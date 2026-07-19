#!/usr/bin/env python3
"""Full-stack integration test -- WITH a real Home Assistant core object.

Unlike scripts/test_api.py (which tests api.py in isolation, without
homeassistant installed at all), this script exercises the coordinator and
every entity (sensor/binary_sensor) against the real wallbox, using a real
`homeassistant.core.HomeAssistant` instance. This is the harness used
throughout development to verify things like device info population, the
sensors, and the resilience callbacks (reconnect/reauth) -- saved here so it
doesn't have to be reinvented in a future session.

NOTE on scope: a bare `HomeAssistant(config_dir)` has no initialized
`config_entries` manager (that only happens during HA's full bootstrap), so
this script calls `coordinator.async_setup()` and constructs entities
directly instead of going through `__init__.py`'s `async_setup_entry()` /
`hass.config_entries.async_forward_entry_setups()`. That means the (very
thin) glue code in `__init__.py` itself -- entry setup/unload,
`get_charge_log` service registration -- is not exercised here. Everything
below that (coordinator, client, all entities, diagnostics) is exercised for
real.

Requires the `homeassistant` package (heavy, unlike test_api.py's aiomqtt-only
dependency):

    .venv/bin/pip install homeassistant

Usage:

    cp .env.example .env   # fill in values, see test_api.py for details
    .venv/bin/python scripts/test_integration.py

A fake, minimal ConfigEntry stand-in is used instead of pytest-homeassistant-
custom-components' MockConfigEntry (which isn't on PyPI as a standalone
package) -- just enough attributes/methods for DataUpdateCoordinator and
async_start_reauth to work: entry_id, data, async_on_unload(), async_start_reauth().
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import load_dotenv  # noqa: E402

from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.amperfied_wallbox.api import AmperfiedWallboxClient  # noqa: E402
from custom_components.amperfied_wallbox.binary_sensor import (  # noqa: E402
    AmperfiedWallboxDefaultPasswordBinarySensor,
    AmperfiedWallboxEvConnectedBinarySensor,
)
from custom_components.amperfied_wallbox.const import DOMAIN  # noqa: E402
from custom_components.amperfied_wallbox.coordinator import (  # noqa: E402
    AmperfiedWallboxCoordinator,
)
from custom_components.amperfied_wallbox.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)
from custom_components.amperfied_wallbox.sensor import (  # noqa: E402
    SENSOR_DESCRIPTIONS,
    AmperfiedWallboxSensor,
)


class FakeConfigEntry:
    """Minimal stand-in for homeassistant.config_entries.ConfigEntry."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.entry_id = "test_entry_id"
        self.data = data

    def async_on_unload(self, func: Any) -> None:
        pass

    def async_start_reauth(self, hass: HomeAssistant) -> None:
        print("!! async_start_reauth() was called -- reauth flow would trigger here !!")


async def main() -> None:
    load_dotenv()
    try:
        host = os.environ["WALLBOX_HOST"]
        device_prefix = os.environ["WALLBOX_DEVICE_PREFIX"]
        password = os.environ["WALLBOX_PASSWORD"]
    except KeyError as err:
        sys.exit(f"Missing environment variable: {err}. See scripts/test_api.py for the .env format.")
    username = os.environ.get("WALLBOX_USERNAME", "admin")

    with tempfile.TemporaryDirectory() as config_dir:
        hass = HomeAssistant(config_dir)
        entry = FakeConfigEntry({"host": host, "device_prefix": device_prefix, "username": username})

        client = AmperfiedWallboxClient(
            host=host, device_prefix=device_prefix, username=username, password=password
        )
        coordinator = AmperfiedWallboxCoordinator(hass, entry, client)
        client.set_callbacks(
            on_connection_lost=coordinator.async_set_update_error,
            on_persistent_auth_failure=lambda: entry.async_start_reauth(hass),
        )

        print(f"Setting up against {host} ...")
        await coordinator.async_setup()
        print("Setup succeeded.")
        print("device_info:", dict(coordinator.device_info))

        await asyncio.sleep(3)  # let a few telemetry updates arrive

        print(f"\n{len(SENSOR_DESCRIPTIONS)} sensors:")
        for desc in SENSOR_DESCRIPTIONS:
            sensor_entity = AmperfiedWallboxSensor(coordinator, entry, desc)
            attrs = sensor_entity.extra_state_attributes
            print(f"  {desc.key}: {sensor_entity.native_value!r}" + (f"  attrs={attrs}" if attrs else ""))

        print("\nBinary sensors:")
        print(f"  ev_connected: {AmperfiedWallboxEvConnectedBinarySensor(coordinator, entry).is_on!r}")
        print(f"  using_default_password: {AmperfiedWallboxDefaultPasswordBinarySensor(coordinator, entry).is_on!r}")

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator
        print("\nDiagnostics export:")
        diag = await async_get_config_entry_diagnostics(hass, entry)
        print(f"  keys: {list(diag.keys())}")
        print(f"  device_details: {len(diag['device_details'])} entries")
        print(f"  rfid_list: {len(diag['rfid_list'])} entries")

        print("\nDisconnecting...")
        await client.async_disconnect()
        print("Disconnected cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
