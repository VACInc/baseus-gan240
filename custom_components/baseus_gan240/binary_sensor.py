"""Read-only charger setting/status sensors."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
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


class BaseusBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
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
        return self.entity_description.value_fn(self.coordinator.data)
