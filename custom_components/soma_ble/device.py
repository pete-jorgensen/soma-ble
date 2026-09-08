"""Talking to one SOMA Smart Shades 3 over Bluetooth LE.

Everything Home-Assistant-shaped lives above this; everything wire-shaped lives in
``protocol``. This module is the bit in between: hold a connection long enough to run a
batch of frames, decode them into a :class:`SomaState`, and drop it again.

Why it connects in bursts rather than staying connected: the SS3 is battery powered
and advertises its position and battery continuously, so the cheap data needs no
connection at all. A connection is only for commanding the motor and for the diagnostics
that are not advertised.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import CONNECT_RETRIES, CONNECT_TIMEOUT, REPLY_POLL, REPLY_TIMEOUT
from .protocol import (
    READ_UUID,
    WRITE_UUID,
    Advertisement,
    Cmd,
    ProtocolError,
    as_float,
    as_int,
    as_text,
    build,
    parse,
)

_LOGGER = logging.getLogger(__name__)


class SomaConnectionError(Exception):
    """The device could not be reached, or dropped the link mid-exchange."""


class SomaServiceCacheError(SomaConnectionError):
    """The command characteristic was missing from the cached GATT service list.

    ⚠️ This device is unusually prone to it. An SS3 does not advertise its command
    service at all -- ``8998a466-...`` only appears after connecting -- so a connection
    that resolves services early, or a cache populated while another client held the
    device, leaves ``BleakClientWithServiceCache`` certain the characteristic does not
    exist. It presents as ``Characteristic ...5191 was not found!`` on a connection that
    previously worked, and takes every entity unavailable.

    It is recoverable: clear the cache and reconnect.
    """


@dataclass
class SomaState:
    """Everything known about one shade.

    Fields sourced from the advertisement are always present once the device has been
    heard from. Everything else is None until a connected refresh has happened, which is
    deliberate: a diagnostic entity should read "unknown", not zero, before it has data.
    """

    # -- from the advertisement, no connection needed --------------------------
    closed_percent: int | None = None
    battery_percent: int | None = None

    # -- calibration -----------------------------------------------------------
    positions_configured: bool | None = None
    open_limit: int | None = None
    closed_limit: int | None = None
    current_position: int | None = None

    # -- power -----------------------------------------------------------------
    battery_voltage_mv: int | None = None
    input_voltage_mv: int | None = None
    charger_status: int | None = None
    charger_fault: int | None = None

    # -- motor health ----------------------------------------------------------
    motor_moving: bool | None = None
    motor_status: int | None = None
    move_count: int | None = None
    last_move_duration_ms: int | None = None
    last_move_max_rpm: int | None = None
    last_move_max_pwm: int | None = None
    last_move_high_current: int | None = None
    last_move_low_voltage: int | None = None
    speed: int | None = None

    # -- environment / identity -------------------------------------------------
    driver_temperature: float | None = None
    light_level: int | None = None
    firmware: str | None = None
    board: str | None = None
    board_revision: str | None = None
    boot_counter: int | None = None
    zigbee_enabled: bool | None = None
    touch_enabled: bool | None = None

    #: Getters that failed to decode on the last refresh, so the cause is visible rather
    #: than silently absent. Some firmware builds answer a few opcodes with a payload the
    #: reference does not describe.
    unreadable: list[str] = field(default_factory=list)

    @property
    def ha_position(self) -> int | None:
        """HA cover position: 100 open, 0 closed. The device reports the inverse."""
        return None if self.closed_percent is None else 100 - self.closed_percent

    @property
    def calibrated(self) -> bool | None:
        return self.positions_configured

    def apply_advertisement(self, adv: Advertisement) -> None:
        self.closed_percent = adv.closed_percent
        self.battery_percent = adv.battery_percent


#: The connected refresh. Ordered so that a link which drops part way still leaves the most
#: important fields populated.
#:
#: The three identity getters come FIRST even though they never change. `DeviceInfo` is
#: built once, when the entities are created, from whatever the first refresh managed to
#: read. If firmware/board were read last and the link dropped, the device registry would
#: show no firmware permanently, because nothing rewrites device info afterwards. Reading
#: them first makes that unlikely; the `firmware` sensor is the fallback either way.
_REFRESH: tuple[tuple[str, Cmd, str], ...] = (
    ("firmware", Cmd.GET_FIRMWARE_VERSION, "text"),
    ("board", Cmd.GET_BOARD, "text"),
    ("board_revision", Cmd.GET_BOARD_REVISION, "text"),
    ("positions_configured", Cmd.GET_POSITIONS_CONFIGURED, "bool"),
    ("closed_percent", Cmd.GET_CLOSED_PCT, "int"),
    ("battery_percent", Cmd.GET_BATTERY_PCT, "int"),
    ("battery_voltage_mv", Cmd.GET_BATTERY_VOLTAGE, "int"),
    ("input_voltage_mv", Cmd.GET_INPUT_VOLTAGE, "int"),
    ("open_limit", Cmd.GET_OPEN_POSITION, "int"),
    ("closed_limit", Cmd.GET_CLOSED_POSITION, "int"),
    ("current_position", Cmd.GET_CURRENT_POSITION, "int"),
    ("motor_moving", Cmd.GET_MOTOR_MOVING, "bool"),
    ("motor_status", Cmd.GET_MOTOR_STATUS, "int"),
    ("move_count", Cmd.GET_MOVE_COUNT, "int"),
    ("last_move_duration_ms", Cmd.GET_LAST_MOVE_DURATION, "int"),
    ("last_move_max_rpm", Cmd.GET_LAST_MOVE_MAX_RPM, "int"),
    ("last_move_max_pwm", Cmd.GET_LAST_MOVE_MAX_PWM, "int"),
    ("last_move_high_current", Cmd.GET_LAST_MOVE_HIGH_CURRENT_COUNT, "int"),
    ("last_move_low_voltage", Cmd.GET_LAST_MOVE_LOW_VOLTAGE_COUNT, "int"),
    ("speed", Cmd.GET_SPEED, "int"),
    ("charger_status", Cmd.GET_MP2672A_STATUS, "int"),
    ("charger_fault", Cmd.GET_MP2672A_FAULT, "int"),
    ("driver_temperature", Cmd.GET_DRIVER_TEMPERATURE, "float"),
    ("light_level", Cmd.GET_LIGHT_LEVEL, "int"),
    ("boot_counter", Cmd.GET_BOOT_COUNTER, "int"),
    ("zigbee_enabled", Cmd.GET_ZIGBEE_ENABLED, "bool"),
    ("touch_enabled", Cmd.GET_TOUCH_ENABLED, "bool"),
)

def _is_missing_characteristic(err: Exception) -> bool:
    """Is this bleak telling us the characteristic is not in its cached service list?

    Matched on the message rather than the type, because the exception class for this has
    moved between bleak versions and getting it wrong turns a recoverable stale cache into
    a permanently unavailable device.
    """
    text = str(err).lower()
    return "not found" in text and ("characteristic" in text or "5191" in text or "5192" in text)


_DECODERS = {"int": as_int, "bool": lambda d: None if as_int(d) is None else bool(as_int(d)),
             "float": as_float, "text": as_text}


class SomaDevice:
    """One shade. Not tied to Home Assistant; the coordinator wraps it."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.state = SomaState()
        self._lock = asyncio.Lock()
        self._ble_device: BLEDevice | None = None
        # The device reports THAT the motor is moving, never which way. Remember the
        # direction we asked for so the cover can say "opening" or "closing" honestly
        # instead of calling every move an opening one.
        self._commanded_direction: str | None = None

    @property
    def commanded_direction(self) -> str | None:
        """'opening', 'closing', or None once the motor has stopped."""
        if not self.state.motor_moving:
            return None
        return self._commanded_direction

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Hand in the freshest BLEDevice; HA's bluetooth stack owns discovery."""
        self._ble_device = ble_device

    # -- transport ---------------------------------------------------------------

    async def _client(self) -> BleakClientWithServiceCache:
        if self._ble_device is None:
            raise SomaConnectionError(
                f"{self.address} has not been seen by any Bluetooth adapter yet"
            )
        try:
            return await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.address,
                max_attempts=CONNECT_RETRIES,
                timeout=CONNECT_TIMEOUT,
            )
        except Exception as err:  # noqa: BLE001 -- bleak raises a wide family
            raise SomaConnectionError(f"could not connect to {self.address}: {err}") from err

    async def _with_client(self, operation, *, allow_retry: bool = True):
        """Connect, run ``operation(client)``, always disconnect.

        On a stale service cache, clear it and try once more -- that is the documented
        recovery. Without it a single bad cache leaves the device unavailable until the
        config entry is reloaded by hand.
        """
        for attempt in (1, 2):
            client = await self._client()
            try:
                return await operation(client)
            except SomaServiceCacheError:
                if attempt == 2 or not allow_retry:
                    raise
                _LOGGER.debug(
                    "%s: command characteristic missing from the cached services; "
                    "clearing the cache and reconnecting", self.address
                )
                try:
                    await client.clear_cache()
                except Exception:  # noqa: BLE001 -- best effort, the reconnect is the fix
                    _LOGGER.debug("%s: clear_cache failed", self.address, exc_info=True)
            finally:
                await client.disconnect()
        raise SomaConnectionError(f"{self.address}: unreachable after clearing the cache")

    async def _exchange(
        self, client: BleakClientWithServiceCache, cmd: Cmd, payload: bytes = b""
    ) -> bytes:
        """Write one frame and read its reply. Returns the reply DATA."""
        frame = build(cmd, payload)
        try:
            await client.write_gatt_char(WRITE_UUID, frame, response=True)
        except Exception as first:  # noqa: BLE001 -- some builds refuse write-with-response
            if _is_missing_characteristic(first):
                raise SomaServiceCacheError(str(first)) from first
            try:
                await client.write_gatt_char(WRITE_UUID, frame, response=False)
            except Exception as err:  # noqa: BLE001
                if _is_missing_characteristic(err):
                    raise SomaServiceCacheError(str(err)) from err
                raise SomaConnectionError(
                    f"could not write to {self.address}: {err}"
                ) from err

        # Poll for OUR reply rather than sleeping for the worst case. The read
        # characteristic holds the PREVIOUS answer until this command's lands, and the
        # opcode tells the two apart -- so the same check that stops an ignored command
        # reading as a success also lets the fast path be fast. A flat sleep here cost
        # ~19 s of connected time per refresh across the full getter set.
        deadline = asyncio.get_running_loop().time() + REPLY_TIMEOUT
        while True:
            await asyncio.sleep(REPLY_POLL)
            try:
                raw = bytes(await client.read_gatt_char(READ_UUID))
            except Exception as err:  # noqa: BLE001 -- bleak's failures are a wide family
                if _is_missing_characteristic(err):
                    raise SomaServiceCacheError(str(err)) from err
                raise SomaConnectionError(
                    f"link to {self.address} dropped mid-exchange: {err}"
                ) from err
            try:
                return parse(raw, expect=cmd)
            except ProtocolError:
                # Still the previous command's reply. Keep looking until the deadline,
                # then let the last failure propagate with its own context.
                if asyncio.get_running_loop().time() >= deadline:
                    raise

    async def _write_only(
        self, client: BleakClientWithServiceCache, cmd: Cmd, payload: bytes = b""
    ) -> None:
        """Write without waiting for a reply.

        Used for the jog pair, where the settle delay would land between the run command
        and the stop command and make a "0.5 s" jog run for nearly two seconds.
        """
        frame = build(cmd, payload)
        try:
            await client.write_gatt_char(WRITE_UUID, frame, response=True)
        except Exception:  # noqa: BLE001
            await client.write_gatt_char(WRITE_UUID, frame, response=False)

    # -- public operations --------------------------------------------------------

    async def async_refresh(self) -> SomaState:
        """Connect once and read the whole diagnostic surface."""

        async def _read_all(client) -> SomaState:
            unreadable: list[str] = []
            for attr, cmd, kind in _REFRESH:
                try:
                    data = await self._exchange(client, cmd)
                except ProtocolError as err:
                    _LOGGER.debug("%s: %s could not be read: %s", self.address, attr, err)
                    unreadable.append(attr)
                    continue
                value = _DECODERS[kind](data)
                if value is not None:
                    setattr(self.state, attr, value)
            self.state.unreadable = unreadable
            return self.state

        async with self._lock:
            return await self._with_client(_read_all)

    async def async_command(self, cmd: Cmd, payload: bytes = b"") -> None:
        """Send one command and drop the link."""

        async def _send(client) -> None:
            try:
                await self._exchange(client, cmd, payload)
            except ProtocolError:
                # Motion commands do not always leave a matching reply; the state read on
                # the next refresh is the source of truth, not this ack.
                _LOGGER.debug("%s: no matching reply to %s", self.address, cmd.name)

        async with self._lock:
            await self._with_client(_send)

    async def async_set_closed_percent(self, closed_percent: int) -> None:
        """Move to a position. 0 is fully open, 100 fully closed (the device's sense)."""
        target = max(0, min(100, closed_percent))
        current = self.state.closed_percent
        if current is not None and current != target:
            self._commanded_direction = "closing" if target > current else "opening"
        await self.async_command(Cmd.SET_CLOSED_PCT, bytes([target]))

    async def async_jog(self, direction: str, seconds: float) -> None:
        """Run the motor for a bounded time, then stop it.

        Only useful, and only effective, while the shade is UNCALIBRATED -- OPEN/CLOSE stop
        driving the motor once the limits are committed. This is how the travel limits get
        set without the vendor app.
        """
        cmd = Cmd.OPEN if direction == "open" else Cmd.CLOSE

        async def _jog(client) -> None:
            # Probe FIRST with a harmless getter. If the service cache is stale this
            # raises before any motion command goes out, so _with_client's retry cannot
            # ever re-run a movement that already happened.
            await self._exchange(client, Cmd.GET_POSITIONS_CONFIGURED)
            try:
                await self._write_only(client, cmd)
                await asyncio.sleep(seconds)
            finally:
                # ⛔ STOP goes out even if the sleep was CANCELLED (config entry unload, HA
                # shutting down, the calling script stopped) or raised. An uncalibrated
                # motor has no end stops, so this write is the only thing bounding travel;
                # skipping it runs the shade into its mount. Shielded so that a cancellation
                # cannot also cancel the stop.
                try:
                    await asyncio.shield(self._write_only(client, Cmd.STOP))
                    await asyncio.sleep(0.5)
                except Exception:  # noqa: BLE001 -- nothing here may mask the stop attempt
                    _LOGGER.exception("%s: STOP after jog failed", self.address)

        async with self._lock:
            await self._with_client(_jog)

    async def async_calibrate(self, step: str) -> None:
        """One calibration step: ``mark_open``, ``mark_closed``, ``commit`` or ``reset``."""
        cmd = {
            "mark_open": Cmd.SET_OPEN_POSITION,
            "mark_closed": Cmd.SET_CLOSED_POSITION,
            "commit": Cmd.SET_POSITIONS_CONFIGURED,
            "reset": Cmd.RESET_SETTINGS,
        }[step]
        await self.async_command(cmd)

    def diagnostics(self) -> dict[str, Any]:
        """Redacted device diagnostics for a HA download."""
        data = {k: v for k, v in vars(self.state).items()}
        data["address"] = "**REDACTED**"
        return data
