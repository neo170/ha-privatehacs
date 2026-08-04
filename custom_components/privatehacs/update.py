"""Home Assistant update entities for PrivateHACS-managed repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DATA_RUNTIMES, DOMAIN
from .manager import PrivateHacsManager
from .models import InstalledRepository

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an update entity for every managed private repository."""
    manager = hass.data[DOMAIN][DATA_RUNTIMES][entry.entry_id].manager
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}_updates",
        update_method=manager.async_get_catalog,
        update_interval=SCAN_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()
    async_add_entities(
        PrivateHacsRepositoryUpdateEntity(entry.entry_id, manager, coordinator, record)
        for record in manager.installed_repositories
    )


class PrivateHacsRepositoryUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Represent one PrivateHACS-managed GitHub repository as an update."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:github"
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(
        self,
        entry_id: str,
        manager: PrivateHacsManager,
        coordinator: DataUpdateCoordinator,
        record: InstalledRepository,
    ) -> None:
        """Initialize the repository update entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._manager = manager
        self._record = record
        self._attr_name = record.full_name.rsplit("/", maxsplit=1)[-1]
        self._attr_title = record.full_name
        self._attr_unique_id = f"{entry_id}_{record.full_name}"

    @property
    def available(self) -> bool:
        """Return whether the repository remains available to the configured PAT."""
        return super().available and self._catalog_entry is not None

    @property
    def installed_version(self) -> str:
        """Return the commit currently installed by PrivateHACS."""
        return _short_revision(self._record.commit_sha)

    @property
    def latest_version(self) -> str | None:
        """Return the available commit, or a manifest fallback when necessary."""
        repository = self._catalog_entry
        if repository is None:
            return None

        if not repository.get("update_available"):
            return self.installed_version

        available_commit = repository.get("available_commit")
        if isinstance(available_commit, str) and available_commit:
            return _short_revision(available_commit)

        return _manifest_version_marker(repository.get("available_versions"))

    @property
    def release_url(self) -> str | None:
        """Return the GitHub repository where the available revision is published."""
        repository = self._catalog_entry
        html_url = repository.get("html_url") if repository else None
        return html_url if isinstance(html_url, str) else None

    @property
    def release_summary(self) -> str | None:
        """Provide a concise description for the Home Assistant update dialog."""
        if self.latest_version == self.installed_version:
            return None
        return "Update from the configured GitHub default branch. Restart Home Assistant after installation."

    def version_is_newer(
        self, latest_version: str, installed_version: str
    ) -> bool:
        """Use PrivateHACS' commit and manifest comparison result."""
        repository = self._catalog_entry
        return bool(repository and repository.get("update_available"))

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the current default-branch revision of this repository."""
        if version is not None:
            raise HomeAssistantError("PrivateHACS only installs the current default branch.")

        result = await self._manager.async_install_repository(self._record.full_name)
        commit = result.get("commit")
        if isinstance(commit, str) and commit:
            self._record = replace(self._record, commit_sha=commit)

        persistent_notification.async_create(
            self.hass,
            (
                f"PrivateHACS installed {self._record.full_name}. "
                "Restart Home Assistant to load the integration code."
            ),
            title="PrivateHACS restart required",
            notification_id=(
                f"{DOMAIN}_restart_{self._entry_id}_"
                f"{self._record.full_name.replace('/', '_')}"
            ),
        )
        await self.coordinator.async_request_refresh()

    @property
    def _catalog_entry(self) -> dict[str, object] | None:
        """Return this repository's cached catalog state without network I/O."""
        return next(
            (
                repository
                for repository in self.coordinator.data or []
                if repository.get("full_name") == self._record.full_name
            ),
            None,
        )


def _short_revision(commit: str) -> str:
    """Format a Git commit for Home Assistant's version display."""
    return commit[:12]


def _manifest_version_marker(available_versions: object) -> str:
    """Return a distinct update marker when GitHub's commit endpoint failed."""
    if not isinstance(available_versions, dict):
        return "new manifest version"

    versions = [
        f"{domain}={version or '?'}"
        for domain, version in sorted(available_versions.items())
        if isinstance(domain, str) and (isinstance(version, str) or version is None)
    ]
    return "manifest " + ", ".join(versions) if versions else "new manifest version"