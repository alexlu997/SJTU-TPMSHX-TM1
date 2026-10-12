"""Execute a prepared 3D case with the Python backend."""
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs


def run_case(case, control=RunControl()):
    from . import runtime
    from .result_capture import capture_result
    if control.backend != 'python':
        raise ValueError(f'unsupported backend: {control.backend}')
    control.check_cancelled()
    cfg, prepared = build_execution_inputs(case)
    prob = runtime.build_problem(cfg, prepared, control=control)
    hv = runtime._build_hv_machinery(prob)
    outer = runtime._run_outer_coupling_3d(prob, hv, control=control, capture_native=True)
    metrics = runtime._extract_3d_metrics(prob, outer)
    diagnostics = runtime._assemble_3d_diagnostics(prob, outer, metrics)
    control.check_cancelled()
    result = capture_result(case, prob, outer, metrics, diagnostics)
    control.report_progress(100)
    return result
