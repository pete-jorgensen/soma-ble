"""Protocol tests.

Every reply below is a real frame from a Smart Shades 3 on firmware 3.0.17+0, not one
invented to match the parser. That distinction is the point: the opcode names come from a
third-party list, so the only thing that makes this parser trustworthy is that it decodes
bytes the hardware actually sends.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "soma_ble"))

import protocol as p  # noqa: E402


class TestBuild:
    def test_getter_is_opcode_then_zero_length(self):
        assert p.build(p.Cmd.GET_ZIGBEE_ENABLED) == bytes.fromhex("5100")

    def test_one_byte_setter(self):
        assert p.build(p.Cmd.SET_ZIGBEE_ENABLED, b"\x01") == bytes.fromhex("500101")

    def test_position_command(self):
        assert p.build(p.Cmd.SET_CLOSED_PCT, bytes([20])) == bytes.fromhex("080114")

    def test_payload_too_long_is_refused(self):
        with pytest.raises(ValueError):
            p.build(p.Cmd.SET_DEVICE_NAME, b"x" * 254)


class TestParse:
    @pytest.mark.parametrize(
        ("raw", "cmd", "expected"),
        [
            ("2708332e302e31372b30", p.Cmd.GET_FIRMWARE_VERSION, "3.0.17+0"),
            ("2807626c696e647933", p.Cmd.GET_BOARD, "blindy3"),
            ("2905332e302e36", p.Cmd.GET_BOARD_REVISION, "3.0.6"),
        ],
    )
    def test_text_replies(self, raw, cmd, expected):
        assert p.as_text(p.parse(bytes.fromhex(raw), cmd)) == expected

    @pytest.mark.parametrize(
        ("raw", "cmd", "expected"),
        [
            ("110100", p.Cmd.GET_POSITIONS_CONFIGURED, 0),
            ("110101", p.Cmd.GET_POSITIONS_CONFIGURED, 1),
            ("2404f9010000", p.Cmd.GET_CLOSED_POSITION, 505),  # a calibrated limit
            ("0d04160d0000", p.Cmd.GET_LAST_MOVE_DURATION, 3350),
            ("0402421e", p.Cmd.GET_BATTERY_VOLTAGE, 7746),
            ("1d029413", p.Cmd.GET_INPUT_VOLTAGE, 5012),  # USB-C supplying
            ("0b013d", p.Cmd.GET_BATTERY_PCT, 61),
            ("0f0132", p.Cmd.GET_SPEED, 50),
            ("0904060000 00".replace(" ", ""), p.Cmd.GET_MOVE_COUNT, 6),
        ],
    )
    def test_integer_replies(self, raw, cmd, expected):
        assert p.as_int(p.parse(bytes.fromhex(raw), cmd)) == expected

    def test_short_frame_is_rejected(self):
        with pytest.raises(p.ProtocolError):
            p.parse(b"\x11")

    def test_truncated_payload_is_rejected(self):
        # Claims four data bytes, carries two.
        with pytest.raises(p.ProtocolError):
            p.parse(bytes.fromhex("2404f901"), p.Cmd.GET_CLOSED_POSITION)

    def test_stale_reply_for_another_opcode_is_rejected(self):
        """The read characteristic holds the PREVIOUS answer when a command is ignored.

        Without the opcode check an ignored command reads back as a success, which is
        exactly how a silently-latched calibration looks like a working one.
        """
        with pytest.raises(p.ProtocolError, match="stale read"):
            p.parse(bytes.fromhex("110100"), p.Cmd.GET_CLOSED_POSITION)


class TestAdvertisement:
    def test_real_advertisement(self):
        """10 00 3e -- fully open, 62 % charge."""
        adv = p.parse_advertisement({p.MANUFACTURER_ID: bytes.fromhex("10003e")})
        assert adv is not None
        assert adv.closed_percent == 0
        assert adv.battery_percent == 62

    def test_device_and_ha_position_are_inverted(self):
        """The device reports percent CLOSED; Home Assistant wants percent OPEN."""
        adv = p.parse_advertisement({p.MANUFACTURER_ID: bytes.fromhex("10643e")})
        assert adv.closed_percent == 100
        assert adv.ha_position == 0

    def test_other_manufacturer_is_not_a_soma(self):
        assert p.parse_advertisement({0x004C: b"\x01\x02\x03"}) is None

    def test_truncated_advertisement(self):
        assert p.parse_advertisement({p.MANUFACTURER_ID: b"\x10"}) is None

    def test_out_of_range_values_are_rejected(self):
        assert p.parse_advertisement({p.MANUFACTURER_ID: bytes([0x10, 200, 50])}) is None


class TestOpcodeSafety:
    def test_every_write_command_is_a_real_opcode(self):
        for cmd in p.WRITE_COMMANDS:
            assert isinstance(cmd, p.Cmd)

    def test_getters_are_not_listed_as_writes(self):
        for cmd in (p.Cmd.GET_POSITIONS_CONFIGURED, p.Cmd.GET_BATTERY_PCT, p.Cmd.IDENTIFY):
            assert cmd not in p.WRITE_COMMANDS

    def test_reset_settings_is_treated_as_a_write(self):
        """0x10 clears the travel limits -- it must never be reachable from a poll."""
        assert p.Cmd.RESET_SETTINGS in p.WRITE_COMMANDS
