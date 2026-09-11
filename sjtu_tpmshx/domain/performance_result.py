"""Engineering metrics evaluated from a :class:`FieldResult`."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Mapping

from sjtu_tpmshx.domain.metric_spec import MetricSpec


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    spec: MetricSpec
    status: str = "available"
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, MetricSpec):
            raise TypeError("MetricValue.spec must be a MetricSpec")
        if self.status not in ("available", "insufficient_data", "unsupported", "invalid"):
            raise ValueError(f"unsupported metric status: {self.status}")
        if self.status == "available":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("available metrics require a finite value")
        elif self.value is not None or not self.reason:
            raise ValueError("unavailable metrics require no value and an explicit reason")


@dataclass(frozen=True)
class PerformanceResult:
    result_id: str
    source_result_id: str
    metrics: Mapping[str, MetricValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id or not self.source_result_id:
            raise ValueError("PerformanceResult requires result and source identities")
        if any(not isinstance(key, str) or not isinstance(value, MetricValue)
               for key, value in self.metrics.items()):
            raise TypeError("metrics must map names to MetricValue records")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
