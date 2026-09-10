"""Engineering metrics evaluated from a :class:`FieldResult`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.model_refs import freeze_mapping


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    spec: MetricSpec
    status: str = "available"
    reason: str = ""


@dataclass(frozen=True)
class PerformanceResult:
    result_id: str
    source_result_id: str
    metrics: Mapping[str, MetricValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", freeze_mapping(self.metrics))

