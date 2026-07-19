# Project context for Claude Code

## What's being built here

A **Home Assistant custom integration** for the Amperfied/Heidelberg connect.solar wallbox
(HDM-SMART-CONNECT series). The wallbox doesn't speak an open protocol, but an internal
MQTT5-over-WebSocket API that was reverse-engineered from the wallbox's web UI.

**The full protocol documentation is in `PROTOCOL.md`** – read this file first, before you
start coding. It contains the auth flow, all known topics, payload formats, and a working
synchronous reference script.

## Target architecture

Native `custom_components/amperfied_wallbox/` integration following HA conventions, so it can
later be shared via HACS. Core requirements:

1. **Async from the start.** HA runs entirely on `asyncio`. Please use `aiomqtt` (successor
   to `asyncio-mqtt`) instead of `paho-mqtt`, or if `paho-mqtt` is used, embed its callback API
   cleanly into the HA event loop (`hass.async_add_executor_job` only if truly necessary, not
   as a default solution).
2. **`DataUpdateCoordinator`** for the telemetry topics, so entities don't each poll
   individually but get updated centrally. Since the wallbox *pushes* though (no polling API),
   a push-based coordinator (`async_set_updated_data`) is a better fit than an
   `update_interval` timer.
3. **`config_flow.py`** for setup via the HA UI: wallbox host/IP, username, password. Please
   use `async_step_user` with a connection test (log in once, check whether `api/resp/login`
   responds with `{}`) before saving the config entry.
4. **Token management** as its own class/module (`api.py` or `auth.py`) that:
   - encapsulates the login flow
   - automatically refreshes the access token roughly every 8 minutes (timer/task, no blocking
     sleep)
   - handles reconnects cleanly on connection loss (the WebSocket connection can drop, e.g.
     when the wallbox is briefly offline) -- done: exponential backoff reconnect, entities
     marked unavailable for the duration (`coordinator.async_set_update_error`, live-verified
     with a forced disconnect), `ConfigEntryNotReady` if the wallbox is unreachable at HA
     startup, and a reauth flow if the password stops working after setup (see `api.py`'s
     `on_connection_lost`/`on_persistent_auth_failure` callbacks and `config_flow.py`'s
     `async_step_reauth`)
5. **Entities:**
   - `sensor.*` for: charging power, total energy, PCB temperature, EV status, wallbox status,
     energy manager status, current phase count, power limit
   - `button.*` for: manual charge authorization (`energymanager/authenticate`)
   - optionally `binary_sensor.*` for "EV connected" (derived from `evState != A1`)
   - the RFID list rather as an attribute of a sensor or as a `diagnostics` export, not as a
     flood of dedicated entities (4 cards is no reason for 4 entities)
6. **Translations:** `strings.json` + `translations/en.json` + `translations/de.json` for the
   config flow (see the scaffold, already set up as placeholders).
7. **`manifest.json`**: `iot_class` should be `local_push` (the wallbox actively pushes
   telemetry over the open WebSocket connection), not `local_polling`.
8. **Design policy: read-primary.** This integration deliberately stays read-primary. Telemetry,
   diagnostics, and device info are fully in scope; write/config actions are only added after an
   explicit, deliberate decision, and only for things with low blast radius if something goes
   wrong (e.g. manually authorizing a charge session). Setting the power/current limit, phase
   switching, PV surplus toggling, and RFID management are **intentionally not implemented**,
   even where the command topic and payload shape are known -- misconfiguring wallbox
   hardware/firmware settings via HA carries a real risk of hardware damage or a bricked device.
   Don't add these without being asked to explicitly.

## Status

Core functionality is done and live-verified: connect/login, `api/cmd/user/refreshAuth`-based
token refresh (password only needed once, at initial setup), auto-discovery of the device
prefix (no need to ask the user for it), 24 sensors (incl. per-phase power/voltage/current,
solar surplus/grid/house power, charge authorization source, last charge session), 2 binary
sensors (EV connected, using default password), manual charge authorization, a `get_charge_log`
service, RFID/device-detail diagnostics, device info (firmware/hardware version, serial, MAC
addresses) on the HA device page, and resilience (`ConfigEntryNotReady`/`ConfigEntryAuthFailed`
at setup, reauth flow, unavailability marking + auto-recovery on connection loss, debug
logging via the standard HA per-integration logger). Also supports multiple wallboxes as
separate config entries (no `single_config_entry` restriction).

Static analysis of the wallbox's own frontend JS bundle (served at `/assets/index-*.js`) has
proven to be a very productive way to find command topics and payload shapes without needing to
trigger every action manually in the UI while sniffing -- see PROTOCOL.md's "Not yet
reverse-engineered / not implemented (by design)" section for what's been found this way. Per
the read-primary policy above, most of those findings are deliberately not wired into `api.py`.

## Starting point for the first session

1. Read `PROTOCOL.md`
2. Look over the scaffold in `custom_components/amperfied_wallbox/` (already set up, partly
   placeholders/TODOs)
3. First finish implementing `api.py`/`auth.py` and **test it in isolation** (a small test
   script outside of HA that connects, logs in, refreshes the token) -- only then wire it into
   the coordinator and entities
4. Then `config_flow.py` and `__init__.py` (config entry setup/unload)
5. Then entities (`sensor.py`, `button.py`)
6. Run `hassfest` validation (`python -m script.hassfest` from a HA core checkout, or via the
   GitHub Action if no local HA core checkout is available)

## Test environment

The real wallbox is reachable at `192.168.0.123` (self-signed TLS certificate, certificate
verification must be disabled). Credentials are not in this repo -- please never commit
passwords or tokens, use the `secrets.yaml`/`.env` pattern and add it to `.gitignore`.

**Important limitation:** this is a single, standalone wallbox (`"mode": "leader"` per its own
device info, but with no followers actually attached). Everything in this repo -- protocol
docs, api.py, entities -- has only ever been verified against this one wallbox in isolation.
Multi-wallbox "grid" setups (leader + followers on one circuit, see the `wallboxgrid/*` topics
found in the frontend JS) are architecturally anticipated in a couple of places (e.g.
`async_discover_device_prefix()`'s "most frequent prefix" logic) but never actually tested,
since no such grid is available. Don't assume grid behavior works correctly without dedicated
testing against a real grid -- see README.md's "Known limitation" section.
