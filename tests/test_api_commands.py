"""Unit tests for AmperfiedWallboxClient's simple cmd/resp wrapper methods
(authenticate/pause/resume): each must publish to the right topic with the
right payload shape.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.amperfied_wallbox.api import AmperfiedWallboxClient


class _RecordingFakeClient:
    """Records every publish and immediately acks with {} on the resp topic."""

    def __init__(self, owner: AmperfiedWallboxClient) -> None:
        self._owner = owner
        self.published: list[tuple[str, str]] = []

    async def subscribe(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, payload: str) -> None:
        self.published.append((topic, payload))
        resp_topic = topic.replace("/cmd/", "/resp/")

        class _FakeMessage:
            def __init__(self, topic: str, payload: str) -> None:
                self.topic = topic
                self.payload = payload

        asyncio.get_running_loop().call_soon(
            lambda: asyncio.ensure_future(
                self._owner._async_handle_message(_FakeMessage(resp_topic, "{}"))
            )
        )


@pytest.mark.asyncio
async def test_authenticate_charging_sends_web_source_and_username() -> None:
    client = AmperfiedWallboxClient("host", "prefix", "someuser", "pass")
    fake = _RecordingFakeClient(client)
    client._client = fake

    await client.async_authenticate_charging()

    assert fake.published == [
        ("prefix/api/cmd/energymanager/authenticate", json.dumps({"source": "web", "label": "someuser"}))
    ]


@pytest.mark.asyncio
async def test_pause_charging_sends_empty_payload() -> None:
    client = AmperfiedWallboxClient("host", "prefix", "user", "pass")
    fake = _RecordingFakeClient(client)
    client._client = fake

    await client.async_pause_charging()

    assert fake.published == [("prefix/api/cmd/energymanager/pause", json.dumps({}))]


@pytest.mark.asyncio
async def test_resume_charging_sends_empty_payload() -> None:
    client = AmperfiedWallboxClient("host", "prefix", "user", "pass")
    fake = _RecordingFakeClient(client)
    client._client = fake

    await client.async_resume_charging()

    assert fake.published == [("prefix/api/cmd/energymanager/resume", json.dumps({}))]
