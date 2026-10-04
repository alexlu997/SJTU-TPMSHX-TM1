"""Public prepared-case execution entry point."""
from dataclasses import replace
from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.domain.provenance import source_context


def run_case(case: CaseData, control: RunControl = RunControl()) -> FieldResult:
    if control.backend not in ('python', 'cpp'):
        raise ValueError(f'unsupported backend: {control.backend}')
    dimension = case.grid.get('dimension')
    mode = case.metadata.get('mode', 'full')
    from sjtu_tpmshx.domain.compute_config import validate_enthalpy_algorithm
    settings = (case.parameters.get('run_settings', {}).get('solver', {})
                if dimension == 2 else case.parameters)
    algorithm = settings.get('enthalpy_algorithm', 'legacy_h_fou')
    validate_enthalpy_algorithm(algorithm, settings.get('enthalpy_temperature_tol_K', 1e-8))
    if algorithm != 'legacy_h_fou' and (control.backend != 'cpp' or mode != 'full'):
        raise ValueError('conservative temperature energy currently requires full compute with backend=cpp')
    if mode != 'full':
        from .backends.python.thermal_native import resolve_true_h_kernel
        resolve_true_h_kernel(case.parameters, supported=False)
    if control.backend == 'cpp':
        if mode == 'quick_design':
            from .backends.cpp.quick_design import run_case as run
        elif mode != 'full':
            raise ValueError(f'unsupported solver mode: {mode}')
        elif dimension == 2:
            from .backends.cpp.full_2d import run_case as run
        elif dimension == 3:
            from .backends.cpp.full_3d import run_case as run
        else:
            raise ValueError(f'unsupported physical dimension: {dimension}')
    elif mode == 'quick_design':
        from .backends.python.quick_design.execution import run_case as run
    elif mode != 'full':
        raise ValueError(f'unsupported solver mode: {mode}')
    elif dimension == 2:
        from .backends.python.two_d.execution import run_case as run
    elif dimension == 3:
        from .backends.python.three_d.execution import run_case as run
    else:
        raise ValueError(f'unsupported physical dimension: {dimension}')
    provenance = dict(preparation=case.metadata.get('provenance', {'status':'not_recorded'}),
                      execution=source_context())
    with warning_scope({}) as records:
        result = run(case, control)
    diagnostics = dict(result.metadata.get('diagnostics', {}))
    diagnostics['warnings_list'] = tuple(dict.fromkeys((
        *case.metadata.get('warnings', ()), *diagnostics.get('warnings_list', ()),
        *warning_messages(records))))
    return replace(result, metadata={**result.metadata, 'diagnostics': diagnostics,
                                     'provenance': provenance})
