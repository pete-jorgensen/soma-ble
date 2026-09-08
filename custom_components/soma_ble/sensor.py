"""Everything the shade knows about itself.

Zigbee exposes three of these (position, battery, link quality). The rest are only
reachable over BLE, and several of them are the difference between "the shade stopped
working" and knowing why: the per-move telemetry says whether the last move stalled, ran
under-voltage, or ran clean.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .device import SomaState
from .entity import SomaEntity


@dataclass(frozen=True, kw_only=True)
class SomaSensorDescription(SensorEntityDescription):
    value: Callable[[SomaState], float | int | str | None]


SENSORS: tuple[SomaSensorDescription, ...] = (
    SomaSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.battery_percent,
    ),
    SomaSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value=lambda s: None if s.battery_voltage_mv is None else s.battery_voltage_mv / 1000,
    ),
    SomaSensorDescription(
        # ~5 V whenever USB-C or the solar panel is supplying. This is how you tell
        # "charging" from "plugged in but not actually charging", which a battery
        # percentage alone cannot answer.
        key="input_voltage",
        translation_key="input_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value=lambda s: None if s.input_voltage_mv is None else s.input_voltage_mv / 1000,
    ),
    SomaSensorDescription(
        key="driver_temperature",
        translation_key="driver_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value=lambda s: s.driver_temperature,
    ),
    SomaSensorDescription(
        key="light_level",
        translation_key="light_level",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.light_level,
    ),
    SomaSensorDescription(
        key="move_count",
        translation_key="move_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.move_count,
    ),
    SomaSensorDescription(
        key="last_move_duration",
        translation_key="last_move_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.last_move_duration_ms,
    ),
    SomaSensorDescription(
        key="last_move_max_rpm",
        translation_key="last_move_max_rpm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.last_move_max_rpm,
    ),
    SomaSensorDescription(
        # How hard the driver had to push. Rising peak PWM at an unchanged load is the
        # early half of the same story the stall counter tells late.
        key="last_move_max_pwm",
        translation_key="last_move_max_pwm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.last_move_max_pwm,
    ),
    SomaSensorDescription(
        # The stall counter. A shade that is binding, over-tensioned or fouled shows up
        # here BEFORE it fails outright, and nothing on the Zigbee side reports it.
        key="last_move_high_current",
        translation_key="last_move_high_current",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.last_move_high_current,
    ),
    SomaSensorDescription(
        key="last_move_low_voltage",
        translation_key="last_move_low_voltage",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.last_move_low_voltage,
    ),
    SomaSensorDescription(
        key="charger_status",
        translation_key="charger_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.charger_status,
    ),
    SomaSensorDescription(
        key="charger_fault",
        translation_key="charger_fault",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.charger_fault,
    ),
    SomaSensorDescription(
        key="boot_counter",
        translation_key="boot_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.boot_counter,
    ),
    SomaSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.firmware,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SomaSensor(coordinator, d) for d in SENSORS)


class SomaSensor(SomaEntity, SensorEntity):
    entity_description: SomaSensorDescription

    def __init__(self, coordinator, description: SomaSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value(self.state_obj)
