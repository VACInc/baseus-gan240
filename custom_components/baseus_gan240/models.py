"""Immutable coordinator data decoded from documented Baseus app registers."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BaseusData:
    mask: int
    total_power: float | None = None
    temperature: float | None = None
    port_power: dict[str, float] = field(default_factory=dict)
    protocols: dict[str, str] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    priority_output: int | None = None
    screen_on: bool | None = None
    child_lock: bool | None = None
    bluetooth_module_version: str | None = None
    dc_module_version: str | None = None
