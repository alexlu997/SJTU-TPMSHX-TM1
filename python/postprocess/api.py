"""Evaluate stored evidence through the independent native result stage."""
from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.data_types.metric_spec import MetricSpec
from sjtu_tpmshx.data_types.performance_result import PerformanceResult
from sjtu_tpmshx.cpp_interface._native_result_stage import (
    evaluate_applicability as evaluate_applicability,
    evaluate_physical_balance as evaluate_physical_balance,
    evaluate_qualification as evaluate_qualification,
)


def evaluate(result: FieldResult, metric_spec: MetricSpec | None = None) -> PerformanceResult:
    """Return metrics and qualification from recorded evidence."""
    from sjtu_tpmshx.cpp_interface._native_result_stage import evaluate
    return evaluate(result, metric_spec)
