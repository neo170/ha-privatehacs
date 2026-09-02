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


def test_panel_uses_html_confirmation_dialogs() -> None:
    """All confirmation flows use the panel's native HTML dialog."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "frontend"
        / "privatehacs-panel.js"
    ).read_text(encoding="utf-8")

    assert '<dialog class="confirmation-dialog"' in panel_source
    assert "confirmationDialog.showModal()" in panel_source
    assert "window" + ".confirm" not in panel_source
    assert panel_source.count("await this._confirm(") == 4


def test_panel_confirmation_dialog_matches_cardbook_style() -> None:
    """The confirmation dialog follows CardBook's popup styling tokens."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "frontend"
        / "privatehacs-panel.js"
    ).read_text(encoding="utf-8")

    assert "width: 90%;" in panel_source
    assert "max-width: 380px;" in panel_source
    assert "padding: 24px 28px;" in panel_source
    assert "border-radius: 10px;" in panel_source
    assert "box-shadow: 0 6px 28px rgb(0 0 0 / 35%);" in panel_source
    assert "background: rgb(0 0 0 / 50%);" in panel_source
    assert "background: var(--secondary-background-color, #e0e0e0);" in panel_source
    assert 'class="button button--secondary"' in panel_source
    assert ".confirmation-dialog__header" not in panel_source


def test_panel_exposes_home_assistant_menu_on_mobile() -> None:
    """The mobile header can reopen Home Assistant navigation."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "frontend"
        / "privatehacs-panel.js"
    ).read_text(encoding="utf-8")

    assert 'id="menu"' in panel_source
    assert 'icon="mdi:menu"' in panel_source
    assert ".menu-button {" in panel_source
    assert "display: inline-flex;" in panel_source
    assert '"hass-toggle-menu"' in panel_source


def test_panel_header_matches_cardbook_header_tokens() -> None:
    """The panel header uses the same Home Assistant header tokens as CardBook."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "frontend"
        / "privatehacs-panel.js"
    ).read_text(encoding="utf-8")

    assert "height: var(--header-height);" in panel_source
    assert "background: var(--app-header-background-color);" in panel_source
    assert "color: var(--app-header-text-color);" in panel_source
    assert "border-bottom: var(--app-header-border-bottom);" in panel_source
    assert "font-size: var(--app-header-font-size, var(--ha-font-size-xl));" in panel_source
    assert "@media (max-width: 640px)" in panel_source


def test_panel_does_not_register_custom_element_twice() -> None:
    """Reloading the asset must not redefine the panel custom element."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "frontend"
        / "privatehacs-panel.js"
    ).read_text(encoding="utf-8")

    assert 'if (!customElements.get("privatehacs-panel")) {' in panel_source
    assert panel_source.count('customElements.define("privatehacs-panel", PrivateHacsPanel)') == 1


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