"""HA Bluetooth adapter selection and authoritative state publication."""

import asyncio
import logging
from datetime import timedelta

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .transport import BaseusError, BaseusTransport

_LOGGER = logging.getLogger(__name__)


def make_transport(hass, address):
    async def connect(disconnected_callback):
        device = bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        )
        if device is None:
            raise BaseusError("No connectable Bluetooth path to charger")
        return await establish_connection(
            BleakClientWithServiceCache,
            device,
            "Baseus BS-GaN240",
            disconnected_callback=disconnected_callback,
            max_attempts=3,
        )

    return BaseusTransport(connect)


class BaseusCoordinator(DataUpdateCoordinator[int]):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=60),
        )
        self.transport = make_transport(hass, entry.data["address"])
        # Serialize publication as well as I/O, so an earlier poll cannot
        # overwrite a newer service call's verified result.
        self.operation_lock = asyncio.Lock()

    async def _async_update_data(self):
        async with self.operation_lock:
            try:
                return await self.transport.read()
            except BaseusError as err:
                raise UpdateFailed(str(err)) from err

    async def set_port(self, port, on):
        async with self.operation_lock:
            try:
                mask = await self.transport.set_port(port, on)
            except (BaseusError, asyncio.CancelledError) as err:
                self.async_set_update_error(UpdateFailed("State unverified"))
                raise err
            self.async_set_updated_data(mask)

    async def async_shutdown(self):
        await self.transport.close()
        await super().async_shutdown()
