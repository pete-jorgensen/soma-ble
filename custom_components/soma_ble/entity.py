"""Shared base for every SOMA entity."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import SomaCoordinator
from .device import SomaState


class SomaEntity(CoordinatorEntity[SomaCoordinator]):
    """Common device identity and availability."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SomaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        address = coordinator.device.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"Smart Shades 3 {address[-5:].replace(':', '')}",
            sw_version=coordinator.data.firmware if coordinator.data else None,
            hw_version=coordinator.data.board_revision if coordinator.data else None,
        )

    #: True on read-only entities, whose job is to report a reading: they go unavailable
    #: when the Bluetooth stack stops hearing the shade, so a stale number never reads as
    #: a current one. False on CONTROLS, which stay available whenever the integration is
    #: loaded -- see `available` for why that asymmetry is deliberate and load-bearing.
    _soma_needs_presence = False

    @property
    def available(self) -> bool:
        """Reachability, and ONLY reachability.

        Do NOT fall back to ``CoordinatorEntity.available``, which is
        ``coordinator.last_update_success``. That ties every entity to whether the last
        CONNECTED read worked, and on this device that is a self-inflicted outage:

        1. a command runs, and the motor drops the link and goes quiet;
        2. the refresh that follows the command cannot reconnect, so the coordinator
           records a failure;
        3. all 28 entities go unavailable -- including the cover;
        4. Home Assistant filters unavailable entities out of entity service calls, so
           ``soma_ble.jog`` can no longer be targeted at the cover at all.

        The one control needed to recover is removed by the failure, and reloading the
        config entry is the only way back.

        A CONTROL therefore stays available while the integration is loaded, full stop.
        Not "while the shade answers" either: an SS3 falls silent for minutes after a move,
        so gating controls on presence would remove the jog in exactly
        the window where someone is standing at the window trying to use it. A control the
        user cannot press cannot report why it would have failed; a press that goes on to
        fail raises an error naming the cause, which is strictly more information.

        A READING is the opposite case and is gated on presence, so that a value the stack
        has stopped hearing does not sit on the dashboard looking current.
        """
        if self.coordinator.data is None:
            return False
        if not self._soma_needs_presence:
            return True
        return bluetooth.async_address_present(
            self.hass, self.coordinator.device.address, connectable=False
        )

    @property
    def state_obj(self) -> SomaState:
        return self.coordinator.data
