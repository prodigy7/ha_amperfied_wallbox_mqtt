# Amperfied Heidelberg connect.solar – MQTT API protocol

Reverse-engineered from the wallbox's web UI (model: HDM-SMART-CONNECT, software 5.1.1,
backend "bosch", mode "leader"). This documentation is the foundation for the Home Assistant
integration in this repo.

**Important caveat: single standalone wallbox only.** The device this was reverse-engineered
against reports `"mode": "leader"`, but has no followers actually attached -- everything here
is verified against one wallbox in isolation, never against a real multi-wallbox "grid" setup
(several wallboxes load-balancing one shared circuit; see `wallboxgrid/*` topics under
"Other commands found in the topic registry" below). Topics/behavior may differ when a wallbox
is actually grouped with others -- e.g. `loadbalancer/grid/monitor/leader`'s `connectors` array
might contain more than the single entry always observed here.

## Device info

- Hostname/mDNS: `HDM-SMART-CONNECT-<suffix>.local` (example: `HDM-SMART-CONNECT-abc123`)
- Connection: **MQTT5 over WebSocket (WSS)**, port 443, path `/mqtt`
- TLS: self-signed certificate → certificate verification must be disabled
- All topics are organized under a device prefix: `{hostname}/api/...`
  (example: `hdm-smart-connect-abc123/api/t/power/evState`)

### Auto-discovering the device prefix (no need to ask the user)

Most users don't know their wallbox's mDNS hostname/topic prefix. Live-verified: connecting
anonymously and subscribing to the **bare MQTT wildcard `#`** (not `<prefix>/#`, since the
prefix isn't known yet) still makes the broker deliver its own retained topics -- the topic of
the first incoming message reveals the prefix (everything before `/api/`). Implemented in
`api.py` as `async_discover_device_prefix()`, used by `config_flow.py` so the setup form only
asks for host/username/password.

### Device/factory info (`api/eol/...`, `api/conf/...`)

Retained, mostly static topics with useful hardware/firmware info, live-captured via a bare
`#` wildcard subscribe:

| Topic | Example value | Meaning |
|---|---|---|
| `api/eol/config/hostname` | `{"value":"HDM-SMART-CONNECT-abc123"}` | Device hostname |
| `api/eol/config/softwareVersion` | `{"value":"5.1.1"}` | Firmware version |
| `api/eol/config/softwareVariant` | `{"value":"HDM"}` | Firmware variant |
| `api/eol/config/hardwareVersion` | `{"value":"COMMODUL_V1"}` | Hardware revision |
| `api/eol/config/eth0_MAC` | `{"value":"006034abc124"}` | Ethernet MAC address |
| `api/eol/config/wifi_MAC` | `{"value":"006034abc123"}` | WiFi MAC address |
| `api/eol/config/van30` | `{"value":"00000000000000000000000"}` | Some kind of device/VAN identifier |
| `api/eol/canstartup/productName` | `connect.solar` | Product name (raw string, not JSON) |
| `api/eol/canstartup/boxPart` / `boxSerial` / `boxDate` | `00.779.3162` / `000123` / `4524` | Main PCB part number/serial/production date |
| `api/eol/canstartup/hcbPart` / `hcbSerial` / `hcbDate` | similar | Charge-control-board part number/serial/date |
| `api/eol/canstartup/hmiPart` / `hmiSerial` / `hmiDate` | similar | HMI (display/UI) board part number/serial/date |
| `api/eol/canstartup/relaisAvailable` / `midAvailable` / `rfidAvailable` / `plcAvailable` / `RS485available` / `incoAvailable` | `on`/`off` (raw strings) | Which optional hardware modules are installed |
| `api/eol/mid/identification` | `{"serial":"123456789","vendorName":"WAGO GmbH","productName":"879-3020 4PS","softwareVersion":"1.34","hardwareVersion":"1.04"}` | The built-in MID-certified energy meter's own identification (separate vendor: WAGO) |
| `api/conf/canstartup/paragraph14a` | `{"value":true}` | Whether §14a EnWG (German grid operator dimmable-device regulation) is active |
| `api/conf/mqttapi/user/initialPassword` | `{"value":false}` | Whether the wallbox is still on its factory-default password |

All of the above is now wired into the integration, live-verified:
- `softwareVersion`, `hardwareVersion`, `boxSerial`, `eth0_MAC`, `wifi_MAC` are fetched once at
  startup (`api.async_get_device_info()`) and populate the shared `DeviceInfo` object
  (`coordinator.device_info`, used by all entities) as `sw_version`/`hw_version`/
  `serial_number`/`connections` (MAC, formatted with colons) -- they show up on the HA device
  page.
- `mqttapi/user/initialPassword` is merged into `coordinator.data` like telemetry and drives
  `binary_sensor.using_default_password` (device_class `problem`) -- a security nudge to change
  the factory-default password, since this integration doesn't do that for you (read-primary
  policy, see below).
