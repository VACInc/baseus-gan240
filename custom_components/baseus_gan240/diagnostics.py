"""Allowlisted diagnostics: no addresses, identifiers, adapters or raw errors."""

from .const import MODEL


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    data = coordinator.data if coordinator.last_update_success else None
    return {
        "model": MODEL,
        "available": coordinator.last_update_success,
        "disable_mask": data.mask if data is not None else None,
        "telemetry_fields": sorted(
            key
            for key, value in {
                "total_power": data.total_power if data is not None else None,
                "temperature": data.temperature if data is not None else None,
                "bluetooth_module_version": (
                    data.bluetooth_module_version if data is not None else None
                ),
                "dc_module_version": (
                    data.dc_module_version if data is not None else None
                ),
            }.items()
            if value is not None
        ),
        "poll_interval_seconds": 60,
    }
