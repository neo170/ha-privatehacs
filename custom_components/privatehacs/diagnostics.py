"""Diagnostics support for PrivateHACS."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_RUNTIMES, DOMAIN
from .manager import PrivateHacsRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for one PrivateHACS config entry."""
    runtimes: dict[str, PrivateHacsRuntime] = hass.data.get(DOMAIN, {}).get(
        DATA_RUNTIMES, {}
    )
    runtime = runtimes.get(entry.entry_id)
    return {
        "runtime_loaded": runtime is not None,
        "catalog": runtime.manager.diagnostics if runtime else None,
    }