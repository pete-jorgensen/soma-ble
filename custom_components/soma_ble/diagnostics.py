"""Downloadable diagnostics.

Worth having for this device specifically: almost every question about a misbehaving shade
("is it calibrated?", "did the last move stall?", "is it actually charging?") is answered by
the state dump, and none of it is visible over Zigbee.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import SomaConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SomaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with the Bluetooth address redacted."""
    return {"state": entry.runtime_data.device.diagnostics()}
