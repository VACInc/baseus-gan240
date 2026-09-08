"""Read-only power, temperature, protocol and diagnostic sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfPower, UnitOfTemperature
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
from .models import BaseusData


@dataclass(frozen=True, kw_only=True)
class BaseusSensorDescription(SensorEntityDescription):
    value_fn: Callable[[BaseusData], Any]


def _power(key, name, value_fn):
    return BaseusSensorDescription(
        key=key,
        name=name,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=value_fn,
    )


SENSORS = (
    _power("total_power", "Total power", lambda data: data.total_power),
    *(
        _power(
            f"{port}_power",
            f"{name} power",
            lambda data, port=port: data.port_power.get(port),
        )
        for port, name in (
            ("c1", "USB C1"),
            ("c2", "USB C2"),
            ("c3", "USB C3"),
            ("a", "USB A"),
            ("dc", "DC"),
        )
    ),
    BaseusSensorDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.temperature,
    ),
    *(
        BaseusSensorDescription(
            key=f"{port}_protocol",
            name=f"{name} protocol",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data, port=port: data.protocols.get(port),
        )
        for port, name in (
            ("c1", "USB C1"),
            ("c2", "USB C2"),
            ("c3", "USB C3"),
            ("a", "USB A"),
        )
    ),
    *(
        BaseusSensorDescription(
            key=f"{port}_error",
            name=f"{name} error bitmap",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=lambda data, port=port: data.errors.get(port),
        )
        for port, name in (
            ("c1", "USB C1"),
            ("c2", "USB C2"),
            ("c3", "USB C3"),
            ("a", "USB A"),
            ("dc", "DC"),
        )
    ),
    BaseusSensorDescription(
        key="priority_output",
        name="Priority output",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.priority_output,
    ),
    BaseusSensorDescription(
        key="bluetooth_module_version",
        name="Bluetooth module version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.bluetooth_module_version,
    ),
    BaseusSensorDescription(
        key="dc_module_version",
        name="DC module version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.dc_module_version,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        BaseusSensor(entry.runtime_data, entry, description) for description in SENSORS
    )


class BaseusSensor(CoordinatorEntity, SensorEntity):
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
    def native_value(self):
        if self.coordinator.data is None or not self.coordinator.last_update_success:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
