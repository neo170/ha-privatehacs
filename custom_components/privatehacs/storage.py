"""Persistent repository state for PrivateHACS."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import InstalledRepository


class PrivateHacsStore:
    """Store PrivateHACS installation records without storing source archives."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize empty in-memory records backed by Home Assistant storage."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._repositories: dict[str, InstalledRepository] = {}
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load valid repository records from persistent storage."""
        payload = await self._store.async_load()
        if not isinstance(payload, dict):
            return

        raw_repositories = payload.get("repositories")
        if not isinstance(raw_repositories, dict):
            return

        for full_name, raw_record in raw_repositories.items():
            if not isinstance(full_name, str) or not isinstance(raw_record, dict):
                continue
            try:
                record = InstalledRepository.from_dict(raw_record)
            except ValueError:
                continue
            if record.full_name == full_name:
                self._repositories[full_name] = record

    def get(self, full_name: str) -> InstalledRepository | None:
        """Return one installed repository record."""
        return self._repositories.get(full_name)

    def values(self) -> tuple[InstalledRepository, ...]:
        """Return all installed repository records."""
        return tuple(self._repositories.values())

    async def async_upsert(self, record: InstalledRepository) -> None:
        """Persist an installed repository record immediately."""
        async with self._lock:
            self._repositories[record.full_name] = record
            await self._store.async_save(
                {
                    "repositories": {
                        full_name: repository.as_dict()
                        for full_name, repository in self._repositories.items()
                    }
                }
            )

    async def async_remove(self, full_name: str) -> bool:
        """Remove one PrivateHACS-managed repository record."""
        async with self._lock:
            if full_name not in self._repositories:
                return False
            del self._repositories[full_name]
            await self._store.async_save(
                {
                    "repositories": {
                        repository_name: repository.as_dict()
                        for repository_name, repository in self._repositories.items()
                    }
                }
            )
            return True