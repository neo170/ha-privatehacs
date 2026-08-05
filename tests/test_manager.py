"""Focused catalog tests for PrivateHACS ownership rules."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types


def _load_manager_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    homeassistant.loader = types.ModuleType("homeassistant.loader")
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.loader", homeassistant.loader)

    root = Path(__file__).parents[1] / "custom_components" / "privatehacs"
    package_name = "privatehacs_manager_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    installer = types.ModuleType(f"{package_name}.installer")

    class ArchiveInstaller:
        def __init__(
            self, custom_components_path: Path, www_path: Path | None = None
        ) -> None:
            self.custom_components_path = custom_components_path

    installer.ArchiveInstaller = ArchiveInstaller
    installer.InstallationError = RuntimeError
    sys.modules[installer.__name__] = installer

    github = types.ModuleType(f"{package_name}.github")
    github.GitHubClient = object
    github.GitHubError = RuntimeError
    sys.modules[github.__name__] = github

    storage = types.ModuleType(f"{package_name}.storage")
    storage.PrivateHacsStore = object
    sys.modules[storage.__name__] = storage

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.manager", root / "manager.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


manager_module = _load_manager_module()
GitHubRepository = manager_module.GitHubRepository
PrivateHacsManager = manager_module.PrivateHacsManager


class _Hass:
    def __init__(self, config_path: Path) -> None:
        self.config = types.SimpleNamespace(
            path=lambda *parts: str(config_path.joinpath(*parts))
        )
        self.data = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _Client:
    async def async_list_private_repositories(self):
        return [
            GitHubRepository(
                full_name="owner/ha-example",
                description=None,
                default_branch="main",
                html_url="https://example.test/owner/ha-example",
                updated_at=None,
                archived=False,
            )
        ]

    async def async_get_integration_versions(self, *_):
        return {"example": "1.1.0"}


class _Store:
    def values(self):
        return ()

    def get(self, _):
        return None


class _InstallClient:
    repository = GitHubRepository(
        full_name="owner/ha-example",
        description=None,
        default_branch="main",
        html_url="https://example.test/owner/ha-example",
        updated_at=None,
        archived=False,
    )

    async def async_get_repository(self, _):
        return self.repository

    async def async_get_commit_sha(self, *_):
        return "commit-sha"

    async def async_download_archive(self, *_):
        return b"archive"


class _InstallStore(_Store):
    def __init__(self) -> None:
        self.record = None

    async def async_upsert(self, record) -> None:
        self.record = record


class _Installer:
    def __init__(self, custom_components_path: Path) -> None:
        self.custom_components_path = custom_components_path
        self.allowed_existing: set[str] | None = None

    def inspect_archive(self, _):
        return types.SimpleNamespace(domains=("example",), lovelace_filename=None)

    def install_archive(self, _, allowed_existing: set[str]) -> None:
        self.allowed_existing = allowed_existing


class _LovelaceInstaller(_Installer):
    def inspect_archive(self, _):
        return types.SimpleNamespace(domains=(), lovelace_filename="ha-example.js")

    def install_lovelace_card(
        self, _, directory_name: str, allow_existing: bool
    ) -> None:
        self.directory_name = directory_name
        self.allow_existing = allow_existing


class _Resources:
    store = object()
    loaded = False

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict[str, str]]:
        return self.items

    async def async_create_item(self, item: dict[str, str]) -> None:
        self.items.append({"id": "resource", **item})

    async def async_update_item(self, item_id: str, item: dict[str, str]) -> None:
        for resource in self.items:
            if resource["id"] == item_id:
                resource.update(item)


def test_externally_managed_integration_is_not_advertised_as_updatable(
    tmp_path: Path,
) -> None:
    """A newer external integration remains informational and non-updatable."""
    manifest_path = tmp_path / "custom_components" / "example" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"domain": "example", "version": "1.0.0"}), encoding="utf-8"
    )

    catalog = asyncio.run(
        PrivateHacsManager(_Hass(tmp_path), _Client(), _Store()).async_get_catalog()
    )

    assert catalog == [
        {
            "full_name": "owner/ha-example",
            "description": None,
            "default_branch": "main",
            "html_url": "https://example.test/owner/ha-example",
            "updated_at": None,
            "archived": False,
            "installed": True,
            "managed_by_privatehacs": False,
            "managed_externally": True,
            "domains": ["example"],
            "lovelace_filename": None,
            "icon_url": None,
            "local_versions": {"example": "1.0.0"},
            "available_versions": {"example": "1.1.0"},
            "installed_at": None,
            "installed_commit": None,
            "available_commit": None,
            "update_available": False,
        }
    ]


def test_newly_installed_integration_requires_a_restart(tmp_path: Path) -> None:
    """A successful first install tells the panel to request a restart."""
    async def async_get_custom_components(_):
        return {}

    manager_module.loader.DATA_CUSTOM_COMPONENTS = "custom_components"
    manager_module.loader.async_get_custom_components = async_get_custom_components
    store = _InstallStore()
    manager = PrivateHacsManager(_Hass(tmp_path), _InstallClient(), store)
    installer = _Installer(tmp_path / "custom_components")
    manager._installer = installer

    result = asyncio.run(manager.async_install_repository("owner/ha-example"))

    assert result["restart_required"] is True
    assert manager.restart_required is True
    assert installer.allowed_existing == set()
    assert store.record is not None
    assert store.record.commit_sha == "commit-sha"


def test_takeover_allows_replacing_an_external_component(tmp_path: Path) -> None:
    """An explicitly requested takeover may replace a stale external folder."""
    async def async_get_custom_components(_):
        return {}

    manager_module.loader.DATA_CUSTOM_COMPONENTS = "custom_components"
    manager_module.loader.async_get_custom_components = async_get_custom_components
    store = _InstallStore()
    manager = PrivateHacsManager(_Hass(tmp_path), _InstallClient(), store)
    installer = _Installer(tmp_path / "custom_components")
    manager._installer = installer

    asyncio.run(
        manager.async_install_repository("owner/ha-example", take_over=True)
    )

    assert installer.allowed_existing == {"example"}
    assert store.record is not None


def test_catalog_serves_an_installed_component_brand_icon(tmp_path: Path) -> None:
    """A local brand icon is copied to PrivateHACS' restricted static cache."""
    component_path = tmp_path / "custom_components" / "example"
    component_path.mkdir(parents=True)
    (component_path / "manifest.json").write_text(
        json.dumps({"domain": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    brand_path = component_path / "brand"
    brand_path.mkdir()
    (brand_path / "icon.png").write_bytes(b"icon")

    catalog = asyncio.run(
        PrivateHacsManager(_Hass(tmp_path), _Client(), _Store()).async_get_catalog()
    )

    assert catalog[0]["icon_url"] == "/local/privatehacs_icons/example.png"
    assert (
        tmp_path / "www" / "privatehacs_icons" / "example.png"
    ).read_bytes() == b"icon"


def test_lovelace_card_is_installed_and_registered_as_a_module(tmp_path: Path) -> None:
    """A frontend card is stored below www and added to Lovelace resources."""
    async def async_get_custom_components(_):
        return {}

    manager_module.loader.DATA_CUSTOM_COMPONENTS = "custom_components"
    manager_module.loader.async_get_custom_components = async_get_custom_components
    hass = _Hass(tmp_path)
    resources = _Resources()
    hass.data["lovelace"] = {"resources": resources}
    store = _InstallStore()
    manager = PrivateHacsManager(hass, _InstallClient(), store)
    installer = _LovelaceInstaller(tmp_path / "custom_components")
    manager._installer = installer

    result = asyncio.run(manager.async_install_repository("owner/ha-example"))

    assert result["restart_required"] is False
    assert result["lovelace_resource_registered"] is True
    assert result["lovelace_resource"].startswith(
        "/local/privatehacs/ha-example-"
    )
    assert result["lovelace_resource"].endswith("/ha-example.js?v=commit-sha")
    assert resources.items == [
        {"id": "resource", "res_type": "module", "url": result["lovelace_resource"]}
    ]
    assert store.record is not None
    assert store.record.lovelace_filename == "ha-example.js"
    assert installer.allow_existing is False