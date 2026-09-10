"""Backend-neutral, immutable evidence passed from a solver to postprocessing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from sjtu_tpmshx.domain.model_refs import freeze_mapping
from sjtu_tpmshx.domain.case_data import SCHEMA_VERSION


@dataclass(frozen=True)
class FieldResult:
    """Native fields, boundary evidence and run verdict for one completed run."""

    result_id: str
    case_id: str
    backend_id: str
    schema_version: str = SCHEMA_VERSION
    backend_version: str = ""
    grid: Mapping[str, Any] = field(default_factory=dict)
    fields: Mapping[str, Any] = field(default_factory=dict)
    boundary_fluxes: Mapping[str, Any] = field(default_factory=dict)
    pressure_evidence: Mapping[str, Any] = field(default_factory=dict)
    run_status: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id or not self.case_id or not self.backend_id:
            raise ValueError("FieldResult requires result_id, case_id and backend_id")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported FieldResult schema_version: {self.schema_version}")
        for name in ("grid", "fields", "boundary_fluxes", "pressure_evidence", "run_status", "metadata"):
            object.__setattr__(self, name, freeze_mapping(getattr(self, name)))