- Everything else in the table (part numbers/serials/production dates, installed hardware
  modules, the MID meter's own identification, §14a status, product name/variant, `van30`) is
  fetched once via `api.async_get_diagnostics_device_details()` and included in the
  `diagnostics.py` export -- not surfaced as entities, per CLAUDE.md's "4 cards is no reason for
  4 entities" philosophy applied more broadly to rarely-needed static info.

## Topic structure

| Prefix | Meaning | Behavior |
|---|---|---|
| `api/cmd/<action>` | Send a command (PUBLISH with JSON payload) | write |
| `api/resp/<action>` | Response to a `cmd` (SUBSCRIBE **before** publishing required) | request/response |
| `api/conf/<path>` | Configuration, retained | delivered immediately on subscribe, rarely changes |
| `api/t/<path>` | Live telemetry | pushed continuously |
| `api/eol/<path>` | Factory data (end-of-line), retained, static | reading once is enough |

**Important:** For `api/cmd/...` you must **always subscribe first** to the corresponding
`api/resp/...` topic before publishing the command, otherwise you miss the response
(race condition).

## Payload format quirk

Some `api/t/...` and `api/conf/...` topics contain MQTT5 user properties (timestamp `ts`) at
the start of the payload, e.g. as raw bytes: `\x14&\x00\x02ts\x00\r<epoch_ms><value>`.

If you use **paho-mqtt** (Python) or another MQTT5-capable library, these user properties are
automatically stripped from the payload -- `msg.payload` then contains only the clean value
(e.g. `A1` or `{"value":true}`). Response topics (`api/resp/...`) may additionally have a
client-identifier prefix (`mqttjs<hex>`), followed by the actual JSON. Rule of thumb when
parsing: **cut from the first `{`**, then parse normally as JSON.

For re-login (`api/cmd/login`, `api/cmd/user/auth`) the access token is additionally sent as
an MQTT5 **user property** named `accessToken` (not only in the JSON body). With paho-mqtt,
replicate this via a `properties` object; functionally it also worked in tests without this
user property (the server seems to primarily check the JSON body) -- still needs to be
verified in the integration.

## Authentication flow

1. **CONNECT** anonymously (MQTT5, no username/password in the CONNECT packet)
2. **SUBSCRIBE** to `api/resp/user/auth`
3. **PUBLISH** to `api/cmd/user/auth`:
   ```json
   {"name": "admin", "password": "<password>"}
   ```
4. **Response** on `api/resp/user/auth`:
   ```json
   {"refreshToken": "<jwt>", "accessToken": "<jwt>"}
   ```
5. **SUBSCRIBE** to `api/resp/login`
6. **PUBLISH** to `api/cmd/login`:
   ```json
   {"accessToken": "<jwt>"}
   ```
   → This elevates the broker permissions for **this one connection**. Only after this are
   protected topics (especially `api/t/loadbalancer/grid/monitor/+`) actually delivered.
7. **Response** on `api/resp/login`: `{}` → session is active.

**Wrong password**, live-verified: `api/resp/user/auth` responds with
`{"exception": {"id": 41, "msg": "wrong password"}}` instead of the token pair (no
`accessToken` key at all). `api.py` treats any response without an `accessToken` key as an
auth failure -- it doesn't pattern-match on this specific exception shape, so other `exception`
variants (if any exist) would be treated the same way.

### Token lifetime

- `accessToken`: **10 minutes** (check JWT claim `exp`, `iat`+600s)
- `refreshToken`: ~84 days (from earlier tests, lifetime itself not re-verified)
- **`api/cmd/user/refreshAuth` is live-verified and implemented** (see `api.py`,
  `_async_refresh_token()`): payload `{"refreshToken": "<refreshToken>"}`, response
  `{"accessToken","refreshToken"}` -- same shape as `user/auth`, but no password needed. After
  refreshing, `api/cmd/login` must still be (re-)sent with the new `accessToken` to keep the
  connection authorized. The integration now only sends the password once, at initial
  connection setup (or if `refreshAuth` itself ever fails, e.g. an expired refresh token, as a
  fallback). Discovered via the frontend JS bundle's topic registry
  (`UserRefreshAuth:{Topic:"user/refreshAuth",Timeout:3e4,Public:!0}`), then confirmed live.

## Known `api/cmd/...` commands

| Command topic | Payload | Response topic | Purpose |
|---|---|---|---|
| `api/cmd/user/auth` | `{"name","password"}` | `api/resp/user/auth` | Login, returns tokens |
| `api/cmd/user/refreshAuth` | `{"refreshToken"}` | `api/resp/user/refreshAuth` | Refresh tokens without the password (live-verified) |
| `api/cmd/login` | `{"accessToken"}` | `api/resp/login` | Authorize the session/connection |
| `api/cmd/user/get` | `{"id":"id-0"}` | `api/resp/user/get` | User info (name, roles) |
| `api/cmd/user/data/get` | `{"id":"id-0"}` | `api/resp/user/data/get` | User's UI settings (theme etc., irrelevant for the integration) |
| `api/cmd/rfidList/get` | `{}` | `api/resp/rfidList/get` | List of all RFID cards/fobs |
| `api/cmd/clog/get` | `{"filter_after","filter_before","type":"text/json"}` (see note below) | `api/resp/clog/get` | Charging history in a time window |
| `api/cmd/energymanager/authenticate` | `{"source":"web","label":"admin"}` | `api/resp/energymanager/authenticate` | Manual charge authorization without RFID |
| `api/cmd/energymanager/pause` | `{}` | `api/resp/energymanager/pause` | Pauses an active charging session without discarding `chargePermission` (live-verified, see "Observed pause/resume cycle" below) |
| `api/cmd/energymanager/resume` | `{}` | `api/resp/energymanager/resume` | Resumes a session paused via `energymanager/pause` (live-verified) |

**Confirmed:** search/filter/pagination in the web UI (e.g. for the RFID list) are purely
client-side in the browser JS. The server always returns the full list for `rfidList/get`,
regardless of the payload content (tested with `{}` and with search terms in the frontend).

**`clog/get` payload, live-verified (as of 2026-07-18) -- careful, the short form above is
misleading:**
- `type` is **not** an enum of `"text"` OR `"json"`, it must be **literally** the string
  `"text/json"`. Any other value (including just `"json"`) returns
  `{"exception": {"msg": "invalid argument", "id": 14}}`, regardless of the rest of the payload.
- `filter_after`/`filter_before` are optional and actually work (unlike `rfidList/get`, this
  one filters server-side), format as in the example below:
  `"2026-07-18T16:00:00+0200"`. Offset with or without a colon (`+0200` vs. `+02:00`) makes no
  difference -- **but the wallbox interprets the time-of-day digits as local time and does not
  appear to convert the offset correctly**: the same query with UTC-normalized times (`+0000`)
  returns `0` instead of the expected hits, even though the offset was formally correct. Always
  use the wallbox's actual local wall-clock time (in Python: `datetime.now().astimezone()`),
  never convert to UTC.
- A minimal payload of `{}` also works and returns the complete history unfiltered.
- The response is **not** a direct array, but `{"type": "text/json", "value": [...]}` -- the
  actual list of charging sessions is in the `value` key.
- Verified example payload: `{"filter_after": "2026-07-18T15:00:00+0200", "filter_before": "2026-07-18T19:00:00+0200", "type": "text/json"}`
- The wallbox's own frontend uses a 30s timeout for this command
  (`ChargelogGet:{Topic:"clog/get",Timeout:3e4}`); `api.py` matches that instead of the usual
  10s default, since it can legitimately take longer.

`coordinator.py` queries the last ~2 days once at startup and again every time the car is
unplugged (`evState` -> `A1`), storing the newest entry under a synthetic
`_last_charge_session` key that `sensor.last_charge_session_energy` reads -- this avoids
needing to call the `get_charge_log` service manually just to see the last session's energy,
duration, and authorization source.

### Design policy: read-primary, write actions deliberately minimized

This integration is intentionally **read-primary**. Telemetry, diagnostics, and device info are
fully in scope; write/config actions are only added after a deliberate, explicit decision, and
only for things with low blast radius if something goes wrong (e.g. manually authorizing a
charge session). Setting the power/current limit, phase switching, PV surplus toggling, and
RFID management are **deliberately not implemented** in `api.py`, even where the command topic
and payload shape are documented below -- misconfiguring wallbox hardware/firmware settings via
Home Assistant carries a real risk of hardware damage or a bricked device, which isn't worth the
convenience. The findings below exist for documentation completeness (and in case the calculus
ever changes), not as a to-do list.

### Not yet reverse-engineered / not implemented (by design)

Everything below was found by statically analyzing the frontend's own JavaScript bundle
(`/assets/index-*.js`, served by the wallbox itself), which contains a complete topic registry
plus the UI code that builds each command's payload. This is a much more reliable source than
guessing, but **none of it has been exercised live against the hardware**, and -- per the design
policy above -- it's not going to be wired into `api.py` without a deliberate reason to revisit
that decision.

- **Setting the charging power/current limit**: `api/cmd/energymanager/limit/set`. Payload
  built by the UI as:
  ```json
  {"retain": true, "value": <number>, "unit": "A", "source": "web", "phases": 1}
  ```
  or, for a power-based (not current-based) limit:
  ```json
  {"retain": true, "value": <number>, "unit": "W", "source": "web"}
  ```
  The UI lets the user pick between a current limit (Amps, `phases` = 1 or 3 required) and a
  power limit (Watts, no `phases` field) via a `limitType` selector (`"current"` vs `"power"`).
  Response topic presumably `api/resp/energymanager/limit/set` (not observed). Related,
  undocumented: `api/conf/energymanager/limit` (current config, read-only observed shape
  unknown) and `api/cmd/energymanager/force/set` / `energymanager/force/reset` (purpose unclear,
  possibly for forcing/overriding a charge state).

**Not implemented, by design (see read-primary policy above). Topic names and (partial) payload
shapes below are from the same frontend-JS static analysis, not live-tested:**

- **Phase switching (1-phase/3-phase)**: `api/cmd/power/phaseSwitch/config/set`, e.g.
  ```json
  {"waittime": <seconds>, "duration": <seconds>, "sim_carunplug": true}
  ```
  This looks like it configures *timing/debounce parameters* for the automatic phase switch
  logic (how long to wait, simulate-unplug duration), not a direct "switch to N phases now"
  command -- the actual UI control for that wasn't fully traced. Counterpart:
  `api/cmd/power/phaseSwitch/config/reset` with `{"list": ["waittime"]}` (reset specific keys
  to default).
- **PV surplus charging on/off and related load-management settings**:
  `api/cmd/strategy/config/set` (likely the actual full topic is
  `api/cmd/loadbalancer/strategy/config/set`, given the telemetry topic is
  `api/conf/loadbalancer/strategy/config` -- not confirmed). The UI sends a **partial** JSON
  object with just the changed fields (merged server-side), e.g.:
  ```json
  {"solar_surplus_supplement_enabled": true}
  {"current_sys_max_enabled": true, "current_sys_max": 16, "power_sys_max": 11000, "power_sys_max_enabled": false}
  {"current_grid_max": 32, "current_grid_max_enabled": true}
  {"power_available_offset": 0, "power_available_filter_time": 30}
  ```
  By analogy, toggling PV surplus itself is presumably just
  `{"solar_surplus_enabled": true}`. Counterpart `api/cmd/strategy/config/reset` takes
  `{"list": ["fieldname", ...]}` to reset specific fields to default.
- **RFID card management**:
  - Rename/modify: `api/cmd/rfidList/modify`, payload `{"rfidList": [{"uuid": "...", "label": "New label", ...}]}`
    (send the full card object with the changed field(s)); response `{"rfidList": [...]}` where
    each entry is either the updated card or `{"exception": {"msg": "..."}}` on error.
  - Delete: `api/cmd/rfidList/delete`, payload `{"rfidList": [{"uuid": "..."}]}` (just the UUIDs
    to remove).
  - Add (physical "teach-in", not an arbitrary UUID you can type in): `api/cmd/rfidList/teachIn/start`,
    payload `{"timeout": <seconds>}` -- the wallbox then waits for a physical card/fob tap and
    responds with `{"rfidList": [{"uuid": "<newly read uuid>"}]}` once one is presented.
    Abort via `api/cmd/rfidList/teachIn/abort`.

**Other commands found in the topic registry, not investigated further (purpose is largely
self-explanatory from the name, but payload shapes not traced):** `energymanager/auth/enable`,
`energymanager/lock/set`, `dateTime/set`,
`timeZone/set`, `ntp/set`/`ntp/enable`/`ntp/reset`, `network/ethernet/set`, `wlan/scan`/`wlan/select`/`wlan/reset`,
`system/reboot`, `system/factoryReset`, `system/backend/set`, `ocpp16/config/set`,
`modbustcp/*`, `user/add`/`user/modify`/`user/remove`/`user/changePwd`, `auth/secure/enable`,
`wallbox/mode/set` (switch between `"leader"` and presumably `"follower"`),
`wallboxgrid/scan`/`wallboxgrid/select`/`wallboxgrid/remove`/`wallboxgrid/restart`/
`wallboxgrid/follower/get` (managing a multi-wallbox load-balancing grid -- see the "single
standalone wallbox only" caveat at the top of this document; none of this was tested since no
grid was available).
Several of these are destructive (factory reset, reboot) or security-sensitive (password
change, secure-auth toggle) and should only ever be touched deliberately, never guessed at.

The `power/limiter` / `chargePermission.source` value space is larger than what's been observed
live so far; the frontend defines this enum (used for the `source` field across several
subsystems): `app`, `derating`, `dynLmm`, `staticLmm`, `emma`, `hems`, `key`, `key_sg`, `lms`,
`loadbalancer`, `modbustcp`, `nocar`, `none`, `ocpp`, `powermeterFailSafe`, `pv`, `schedule`,
`watchdog`, `web`. Note this doesn't include `em`, which *was* observed live as a `power/limiter`
value shortly after plugging in (see below) -- possibly a distinct/abbreviated code path, not
confirmed to be the same enum.

**Process for filling gaps:** keep the Tampermonkey sniffer active in the web UI, trigger the
desired action deliberately, export the log, then add it to this document. Alternatively,
static analysis of the wallbox's own frontend JS bundle (served at `/assets/index-*.js`) is a
productive shortcut -- it contains a full topic registry (`{ActionName:{Topic:"...",...}}`) and
the payload-construction code for every UI action, even for actions not yet exercised in the UI
during a sniffing session.

## Relevant telemetry topics (`api/t/...`)

| Topic | Example value | Meaning |
|---|---|---|
| `power/evState` | `A1` | EV state per EN 61851-1. Observed values: `A1`=no car (idle), `A2`=brief transitional state while unplugging (only visible for a fraction of a second), `B1`=plugged in, not yet authorized, `B2`=plugged in and authorized, waiting for charging to start, `C2`=actively charging |
| `power/temp` | `36.5` | PCB temperature °C |
| `power/phases` | `3` | Number of active phases |
| `power/powerLimit` | `0` | Current power limit in W (0 if no car/no charging, otherwise e.g. `9660`) |
| `power/limiter` | `nocar` | Reason for the current limit. Observed values: `nocar` (no car plugged in), `em` (briefly after plugging in, the energy manager is still deciding), `none` (car plugged in/charging, no active limiting by PV/load management) |
| `power/phaseSwitchState` | `{"value":"Ready"}` | Phase switching status |
| `powermeter/power` | `0` | Instantaneous power in W |
| `powermeter/energy` | `1998.418` | Total energy in kWh (meter reading) |
| `powermeter/powerPerPhases` | `0;0;0` | Power per phase (L1;L2;L3) |
| `powermeter/sensor` | `231.6;0;230.5;0;231.0;0` | Voltage/current alternating per phase |
| `chargectrl/wbState` | `Available` | Wallbox status. Observed values: `Available` (idle), `Preparing` (car just plugged in, EVSE side not yet ready/authorized), `SuspendedEVSE` (paused on the charging station side, e.g. briefly after authorization or while unplugging), `SuspendedEV` (paused on the car side -- among other things the state right after manually stopping via the RFID fob, even though still authorized), `Charging` (actively charging) |
| `energymanager/emState` | `Available` | Energy manager status. Observed values: `Available` (idle), `CarPlugedIn` (car just plugged in -- the "Pluged" typo is exactly as sent by the wallbox, deliberately documented unchanged), `LimitCurrent` (active charging resp. authorized, current is being limited/regulated), `LimitReset` (brief transition while unplugging, before returning to `Available`), `Pause` (charging paused via `energymanager/pause`, see below) |
| `energymanager/chargePermission` | `{}` or `{"source","label","timestamp"}` | Authorization details. Much richer for RFID authorization: `{"uuid","cardnum","secure","state","expiry","label","connectorList","source":"rfid","timestamp"}` (the complete card record from the RFID list). **Important:** manually stopping via the RFID fob while charging does **not** reset `chargePermission` -- the card stays remembered until the car is actually unplugged. `chargePermission` alone is therefore NOT suitable for detecting "currently charging"; use `wbState`/`evState` for that. |
| `loadbalancer/grid/monitor/leader` | large JSON, every ~5s | Complete grid/connector telemetry |

All of the above are wired into `sensor.py` (`power/limiter` and `power/phaseSwitchState` as
diagnostic-category sensors; `powermeter/powerPerPhases`/`powermeter/sensor` split into
per-phase power/voltage/current sensors via `value_fn`; `energymanager/chargePermission` as a
`charge_permission_source` sensor with label/timestamp attributes -- deliberately excluding
uuid/cardnum, same redaction policy as diagnostics.py; `loadbalancer/grid/monitor/leader`'s
`surplusPower`/`gridPower`/`housePower` fields as dedicated sensors, useful for PV-surplus
setups). Live-verified against a real wallbox.

### Observed state transition while unplugging (car charging -> car removed)

Recorded with the finished `api.py` client against a real wallbox during an active charging
session (`powermeter/power` ~9000 W, 3-phase). Timestamps relative to the observation start,
`t` in seconds:

```
[t=  24.9s] powermeter/power = 9001            # still charging
[t=  27.3s] power/evState = 'A2'               # transition, visible for only ~0.1s
[t=  27.3s] power/evState = 'A1'               # then idle (no car)
[t=  27.4s] energymanager/chargePermission = {}       # authorization automatically revoked
[t=  27.4s] energymanager/emState = 'LimitReset'
[t=  27.4s] chargectrl/wbState = 'SuspendedEVSE'
[t=  27.4s] powermeter/power = 298              # residual reading during ramp-down
[t=  27.4s] energymanager/emState = 'Available'
[t=  27.5s] chargectrl/wbState = 'Available'
[t=  29.8s] power/powerLimit = 0
[t=  29.8s] power/limiter = 'nocar'
[t=  29.9s] powermeter/power = 0
```

Summary of the sequence: `evState` drops first (via the brief intermediate state `A2`) to
`A1`, then `chargePermission` is discarded and `emState`/`wbState` each go through a brief
intermediate state (`LimitReset`/`SuspendedEVSE`) before landing on `Available`.
`powermeter/power` drops to 0 in two steps (residual value `298`, then `0` ~2.5s later, at the
same time as `powerLimit`/`limiter`, which are reset last). For a new charge authorization
after plugging in again, `energymanager/authenticate` (or RFID) must be called again, since
`chargePermission` does not automatically persist for the next plug-in.

### Observed complete charging cycle via RFID fob (plug in -> start -> stop -> unplug)

Recorded with `api.py` against the real wallbox: plug in the car, wait ~20s, start charging
via the RFID fob, wait ~20s (full power reached), stop charging via another fob tap, wait
~20s, unplug the car. Timestamps relative to the observation start:

```
[t=   2.2s] (idle) evState=A1 wbState=Available emState=Available
                    limiter=nocar powerLimit=0 chargePermission={}

[t=  47.1s] power/evState = 'B1'                          # car plugged in
[t=  47.1s] energymanager/emState = 'CarPlugedIn'          # (original typo, see above)
[t=  47.1s] chargectrl/wbState = 'Preparing'
[t=  51.5s] power/limiter = 'em'

[t=  71.0s] energymanager/chargePermission = {             # RFID fob tap: charging authorized
              'uuid': 'de:ad:be:ef:00:11:22', 'cardnum': '-', 'secure': False,
              'state': 1, 'expiry': '', 'label': 'Autoschlüssel Fob',
              'connectorList': [-1], 'source': 'rfid',
              'timestamp': '2026-07-18T16:18:32Z'
            }
[t=  71.0s] energymanager/emState = 'LimitCurrent'
[t=  71.0s] chargectrl/wbState = 'SuspendedEVSE'
[t=  71.3s] power/evState = 'B2'
[t=  71.5s] power/powerLimit = 9660
[t=  71.5s] chargectrl/wbState = 'SuspendedEV'
[t=  71.5s] power/limiter = 'none'
[t=  73.0s] power/evState = 'C2'                            # charging begins
[t=  74.2s] powermeter/power = 4
[t=  76.7s] powermeter/power = 1854
[t=  76.7s] chargectrl/wbState = 'Charging'
[t=  79.2s] powermeter/power = 9016                         # full power (3-phase)
             ... (stable at ~9000 W until t=101.7s) ...

[t= 104.2s] powermeter/power = 4                             # RFID fob tap: charging stopped
[t= 104.2s] chargectrl/wbState = 'SuspendedEV'
             # chargePermission stays unchanged! The card is still "remembered".

[t= 124.2s] power/evState = 'A2'                             # car unplugged
[t= 124.2s] power/evState = 'A1'
[t= 124.2s] power/powerLimit = 0
[t= 124.2s] chargectrl/wbState = 'SuspendedEVSE'
[t= 124.2s] power/limiter = 'nocar'
[t= 124.2s] energymanager/chargePermission = {}              # only now reset
[t= 124.2s] energymanager/emState = 'LimitReset'
[t= 124.3s] energymanager/emState = 'Available'
[t= 124.3s] chargectrl/wbState = 'Available'
[t= 126.7s] powermeter/power = 0
```

Findings:
- **Plugging in** first sets `evState=B1`, `emState=CarPlugedIn`, `wbState=Preparing`, shortly
  after `limiter=em` (the energy manager is still deciding on authorization/limit).
- **Authorizing via RFID** fills `chargePermission` with the full card record (not just
  `source`/`label`/`timestamp` as with web authorization), sets `powerLimit`, and runs through
  `wbState`: `Preparing` -> `SuspendedEVSE` -> `SuspendedEV`, `evState`: `B1` -> `B2`, before
  actually charging starts with `evState=C2`/`wbState=Charging`.
- **Stopping via another RFID tap** while charging immediately sets `powermeter/power` to ~0
  and `wbState` to `SuspendedEV` -- **`chargePermission` is left untouched**. This is the most
  important new finding: an integration must not use `chargePermission` as a signal for
  "currently charging", but must evaluate `wbState`/`evState` instead.
- **Unplugging** proceeds as described in the previous section (`evState` via `A2` to `A1`,
  then `chargePermission` discarded, `emState`/`wbState` via intermediate states to
  `Available`), regardless of whether authorization was previously via RFID or
  `energymanager/authenticate` (web).

### Observed pre-authorization before plug-in

Unlike the RFID cycle above (authorize *after* plugging in), calling `energymanager/authenticate`
*before* a car is plugged in (the "Laden freigeben" button in the idle `Available` state) leaves
the wallbox waiting with `chargePermission` already set and `evState` still `A1`. Live-verified:
plugging in the car afterwards skips the `B1` "waiting for authorization" state entirely and goes
straight to `evState=C2`/`wbState=Charging` -- the pending permission is consumed immediately, no
second authorization step needed. `chargePermission` itself is not re-issued/changed by this;
repeated `energymanager/authenticate` calls while a permission is already pending did not appear
to alter or refresh the existing `chargePermission` entry (same `source`/`label`/`timestamp` as
before, even with a different payload) -- consistent with the web UI itself never offering a
"cancel" action for the `Authenticated` state (see below), since a second authenticate call
wouldn't have any observable effect anyway.

**No cancel/deauthorize action while waiting for a car:** the wallbox's own frontend state
machine maps the `Authenticated` (waiting) state to a *disabled* button (`lblBtnWait`, "Wait...")
with no `buttonAction` at all -- confirmed by reading the frontend JS's state-to-button mapping.
There is no observed way to revoke a pending web authorization before a car is plugged in, short
of an eventual server-side timeout (not observed/confirmed either way).

### Observed pause/resume cycle (`energymanager/pause` / `energymanager/resume`)

Found in the frontend JS topic registry, and live-verified by using the wallbox's own "Laden
pausieren"/"Fortsetzen" buttons during an active charging session (`energymanager/pause` and
`.../resume`, both take/return `{}`). This is a **different mechanism from the RFID-fob stop**
documented in the charging-cycle section above:

