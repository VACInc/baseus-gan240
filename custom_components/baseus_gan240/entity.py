"""Shared device identity and fail-closed state access for every platform."""

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
from .coordinator import BaseusCoordinator
from .models import BaseusData


class BaseusEntity(CoordinatorEntity[BaseusCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BaseusCoordinator, entry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            connections={(CONNECTION_BLUETOOTH, entry.data["address"])},
            manufacturer="Baseus",
            model=MODEL,
            name="Baseus BS-GaN240",
        )

    @property
    def verified_data(self) -> BaseusData | None:
        """Return data only while the last update was verified successful."""
        if self.coordinator.data is None or not self.coordinator.last_update_success:
            return None
        return self.coordinator.data
