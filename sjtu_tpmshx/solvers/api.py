"""Public prepared-case execution entry point."""
from dataclasses import replace
from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.domain.provenance import source_context


def run_case(case: CaseData, control: RunControl = RunControl(), *,
             resume_state=None, checkpoint=None, checkpoint_due=None) -> FieldResult:
    if case.metadata.get('preprocessor') == 'research_three_d_v1':
        raise ValueError('Python research cases have been retired; prepare a ComputeConfig case')
    if control.backend not in case.metadata.get('supported_backends', ('cpp',)):
        raise ValueError(f'prepared case does not support backend={control.backend}')
    dimension = case.grid.get('dimension')
    mode = case.metadata.get('mode', 'full')
    continuation = resume_state is not None or checkpoint is not None or checkpoint_due is not None
    if continuation and mode != 'full':
        raise ValueError('solver continuation requires full compute with backend=cpp')
    if checkpoint_due is not None and checkpoint is None:
        raise ValueError('checkpoint_due requires a checkpoint callback')
    from sjtu_tpmshx.domain.compute_config import (
        validate_enthalpy_algorithm, validate_simple_velocity_relaxation,
    )
    settings = (case.parameters.get('run_settings', {}).get('solver', {})
                if dimension == 2 else case.parameters)
    relaxation = settings.get('simple_velocity_relaxation')
    validate_simple_velocity_relaxation(relaxation)
    if relaxation is not None and mode != 'full':
        raise ValueError('simple_velocity_relaxation requires full compute with backend=cpp')
    algorithm = settings.get('enthalpy_algorithm', 'legacy_h_fou')
    validate_enthalpy_algorithm(algorithm, settings.get('enthalpy_temperature_tol_K', 1e-8))
    explicit_energy_gates = any(settings.get(name) is not None for name in (
        'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol'))
    require_h = settings.get('require_enthalpy_update_on_temperature', False)
    if type(require_h) is not bool:
        raise ValueError('require_enthalpy_update_on_temperature must be boolean')
    explicit_2d_thermal = dimension == 2 and any(settings.get(name) is not None for name in (
        'ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega', 'ltne_enthalpy_tol'))
    if (explicit_energy_gates or require_h or explicit_2d_thermal) and (
            mode != 'full'):
        raise ValueError('explicit energy controls require full compute with backend=cpp')
    if any(settings.get(name) is not None for name in (
            'model_h_max_iterations', 'model_h_temperature_tol_K', 'model_h_q_relative_tol')) and (
                mode != 'full'):
        raise ValueError('explicit model-h controls require full compute with backend=cpp')
    from sjtu_tpmshx.domain.run_environment import reject_retired_kernel
    from sjtu_tpmshx.domain.module_ports import resolve_control
    reject_retired_kernel(case.parameters)
    control = resolve_control(control)
    if mode == 'quick_design':
        from .backends.cpp.quick_design import run_case as run_quick_design
    elif mode != 'full':
        raise ValueError(f'unsupported solver mode: {mode}')
    elif dimension == 2:
        from .backends.cpp.full_2d import run_case as run
    elif dimension == 3:
        from .backends.cpp.full_3d import run_case as run
    else:
        raise ValueError(f'unsupported physical dimension: {dimension}')
    provenance = dict(preparation=case.metadata.get('provenance', {'status':'not_recorded'}),
                      execution=source_context())
    with warning_scope({}) as records:
        if mode == 'quick_design':
            result = run_quick_design(case, control)
        else:
            result = (run(case, control, resume_state=resume_state, checkpoint=checkpoint,
                          checkpoint_due=checkpoint_due) if continuation else run(case, control))
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
