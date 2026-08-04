"""Tests for the PrivateHACS panel asset URL."""

from __future__ import annotations

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


def test_frontend_module_url_uses_the_asset_content_hash(tmp_path: Path) -> None:
    """Changing the panel asset produces a distinct browser module URL."""
    content = b"customElements.define('privatehacs-panel', class {});"
    (tmp_path / "privatehacs-panel.js").write_bytes(content)

    module_url = frontend_module._frontend_module_url(tmp_path)

    expected_hash = hashlib.sha256(content).hexdigest()[:12]
    assert module_url == f"/privatehacs_static/privatehacs-panel.js?v={expected_hash}"