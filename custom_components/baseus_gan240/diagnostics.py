"""Allowlisted diagnostics: no addresses, identifiers, adapters or raw errors."""

from .const import MODEL


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "model": MODEL,
        "available": coordinator.last_update_success,
        "disable_mask": coordinator.data if coordinator.last_update_success else None,
        "poll_interval_seconds": 60,
    }
