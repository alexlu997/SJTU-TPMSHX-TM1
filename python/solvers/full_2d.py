"""Run a saved full 2D case and assemble its portable FieldResult."""
from collections.abc import Mapping
from copy import deepcopy
from uuid import uuid4

import numpy as np

from tm1.cpp_interface import full_2d_stage
from tm1.data_types.case_data import resolved_input_record
from tm1.data_types.compute_config import (
    ComputeConfig,
    _checked_saved_2d_settings,
    validate_simple_velocity_relaxation,
)
from tm1.data_types.field_result import FieldResult, execution_record
from tm1.data_types.persistence_validation import validate_grid, validate_thermal_geometry
from tm1.data_types.portable_data import mutable_data
from tm1.physical_models.envelope import ChokedFlowError
from tm1.physical_models.fluid_props import WaterStateError
from tm1.physical_models.zone_config import Zone, ZoneConfig
from tm1.physical_models.zone_units import _legacy_zone_units
from tm1.run_control.cancellation import CancelledError
from tm1.run_control.module_ports import RunControl
from tm1.run_control.run_environment import require_f2_mode, run_environment
from tm1.run_control.run_warnings import (
    current_warnings,
    merge_warnings,
    replay_sco2_notices,
    warning_messages,
    warning_scope,
)
from .physical_ledger import ports_complete
from .stage_execution import link_execution

_TOPOLOGIES = ('Diamond', 'Gyroid')
_ERROR_TYPES = {
    1: ValueError,
    2: WaterStateError,
    3: FloatingPointError,
    4: ChokedFlowError,
    6: CancelledError,
}


def _run_settings(cfg):
    settings = cfg['compute_cfg']
    return settings if isinstance(settings, dict) else vars(settings)


def execution_grid(case, checked_shape=None):
    if case.grid.get('dimension') != 2:
        raise ValueError('2D execution requires a prepared 2D grid')
    missing = {'thermal_geometry', 'flow_inputs'} - case.parameters.keys()
    if missing:
        raise ValueError(f'incomplete prepared 2D execution data: {sorted(missing)}')
    return checked_shape if checked_shape is not None else validate_grid(case.grid)


def _can_pack_settings(settings):
    if not isinstance(settings, dict) or 'domain' in settings:
        return False
    mode = settings.get('df_mode', 'cfd_smooth')
    if type(mode) is not str or mode != 'experimental':
        return type(mode) is str
    geometry = settings.get('geometry')
    fa = settings.get('fluid_A')
    fb = settings.get('fluid_B')
    if not all([type(part) is dict for part in (geometry, fa, fb)]):
        return False
    if type(geometry.get('tpms')) is not str or geometry['tpms'] not in _TOPOLOGIES:
        return False
    if not all([type(geometry.get(name)) in (int, float) for name in
                ('L_dom_m', 'H_dom_m', 'L_cell_mm', 't_wall_mm', 'delta_levelset')]):
        return False
    if geometry.get('Lz_m') is not None and type(geometry['Lz_m']) not in (int, float):
        return False
    return all([
        type(fluid.get('type')) is str and fluid['type'] in ('air', 'water', 'sco2', 'co2')
        and (fluid.get('mass_flow_kg_s') is not None or type(fluid.get('u_mps')) in (int, float))
        for fluid in (fa, fb)
    ])


def _zone_objects(zone):
    return ZoneConfig(**{**zone, 'zones': [Zone(**item) for item in zone['zones']]})


def _plain_zone(zone):
    if set(zone) != {'zones', 'tpms_type', 'k_s'} or not isinstance(zone['zones'], list):
        return False
    required = {'name', 'y_frac_start', 'y_frac_end', 'L_mm', 't_mm'}
    optional = {'props_A', 'props_B'}
    return all([
        isinstance(row, dict) and required <= row.keys() <= required | optional
        for row in zone['zones']
    ])


