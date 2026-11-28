"""Prepared, immutable solver input for the three-module boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from tm1.data_types.compute_config import ComputeConfig
from tm1.data_types.model_refs import ModelRef, freeze_mapping

SCHEMA_VERSION = "three_module_v1"


@dataclass(frozen=True)
class CaseData:
    """A prepared case; runtime state belongs to the solver, never here."""

    case_id: str
    schema_version: str = SCHEMA_VERSION
    config_snapshot: Mapping[str, Any] = field(default_factory=dict)
    grid: Mapping[str, Any] = field(default_factory=dict)
    design_fields: Mapping[str, Any] = field(default_factory=dict)
    model_refs: Sequence[ModelRef] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("CaseData.case_id is required")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported CaseData schema_version: {self.schema_version}")
        for name in ("config_snapshot", "grid", "design_fields", "metadata", "parameters"):
            object.__setattr__(self, name, freeze_mapping(getattr(self, name)))
        if any(not isinstance(ref, ModelRef) for ref in self.model_refs):
            raise TypeError("CaseData.model_refs must contain ModelRef values")
        object.__setattr__(self, "model_refs", tuple(self.model_refs))

    @classmethod
    def from_compute_config(cls, case_id: str, config: ComputeConfig, **kwargs: Any) -> "CaseData":
        """Capture the existing input authority as a detached case snapshot."""
        return cls(case_id=case_id, config_snapshot=config.to_dict(), **kwargs)


def resolved_input_record(case, fluids, shape, directions):
    """Link executed input facts to the validated case resources."""
    return dict(version='prepared_input_v1', source='CaseData.parameters',
                grid_source='CaseData.grid', design_source='CaseData.design_fields',
                grid_shape=tuple(shape), active_sides=tuple(directions), directions=directions,
                grid_length_unit='m', cell_length_unit_in_file='m', cell_length_unit_after_resolution='mm',
                resources={role: dict(model_ref=index, name=case.model_refs[index].name,
                                      version=case.model_refs[index].version)
                           for role, index in case.metadata['model_roles'].items()},
                fluids=fluids)
