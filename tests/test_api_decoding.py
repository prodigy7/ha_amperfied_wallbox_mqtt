"""Unit tests for AmperfiedWallboxClient's pure payload-decoding helpers.

These are plain static methods with no network/HA dependency, so they're
tested directly without any fixtures or mocking -- see PROTOCOL.md's
"Payload format quirk" section for the behavior being verified here.
"""
from __future__ import annotations

from custom_components.amperfied_wallbox.api import AmperfiedWallboxClient


class TestExtractJson:
    def test_plain_json(self) -> None:
        assert AmperfiedWallboxClient._extract_json('{"accessToken": "abc"}') == {
            "accessToken": "abc"
        }

    def test_with_client_identifier_prefix(self) -> None:
        # api/resp/... topics can be prefixed with e.g. "mqttjs<hex>" before the JSON.
        raw = 'mqttjs1a2b3c{"refreshToken": "r", "accessToken": "a"}'
        assert AmperfiedWallboxClient._extract_json(raw) == {
            "refreshToken": "r",
            "accessToken": "a",
        }

    def test_exception_response(self) -> None:
        # Wrong-password response shape, see PROTOCOL.md's Authentication flow section.
        raw = '{"exception": {"id": 41, "msg": "wrong password"}}'
        assert AmperfiedWallboxClient._extract_json(raw) == {
            "exception": {"id": 41, "msg": "wrong password"}
        }

    def test_no_json_returns_none(self) -> None:
        assert AmperfiedWallboxClient._extract_json("no braces here") is None

    def test_invalid_json_returns_none(self) -> None:
        assert AmperfiedWallboxClient._extract_json("{not valid json}") is None


class TestParseTelemetryValue:
    def test_dict_wrapped_value(self) -> None:
        assert AmperfiedWallboxClient._parse_telemetry_value('{"value": "5.1.1"}') == {
            "value": "5.1.1"
        }

    def test_plain_float(self) -> None:
        assert AmperfiedWallboxClient._parse_telemetry_value("36.5") == 36.5

    def test_plain_int(self) -> None:
        assert AmperfiedWallboxClient._parse_telemetry_value("3") == 3

    def test_raw_enum_string_stays_string(self) -> None:
        assert AmperfiedWallboxClient._parse_telemetry_value("A1") == "A1"

    def test_leading_zero_string_stays_string(self) -> None:
        # A string with leading zeros (e.g. a serial number) is invalid JSON
        # (leading zeros aren't allowed for numbers), so it must fall back to
        # the raw string -- see PROTOCOL.md.
        assert AmperfiedWallboxClient._parse_telemetry_value("000042") == "000042"

    def test_semicolon_separated_string_stays_string(self) -> None:
        assert AmperfiedWallboxClient._parse_telemetry_value("0;0;0") == "0;0;0"

    def test_boolean_value(self) -> None:
        assert AmperfiedWallboxClient._parse_telemetry_value('{"value":true}') == {
            "value": True
        }