def saved_inputs(case, shape, *, check_experiment, port_windows_fit, checked_geometry=False):
    cfg = dict(case.parameters)
    if not checked_geometry:
        validate_thermal_geometry(cfg['thermal_geometry'], shape)
    if set(cfg['flow_inputs']) != {'A', 'B'}:
        raise ValueError('prepared flow inputs require both physical sides')
    settings = _legacy_zone_units(mutable_data(cfg['run_settings']))
    if cfg['z_axis'] == 'continuous':
        settings['zones'] = dict(enabled=True, axis='continuous', config=mutable_data(cfg['continuous_field']))
    packed = _can_pack_settings(settings)
    # The native run reads the experiment record only for experimental D-F.
    experiment_spec = None
    if packed:
        values = cfg['compute_cfg'] = _checked_saved_2d_settings(settings, port_windows_fit=port_windows_fit)
        if values['df_mode'] == 'experimental':
            experiment_spec = values
            check_experiment(experiment_spec)
    else:
        cfg['compute_cfg'] = ComputeConfig.from_dict(settings, prepared_grid=True)
        if cfg['compute_cfg'].df_mode == 'experimental':
            raise ValueError('saved experimental 2D settings lack the fields that the experiment check requires; '
                             'prepare the original configuration again')
    cfg['Lcell'], cfg['t_wall'] = cfg['L_cell_m'] * 1e3, cfg['t_wall_m'] * 1e3
    design = case.design_fields
    if case.metadata['design_mode'] == 'uniform':
        cfg['za'] = None
        properties = cfg['static_properties']
        solid = np.asarray(design['K_ss_arr'])
        if solid.shape != shape:
            raise ValueError('prepared design field K_ss_arr does not match the physical grid')
        cfg['static_properties'] = {**properties, 'geometry': {**properties['geometry'], 'K_ss': float(solid[0, 0])}}
    else:
        for name in ('L_field', 't_field'):
            if np.shape(design.get(name + '_m')) != shape:
                raise ValueError(f'prepared zoned 2D case requires a positive {name}; '
                                 'prepare the original configuration again')
        if cfg['thermal_geometry']['fields'] is None:
            raise ValueError('prepared zoned 2D case requires per-cell thermal geometry; '
                             'prepare the original configuration again')
        cfg['za'] = dict(design)
        if 'grid_cells' in design:
            cfg['za'].update(_legacy_zone_units({'grid_cells': mutable_data(design['grid_cells'])}))
    zone = _legacy_zone_units(mutable_data(cfg['zone_config']))
    if isinstance(zone, dict) and (not packed or not _plain_zone(zone)):
        zone = _zone_objects(zone)
    cfg['zone_config'] = zone
    return cfg, dict(energy_dx=case.grid['dx'], energy_dy=case.grid['dy']), experiment_spec


def convergence_controls(cfg, solver_config):
    """Read the convergence mode and caller-supplied tolerances."""
    def knob(name, default):
        value = getattr(solver_config, name, None)
        if value is None:
            value = cfg.get(name)
        return default if value is None else value

    mode = require_f2_mode(run_environment(
        cfg, 'TPMSHX_CONV_MODE', knob('convergence_mode', 'f2')))
    tolerances = {}
    for name in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        value = knob(name, None)
        if value is not None:
            tolerances[name] = float(value)
    return mode, tolerances


