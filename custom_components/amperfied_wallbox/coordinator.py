"""DataUpdateCoordinator for the Amperfied Wallbox.

The wallbox actively pushes telemetry (see PROTOCOL.md), there is no
meaningful polling interval. Hence: update_interval=None, and instead call
async_set_updated_data() every time a new MQTT message comes in (see api.py:
async_subscribe_telemetry callback).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import AmperfiedWallboxClient
from .const import (
    DOMAIN,
    EV_STATE_NO_CAR,
    LAST_CHARGE_SESSION_KEY,
    TOPIC_EOL_BOX_SERIAL,
    TOPIC_EOL_ETH0_MAC,
    TOPIC_EOL_HARDWARE_VERSION,
    TOPIC_EOL_SOFTWARE_VERSION,
    TOPIC_EOL_WIFI_MAC,
    TOPIC_EV_STATE,
)

_LOGGER = logging.getLogger(__name__)


def _unwrap(raw: Any) -> Any:
    """Extracts the "value" key from a dict-wrapped payload, if present."""
    return raw["value"] if isinstance(raw, dict) and "value" in raw else raw


def _format_mac(raw: Any) -> str | None:
    """Formats a MAC address like "006034abc123" as "00:60:34:ab:c1:23"."""
    value = _unwrap(raw)
    if not isinstance(value, str) or len(value) != 12:
        return None
    return ":".join(value[i : i + 2] for i in range(0, 12, 2))


class AmperfiedWallboxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the last known state of all telemetry topics.

    self.data is a dict, key = relative topic (e.g. "api/t/power/evState"),
    value = parsed value (string, number, or dict, depending on the topic).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AmperfiedWallboxClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,  # push-based, no polling
        )
        self.entry = entry
        self.client = client
        self._refresh_task: asyncio.Task[None] | None = None
        # Filled in with sw_version/hw_version/serial_number during
        # async_setup(); shared by all entities so the HA device page shows
        # real firmware/hardware info instead of just the static basics.
        self.device_info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Amperfied Wallbox",
            manufacturer="Amperfied / Heidelberg",
            model="connect.solar",
        )

    async def _async_on_telemetry(self, topic: str, value: Any) -> None:
        """Callback for incoming telemetry, passed through from api.py.

        Updates only the affected key and passes a new dict to all entities
        (async_set_updated_data also handles the listener callback and
        resetting last_update_success). When the car gets unplugged
        (evState -> A1), also kicks off a background refresh of the "last
        charge session" data, since a new session will have just completed.
        """
        data = dict(self.data or {})
        data[topic] = value
        self.async_set_updated_data(data)

        if topic == TOPIC_EV_STATE and _unwrap(value) == EV_STATE_NO_CAR:
            if self._refresh_task is not None and not self._refresh_task.done():
                _LOGGER.debug(
                    "Last charge session refresh already in progress, not starting another"
                )
                return
            _LOGGER.debug("Car unplugged, refreshing last charge session")
            self._refresh_task = self.entry.async_create_background_task(
                self.hass,
                self._async_refresh_last_charge_session(),
                name="amperfied_wallbox_refresh_last_charge_session",
            )

    async def async_setup(self) -> None:
        """Connects the client, fetches static device info, and starts the
        telemetry subscription.

        Called from __init__.py (async_setup_entry) before the platforms
        (sensor, button) are loaded.
        """
        await self.client.async_connect()

        _LOGGER.debug("Fetching one-time device info snapshot")
        device_data = await self.client.async_get_device_info()

        sw_version = _unwrap(device_data.get(TOPIC_EOL_SOFTWARE_VERSION))
        if sw_version is not None:
            self.device_info["sw_version"] = sw_version
        hw_version = _unwrap(device_data.get(TOPIC_EOL_HARDWARE_VERSION))
        if hw_version is not None:
            self.device_info["hw_version"] = hw_version
        serial_number = _unwrap(device_data.get(TOPIC_EOL_BOX_SERIAL))
        if serial_number is not None:
            self.device_info["serial_number"] = serial_number

        connections: set[tuple[str, str]] = set()
        for mac_topic in (TOPIC_EOL_ETH0_MAC, TOPIC_EOL_WIFI_MAC):
            mac = _format_mac(device_data.get(mac_topic))
            if mac is not None:
                connections.add((dr.CONNECTION_NETWORK_MAC, mac))
        if connections:
            self.device_info["connections"] = connections

        # Merge the raw (still dict-wrapped-where-applicable) device data into
        # self.data too, keyed by topic like telemetry -- e.g. so a binary
        # sensor can read TOPIC_CONF_INITIAL_PASSWORD the same way any other
        # topic is read.
        self.async_set_updated_data({**(self.data or {}), **device_data})

        await self.client.async_subscribe_telemetry(self._async_on_telemetry)
        _LOGGER.debug("Subscribed to telemetry")
        await self._async_refresh_last_charge_session()

    async def _async_refresh_last_charge_session(self) -> None:
        """Fetches the most recently completed charge session (api/cmd/clog/get)
        and stores it under a synthetic key (see const.LAST_CHARGE_SESSION_KEY).

        Refreshed once at startup and again every time the car is unplugged.
        Errors are logged but not raised -- this is a nice-to-have sensor,
        not something that should ever take down telemetry updates.
        """
        try:
            local_now = datetime.now().astimezone()
            resp = await self.client.async_get_charge_log(
                filter_after=(local_now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S%z"),
                filter_before=(local_now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S%z"),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to refresh the last charge session")
            return

        sessions = resp.get("value") if isinstance(resp, dict) else None
        if not sessions:
            _LOGGER.debug("No charge sessions found in the last 2 days")
            return
        _LOGGER.debug("Last charge session refreshed: %s", sessions[0].get("guid"))
        data = dict(self.data or {})
        data[LAST_CHARGE_SESSION_KEY] = sessions[0]
        self.async_set_updated_data(data)

    async def _async_update_data(self) -> dict[str, Any]:
        """Not normally called actively for a push-based coordinator.

        Still implemented in case of a manual refresh button in the UI (HA
        calls this method on "Refresh" in the integration). Can simply
        return self.data.
        """
        return self.data or {}
