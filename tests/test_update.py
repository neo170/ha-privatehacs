"""Focused tests for PrivateHACS Home Assistant update entities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import IntFlag
import importlib.util
from pathlib import Path
import sys
import types


def _load_update_module():
    root = Path(__file__).parents[1] / "custom_components" / "privatehacs"
    package_name = "privatehacs_update_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")
    homeassistant.components = components
    homeassistant.helpers = helpers
    persistent_notification = types.ModuleType(
        "homeassistant.components.persistent_notification"
    )
    persistent_notification.notifications = []
    persistent_notification.async_create = lambda *args, **kwargs: (
        persistent_notification.notifications.append((args, kwargs))
    )
    update = types.ModuleType("homeassistant.components.update")

    class UpdateEntity:
        pass

    class UpdateEntityFeature(IntFlag):
        INSTALL = 1

    update.UpdateEntity = UpdateEntity
    update.UpdateEntityFeature = UpdateEntityFeature
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return self.coordinator.last_update_success

    class DataUpdateCoordinator:
        pass

    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    helpers.entity_platform = entity_platform
    helpers.update_coordinator = update_coordinator
    manager = types.ModuleType(f"{package_name}.manager")
    manager.PrivateHacsManager = object
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.helpers": helpers,
            "homeassistant.components.persistent_notification": persistent_notification,
            "homeassistant.components.update": update,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.exceptions": exceptions,
            "homeassistant.helpers.entity_platform": entity_platform,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            manager.__name__: manager,
        }
    )

    for name in ("const", "models", "update"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}", root / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

    return sys.modules[f"{package_name}.update"], persistent_notification


update_module, notifications = _load_update_module()
InstalledRepository = update_module.InstalledRepository
PrivateHacsRepositoryUpdateEntity = update_module.PrivateHacsRepositoryUpdateEntity


@dataclass
class _Coordinator:
    data: list[dict[str, object]]
    last_update_success: bool = True
    refreshes: int = 0

    async def async_request_refresh(self) -> None:
        self.refreshes += 1


class _Manager:
    async def async_install_repository(self, full_name: str) -> dict[str, object]:
        self.installed = full_name
        return {"commit": "fedcba9876543210"}


def test_update_entity_exposes_and_installs_a_github_revision() -> None:
    """The update page gets the catalog state and can install its update."""
    record = InstalledRepository(
        full_name="owner/ha-example",
        default_branch="main",
        commit_sha="0123456789abcdef",
        domains=("example",),
        installed_at="2026-08-05T00:00:00+00:00",
    )
    coordinator = _Coordinator(
        [
            {
                "full_name": record.full_name,
                "available_commit": "fedcba9876543210",
                "update_available": True,
                "html_url": "https://github.test/owner/ha-example",
            }
        ]
    )
    manager = _Manager()
    entity = PrivateHacsRepositoryUpdateEntity("entry", manager, coordinator, record)
    entity.hass = object()

    assert entity.available is True
    assert entity.installed_version == "0123456789ab"
    assert entity.latest_version == "fedcba987654"
    assert entity.version_is_newer(entity.latest_version, entity.installed_version)

    asyncio.run(entity.async_install(None, False))

    assert manager.installed == record.full_name
    assert entity.installed_version == "fedcba987654"
    assert coordinator.refreshes == 1
    assert "Restart Home Assistant" in notifications.notifications[-1][0][1]