```
[t=  0.0s] (charging) evState=C2 wbState=Charging emState=LimitCurrent powermeter/power=~9000

# "Laden pausieren" clicked (energymanager/pause):
[t=  8.5s] energymanager/emState = 'Pause'          # vs. RFID stop: emState unchanged
[t=  8.5s] chargectrl/wbState = 'SuspendedEVSE'      # vs. RFID stop: wbState = 'SuspendedEV'
[t= 13.1s] power/evState = 'C2' -> 'C1'
[t= 15.3s] power/evState = 'C1' -> 'B1'              # vs. RFID stop: evState unchanged
[t= 15.9s] power/powerLimit = 0, power/limiter = 'em'
             # settles at evState=B1, powerLimit=0, power=0 -- stays here indefinitely
             # chargePermission untouched (same source/label/timestamp throughout)

# "Fortsetzen" clicked (energymanager/resume):
[t=  3.5s] energymanager/emState = 'Pause' -> 'LimitCurrent'
[t=  5.8s] power/evState = 'B1' -> 'B2', wbState = 'SuspendedEV', powerLimit = 9660, limiter = 'none'
[t=  9.5s] power/evState = 'B2' -> 'C2'              # charging resumes
[t= 27.0s] chargectrl/wbState = 'SuspendedEV' -> 'Charging', powermeter/power back to ~9000
```

