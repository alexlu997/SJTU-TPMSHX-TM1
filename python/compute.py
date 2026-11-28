"""Own the common prepare, solve and postprocess sequence."""
from collections.abc import Callable
from dataclasses import replace
from time import perf_counter
from uuid import uuid4

from tm1.data_types.case_data import CaseData
from tm1.data_types.compute_config import ComputeConfig
from tm1.data_types.field_result import FieldResult
from tm1.run_control.module_ports import RunControl
from tm1.data_types.performance_result import PerformanceResult
from tm1.run_control.run_warnings import warning_scope, warning_messages


def compute(config: ComputeConfig, *, case_id: str | None = None,
            control: RunControl = RunControl(), progress_cb: Callable[[int], None] | None = None,
            prepare: Callable[..., CaseData] | None = None,
            solve: Callable[[CaseData, RunControl], FieldResult] | None = None,
            evaluate: Callable[[FieldResult], PerformanceResult] | None = None,
            ) -> tuple[CaseData, FieldResult, PerformanceResult]:
    """Return portable stage results and retain this run's timing and warnings.

    progress_cb receives overall progress. RunControl retains raw solver
    progress and the host's backend, cancellation and iteration controls.
    """
    native_preparation = prepare is None and control.cancel_check is None
    if prepare is None:
        from tm1.preprocess.api import prepare_case
        prepare = prepare_case
    if solve is None:
        from tm1.solvers.api import run_case
        solve = run_case
    if evaluate is None:
        from tm1.postprocess.api import evaluate as evaluate_result
        evaluate = evaluate_result
    progress = progress_cb if progress_cb is not None else lambda _percent: None

    def solver_progress(percent):
        progress(20 + int(.7 * percent))
        control.report_progress(percent)

    solver_control = control if progress_cb is None else replace(control, progress=solver_progress)
    control.check_cancelled()
    with warning_scope({}) as records:
        config.validate(_native_preparation=native_preparation)
        control.check_cancelled()
        started = perf_counter()
        case = prepare(config, case_id=str(uuid4()) if case_id is None else case_id)
        timings = {'prepare': perf_counter() - started}
        progress(20)
        control.check_cancelled()
        started = perf_counter()
        result = solve(case, solver_control)
        timings['solve'] = perf_counter() - started
        progress(90)
        control.check_cancelled()
        started = perf_counter()
        performance = evaluate(result)
        timings['postprocess'] = perf_counter() - started
        control.check_cancelled()
        progress(100)
        control.check_cancelled()
        diagnostics = dict(result.metadata.get('diagnostics', {}))
        diagnostics['warnings_list'] = tuple(dict.fromkeys((
            *diagnostics.get('warnings_list', ()), *warning_messages(records))))
        result = replace(result, metadata={**result.metadata,
            'diagnostics': diagnostics, 'timings_s': timings})
    return case, result, performance
