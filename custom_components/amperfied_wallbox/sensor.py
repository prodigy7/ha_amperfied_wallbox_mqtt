"""Sensor entities for the Amperfied Wallbox.

Values are extracted from coordinator.data (key = relative topic, see
const.py) in native_value. Payload formats are documented in PROTOCOL.md,
"Relevant telemetry topics" section.

Notes on individual sensors:
- powermeter/energy is a monotonically increasing meter reading -> state_class
  TOTAL_INCREASING, device_class ENERGY.
- powermeter/power is instantaneous power -> state_class MEASUREMENT,
  device_class POWER.
- power/evState is a string enum (A1, B, C, ...) -> consider a dedicated
  translation/mapping to readable states (see translations/de.json for
  suggestions).
- powermeter/powerPerPhases and powermeter/sensor are semicolon-separated
  strings (see PROTOCOL.md); per-phase sensors pull one field out via
  value_fn and are marked as diagnostic entities (technical detail, not a
  main dashboard value).
- loadbalancer/grid/monitor/leader is a single big JSON blob; surplus/grid/
  house power sensors pull one field (or sum one array) out of it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    LAST_CHARGE_SESSION_KEY,
    TOPIC_CHARGE_PERMISSION,
    TOPIC_EM_STATE,
    TOPIC_EV_STATE,
    TOPIC_GRID_MONITOR_LEADER,
    TOPIC_LIMITER,
    TOPIC_PHASE_SWITCH_STATE,
    TOPIC_PHASES,
    TOPIC_POWER_LIMIT,
    TOPIC_POWERMETER_ENERGY,
    TOPIC_POWERMETER_POWER,
    TOPIC_POWERMETER_POWER_PER_PHASES,
    TOPIC_POWERMETER_SENSOR,
    TOPIC_TEMP,
    TOPIC_WB_STATE,
)
from .coordinator import AmperfiedWallboxCoordinator


def _semicolon_field(raw: Any, index: int) -> float | None:
    """Pulls one numeric field out of a "a;b;c;..." string topic value."""
    if not isinstance(raw, str):
        return None
    parts = raw.split(";")
    if index >= len(parts):
        return None
    try:
        return float(parts[index])
    except ValueError:
        return None


def _grid_field(raw: Any, key: str) -> float | None:
    """Pulls a single numeric field out of the grid/monitor/leader JSON blob."""
    if not isinstance(raw, dict):
        return None
    return raw.get(key)


def _grid_field_sum(raw: Any, key: str) -> float | None:
    """Sums a per-phase array field (e.g. gridPower: [L1, L2, L3]) out of the
    grid/monitor/leader JSON blob.
    """
    if not isinstance(raw, dict):
        return None
    values = raw.get(key)
    if not isinstance(values, list):
        return None
    return sum(values)


def _charge_permission_source(raw: Any) -> str:
    """Who/what currently holds the charge authorization, if any."""
    if not isinstance(raw, dict) or not raw:
        return "none"
    return raw.get("source", "unknown")


def _charge_permission_attributes(raw: Any) -> dict[str, Any]:
    """label/timestamp of the current charge authorization.

    Deliberately omits uuid/cardnum -- those identify a physical RFID
    card/fob and are treated like personal data, same as in diagnostics.py.
    """
    if not isinstance(raw, dict):
        return {}
    attrs: dict[str, Any] = {}
    if raw.get("label"):
        attrs["label"] = raw["label"]
    if "timestamp" in raw:
        attrs["timestamp"] = raw["timestamp"]
    return attrs


def _last_session_energy(raw: Any) -> float | None:
    if not isinstance(raw, dict):
        return None
    return raw.get("energy")


def _last_session_attributes(raw: Any) -> dict[str, Any]:
    """begin/end/duration/authorization source of the last charge session.

    Deliberately omits uuid/cardnum, see _charge_permission_attributes.
    """
    if not isinstance(raw, dict):
        return {}
    attrs: dict[str, Any] = {}
    for key in ("begin", "end", "chargingDuration", "sessionDuration"):
        if key in raw:
            attrs[key] = raw[key]
    authentication = raw.get("authentication")
    if isinstance(authentication, dict):
        if authentication.get("source"):
            attrs["source"] = authentication["source"]
        if authentication.get("label"):
            attrs["label"] = authentication["label"]
    return attrs


@dataclass(frozen=True, kw_only=True)
class AmperfiedWallboxSensorDescription(SensorEntityDescription):
    """Extended entity description with the associated telemetry topic.

    value_fn/attributes_fn allow pulling a specific field out of a topic
    whose raw value is a bigger structure (a semicolon-separated string or a
    nested JSON blob) instead of the default "unwrap {'value': ...}" logic.
    """

    topic: str = ""
    value_fn: Callable[[Any], Any] | None = None
    attributes_fn: Callable[[Any], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[AmperfiedWallboxSensorDescription, ...] = (
    AmperfiedWallboxSensorDescription(
        key="charging_power",
        translation_key="charging_power",
        topic=TOPIC_POWERMETER_POWER,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    AmperfiedWallboxSensorDescription(
        key="total_energy",
        translation_key="total_energy",
        topic=TOPIC_POWERMETER_ENERGY,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    AmperfiedWallboxSensorDescription(
        key="pcb_temperature",
        translation_key="pcb_temperature",
        topic=TOPIC_TEMP,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    AmperfiedWallboxSensorDescription(
        key="ev_state",
        translation_key="ev_state",
        topic=TOPIC_EV_STATE,
    ),
    AmperfiedWallboxSensorDescription(
        key="wallbox_state",
        translation_key="wallbox_state",
        topic=TOPIC_WB_STATE,
    ),
    AmperfiedWallboxSensorDescription(
        key="power_limit",
        translation_key="power_limit",
        topic=TOPIC_POWER_LIMIT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    AmperfiedWallboxSensorDescription(
        key="energy_manager_state",
        translation_key="energy_manager_state",
        topic=TOPIC_EM_STATE,
    ),
    AmperfiedWallboxSensorDescription(
        key="active_phases",
        translation_key="active_phases",
        topic=TOPIC_PHASES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AmperfiedWallboxSensorDescription(
        key="limiter",
        translation_key="limiter",
        topic=TOPIC_LIMITER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AmperfiedWallboxSensorDescription(
        key="phase_switch_state",
        translation_key="phase_switch_state",
        topic=TOPIC_PHASE_SWITCH_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AmperfiedWallboxSensorDescription(
        key="charge_permission_source",
        translation_key="charge_permission_source",
        topic=TOPIC_CHARGE_PERMISSION,
        value_fn=_charge_permission_source,
        attributes_fn=_charge_permission_attributes,
    ),
    AmperfiedWallboxSensorDescription(
        key="surplus_power",
        translation_key="surplus_power",
        topic=TOPIC_GRID_MONITOR_LEADER,
        value_fn=lambda raw: _grid_field(raw, "surplusPower"),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    AmperfiedWallboxSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        topic=TOPIC_GRID_MONITOR_LEADER,
        value_fn=lambda raw: _grid_field_sum(raw, "gridPower"),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AmperfiedWallboxSensorDescription(
        key="house_power",
        translation_key="house_power",
        topic=TOPIC_GRID_MONITOR_LEADER,
        value_fn=lambda raw: _grid_field_sum(raw, "housePower"),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AmperfiedWallboxSensorDescription(
        key="last_charge_session_energy",
        translation_key="last_charge_session_energy",
        topic=LAST_CHARGE_SESSION_KEY,
        value_fn=_last_session_energy,
        attributes_fn=_last_session_attributes,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
) + tuple(
    AmperfiedWallboxSensorDescription(
        key=f"power_phase_{phase}",
        translation_key=f"power_phase_{phase}",
        topic=TOPIC_POWERMETER_POWER_PER_PHASES,
        value_fn=lambda raw, i=phase - 1: _semicolon_field(raw, i),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for phase in (1, 2, 3)
) + tuple(
    AmperfiedWallboxSensorDescription(
        key=f"voltage_phase_{phase}",
        translation_key=f"voltage_phase_{phase}",
        topic=TOPIC_POWERMETER_SENSOR,
        value_fn=lambda raw, i=(phase - 1) * 2: _semicolon_field(raw, i),
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for phase in (1, 2, 3)
) + tuple(
    AmperfiedWallboxSensorDescription(
        key=f"current_phase_{phase}",
        translation_key=f"current_phase_{phase}",
        topic=TOPIC_POWERMETER_SENSOR,
        value_fn=lambda raw, i=(phase - 1) * 2 + 1: _semicolon_field(raw, i),
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for phase in (1, 2, 3)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sets up the sensor entities for this config entry."""
    coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AmperfiedWallboxSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class AmperfiedWallboxSensor(CoordinatorEntity[AmperfiedWallboxCoordinator], SensorEntity):
    """Represents a single telemetry value of the wallbox."""

    entity_description: AmperfiedWallboxSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmperfiedWallboxCoordinator,
        entry: ConfigEntry,
        description: AmperfiedWallboxSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Any:
        """Extracts the value from coordinator.data for this topic.

        Uses entity_description.value_fn if given (for semicolon-separated
        or nested-JSON topics); otherwise falls back to unwrapping a
        "value" key if the raw payload is a dict, or returning it as-is.
        """
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self.entity_description.topic)
        if raw is None:
            return None
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(raw)
        if isinstance(raw, dict) and "value" in raw:
            return raw["value"]
        return raw

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Optional extra attributes via entity_description.attributes_fn."""
        if self.coordinator.data is None or self.entity_description.attributes_fn is None:
            return None
        raw = self.coordinator.data.get(self.entity_description.topic)
        if raw is None:
            return None
        return self.entity_description.attributes_fn(raw)
