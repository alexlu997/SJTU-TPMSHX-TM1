"""Run saved 2D inputs through one native lifecycle and capture owner."""
import ctypes as ct
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.cpp_interface._native_result_stage import Evidence, detach_stage_fields, record
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.data_types.compute_config import validate_simple_velocity_relaxation
from sjtu_tpmshx.run_control.run_environment import run_environment
from sjtu_tpmshx.cpp_interface._native_preparation_case import _Array, _Kind, _ResultV2
from sjtu_tpmshx.physical_models.envelope import ChokedFlowError
from sjtu_tpmshx.cpp_interface.solver_library._full_2d_abi import _Callbacks, _Config, _EnergyControl, _EnergyEvidence, _Result
from sjtu_tpmshx.cpp_interface.solver_library.enthalpy import _EnergyOptions, _energy_algorithm_query, _energy_options
from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.data_types.validator import compute_volumetric_htc
from sjtu_tpmshx.run_control.run_warnings import current_warnings, merge_warnings, warning_messages, warning_scope
from sjtu_tpmshx.physical_models.nu_correlations import warn_sco2_nu_evidence
from sjtu_tpmshx.cpp_interface.solver_library.model_h import _IterationOptions, _iteration_options
from sjtu_tpmshx.cpp_interface.solver_library.prepared_stage_2d import prepare_stage
from .run_state import NativeRun

_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Size = record('SizeOption', [('present', _U), ('value', _S)])
_Double = record('DoubleOption', [('present', _U), ('value', _D)])
_RequestV1 = record('RunRequestV1', [('abi_version', _U), ('struct_size', _S),
    ('max_iter_simple', _Size), ('max_outer_ltne', _Size),
    *((key, _Double) for key in ('outer_tol_K', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K')),
    ('have_pressure_shooting', _U), ('pressure_shooting', _U), ('convergence_mode', ct.c_char_p),
    ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('explicit_energy', ct.POINTER(_EnergyControl))])
_RequestV2 = record('RunRequestV2', [('abi_version', _U), ('struct_size', _S),
    ('values', _RequestV1), ('envelope_mode', ct.c_char_p)])
_Request = record('RunRequestV3', [('abi_version', _U), ('struct_size', _S),
    ('values', _RequestV2), ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *((key, _Double) for key in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')),
    ('require_enthalpy_update_on_temperature', _U)])
_Control = record('StageControl', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _S), ('callbacks', _Callbacks)])
_Saved = record('SavedCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', ct.POINTER(_ResultV2)), ('area_density_per_m', _Array),
    ('hydraulic_diameter_m', _Array), ('fluid_conductivity', _Array * 2),
    ('inlet_recorded', _U), ('range_captured', ct.POINTER(_U)),
    ('reference_cell_kind', _Kind), ('cell_field_kind', _Kind), ('hydraulic_diameter_kind', _Kind)])
_SavedV2 = record('SavedCaseV2', [('abi_version', _U), ('struct_size', _S),
    ('values', _Saved), ('have_side_geometry', _U), ('side_geometry', (_D * 4) * 2)])


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', _U), ('struct_size', _S), ('owner', ct.c_void_p),
               ('raw', _Result), ('evidence', Evidence), ('resolved', _Config)]

    def __init__(self):
        super().__init__(1, ct.sizeof(type(self)))


_Application = record('CaptureApplication', [
    ('area_density_per_m', _D * 2), ('surface_htc_W_m2K', _D * 2)])
_Summary = record('CaptureSummary', [
    ('model_h_available', _U * 2), ('nu_available', _U * 2), ('pressure_available', _U),
    ('model_h_cell_count', _S * 2), ('model_h_area_m2', _D * 2),
    ('nu_floor', _D * 2), ('nu_floor_fraction', _D * 2),
    ('pressure_min_Pa', _D * 2), ('pressure_max_Pa', _D * 2),
    ('q_net', _D), ('absolute_duty', _D * 2), ('application_hv', _D * 2),
    ('pressure_clip_hits', _S), ('have_finite_duty', _U), ('red_black', _U * 2)])


