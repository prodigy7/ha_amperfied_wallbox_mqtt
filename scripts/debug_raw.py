#!/usr/bin/env python3
"""Low-level debug: raw aiomqtt connection, wildcard-subscribes to everything."""
from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
from pathlib import Path

import aiomqtt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_dotenv  # noqa: E402


async def main() -> None:
    load_dotenv()
    host = os.environ["WALLBOX_HOST"]
    prefix = os.environ["WALLBOX_DEVICE_PREFIX"]
    username = os.environ.get("WALLBOX_USERNAME", "admin")
    password = os.environ["WALLBOX_PASSWORD"]

    print(f"Connecting to {host}:443 wss transport, prefix={prefix!r}", file=sys.stderr)

    async with aiomqtt.Client(
        hostname=host,
        port=443,
        transport="websockets",
        websocket_path="/mqtt",
        protocol=aiomqtt.ProtocolVersion.V5,
        tls_params=aiomqtt.TLSParameters(cert_reqs=ssl.CERT_NONE),
        tls_insecure=True,
        identifier="debugclient1234",
    ) as client:
        print("Connected.", file=sys.stderr)
        await client.subscribe(f"{prefix}/#")
        print("Subscribed to wildcard.", file=sys.stderr)

        await client.publish(
            f"{prefix}/api/cmd/user/auth",
            json.dumps({"name": username, "password": password}),
        )
        print("Published user/auth.", file=sys.stderr)

        async def printer():
            async for message in client.messages:
                payload = message.payload
                raw = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
                print(f"TOPIC={message.topic} PAYLOAD={raw!r}")

        try:
            await asyncio.wait_for(printer(), timeout=15)
        except asyncio.TimeoutError:
            print("done waiting", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
