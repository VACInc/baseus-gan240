"""Five non-optimistic output switches; no restore behavior."""

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, PORT_BITS
from .entity import BaseusEntity
from .transport import BaseusError


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        BaseusSwitch(entry.runtime_data, entry, port) for port in PORT_BITS
    )


class BaseusSwitch(BaseusEntity, SwitchEntity):
    def __init__(self, coordinator, entry, port):
        super().__init__(coordinator, entry, port)
        self.entity_description = SwitchEntityDescription(
            key=port, translation_key=port
        )
        self._port = port

    @property
    def is_on(self):
        if (data := self.verified_data) is None:
            return None
        return not bool(data.mask & PORT_BITS[self._port])

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