def request_controls(cfg, solver_config):
    """Resolve convergence, relaxation, shooting, and envelope controls for the 2D request."""
    mode, tolerances = convergence_controls(cfg, solver_config)
    validate_simple_velocity_relaxation(solver_config.simple_velocity_relaxation)
    pressure_shooting = cfg.get('p_in_shooting', run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') == '1')
    envelope_mode = cfg.get('envelope_mode', 'raise')
    return mode, tolerances, pressure_shooting, envelope_mode


def zone_result(cfg, prepared, temperature, *, solver_library=None):
    """Summarize main-grid temperatures by saved zone without loading unrelated images."""
    axis, design = cfg['z_axis'], cfg['za']
    if cfg['zone_config'] is None or design is None:
        return None
    if axis == 'continuous':
        return dict(axis_dir=axis, boundaries=[], boundaries_x=[], boundaries_y=[], stats=[])
    if axis == 'grid':
        zones = [(f'g{i}', cell['L'], cell['t']) for i, cell in enumerate(design.get('grid_cells', ()))]
        fractions = design.get('x_bounds', ()), design.get('y_bounds', ())
    else:
        config = cfg['zone_config']
        if isinstance(config, Mapping):
            definitions = config['zones']
            zones = [(row['name'], row['L_mm'], row['t_mm']) for row in definitions]
            ends = [row['y_frac_end'] for row in definitions[:-1]]
        else:
            definitions = config.zones
            zones = [(zone.name, zone.L_mm, zone.t_mm) for zone in definitions]
            ends = [zone.y_frac_end for zone in definitions[:-1]]
        fractions = ((), ends) if axis == 'y' else (ends, ())
    stats, x, y = full_2d_stage.zone_temperatures(
        (prepared['energy_dx'], prepared['energy_dy']), temperature,
        design['zone_id'], zones, (cfg['L'], cfg['H']), fractions,
        solver_library=solver_library)
    from tm1.run_control.logutil import log_zone_report
    log_zone_report(stats)
    if axis == 'grid':
        return dict(axis_dir=axis, boundaries=[], boundaries_x=x, boundaries_y=y, stats=stats)
    return dict(axis_dir=axis, boundaries=y if axis == 'y' else x, boundaries_x=None, boundaries_y=None, stats=stats)


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


def capture_result(case, cfg, prepared, native, *, application_hv, zone_summary, stage_fields):
    """Capture a completed native return without re-entering Python solvers."""
    if native['cancelled']:
        raise CancelledError('compute cancelled by user')
    settings = _run_settings(cfg)
    main, fine = native['main'], native['fine']
    capture_scalars = native['capture_scalars']
    mode = main['mode']
    outer_index = native['outer_index']
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
            P_in_A_Pa=settings['fluid_A'].P_in_Pa,
            P_in_B_Pa=settings['fluid_B'].P_in_Pa,
            outer_converged=bool(native['outer_converged']),
            post_after_last_thermal=bool(native['post_after_last_thermal']),
            state='last true-h solve, before any final post update')
        for side, label in enumerate('AB'):
            true_balance['P_' + label + '_range_Pa'] = list(capture_scalars['pressure_ranges'][side])
        true_balance.update({key: deepcopy(true_h_info[key]) for key in (
            'exit_reason', 'enthalpy_clip_counts', 'effective_settings',
            'coupled_energy_balance', 'equation_energy_balance', 'energy_algorithm',
            'energy_algorithm_version', 'temperature_update_K') if key in true_h_info})

    warnings = list(cfg['warnings_list'])
    merge_warnings(current_warnings(), [native['range_warnings']])
    warnings.extend(warning_messages(native['range_warnings']))
    notices = {}
    with warning_scope(notices):
        replay_sco2_notices(native['sco2_notices'], '2D main-hv')
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
        mass = native['thermal_mass'][side]
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
        source = '主网格值' if capture_scalars['have_finite_duty'] else ('不可用值' if mode == 'model_h' or 'temperature_evidence' in main else '1D 最后兜底值')
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
        Q_A=native['duty'][0], Q_B=native['duty'][1], Q_net=capture_scalars['q_net'],
        energy_imbalance_rel=native['energy_imbalance'],
        Q_enthalpy_A=capture_scalars['absolute_duty'][0], Q_enthalpy_B=capture_scalars['absolute_duty'][1],
        Q_solid_richardson=native['q_solid'], Q_richardson_warn=bool(native['fine_warning']),
        richardson_info=fine_info, model_h_balance=None if model_balance is None else dict(main=model_balance, fine=fine_balance),
        true_h_balance=true_balance, envelope_valid=bool(native['envelope_ok']),
        envelope_reasons=[f'[{label}] {reason}' for label, flow in zip('AB', native['flow']) for reason in flow['envelope_reasons']],
        p_clip_hits=capture_scalars['pressure_clip_hits'],
        df_metadata=dict(mode=settings['df_mode'],
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
    hv_a, hv_b = application_hv
    application = dict(
        coeffs=dict(K_ffA=r_a['K_ff'], K_ffB=r_b['K_ff'], K_ss=properties['geometry']['K_ss'],
                    h_vA=hv_a, h_vB=hv_b),
        props=dict(rho_A=r_a['rho'], rho_B=r_b['rho'], mu_A=r_a['mu'], mu_B=r_b['mu']),
        zones=zone_summary)
    evidence.update(input_resolution=cfg['_input_resolution'], property_sampling=native['property_sampling'])
    audit = {key: native[key] for key in ('continuation', 'runtime_resources', '_native_applicability')
             if key in native}
    if 'native_metadata' in native:
        audit['native'] = native['native_metadata']
    audit.update(_last_closure_ranges=native['last_closure_ranges'],
                 enthalpy_update_normalization=native['enthalpy_update_normalization'],
                 simple_velocity_relaxation=native['simple_velocity_relaxation'], simple_flow=native['simple_flow'],
                 model_h_iterations=native['model_h_iterations'])
    return _capture_result(case, stage_fields, evidence, application, diagnostics,
                           audit=audit, facts=native['execution_facts'],
                           backend_version=f"full_2d_v{native['entry_version']}")


def _capture_result(case, stage_fields, native, application, diagnostics, *, audit, facts, backend_version):
    fields, field_metadata = stage_fields
    ledger = native.get('physical_ledger')
    if ledger is not None and ledger['physical_boundary_complete'] is None:
        parameters = case.parameters
        ledger = dict(ledger, physical_boundary_complete=all([ports_complete(
            native['mass_flux_' + side], parameters['dir_' + side],
            parameters['boundary_openings'][side]['in_geom_frac'],
            parameters['boundary_openings'][side]['out_geom_frac']) for side in ('A', 'B')]))
    model_metadata = dict(case.metadata['model_metadata'])
    for key in ('enthalpy_eos', 'sco2_enthalpy_eos'):
        if native['true_h'] and key in native['true_h']:
            model_metadata[key] = native['true_h'][key]
    metadata = dict(**audit, dimension=2, quantity_basis='per_unit_depth',
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
            'Q_total', 'dP_A', 'dP_B', 'T_out_A_K', 'T_out_B_K')})
    metadata['execution_record'] = execution_record('cpp', backend_version, metadata,
        roles=case.metadata['model_roles'], **facts)
    return FieldResult(
        result_id=str(uuid4()), case_id=case.case_id,
        backend_id='cpp', backend_version=backend_version, grid=case.grid,
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
        metadata=metadata)


