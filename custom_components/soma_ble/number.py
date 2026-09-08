"""Motor speed — a setting the Zigbee interface does not expose at all."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .entity import SomaEntity
from .protocol import Cmd

SPEED = NumberEntityDescription(
    key="speed",
    translation_key="speed",
    entity_category=EntityCategory.CONFIG,
    native_min_value=1,
    native_max_value=100,
    native_step=1,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SomaSpeed(entry.runtime_data)])


class SomaSpeed(SomaEntity, NumberEntity):
    entity_description = SPEED

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, SPEED.key)
        self.entity_description = SPEED

    @property
    def native_value(self) -> float | None:
        return self.state_obj.speed

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_command(Cmd.SET_SPEED, bytes([int(value)]))
        )
