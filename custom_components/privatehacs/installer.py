"""Secure archive installation for PrivateHACS repositories."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from zipfile import BadZipFile, ZipFile, ZipInfo

MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_SIZE = 250 * 1024 * 1024
MAX_LOVELACE_ASSET_SIZE = 10 * 1024 * 1024
_LOVELACE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.js")


class InstallationError(Exception):
    """An archive cannot be safely installed as a Home Assistant integration."""


@dataclass(frozen=True, slots=True)
class ArchiveContents:
    """Validated integration domains contained in an archive."""

    domains: tuple[str, ...]
    lovelace_filename: str | None = None


class ArchiveInstaller:
    """Extract only valid custom components and replace them atomically."""

    def __init__(self, custom_components_path: Path, www_path: Path | None = None) -> None:
        """Initialize the installer for Home Assistant's custom components directory."""
        self._custom_components_path = custom_components_path
        self._www_path = www_path or custom_components_path.parent / "www"

    @property
    def custom_components_path(self) -> Path:
        """Return Home Assistant's custom components directory."""
        return self._custom_components_path

    def inspect_archive(self, archive: bytes) -> ArchiveContents:
        """Validate the archive and list the integration domains it contains."""
        try:
            with ZipFile(io.BytesIO(archive)) as zip_file:
                components = self._collect_components(zip_file)
                lovelace_filename = (
                    None if components else self._get_lovelace_filename(zip_file)
                )
        except BadZipFile as err:
            raise InstallationError("GitHub returned an invalid ZIP archive.") from err

        if not components and lovelace_filename is None:
            raise InstallationError(
                "Repository does not contain custom_components/<domain>/manifest.json "
                "or a Lovelace card declared in hacs.json."
            )

        return ArchiveContents(
            domains=tuple(sorted(components)), lovelace_filename=lovelace_filename
        )

    def install_archive(
        self, archive: bytes, allowed_existing_domains: set[str]
    ) -> ArchiveContents:
        """Install a validated archive and preserve previous files on failure."""
        try:
            with ZipFile(io.BytesIO(archive)) as zip_file:
                components = self._collect_components(zip_file)
                if not components:
                    raise InstallationError(
                        "Repository does not contain custom_components/<domain>/manifest.json."
                    )
                self._install_components(zip_file, components, allowed_existing_domains)
        except BadZipFile as err:
            raise InstallationError("GitHub returned an invalid ZIP archive.") from err

        return ArchiveContents(domains=tuple(sorted(components)))

    def install_lovelace_card(
        self, archive: bytes, directory_name: str, allow_existing: bool
    ) -> ArchiveContents:
        """Install a hacs.json-declared Lovelace JavaScript card atomically."""
        if not re.fullmatch(r"[a-z0-9-]+", directory_name):
            raise InstallationError("Lovelace card has an invalid installation path.")

        try:
            with ZipFile(io.BytesIO(archive)) as zip_file:
                asset = self._get_lovelace_asset(zip_file)
                if asset is None:
                    raise InstallationError(
                        "Repository does not declare a Lovelace card in hacs.json."
                    )
                filename, asset_member = asset
                self._install_lovelace_card(
                    zip_file, filename, asset_member, directory_name, allow_existing
                )
        except BadZipFile as err:
            raise InstallationError("GitHub returned an invalid ZIP archive.") from err

        return ArchiveContents(domains=(), lovelace_filename=filename)

    def uninstall_components(self, domains: tuple[str, ...]) -> None:
        """Remove only validated component directories managed by PrivateHACS."""
        if not domains or any(not re.fullmatch(r"[a-z0-9_]+", domain) for domain in domains):
            raise InstallationError("Integration has an invalid component path.")
        self._remove_directories(self._custom_components_path, domains)

    def uninstall_lovelace_card(self, directory_name: str) -> None:
        """Remove one PrivateHACS-managed Lovelace card directory."""
        if not re.fullmatch(r"[a-z0-9-]+", directory_name):
            raise InstallationError("Lovelace card has an invalid installation path.")
        self._remove_directories(self._www_path / "privatehacs", (directory_name,))

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

    def _get_lovelace_filename(self, zip_file: ZipFile) -> str | None:
        """Return the declared card asset when a HACS frontend layout is valid."""
        asset = self._get_lovelace_asset(zip_file)
        return asset[0] if asset is not None else None

    def _get_lovelace_asset(
        self, zip_file: ZipFile
    ) -> tuple[str, ZipInfo] | None:
        """Return the filename and exact archive member selected by hacs.json."""
        hacs_member: ZipInfo | None = None
        root: tuple[str, ...] | None = None
        for member in zip_file.infolist():
            parts = self._member_parts(member)
            if (
                not member.is_dir()
                and parts[-1:] == ("hacs.json",)
                and len(parts) in (1, 2)
            ):
                hacs_member = member
                root = parts[:-1]
                break

        if hacs_member is None or root is None or hacs_member.file_size > 64 * 1024:
            return None

        try:
            manifest = json.loads(zip_file.read(hacs_member).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(manifest, dict):
            return None

        filename = manifest.get("filename")
        content_in_root = manifest.get("content_in_root", False)
        if (
            not isinstance(filename, str)
            or _LOVELACE_FILENAME.fullmatch(filename) is None
            or not isinstance(content_in_root, bool)
        ):
            return None

        expected_path = root + (() if content_in_root else ("dist",)) + (filename,)
        for member in zip_file.infolist():
            if self._member_parts(member) != expected_path or member.is_dir():
                continue
            if member.file_size > MAX_LOVELACE_ASSET_SIZE:
                raise InstallationError("Lovelace card asset is too large.")
            return filename, member
        return None

    def _component_domain(self, member: ZipInfo) -> str | None:
        """Return a custom integration domain for a safe archive member."""
        component_path = self._component_path(member)
        return component_path[0] if component_path is not None else None

    def _component_path(self, member: ZipInfo) -> tuple[str, tuple[str, ...]] | None:
        """Return domain and relative path when a ZIP member is installable."""
        parts = self._member_parts(member)

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

    @staticmethod
    def _member_parts(member: ZipInfo) -> tuple[str, ...]:
        """Validate and return an archive member path."""
        name = member.filename
        if name.startswith(("/", "\\")) or "\\" in name:
            raise InstallationError("Archive contains an unsafe path.")

        parts = tuple(part for part in name.split("/") if part)
        if not parts or any(part in {".", ".."} for part in parts):
            raise InstallationError("Archive contains an unsafe path.")
        if stat.S_ISLNK(member.external_attr >> 16):
            raise InstallationError("Archive contains unsupported symbolic links.")
        return parts

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
                    f"Component {domain} is already installed outside PrivateHACS. "
                    "Remove it in HACS or delete it manually before installing it "
                    "with PrivateHACS."
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

    @staticmethod
    def _remove_directories(root: Path, names: tuple[str, ...]) -> None:
        """Move target directories aside before permanently deleting them."""
        if not root.is_dir():
            return

        targets: list[tuple[str, Path]] = []
        for name in sorted(set(names)):
            target = root / name
            if not target.exists():
                continue
            if target.is_symlink() or not target.is_dir():
                raise InstallationError(f"Target path for {name} is not a directory.")
            targets.append((name, target))

        if not targets:
            return

        workspace = Path(tempfile.mkdtemp(prefix=".privatehacs-", dir=root))
        removed_root = workspace / "removed"
        moved: list[tuple[Path, Path]] = []
        try:
            for name, target in targets:
                backup = removed_root / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                moved.append((target, backup))
        except OSError as err:
            for target, backup in reversed(moved):
                if backup.exists():
                    os.replace(backup, target)
            raise InstallationError("Could not remove the installed files.") from err
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _install_lovelace_card(
        self,
        zip_file: ZipFile,
        filename: str,
        asset_member: ZipInfo,
        directory_name: str,
        allow_existing: bool,
    ) -> None:
        """Stage and exchange the validated card directory without partial writes."""
        cards_path = self._www_path / "privatehacs"
        cards_path.mkdir(parents=True, exist_ok=True)
        destination = cards_path / directory_name
        if destination.exists() and not destination.is_dir():
            raise InstallationError("Lovelace card target path is not a directory.")
        if destination.exists() and not allow_existing:
            raise InstallationError(
                "Lovelace card is already installed outside PrivateHACS."
            )

        workspace = Path(tempfile.mkdtemp(prefix=".privatehacs-", dir=cards_path))
        staged_directory = workspace / "staging"
        backup_directory = workspace / "backup"
        try:
            staged_directory.mkdir()
            with zip_file.open(asset_member) as source, (staged_directory / filename).open(
                "wb"
            ) as target:
                shutil.copyfileobj(source, target)

            if destination.exists():
                os.replace(destination, backup_directory)
            os.replace(staged_directory, destination)
        except OSError as err:
            if not destination.exists() and backup_directory.exists():
                os.replace(backup_directory, destination)
            raise InstallationError("Could not write the Lovelace card to www.") from err
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
