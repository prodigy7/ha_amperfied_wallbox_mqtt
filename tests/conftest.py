"""Shared pytest fixtures.

Loads the recorded telemetry fixtures (real snapshots captured against a
live wallbox, see tests/fixtures/*.json) so tests can exercise the actual
decoding/entity logic without needing hardware or a full Home Assistant
instance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    data.pop("_comment", None)
    return data


@pytest.fixture
def telemetry_idle() -> dict[str, Any]:
    """Real snapshot: no EV connected."""
    return _load_fixture("telemetry_idle.json")


@pytest.fixture
def telemetry_charging() -> dict[str, Any]:
    """Real snapshot: actively charging, 3-phase, authorized via RFID."""
    return _load_fixture("telemetry_charging.json")
