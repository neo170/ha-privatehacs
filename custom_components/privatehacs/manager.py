"""Repository catalog and installation orchestration for PrivateHACS."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from homeassistant.core import HomeAssistant
from homeassistant import loader

from .const import DOMAIN, PANEL_ICON_URL_PATH
from .github import GitHubClient, GitHubError
from .installer import ArchiveInstaller, InstallationError
from .models import GitHubRepository, InstalledRepository
from .storage import PrivateHacsStore
from .versioning import is_newer_version

MAX_BRAND_ICON_SIZE = 1 * 1024 * 1024


@dataclass(slots=True)
class PrivateHacsRuntime:
    """Runtime objects for one configured GitHub account."""

    manager: PrivateHacsManager


class PrivateHacsManager:
    """Expose private GitHub integrations as an installable Home Assistant catalog."""

    def __init__(
        self, hass: HomeAssistant, client: GitHubClient, store: PrivateHacsStore
    ) -> None:
        """Initialize a manager for one GitHub account."""
        self._hass = hass
        self._client = client
        self._store = store
        self._installer = ArchiveInstaller(
            Path(hass.config.path("custom_components")), Path(hass.config.path("www"))
        )
        self._icon_cache_path = Path(
            hass.config.path(".storage", f"{DOMAIN}_icons")
        )
        self._install_lock = asyncio.Lock()
        self._restart_required = False

    async def async_get_catalog(self) -> list[dict[str, object]]:
        """Return available private repositories and their installed update state."""
        repositories = [
            repository
            for repository in await self._client.async_list_private_repositories()
            if _is_privatehacs_repository(repository)
        ]
        installed = {record.full_name: record for record in self._store.values()}
        local_versions = await self._hass.async_add_executor_job(
            _get_local_component_versions, self._installer.custom_components_path
        )
        icon_domains = await self._hass.async_add_executor_job(
            _sync_local_component_icons,
            self._installer.custom_components_path,
            self._icon_cache_path,
        )
        semaphore = asyncio.Semaphore(4)

        async def build_item(repository: GitHubRepository) -> dict[str, object]:
            record = installed.get(repository.full_name)
            remote_commit: str | None = None
            remote_versions: dict[str, str | None] = {}
            async with semaphore:
                try:
                    remote_versions = await self._client.async_get_integration_versions(
                        repository.full_name, repository.default_branch
                    )
                except GitHubError:
                    remote_versions = {}
                if record is not None:
                    try:
                        remote_commit = await self._client.async_get_commit_sha(
                            repository.full_name, repository.default_branch
                        )
                    except GitHubError:
                        remote_commit = None

            local_component_versions = {
                domain: local_versions[domain]
                for domain in remote_versions
                if domain in local_versions
            }
            managed_by_privatehacs = record is not None
            managed_externally = bool(local_component_versions) and not managed_by_privatehacs
            version_update_available = any(
                is_newer_version(remote_versions[domain], local_version)
                for domain, local_version in local_component_versions.items()
            )
            domains = tuple(sorted(set(remote_versions) | set(record.domains if record else ())))
            icon_domain = next(
                (domain for domain in domains if domain in icon_domains), None
            )

            return {
                "full_name": repository.full_name,
                "description": repository.description,
                "default_branch": repository.default_branch,
                "html_url": repository.html_url,
                "updated_at": repository.updated_at,
                "archived": repository.archived,
                "installed": managed_by_privatehacs or bool(local_component_versions),
                "managed_by_privatehacs": managed_by_privatehacs,
                "managed_externally": managed_externally,
                "domains": list(domains),
                "lovelace_filename": record.lovelace_filename if record else None,
                "icon_url": (
                    f"{PANEL_ICON_URL_PATH}/{icon_domain}.png"
                    if icon_domain is not None
                    else None
                ),
                "local_versions": local_component_versions,
                "available_versions": remote_versions,
                "installed_at": record.installed_at if record else None,
                "installed_commit": record.commit_sha if record else None,
                "available_commit": remote_commit,
                "update_available": bool(
                    not managed_externally
                    and (
                        version_update_available
                        or (
                            managed_by_privatehacs
                            and remote_commit is not None
                            and record.commit_sha != remote_commit
                        )
                    )
                ),
            }

        return await asyncio.gather(*(build_item(repository) for repository in repositories))

    async def async_install_repository(self, full_name: str) -> dict[str, object]:
        """Install or update all custom components published by one private repository."""
        async with self._install_lock:
            repository = await self._client.async_get_repository(full_name)
            if not _is_privatehacs_repository(repository):
                raise InstallationError("Only repositories whose name starts with ha- are supported.")
            current = self._store.get(repository.full_name)
            commit_sha = await self._client.async_get_commit_sha(
                repository.full_name, repository.default_branch
            )
            archive = await self._client.async_download_archive(
                repository.full_name, commit_sha
            )
            contents = await self._hass.async_add_executor_job(
                self._installer.inspect_archive, archive
            )

            if contents.lovelace_filename is not None:
                if current and current.lovelace_filename is None:
                    raise InstallationError(
                        "Repository changed from a custom integration to a Lovelace card."
                    )
                directory_name = (
                    current.lovelace_directory
                    if current and current.lovelace_directory
                    else _lovelace_directory_name(repository.full_name)
                )
                await self._hass.async_add_executor_job(
                    self._installer.install_lovelace_card,
                    archive,
                    directory_name,
                    current is not None,
                )
                record = InstalledRepository(
                    full_name=repository.full_name,
                    default_branch=repository.default_branch,
                    commit_sha=commit_sha,
                    domains=(),
                    installed_at=datetime.now(UTC).isoformat(),
                    lovelace_filename=contents.lovelace_filename,
                    lovelace_directory=directory_name,
                )
                await self._store.async_upsert(record)
                resource_url = _lovelace_resource_url(
                    directory_name, contents.lovelace_filename, commit_sha
                )
                resource_registered = await _async_upsert_lovelace_resource(
                    self._hass, directory_name, resource_url
                )
                return {
                    "full_name": record.full_name,
                    "domains": [],
                    "commit": record.commit_sha,
                    "lovelace_resource": resource_url,
                    "lovelace_resource_registered": resource_registered,
                    "restart_required": False,
                }

            if current and current.lovelace_filename is not None:
                raise InstallationError(
                    "Repository changed from a Lovelace card to a custom integration."
                )

            installed_domains = self._domain_owners()
            conflicting_domains = {
                domain
                for domain in contents.domains
                if domain in installed_domains and installed_domains[domain] != repository.full_name
            }
            if conflicting_domains:
                raise InstallationError(
                    "Another PrivateHACS repository already manages: "
                    + ", ".join(sorted(conflicting_domains))
                )

            if current and not set(current.domains).issubset(contents.domains):
                raise InstallationError(
                    "Repository no longer contains every component managed by PrivateHACS."
                )

            allowed_existing = set(current.domains) if current else set()
            await self._hass.async_add_executor_job(
                self._installer.install_archive, archive, allowed_existing
            )

            record = InstalledRepository(
                full_name=repository.full_name,
                default_branch=repository.default_branch,
                commit_sha=commit_sha,
                domains=contents.domains,
                installed_at=datetime.now(UTC).isoformat(),
            )
            await self._store.async_upsert(record)
            self._hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
            await loader.async_get_custom_components(self._hass)
            self._restart_required = True

            return {
                "full_name": record.full_name,
                "domains": list(record.domains),
                "commit": record.commit_sha,
                "restart_required": True,
            }

    def _domain_owners(self) -> dict[str, str]:
        """Map each PrivateHACS-managed domain to its owning repository."""
        return {
            domain: record.full_name
            for record in self._store.values()
            for domain in record.domains
        }

    @property
    def installed_repositories(self) -> tuple[InstalledRepository, ...]:
        """Return the repositories that PrivateHACS is allowed to update."""
        return self._store.values()

    @property
    def restart_required(self) -> bool:
        """Return whether this runtime installed integration code awaiting a restart."""
        return self._restart_required

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return diagnostic state without private repository names or credentials."""
        installed_repositories = self._store.values()
        return {
            "repository_query": self._client.repository_query_diagnostics,
            "installed_repository_count": len(installed_repositories),
            "managed_component_count": sum(
                len(repository.domains) for repository in installed_repositories
            ),
        }


