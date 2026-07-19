# Home Assistant Integration: Amperfied Wallbox (connect.solar)

Native Home Assistant integration for Amperfied/Heidelberg connect.solar wallboxes
(HDM-SMART-CONNECT series), connected via the wallbox's reverse-engineered
MQTT5-over-WebSocket API (no Modbus needed, web UI features remain usable).

## Installation

**Via HACS:**

1. In HACS, add this repository as a custom repository:
   `https://github.com/prodigy7/ha_amperfied_wallbox_mqtt`, category "Integration".
2. Install "Amperfied Wallbox (connect.solar)" from HACS, then restart Home Assistant.
3. Continue with step 3 below ("Add Integration").

**Manual install:**

1. Copy `custom_components/amperfied_wallbox/` into your Home Assistant config directory, so
   you end up with `<config>/custom_components/amperfied_wallbox/`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**, search for "Amperfied Wallbox",
   and enter:
   - **IP address or hostname** of the wallbox (e.g. `192.168.1.50`)
   - **Username** (`admin` by default)
   - **Password**
4. That's it -- the device prefix (mDNS hostname suffix) is auto-discovered, no need to look it
   up yourself. If the wallbox is unreachable or the credentials are wrong, the form shows an
   error and nothing is saved.

Once set up, all entities, the manual charge-authorization button, and the `get_charge_log`
service become available immediately; no further configuration is needed. See "Robustness"
below for what happens if the wallbox is temporarily unreachable or the password changes later.

## Status

Core functionality is implemented and verified live against a real wallbox: connect/login,
`api/cmd/user/refreshAuth`-based token refresh (password only needed once), auto-discovery of
the device prefix, 24 sensors (charging power/energy, per-phase power/voltage/current, PCB
temperature, EV/wallbox/energy-manager state, limit reason, phase switch state, charge
authorization source, solar surplus/grid/house power, last charge session), 2 binary sensors
(EV connected, using default password), manual charge authorization button, a `get_charge_log`
service, RFID/device-detail diagnostics, and device info (firmware/hardware version, serial,
MAC addresses) on the HA device page.

This integration is deliberately **read-primary**. Setting the charging power limit, phase
switching, PV surplus charging toggle, and RFID card management are intentionally *not*
implemented, even though their command topics are documented -- misconfiguring wallbox
hardware/firmware settings via Home Assistant carries a real risk of hardware damage. See
`PROTOCOL.md` for the full protocol documentation and `CLAUDE.md` for the project brief.

### Usage examples

Entity IDs below assume the default device name ("Amperfied Wallbox") and are only
illustrative -- check **Settings → Devices & Services → Amperfied Wallbox → Entities** for
your actual IDs (they get a different suffix if you rename the device or run more than one
wallbox).

**Notify when the EV is plugged in:**

```yaml
automation:
  - alias: "Notify when EV is plugged in"
    trigger:
      - trigger: state
        entity_id: binary_sensor.amperfied_wallbox_ev_connected
        to: "on"
    action:
      - action: notify.notify
        data:
          message: "EV plugged in at the wallbox."
```

**Automatically authorize charging overnight** (using the button entity from an automation,
not just the dashboard):

```yaml
automation:
  - alias: "Authorize wallbox charging after 22:00"
    trigger:
      - trigger: state
        entity_id: binary_sensor.amperfied_wallbox_ev_connected
        to: "on"
    condition:
      - condition: time
        after: "22:00:00"
        before: "06:00:00"
    action:
      - action: button.press
        target:
          entity_id: button.amperfied_wallbox_authorize_charging
```

**Summarize last week's charging sessions** (calling the `get_charge_log` service and using
its response data -- note the filter times must be *local* wall-clock time, not UTC, see
PROTOCOL.md's `clog/get` notes; `now()` in HA templates already is local time):

```yaml
script:
  wallbox_weekly_summary:
    sequence:
      - action: amperfied_wallbox.get_charge_log
        data:
          filter_after: "{{ (now() - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S%z') }}"
          filter_before: "{{ now().strftime('%Y-%m-%dT%H:%M:%S%z') }}"
        response_variable: charge_log
      - action: notify.notify
        data:
          message: >
            {{ charge_log.value | length }} charging session(s) in the last 7 days,
            {{ charge_log.value | map(attribute='energy') | sum | round(2) }} kWh total.
```

(For just the *most recent* session, `sensor.amperfied_wallbox_last_charge_session_energy`
already covers that -- its `begin`/`end`/`source`/`label` attributes -- without needing to
call the service at all.)

### Robustness

Live-verified (forced disconnects/wrong credentials against the real wallbox, see
`scripts/` history in the repo's development log):
- **Wallbox unreachable when HA starts** (e.g. after a power outage): raises
  `ConfigEntryNotReady`, so HA retries setup automatically with backoff instead of failing
  permanently.
- **Connection lost during normal operation**: automatic reconnect with exponential backoff
  (1s up to 60s), plus entities are marked "unavailable" for the duration instead of silently
  showing stale values, and recover automatically once telemetry resumes.
- **Password changed on the wallbox after setup**: detected on the next reconnect attempt and
  triggers Home Assistant's standard reauth flow (a notification leading to a small "enter new
  password" form) instead of retrying forever with credentials that will never work again.
- **Multiple *independent* wallboxes** (separate devices, separate circuits): supported by
  design (no `single_config_entry` restriction, each gets its own config entry/unique
  ID/entities, and the `get_charge_log` service has a `config_entry_id` field to pick between
  them) -- but only verified by code review, not against two real physical wallboxes
  simultaneously (only one was available for testing).

### Known limitation: untested with a wallbox grid (leader/follower)

**Everything in this repo has only ever been tested against a single, standalone wallbox that
is not electrically/logically grouped with other wallboxes.** PROTOCOL.md's device info shows
the tested unit runs in `"mode": "leader"`, and the frontend JS references
`wallboxgrid/follower/*` topics for multi-wallbox load-balancing setups (several wallboxes on
one circuit, coordinating who gets how much current) -- but no such grid was available to test
against. If your wallbox is part of a grid, be aware that:
- Device-prefix auto-discovery (subscribing to bare `#`) might see multiple prefixes if
  follower topics are bridged onto the same broker; it picks the most frequently seen one, but
  this hasn't been validated against a real grid.
- `loadbalancer/grid/monitor/leader`'s `connectors` array may contain more than one entry in a
  grid (one per physical wallbox); the `surplus_power`/`grid_power`/`house_power` sensors and
  the `evState`/`wbState`/etc. topics all currently assume a single connector/wallbox and would
  likely need rework to correctly represent a multi-wallbox grid.
- If you *do* run a grid setup, proceed cautiously and please report back what you find --
  PROTOCOL.md's "process for filling gaps" section describes how to capture and document new
  findings.

### Debugging

Standard Home Assistant debug logging works out of the box (Settings → Devices & Services →
this integration → "..." → *Enable debug logging*, or via `logger:` in `configuration.yaml`
for `custom_components.amperfied_wallbox`). This traces the connection/login lifecycle,
request/response cycles (topic names only -- payloads containing passwords/tokens are never
logged), reconnects, and charge-session refreshes.

## For developers

Working on the integration itself (project structure, local/full-stack testing, validation
before PRs)? See [DEVELOPMENT.md](DEVELOPMENT.md).

## License

MIT, see [LICENSE](LICENSE).
