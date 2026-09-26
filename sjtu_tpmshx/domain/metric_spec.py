"""Explicit metric meaning for backend-independent postprocessing."""
from __future__ import annotations

from dataclasses import dataclass

METRIC_KINDS = {
    'Q_A': 'Q', 'Q_B': 'Q', 'Q_cold': 'Q',
    'Q_richardson_A': 'Q', 'Q_richardson_B': 'Q',
    'dP_A': 'dP', 'dP_B': 'dP', 'T_out_A': 'T_out', 'T_out_B': 'T_out',
    'mass_flow_A': 'mass_flow', 'mass_flow_B': 'mass_flow',
    'mass_imbalance_rel_A': 'mass_imbalance_rel',
    'mass_imbalance_rel_B': 'mass_imbalance_rel', 'Re_A': 'Re', 'Re_B': 'Re',
}
_CORE_UNITS = {
    'Q': ('W', 'W/m'), 'dP': ('Pa',), 'T_out': ('K',), 'mass': ('kg', 'kg/m'),
    'mass_flow': ('kg/s', 'kg/(s m)', 'kg/(m s)'), 'mass_imbalance_rel': ('1',),
    'energy_imbalance_rel': ('1',), 'Re': ('1',),
}


def full_metric_version(name: str) -> str:
    """Current full-compute definitions; approximation modes retain their own."""
    if name in ('dP_A', 'dP_B'):
        return 'pressure_face_v1'
    if name in ('Q', 'Q_A', 'Q_B', 'Q_richardson_A', 'Q_richardson_B',
                'T_out_A', 'T_out_B', 'mass_flow_A', 'mass_flow_B',
                'energy_imbalance_rel'):
        return 'native_boundary_v1'
    return 'three_module_v1'


@dataclass(frozen=True)
class MetricSpec:
    name: str
    unit: str
    definition_version: str = "three_module_v1"
    description: str = ""

    def __post_init__(self) -> None:
        expected = _CORE_UNITS.get(METRIC_KINDS.get(self.name, self.name))
        if not self.name or not self.unit or not self.definition_version:
            raise ValueError("MetricSpec requires name, unit and definition_version")
        if expected is not None and self.unit not in expected:
            raise ValueError(f"{self.name} must use {expected}, not {self.unit}")
