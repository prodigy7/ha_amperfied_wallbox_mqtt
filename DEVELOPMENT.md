# Development guide

For end-user installation and features, see [README.md](README.md). This document is for
working on the integration itself.

## Project structure

```
.
├── .github/workflows/                 # CI: hassfest/HACS validation, pytest (see below)
├── CLAUDE.md                          # Context & project brief for Claude Code
├── PROTOCOL.md                        # Reverse-engineered MQTT API documentation
├── hacs.json                          # HACS metadata
├── pytest.ini                         # pytest config (testpaths = tests)
├── requirements_test.txt              # Test dependencies (pytest, homeassistant, aiomqtt)
├── tests/                             # Offline, fixture-based unit tests (see below)
└── custom_components/
    └── amperfied_wallbox/
        ├── __init__.py                # Config entry setup/unload, get_charge_log service
        ├── api.py                     # Async MQTT client, login/token refresh
        ├── binary_sensor.py           # Binary sensors: EV connected, using default password
        ├── button.py                  # Button entity: manual charge authorization
        ├── config_flow.py             # Setup via the HA UI
        ├── const.py                   # Domain, topics, config keys
        ├── coordinator.py             # DataUpdateCoordinator (push-based)
        ├── diagnostics.py             # RFID list + telemetry snapshot export
        ├── manifest.json
        ├── sensor.py                  # Sensor entities (power, energy, status, ...)
        ├── services.yaml              # get_charge_log service definition
        ├── strings.json               # UI text (source for translations)
        └── translations/
            ├── en.json
            └── de.json
```

## Getting started

1. Open the repo in VS Code (the project folder, not individual files)
2. Read `CLAUDE.md` and `PROTOCOL.md`
3. Recommended implementation order: see "Starting point for the first session"
   in `CLAUDE.md`

## Working with Claude Code (or another AI assistant)

Most of this integration, including this document, was built with Claude Code. If you continue
that way:

- **`CLAUDE.md` is picked up automatically** as project context in a new Claude Code session --
  you don't need to paste it in or re-explain the project. It already establishes the
  read-primary design policy ("don't add power-limit/phase-switching/PV-surplus/RFID-management
  write actions without being asked explicitly"), the architecture decisions (async, push-based
  coordinator, token refresh), and the recommended build order. You generally don't need to
  repeat any of that -- just state the task.
- **Point it at `PROTOCOL.md` for protocol questions** rather than describing the wallbox API
  yourself; it's the single source of truth for topics/payloads and gets updated as new things
  are reverse-engineered (see "process for filling gaps" in `PROTOCOL.md`). Static analysis of
  the wallbox's own frontend JS bundle (`/assets/index-*.js`) has repeatedly turned up more/
  better information than sniffing the UI -- worth suggesting as an approach if something is
  still undocumented.
