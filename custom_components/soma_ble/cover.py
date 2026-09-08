"""The shade itself.

⚠️ **An uncalibrated shade refuses every move.** That is not this integration failing --
it is the motor declining to run without travel limits, and over Zigbee it is completely
invisible: the command is accepted, no error is logged, and the shade reports itself fully
open forever. Here it is surfaced honestly: a move on an uncalibrated shade fails with an
error naming the cause, and the Needs-calibration sensor says so standing still, so the fix
is discoverable rather than hidden behind a link that was never broken.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SomaConfigEntry
from .entity import SomaEntity
from .protocol import Cmd

SERVICE_JOG = "jog"

#: 15 s is a deliberate ceiling. While uncalibrated the motor has NO end stops, so this
#: duration is the only thing bounding travel; a mistyped 120 would run it into the stop.
JOG_SCHEMA = {
    vol.Required("direction"): vol.In(["open", "close"]),
    vol.Required("seconds"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=15)),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: SomaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_JOG, JOG_SCHEMA, "async_jog")
    async_add_entities([SomaCover(entry.runtime_data)])


class SomaCover(SomaEntity, CoverEntity):
    """A roller/venetian lift driven by an SS3."""

    _attr_name = None
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "cover")

    # ⛔ `available` reflects REACHABILITY ONLY, never whether the shade will act. Marking
    # an uncalibrated shade unavailable would be wrong twice over: it misuses the word --
    # such a shade is perfectly reachable, it just refuses to move -- and Home Assistant
    # filters unavailable entities out of entity service calls
    # (`entity_candidates = [e for e in entity_candidates if e.available]`), which would
    # make the `jog` service registered on this entity unreachable in the ONLY state where
    # jogging works. "It will not move, and why" belongs on the Needs-calibration binary
    # sensor and on an error raised by an actual move attempt.

    @property
    def current_cover_position(self) -> int | None:
        """HA's sense: 100 open, 0 closed. The device reports percent CLOSED."""
        return self.state_obj.ha_position

    @property
    def is_closed(self) -> bool | None:
        position = self.state_obj.ha_position
        return None if position is None else position == 0

    @property
    def is_opening(self) -> bool | None:
        # The device reports THAT it is moving, never which way, so the direction has to
        # come from what was commanded -- otherwise every move reads as "opening".
        if self.state_obj.motor_moving is None:
            return None
        return self.coordinator.device.commanded_direction == "opening"

    @property
    def is_closing(self) -> bool | None:
        if self.state_obj.motor_moving is None:
            return None
        return self.coordinator.device.commanded_direction == "closing"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.state_obj
        return {
            "calibrated": state.positions_configured,
            "open_limit": state.open_limit,
            "closed_limit": state.closed_limit,
        }

    def _assert_calibrated(self) -> None:
        """Refuse a move that the motor is certain to ignore, and say why.

        Without this the command is accepted, nothing is logged, the shade does not move,
        and the Zigbee-side symptom returns: position appears to snap back forever.
        """
        if self.state_obj.positions_configured is False:
            raise HomeAssistantError(
                "This shade has no travel limits set, so the motor will ignore every move "
                "command. Calibrate it first: jog it to the top and bottom and press "
                "'Set open limit here' / 'Set closed limit here', then 'Save travel limits'."
            )

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._assert_calibrated()
        # Deliberately a position command, not CMD_OPEN: the raw motor commands only drive
        # an UNcalibrated motor, so on a working shade they would silently do nothing.
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_set_closed_percent(0)
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._assert_calibrated()
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_set_closed_percent(100)
        )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        self._assert_calibrated()
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_set_closed_percent(100 - kwargs[ATTR_POSITION])
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_command(Cmd.STOP)
        )

    async def async_jog(self, direction: str, seconds: float) -> None:
        """Run the motor for a bounded time -- the manual half of calibration.

        Raw OPEN/CLOSE only drive an uncalibrated motor, so this quietly does nothing on a
        calibrated shade. Rather than let that look like a broken service, refuse it.
        """
        if self.state_obj.positions_configured:
            raise HomeAssistantError(
                "This shade is already calibrated, and a calibrated motor ignores jog "
                "commands. Press 'Clear travel limits' first if you want to re-calibrate."
            )
        await self.coordinator.async_command_and_refresh(
            self.coordinator.device.async_jog(direction, seconds)
        )
