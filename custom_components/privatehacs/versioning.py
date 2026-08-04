"""Version comparison helpers for integration manifests."""

from __future__ import annotations

import re

_VERSION_PATTERN = re.compile(
    r"^v?(?P<numbers>\d+(?:\.\d+)*)(?:[-.]?(?P<stage>dev|a|alpha|b|beta|rc)(?P<stage_number>\d*)?)?$",
    re.IGNORECASE,
)
_STAGE_ORDER = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "rc": 3}


def is_newer_version(available: str | None, installed: str | None) -> bool:
    """Return whether a parseable available manifest version is newer."""
    if not available or not installed or available == installed:
        return False

    available_key = _version_key(available)
    installed_key = _version_key(installed)
    return bool(
        available_key is not None
        and installed_key is not None
        and available_key > installed_key
    )


def _version_key(version: str) -> tuple[tuple[int, ...], int, int] | None:
    """Create a comparable key for common Home Assistant manifest versions."""
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        return None

    numbers = tuple(int(part) for part in match.group("numbers").split("."))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    stage = match.group("stage")
    if stage is None:
        return numbers, 4, 0

    return numbers, _STAGE_ORDER[stage.lower()], int(match.group("stage_number") or 0)