Findings:
- `energymanager/pause` drops the EV-side pilot signal all the way back to `evState=B1` (as if
  freshly plugged in but not yet authorized), unlike an RFID-fob stop which leaves `evState`
  unchanged. `wbState` also differs (`SuspendedEVSE` vs. `SuspendedEV`).
- `chargePermission` survives a pause/resume cycle unchanged, same as it survives an RFID stop --
  it is only ever discarded on an actual unplug (see the charging-cycle section above).
- `energymanager/resume` re-runs essentially the same state sequence as a fresh
  authorize+plug-in (`B1` -> `B2` -> `C2`, `wbState` `SuspendedEVSE` -> `SuspendedEV` ->
  `Charging`), just without needing a new authorization.
- Not wired into `api.py`/entities yet -- per the read-primary policy, pause/resume of an
  already-authorized, already-active session is arguably as low-blast-radius as the existing
  manual-authorization button, but adding entities for it is a deliberate decision to make
  separately, not a side effect of this documentation update.

### Example payload `loadbalancer/grid/monitor/leader`

```json
{
  "meterCurrent": [0.0, 0.0, 0.0],
  "meterPower": [0.0, 0.0, 0.0],
  "meterRequired": false,
  "meterConnected": true,
  "gridCurrent": [0.0, 0.0, 0.0],
  "gridPower": [0.0, 0.0, 0.0],
  "houseCurrent": [0.0, 0.0, 0.0],
  "housePower": [0.0, 0.0, 0.0],
  "surplusPower": 0.0,
  "chargingCnt": 0,
  "suspendedEvCnt": 0,
  "connectors": [
    {
      "id": "0",
      "evState": "A1",
      "connected": true,
      "input": {"value": 0.0, "phases": 0, "unit": "A", "source": "em", "reason": "idle"},
      "output": {"value": 0.0, "phases": 0, "unit": "A", "source": "em", "reason": "suspended"},
      "current": [0.0, 0.0, 0.0],
      "power": [0.0, 0.0, 0.0]
    }
  ]
}
```