- **Insist on live verification, not just "it should work".** The real wallbox is reachable on
  the local network (see `CLAUDE.md`'s "Test environment"), and `.env`-based credentials make
  this cheap to do (see below). Ask for the actual command output/observed behavior, not just a
  description of the change. Every feature currently in this repo was live-tested against the
  real device before being considered done, including deliberately forcing failure conditions
  (wrong password, unreachable host, forced mid-session disconnects) to verify error handling
  and reconnect/reauth behavior.
- **Review before accepting**, especially anything written into `PROTOCOL.md`: it documents
  reverse-engineered, undocumented hardware behavior, so a plausible-sounding but wrong entry is
  worse than an admitted gap. Cross-check surprising claims (e.g. "the wallbox ignores the UTC
  offset on this one endpoint") against the actual command output shown.
- **Known environment gotchas** hit during development, worth knowing before handing the AI a
  fresh environment:
  - `pip`/`ensurepip` are not preinstalled on a bare system in some sandboxes -- needed
    `sudo apt-get install python3-pip python3-venv` once, interactively (sudo needs a real
    terminal for the password prompt).
  - Never load `.env` via `source .env` in Bash -- special characters like `$` in the password
    get interpreted as shell variable expansion and silently mangle it. Use
    `scripts/_env.py`'s `load_dotenv()` (plain Python file parsing) instead, as all the
    `scripts/*.py` tools already do.
  - Running `scripts/test_integration.py` requires the (heavy) `homeassistant` package;
    `scripts/test_api.py` deliberately doesn't, so it stays fast for quick `api.py`-only
    iteration.

## Local testing without a full HA instance

`scripts/test_api.py` connects in isolation (without Home Assistant) to the real
wallbox, logs in, subscribes to all telemetry topics, and fetches the RFID list --
this is how `api.py` was tested before being wired into the coordinator/entities.

```bash
python3 -m venv .venv
.venv/bin/pip install aiomqtt
cp .env.example .env   # fill in values; quote WALLBOX_PASSWORD if it has special characters
.venv/bin/python scripts/test_api.py
```

`.env` is read directly in Python by `scripts/_env.py` (don't use `source .env` in
Bash -- special characters like `$` in the password would otherwise be interpreted
by the shell as variable expansion and mangle the password). Never commit the
wallbox credentials (`.env` is already in `.gitignore`).

`scripts/debug_raw.py` is a low-level debug tool (raw aiomqtt, wildcard-subscribes to
`{prefix}/#`) for when a response payload needs to be inspected directly.

## Full-stack testing with a real Home Assistant core object

`scripts/test_integration.py` goes one level up from `test_api.py`: it exercises the
coordinator and every entity (sensors, binary sensors, diagnostics) against the real wallbox,
using an actual `homeassistant.core.HomeAssistant` instance instead of mocks. This is the
harness used throughout development to verify device info population, new sensors, and the
resilience callbacks -- reuse it instead of rebuilding this from scratch.

```bash
.venv/bin/pip install homeassistant   # heavy; test_api.py doesn't need this
.venv/bin/python scripts/test_integration.py
```

Note: a bare `HomeAssistant()` object has no initialized `config_entries` manager (that only
happens during HA's full bootstrap), so this script calls `coordinator.async_setup()` and
builds entities directly rather than going through `__init__.py`'s `async_setup_entry()`. The
thin glue code in `__init__.py` itself (entry setup/unload, service registration) is therefore
not covered by this script -- everything below that (client, coordinator, entities,
diagnostics) is exercised for real.

## Automated tests (pytest, offline, no hardware needed)

`tests/` contains fast, offline unit tests for the decoding/entity logic (`sensor.py`,
`binary_sensor.py`, `coordinator.py`, `api.py`'s payload parsing) built around **recorded
fixtures** -- real telemetry snapshots captured live against a wallbox (`tests/fixtures/*.json`,
one idle and one actively-charging) rather than hand-rolled data, so they double as a
regression check against actually-observed payload shapes. No live wallbox, no
`pytest-homeassistant-custom-component`-style HA test harness needed -- entities are
constructed directly with a small duck-typed fake coordinator (`tests/helpers.py`), since
`CoordinatorEntity.__init__` only ever stores `self.coordinator`, nothing more.

```bash
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest tests/ -v
```

To add a fixture for a new scenario (e.g. an error state), capture a real snapshot with
`scripts/test_integration.py` (print `coordinator.data` as JSON) and drop it in
`tests/fixtures/`, then add a `conftest.py` fixture function for it.

Runs automatically in CI on every push/PR via `.github/workflows/test.yaml`.

## Validation before PRs

CI runs automatically via `.github/workflows/`:
- `validate.yaml`: official `home-assistant/actions/hassfest` and `hacs/action` validation
  (push/PR, plus a daily scheduled run to catch upstream breakage) -- no local HA-core checkout
  needed.
- `test.yaml`: the pytest suite above.

To run hassfest locally instead of waiting for CI:

```bash
python -m script.hassfest   # from a Home Assistant core checkout
```
