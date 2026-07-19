#!/usr/bin/env python3
"""Standalone test script for api.py -- WITHOUT Home Assistant.

Connects to the real wallbox, logs in, subscribes to telemetry, prints
incoming updates, and fetches the RFID list. Serves as an isolated test of
AmperfiedWallboxClient before it's wired into the coordinator/entities (see
CLAUDE.md, "Starting point for the first session").

Credentials come from environment variables (never commit them):

    export WALLBOX_HOST=192.168.0.123
    export WALLBOX_DEVICE_PREFIX=hdm-smart-connect-abc123
    export WALLBOX_USERNAME=admin
    export WALLBOX_PASSWORD=...
    python3 scripts/test_api.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "amperfied_wallbox"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_dotenv  # noqa: E402


def _load_api_module() -> Any:
    """Loads api.py directly, without running the integration's real
    __init__.py -- that imports homeassistant, which is deliberately not
    installed here (isolated test outside of HA, see README.md).
    """
    pkg = types.ModuleType("amperfied_wallbox")
    pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules["amperfied_wallbox"] = pkg

    spec = importlib.util.spec_from_file_location(
        "amperfied_wallbox.api", COMPONENT_DIR / "api.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["amperfied_wallbox.api"] = module
    spec.loader.exec_module(module)
    return module


api = _load_api_module()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    load_dotenv()

    try:
        host = os.environ["WALLBOX_HOST"]
        device_prefix = os.environ["WALLBOX_DEVICE_PREFIX"]
        password = os.environ["WALLBOX_PASSWORD"]
    except KeyError as err:
        sys.exit(f"Missing environment variable: {err}. See docstring above.")
    username = os.environ.get("WALLBOX_USERNAME", "admin")

    client = api.AmperfiedWallboxClient(
        host=host, device_prefix=device_prefix, username=username, password=password
    )

    async def on_telemetry(topic: str, value: Any) -> None:
        print(f"[telemetry] {topic} = {value!r}")

    print(f"Connecting to {host} (prefix {device_prefix!r})...")
    await client.async_connect()
    print("Connected and logged in (user/auth -> login succeeded).")

    await client.async_subscribe_telemetry(on_telemetry)
    print("Subscribed to telemetry, waiting for updates (Ctrl+C to stop)...")

    try:
        rfid_list = await client.async_get_rfid_list()
        print(f"RFID list ({len(rfid_list)} entries):")
        for entry in rfid_list:
            print(f"  - {entry.get('label') or entry.get('cardnum')}: {entry}")
    except Exception:
        logging.exception("rfidList/get failed")

    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        print("Disconnecting...")
        await client.async_disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
