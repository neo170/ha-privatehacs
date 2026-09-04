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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DATA_RUNTIMES, DOMAIN, SIGNAL_REPOSITORIES_CHANGED
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
        update_method=lambda: manager.async_get_catalog(force_refresh=True),
        update_interval=SCAN_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    def refresh_update_entities() -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_REPOSITORIES_CHANGED, refresh_update_entities
        )
    )
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
        """Return the release tag that was installed by PrivateHACS."""
        repository = self._catalog_entry
        version = repository.get("installed_version") if repository else None
        return version if isinstance(version, str) and version else "unversioned"

    @property
    def latest_version(self) -> str | None:
        """Return the latest published GitHub release tag."""
        repository = self._catalog_entry
        if repository is None:
            return None

        version = repository.get("available_version")
        if repository.get("update_available") and isinstance(version, str) and version:
            return version
        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the GitHub page for the available release."""
        repository = self._catalog_entry
        html_url = repository.get("release_url") if repository else None
        return html_url if isinstance(html_url, str) else None

    @property
    def release_summary(self) -> str | None:
        """Provide a concise description for the Home Assistant update dialog."""
        if self.latest_version == self.installed_version:
            return None
        return (
            f"Update to GitHub release {self.latest_version}. Optionally reload "
            "configured entries in PrivateHACS, or restart Home Assistant."
        )

    def version_is_newer(
        self, latest_version: str, installed_version: str
    ) -> bool:
        """Use PrivateHACS' release comparison result."""
        repository = self._catalog_entry
        return bool(repository and repository.get("update_available"))

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the latest published GitHub release of this repository."""
        if version is not None:
            raise HomeAssistantError("PrivateHACS only installs the current default branch.")

        result = await self._manager.async_install_repository(self._record.full_name)
        release_tag = result.get("version")
        if isinstance(release_tag, str) and release_tag:
            self._record = replace(self._record, release_tag=release_tag)

        persistent_notification.async_create(
            self.hass,
            _update_completion_message(self._record.full_name, result),
            title="PrivateHACS installation complete",
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


def _update_completion_message(full_name: str, result: dict[str, object]) -> str:
    """Return the appropriate post-update instruction for installed content."""
    release_tag = result.get("version")
    release = (
        f" from GitHub release {release_tag}"
        if isinstance(release_tag, str) and release_tag
        else ""
    )
    if result.get("lovelace_resource"):
        return (
            f"PrivateHACS updated the Lovelace card {full_name}{release}. "
            "Reload the dashboard to load the new card code."
        )
    return (
        f"PrivateHACS installed {full_name}{release}. "
        "Optionally reload configured entries in PrivateHACS, or restart Home Assistant."
    )