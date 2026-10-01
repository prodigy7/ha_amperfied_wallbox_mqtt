"""Unit tests for the DeviceInfo that AmperfiedWallboxCoordinator.async_setup()
builds from the one-time factory-topic snapshot.
"""
from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.amperfied_wallbox.const import (
    TOPIC_EOL_PRODUCT_NAME,
    TOPIC_EOL_SOFTWARE_VERSION,
)
from custom_components.amperfied_wallbox.coordinator import AmperfiedWallboxCoordinator

from .helpers import FakeEntry


class _FakeClient:
    def __init__(self, device_data: dict[str, Any]) -> None:
        self._device_data = device_data

    async def async_connect(self) -> None:
        return None

    async def async_get_device_info(self) -> dict[str, Any]:
        return self._device_data

    async def async_subscribe_telemetry(self, callback: Any) -> None:
        return None

    async def async_get_charge_log(self, **kwargs: Any) -> dict[str, Any]:
        return {}


class _FakeEntry(FakeEntry):
    def async_on_unload(self, func: Any) -> None:
        return None


async def _setup(tmp_path: Any, device_data: dict[str, Any]) -> AmperfiedWallboxCoordinator:
    hass = HomeAssistant(str(tmp_path))
    coordinator = AmperfiedWallboxCoordinator(hass, _FakeEntry(), _FakeClient(device_data))
    await coordinator.async_setup()
    return coordinator


@pytest.mark.asyncio
async def test_model_taken_from_product_name(tmp_path: Any) -> None:
    coordinator = await _setup(
        tmp_path,
        {TOPIC_EOL_PRODUCT_NAME: "connect.home", TOPIC_EOL_SOFTWARE_VERSION: {"value": "5.1.0"}},
    )

    assert coordinator.device_info["model"] == "connect.home"
    assert coordinator.device_info["sw_version"] == "5.1.0"


@pytest.mark.asyncio
async def test_model_falls_back_to_connect_solar(tmp_path: Any) -> None:
    coordinator = await _setup(tmp_path, {})

    assert coordinator.device_info["model"] == "connect.solar"
