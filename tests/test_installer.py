"""Focused tests for the archive safety boundary."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest


def _load_installer_module():
    installer_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "installer.py"
    )
    module_name = "privatehacs_installer_test"
    spec = importlib.util.spec_from_file_location(module_name, installer_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


installer_module = _load_installer_module()
ArchiveInstaller = installer_module.ArchiveInstaller
InstallationError = installer_module.InstallationError


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        for name, content in files.items():
            zip_file.writestr(name, content)
    return buffer.getvalue()


def _component_archive(domain: str, body: str = "NEW") -> bytes:
    return _archive(
        {
            f"repo-sha/custom_components/{domain}/manifest.json": (
                '{"domain": "' + domain + '", "name": "Test", "version": "1.0.0"}'
            ),
            f"repo-sha/custom_components/{domain}/__init__.py": body,
        }
    )


def _lovelace_archive(filename: str = "ha-example.js") -> bytes:
    return _archive(
        {
            "repo-sha/hacs.json": (
                '{"filename": "' + filename + '", "content_in_root": false}'
            ),
            f"repo-sha/dist/{filename}": "window.customElements.define('ha-example', class {});",
        }
    )


def test_install_replaces_a_managed_component_atomically(tmp_path: Path) -> None:
    custom_components = tmp_path / "custom_components"
    old_component = custom_components / "example"
    old_component.mkdir(parents=True)
    (old_component / "__init__.py").write_text("OLD", encoding="utf-8")

    contents = ArchiveInstaller(custom_components).install_archive(
        _component_archive("example"), {"example"}
    )

    assert contents.domains == ("example",)
    assert (old_component / "__init__.py").read_text(encoding="utf-8") == "NEW"


def test_install_does_not_overwrite_unmanaged_component(tmp_path: Path) -> None:
    custom_components = tmp_path / "custom_components"
    external_component = custom_components / "example"
    external_component.mkdir(parents=True)
    (external_component / "__init__.py").write_text("EXTERNAL", encoding="utf-8")

    with pytest.raises(InstallationError, match="Remove it in HACS"):
        ArchiveInstaller(custom_components).install_archive(
            _component_archive("example"), set()
        )

    assert (external_component / "__init__.py").read_text(encoding="utf-8") == "EXTERNAL"


def test_uninstall_removes_managed_component_directories(tmp_path: Path) -> None:
    """Removing a managed integration only deletes its domain directory."""
    custom_components = tmp_path / "custom_components"
    managed_component = custom_components / "example"
    managed_component.mkdir(parents=True)
    (managed_component / "__init__.py").write_text("MANAGED", encoding="utf-8")
    unrelated_component = custom_components / "unrelated"
    unrelated_component.mkdir()

    ArchiveInstaller(custom_components).uninstall_components(("example",))

    assert not managed_component.exists()
    assert unrelated_component.is_dir()


def test_install_rejects_path_traversal(tmp_path: Path) -> None:
    archive = _component_archive("example")
    buffer = io.BytesIO(archive)
    with ZipFile(buffer, "a") as zip_file:
        zip_file.writestr("../outside.py", "UNSAFE")

    with pytest.raises(InstallationError, match="unsafe path"):
        ArchiveInstaller(tmp_path / "custom_components").install_archive(buffer.getvalue(), set())


def test_install_rejects_mismatched_manifest_domain(tmp_path: Path) -> None:
    archive = _archive(
        {
            "repo-sha/custom_components/example/manifest.json": (
                '{"domain": "other", "name": "Test", "version": "1.0.0"}'
            )
        }
    )

    with pytest.raises(InstallationError, match="different domain"):
        ArchiveInstaller(tmp_path / "custom_components").install_archive(archive, set())


def test_install_lovelace_card_to_privatehacs_www_path(tmp_path: Path) -> None:
    """A HACS-declared frontend card is atomically installed below www."""
    installer = ArchiveInstaller(tmp_path / "custom_components", tmp_path / "www")

    contents = installer.install_lovelace_card(
        _lovelace_archive(), "ha-example-123456789abc", allow_existing=False
    )

    assert contents.domains == ()
    assert contents.lovelace_filename == "ha-example.js"
    assert (
        tmp_path / "www" / "privatehacs" / "ha-example-123456789abc" / "ha-example.js"
    ).read_text(encoding="utf-8") == "window.customElements.define('ha-example', class {});"


def test_lovelace_card_does_not_overwrite_unmanaged_directory(tmp_path: Path) -> None:
    """A non-PrivateHACS card directory is not replaced during first install."""
    target = tmp_path / "www" / "privatehacs" / "ha-example-123456789abc"
    target.mkdir(parents=True)
    (target / "ha-example.js").write_text("EXTERNAL", encoding="utf-8")
    installer = ArchiveInstaller(tmp_path / "custom_components", tmp_path / "www")

    with pytest.raises(InstallationError, match="already installed outside"):
        installer.install_lovelace_card(
            _lovelace_archive(), "ha-example-123456789abc", allow_existing=False
        )

    assert (target / "ha-example.js").read_text(encoding="utf-8") == "EXTERNAL"


def test_uninstall_removes_privatehacs_lovelace_card(tmp_path: Path) -> None:
    """Removing a card only deletes its dedicated PrivateHACS asset directory."""
    card_directory = tmp_path / "www" / "privatehacs" / "ha-example-123456789abc"
    card_directory.mkdir(parents=True)
    (card_directory / "ha-example.js").write_text("CARD", encoding="utf-8")
    unrelated_card = tmp_path / "www" / "privatehacs" / "other-card-123456789abc"
    unrelated_card.mkdir()

    ArchiveInstaller(tmp_path / "custom_components", tmp_path / "www").uninstall_lovelace_card(
        "ha-example-123456789abc"
    )

    assert not card_directory.exists()
    assert unrelated_card.is_dir()