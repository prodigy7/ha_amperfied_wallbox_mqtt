"""Binary sensor entities for the Amperfied Wallbox: EV connected, default password.

EV connected is derived from power/evState != A1 (see PROTOCOL.md, "Relevant
telemetry topics" -- A1 is the only state meaning "no car"). Default password
is derived from api/conf/mqttapi/user/initialPassword (see PROTOCOL.md,
"Device/factory info").
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EV_STATE_NO_CAR, TOPIC_CONF_INITIAL_PASSWORD, TOPIC_EV_STATE
from .coordinator import AmperfiedWallboxCoordinator

EV_CONNECTED_DESCRIPTION = BinarySensorEntityDescription(
    key="ev_connected",
    translation_key="ev_connected",
    device_class=BinarySensorDeviceClass.PLUG,
)

USING_DEFAULT_PASSWORD_DESCRIPTION = BinarySensorEntityDescription(
    key="using_default_password",
    translation_key="using_default_password",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


def _unwrap(raw: Any) -> Any:
    return raw["value"] if isinstance(raw, dict) and "value" in raw else raw


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sets up the binary sensor entities for this config entry."""
    coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AmperfiedWallboxEvConnectedBinarySensor(coordinator, entry),
            AmperfiedWallboxDefaultPasswordBinarySensor(coordinator, entry),
        ]
    )


class AmperfiedWallboxEvConnectedBinarySensor(
    CoordinatorEntity[AmperfiedWallboxCoordinator], BinarySensorEntity
):
    """Is an EV currently plugged in?"""

    entity_description = EV_CONNECTED_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: AmperfiedWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_ev_connected"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        raw: Any = self.coordinator.data.get(TOPIC_EV_STATE)
        if raw is None:
            return None
        return _unwrap(raw) != EV_STATE_NO_CAR


class AmperfiedWallboxDefaultPasswordBinarySensor(
    CoordinatorEntity[AmperfiedWallboxCoordinator], BinarySensorEntity
):
    """Is the wallbox still using its factory-default password?

    A security hint, not something this integration can fix (see
    read-primary policy in CLAUDE.md/PROTOCOL.md) -- the password must be
    changed via the wallbox's own web UI.
    """

    entity_description = USING_DEFAULT_PASSWORD_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: AmperfiedWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_using_default_password"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        raw: Any = self.coordinator.data.get(TOPIC_CONF_INITIAL_PASSWORD)
        if raw is None:
            return None
        return bool(_unwrap(raw))
