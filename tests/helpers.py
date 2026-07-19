"""Minimal fakes shared across tests.

Entity classes only ever touch `coordinator.data` and `coordinator.device_info`
at the level these tests exercise (no listener registration, no hass access),
so a small duck-typed stand-in is enough -- no need for a real
DataUpdateCoordinator or a real ConfigEntry.
"""
from __future__ import annotations

from typing import Any


class FakeCoordinator:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.device_info: dict[str, Any] = {}


class FakeEntry:
    entry_id = "test_entry"
