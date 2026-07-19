"""Unit tests for button.py: each button's press_fn must call the matching
client method, and nothing else.
"""
from __future__ import annotations

import pytest

from custom_components.amperfied_wallbox.button import (
    BUTTON_DESCRIPTIONS,
    AmperfiedWallboxButton,
)

from .helpers import FakeCoordinator, FakeEntry


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def async_authenticate_charging(self) -> None:
        self.calls.append("authenticate")

    async def async_pause_charging(self) -> None:
        self.calls.append("pause")

    async def async_resume_charging(self) -> None:
        self.calls.append("resume")


def _button_for(key: str, client: FakeClient) -> AmperfiedWallboxButton:
    description = next(d for d in BUTTON_DESCRIPTIONS if d.key == key)
    return AmperfiedWallboxButton(FakeCoordinator({}, client), FakeEntry(), description)


class TestButtonPress:
    @pytest.mark.asyncio
    async def test_authenticate_charging_calls_matching_client_method(self) -> None:
        client = FakeClient()
        await _button_for("authenticate_charging", client).async_press()
        assert client.calls == ["authenticate"]

    @pytest.mark.asyncio
    async def test_pause_charging_calls_matching_client_method(self) -> None:
        client = FakeClient()
        await _button_for("pause_charging", client).async_press()
        assert client.calls == ["pause"]

    @pytest.mark.asyncio
    async def test_resume_charging_calls_matching_client_method(self) -> None:
        client = FakeClient()
        await _button_for("resume_charging", client).async_press()
        assert client.calls == ["resume"]

    def test_three_distinct_buttons_with_unique_ids(self) -> None:
        client = FakeClient()
        entry = FakeEntry()
        buttons = [
            AmperfiedWallboxButton(FakeCoordinator({}, client), entry, description)
            for description in BUTTON_DESCRIPTIONS
        ]
        unique_ids = {button.unique_id for button in buttons}
        assert len(unique_ids) == 3
