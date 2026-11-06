"""Two update paths, because the device has two very different kinds of data.

* **Passive.** Every advertisement carries position and battery. That arrives for free,
  within seconds, without waking the device -- so the cover and the battery sensor are
  live even though this is a battery-powered BLE device.
* **Active.** Everything else -- charger state, temperatures, motor telemetry, calibration
  -- needs a connection, so it runs on a long interval and on demand.

Keeping them apart is the whole point. Polling the device every 30 seconds for a position
it is already broadcasting would flatten the cells for nothing.

WORKS THROUGH BLUETOOTH PROXIES
-------------------------------
Every Bluetooth operation here goes through Home Assistant's own ``bluetooth`` component
rather than through bleak directly, which is what makes an **ESPHome Bluetooth proxy** (or
any other HA-registered adapter) usable: HA picks whichever adapter or proxy currently
hears the shade best, and hands back a ``BLEDevice`` bound to that route.

Three things make that work, and all three are load-bearing:

* the two paths ask for different things. The advertisement subscription does NOT require
  a connectable route -- position and battery ride in the advertisement, so a
  forward-only proxy is genuinely useful. Connecting DOES require one, so the route is
  re-resolved with ``connectable=True`` immediately before every connection.
* the ``BLEDevice`` is refreshed from every advertisement, so if the shade moves between
  proxies -- or a proxy reboots -- the next connection uses the new route instead of a
  stale one that fails for no visible reason.
* nothing calls ``bleak.BleakScanner`` or constructs ``BleakClient`` from a bare address.
  Either would bypass HA entirely and only ever use the local adapter, which is the usual
  reason an integration "does not work over my proxy".
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ADVERTISEMENT_WAIT,
    COMMAND_BUSY_MESSAGE,
    DEFAULT_JOG_SECONDS,
    DOMAIN,
    MOTION_FOLLOW_UP,
    POST_COMMAND_SETTLE,
    SCAN_INTERVAL,
)
from .device import SomaConnectionError, SomaDevice, SomaState
from .protocol import parse_advertisement

_LOGGER = logging.getLogger(__name__)


class SomaCoordinator(DataUpdateCoordinator[SomaState]):
    """Owns the device object and both update paths."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: SomaDevice) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {device.address}",
            update_interval=SCAN_INTERVAL,
            # This keyword sets the floor in hacs.json. DataUpdateCoordinator gained a
            # `config_entry` PARAMETER in Home Assistant 2024.11.0; it does not exist in
            # 2024.10.0 or earlier, where this is a TypeError at setup. Do not lower the
            # hacs.json minimum below that.
            config_entry=entry,
        )
        self.device = device
        self._unregister: callback | None = None
        self._unregister_unavailable: callback | None = None
        self._motion_task: asyncio.Task | None = None
        #: Not a queue. A press that is waiting for an advertisement looks identical to
        #: nothing happening, so a second press is the natural response -- and two moves
        #: landing together travel twice as far as either was meant to.
        self._command_in_flight = False
        #: Duration the jog buttons use, in seconds. Owned here rather than on the device
        #: because it is a user preference about how to drive the motor, not a motor fact.
        #: The `Jog step` number entity writes it and restores it across restarts.
        self.jog_seconds: float = DEFAULT_JOG_SECONDS

    def _refresh_ble_device(self) -> None:
        """Re-resolve the route to the shade through HA's bluetooth stack.

        ``async_ble_device_from_address`` is what returns a proxy-backed device when the
        shade is only in range of an ESPHome proxy. Without this the integration would work
        only for shades near the HA host's own adapter.
        """
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.device.address, connectable=True
        )
        if ble_device is not None:
            self.device.set_ble_device(ble_device)

    async def _async_wait_for_route(self) -> None:
        """Resolve a connectable route, waiting for the next advertisement if need be.

        This is what makes a user-pressed control reliable on a sleepy motor.

        Home Assistant can only open a connection while a recent CONNECTABLE advertisement
        is in its discovered set. That record does go stale in practice, for minutes at a
        time, and every command issued while it is stale fails instantly with "no
        connectable path". Waiting for the next advertisement beats reporting a failure the
        user cannot act on.

        The motor is not the cause: `GET_ADV_INTERVAL` reads a 100 ms / 150 ms BLE pair,
        so the radio advertises about ten times a second. Something between the radio and
        the coordinator drops them, and the wait covers that gap.

        Only user-initiated work waits. The background refresh does not -- it runs every 30
        minutes and can simply try again.
        """
        if (
            ble_device := bluetooth.async_ble_device_from_address(
                self.hass, self.device.address, connectable=True
            )
        ) is None:
            try:
                service_info = await bluetooth.async_process_advertisements(
                    self.hass,
                    lambda service_info: True,
                    {"address": self.device.address, "connectable": True},
                    bluetooth.BluetoothScanningMode.ACTIVE,
                    int(ADVERTISEMENT_WAIT),
                )
            except asyncio.TimeoutError as err:
                raise SomaConnectionError(
                    f"{self.device.address} did not advertise a connectable route within "
                    f"{int(ADVERTISEMENT_WAIT)} s, so there was nothing to connect to. "
                    "The motor advertises about ten times a second, so this usually means "
                    "the adapter or proxy has stopped delivering its advertisements -- "
                    "check the proxy nearest the shade. Pressing the motor's pinhole "
                    "button, or reloading this integration, is the quick way to retry."
                ) from err
            ble_device = service_info.device
        self.device.set_ble_device(ble_device)

    async def _async_update_data(self) -> SomaState:
        """The connected refresh."""
        self._refresh_ble_device()
        try:
            return await self.device.async_refresh()
        except SomaConnectionError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def _advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Position and battery, straight off the air."""
        adv = parse_advertisement(dict(service_info.manufacturer_data))
        if adv is None:
            return
        self.device.state.apply_advertisement(adv)

        # NOT async_set_updated_data(). Its own docstring is "notify listeners and RESET
        # REFRESH INTERVAL": it unschedules the timer and reschedules it from now. A device
        # that advertises every few seconds would therefore push the connected refresh into
        # the future indefinitely, and everything not carried in the advertisement --
        # calibration state, charger, temperatures, motor telemetry -- would freeze at its
        # startup value. Update the data and notify listeners without touching the
        # scheduler.
        self.data = self.device.state
        self.async_update_listeners()

    async def async_start(self) -> None:
        """Subscribe to advertisements for this address."""
        self._unregister = bluetooth.async_register_callback(
            self.hass,
            self._advertisement,
            # connectable=False on purpose: position and battery ride in the
            # advertisement, so a proxy that can only forward advertisements is useful
            # here. The CONNECTABLE route is resolved separately, per connection, by
            # _refresh_ble_device().
            {"address": self.device.address, "connectable": False},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        # Seed from whatever the stack already heard, so entities are populated before the
        # first advertisement rather than sitting unknown for a scan interval.
        if service_info := bluetooth.async_last_service_info(
            self.hass, self.device.address, connectable=False
        ):
            self._advertisement(service_info, bluetooth.BluetoothChange.ADVERTISEMENT)
        # Availability is a property; it is only re-read when state is written. See
        # `_unavailable`.
        self._unregister_unavailable = bluetooth.async_track_unavailable(
            self.hass, self._unavailable, self.device.address, connectable=False
        )

    @callback
    def _publish(self) -> None:
        """Push `device.state` to the entities.

        Required after any read that did not go through the coordinator's own refresh.
        `device.state` is the SAME object as `self.data`, so a read updates it in place and
        every entity keeps rendering the old value until something calls
        `async_update_listeners`. A read nobody is told about is a read that did not happen.

        Deliberately NOT `async_set_updated_data` -- see `_advertisement` for why that one
        would push the scheduled refresh into the future indefinitely.
        """
        self.data = self.device.state
        self.async_update_listeners()

    @callback
    def _unavailable(self, info: bluetooth.BluetoothServiceInfoBleak) -> None:
        """The stack has stopped hearing the shade.

        Entity availability is a property, so it is only re-evaluated when something writes
        state. Without this subscription a shade that went silent would keep showing its
        last reading as current until the next scheduled refresh -- up to 30 minutes --
        which is precisely what `SomaEntity.available` claims to prevent.
        """
        _LOGGER.debug("%s: no longer seen by any adapter or proxy", self.device.address)
        self.async_update_listeners()

    @callback
    def async_stop(self) -> None:
        if self._motion_task is not None:
            self._motion_task.cancel()
            self._motion_task = None
        if self._unregister_unavailable is not None:
            self._unregister_unavailable()
            self._unregister_unavailable = None
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    async def _async_follow_motion(self) -> None:
        """Re-read `motor moving` until the shade reports itself stopped.

        Nothing else can do this. The read that rides on the move's own connection
        necessarily catches the motor still running; advertisements never carry
        `motor moving`, only position and battery; and the scheduled refresh is 30 minutes
        away. Without this the cover shows "Opening" for half an hour after the shade has
        stopped -- a move that worked, reported as one that never finished.

        Bounded, and not a poll: a few widening delays, each one short connection, stopping
        the moment the motor says it has finished.
        """
        for delay in MOTION_FOLLOW_UP:
            await asyncio.sleep(delay)
            try:
                await self.device.async_read_motion()
            except SomaConnectionError as err:
                # The motor goes quiet while it works. Not a fault; the next delay is
                # longer, and giving up quietly beats reporting a failure nobody can act on.
                _LOGGER.debug("%s: motion follow-up: %s", self.device.address, err)
                continue
            self._publish()
            if self.device.state.motor_moving is False:
                return
        _LOGGER.debug(
            "%s: still reporting movement after %s s; leaving it to the scheduled refresh",
            self.device.address, sum(MOTION_FOLLOW_UP),
        )

    async def async_command_and_refresh(
        self, coro, *, refresh: bool = True, follow_motion: bool = False
    ) -> None:
        """Run a command, then re-read.

        The device does not report a move as it happens over BLE, and its advertisement
        can lag a move by a few seconds, so a command is followed by an explicit refresh
        rather than trusting the next broadcast to arrive promptly.

        ``refresh=False`` is for commands that read back what they changed on their own
        connection -- the jog, which changes nothing worth reading, and the moves, which
        piggyback three getters. Following either with the 27-getter read would cost a
        reconnect the motor often refuses, and ~16 s, for values the command cannot have
        changed.
        """
        if self._command_in_flight:
            raise HomeAssistantError(COMMAND_BUSY_MESSAGE)
        self._command_in_flight = True
        try:
            try:
                await self._async_wait_for_route()
            except SomaConnectionError as err:
                # The caller built `coro` before handing it over. Abandoning it unawaited
                # would raise "coroutine was never awaited" from the garbage collector, in
                # an unrelated task, long after the real error was reported.
                coro.close()
                raise UpdateFailed(str(err)) from err
            try:
                await coro
            except SomaConnectionError as err:
                raise UpdateFailed(str(err)) from err
        finally:
            self._command_in_flight = False

        if follow_motion:
            # A BACKGROUND task, not an await: the device lock must be free for STOP.
            # Blocking here until the shade finished would make stopping a moving shade
            # impossible for the length of its travel.
            if self._motion_task is not None:
                self._motion_task.cancel()
            self._motion_task = self.config_entry.async_create_background_task(
                self.hass, self._async_follow_motion(), f"{DOMAIN} motion follow-up"
            )

        if not refresh:
            # The command read back what it changed on its own link -- but a read nobody is
            # told about is a read that did not happen.
            self._publish()
            return
        # The motor has just dropped the link and may still be moving, and a reconnect in
        # the same breath is often refused.
        await asyncio.sleep(POST_COMMAND_SETTLE)
        await self.async_request_refresh()
