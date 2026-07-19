"""Async API client for the Amperfied Wallbox.

Implements the auth flow documented in PROTOCOL.md (user/auth -> login),
token refresh, and telemetry subscription, async via aiomqtt (MQTT5 over
WebSocket). See CLAUDE.md for the architectural requirements.

DESIGN POLICY: this integration is deliberately read-primary. Only a small,
carefully chosen set of write actions is implemented (manual charge
authorization). Setting the charging power/current limit, phase switching,
PV surplus toggling, and RFID management are intentionally NOT implemented
here, even though their command topics are documented in PROTOCOL.md --
misconfiguring wallbox hardware/firmware settings via HA carries a real risk
of hardware damage or a bricked device, which isn't worth the convenience.
Don't add these without an explicit, deliberate decision to do so.

TODO (see PROTOCOL.md, "Not yet reverse-engineered" section):
- Phase switching, PV surplus charging on/off, RFID management
  (rename/add/delete) are still completely missing (and, per the policy
  above, deliberately out of scope for now).
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any
from uuid import uuid4

import aiomqtt

from .const import (
    ALL_TELEMETRY_TOPICS,
    CMD_CLOG_GET,
    CMD_ENERGYMANAGER_AUTHENTICATE,
    CMD_LOGIN,
    CMD_RFID_LIST_GET,
    CMD_USER_AUTH,
    CMD_USER_REFRESH_AUTH,
    DEFAULT_MQTT_PATH,
    DEFAULT_PORT,
    RESP_CLOG_GET,
    RESP_ENERGYMANAGER_AUTHENTICATE,
    RESP_LOGIN,
    RESP_RFID_LIST_GET,
    RESP_USER_AUTH,
    RESP_USER_REFRESH_AUTH,
    TOKEN_REFRESH_INTERVAL_SECONDS,
    TOPIC_CONF_INITIAL_PASSWORD,
    TOPIC_CONF_PARAGRAPH14A,
    TOPIC_EOL_BOX_DATE,
    TOPIC_EOL_BOX_PART,
    TOPIC_EOL_BOX_SERIAL,
    TOPIC_EOL_ETH0_MAC,
    TOPIC_EOL_HARDWARE_VERSION,
    TOPIC_EOL_HCB_DATE,
    TOPIC_EOL_HCB_PART,
    TOPIC_EOL_HCB_SERIAL,
    TOPIC_EOL_HMI_DATE,
    TOPIC_EOL_HMI_PART,
    TOPIC_EOL_HMI_SERIAL,
    TOPIC_EOL_INCO_AVAILABLE,
    TOPIC_EOL_MID_AVAILABLE,
    TOPIC_EOL_MID_IDENTIFICATION,
    TOPIC_EOL_PLC_AVAILABLE,
    TOPIC_EOL_PRODUCT_NAME,
    TOPIC_EOL_RELAIS_AVAILABLE,
    TOPIC_EOL_RFID_AVAILABLE,
    TOPIC_EOL_RS485_AVAILABLE,
    TOPIC_EOL_SOFTWARE_VARIANT,
    TOPIC_EOL_SOFTWARE_VERSION,
    TOPIC_EOL_VAN30,
    TOPIC_EOL_WIFI_MAC,
)

_LOGGER = logging.getLogger(__name__)

# Callback type: called for every received message with (topic, parsed_payload_or_None).
MessageCallback = Callable[[str, dict[str, Any] | Any], Awaitable[None]]

# After a connection drop: backoff between reconnect attempts.
_RECONNECT_BACKOFF_INITIAL_SECONDS = 1.0
_RECONNECT_BACKOFF_MAX_SECONDS = 60.0
_REQUEST_TIMEOUT_SECONDS = 10.0
_DISCOVERY_TIMEOUT_SECONDS = 5.0


class AmperfiedWallboxAuthError(Exception):
    """Login failed (wrong password, etc.)."""


class AmperfiedWallboxConnectionError(Exception):
    """Could not establish/maintain the connection to the wallbox."""


async def async_discover_device_prefix(
    host: str, port: int = DEFAULT_PORT, timeout: float = _DISCOVERY_TIMEOUT_SECONDS
) -> str:
    """Auto-discovers the device's MQTT topic prefix (e.g. "hdm-smart-connect-abc123").

    Most users don't know their wallbox's mDNS hostname suffix. Instead of
    asking for it, connect anonymously and subscribe to the bare MQTT
    wildcard "#" (not "<prefix>/#", since the prefix isn't known yet) -- the
    broker still delivers its own retained topics, so incoming topics reveal
    the prefix (everything before "/api/"). Live-verified against a real
    wallbox, see PROTOCOL.md.

    Collects messages for the full timeout window and returns the most
    frequently seen prefix, in case other devices' topics are ever bridged
    onto the same broker (e.g. a wallbox grid leader/follower setup).
    """
    prefix_counts: dict[str, int] = {}
    try:
        async with aiomqtt.Client(
            hostname=host,
            port=port,
            transport="websockets",
            websocket_path=DEFAULT_MQTT_PATH,
            protocol=aiomqtt.ProtocolVersion.V5,
            tls_params=aiomqtt.TLSParameters(cert_reqs=ssl.CERT_NONE),
            tls_insecure=True,
            identifier=f"ha-amperfied-discover-{uuid4().hex[:8]}",
        ) as client:
            await client.subscribe("#")
            try:
                async with asyncio.timeout(timeout):
                    async for message in client.messages:
                        topic = str(message.topic)
                        if "/api/" in topic:
                            prefix = topic.split("/api/")[0]
                            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
            except TimeoutError:
                pass
    except aiomqtt.MqttError as err:
        raise AmperfiedWallboxConnectionError(
            f"Failed to connect to {host}:{port}: {err}"
        ) from err

    if not prefix_counts:
        raise AmperfiedWallboxConnectionError(
            f"Could not auto-discover the device prefix from {host}:{port} "
            "(no matching topic received within timeout)"
        )
    return max(prefix_counts, key=lambda p: prefix_counts[p])


class AmperfiedWallboxClient:
    """Encapsulates connection, login, and token refresh against the wallbox.

    Usage:

        client = AmperfiedWallboxClient(host, device_prefix, username, password)
        await client.async_connect()
        await client.async_subscribe_telemetry(callback)
        ...
        await client.async_disconnect()
    """

    def __init__(
        self,
        host: str,
        device_prefix: str,
        username: str,
        password: str,
        port: int = 443,
    ) -> None:
        self._host = host
        self._port = port
        self._device_prefix = device_prefix
        self._username = username
        self._password = password

        self._access_token: str | None = None
        self._refresh_token: str | None = None

        self._client: aiomqtt.Client | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._supervisor_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None
        self._closing = False

        self._telemetry_callback: MessageCallback | None = None
        self._pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._request_locks: dict[str, asyncio.Lock] = {}

        # Optional hooks for the caller (see set_callbacks docstring).
        self._on_connection_lost: Callable[[Exception], None] | None = None
        self._on_persistent_auth_failure: Callable[[], None] | None = None
        self._auth_failure_notified = False

    def set_callbacks(
        self,
        *,
        on_connection_lost: Callable[[Exception], None] | None = None,
        on_persistent_auth_failure: Callable[[], None] | None = None,
    ) -> None:
        """Registers optional hooks for connection health, called from
        _async_supervise's reconnect loop (i.e. only for drops *after* the
        initial connection succeeded -- the first attempt's failure is
        raised directly from async_connect() instead).

        on_connection_lost(err): called every time the connection drops and
        a reconnect attempt begins. Intended for
        coordinator.async_set_update_error(), so entities show as
        unavailable during an extended outage instead of silently keeping
        stale values forever. Clears itself automatically: the next
        successful telemetry update already resets a DataUpdateCoordinator's
        last_update_success, no explicit "restored" hook needed.

        on_persistent_auth_failure(): called once when a *reconnect*
        (not the initial connection) fails due to bad credentials -- e.g.
        the wallbox password was changed after setup. Intended for
        ConfigEntry.async_start_reauth(). Only fires once per outage (reset
        after the next successful login) to avoid spamming reauth triggers
        on every retry.
        """
        self._on_connection_lost = on_connection_lost
        self._on_persistent_auth_failure = on_persistent_auth_failure

    def _topic(self, relative_topic: str) -> str:
        """Builds the full topic including the device prefix."""
        return f"{self._device_prefix}/{relative_topic}"

    @staticmethod
    def _extract_json(raw_payload: str) -> dict[str, Any] | None:
        """Extracts JSON from a raw payload string.

        Some response topics contain a client-identifier prefix before the
        actual JSON (e.g. "mqttjs<hex>..."). See PROTOCOL.md, "Payload format
        quirk" section. The robust strategy is to cut from the first "{".
        """
        idx = raw_payload.find("{")
        if idx == -1:
            return None
        try:
            return json.loads(raw_payload[idx:])
        except json.JSONDecodeError:
            _LOGGER.debug("Could not parse payload as JSON: %r", raw_payload)
            return None

    @staticmethod
    def _parse_telemetry_value(raw: str) -> Any:
        """Parses a telemetry payload as best-effort.

        Many values are valid JSON (numbers, bools, `{"value": ...}`), some
        are raw strings (e.g. "A1" or "0;0;0"). If JSON parsing fails, the
        raw string is returned as-is.
        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def async_connect(self) -> None:
        """Establishes the connection and performs the initial login.

        Afterwards starts a supervisor task that processes incoming messages
        and automatically reconnects with backoff on connection loss
        (including a fresh login and re-subscribing telemetry topics), plus
        a task for the periodic token refresh.

        If the *first* connection/login attempt fails, the corresponding
        exception is raised here (important for the connection test in
        config_flow). Later disconnects are handled internally without
        crashing the integration.
        """
        if self._supervisor_task is not None:
            return

        _LOGGER.debug("Connecting to %s:%s (prefix %r)", self._host, self._port, self._device_prefix)
        self._closing = False
        first_attempt: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._supervisor_task = asyncio.create_task(self._async_supervise(first_attempt))
        try:
            await first_attempt
        except BaseException:
            self._supervisor_task = None
            raise

        _LOGGER.debug("Connected and logged in")
        self._refresh_task = asyncio.create_task(self._async_schedule_token_refresh())

    async def async_disconnect(self) -> None:
        """Disconnects cleanly and stops all background tasks."""
        _LOGGER.debug("Disconnecting")
        self._closing = True
        for task in (self._refresh_task, self._supervisor_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, aiomqtt.MqttError):
                pass
        self._refresh_task = None
        self._supervisor_task = None
        await self._async_close_connection()

    async def _async_supervise(self, first_attempt: asyncio.Future[None]) -> None:
        """Keeps the connection alive: connects, logs in, listens for
        messages, and reconnects with exponential backoff on failure.

        If the very first attempt fails, the exception is set on
        `first_attempt` and the task ends (no retry) -- so e.g. the
        config_flow connection test gets an immediate, clear error instead
        of retrying forever in the background.
        """
        backoff = _RECONNECT_BACKOFF_INITIAL_SECONDS
        is_first_attempt = True

        while not self._closing:
            message_task: asyncio.Task | None = None
            try:
                await self._async_open_connection()
                # The message loop MUST be running before we log in: the
                # login handshake waits on futures that can only be resolved
                # by the running consumer (_async_handle_message).
                # Otherwise _async_login() deadlocks on its first await.
                message_task = asyncio.create_task(self._async_consume_messages())

                await self._async_refresh_token()
                # A login just succeeded on this connection -- any future
                # auth failure is a new occurrence, not a continuation of a
                # previously-notified one.
                self._auth_failure_notified = False

                if self._telemetry_callback is not None:
                    for topic in ALL_TELEMETRY_TOPICS:
                        await self._client.subscribe(self._topic(topic))
                    _LOGGER.debug("Subscribed to %d telemetry topics", len(ALL_TELEMETRY_TOPICS))

                if is_first_attempt and not first_attempt.done():
                    first_attempt.set_result(None)
                else:
                    _LOGGER.debug("Reconnected successfully")
                is_first_attempt = False
                backoff = _RECONNECT_BACKOFF_INITIAL_SECONDS

                await message_task
                raise AmperfiedWallboxConnectionError(
                    "MQTT message stream ended unexpectedly"
                )
            except asyncio.CancelledError:
                raise
            except (AmperfiedWallboxAuthError, AmperfiedWallboxConnectionError, aiomqtt.MqttError) as err:
                if is_first_attempt:
                    if not first_attempt.done():
                        if isinstance(err, aiomqtt.MqttError):
                            err = AmperfiedWallboxConnectionError(str(err))
                        first_attempt.set_exception(err)
                    return
                _LOGGER.warning(
                    "Lost wallbox connection (%s), reconnecting in %.0f s", err, backoff
                )
                if self._on_connection_lost is not None:
                    self._on_connection_lost(err)
                if isinstance(err, AmperfiedWallboxAuthError) and not self._auth_failure_notified:
                    self._auth_failure_notified = True
                    _LOGGER.debug("Notifying persistent auth failure (likely a changed password)")
                    if self._on_persistent_auth_failure is not None:
                        self._on_persistent_auth_failure()
            finally:
                if message_task is not None:
                    message_task.cancel()
                    try:
                        await message_task
                    except (asyncio.CancelledError, aiomqtt.MqttError):
                        pass
                await self._async_close_connection()

            if self._closing:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX_SECONDS)

    async def _async_open_connection(self) -> None:
        """Opens the WSS/MQTT5 connection (without logging in)."""
        self._client = aiomqtt.Client(
            hostname=self._host,
            port=self._port,
            transport="websockets",
            websocket_path=DEFAULT_MQTT_PATH,
            protocol=aiomqtt.ProtocolVersion.V5,
            tls_params=aiomqtt.TLSParameters(cert_reqs=ssl.CERT_NONE),
            tls_insecure=True,
            identifier=f"ha-amperfied-{uuid4().hex[:8]}",
        )
        self._exit_stack = AsyncExitStack()
        try:
            await self._exit_stack.enter_async_context(self._client)
        except aiomqtt.MqttError as err:
            self._client = None
            _LOGGER.debug("MQTT connection failed: %s", err)
            raise AmperfiedWallboxConnectionError(
                f"Failed to connect to {self._host}:{self._port}: {err}"
            ) from err
        _LOGGER.debug("MQTT connection established")

    async def _async_consume_messages(self) -> None:
        """Continuously reads incoming messages and dispatches them.

        Runs as a background task in parallel with the login handshake and
        with later requests, since those wait on futures resolved here.
        """
        assert self._client is not None
        async for message in self._client.messages:
            await self._async_handle_message(message)

    async def _async_close_connection(self) -> None:
        """Discards the current connection and all pending requests."""
        for fut in self._pending_responses.values():
            if not fut.done():
                fut.cancel()
        self._pending_responses.clear()

        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except aiomqtt.MqttError:
                pass
            self._exit_stack = None
        self._client = None

    async def _async_request(
        self,
        cmd_topic: str,
        resp_topic: str,
        payload: dict[str, Any],
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Performs a cmd/resp request-response cycle.

        Subscribes to resp_topic first (to avoid a race condition, see
        PROTOCOL.md), then publishes cmd_topic and waits for the response.

        Serialized per resp_topic: the wallbox protocol has no per-request
        correlation ID, only the response topic name, so two requests in
        flight concurrently on the same resp_topic would otherwise overwrite
        each other's future in _pending_responses and one would hang until
        timeout (seen in practice: coordinator startup's explicit charge-log
        refresh racing a concurrent one triggered by retained EV-state
        telemetry).
        """
        if self._client is None:
            raise AmperfiedWallboxConnectionError("Not connected")

        lock = self._request_locks.setdefault(resp_topic, asyncio.Lock())
        async with lock:
            # Deliberately never log `payload` -- it can contain the plaintext
            # password (user/auth) or tokens (login, refreshAuth).
            _LOGGER.debug("Request: %s -> %s", cmd_topic, resp_topic)
            fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending_responses[resp_topic] = fut
            try:
                await self._client.subscribe(self._topic(resp_topic))
                await self._client.publish(self._topic(cmd_topic), json.dumps(payload))
                async with asyncio.timeout(timeout):
                    result = await fut
                    _LOGGER.debug("Response received: %s", resp_topic)
                    return result
            except TimeoutError:
                _LOGGER.debug(
                    "Request timed out: %s (no response on %s)", cmd_topic, resp_topic
                )
                raise
            finally:
                self._pending_responses.pop(resp_topic, None)

    async def _async_login(self) -> None:
        """Performs the full auth flow: user/auth -> login.

        See PROTOCOL.md, "Authentication flow" section. Only needed once, at
        initial connection setup (or as a fallback if user/refreshAuth ever
        fails, e.g. an expired refresh token) -- see _async_refresh_token(),
        which is what callers should normally use.
        """
        _LOGGER.debug("Performing full password login (user/auth)")
        try:
            auth_resp = await self._async_request(
                CMD_USER_AUTH,
                RESP_USER_AUTH,
                {"name": self._username, "password": self._password},
            )
        except TimeoutError as err:
            raise AmperfiedWallboxConnectionError(
                "Timeout during login (api/resp/user/auth did not respond)"
            ) from err

        if not isinstance(auth_resp, dict) or "accessToken" not in auth_resp:
            raise AmperfiedWallboxAuthError(
                f"Login failed, unexpected response to user/auth: {auth_resp!r}"
            )

        self._access_token = auth_resp["accessToken"]
        self._refresh_token = auth_resp.get("refreshToken", self._refresh_token)
        _LOGGER.debug("Password login succeeded")

        await self._async_authorize_connection()

    async def _async_authorize_connection(self) -> None:
        """Sends api/cmd/login with the current access token to authorize
        this connection (see PROTOCOL.md, "Authentication flow").
        """
        try:
            await self._async_request(
                CMD_LOGIN, RESP_LOGIN, {"accessToken": self._access_token}
            )
        except TimeoutError as err:
            raise AmperfiedWallboxConnectionError(
                "Timeout during login (api/resp/login did not respond)"
            ) from err

    async def _async_refresh_token(self) -> None:
        """Refreshes the access/refresh tokens, preferring
        api/cmd/user/refreshAuth (no password needed) over a full
        api/cmd/user/auth login.

        Falls back to the full password login if there's no refresh token
        yet (very first connection) or if refreshAuth fails for any reason
        (e.g. the refresh token itself expired, see PROTOCOL.md -- token
        lifetime is ~84 days). Live-verified against a real wallbox.
        """
        if self._refresh_token is not None:
            _LOGGER.debug("Refreshing token via user/refreshAuth (no password needed)")
            try:
                refresh_resp = await self._async_request(
                    CMD_USER_REFRESH_AUTH,
                    RESP_USER_REFRESH_AUTH,
                    {"refreshToken": self._refresh_token},
                )
            except TimeoutError:
                refresh_resp = None

            if isinstance(refresh_resp, dict) and "accessToken" in refresh_resp:
                self._access_token = refresh_resp["accessToken"]
                self._refresh_token = refresh_resp.get("refreshToken", self._refresh_token)
                _LOGGER.debug("Token refresh succeeded")
                await self._async_authorize_connection()
                return

            _LOGGER.warning(
                "user/refreshAuth failed, falling back to a full password login"
            )

        await self._async_login()

    async def _async_schedule_token_refresh(self) -> None:
        """Refreshes the access token every TOKEN_REFRESH_INTERVAL_SECONDS.

        Never blocks the event loop (asyncio.sleep). If the connection is
        currently down (reconnect in progress in _async_supervise), this
        cycle is skipped -- the reconnect will perform a fresh login anyway.
        """
        while True:
            await asyncio.sleep(TOKEN_REFRESH_INTERVAL_SECONDS)
            if self._client is None:
                continue
            try:
                await self._async_refresh_token()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Token refresh failed, retrying in %s s",
                    TOKEN_REFRESH_INTERVAL_SECONDS,
                )

    async def _async_handle_message(self, message: aiomqtt.Message) -> None:
        """Routes incoming messages to response futures or the telemetry
        callback.
        """
        topic = str(message.topic)
        prefix = f"{self._device_prefix}/"
        if not topic.startswith(prefix):
            return
        relative_topic = topic[len(prefix):]

        payload = message.payload
        raw = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)

        if relative_topic.startswith("api/resp/"):
            fut = self._pending_responses.get(relative_topic)
            if fut is not None and not fut.done():
                fut.set_result(self._extract_json(raw) or {})
            return

        if self._telemetry_callback is not None:
            await self._telemetry_callback(relative_topic, self._parse_telemetry_value(raw))

    async def async_subscribe_telemetry(self, callback: MessageCallback) -> None:
        """Subscribes to all topics in const.ALL_TELEMETRY_TOPICS.

        callback is called for every incoming message with
        (relative_topic, parsed_value). Intended for the DataUpdateCoordinator
        (async_set_updated_data).
        """
        self._telemetry_callback = callback
        if self._client is not None:
            for topic in ALL_TELEMETRY_TOPICS:
                await self._client.subscribe(self._topic(topic))

    async def async_get_rfid_list(self) -> list[dict[str, Any]]:
        """Fetches the RFID card list (api/cmd/rfidList/get -> rfidList/get).

        See PROTOCOL.md: there is no server-side search/filter, the server
        always returns the full list.
        """
        resp = await self._async_request(
            CMD_RFID_LIST_GET, RESP_RFID_LIST_GET, {"accessToken": self._access_token}
        )
        return resp.get("rfidList", [])

    async def async_authenticate_charging(self) -> None:
        """Manually authorizes charging without RFID (api/cmd/energymanager/authenticate)."""
        await self._async_request(
            CMD_ENERGYMANAGER_AUTHENTICATE,
            RESP_ENERGYMANAGER_AUTHENTICATE,
            {"source": "web", "label": self._username},
        )

    async def async_get_charge_log(
        self, filter_after: str, filter_before: str, log_type: str = "text/json"
    ) -> dict[str, Any]:
        """Fetches the charging session history for a time window (api/cmd/clog/get).

        filter_after/filter_before are ISO-8601 time strings, e.g.
        "2026-07-18T16:00:00+0200". IMPORTANT (live-verified, see
        PROTOCOL.md): the wallbox interprets the time-of-day digits as local
        time and does not appear to convert the offset correctly -- UTC-
        normalized timestamps (e.g. with "+0000") return empty results for
        time windows that demonstrably contain charging sessions. Always
        pass the actual local wall-clock time
        (`datetime.now().astimezone()`), never convert to UTC.

        log_type MUST be the literal string "text/json" -- this is not an
        enum of "text" OR "json" as the original documentation suggested;
        any other value (including just "json") returns
        `{"exception": {"msg": "invalid argument", "id": 14}}`.
        """
        return await self._async_request(
            CMD_CLOG_GET,
            RESP_CLOG_GET,
            {"filter_after": filter_after, "filter_before": filter_before, "type": log_type},
            # The wallbox's own frontend uses a 30s timeout for this command
            # (ChargelogGet:{Topic:"clog/get",Timeout:3e4}); match it here,
            # since it can legitimately take longer than the 10s default.
            timeout=30.0,
        )

    async def _async_snapshot_topics(
        self, topics: list[str], timeout: float = 5.0
    ) -> dict[str, Any]:
        """Fetches a one-time snapshot of a set of retained topics.

        Returns a dict keyed by *relative topic* (not a friendly name), with
        the same raw (still-dict-wrapped-where-applicable) values telemetry
        callbacks receive -- so callers can merge the result directly into a
        telemetry-style data store and reuse the usual `{"value": ...}`
        unwrap logic.

        Safe to call regardless of whether async_subscribe_telemetry() has
        already been set up: temporarily chains onto the existing telemetry
        callback (if any) instead of replacing it, and restores it
        afterwards.
        """
        if self._client is None:
            raise AmperfiedWallboxConnectionError("Not connected")

        wanted = set(topics)
        collected: dict[str, Any] = {}
        done = asyncio.Event()
        previous_callback = self._telemetry_callback

        async def _collector(topic: str, value: Any) -> None:
            if previous_callback is not None:
                await previous_callback(topic, value)
            if topic in wanted and topic not in collected:
                collected[topic] = value
                if len(collected) == len(wanted):
                    done.set()

        self._telemetry_callback = _collector
        try:
            for topic in wanted:
                await self._client.subscribe(self._topic(topic))
            try:
                async with asyncio.timeout(timeout):
                    await done.wait()
            except TimeoutError:
                pass
        finally:
            self._telemetry_callback = previous_callback

        return collected

    async def async_get_device_info(self, timeout: float = 5.0) -> dict[str, Any]:
        """Fetches the small set of factory topics needed for `DeviceInfo`
        (sw_version, hw_version, serial_number) and the "still on default
        password" security check, keyed by relative topic so the result can
        be merged straight into `coordinator.data` like telemetry.
        """
        return await self._async_snapshot_topics(
            [
                TOPIC_EOL_SOFTWARE_VERSION,
                TOPIC_EOL_HARDWARE_VERSION,
                TOPIC_EOL_BOX_SERIAL,
                TOPIC_EOL_ETH0_MAC,
                TOPIC_EOL_WIFI_MAC,
                TOPIC_CONF_INITIAL_PASSWORD,
            ],
            timeout=timeout,
        )

    async def async_get_diagnostics_device_details(self, timeout: float = 5.0) -> dict[str, Any]:
        """Fetches the broader set of factory/regulatory topics that are
        only useful for the diagnostics export (part numbers, serials,
        production dates, which optional hardware modules are installed,
        the built-in MID meter's own identification, §14a EnWG status) --
        not needed often enough to justify dedicated entities.
        """
        return await self._async_snapshot_topics(
            [
                TOPIC_EOL_PRODUCT_NAME,
                TOPIC_EOL_SOFTWARE_VARIANT,
                TOPIC_EOL_VAN30,
                TOPIC_EOL_BOX_PART,
                TOPIC_EOL_BOX_DATE,
                TOPIC_EOL_HCB_PART,
                TOPIC_EOL_HCB_SERIAL,
                TOPIC_EOL_HCB_DATE,
                TOPIC_EOL_HMI_PART,
                TOPIC_EOL_HMI_SERIAL,
                TOPIC_EOL_HMI_DATE,
                TOPIC_EOL_RELAIS_AVAILABLE,
                TOPIC_EOL_MID_AVAILABLE,
                TOPIC_EOL_RFID_AVAILABLE,
                TOPIC_EOL_PLC_AVAILABLE,
                TOPIC_EOL_RS485_AVAILABLE,
                TOPIC_EOL_INCO_AVAILABLE,
                TOPIC_EOL_MID_IDENTIFICATION,
                TOPIC_CONF_PARAGRAPH14A,
            ],
            timeout=timeout,
        )
