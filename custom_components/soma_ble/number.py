"""The jog step.

A local preference that says how far each press of `Jog open` / `Jog closed` moves the
shade. It is kept here rather than as a fixed constant because the right size changes
during the job: long nudges to cross the window, short ones to land on the stop.
"""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .entity import SomaEntity

#: 15 s is the same ceiling the `jog` service enforces, and for the same reason: while
#: uncalibrated the motor has NO end stops, so this duration is the only thing bounding
#: travel. A box rather than a slider, because this is a number someone types deliberately.
JOG_STEP = NumberEntityDescription(
    key="jog_step",
    translation_key="jog_step",
    entity_category=EntityCategory.CONFIG,
    device_class=NumberDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    native_min_value=0.1,
    native_max_value=15,
    native_step=0.1,
    mode=NumberMode.BOX,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SomaJogStep(entry.runtime_data)])


class SomaJogStep(SomaEntity, RestoreNumber):
    """How long each jog button press runs the motor.

    Local only -- it never touches the shade, so it must not go through
    `async_command_and_refresh`. Setting it is not a reason to open a Bluetooth connection.
    """

    entity_description = JOG_STEP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, JOG_STEP.key)
        self.entity_description = JOG_STEP

    @property
    def available(self) -> bool:
        # A preference, not a reading. It stays usable while the shade is out of range --
        # and in particular it must stay usable when the shade cannot be heard, so the step
        # can be set BEFORE walking over to the window.
        return True

    @property
    def native_value(self) -> float:
        return self.coordinator.jog_seconds

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None:
            if last.native_value is not None:
                self.coordinator.jog_seconds = float(last.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.jog_seconds = float(value)
        self.async_write_ha_state()
