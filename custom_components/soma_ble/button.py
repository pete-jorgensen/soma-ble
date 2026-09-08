"""Calibration, and the two buttons that make a shade findable and recoverable.

⛔ **Calibration latches.** Once the limits are committed the motor ignores further
mark commands and stops responding to the raw jog, so the only way to re-calibrate is
`Clear travel limits`. That is why these buttons exist at all: without them a shade
calibrated wrongly is stuck that way unless you own the vendor phone app.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .device import SomaDevice
from .entity import SomaEntity
from .protocol import Cmd


@dataclass(frozen=True, kw_only=True)
class SomaButtonDescription(ButtonEntityDescription):
    press: Callable[[SomaDevice], Coroutine[Any, Any, None]]
    #: True for buttons that only do anything on an UNcalibrated shade. They are disabled
    #: once it is calibrated rather than left to fail silently.
    uncalibrated_only: bool = False


BUTTONS: tuple[SomaButtonDescription, ...] = (
    SomaButtonDescription(
        # The device makes a noise. On a product that advertises no name and looks
        # identical to every other one, this is the only way to tell which is which.
        key="identify",
        translation_key="identify",
        entity_category=EntityCategory.DIAGNOSTIC,
        press=lambda d: d.async_command(Cmd.IDENTIFY),
    ),
    SomaButtonDescription(
        key="mark_open",
        translation_key="mark_open",
        entity_category=EntityCategory.CONFIG,
        uncalibrated_only=True,
        press=lambda d: d.async_calibrate("mark_open"),
    ),
    SomaButtonDescription(
        key="mark_closed",
        translation_key="mark_closed",
        entity_category=EntityCategory.CONFIG,
        uncalibrated_only=True,
        press=lambda d: d.async_calibrate("mark_closed"),
    ),
    SomaButtonDescription(
        key="commit_limits",
        translation_key="commit_limits",
        entity_category=EntityCategory.CONFIG,
        uncalibrated_only=True,
        press=lambda d: d.async_calibrate("commit"),
    ),
    SomaButtonDescription(
        # Despite the underlying opcode's name (CMD_RESET_SETTINGS) it clears ONLY the
        # limits, the configured flag and the encoder position. The Zigbee pairing, radio
        # flags, speed, name and counters all survive.
        key="clear_limits",
        translation_key="clear_limits",
        entity_category=EntityCategory.CONFIG,
        press=lambda d: d.async_calibrate("reset"),
    ),
    SomaButtonDescription(
        key="reboot",
        translation_key="reboot",
        entity_category=EntityCategory.CONFIG,
        press=lambda d: d.async_command(Cmd.REBOOT),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SomaButton(entry.runtime_data, d) for d in BUTTONS)


class SomaButton(SomaEntity, ButtonEntity):
    entity_description: SomaButtonDescription

    def __init__(self, coordinator, description: SomaButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self.entity_description.uncalibrated_only:
            # Acked and ignored by the firmware once committed -- so do not offer it.
            return self.state_obj.positions_configured is not True
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_command_and_refresh(
            self.entity_description.press(self.coordinator.device)
        )
