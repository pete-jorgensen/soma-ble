"""Radio and touch settings.

⚠️ The Zigbee switch is here because turning the radio on is what makes the shade usable
over Zigbee at all -- it ships **off from the factory** and the documented way to enable it
is the vendor phone app. Enabling it over BLE removes the app from the loop entirely.

⛔ The Zigbee stack only starts at boot, so flipping this on is not enough on its own: the
motor has to be rebooted afterwards (there is a Reboot button). Skipping that looks exactly
like the switch silently failing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .device import SomaState
from .entity import SomaEntity
from .protocol import Cmd


@dataclass(frozen=True, kw_only=True)
class SomaSwitchDescription(SwitchEntityDescription):
    value: Callable[[SomaState], bool | None]
    setter: Cmd


SWITCHES: tuple[SomaSwitchDescription, ...] = (
    SomaSwitchDescription(
        key="touch_enabled",
        translation_key="touch_enabled",
        entity_category=EntityCategory.CONFIG,
        value=lambda s: s.touch_enabled,
        setter=Cmd.SET_TOUCH_ENABLED,
    ),
    SomaSwitchDescription(
        key="zigbee_radio",
        translation_key="zigbee_radio",
        entity_category=EntityCategory.CONFIG,
        value=lambda s: s.zigbee_enabled,
        setter=Cmd.SET_ZIGBEE_ENABLED,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SomaSwitch(entry.runtime_data, d) for d in SWITCHES)


class SomaSwitch(SomaEntity, SwitchEntity):
    entity_description: SomaSwitchDescription

    def __init__(self, coordinator, description: SomaSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.state_obj)

    async def _set(self, on: bool) -> None:
        # The payload width and encoding for these setters are not documented. The refresh
        # that follows is what confirms the write took -- never trust the write alone.
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_command(
                self.entity_description.setter, bytes([1 if on else 0])
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
