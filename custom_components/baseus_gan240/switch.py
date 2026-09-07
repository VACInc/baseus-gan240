"""Four non-optimistic switches; no DC entity or restore behavior."""

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL, PORT_BITS
from .transport import BaseusError


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        BaseusSwitch(entry.runtime_data, entry, port) for port in PORT_BITS
    )


class BaseusSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, port):
        super().__init__(coordinator)
        self.entity_description = SwitchEntityDescription(
            key=port, translation_key=port
        )
        self._port = port
        self._attr_unique_id = f"{entry.unique_id}_{port}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            connections={(CONNECTION_BLUETOOTH, entry.data["address"])},
            manufacturer="Baseus",
            model=MODEL,
            name="Baseus BS-GaN240",
        )

    @property
    def is_on(self):
        if self.coordinator.data is None or not self.coordinator.last_update_success:
            return None
        return not bool(self.coordinator.data & PORT_BITS[self._port])

    async def _set(self, on):
        try:
            await self.coordinator.set_port(self._port, on)
        except BaseusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="control_failed"
            ) from err

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
