"""Unit tests for switch.py: the Boost switch's is_on must track emState, and
turn_on/turn_off must call the matching client method.
"""
from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.amperfied_wallbox.api import AmperfiedWallboxConnectionError
from custom_components.amperfied_wallbox.const import TOPIC_EM_STATE
from custom_components.amperfied_wallbox.switch import AmperfiedWallboxBoostSwitch

from .helpers import FakeCoordinator, FakeEntry


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def async_set_boost(self, enable: bool) -> None:
        self.calls.append(enable)


class TimingOutFakeClient:
    async def async_set_boost(self, enable: bool) -> None:
        raise TimeoutError("no response on api/resp/energymanager/force/set")


class DisconnectedFakeClient:
    async def async_set_boost(self, enable: bool) -> None:
        raise AmperfiedWallboxConnectionError("Not connected")


def _switch_for(data: dict[str, object], client: object) -> AmperfiedWallboxBoostSwitch:
    return AmperfiedWallboxBoostSwitch(FakeCoordinator(data, client), FakeEntry())


class TestBoostSwitchState:
    def test_is_on_when_force_current(self) -> None:
        switch = _switch_for({TOPIC_EM_STATE: "ForceCurrent"}, FakeClient())
        assert switch.is_on is True

    def test_is_off_for_other_states(self) -> None:
        switch = _switch_for({TOPIC_EM_STATE: "Available"}, FakeClient())
        assert switch.is_on is False

    def test_is_none_when_topic_unknown(self) -> None:
        switch = _switch_for({}, FakeClient())
        assert switch.is_on is None

    def test_unwraps_dict_wrapped_value(self) -> None:
        switch = _switch_for({TOPIC_EM_STATE: {"value": "ForceCurrent"}}, FakeClient())
        assert switch.is_on is True


class TestBoostSwitchActions:
    @pytest.mark.asyncio
    async def test_turn_on_calls_set_boost_true(self) -> None:
        client = FakeClient()
        await _switch_for({}, client).async_turn_on()
        assert client.calls == [True]

    @pytest.mark.asyncio
    async def test_turn_off_calls_set_boost_false(self) -> None:
        client = FakeClient()
        await _switch_for({}, client).async_turn_off()
        assert client.calls == [False]

    @pytest.mark.asyncio
    async def test_timeout_becomes_home_assistant_error(self) -> None:
        switch = _switch_for({}, TimingOutFakeClient())
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_on()

    @pytest.mark.asyncio
    async def test_connection_error_becomes_home_assistant_error(self) -> None:
        switch = _switch_for({}, DisconnectedFakeClient())
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_on()
