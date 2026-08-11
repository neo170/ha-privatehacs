"""Tests for manifest version comparison."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_versioning_module():
    module_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "privatehacs"
        / "versioning.py"
    )
    spec = importlib.util.spec_from_file_location("privatehacs_versioning_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


versioning = _load_versioning_module()


def test_is_newer_version_handles_manifest_versions() -> None:
    """Release, pre-release and invalid manifest versions compare safely."""
    assert versioning.is_newer_version("1.2.0", "1.1.9")
    assert versioning.is_newer_version("v1.2.0", "1.1.9")
    assert versioning.is_newer_version("1.2.0", "1.2.0rc1")
    assert not versioning.is_newer_version("1.2.0rc1", "1.2.0")
    assert not versioning.is_newer_version("1.2.0", "1.2")
    assert not versioning.is_newer_version("invalid", "1.0.0")


def test_versions_equal_normalizes_release_tag_prefixes() -> None:
    """Release tags and manifest versions can use different v-prefixes."""
    assert versioning.versions_equal("v1.5.22", "1.5.22")
    assert versioning.versions_equal("1.2", "1.2.0")
    assert not versioning.versions_equal("1.2.0", "1.2.1")
    assert not versioning.versions_equal("invalid", "1.2.0")