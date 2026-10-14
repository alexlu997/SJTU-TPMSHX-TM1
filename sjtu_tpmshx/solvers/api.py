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
    if control.backend not in case.metadata.get('supported_backends', ('python', 'cpp')):
        raise ValueError(f'prepared research case does not support backend={control.backend}')
    dimension = case.grid.get('dimension')
    mode = case.metadata.get('mode', 'full')
    from sjtu_tpmshx.domain.compute_config import validate_enthalpy_algorithm
    settings = (case.parameters.get('run_settings', {}).get('solver', {})
                if dimension == 2 else case.parameters)
    algorithm = settings.get('enthalpy_algorithm', 'legacy_h_fou')
    validate_enthalpy_algorithm(algorithm, settings.get('enthalpy_temperature_tol_K', 1e-8))
    if algorithm != 'legacy_h_fou' and (control.backend != 'cpp' or mode != 'full'):
        raise ValueError('conservative temperature energy currently requires full compute with backend=cpp')
    explicit_energy_gates = any(settings.get(name) is not None for name in (
        'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol'))
    require_h = settings.get('require_enthalpy_update_on_temperature', False)
    if type(require_h) is not bool:
        raise ValueError('require_enthalpy_update_on_temperature must be boolean')
    explicit_2d_thermal = dimension == 2 and any(settings.get(name) is not None for name in (
        'ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega', 'ltne_enthalpy_tol'))
    if (explicit_energy_gates or require_h or explicit_2d_thermal) and (
            control.backend != 'cpp' or mode != 'full'):
        raise ValueError('explicit energy controls require full compute with backend=cpp')
    if control.backend == 'python' or mode != 'full':
        from sjtu_tpmshx.domain.run_environment import require_python_kernel
        require_python_kernel(case.parameters)
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
    metadata = dict(result.metadata, diagnostics=diagnostics, provenance=provenance)
    if mode == 'full' and result.run_status['execution'] == 'completed':
        from .execution_record import full_execution_record
        metadata['execution_record'] = full_execution_record(case, result)
        from .applicability_evidence import capture_applicability
        metadata['applicability_evidence'] = capture_applicability(case, result, records)
        metadata.pop('_last_closure_ranges', None)
    return replace(result, metadata=metadata)
