"""Repository catalog and installation orchestration for PrivateHACS."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant import loader

from .github import GitHubClient, GitHubError
from .installer import ArchiveInstaller, InstallationError
from .models import GitHubRepository, InstalledRepository
from .storage import PrivateHacsStore
from .versioning import is_newer_version


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
        self._installer = ArchiveInstaller(Path(hass.config.path("custom_components")))
        self._install_lock = asyncio.Lock()

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