"""Unit tests for binary_sensor.py, using the recorded telemetry fixtures."""
from __future__ import annotations

from typing import Any

from custom_components.amperfied_wallbox.binary_sensor import (
    AmperfiedWallboxDefaultPasswordBinarySensor,
    AmperfiedWallboxEvConnectedBinarySensor,
)
from custom_components.amperfied_wallbox.const import TOPIC_CONF_INITIAL_PASSWORD

from .helpers import FakeCoordinator, FakeEntry


class TestEvConnected:
    def test_false_when_idle(self, telemetry_idle: dict[str, Any]) -> None:
        sensor = AmperfiedWallboxEvConnectedBinarySensor(FakeCoordinator(telemetry_idle), FakeEntry())
        assert sensor.is_on is False

    def test_true_when_charging(self, telemetry_charging: dict[str, Any]) -> None:
        sensor = AmperfiedWallboxEvConnectedBinarySensor(FakeCoordinator(telemetry_charging), FakeEntry())
        assert sensor.is_on is True

    def test_none_when_no_data_yet(self) -> None:
        sensor = AmperfiedWallboxEvConnectedBinarySensor(FakeCoordinator({}), FakeEntry())
        assert sensor.is_on is None


class TestUsingDefaultPassword:
    def test_false(self) -> None:
        data = {TOPIC_CONF_INITIAL_PASSWORD: {"value": False}}
        sensor = AmperfiedWallboxDefaultPasswordBinarySensor(FakeCoordinator(data), FakeEntry())
        assert sensor.is_on is False

    def test_true(self) -> None:
        data = {TOPIC_CONF_INITIAL_PASSWORD: {"value": True}}
        sensor = AmperfiedWallboxDefaultPasswordBinarySensor(FakeCoordinator(data), FakeEntry())
        assert sensor.is_on is True

    def test_none_when_no_data_yet(self) -> None:
        sensor = AmperfiedWallboxDefaultPasswordBinarySensor(FakeCoordinator({}), FakeEntry())
        assert sensor.is_on is None
