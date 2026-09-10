"""Prepared, immutable solver input for the three-module boundary."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.model_refs import ModelRef, freeze_mapping

SCHEMA_VERSION = "three_module_v1"


def _reject_runtime_values(value: Any) -> None:
    """Keep closures and live runtime objects out of a persisted case."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return
    if callable(value):
        raise TypeError("CaseData cannot contain callables or runtime objects")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_runtime_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _reject_runtime_values(item)
        return
    if hasattr(value, "setflags") and hasattr(value, "copy"):
        return
    raise TypeError("CaseData only accepts values that can cross a process boundary")


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

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("CaseData.case_id is required")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported CaseData schema_version: {self.schema_version}")
        for name in ("config_snapshot", "grid", "design_fields", "metadata"):
            _reject_runtime_values(getattr(self, name))
            object.__setattr__(self, name, freeze_mapping(getattr(self, name)))
        object.__setattr__(self, "model_refs", tuple(self.model_refs))

    @classmethod
    def from_compute_config(cls, case_id: str, config: ComputeConfig, **kwargs: Any) -> "CaseData":
        """Capture the existing input authority as a detached case snapshot."""
        return cls(case_id=case_id, config_snapshot=asdict(config), **kwargs)
