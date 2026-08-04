"""Runtime registration of the PrivateHACS sidebar panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import (
    async_panel_exists,
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DATA_PANEL_STATIC_REGISTERED,
    DOMAIN,
    PANEL_COMPONENT_NAME,
    PANEL_MODULE_URL,
    PANEL_URL_PATH,
)


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve and register the admin-only PrivateHACS panel."""
    domain_data = hass.data[DOMAIN]
    if not domain_data.get(DATA_PANEL_STATIC_REGISTERED):
        frontend_path = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(f"/{DOMAIN}_static", str(frontend_path), False)]
        )
        domain_data[DATA_PANEL_STATIC_REGISTERED] = True

    if async_panel_exists(hass, PANEL_URL_PATH):
        return

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="PrivateHACS",
        sidebar_icon="mdi:github",
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_COMPONENT_NAME,
                "module_url": PANEL_MODULE_URL,
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=True,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar item when no PrivateHACS account remains."""
    if async_panel_exists(hass, PANEL_URL_PATH):
        async_remove_panel(hass, PANEL_URL_PATH)