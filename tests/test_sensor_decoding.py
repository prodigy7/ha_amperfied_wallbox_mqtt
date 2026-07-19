"""Unit tests for sensor.py's decoding helpers and native_value/attributes.

Uses the recorded telemetry fixtures (tests/fixtures/*.json, real snapshots
from a live wallbox) instead of hand-rolled data, so these tests double as
a regression check against actually-observed payload shapes.
"""
from __future__ import annotations

from typing import Any

import pytest

from custom_components.amperfied_wallbox.sensor import (
    SENSOR_DESCRIPTIONS,
    AmperfiedWallboxSensor,
    _charge_permission_attributes,
    _charge_permission_source,
    _grid_field,
    _grid_field_sum,
    _last_session_attributes,
    _last_session_energy,
    _semicolon_field,
)

from .helpers import FakeCoordinator, FakeEntry


def _sensor_for(data: dict[str, Any], key: str) -> AmperfiedWallboxSensor:
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
    return AmperfiedWallboxSensor(FakeCoordinator(data), FakeEntry(), description)


class TestSemicolonField:
    def test_extracts_by_index(self) -> None:
        assert _semicolon_field("3054;3070;2965", 0) == 3054.0
        assert _semicolon_field("3054;3070;2965", 2) == 2965.0

    def test_alternating_voltage_current_layout(self) -> None:
        raw = "229.29;13.533;230.53;13.551;230.44;13.018"
        assert _semicolon_field(raw, 0) == 229.29  # voltage L1
        assert _semicolon_field(raw, 1) == 13.533  # current L1
        assert _semicolon_field(raw, 4) == 230.44  # voltage L3

    def test_out_of_range_returns_none(self) -> None:
        assert _semicolon_field("0;0;0", 5) is None

    def test_non_string_returns_none(self) -> None:
        assert _semicolon_field(None, 0) is None
        assert _semicolon_field({"value": "x"}, 0) is None


class TestGridField:
    def test_field_and_sum(self) -> None:
        raw = {"surplusPower": 42.0, "gridPower": [1.0, 2.0, 3.0]}
        assert _grid_field(raw, "surplusPower") == 42.0
        assert _grid_field_sum(raw, "gridPower") == 6.0

    def test_non_dict_returns_none(self) -> None:
        assert _grid_field(None, "surplusPower") is None
        assert _grid_field_sum("not a dict", "gridPower") is None

    def test_missing_key_returns_none(self) -> None:
        assert _grid_field_sum({}, "gridPower") is None


class TestChargePermission:
    def test_source_and_attributes_for_rfid(self) -> None:
        raw = {
            "uuid": "de:ad:be:ef:00:11:22",
            "cardnum": "-",
            "label": "Autoschlüssel Fob",
            "source": "rfid",
            "timestamp": "2026-07-18T16:18:32Z",
        }
        assert _charge_permission_source(raw) == "rfid"
        attrs = _charge_permission_attributes(raw)
        assert attrs == {"label": "Autoschlüssel Fob", "timestamp": "2026-07-18T16:18:32Z"}
        # uuid/cardnum identify a physical RFID card -- must never leak into attributes.
        assert "uuid" not in attrs
        assert "cardnum" not in attrs

    def test_empty_permission_is_none(self) -> None:
        assert _charge_permission_source({}) == "none"
        assert _charge_permission_attributes({}) == {}


class TestLastSession:
    def test_energy_and_attributes(self) -> None:
        raw = {
            "energy": 0.064,
            "begin": "2026-07-18T18:18:32+0200",
            "end": "2026-07-18T18:19:25+0200",
            "chargingDuration": 28,
            "sessionDuration": 53,
            "authentication": {
                "source": "rfid",
                "label": "Autoschlüssel Fob",
                "uuid": "should-never-appear",
            },
        }
        assert _last_session_energy(raw) == 0.064
        attrs = _last_session_attributes(raw)
        assert attrs["source"] == "rfid"
        assert attrs["label"] == "Autoschlüssel Fob"
        assert attrs["chargingDuration"] == 28
        assert "uuid" not in attrs


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("charging_power", 0),
        ("total_energy", 1999.167),
        ("pcb_temperature", 34.0),
        ("ev_state", "A1"),
        ("wallbox_state", "Available"),
        ("power_limit", 0),
        ("energy_manager_state", "Available"),
        ("active_phases", 3),
        ("limiter", "nocar"),
        ("phase_switch_state", "Ready"),
        ("charge_permission_source", "none"),
        ("surplus_power", 0.0),
        ("grid_power", 0.0),
        ("house_power", 0.0),
        ("power_phase_1", 0.0),
        ("voltage_phase_1", 232.97),
        ("current_phase_1", 0.0),
    ],
)
def test_native_value_idle(telemetry_idle: dict[str, Any], key: str, expected: Any) -> None:
    assert _sensor_for(telemetry_idle, key).native_value == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("charging_power", 9089),
        ("ev_state", "C2"),
        ("wallbox_state", "Charging"),
        ("power_limit", 9660),
        ("energy_manager_state", "LimitCurrent"),
        ("limiter", "none"),
        ("charge_permission_source", "rfid"),
        ("power_phase_1", 3054.0),
        ("power_phase_2", 3070.0),
        ("power_phase_3", 2965.0),
        ("voltage_phase_1", 229.29),
        ("current_phase_1", 13.533),
        ("voltage_phase_3", 230.44),
        ("current_phase_3", 13.018),
    ],
)
def test_native_value_charging(telemetry_charging: dict[str, Any], key: str, expected: Any) -> None:
    assert _sensor_for(telemetry_charging, key).native_value == expected


def test_last_charge_session_sensor(telemetry_idle: dict[str, Any]) -> None:
    sensor = _sensor_for(telemetry_idle, "last_charge_session_energy")
    assert sensor.native_value == 0.064
    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["source"] == "rfid"
    assert "uuid" not in attrs


def test_charge_permission_source_rich_rfid_attributes(telemetry_charging: dict[str, Any]) -> None:
    sensor = _sensor_for(telemetry_charging, "charge_permission_source")
    assert sensor.native_value == "rfid"
    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["label"] == "Autoschlüssel Fob"
    assert "uuid" not in attrs
    assert "cardnum" not in attrs


def test_all_sensor_descriptions_have_unique_keys() -> None:
    keys = [d.key for d in SENSOR_DESCRIPTIONS]
    assert len(keys) == len(set(keys))
