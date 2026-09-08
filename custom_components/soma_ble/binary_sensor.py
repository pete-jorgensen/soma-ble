"""State that is either true or false, including the one that explains a dead shade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .device import SomaState
from .entity import SomaEntity


@dataclass(frozen=True, kw_only=True)
class SomaBinaryDescription(BinarySensorEntityDescription):
    value: Callable[[SomaState], bool | None]


BINARY_SENSORS: tuple[SomaBinaryDescription, ...] = (
    SomaBinaryDescription(
        # ⭐ The single most useful entity here. An uncalibrated motor refuses every move
        # while reporting a perfectly healthy Zigbee link, so over Zigbee the fault is
        # undiagnosable. This turns it into one boolean you can alert on.
        key="calibrated",
        translation_key="calibrated",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: None if s.positions_configured is None else not s.positions_configured,
    ),
    SomaBinaryDescription(
        key="motor_moving",
        translation_key="motor_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value=lambda s: s.motor_moving,
    ),
    SomaBinaryDescription(
        # Derived, not reported: the charger IC does not expose a clean "charging" bit, but
        # input voltage above ~4.5 V means something is supplying it.
        key="external_power",
        translation_key="external_power",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: None if s.input_voltage_mv is None else s.input_voltage_mv > 4500,
    ),
    SomaBinaryDescription(
        key="zigbee_enabled",
        translation_key="zigbee_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.zigbee_enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SomaBinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class SomaBinarySensor(SomaEntity, BinarySensorEntity):
    entity_description: SomaBinaryDescription

    def __init__(self, coordinator, description: SomaBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.state_obj)
