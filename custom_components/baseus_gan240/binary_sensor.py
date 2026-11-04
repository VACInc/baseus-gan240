"""Read-only charger setting/status sensors."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .entity import BaseusEntity
from .models import BaseusData


@dataclass(frozen=True, kw_only=True)
class BaseusBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[BaseusData], bool | None]


BINARY_SENSORS = (
    BaseusBinarySensorDescription(
        key="screen",
        name="Screen",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.screen_on,
    ),
    BaseusBinarySensorDescription(
        key="child_lock",
        name="Child lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.child_lock,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        BaseusBinarySensor(entry.runtime_data, entry, description)
        for description in BINARY_SENSORS
    )


class BaseusBinarySensor(BaseusEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self):
        if (data := self.verified_data) is None:
            return None
        return self.entity_description.value_fn(data)
