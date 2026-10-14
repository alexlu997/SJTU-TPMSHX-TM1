"""Execute a prepared 2D case with the Python backend."""
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs


def run_case(case: CaseData, control: RunControl = RunControl()):
    """Execute only the numerical stages and capture portable raw evidence."""
    from .runtime import build_runtime
    from .coupling import _run_solvers
    from sjtu_tpmshx.solvers.backends.capture_2d import capture_result
    if control.backend != 'python':
        raise ValueError(f'unsupported backend: {control.backend}')
    control.check_cancelled()
    cfg, prepared = build_execution_inputs(case)
    runtime = build_runtime(cfg, prepared, residual_cb=control.residual)
    display_fields, native, application, diagnostics = _run_solvers(cfg, runtime, control)
    control.check_cancelled()
    native['input_resolution'] = cfg['_input_resolution']
    result = capture_result(case, display_fields, native, application, diagnostics)
    control.report_progress(100)
    return result
