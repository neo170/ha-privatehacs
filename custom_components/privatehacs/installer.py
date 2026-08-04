"""Secure archive installation for PrivateHACS repositories."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from zipfile import BadZipFile, ZipFile, ZipInfo

MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_SIZE = 250 * 1024 * 1024


class InstallationError(Exception):
    """An archive cannot be safely installed as a Home Assistant integration."""


@dataclass(frozen=True, slots=True)
class ArchiveContents:
    """Validated integration domains contained in an archive."""

    domains: tuple[str, ...]


class ArchiveInstaller:
    """Extract only valid custom components and replace them atomically."""

    def __init__(self, custom_components_path: Path) -> None:
        """Initialize the installer for Home Assistant's custom components directory."""
        self._custom_components_path = custom_components_path

    @property
    def custom_components_path(self) -> Path:
        """Return Home Assistant's custom components directory."""
        return self._custom_components_path

    def inspect_archive(self, archive: bytes) -> ArchiveContents:
        """Validate the archive and list the integration domains it contains."""
        try:
            with ZipFile(io.BytesIO(archive)) as zip_file:
                components = self._collect_components(zip_file)
        except BadZipFile as err:
            raise InstallationError("GitHub returned an invalid ZIP archive.") from err

        return ArchiveContents(domains=tuple(sorted(components)))

    def install_archive(
        self, archive: bytes, allowed_existing_domains: set[str]
    ) -> ArchiveContents:
        """Install a validated archive and preserve previous files on failure."""
        try:
            with ZipFile(io.BytesIO(archive)) as zip_file:
                components = self._collect_components(zip_file)
                self._install_components(zip_file, components, allowed_existing_domains)
        except BadZipFile as err:
            raise InstallationError("GitHub returned an invalid ZIP archive.") from err

        return ArchiveContents(domains=tuple(sorted(components)))

    def _collect_components(self, zip_file: ZipFile) -> dict[str, list[ZipInfo]]:
        """Find safe custom-component paths in an archive."""
        members = zip_file.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise InstallationError("Archive contains too many files.")
        if sum(member.file_size for member in members) > MAX_ARCHIVE_SIZE:
            raise InstallationError("Archive is too large to install safely.")

        components: dict[str, list[ZipInfo]] = {}
        for member in members:
            domain = self._component_domain(member)
            if domain is not None:
                components.setdefault(domain, []).append(member)

        if not components:
            raise InstallationError(
                "Repository does not contain custom_components/<domain>/manifest.json."
            )

        manifest_names = {
            self._component_path(member)
            for members in components.values()
            for member in members
            if self._component_path(member) is not None
            and self._component_path(member)[1] == ("manifest.json",)
        }
        missing_manifest = set(components) - {domain for domain, _ in manifest_names}
        if missing_manifest:
            raise InstallationError(
                "Each installed component must include a manifest.json file."
            )

        return components

    def _component_domain(self, member: ZipInfo) -> str | None:
        """Return a custom integration domain for a safe archive member."""
        component_path = self._component_path(member)
        return component_path[0] if component_path is not None else None

    def _component_path(self, member: ZipInfo) -> tuple[str, tuple[str, ...]] | None:
        """Return domain and relative path when a ZIP member is installable."""
        name = member.filename
        if name.startswith(("/", "\\")) or "\\" in name:
            raise InstallationError("Archive contains an unsafe path.")

        parts = tuple(part for part in name.split("/") if part)
        if any(part in {".", ".."} for part in parts):
            raise InstallationError("Archive contains an unsafe path.")
        if stat.S_ISLNK(member.external_attr >> 16):
            raise InstallationError("Archive contains unsupported symbolic links.")

        try:
            component_index = parts.index("custom_components")
        except ValueError:
            return None

        if component_index > 1 or len(parts) < component_index + 2:
            return None

        domain = parts[component_index + 1]
        if not domain.replace("_", "").isalnum() or domain.lower() != domain:
            raise InstallationError("Archive contains an invalid integration domain.")

        return domain, parts[component_index + 2 :]

    def _install_components(
        self,
        zip_file: ZipFile,
        components: dict[str, list[ZipInfo]],
        allowed_existing_domains: set[str],
    ) -> None:
        """Stage archive files and atomically exchange target component folders."""
        self._custom_components_path.mkdir(parents=True, exist_ok=True)
        workspace = Path(
            tempfile.mkdtemp(prefix=".privatehacs-", dir=self._custom_components_path)
        )
        staging_root = workspace / "staging"
        backups_root = workspace / "backups"

        try:
            for domain, members in components.items():
                for member in members:
                    component_path = self._component_path(member)
                    if component_path is None:
                        continue
                    _, relative_path = component_path
                    if not relative_path:
                        continue

                    destination = staging_root / domain / Path(*relative_path)
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue

                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zip_file.open(member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)

            for domain in components:
                self._validate_manifest(staging_root / domain / "manifest.json", domain)

            self._replace_components(
                staging_root, backups_root, set(components), allowed_existing_domains
            )
        except OSError as err:
            raise InstallationError("Could not write the integration to custom_components.") from err
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _validate_manifest(self, manifest_path: Path, domain: str) -> None:
        """Ensure the staged manifest belongs to the directory it will occupy."""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            raise InstallationError(f"Component {domain} has an invalid manifest.json.") from err

        if not isinstance(manifest, dict) or manifest.get("domain") != domain:
            raise InstallationError(
                f"Component {domain} has a manifest with a different domain."
            )

    def _replace_components(
        self,
        staging_root: Path,
        backups_root: Path,
        domains: set[str],
        allowed_existing_domains: set[str],
    ) -> None:
        """Replace component directories, restoring all originals if any swap fails."""
        for domain in domains:
            destination = self._custom_components_path / domain
            if destination.exists() and not destination.is_dir():
                raise InstallationError(f"Target path for {domain} is not a directory.")
            if destination.exists() and domain not in allowed_existing_domains:
                raise InstallationError(
                    f"Component {domain} is already managed outside PrivateHACS."
                )

        backups: dict[str, Path] = {}
        installed: list[str] = []
        try:
            for domain in sorted(domains):
                destination = self._custom_components_path / domain
                if destination.exists():
                    backup = backups_root / domain
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, backup)
                    backups[domain] = backup

                os.replace(staging_root / domain, destination)
                installed.append(domain)
        except OSError as err:
            for domain in installed:
                destination = self._custom_components_path / domain
                if destination.exists():
                    shutil.rmtree(destination)
            for domain, backup in backups.items():
                if backup.exists():
                    os.replace(backup, self._custom_components_path / domain)
            raise InstallationError("Could not replace the previous integration version.") from err