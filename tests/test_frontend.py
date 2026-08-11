"""Tests for the PrivateHACS panel asset URL."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from pathlib import Path
import sys
import types


def _load_frontend_module():
    root = Path(__file__).parents[1] / "custom_components" / "privatehacs"
    package_name = "privatehacs_frontend_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    frontend = types.ModuleType("homeassistant.components.frontend")
    frontend.async_panel_exists = lambda *_: False
    frontend.async_register_built_in_panel = lambda *_args, **_kwargs: None
    frontend.async_remove_panel = lambda *_: None
    http = types.ModuleType("homeassistant.components.http")
    http.StaticPathConfig = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.components.frontend"] = frontend
    sys.modules["homeassistant.components.http"] = http
    sys.modules["homeassistant.core"] = core

    for name in ("const", "frontend"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}", root / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

    return sys.modules[f"{package_name}.frontend"]


frontend_module = _load_frontend_module()


def test_panel_displays_lovelace_release_tags() -> None:
    """Lovelace cards display installed and available release tags."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "frontend"
        / "privatehacs-panel.js"
    ).read_text(encoding="utf-8")

    assert "const releaseVersion = repository.available_version" in panel_source
    assert "repository.installed_version || labels.unversioned" in panel_source
    assert "repository.installed_commit" not in panel_source
    assert "repository.available_commit" not in panel_source


def test_frontend_module_url_uses_the_asset_content_hash(tmp_path: Path) -> None:
    """Changing the panel asset produces a distinct browser module URL."""
    content = b"customElements.define('privatehacs-panel', class {});"
    (tmp_path / "privatehacs-panel.js").write_bytes(content)

    module_url = frontend_module._frontend_module_url(tmp_path)

    expected_hash = hashlib.sha256(content).hexdigest()[:12]
    assert module_url == f"/privatehacs_static/privatehacs-panel.js?v={expected_hash}"


def test_register_panel_hashes_the_asset_in_the_executor(tmp_path: Path) -> None:
    """Panel asset I/O is delegated away from the event loop."""
    executed_functions = []

    class Http:
        async def async_register_static_paths(self, _paths) -> None:
            pass

    class Hass:
        http = Http()

        def __init__(self) -> None:
            self.data = {
                frontend_module.DOMAIN: {
                    frontend_module.DATA_PANEL_STATIC_REGISTERED: True
                }
            }

        async def async_add_executor_job(self, func, *args):
            executed_functions.append(func)
            return func(*args)

    hass = Hass()
    asyncio.run(frontend_module.async_register_panel(hass))

    assert executed_functions == [frontend_module._frontend_module_url]