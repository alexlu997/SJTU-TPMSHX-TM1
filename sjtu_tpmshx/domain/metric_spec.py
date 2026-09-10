"""Explicit metric meaning for backend-independent postprocessing."""
from __future__ import annotations

from dataclasses import dataclass

_CORE_UNITS = {"Q": "W", "dP": "Pa", "T_out": "K"}


@dataclass(frozen=True)
class MetricSpec:
    name: str
    unit: str
    definition_version: str = "three_module_v1"
    description: str = ""

    def __post_init__(self) -> None:
        expected = _CORE_UNITS.get(self.name)
        if expected is not None and self.unit != expected:
            raise ValueError(f"{self.name} must use {expected}, not {self.unit}")
