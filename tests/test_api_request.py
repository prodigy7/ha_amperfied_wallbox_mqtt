"""Regression test for the _async_request race condition.

_pending_responses is keyed only by resp_topic (the wallbox protocol has no
per-request correlation ID), so two requests in flight concurrently on the
same resp_topic used to overwrite each other's future -- one request's
response would resolve the *other* request's future (or, if that one had
already finished, get silently dropped and the first request would hang
until timeout). Fixed in api.py via a per-resp_topic asyncio.Lock that
serializes concurrent requests to the same topic. See PROTOCOL.md and the
docstring on AmperfiedWallboxClient._async_request.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.amperfied_wallbox.api import AmperfiedWallboxClient


class _FakeMessage:
    def __init__(self, topic: str, payload: str) -> None:
        self.topic = topic
        self.payload = payload


class _FakeMqttClient:
    """Stands in for aiomqtt.Client: records publishes and, after a
    configurable delay, delivers a canned response back through the real
    client's _async_handle_message -- simulating the wallbox replying
    asynchronously over the network.
    """

    def __init__(self, owner: AmperfiedWallboxClient, responses: dict[str, tuple[float, dict]]) -> None:
        self._owner = owner
        self._responses = responses

    async def subscribe(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, payload: str) -> None:
        delay, resp_payload = self._responses[payload]

        async def _deliver() -> None:
            await asyncio.sleep(delay)
            resp_topic = f"{self._owner._device_prefix}/api/resp/clog/get"
            await self._owner._async_handle_message(
                _FakeMessage(resp_topic, json.dumps(resp_payload))
            )

        asyncio.create_task(_deliver())


@pytest.mark.asyncio
async def test_concurrent_requests_to_same_resp_topic_do_not_corrupt_each_other() -> None:
    client = AmperfiedWallboxClient("host", "prefix", "user", "pass")

    payload_a = json.dumps({"marker": "A"})
    payload_b = json.dumps({"marker": "B"})
    responses = {
        # A's response arrives *later* than B's -- if the two requests' futures
        # weren't serialized, B's (earlier, faster) publish would overwrite A's
        # entry in _pending_responses before A's response arrives.
        payload_a: (0.05, {"marker": "A", "result": "first"}),
        payload_b: (0.01, {"marker": "B", "result": "second"}),
    }
    client._client = _FakeMqttClient(client, responses)

    result_a, result_b = await asyncio.gather(
        client._async_request("api/cmd/clog/get", "api/resp/clog/get", {"marker": "A"}),
        client._async_request("api/cmd/clog/get", "api/resp/clog/get", {"marker": "B"}),
    )

    assert result_a == {"marker": "A", "result": "first"}
    assert result_b == {"marker": "B", "result": "second"}


@pytest.mark.asyncio
async def test_concurrent_requests_to_different_resp_topics_run_in_parallel() -> None:
    """Serialization is per-topic, not global -- unrelated request types
    (e.g. clog/get vs rfidList/get) must still be able to run concurrently.
    """
    client = AmperfiedWallboxClient("host", "prefix", "user", "pass")

    class _MultiTopicFakeClient:
        def __init__(self, owner: AmperfiedWallboxClient) -> None:
            self._owner = owner

        async def subscribe(self, topic: str) -> None:
            return None

        async def publish(self, topic: str, payload: str) -> None:
            resp_topic = "api/resp/clog/get" if "clog" in topic else "api/resp/rfidList/get"

            async def _deliver() -> None:
                await asyncio.sleep(0.05)
                await self._owner._async_handle_message(
                    _FakeMessage(
                        f"{self._owner._device_prefix}/{resp_topic}",
                        json.dumps({"ok": True}),
                    )
                )

            asyncio.create_task(_deliver())

    client._client = _MultiTopicFakeClient(client)

    async def _timed_request(cmd_topic: str, resp_topic: str) -> float:
        start = asyncio.get_running_loop().time()
        await client._async_request(cmd_topic, resp_topic, {})
        return asyncio.get_running_loop().time() - start

    duration_a, duration_b = await asyncio.gather(
        _timed_request("api/cmd/clog/get", "api/resp/clog/get"),
        _timed_request("api/cmd/rfidList/get", "api/resp/rfidList/get"),
    )

    # If these were serialized against each other (bug: a single global lock
    # instead of one per resp_topic), the second request would take ~2x as
    # long as the per-request delay. Both should complete in ~one delay.
    assert duration_a < 0.09
    assert duration_b < 0.09


@pytest.mark.asyncio
async def test_hung_subscribe_times_out_instead_of_blocking_forever() -> None:
    """subscribe()/publish() must be inside the overall timeout window.

    Previously they were awaited *before* entering the asyncio.timeout(...)
    block, so a stuck/half-broken connection (subscribe()/publish() never
    returning, e.g. mid-reconnect) would hang forever with no time limit at
    all -- and since this holds the per-resp_topic lock, every other queued
    request to the same topic would then also wait forever behind it. Seen
    in practice: HA shutdown logs showing multiple
    _async_refresh_last_charge_session background tasks all still pending
    at once.
    """
    client = AmperfiedWallboxClient("host", "prefix", "user", "pass")

    class _HangingFakeClient:
        async def subscribe(self, topic: str) -> None:
            await asyncio.sleep(999)

        async def publish(self, topic: str, payload: str) -> None:
            raise AssertionError("should never be reached, subscribe() never returns")

    client._client = _HangingFakeClient()

    with pytest.raises(TimeoutError):
        await client._async_request(
            "api/cmd/clog/get", "api/resp/clog/get", {}, timeout=0.05
        )

    # The lock must have been released despite the timeout, so a second
    # request to the same topic isn't wedged behind the first forever.
    client._client = _HangingFakeClient()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            client._async_request("api/cmd/clog/get", "api/resp/clog/get", {}, timeout=0.05),
            timeout=1.0,
        )
