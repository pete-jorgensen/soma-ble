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

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL
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
            # ⚠️ This keyword sets the floor in hacs.json. DataUpdateCoordinator gained a
            # `config_entry` PARAMETER in Home Assistant 2024.11.0; it does not exist in
            # 2024.10.0 or earlier, where this is a TypeError at setup. Do not lower the
            # hacs.json minimum below that.
            config_entry=entry,
        )
        self.device = device
        self._unregister: callback | None = None

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

        # ⛔ NOT async_set_updated_data(). Its own docstring is "notify listeners and RESET
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

    @callback
    def async_stop(self) -> None:
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    async def async_command_and_refresh(self, coro) -> None:
        """Run a command, then re-read.

        The device does not report a move as it happens over BLE, and its advertisement
        can lag a move by a few seconds, so a command is followed by an explicit refresh
        rather than trusting the next broadcast to arrive promptly.
        """
        self._refresh_ble_device()
        try:
            await coro
        except SomaConnectionError as err:
            raise UpdateFailed(str(err)) from err
        await self.async_request_refresh()
