"""Public prepared-case execution entry point."""
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from sjtu_tpmshx.data_types.case_data import CaseData
from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.run_control.provenance import source_context


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
    from sjtu_tpmshx.data_types.compute_config import (
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
    from sjtu_tpmshx.run_control.run_environment import reject_retired_kernel
    from sjtu_tpmshx.run_control.module_ports import resolve_control
    reject_retired_kernel(case.parameters)
    control = resolve_control(control)
    run: Callable[..., FieldResult]
    if mode == 'quick_design':
        from sjtu_tpmshx.cpp_interface.quick_design import run_case as run_quick_design
    elif mode != 'full':
        raise ValueError(f'unsupported solver mode: {mode}')
    elif dimension == 2:
        from sjtu_tpmshx.cpp_interface.full_2d_stage import run_case as run_2d
        run = partial(run_2d, direct_run=_run_retained_2d)
    elif dimension == 3:
        from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case as run_3d
        run = partial(run_3d, retained_run=_run_retained_3d)
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
        metadata['execution_record'] = full_execution_record(case, result,
            sides=metadata.pop('_native_execution_sides', None), thermal=metadata.pop('_native_thermal_execution', None))
        if '_native_applicability' in metadata:
            from sjtu_tpmshx.run_control.run_warnings import captured_scope_notes
            metadata['applicability_evidence'] = dict(metadata.pop('_native_applicability'),
                scope_notes=captured_scope_notes(case, records))
        else:
            from .applicability_evidence import capture_applicability
            metadata['applicability_evidence'] = capture_applicability(case, result, records)
        metadata.pop('_last_closure_ranges', None)
    return replace(result, metadata=metadata)


def _run_retained_2d(*args):
    from sjtu_tpmshx.cpp_interface.solver_library.full_2d import _run_direct
    return _run_direct(*args)


def _run_retained_3d(*args, **kwargs):
    from sjtu_tpmshx.cpp_interface.solver_library.full_3d import _run_retained_case
    return _run_retained_case(*args, **kwargs)
