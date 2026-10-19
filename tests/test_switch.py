"""Unit tests for switch.py: the Boost switch's is_on must track emState,
turn_on must gate on an active session and a known hwCurrentLimit and pass
that current through, and turn_off must call the matching client method.
"""
from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.amperfied_wallbox.api import AmperfiedWallboxConnectionError
from custom_components.amperfied_wallbox.const import (
    TOPIC_CONF_HW_CURRENT_LIMIT,
    TOPIC_EM_STATE,
    TOPIC_ENERGYMANAGER_SESSION,
)
from custom_components.amperfied_wallbox.switch import AmperfiedWallboxBoostSwitch

from .helpers import FakeCoordinator, FakeEntry

ACTIVE_SESSION = {TOPIC_ENERGYMANAGER_SESSION: {"begin": "2026-01-15T20:00:00+0200"}}


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, float | None]] = []

    async def async_set_boost(self, enable: bool, current: float | None = None) -> None:
        self.calls.append((enable, current))


class TimingOutFakeClient:
    async def async_set_boost(self, enable: bool, current: float | None = None) -> None:
        raise TimeoutError("no response on api/resp/energymanager/force/set")


class DisconnectedFakeClient:
    async def async_set_boost(self, enable: bool, current: float | None = None) -> None:
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


class TestBoostSwitchTurnOn:
    @pytest.mark.asyncio
    async def test_calls_set_boost_true_with_configured_current(self) -> None:
        client = FakeClient()
        data = {**ACTIVE_SESSION, TOPIC_CONF_HW_CURRENT_LIMIT: {"value": 20.0}}
        await _switch_for(data, client).async_turn_on()
        assert client.calls == [(True, 20.0)]

    @pytest.mark.asyncio
    async def test_raises_without_active_session(self) -> None:
        """Must not even attempt the request without a session -- mirrors the
        web UI's own precondition for its Boost button (see PR #9).
        """
        client = FakeClient()
        data = {TOPIC_ENERGYMANAGER_SESSION: {}, TOPIC_CONF_HW_CURRENT_LIMIT: {"value": 16.0}}
        with pytest.raises(HomeAssistantError):
            await _switch_for(data, client).async_turn_on()
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_raises_without_known_current(self) -> None:
        """Must never guess/fall back to a hardcoded current (see PR #9: this
        is exactly the bug that was fixed).
        """
        client = FakeClient()
        with pytest.raises(HomeAssistantError):
            await _switch_for(ACTIVE_SESSION, client).async_turn_on()
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_timeout_becomes_home_assistant_error(self) -> None:
        data = {**ACTIVE_SESSION, TOPIC_CONF_HW_CURRENT_LIMIT: {"value": 16.0}}
        switch = _switch_for(data, TimingOutFakeClient())
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_on()

    @pytest.mark.asyncio
    async def test_connection_error_becomes_home_assistant_error(self) -> None:
        data = {**ACTIVE_SESSION, TOPIC_CONF_HW_CURRENT_LIMIT: {"value": 16.0}}
        switch = _switch_for(data, DisconnectedFakeClient())
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_on()


class TestBoostSwitchTurnOff:
    @pytest.mark.asyncio
    async def test_calls_set_boost_false(self) -> None:
        client = FakeClient()
        await _switch_for({}, client).async_turn_off()
        assert client.calls == [(False, None)]

    @pytest.mark.asyncio
    async def test_does_not_require_a_session_or_current(self) -> None:
        """Turning off is always allowed -- force/reset takes no payload."""
        client = FakeClient()
        await _switch_for({TOPIC_ENERGYMANAGER_SESSION: {}}, client).async_turn_off()
        assert client.calls == [(False, None)]

    @pytest.mark.asyncio
    async def test_timeout_becomes_home_assistant_error(self) -> None:
        switch = _switch_for({}, TimingOutFakeClient())
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_off()

    @pytest.mark.asyncio
    async def test_connection_error_becomes_home_assistant_error(self) -> None:
        switch = _switch_for({}, DisconnectedFakeClient())
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_off()
