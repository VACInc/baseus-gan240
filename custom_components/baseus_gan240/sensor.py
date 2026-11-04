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

from .entity import BaseusEntity
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
        key="heavy_load_status",
        name="Heavy load status bitmap",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.heavy_load_status,
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


class BaseusSensor(BaseusEntity, SensorEntity):
    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        if (data := self.verified_data) is None:
            return None
        return self.entity_description.value_fn(data)
