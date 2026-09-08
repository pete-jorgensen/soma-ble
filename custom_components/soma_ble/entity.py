"""Shared base for every SOMA entity."""

from __future__ import annotations

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

    @property
    def state_obj(self) -> SomaState:
        return self.coordinator.data
