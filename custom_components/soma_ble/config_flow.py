"""Config flow: find shades by their manufacturer id, because nothing else identifies them.

An SS3 advertises **no name** and does not advertise its command service, so the usual
"match on a service UUID" discovery finds nothing at all. The only reliable marker in an
advertisement is the manufacturer id, which is what ``manifest.json`` matches on and what
this flow re-checks.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .protocol import parse_advertisement


def _title(service_info: BluetoothServiceInfoBleak) -> str:
    """A human label. The device has no name, so the address is the only distinguisher."""
    return f"Smart Shades 3 ({service_info.address})"


class SomaBleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """A shade turned up on its own."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if parse_advertisement(dict(discovery_info.manufacturer_data)) is None:
            return self.async_abort(reason="not_supported")
        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered shade."""
        assert self._discovered is not None
        if user_input is not None:
            return self.async_create_entry(
                title=_title(self._discovered),
                data={CONF_ADDRESS: self._discovered.address},
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": _title(self._discovered)},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick from the shades Home Assistant can currently hear."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(self._discovered_devices[address]),
                data={CONF_ADDRESS: address},
            )

        current = self._async_current_ids()
        self._discovered_devices = {
            info.address: info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.address not in current
            and parse_advertisement(dict(info.manufacturer_data)) is not None
        }
        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {a: _title(i) for a, i in self._discovered_devices.items()}
                    )
                }
            ),
        )
