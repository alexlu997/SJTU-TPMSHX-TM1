"""Ports joining preprocess, solver and postprocess without cross-imports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import PerformanceResult


@dataclass(frozen=True)
class RunControl:
    """Non-persistent execution controls; never part of CaseData."""

    backend: str = "python"


class Preprocessor(Protocol):
    def build(self, config: object) -> CaseData: ...


class Solver(Protocol):
    def run(self, case: CaseData, control: RunControl) -> FieldResult: ...


class Postprocessor(Protocol):
    def evaluate(self, result: FieldResult, metric_spec: MetricSpec) -> PerformanceResult: ...