def _is_privatehacs_repository(repository: GitHubRepository) -> bool:
    """Return whether a repository follows the PrivateHACS catalog naming rule."""
    return repository.full_name.rsplit("/", maxsplit=1)[-1].lower().startswith("ha-")


def _lovelace_directory_name(full_name: str) -> str:
    """Return a stable, collision-resistant directory for one card repository."""
    repository_name = full_name.rsplit("/", maxsplit=1)[-1].lower()
    safe_name = re.sub(r"[^a-z0-9-]+", "-", repository_name).strip("-")
    digest = hashlib.sha256(full_name.encode("utf-8")).hexdigest()[:12]
    return f"{safe_name}-{digest}"


def _lovelace_resource_url(directory_name: str, filename: str, commit_sha: str) -> str:
    """Return the cache-busted local URL for an installed Lovelace card."""
    return f"/local/privatehacs/{directory_name}/{filename}?v={commit_sha[:12]}"


async def _async_upsert_lovelace_resource(
    hass: HomeAssistant, directory_name: str, resource_url: str
) -> bool:
    """Create or update a storage-mode Lovelace module resource when available."""
    lovelace_data = hass.data.get("lovelace")
    resources = (
        lovelace_data.get("resources")
        if isinstance(lovelace_data, dict)
        else getattr(lovelace_data, "resources", None)
    )
    if resources is None or getattr(resources, "store", None) is None:
        return False

    if not resources.loaded:
        await resources.async_load()

    namespace = f"/local/privatehacs/{directory_name}/"
    for resource in resources.async_items():
        if resource.get("url", "").startswith(namespace):
            if resource["url"] != resource_url:
                await resources.async_update_item(resource["id"], {"url": resource_url})
            return True

    await resources.async_create_item({"res_type": "module", "url": resource_url})
    return True