def _request(cfg, configure_convergence):
    solver = cfg['compute_cfg'].solver
    request = _Request(3, ct.sizeof(_Request),
        _RequestV2(2, ct.sizeof(_RequestV2), _RequestV1(1, ct.sizeof(_RequestV1))))
    values = request.values.values
    for name in ('max_iter_simple', 'max_outer_ltne'):
        value = getattr(solver, name)
        setattr(values, name, _Size(bool(value), value or 0))
    value = solver.outer_tol_K
    values.outer_tol_K = _Double(bool(value), value or 0.)
    settings = SimpleNamespace()
    configure_convergence(settings, cfg, solver)
    values.convergence_mode = settings.convergence_mode.encode()
    for name in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        setattr(values, name, _Double(1, getattr(settings, name)))
    validate_simple_velocity_relaxation(solver.simple_velocity_relaxation)
    if solver.simple_velocity_relaxation is not None:
        values.simple_velocity_relaxation = _Double(1, solver.simple_velocity_relaxation)
    if cfg.get('T_s_init') is not None:
        values.solid_seed_K = _Double(1, cfg['T_s_init'])
    values.have_pressure_shooting = 1
    values.pressure_shooting = cfg.get('p_in_shooting', run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') == '1')
    request.values.envelope_mode = cfg.get('envelope_mode', 'raise').encode()
    energy = _energy_options(solver.enthalpy_algorithm, solver.enthalpy_temperature_tol_K)
    model_h = _iteration_options(vars(solver))
    if model_h is not None:
        values.model_h = model_h
    values.energy = ct.pointer(energy)
    for name, target, kind in (
            ('ltne_enthalpy_outer', 'energy_iterations', _Size),
            ('ltne_enthalpy_nsweep', 'energy_sweeps', _Size),
            ('ltne_enthalpy_omega', 'energy_omega', _Double),
            ('ltne_enthalpy_tol', 'energy_update_tolerance', _Double),
            ('ltne_enthalpy_coupled_energy_tol', 'energy_coupled_tolerance', _Double),
            ('ltne_enthalpy_equation_energy_tol', 'energy_equation_tolerance', _Double)):
        value = getattr(solver, name)
        if value is not None:
            setattr(request, target, kind(1, value))
    request.require_enthalpy_update_on_temperature = solver.require_enthalpy_update_on_temperature
    return request, energy


class _Run(NativeRun):
    api_prefix = 'tpmshx_stage_run_2d'
    advance_name = 'advance_step'
    entry_names = {'create': 'create_saved', 'restore': 'restore_saved', 'release': 'release_run'}
    creation_version = 1
    result_type = _StageResult
    result_release_name = 'tpmshx_stage_run_2d_release_v1'
    error_types = {**NativeRun.error_types, 4: ChokedFlowError, 6: CancelledError}

    def __init__(self, library, saved, request, control, errors, state):
        self.errors = errors
        self.creation_version = saved.abi_version
        common = [ct.POINTER(type(saved)), ct.POINTER(_Request), ct.POINTER(_Control)]
        super().__init__(library, common, [ct.byref(saved), ct.byref(request), ct.byref(control)], control, state)

    def _call(self, function, *args):
        error = ct.create_string_buffer(2048)
        code = function(*args, error, len(error))
        if self.errors:
            raise self.errors[0]
        if code:
            raise self.error_types.get(code, RuntimeError)(error.value.decode())


def _scalars(summary):
    return dict(
        model_h=[dict(cell_count=summary.model_h_cell_count[i], area_m2=summary.model_h_area_m2[i])
                 if summary.model_h_available[i] else None for i in range(2)],
        nu=[dict(floor=summary.nu_floor[i], floor_fraction=summary.nu_floor_fraction[i])
            if summary.nu_available[i] else None for i in range(2)],
        pressure_ranges=([(summary.pressure_min_Pa[i], summary.pressure_max_Pa[i]) for i in range(2)]
                         if summary.pressure_available else None),
        q_net=summary.q_net, absolute_duty=list(summary.absolute_duty),
        pressure_clip_hits=summary.pressure_clip_hits, have_finite_duty=bool(summary.have_finite_duty),
        red_black=[bool(value) for value in summary.red_black])


def run_stage(driver, case, cfg, prepared, control, *, configure_convergence, make_callbacks, saved_version=1,
              resume_state=None, checkpoint=None, checkpoint_due=None):
    """Keep preparation and result storage alive through late application capture."""
    library = driver.library
    try:
        release = library.tpmshx_stage_run_2d_release_v1
        query = library.tpmshx_stage_run_2d_get_capture_v1
        release.argtypes, release.restype = [ct.POINTER(_StageResult)], None
        query.argtypes = [ct.POINTER(_StageResult), ct.POINTER(_Application), ct.POINTER(_Summary)]
        query.restype = ct.c_int
    except AttributeError as error:
        raise ValueError('native library has an incomplete saved 2D stage protocol') from error
    control.check_cancelled()
    uniform, area, diameter, conductivity, recorded, captured, kinds, keepalive = prepare_stage(case, cfg, prepared)
    saved = _Saved(1, ct.sizeof(_Saved), ct.pointer(uniform), area, diameter,
                   (_Array * 2)(*conductivity), recorded, captured, *kinds)
    if saved_version == 2:
        sides = cfg['thermal_geometry']['side_geometry']
        saved = _SavedV2(2, ct.sizeof(_SavedV2), saved, sides is not None)
        if sides is not None:
            for index, side in enumerate('AB'):
                saved.side_geometry[index][:] = sides[side]
    request, energy = _request(cfg, configure_convergence)
    callbacks, errors = make_callbacks(control)
    stage_control = _Control(case.case_id.encode(), driver.table_directory, control.native_cpu_threads(), callbacks)
    energy_query = version_query = None
    if energy.algorithm:
        energy_query = library.tpmshx_full_2d_get_energy_evidence_v1
        energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
        energy_query.restype = ct.c_int
        version_query = _energy_algorithm_query(library)
    result = _StageResult()
    try:
        with _Run(library, saved, request, stage_control, errors, resume_state) as run:
            while run.phase not in (3, 4):
                phase = run.advance()
                if (checkpoint is not None and phase in (1, 2, 6, 7, 8)
                        and (checkpoint_due is None or checkpoint_due())):
                    checkpoint(run.snapshot())
            result = run.take_result()
        summary = _Summary()
        if query(ct.byref(result), ct.byref(_Application()), ct.byref(summary)):
            raise RuntimeError('native full 2D capture query failed')
        shape = (uniform.values.nx, uniform.values.ny)
        fields, declarations = detach_stage_fields(result.evidence, shape)
        # The Python result preserves its published field order.
        names = ('Ta', 'Tb', 'Ts', 'P_thermal_A', 'P_thermal_B', 'P_report_A', 'P_report_B',
                 'h_vA', 'h_vB', 'K_ss', 'Ta_display', 'Tb_display', 'Ts_display',
                 'P_fA_display', 'ucA', 'vcA', 'P_fB_display', 'ucB', 'vcB')
        stage_fields = {key: fields[key] for key in names}, {key: declarations[key] for key in names}
        from .solver_library._stage_capture_abi import stage_records
        records = stage_records(library, result)
        native = driver.copy_result(result.raw, shape, result.resolved,
            entry_version=6, control=control, have_cpu_limit=True, energy_query=energy_query,
            version_query=version_query, resume_state=resume_state, capture_scalars=_scalars(summary), fields=stage_fields[0],
            records=records, evidence=result.evidence)
        control.check_cancelled()

        def application_hv(area_density, surface_htc):
            if area_density < 0 or surface_htc < 0:
                raise ValueError(f'A_0={area_density}, H_sf={surface_htc} must both be >= 0')
            application = _Application((_D * 2)(float(area_density), 0.), (_D * 2)(float(surface_htc), 0.))
            values = _Summary()
            if query(ct.byref(result), ct.byref(application), ct.byref(values)):
                raise RuntimeError('native full 2D application capture query failed')
            return values.application_hv[0]

        zone_summary = None
        if cfg['zone_config'] is not None and cfg['za'] is not None:
            from sjtu_tpmshx.cpp_interface import _native_result_stage as result_stage
            if hasattr(result_stage.core._library().library, 'tpmshx_result_zone_temperatures_2d_v1'):
                zone_summary = result_stage.zone_result
        field = capture_result(case, cfg, prepared, native, application_hv=application_hv,
                               zone_summary=zone_summary, stage_fields=stage_fields)
        from sjtu_tpmshx.cpp_interface._native_result_stage import copy_applicability
        applicability = copy_applicability(result.evidence.applicability, case.metadata.get(
            'applicability_inputs', ()))
        metadata = dict(field.metadata, _native_applicability=applicability)
        if records is not None:
            from ._native_result_stage import execution_sides
            metadata['_native_execution_sides'] = execution_sides(records, result.evidence, case, declarations)
        return replace(field, metadata=metadata)
    finally:
        if result.owner:
            release(ct.byref(result))
        del keepalive


def _model_balance(thermal, result, outer_index, *, fine=False):
    if thermal['mode'] != 'model_h':
        return None
    balance = deepcopy(thermal['model_h'])
    balance.pop('energy_finishing_checks', None)
    balance.update(
        mass_source=('conservative coarse-face prolongation; no fine SIMPLE' if fine else
                     'last thermal input: actual signed SIMPLE faces'),
        outer_index=outer_index,
        outer_converged=bool(result['outer_converged']),
        post_after_last_thermal=bool(result['post_after_last_thermal']))
    if fine:
        balance['state'] = 'raw refined thermal return'
    else:
        balance['raw_state_matches_last_thermal'] = True
    return balance


def _fine_evidence(fine, balance):
    if fine is None:
        return {}
    evidence = dict(zip(('Ta', 'Tb', 'Ts'), fine['temperature']))
    evidence.update(dx=fine['dx'], dy=fine['dy'], eps=fine['epsilon'], model_h_balance=balance,
                    energy=fine.get('physical_ledger'))
    for side, label in enumerate('AB'):
        for prefix, key in (('uc', 'uc'), ('vc', 'vc'), ('rho_cp_', 'rho_cp'),
                            ('inlet_', 'inlet_profile'), ('outlet_', 'outlet_profile')):
            evidence[prefix + label] = fine[key][side]
    if 'native_metadata' in fine:
        evidence['native'] = fine['native_metadata']
    if 'temperature_evidence' in fine:
        evidence['temperature'] = fine['temperature_evidence']
        for index, label in enumerate('AB'):
            evidence['mass_' + label] = (fine['mass_x'][index], fine['mass_y'][index])
        evidence['mass_unit'] = 'kg/(s m)'
    return evidence


def capture_result(case, cfg, prepared, native, *, application_hv=None, zone_summary=None, stage_fields=None, legacy_fields=None):
    """Capture a completed native return without re-entering Python solvers."""
    if native['cancelled']:
        raise CancelledError('compute cancelled by user')
    main, fine = native['main'], native['fine']
    capture_scalars = native.get('capture_scalars')
    mode = main['mode']
    outer_index = native['outer_index'] if 'outer_index' in native else int(native['iterations']) - 1
    model_balance = _model_balance(main, native, outer_index)
    fine_balance = None if fine is None else _model_balance(fine, native, outer_index, fine=True)
    fine_info = None
    if fine is not None:
        fine_info = dict(converged=fine['stop'] == 0, iterations=fine['iterations'],
                         residual=fine['residual'], extrapolated=bool(native['fine_extrapolated']))
        if fine_balance is not None:
            fine_info.update(model_h_balance=fine_balance,
                             energy_finishing_checks=deepcopy(fine['model_h']['energy_finishing_checks']))
    true_h_info = main['true_h'] if mode in ('true_h', 'conservative_energy') else None
    true_balance = None
    if true_h_info is not None:
        true_balance = dict(
            Q_A=native['duty'][0], Q_B=native['duty'][1], units='W/m',
            outer_index=outer_index, converged=bool(native['thermal_ok']),
            iterations=main['iterations'], residual=main['residual'],
            pressure_source=('air: P_ref_abs + SIMPLE gauge; frozen fluids: '
                             'P_in + SIMPLE gauge - open-area physical inlet-face gauge'),
            P_in_A_Pa=cfg['compute_cfg'].fluid_A.P_in_Pa,
            P_in_B_Pa=cfg['compute_cfg'].fluid_B.P_in_Pa,
            outer_converged=bool(native['outer_converged']),
            post_after_last_thermal=bool(native['post_after_last_thermal']),
            state='last true-h solve, before any final post update')
        for side, label in enumerate('AB'):
            if capture_scalars is None:
                pressure = main['pressure'][side]
                limits = [float(pressure.min()), float(pressure.max())]
            else:
                limits = list(capture_scalars['pressure_ranges'][side])
            true_balance['P_' + label + '_range_Pa'] = limits
        true_balance.update({key: deepcopy(true_h_info[key]) for key in (
            'exit_reason', 'enthalpy_clip_counts', 'effective_settings',
            'coupled_energy_balance', 'equation_energy_balance', 'energy_algorithm',
            'energy_algorithm_version', 'temperature_update_K') if key in true_h_info})

    warnings = list(cfg['warnings_list'])
    if 'range_warnings' in native:
        merge_warnings(current_warnings(), [native['range_warnings']])
        warnings.extend(warning_messages(native['range_warnings']))
    else:
        from .solver_library.closure_evidence import replay_range_observations
        warnings.extend(replay_range_observations(native['range_observations']))
    notices = {}
    with warning_scope(notices):
        for label, observation in native['sco2_nu_observations'].items():
            if observation and cfg['fluid_' + label] == 'sco2':
                warn_sco2_nu_evidence(side=label, stage='2D main-hv', tpms_type=cfg['tpms_type'],
                    L_mm=cfg['Lcell'], t_mm=cfg['t_wall'], P_in=observation['P_abs_Pa'])
    merge_warnings(current_warnings(), [notices])
    warnings.extend(warning_messages(notices))
    if not native['outer_converged']:
        last = native['outer_history'][-1]
        rho, temperature = last['relative_density_change'], last['temperature_change']
        warnings.append(
            f"Velocity-temperature coupling: not converged after {native['iterations']} iters "
            f"(drho_A={rho[0]:.4f}, drho_B={rho[1]:.4f}, "
            f"dT_A={temperature[0]:.2f}K, dT_B={temperature[1]:.2f}K)")
    pressure_states, pressure_evidence = {}, {}
    evidence = dict(zip(('Ta', 'Tb', 'Ts'), main['temperature']))
    evidence.update(fine=_fine_evidence(fine, fine_balance),
        true_h=None if true_h_info is None else true_h_info['_native_state'],
        model_h_balance=model_balance, mode=mode, split_A=cfg['thermal_geometry']['split_A'],
        outer_index=outer_index,
        final_after_thermal=bool(native['post_after_last_thermal']), K_ss=main['solid_conductivity'])
    if 'temperature_evidence' in main:
        evidence['temperature'] = main['temperature_evidence']
    for side, label in enumerate('AB'):
        flow = native['flow'][side]
        openings = cfg['boundary_openings'][label]
        pressure_states[label] = flow['inlet_pressure']
        pressure_evidence[label] = dict(
            inlet_gauge_Pa=flow['pressure'][:, 0], outlet_gauge_Pa=flow['pressure'][:, -1],
            inlet_fraction=openings['in_profile_frac'], outlet_fraction=openings['out_profile_frac'],
            outlet_geom_frac=openings['out_geom_frac'], reference_abs_Pa=flow['reference_pressure'])
        if 'thermal_mass' in native:
            mass = native['thermal_mass'][side]
        elif mode == 'conservative_energy' or 'temperature_evidence' in main:
            mass = main['mass_x'][side], main['mass_y'][side]
        else:
            mass = flow['mass_x'], flow['mass_y']
        evidence.update({
            'P_thermal_' + label: main['pressure'][side],
            'P_report_' + label: flow['absolute_pressure'], 'h_v' + label: main['hv'][side],
            'rho_cp_' + label: None if mode in ('true_h', 'conservative_energy') else main['rho_cp'][side],
            'mass_flux_' + label: mass,
        })
        result = flow['result']
        if not result['converged']:
            warnings.append(
                f"SIMPLE (Fluid {label}): not converged after {result['iterations']} iters "
                f"(exit={result['exit_reason']}, mom={result['momentum']['maximum']}, "
                f"mass_local={result['mass']['local_residual']}, "
                f"mass_global={result['mass']['global_residual']})")
    evidence['pressure'] = pressure_evidence
    evidence['physical_ledger'] = main.get('physical_ledger')
    if fine is not None and not native['fine_extrapolated']:
        have_finite_duty = (np.any(np.isfinite(native['duty'])) if capture_scalars is None
                            else capture_scalars['have_finite_duty'])
        source = '主网格值' if have_finite_duty else ('不可用值' if mode == 'model_h' or 'temperature_evidence' in main else '1D 最后兜底值')
        warnings.append(
            f"Richardson 细解或外推未通过，换热量使用{source}，未外推 "
            f"(converged={fine_info['converged']}, iterations={fine_info['iterations']}, "
            f"residual={fine_info['residual']:.3e})")
    detail = dict(inlet_pressure=pressure_states, outer_converged=bool(native['outer_converged']),
        outer_iters=int(native['iterations']), outer_hit_cap=not native['outer_converged'],
        simple_ok=bool(native['simple_ok']), ltne_ok=bool(native['thermal_ok']),
        richardson_ok=None if fine is None else bool(fine_info['converged'] and native['fine_extrapolated']),
        ltne_iterations=int(main['iterations']), ltne_residual=float(main['residual']),
        enthalpy_balance_ok=bool(native['pair_balance_ok']),
        model_h_balance_ok=bool(native['model_balance_ok']) if mode == 'model_h' else None,
        envelope_ok=bool(native['envelope_ok']))
    diagnostics = dict(
        sco2_nu_observations=native['sco2_nu_observations'],
        T_out_A_K=native['outlet_temperature'][0], T_out_B_K=native['outlet_temperature'][1],
        dP_A=native['pressure_drop'][0], dP_B=native['pressure_drop'][1], Q_total=native['q_total'],
        mass_flow_A_kg_s_per_m=native['inlet_mass'][0], mass_flow_B_kg_s_per_m=native['inlet_mass'][1],
        warnings_list=warnings, solver_converged=bool(native['converged']), convergence_detail=detail,
        Q_A=native['duty'][0], Q_B=native['duty'][1], Q_net=sum(native['duty']) if capture_scalars is None else capture_scalars['q_net'],
        energy_imbalance_rel=native['energy_imbalance'],
        Q_enthalpy_A=abs(native['duty'][0]) if capture_scalars is None else capture_scalars['absolute_duty'][0],
        Q_enthalpy_B=abs(native['duty'][1]) if capture_scalars is None else capture_scalars['absolute_duty'][1],
        Q_solid_richardson=native['q_solid'], Q_richardson_warn=bool(native['fine_warning']),
        richardson_info=fine_info, model_h_balance=None if model_balance is None else dict(main=model_balance, fine=fine_balance),
        true_h_balance=true_balance, envelope_valid=bool(native['envelope_ok']),
        envelope_reasons=[f'[{label}] {reason}' for label, flow in zip('AB', native['flow']) for reason in flow['envelope_reasons']],
        p_clip_hits=(sum(flow['result']['pressure_clip_hits'] for flow in native['flow'])
                     if capture_scalars is None else capture_scalars['pressure_clip_hits']),
        df_metadata=dict(mode=cfg['compute_cfg'].df_mode,
                         **{label: cfg['flow_inputs'][label]['metadata'] for label in 'AB'}),
        native_full_2d=dict(numerical_driver='cpp',
                            range_observations=native['range_observations']))
    if native['main']['true_h'] is not None:
        diagnostics['native_full_2d'].update(entry_version=native['entry_version'],
            energy_history=[dict(iteration=row['iteration'], **row['energy_info']) for row in native['outer_history']])
    for side, label in enumerate('AB'):
        state, flow = pressure_states[label], native['flow'][side]
        diagnostics['P_in_realized_' + label] = np.nan if state is None else state['realized_Pa']
        diagnostics['P_in_shoot_resid_' + label] = np.nan if state is None else state['relative_error']
        diagnostics['residuals_' + label] = list(flow['history']['legacy'])
        diagnostics['mass_imbalance_rel_' + label] = flow['result']['mass']['global_residual']
    properties = cfg['static_properties']
    r_a, r_b = properties['A'], properties['B']
    volumetric_htc = compute_volumetric_htc if application_hv is None else application_hv
    application = dict(
        coeffs=dict(K_ffA=r_a['K_ff'], K_ffB=r_b['K_ff'], K_ss=properties['geometry']['K_ss'],
                    h_vA=volumetric_htc(r_a['A_0'], r_a['H_sf']),
                    h_vB=volumetric_htc(r_b['A_0'], r_b['H_sf'])),
        props=dict(rho_A=r_a['rho'], rho_B=r_b['rho'], mu_A=r_a['mu'], mu_B=r_b['mu']),
        zones=None)
    if zone_summary is not None:
        application['zones'] = zone_summary(cfg, prepared, main['temperature'])
    elif cfg['zone_config'] is not None and cfg['za'] is not None:
        from sjtu_tpmshx.postprocess.result_display import zone_statistics_2d
        application['zones'] = zone_statistics_2d(cfg['z_axis'], cfg['zone_config'], cfg['za'], cfg['L'], cfg['H'],
            prepared['energy_dx'], prepared['energy_dy'], *main['temperature'])
    evidence.update(input_resolution=cfg['_input_resolution'], property_sampling=native['property_sampling'])
    if stage_fields is None:
        stage_fields = legacy_fields(evidence, main, native)
    result = _capture_result(case, stage_fields, evidence, application, diagnostics, backend_id='cpp',
                             backend_version=f"full_2d_v{native.get('entry_version', 2)}")
    if 'continuation' in native:
        result = replace(result, metadata=dict(result.metadata, continuation=native['continuation']))
    if 'native_metadata' in native:
        result = replace(result, metadata=dict(result.metadata, native=native['native_metadata']))
    if 'runtime_resources' in native:
        result = replace(result, metadata=dict(result.metadata, runtime_resources=native['runtime_resources']))
    return replace(result, metadata=dict(result.metadata, _last_closure_ranges=native['last_closure_ranges'],
        enthalpy_update_normalization=native['enthalpy_update_normalization'],
        simple_velocity_relaxation=native['simple_velocity_relaxation'], simple_flow=native['simple_flow'],
        model_h_iterations=native['model_h_iterations']))


def _capture_result(case, stage_fields, native, application, diagnostics, *,
                   backend_id='cpp', backend_version='full_2d_v1'):
    fields, field_metadata = stage_fields
    ledger = native.get('physical_ledger')
    if ledger is not None and ledger['physical_boundary_complete'] is None:
        from sjtu_tpmshx.solvers.physical_ledger import ports_complete
        parameters = case.parameters
        ledger = dict(ledger, physical_boundary_complete=all(ports_complete(
            native['mass_flux_' + side], parameters['dir_' + side],
            parameters['boundary_openings'][side]['in_geom_frac'],
            parameters['boundary_openings'][side]['out_geom_frac']) for side in ('A', 'B')))
    model_metadata = dict(case.metadata['model_metadata'])
    for key in ('enthalpy_eos', 'sco2_enthalpy_eos'):
        if native['true_h'] and key in native['true_h']:
            model_metadata[key] = native['true_h'][key]
    return FieldResult(
        result_id=str(uuid4()), case_id=case.case_id,
        backend_id=backend_id, backend_version=backend_version, grid=case.grid,
        fields=fields, field_metadata=field_metadata, model_refs=case.model_refs,
        boundary_fluxes=dict(
            energy=ledger,
            mass_A=native['mass_flux_A'], mass_B=native['mass_flux_B'],
            mass_unit='kg/(s m)', mass_axes=('x-face', 'y-face'),
            mass_sign='positive along physical coordinate axis',
            state='last main thermal input', model_h=native['model_h_balance'],
            true_h=native['true_h'], fine=native['fine'],
            **({'temperature': native['temperature']} if 'temperature' in native else {})),
        pressure_evidence=native['pressure'],
        run_status=dict(execution='completed', converged=bool(diagnostics['solver_converged']),
                        envelope_valid=bool(diagnostics['envelope_valid']),
                        final_flow_after_last_thermal=native['final_after_thermal'],
                        outer_index=native['outer_index']),
        metadata=dict(dimension=2, quantity_basis='per_unit_depth',
                      thermal_mode=native['mode'], split_A=native['split_A'],
                      **({'temperature_transport': native['temperature']['definition']}
                         if 'temperature' in native else {}),
                      rho_cp_A=native['rho_cp_A'], rho_cp_B=native['rho_cp_B'],
                      parameters=case.parameters, design_fields=case.design_fields,
                      design_mode=case.metadata['design_mode'], application=application,
                      model_metadata=model_metadata, notices=case.metadata['notices'],
                      diagnostics=diagnostics, df_metadata=diagnostics['df_metadata'],
                      model_roles=case.metadata['model_roles'],
                      **{key: native[key] for key in ('input_resolution', 'property_sampling') if key in native},
                      reporting_reference={key: diagnostics[key] for key in (
                          'Q_total', 'dP_A', 'dP_B', 'T_out_A_K', 'T_out_B_K')}))
