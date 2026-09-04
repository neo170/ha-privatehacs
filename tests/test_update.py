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
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")

    def async_dispatcher_connect(hass, signal, target):
        callbacks = hass.dispatcher_callbacks.setdefault(signal, [])
        callbacks.append(target)

        def unsubscribe() -> None:
            callbacks.remove(target)

        return unsubscribe

    class CoordinatorEntity:
        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return self.coordinator.last_update_success

    class DataUpdateCoordinator:
        instances = []

        def __init__(self, _, __, *, update_method, **___) -> None:
            self.data = []
            self.last_update_success = True
            self.refreshes = 0
            self._update_method = update_method
            self.instances.append(self)

        async def async_config_entry_first_refresh(self) -> None:
            self.data = await self._update_method()

        async def async_request_refresh(self) -> None:
            self.refreshes += 1
            self.data = await self._update_method()

    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    helpers.entity_platform = entity_platform
    helpers.update_coordinator = update_coordinator
    helpers.dispatcher = dispatcher
    dispatcher.async_dispatcher_connect = async_dispatcher_connect
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
            "homeassistant.helpers.dispatcher": dispatcher,
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
        return {"version": "1.1.0"}


class _SetupManager:
    installed_repositories = ()

    def __init__(self) -> None:
        self.catalog_requests = 0

    async def async_get_catalog(self, *, force_refresh: bool) -> list[dict[str, object]]:
        assert force_refresh is True
        self.catalog_requests += 1
        return []


class _SetupHass:
    def __init__(self, manager) -> None:
        self.data = {
            update_module.DOMAIN: {
                update_module.DATA_RUNTIMES: {
                    "entry": types.SimpleNamespace(manager=manager)
                }
            }
        }
        self.dispatcher_callbacks: dict[str, list] = {}
        self.tasks = []

    def async_create_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task


class _SetupEntry:
    entry_id = "entry"

    def __init__(self) -> None:
        self.unload_callbacks = []

    def async_on_unload(self, callback) -> None:
        self.unload_callbacks.append(callback)


def test_repository_change_refreshes_update_entities() -> None:
    """Panel changes refresh the update coordinator without waiting for polling."""
    manager = _SetupManager()
    hass = _SetupHass(manager)
    entry = _SetupEntry()
    created_before = len(update_module.DataUpdateCoordinator.instances)

    async def run() -> None:
        await update_module.async_setup_entry(hass, entry, lambda entities: list(entities))
        callback = hass.dispatcher_callbacks[
            update_module.SIGNAL_REPOSITORIES_CHANGED
        ][0]
        callback()
        await asyncio.gather(*hass.tasks)

    asyncio.run(run())

    coordinator = update_module.DataUpdateCoordinator.instances[created_before]
    assert manager.catalog_requests == 2
    assert coordinator.refreshes == 1
    assert len(entry.unload_callbacks) == 1


def test_update_entity_exposes_and_installs_a_github_revision() -> None:
    """The update page gets the catalog state and can install its update."""
    record = InstalledRepository(
        full_name="owner/ha-example",
        default_branch="main",
        commit_sha="0123456789abcdef",
        domains=("example",),
        installed_at="2026-08-05T00:00:00+00:00",
        release_tag="1.0.0",
    )
    coordinator = _Coordinator(
        [
            {
                "full_name": record.full_name,
                "update_available": True,
                "installed_version": "1.0.0",
                "available_version": "1.1.0",
                "release_url": "https://github.test/owner/ha-example/releases/tag/1.1.0",
            }
        ]
    )
    manager = _Manager()
    entity = PrivateHacsRepositoryUpdateEntity("entry", manager, coordinator, record)
    entity.hass = object()

    assert entity.available is True
    assert entity.installed_version == "1.0.0"
    assert entity.latest_version == "1.1.0"
    assert entity.version_is_newer(entity.latest_version, entity.installed_version)
    assert entity.release_url.endswith("/releases/tag/1.1.0")

    asyncio.run(entity.async_install(None, False))

    assert manager.installed == record.full_name
    assert coordinator.refreshes == 1
    assert "GitHub release 1.1.0" in notifications.notifications[-1][0][1]


def test_update_entity_offers_a_release_for_a_legacy_installation() -> None:
    """A commit-based legacy record is upgraded to the latest release tag."""
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
                "update_available": True,
                "installed_version": None,
                "available_version": "1.0.0",
                "release_url": "https://github.test/owner/ha-example/releases/tag/1.0.0",
            }
        ]
    )
    entity = PrivateHacsRepositoryUpdateEntity("entry", _Manager(), coordinator, record)

    assert entity.installed_version == "unversioned"
    assert entity.latest_version == "1.0.0"