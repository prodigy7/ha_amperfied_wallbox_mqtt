"""Unit tests for coordinator.py's small pure helper functions."""
from __future__ import annotations

from custom_components.amperfied_wallbox.coordinator import _format_mac, _unwrap


class TestUnwrap:
    def test_dict_with_value_key(self) -> None:
        assert _unwrap({"value": "5.1.1"}) == "5.1.1"

    def test_plain_string_passthrough(self) -> None:
        assert _unwrap("A1") == "A1"

    def test_plain_number_passthrough(self) -> None:
        assert _unwrap(36.5) == 36.5

    def test_dict_without_value_key_passthrough(self) -> None:
        # e.g. chargePermission or grid/monitor/leader are dicts without "value".
        raw = {"source": "web", "label": "admin"}
        assert _unwrap(raw) == raw


class TestFormatMac:
    def test_valid_mac(self) -> None:
        assert _format_mac({"value": "006034abc123"}) == "00:60:34:ab:c1:23"

    def test_wrong_length_returns_none(self) -> None:
        assert _format_mac({"value": "short"}) is None

    def test_none_value_returns_none(self) -> None:
        assert _format_mac(None) is None

    def test_non_string_value_returns_none(self) -> None:
        assert _format_mac({"value": 123456}) is None
