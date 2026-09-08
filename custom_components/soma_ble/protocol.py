"""The SOMA Smart Shades 3 Bluetooth LE protocol.

Pure protocol: framing, opcodes, and the decoding of each reply. No Home Assistant and no
Bluetooth transport, so it can be unit-tested without either.

FRAMING
-------
Every frame, in both directions, is::

    Type(1)  Length(1)  Data(Length)

A getter is ``<opcode> 00``. A one-byte setter is ``<opcode> 01 <value>``. Replies are
read with a **plain GATT read** of the response characteristic -- the device has no notify
on it, so a command is: write, wait briefly, read.

GENERATIONS -- READ THIS BEFORE REUSING ANY OPCODE
--------------------------------------------------
This module is for the **Smart Shades 3** only. The Smart Shades 2 is a different protocol
on a different service, and the same byte means different things on each. The one that
matters: on an SS2, ``0x51`` written to service ``00001890-...`` is a **factory reset**
whose documented recovery is the vendor phone app. On an SS3 it is
``CMD_GET_ZIGBEE_ENABLED``. An SS3 does not expose the legacy service at all, so an SS2
procedure aimed at a 3 fails rather than destroys -- but do not rely on that.

Opcode NAMES are from the community reference `rzuppur/smart-shades-documentation`
(``V3.md``). That reference documents names; the behaviour below is the part no name tells
you. The vendor's names carry a ``CMD_`` prefix (``CMD_RESET_SETTINGS``); :class:`Cmd`
drops it, so ``CMD_RESET_SETTINGS`` is ``Cmd.RESET_SETTINGS`` here.

BEHAVIOUR THAT IS IN NO DATASHEET  (firmware 3.0.17+0)
------------------------------------------------------
**An uncalibrated motor refuses EVERY move while looking completely healthy.** Over Zigbee
it accepts position, open and close alike with no error, answers reads promptly, and
reports raw position 0 -- which a Zigbee cover integration renders as position 100, so a
commanded position appears to "snap back" to fully open, forever. Nothing on the Zigbee
side reveals the cause: ZCL ``configStatus`` reads operational/online/closed-loop and
``windowCoveringMode`` decodes to ``calibration: false``. Those are the ZCL notions of
those words and say nothing about SOMA's own limits. One read settles it:
``GET_POSITIONS_CONFIGURED``. This is the strongest single reason this integration exists.

**The travel limits LATCH when committed.** While ``GET_POSITIONS_CONFIGURED`` reads 1,
``SET_OPEN_POSITION`` and ``SET_CLOSED_POSITION`` are acknowledged and silently ignored,
and ``OPEN``/``CLOSE`` stop driving the motor at all -- only ``SET_CLOSED_PCT`` still moves
it, and only within the stored range. The latch is in flash: it survives a reboot, a
re-sent ``SET_POSITIONS_CONFIGURED``, and the Zigbee cluster's own calibration-mode bit.
``RESET_SETTINGS`` (``0x10``) is the way out and, despite the name, is surgical: it clears
the configured flag, the limits and the encoder position, and nothing else. The Zigbee
pairing, the Zigbee-enabled flag, touch, speed, device name, advertising interval, TX
power, timezone, move count and boot counter all survive. It is not a factory reset.

**Position is unreadable until calibrated.** ``GET_CURRENT_POSITION`` returns 0 while the
motor is uncalibrated, in BOTH directions, even while the motor is turning. The firmware
still tracks position internally -- a limit setter stores a real encoder value at a moment
when the getter reads 0 -- so during calibration there is no position feedback and the ends
have to be judged by eye.

**Raw move works only while uncalibrated.** ``OPEN``/``CLOSE`` free-run the motor while the
limits are unset -- that is how calibration is performed -- and stop driving it once the
limits are committed. A jog control is therefore only usable in exactly the state it is
needed for, and must be hidden or disabled once the shade is calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# --- GATT -------------------------------------------------------------------------------

SERVICE_UUID = "8998a466-a65f-4d49-90b2-927f41c55190"
WRITE_UUID = "8998a466-a65f-4d49-90b2-927f41c55191"
READ_UUID = "8998a466-a65f-4d49-90b2-927f41c55192"

#: Bluetooth SIG company identifier in the advertisement. This is the ONLY reliable way to
#: spot an SS3 while scanning.
#:
#: .. warning::
#:    **An SS3 advertises no name and does NOT advertise its own command service.**
#:    ``SERVICE_UUID`` appears only *after* you connect -- the single service an SS3 does
#:    advertise is unrelated to control -- so a scan filtered on it returns nothing and
#:    looks exactly like the device being absent, asleep or out of range. Discovery must
#:    match on this manufacturer id.
MANUFACTURER_ID = 0x0370


class Cmd(IntEnum):
    """Every documented SS3 opcode.

    Names are the vendor's own. Ones this integration uses are grouped first.
    """

    # -- motion ---------------------------------------------------------------
    OPEN = 0x01
    CLOSE = 0x02
    STOP = 0x03
    SET_CLOSED_PCT = 0x08  # data: 1 byte, 0-100, where 100 is fully CLOSED
    GET_CLOSED_PCT = 0x0A

    # -- calibration ----------------------------------------------------------
    SET_CLOSED_POSITION = 0x06  # store where the shade is now as the closed limit
    SET_OPEN_POSITION = 0x07  # ... and as the open limit
    GET_POSITIONS_CONFIGURED = 0x11
    SET_POSITIONS_CONFIGURED = 0x12
    RESET_SETTINGS = 0x10
    GET_CURRENT_POSITION = 0x22
    GET_OPEN_POSITION = 0x23
    GET_CLOSED_POSITION = 0x24
    SWITCH_DIRECTIONS = 0x05

    # -- power ----------------------------------------------------------------
    GET_BATTERY_VOLTAGE = 0x04  # mV
    GET_BATTERY_PCT = 0x0B
    GET_BATTERY_CURRENT = 0x1F
    GET_BATTERY_CENTER = 0x20
    GET_INPUT_VOLTAGE = 0x1D  # mV; ~5000 when USB-C is supplying
    SET_CHARGER_ENABLED = 0x21
    GET_MP2672A_STATUS = 0x38  # the charger IC
    GET_MP2672A_FAULT = 0x39
    GET_MP2672A_I2C_ERROR = 0x3D
    GET_BATTERY_CURRENT_MAX = 0x47

    # -- motor health ---------------------------------------------------------
    GET_MOVE_COUNT = 0x09
    GET_MOTOR_MOVING = 0x19
    GET_MOTOR_STATUS = 0x3B
    GET_LAST_MOVE_COMMAND_STATUS = 0x3C
    GET_LAST_MOVE_DURATION = 0x0D  # ms
    GET_LAST_MOVE_MAX_RPM = 0x0E
    GET_LAST_MOVE_MAX_PWM = 0x55
    GET_LAST_MOVE_LOW_VOLTAGE_COUNT = 0x56
    GET_LAST_MOVE_HIGH_CURRENT_COUNT = 0x57
    GET_LAST_MOVE_NORMAL_COUNT = 0x58
    GET_LAST_MOVE_SMALLEST_CELL_MIN = 0x54
    GET_RPM = 0x1E
    SET_SPEED = 0x0C
    GET_SPEED = 0x0F

    # -- environment / identity ----------------------------------------------
    GET_DRIVER_TEMPERATURE = 0x16  # little-endian float32, degrees C
    GET_DIE_TEMPERATURE = 0x1A
    GET_LIGHT_LEVEL = 0x3E
    GET_FIRMWARE_VERSION = 0x27
    GET_BOARD = 0x28
    GET_BOARD_REVISION = 0x29
    GET_MAC_ADDRESS = 0x25
    GET_DEVICE_NAME = 0x14
    SET_DEVICE_NAME = 0x15  # ASCII only, no UTF-8
    GET_BOOT_COUNTER = 0x18
    GET_SECONDS_SINCE_BOOT = 0x49
    IDENTIFY = 0x17  # the device makes a noise -- the only way to tell two units apart
    REBOOT = 0x13
    GO_TO_SLEEP = 0x26

    # -- radios ---------------------------------------------------------------
    SET_ZIGBEE_ENABLED = 0x50
    GET_ZIGBEE_ENABLED = 0x51
    RESET_ZIGBEE = 0x46
    SET_TOUCH_ENABLED = 0x52
    GET_TOUCH_ENABLED = 0x53
    SET_ADV_INTERVAL = 0x34
    GET_ADV_INTERVAL = 0x35
    SET_TX_POWER = 0x36
    GET_TX_POWER = 0x37

    # -- schedules ------------------------------------------------------------
    SET_TIME = 0x2A
    GET_TIME = 0x2B
    ADD_TRIGGER = 0x2C
    REMOVE_TRIGGER = 0x2D
    GET_TRIGGER = 0x2E
    EDIT_TRIGGER = 0x2F
    REMOVE_ALL_TRIGGERS = 0x30
    GET_TRIGGER_IDS = 0x31
    SET_TIMEZONE_OFFSET = 0x32
    GET_TIMEZONE_OFFSET = 0x3F
    SET_COORDINATES = 0x33
    GET_COORDINATES = 0x40
    GET_SUNRISE_SUNSET = 0x41


#: Opcodes that change persistent state or move the motor. Anything here should be behind
#: an explicit user action, never a poll.
WRITE_COMMANDS = frozenset(
    {
        Cmd.OPEN, Cmd.CLOSE, Cmd.STOP, Cmd.SET_CLOSED_PCT,
        Cmd.SET_CLOSED_POSITION, Cmd.SET_OPEN_POSITION, Cmd.SET_POSITIONS_CONFIGURED,
        Cmd.RESET_SETTINGS, Cmd.SWITCH_DIRECTIONS, Cmd.SET_SPEED, Cmd.SET_DEVICE_NAME,
        Cmd.SET_ZIGBEE_ENABLED, Cmd.RESET_ZIGBEE, Cmd.SET_TOUCH_ENABLED,
        Cmd.SET_CHARGER_ENABLED, Cmd.SET_ADV_INTERVAL, Cmd.SET_TX_POWER, Cmd.REBOOT,
        Cmd.GO_TO_SLEEP, Cmd.SET_TIME, Cmd.SET_TIMEZONE_OFFSET, Cmd.SET_COORDINATES,
        Cmd.ADD_TRIGGER, Cmd.REMOVE_TRIGGER, Cmd.EDIT_TRIGGER, Cmd.REMOVE_ALL_TRIGGERS,
    }
)


class ProtocolError(Exception):
    """A reply could not be parsed as a frame, or answered a different opcode."""


def build(opcode: Cmd | int, payload: bytes = b"") -> bytes:
    """Build one request frame.

    A getter is ``build(Cmd.GET_ZIGBEE_ENABLED)`` -> ``51 00``.

    .. warning::
       Never write a *bare* opcode byte with no length byte. On an SS3 that is malformed
       framing; on an SS2 a bare ``0x51`` is a factory reset. Always go through this.
    """
    if len(payload) > 253:
        raise ValueError(f"payload too long for one frame: {len(payload)} bytes")
    return bytes([int(opcode), len(payload)]) + bytes(payload)


def parse(reply: bytes, expect: Cmd | int | None = None) -> bytes:
    """Return the DATA of a reply frame, checking the framing and (optionally) the opcode.

    The device answers a write by leaving the reply in the read characteristic, so a stale
    value is read back if the device ignored the command. Passing ``expect`` catches that.
    """
    if len(reply) < 2:
        raise ProtocolError(f"short frame: {reply.hex(' ') or '(empty)'}")
    opcode, length = reply[0], reply[1]
    if expect is not None and opcode != int(expect):
        raise ProtocolError(
            f"reply is for opcode {opcode:#04x}, expected {int(expect):#04x} "
            "(a stale read -- the device may have ignored the command)"
        )
    data = reply[2 : 2 + length]
    if len(data) != length:
        raise ProtocolError(
            f"frame claims {length} data bytes, got {len(data)}: {reply.hex(' ')}"
        )
    return data


def as_int(data: bytes) -> int | None:
    """Little-endian unsigned int, or None for an empty payload."""
    return int.from_bytes(data, "little") if data else None


def as_bool(data: bytes) -> bool | None:
    v = as_int(data)
    return None if v is None else bool(v)


def as_float(data: bytes) -> float | None:
    """Little-endian float32 -- the encoding used by the temperature getters."""
    import struct

    if len(data) != 4:
        return None
    return struct.unpack("<f", data)[0]


def as_text(data: bytes) -> str | None:
    try:
        text = data.decode("ascii").rstrip("\x00")
    except UnicodeDecodeError:
        return None
    return text or None


@dataclass(frozen=True)
class Advertisement:
    """What an SS3 broadcasts without being connected to.

    This is the whole reason the integration can be cheap on battery: position and charge
    arrive passively, and a connection is only needed to command the motor or to read the
    richer diagnostics.
    """

    closed_percent: int
    """0 = fully open, 100 = fully closed. The device's own convention, not HA's."""

    battery_percent: int

    @property
    def ha_position(self) -> int:
        """Home Assistant cover position: 100 = open, 0 = closed. The inverse."""
        return 100 - self.closed_percent


def parse_advertisement(manufacturer_data: dict[int, bytes]) -> Advertisement | None:
    """Decode the manufacturer payload from a scan result, or None if it is not an SS3.

    On firmware 3.0.17+0 the payload is three bytes, ``10 <position> <battery>`` -- e.g.
    ``10 00 3e`` is fully open with 62 % charge.
    """
    raw = manufacturer_data.get(MANUFACTURER_ID)
    if raw is None or len(raw) < 3:
        return None
    closed_percent, battery = raw[1], raw[2]
    if not (0 <= closed_percent <= 100) or not (0 <= battery <= 100):
        return None
    return Advertisement(closed_percent=closed_percent, battery_percent=battery)
