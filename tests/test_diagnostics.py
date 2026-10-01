"""Unit tests for diagnostics.py: RFID card identifiers (uuid/cardnum) must
never end up in the diagnostics export, which users typically attach to
public issue reports.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from homeassistant.components.diagnostics import REDACTED

from custom_components.amperfied_wallbox.const import (
    DOMAIN,
    LAST_CHARGE_SESSION_KEY,
    TOPIC_CHARGE_PERMISSION,
)
from custom_components.amperfied_wallbox.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import FakeCoordinator, FakeEntry

CARD_UUID = "de:ad:be:ef:00:11:22"


class FakeClient:
    async def async_get_rfid_list(self) -> list[dict[str, Any]]:
        return []

    async def async_get_diagnostics_device_details(self) -> dict[str, Any]:
        return {}


class FakeHass:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.data = {DOMAIN: {FakeEntry.entry_id: coordinator}}


class FakeDiagnosticsEntry(FakeEntry):
    data: dict[str, Any] = {"host": "192.0.2.1", "password": "secret"}


@pytest.mark.asyncio
async def test_rfid_card_identifiers_redacted_from_telemetry(
    telemetry_charging: dict[str, Any], telemetry_idle: dict[str, Any]
) -> None:
    # Charging fixture: authorized via RFID fob, so chargePermission carries
    # the card's uuid. The idle fixture's last charge session (from clog/get)
    # was RFID-authorized too.
    data = {
        **telemetry_charging,
        LAST_CHARGE_SESSION_KEY: telemetry_idle[LAST_CHARGE_SESSION_KEY],
    }
    original = copy.deepcopy(data)
    coordinator = FakeCoordinator(data, FakeClient())

    result = await async_get_config_entry_diagnostics(
        FakeHass(coordinator), FakeDiagnosticsEntry()
    )

    assert CARD_UUID not in json.dumps(result)
    permission = result["telemetry"][TOPIC_CHARGE_PERMISSION]
    assert permission["uuid"] == REDACTED
    assert permission["cardnum"] == REDACTED
    assert permission["source"] == "rfid"
    authentication = result["telemetry"][LAST_CHARGE_SESSION_KEY]["authentication"]
    assert authentication["uuid"] == REDACTED
    assert authentication["cardnum"] == REDACTED
    # Redaction works on a copy -- the live coordinator data stays intact.
    assert coordinator.data == original