def _get_local_component_versions(custom_components_path: Path) -> dict[str, str | None]:
    """Read valid local custom component manifest versions from the config directory."""
    if not custom_components_path.is_dir():
        return {}

    versions: dict[str, str | None] = {}
    for manifest_path in custom_components_path.glob("*/manifest.json"):
        domain = manifest_path.parent.name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("domain") != domain:
            continue
        version = manifest.get("version")
        versions[domain] = version if isinstance(version, str) else None
    return versions


def _sync_local_component_icons(
    custom_components_path: Path, icon_cache_path: Path
) -> set[str]:
    """Copy valid local brand icons to the static PrivateHACS cache."""
    icon_cache_path.mkdir(parents=True, exist_ok=True)
    icon_domains: set[str] = set()

    try:
        component_paths = tuple(custom_components_path.iterdir())
    except OSError:
        component_paths = ()

    for component_path in component_paths:
        domain = component_path.name
        icon_path = component_path / "brand" / "icon.png"
        if (
            not component_path.is_dir()
            or not re.fullmatch(r"[a-z0-9_]+", domain)
            or icon_path.is_symlink()
        ):
            continue
        try:
            if not icon_path.is_file() or icon_path.stat().st_size > MAX_BRAND_ICON_SIZE:
                continue
            destination = icon_cache_path / f"{domain}.png"
            temporary = destination.with_suffix(".tmp")
            shutil.copyfile(icon_path, temporary)
            os.replace(temporary, destination)
        except OSError:
            continue
        icon_domains.add(domain)

    for cached_icon in icon_cache_path.glob("*.png"):
        if cached_icon.stem not in icon_domains:
            try:
                cached_icon.unlink()
            except OSError:
                continue

    return icon_domains