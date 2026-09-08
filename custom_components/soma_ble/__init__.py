"""SOMA Smart Shades 3 over Bluetooth LE."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import SomaCoordinator
from .device import SomaDevice

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type SomaConfigEntry = ConfigEntry[SomaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SomaConfigEntry) -> bool:
    """Set up one shade."""
    address: str = entry.data[CONF_ADDRESS]
    device = SomaDevice(address)
    coordinator = SomaCoordinator(hass, entry, device)

    # Subscribe to advertisements BEFORE the first connected refresh: connecting needs a
    # BLEDevice, and the advertisement callback is what supplies it.
    await coordinator.async_start()

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        coordinator.async_stop()
        raise

    if coordinator.data is None:
        coordinator.async_stop()
        raise ConfigEntryNotReady(f"no data from {address} yet")

    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SomaConfigEntry) -> bool:
    """Unload one shade."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
