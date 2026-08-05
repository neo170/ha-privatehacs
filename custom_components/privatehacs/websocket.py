"""WebSocket API consumed by the PrivateHACS sidebar panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import (
    DATA_RUNTIMES,
    DATA_WEBSOCKET_REGISTERED,
    DOMAIN,
    WS_INSTALL_REPOSITORY,
    WS_LIST_REPOSITORIES,
    WS_UNINSTALL_REPOSITORY,
)
from .github import GitHubError
from .installer import InstallationError
from .manager import PrivateHacsManager, PrivateHacsRuntime


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the commands once for the Home Assistant process."""
    domain_data = hass.data[DOMAIN]
    if domain_data.get(DATA_WEBSOCKET_REGISTERED):
        return
    websocket_api.async_register_command(hass, websocket_list_repositories)
    websocket_api.async_register_command(hass, websocket_install_repository)
    websocket_api.async_register_command(hass, websocket_uninstall_repository)
    domain_data[DATA_WEBSOCKET_REGISTERED] = True


def _manager(hass: HomeAssistant) -> PrivateHacsManager | None:
    """Return the single configured PrivateHACS manager."""
    runtimes: dict[str, PrivateHacsRuntime] = hass.data.get(DOMAIN, {}).get(
        DATA_RUNTIMES, {}
    )
    return next((runtime.manager for runtime in runtimes.values()), None)


def _not_configured(connection: websocket_api.ActiveConnection, message_id: int) -> None:
    """Send a consistent error if the config entry is not loaded."""
    connection.send_error(message_id, "not_configured", "PrivateHACS is not configured.")


@websocket_api.websocket_command({vol.Required("type"): WS_LIST_REPOSITORIES})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_list_repositories(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return GitHub private repositories and their installation state."""
    manager = _manager(hass)
    if manager is None:
        _not_configured(connection, msg["id"])
        return

    try:
        repositories = await manager.async_get_catalog()
    except GitHubError as err:
        connection.send_error(msg["id"], "github_error", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "repositories": repositories,
            "restart_required": manager.restart_required,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_INSTALL_REPOSITORY,
        vol.Required("repository"): str,
        vol.Optional("take_over"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_install_repository(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Install or update one private repository."""
    manager = _manager(hass)
    if manager is None:
        _not_configured(connection, msg["id"])
        return

    try:
        result = await manager.async_install_repository(
            msg["repository"], take_over=msg.get("take_over", False)
        )
    except (GitHubError, InstallationError) as err:
        connection.send_error(msg["id"], "install_failed", str(err))
        return

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): WS_UNINSTALL_REPOSITORY, vol.Required("repository"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_uninstall_repository(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove one PrivateHACS-managed repository."""
    manager = _manager(hass)
    if manager is None:
        _not_configured(connection, msg["id"])
        return

    try:
        result = await manager.async_uninstall_repository(msg["repository"])
    except InstallationError as err:
        connection.send_error(msg["id"], "uninstall_failed", str(err))
        return

    connection.send_result(msg["id"], result)