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
        def __init__(self, custom_components_path: Path) -> None:
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
        return types.SimpleNamespace(domains=("example",))

    def install_archive(self, _, allowed_existing: set[str]) -> None:
        self.allowed_existing = allowed_existing


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
    assert installer.allowed_existing == set()
    assert store.record is not None
    assert store.record.commit_sha == "commit-sha"