"""Diagnostics for the Amperfied Wallbox integration.

Exposes the RFID card list (see PROTOCOL.md, api/cmd/rfidList/get) plus the
current telemetry snapshot as a diagnostics export, instead of creating
dedicated entities for it (see CLAUDE.md: "4 cards is no reason for 4 entities").
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, DOMAIN
from .coordinator import AmperfiedWallboxCoordinator

# uuid/cardnum uniquely identify physical RFID cards/fobs and are therefore
# treated like personal data.
TO_REDACT = {CONF_PASSWORD, "accessToken", "refreshToken", "uuid", "cardnum"}


def _unwrap(raw: Any) -> Any:
    return raw["value"] if isinstance(raw, dict) and "value" in raw else raw


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Collects diagnostics data for this config entry."""
    coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]

    try:
        rfid_list: Any = await coordinator.client.async_get_rfid_list()
    except Exception as err:  # noqa: BLE001
        rfid_list = {"error": str(err)}

    try:
        raw_details = await coordinator.client.async_get_diagnostics_device_details()
        device_details: Any = {topic: _unwrap(value) for topic, value in raw_details.items()}
    except Exception as err:  # noqa: BLE001
        device_details = {"error": str(err)}

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "telemetry": coordinator.data,
        "rfid_list": async_redact_data(rfid_list, TO_REDACT),
        "device_details": device_details,
    }
