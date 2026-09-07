"""Manual address and narrowly matched Bluetooth discovery configuration."""

import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, LOCAL_NAME
from .coordinator import make_transport
from .transport import BaseusError

ADDRESS = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")


class BaseusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _address: str

    async def _validate(self):
        transport = make_transport(self.hass, self._address)
        try:
            await transport.read()
        finally:
            await transport.close()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS].strip().upper()
            if not ADDRESS.fullmatch(self._address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(self._address)
                self._abort_if_unique_id_configured()
                try:
                    await self._validate()
                except BaseusError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=LOCAL_NAME, data={CONF_ADDRESS: self._address}
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ):
        if discovery_info.name != LOCAL_NAME or not discovery_info.connectable:
            return self.async_abort(reason="not_supported")
        self._address = discovery_info.address.upper()
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": LOCAL_NAME}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._validate()
            except BaseusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=LOCAL_NAME, data={CONF_ADDRESS: self._address}
                )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            errors=errors,
            description_placeholders={"name": LOCAL_NAME},
        )
