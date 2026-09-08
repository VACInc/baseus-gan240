"""HA Bluetooth adapter selection and authoritative state publication."""

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .models import BaseusData
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


TELEMETRY_CODES = (
    "0012",  # disable mask
    "001E",  # total power
    "001C",  # USB-C1 power
    "001B",  # USB-C2 power
    "001A",  # USB-C3 power
    "0019",  # USB-A power
    "001D",  # DC power
    "000B",  # hottest internal temperature probe
    "0017",  # USB-C1/C2 negotiated protocols
    "0018",  # USB-C3/USB-A negotiated protocols
    "0011",  # USB-C1 error bitmap
    "0010",  # USB-C2 error bitmap
    "000F",  # USB-C3 error bitmap
    "000E",  # USB-A error bitmap
    "000D",  # DC error bitmap
    "0013",  # heavy-load status bitmap
    "0014",  # priority output
    "0016",  # Bluetooth module version
    "0015",  # DC module version
    "0024",  # screen state
    "0029",  # child lock
)

POWER_CODES = {
    "001C": "c1",
    "001B": "c2",
    "001A": "c3",
    "0019": "a",
    "001D": "dc",
}
ERROR_CODES = {
    "0011": "c1",
    "0010": "c2",
    "000F": "c3",
    "000E": "a",
    "000D": "dc",
}
TYPE_C_PROTOCOLS = ("", "PD3.1", "PD3.0", "SCP", "AFC", "FCP", "QC2.0", "QC3.0", "PPS")
USB_PROTOCOLS = ("", "SCP", "AFC", "FCP", "QC2.0", "QC3.0", "Apple 2.4A")


def _power(registers, code):
    scale, value = registers[code]
    return value / scale if scale else None


def _protocol(options, value):
    return options[value] if 0 <= value < len(options) else f"Unknown ({value})"


def _version(value: int, dc: bool) -> str:
    text = f"{value:04X}"
    if dc:
        return f"{int(text[0], 16)}{int(text[1], 16)}.{int(text[2:], 16):02d}"
    return f"{int(text[0], 16)}.{int(text[1], 16)}.{int(text[2:], 16):02d}"


def decode_data(registers: dict[str, tuple[int, int]]) -> BaseusData:
    protocol_one = registers["0017"][1]
    protocol_two = registers["0018"][1]
    temperature_word = registers["000B"][1]
    return BaseusData(
        mask=registers["0012"][1],
        total_power=_power(registers, "001E"),
        temperature=float(max(temperature_word >> 8, temperature_word & 0xFF) - 100),
        port_power={
            port: _power(registers, code) for code, port in POWER_CODES.items()
        },
        protocols={
            "c1": _protocol(TYPE_C_PROTOCOLS, protocol_one & 0xFF),
            "c2": _protocol(TYPE_C_PROTOCOLS, protocol_one >> 8),
            "c3": _protocol(TYPE_C_PROTOCOLS, protocol_two & 0xFF),
            "a": _protocol(USB_PROTOCOLS, protocol_two >> 8),
        },
        errors={port: registers[code][1] for code, port in ERROR_CODES.items()},
        heavy_load_status=registers["0013"][1],
        priority_output=registers["0014"][1],
        screen_on=registers["0024"][1] == 0,
        child_lock=registers["0029"][1] == 1,
        bluetooth_module_version=_version(registers["0016"][1], False),
        dc_module_version=_version(registers["0015"][1], True),
    )


class BaseusCoordinator(DataUpdateCoordinator[BaseusData]):
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
                return decode_data(await self.transport.read_registers(TELEMETRY_CODES))
            except BaseusError as err:
                raise UpdateFailed(str(err)) from err

    async def set_port(self, port, on):
        async with self.operation_lock:
            try:
                mask = await self.transport.set_port(port, on)
            except (BaseusError, asyncio.CancelledError) as err:
                self.async_set_update_error(UpdateFailed("State unverified"))
                raise err
            if self.data is None:
                self.async_set_updated_data(BaseusData(mask=mask))
            else:
                self.async_set_updated_data(replace(self.data, mask=mask))

    async def async_shutdown(self):
        await self.transport.close()
        await super().async_shutdown()
