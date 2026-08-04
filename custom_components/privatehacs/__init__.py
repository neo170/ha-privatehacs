"""PrivateHACS integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_GITHUB_TOKEN,
    CONF_GITHUB_USERNAME,
    DATA_RUNTIMES,
    DOMAIN,
)
from .frontend import async_register_panel, async_unregister_panel
from .github import GitHubClient
from .manager import PrivateHacsManager, PrivateHacsRuntime
from .storage import PrivateHacsStore
from .websocket import async_register_websocket_commands

PLATFORMS: list[Platform] = [Platform.UPDATE]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up PrivateHACS without YAML configuration."""
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PrivateHACS from a config entry."""
    store = PrivateHacsStore(hass)
    await store.async_load()

    client = GitHubClient(
        async_get_clientsession(hass),
        entry.data[CONF_GITHUB_USERNAME],
        entry.data[CONF_GITHUB_TOKEN],
    )
    manager = PrivateHacsManager(hass, client, store)
    runtimes: dict[str, PrivateHacsRuntime] = hass.data[DOMAIN].setdefault(
        DATA_RUNTIMES, {}
    )
    runtimes[entry.entry_id] = PrivateHacsRuntime(manager)

    await async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a PrivateHACS config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    runtimes: dict[str, PrivateHacsRuntime] = hass.data[DOMAIN].get(
        DATA_RUNTIMES, {}
    )
    runtimes.pop(entry.entry_id, None)

    if not runtimes:
        async_unregister_panel(hass)

    return True