## Example payload for the `clog/get` response

The response is **not** a direct array, but wrapped in `{"type", "value"}` -- `value` contains
the list of charging sessions (newest first, live-verified):

```json
{
  "type": "text/json",
  "value": [
    {
      "chargingDuration": 13605,
      "ocpp": [],
      "begin": "2026-07-12T12:14:05+0200",
      "end": "2026-07-12T21:39:41+0200",
      "unplugged": "2026-07-12T21:39:41+0200",
      "plugged": "2026-07-12T12:14:05+0200",
      "sessionDuration": 33935,
      "meter": {"source": "", "serial": "", "posBegin": 1964.623, "posEnd": 1998.164},
      "energy": 33.541,
      "solar": {"strategy": "", "gridEnergy": 33.54089, "solarSaving": 0.0, "solarEnergy": 0.000107},
      "label": "wallbox",
      "guid": "83e1c396-5ced-4415-8798-7b5f4d50ef28",
      "authentication": {
        "uuid": "de:ad:be:ef:00:11:22",
        "cardnum": "-",
        "label": "Autoschlüssel Fob",
        "source": "rfid",
        "secure": false
      },
      "cost": {"unit": 0.0, "total": 0.0}
    }
  ]
}
```

`authentication.source` can be `rfid` or `web`, among others (for web authorization via
`energymanager/authenticate`, `uuid`/`cardnum`/`secure` are missing, e.g.
`{"source":"web","label":"admin"}`).