def run_case(case, control=RunControl(), *, resume_state=None, checkpoint=None, checkpoint_due=None):
    """Validate a saved 2D case, execute the native stage, and build FieldResult."""
    if control.backend != 'cpp' or control.native_library is None:
        raise ValueError('full native 2D requires backend=cpp and an explicit native_library')
    control.check_cancelled()
    try:
        driver = full_2d_stage.StageDriver(control.native_library, table_directory=control.native_table_directory)
    except Exception:
        execution_grid(case)
        raise
    checked = full_2d_stage.borrow_mesh(case, driver.library)
    shape = execution_grid(case, None if checked is None else checked.shape)
    entries = full_2d_stage.stage_entries(driver.library)
    cfg, prepared, experiment_spec = saved_inputs(
        case, shape, checked_geometry=checked is not None,
        check_experiment=lambda spec: full_2d_stage.check_experiment(entries, spec, _ERROR_TYPES),
        port_windows_fit=entries['port_windows_fit'])
    prepared['solver_mesh'] = checked
    native, stage_fields, report, application_hv = full_2d_stage.run_stage(
        driver, case, cfg, prepared, control, entries, experiment_spec,
        resolve_controls=request_controls, error_types=_ERROR_TYPES,
        resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)
    cfg['_input_resolution'] = resolved_input_record(case, **report['input'])
    native['execution_facts'] = link_execution(report, case, native['main']['true_h'])
    zone_summary = None
    if cfg['zone_config'] is not None and cfg['za'] is not None:
        zone_summary = zone_result(
            cfg, prepared, native['main']['temperature'],
            solver_library=None if cfg['z_axis'] == 'continuous' else driver.library)
    result = capture_result(case, cfg, prepared, native, application_hv=application_hv,
                            zone_summary=zone_summary, stage_fields=stage_fields)
    control.report_progress(100)
    return result