## Example payload for the `rfidList/get` response

```json
{
  "total": 4,
  "rfidList": [
    {"uuid": "04:22:20:62:c0:11:90", "cardnum": "00000000000001006111", "secure": true, "state": 1, "expiry": "", "label": "", "connectorList": [-1]},
    {"uuid": "08:14:0b:e2", "cardnum": "-", "secure": false, "state": 1, "expiry": "", "label": "Google Pixel 8 - MB", "connectorList": [-1]},
    {"uuid": "de:ad:be:ef:00:11:22", "cardnum": "-", "secure": false, "state": 1, "expiry": "", "label": "Autoschlüssel Fob", "connectorList": [-1]}
  ]
}
```

## Working reference script (synchronous, paho-mqtt)

This script has proven itself in tests and serves as a functional reference. The HA
integration must replicate the same logic **async** (aiomqtt or asyncio-mqtt), since Home
Assistant runs entirely on asyncio and blocking calls in the event loop are forbidden.

```python
import paho.mqtt.client as mqtt
import ssl, json, threading

WALLBOX_HOST = "192.168.0.123"
WALLBOX_PORT = 443
PREFIX = "hdm-smart-connect-abc123"
USERNAME = "admin"
PASSWORD = "..."
REFRESH_INTERVAL = 480  # 8 min < 10 min token expiry

ACCESS_TOKEN = None

client = mqtt.Client(protocol=mqtt.MQTTv5, transport="websockets")
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)

def do_login(client):
    client.publish(f"{PREFIX}/api/cmd/user/auth",
                    json.dumps({"name": USERNAME, "password": PASSWORD}))

def get_rfid_list(client):
    client.publish(f"{PREFIX}/api/cmd/rfidList/get",
                    json.dumps({"accessToken": ACCESS_TOKEN}))

def authenticate_charging(client):
    client.publish(f"{PREFIX}/api/cmd/energymanager/authenticate",
                    json.dumps({"source": "web", "label": "admin"}))

def schedule_refresh(client):
    t = threading.Timer(REFRESH_INTERVAL, do_login, args=[client])
    t.daemon = True
    t.start()

def on_connect(client, userdata, flags, rc, properties=None):
    # subscribe to all relevant topics here
    do_login(client)
    schedule_refresh(client)

def on_message(client, userdata, msg):
    global ACCESS_TOKEN
    topic = msg.topic
    raw = msg.payload.decode('utf-8', errors='replace')

    if topic.endswith("/api/resp/user/auth"):
        data = json.loads(raw[raw.find('{'):])
        ACCESS_TOKEN = data["accessToken"]
        client.publish(f"{PREFIX}/api/cmd/login", json.dumps({"accessToken": ACCESS_TOKEN}))
        return

    if topic.endswith("/api/resp/login"):
        get_rfid_list(client)
        return

    # ... additional topic handlers

client.on_connect = on_connect
client.on_message = on_message
client.connect(WALLBOX_HOST, WALLBOX_PORT)
client.loop_forever()
```
