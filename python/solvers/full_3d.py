"""Run a saved full 3D case and assemble its portable FieldResult."""
from uuid import uuid4

import numpy as np

from tm1.cpp_interface import full_3d_stage
from tm1.data_types.case_data import resolved_input_record
from tm1.data_types.compute_config import (
    Sco2NuConfig, reject_retired_research_options, validate_simple_velocity_relaxation,
)
from tm1.data_types.field_result import FieldResult, execution_record
from tm1.data_types.model_refs import freeze_value
from tm1.data_types.persistence_validation import (
    grid_axes, validate_axis_permutation, validate_grid, validate_thermal_geometry,
)
from tm1.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE
from tm1.physical_models.fluid_props import WaterStateError
from tm1.physical_models.nu_correlations import sco2_nu_parameters
from tm1.run_control.run_environment import require_f2_mode, run_environment
from tm1.run_control.run_warnings import current_warnings, merge_warnings, replay_sco2_notices
from .stage_execution import link_execution

_DOMAIN_ERRORS = {1: ValueError, 2: WaterStateError, 3: FloatingPointError}
_CHECKPOINT_PHASES = (1, 2, 6, 7, 8, 9, 10)


def run_case(case, control, *, resume_state=None, checkpoint=None, checkpoint_due=None):
    """Validate a saved 3D case, execute the native stage, and build FieldResult."""
    if control.backend != 'cpp':
        raise ValueError('full native 3D requires backend=cpp')
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    control.check_cancelled()
    try:
        runtime = full_3d_stage.open_library(
            control.native_library, getattr(control, 'native_table_directory', None))
    except Exception:
        validate_saved_axes(case)
        raise
    _, library, abi, table_directory = runtime
    checked = full_3d_stage.borrow_mesh(case, library)
    if checked is None:
        validate_saved_axes(case)
    full_3d_stage.require_saved_stage(library)
    query = full_3d_stage.execution_view_query(library)
    output = full_3d_stage.run_saved(
        case, library, abi, table_directory, query,
        mesh=checked, native_cpu_threads=control.native_cpu_threads,
        resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due,
        checkpoint_phases=_CHECKPOINT_PHASES,
        error_types=_DOMAIN_ERRORS,
        validate_case=validate_saved_case,
        check_cancelled=control.check_cancelled,
        validate_energy=validate_energy_controls,
        validate_flow=validate_flow_options,
        select_nu=select_sco2_nu,
        validate_velocity_relaxation=validate_simple_velocity_relaxation,
        cancel_check=control.cancel_check,
        report_progress=control.report_progress,
        iteration=control.iteration,
        outer_iteration=control.outer_iteration,
    )
    cfg = case.parameters
    prepared = cfg['prepared']
    detached = output['detached']
    report = output['report']
    detached.update({name: report[name] for name in
                     ('property_sampling', 'enthalpy_update_normalization', 'model_h_iterations')})
    add_run_evidence(detached, output['resolved'], output['entry_version'], control, output['cpu_threads'], resume_state)
    if 'temperature_evidence' in output:
        detached['temperature_evidence'] = output['temperature_evidence']
    if 'native_metadata' in output:
        detached['native_metadata'] = output['native_metadata']
    detached['_input_resolution'] = resolved_input_record(case, **report['input'])
    detached['last_closure_ranges'] = output['last_closure_ranges']
    detached['stage_diagnostics'] = diagnostics(output['raw_diagnostics'], cfg, case.design_fields)
    detached['execution_facts'] = link_execution(report, case, detached['true_h'])
    detached['_native_applicability'] = output['native_applicability']
    if 'physical_ledger' in output:
        detached['physical_ledger'] = output['physical_ledger']
    detached.update(capture_scalars=output['summary'], bootstrap_trace=output['bootstrap'])
    merge_warnings(current_warnings(), [output['closure_warnings']])
    replay_sco2_notices(output['sco2_notices'], '3D h_v property refresh')
    control.check_cancelled()
    return capture_result(case, cfg, prepared, detached, abi)


def validate_saved_axes(case):
    grid_axes(case.grid)
    for side, axes in case.parameters['prepared']['axes'].items():
        if axes is not None:
            validate_axis_permutation(axes, side)


def validate_saved_case(case, checked_shape=None):
    if case.grid.get('dimension') != 3:
        raise ValueError('3D execution requires a prepared 3D grid')
    cfg = case.parameters
    reject_retired_research_options(cfg)
    missing = {'thermal_geometry', 'roughness_resolved', 'df_application'} - cfg.keys()
    if missing:
        raise ValueError(f'incomplete prepared 3D execution data: {sorted(missing)}')
    shape = checked_shape
    if shape is None:
        shape = validate_grid(case.grid)
        validate_thermal_geometry(cfg['thermal_geometry'], shape)
    prepared = cfg['prepared']
    active = case.metadata.get('active_fluids')
    if active is not None and (tuple(prepared['axes']) != tuple(active)
            or set(prepared['openings']) != set(active)
            or tuple(side for side in 'AB' if cfg['fluid_' + side + '_cfg'] is not None) != tuple(active)):
        raise ValueError('prepared active fluids disagree with the ports and axis maps')
    for axis, count in zip('xyz', shape):
        if prepared['N' + axis] != count:
            raise ValueError(f'prepared {axis} count and grid disagree')
    cell_mm, wall_mm = cfg['L_cell_m'] / 1e-3, cfg['t_wall_m'] / 1e-3
    for side in 'AB':
        axis = prepared['axes'].get(side)
        if axis is not None:
            for mask in prepared['openings'][side].values():
                if np.shape(mask) != (axis['N_cross1'], axis['N_cross2']):
                    raise ValueError(f'invalid prepared fluid {side} opening mask')
    nu = Sco2NuConfig(**cfg['sco2_nu'])
    known = {'eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m', 'K_ss', 'L_field_m', 't_field_m'}
    for name, field in case.design_fields.items():
        arr = np.asarray(field)
        if arr.ndim and arr.shape != shape:
            raise ValueError(f'prepared design field {name} does not match the grid')
        if name not in known:
            if not np.all(np.isfinite(arr) & (arr > 0)):
                raise ValueError(f'prepared design field {name} must be finite and positive')
            if name.startswith('eps') and not np.all(arr < 1):
                raise ValueError(f'prepared porosity {name} must be below one')
    return shape, cell_mm, wall_mm, nu


def select_sco2_nu(cfg, nu):
    """Select the native topology code and sCO2 Nu multiplier for the saved case."""
    return sco2_nu_parameters(cfg['tpms_type'], nu if nu.mode == 'experimental' else None)


def validate_energy_controls(cfg):
    require_h = cfg.get('require_enthalpy_update_on_temperature', False)
    if type(require_h) is not bool:
        raise ValueError('require_enthalpy_update_on_temperature must be boolean')
    strict = require_h or any(cfg.get(name) is not None for name in (
        'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol'))
    return require_h, strict


def validate_flow_options(cfg):
    require_f2_mode(cfg.get('convergence_mode') or run_environment(cfg, 'TPMSHX_CONV_MODE', 'f2'))
    if cfg.get('use_anderson', False):
        raise ValueError('use_anderson=True in SIMPLE has been retired; disable TPMSHX_PHASE_B/use_anderson')


def diagnostics(raw, config, design):
    def drag(value):
        return value['minimum'] if value['scalar'] else dict(min=value['minimum'], max=value['maximum'])
    mode = config.get('df_mode', 'cfd_smooth')
    base_k, base_cf = [
        value['minimum'] if np.size(design[name]) == 1 else drag(value)
        for name, value in zip(('K_m2', 'cF_per_m'), raw['base_drag'])
    ]
    summary = dict(mode=mode)
    ratios = {}
    for index, side in enumerate('AB'):
        for offset, suffix in enumerate(('', '_cellmax')):
            ratios['eps_' + side + '_strict' + suffix] = raw['strict_ratios'][2 * index + offset]
        summary[side] = None
        if not raw['executed_sides'][index]:
            continue
        applied_k, applied_cf = [drag(value) for value in raw['applied_drag'][index]]
        if mode == 'experimental':
            row = dict((config.get('df_application') or {}).get(side, {}))
        else:
            row = dict(scale_K=1., scale_F=1., campaign=CFD_CAMPAIGN, scope=CFD_SCOPE)
        summary[side] = dict(row, base_K=base_k, base_cF=base_cf, applied_K=applied_k, applied_cF=applied_cf)
    return dict(df_metadata=summary, strict_ratios=ratios, history_converged=raw['history_converged'],
                transient=raw['transient'], final=raw['final'])


def add_run_evidence(detached, resolved, entry_version, control, cpu_thread_limit, resume_state):
    if resume_state is not None:
        detached['continuation'] = dict(format='full_3d_continuation_v1', build=resume_state['build'],
            completed_outer_steps=int(resume_state['state.result.outer.size'][0]),
            saved_phase=int(resume_state['state.phase'][0]))
    detached['simple_velocity_relaxation'] = resolved['simple_velocity_relaxation']
    detached['max_outer'] = resolved['max_outer']
    detached['thermal_iterations'] = resolved['thermal_iterations']
    budgets = {row['outer_index']: row['settings']['total_iteration_budget']
               for row in detached['model_h_iterations']['records']}
    for row in detached['outer']:
        if 'coupling_startup' in row:
            row['coupling_startup']['iteration_budget'] = budgets[row['outer']]
    detached['entry_version'] = entry_version
    if cpu_thread_limit is not None:
        detached['runtime_resources'] = dict(cpu_thread_limit=cpu_thread_limit,
            requested_cpu_threads=control.cpu_threads, policy='native_cpu_limit_v1')


def capture_result(case, cfg, p, r, abi):
    """Publish a detached saved-stage return as the portable FieldResult."""
    scalars = r['capture_scalars']
    fields, field_metadata = r['stage_fields']
    pressure, report = {}, {}
    for s, label in enumerate('AB'):
        f = r['flow'][s]
        if f is None:
            continue
        axis = case.parameters['prepared']['axes'][label]
        pressure[label] = dict(P=f['pressure'], dx=f['widths'][0], dy=f['widths'][1], dz=f['widths'][2],
            inlet_frac=f['inlet_opening'], outlet_frac=f['outlet_opening'], P_ref_abs=f['pressure_reference'], axis_map=axis,
            unit='Pa', axes=('solver_x', 'solver_y', 'solver_z'), stream_axis=1, state='final SIMPLE flow', method='face_extrapolation_v1')
        report[label] = dict(direction=cfg['fluid_' + label + '_cfg']['dir'])
    captured = r['stage_diagnostics']
    df_metadata, strict = captured['df_metadata'], captured['strict_ratios']
    model_h_calls = r['model_h_iterations']['records']
    thermal_budget = (model_h_calls[-1]['settings']['total_iteration_budget'] if model_h_calls else r['thermal_iterations'])
    ltne = []
    for h in r['outer']:
        row = {key: h[key] for key in ('outer', 'iters', 'converged', 'residual')}
        for key in ('coupling_startup', 'energy_finishing_checks', 'model_h_balance'):
            if key in h:
                row[key] = h[key]
        if 'true_h_info' in h:
            info = h['true_h_info']
            row['true_h_balance'] = dict(Q_A=info['Q_A'], Q_B=info['Q_B'], units='W', outer_index=h['outer'],
                converged=h['converged'], iterations=h['iters'], residual=h['residual'],
                pressure_source='completed SIMPLE P_ref_abs + gauge', P_in_A_Pa=cfg['P_inA'], P_in_B_Pa=cfg['P_inB'],
                P_A_offset_Pa=h['pressure_reference'][0], P_B_offset_Pa=h['pressure_reference'][1],
                P_A_range_Pa=h['pressure_range'][0], P_B_range_Pa=h['pressure_range'][1])
            row['true_h_balance'].update({key: info[key] for key in ('exit_reason', 'enthalpy_clip_counts', 'effective_settings',
                'coupled_energy_balance', 'equation_energy_balance', 'energy_algorithm',
                'energy_algorithm_version', 'temperature_update_K') if key in info})
        ltne.append(row)
    final_info = ltne[-1]
    diagnostics_map = dict(dP=r['pressure_drop'][0], dP_A=r['pressure_drop'][0], dP_B=r['pressure_drop'][1],
        Lx=cfg['L'], Ly=cfg['H'], Lz=cfg['Lz'], Q=r['duty'][0], Q_total=r['duty'][0],
        Q_enthalpy_A=r['duty'][0], Q_enthalpy_B=r['duty'][1], Q_solid_B=r['solid_exchange'][1],
        mass_flow_A_kg_s=r['inlet_mass'][0], mass_flow_B_kg_s=r['inlet_mass'][1] if r['flow'][1] else None,
        u_A=cfg['u_A'], T_in=cfg['T_inA'], T_A_out=r['outlet_temperature'][0], T_B_out=r['outlet_temperature'][1] if r['flow'][1] else None,
        T_out_A=r['outlet_temperature'][0], T_out_B=r['outlet_temperature'][1] if r['flow'][1] else None,
        dir_A=cfg['fluid_A_cfg']['dir'], dir_B=cfg['fluid_B_cfg']['dir'] if r['flow'][1] else None,
        Q_sA=r['solid_exchange'][0], Q_sB=r['solid_exchange'][1], Q_net=scalars['q_net'],
        energy_imbalance_rel=r['energy_imbalance'], mass_imbalance_rel_A=r['mass_imbalance'][0], mass_imbalance_rel_B=r['mass_imbalance'][1],
        Q_AB_imbalance_rel=r['enthalpy_imbalance'], Q_sA_interior=r['interior_exchange'][0], Q_sB_interior=r['interior_exchange'][1],
        Q_interior=r['interior_duty'], AB_interior=r['interior_imbalance'], **strict, _ltne_info=ltne,
        _max_outer=r['max_outer'], _ltne_max_iter=thermal_budget,
        _needs_full_validate=bool(p.get('compact', False) and not captured['history_converged']),
        sco2_nu_observations=r['nu_observations'], df_metadata=df_metadata,
        solver_converged=r['converged'], envelope_valid=r['envelope_ok'], envelope_reasons=r['envelope_reasons'],
        envelope_warnings=list(r['warnings']), p_clip_hits=scalars['pressure_clip_hits'])
    pressure_states = {label: None if f is None else f['inlet_pressure'] for label, f in zip('AB', r['flow'])}
    for label in 'AB':
        state = pressure_states[label]
        diagnostics_map['P_in_realized_' + label] = np.nan if state is None else state['realized_Pa']
        diagnostics_map['P_in_shoot_resid_' + label] = np.nan if state is None else state['relative_error']

    def simple_detail(f):
        if f is None:
            return None
        last = f['last']
        return dict(**{key: last[key] for key in ('exit_reason', 'final_res', 'res_norm_ref', 'final_res_mom',
            'final_res_mass_local', 'final_res_mass_global', 'outlet_backflow_frac')}, convergence_mode='f2', iterations=len(f['legacy']))

    transient, final = captured['transient'], captured['final']
    if not r['simple_ok']:
        diagnostics_map['envelope_warnings'].append('SIMPLE momentum solve did not converge in the FINAL solve: '
            + ', '.join(final or r['simple_failures'])
            + ' — the reported velocity/pressure field is not converged (inspect the F2 residuals and iteration budget).')
    elif transient:
        diagnostics_map['envelope_warnings'].append('SIMPLE momentum solve stalled in a TRANSIENT (superseded) solve: '
            + ', '.join(transient) + ' — the cold-start field was re-solved by the outer loop and the '
            'reported field DID converge, so this is informational. It does flag a hard cold start (typically high u).')
    if not r['finite_fields']:
        diagnostics_map['envelope_warnings'].append('Non-finite (NaN/inf) cells in the converged temperature or '
            'velocity field — the result is not physical; solver_converged is forced False.')
    diagnostics_map['envelope_warnings'] = list(dict.fromkeys(diagnostics_map['envelope_warnings']))
    diagnostics_map['convergence_detail'] = dict(inlet_pressure=pressure_states,
        simple_A=simple_detail(r['flow'][0]), simple_B=simple_detail(r['flow'][1]), simple_nonconv=r['simple_failures'],
        outer_dT=[h['temperature_change'] for h in r['outer']], outer_converged=r['outer_ok'], outer_iters=len(r['outer']),
        outer_hit_cap=not r['outer_ok'], simple_ok=r['simple_ok'], simple_nonconv_final=final, simple_nonconv_transient=transient,
        simple_exit_A=r['flow'][0]['last']['exit_reason'], simple_exit_B=None if r['flow'][1] is None else r['flow'][1]['last']['exit_reason'],
        ltne_ok=r['thermal_ok'], fields_finite=r['finite_fields'], envelope_ok=r['envelope_ok'])
    for mode in ('true_h', 'model_h'):
        key = mode + '_balance'
        diagnostics_map[key] = dict(final_info[key], outer_converged=r['outer_ok'], post_after_last_thermal=r['post_after_last_thermal'],
            state='last true-h solve, before any final post update' if mode == 'true_h' else 'last model-h thermal solve, before any final post update') if key in final_info else None
    diagnostics_map['native_full_3d'] = dict(abi=abi, entry_version=r['entry_version'], numerical_driver='cpp',
        coarse_bootstrap={label: None if f is None else f['bootstrap'] for label, f in zip('AB', r['flow'])},
        pressure={label: None if f is None else f['last']['pressure'] for label, f in zip('AB', r['flow'])})
    diagnostics_map['coarse_bootstrap_trace'] = r['bootstrap_trace']
    model_metadata = dict(case.metadata['model_metadata'])
    mass = freeze_value(r['mass'])
    true_h = None if r['true_h'] is None else dict(r['true_h']['_native_state'],
        mass_flux_A=mass[0], mass_flux_B=mass[1])
    if true_h and 'enthalpy_eos' in true_h:
        model_metadata['enthalpy_eos'] = true_h['enthalpy_eos']
    emit_audit = bool(cfg.get('_emit_audit', False))
    if emit_audit:
        for s, label in enumerate('AB'):
            f = r['flow'][s]
            bc = cfg['fluid_' + label + '_cfg']
            axes = p['axes'][label]
            outlet_coeff = scalars['audit_outlet'][s]
            diagnostics_map['_audit_s' + label + '_face'] = None if f is None else dict(
                u=f['u'], v=f['v'], w=f['w'], rho=f['density'], outlet_coeff=outlet_coeff,
                inlet_frac=f['inlet_opening'], outlet_frac=f['outlet_opening'], eps=f['epsilon'],
                dx=f['widths'][0], dy=f['widths'][1], dz=f['widths'][2], dir_real=bc['dir'], solver_to_real_perm=axes['solver_to_real_perm'])
            for key, value in (('m_dot_' + label + '_simple', r['inlet_mass'][s]), ('cp_' + label, r['inlet_cp'][s]),
                ('T_in' + label, cfg['T_in' + label]), ('u_' + label, cfg['u_' + label]), ('f' + label, bc)):
                diagnostics_map['_audit_' + key] = value if f is not None else None
            diagnostics_map['_audit_P_in' + label] = cfg['P_in' + label]
        diagnostics_map['_audit_eps'] = float(cfg['eps'])
        diagnostics_map['_audit_m_dot_B_phys_in'] = r['physical_mass_in'][1] if r['flow'][1] else None
        diagnostics_map['_audit_m_dot_B_phys_out'] = r['physical_mass_out'][1] if r['flow'][1] else None
    backend_version = f"full_3d_v{r['entry_version']}"
    metadata = dict(**({'continuation': r['continuation']} if 'continuation' in r else {}),
        **({'runtime_resources': r['runtime_resources']} if 'runtime_resources' in r else {}),
        _last_closure_ranges=r['last_closure_ranges'], dimension=3, quantity_basis='total', thermal_mode=r['mode'], parameters=case.parameters, design_fields=case.design_fields,
        **({'temperature_transport': r['temperature_evidence']['definition']} if 'temperature_evidence' in r else {}),
        input_resolution=r['_input_resolution'], property_sampling=r['property_sampling'],
        enthalpy_update_normalization=r['enthalpy_update_normalization'],
        simple_velocity_relaxation=r['simple_velocity_relaxation'],
        model_h_iterations=r['model_h_iterations'],
        design_mode=case.metadata['design_mode'], model_metadata=model_metadata, notices=case.metadata['notices'],
        application=dict(coeffs=dict(K_ffA=r['final_conductivity'][0], K_ffB=r['final_conductivity'][1],
            K_ss=fields['K_ss'] if emit_audit else None),
            props=dict(rho_cp_A=r['final_rho_cp'][0], rho_cp_B=r['final_rho_cp'][1], u_A_in_mps=cfg['u_A'], T_in_A_K=cfg['T_inA'])),
        **({'native': r['native_metadata']} if 'native_metadata' in r else {}),
        _native_applicability=r['_native_applicability'],
        diagnostics=diagnostics_map, df_metadata=df_metadata, model_roles=case.metadata['model_roles'],
        reporting_reference={key: diagnostics_map[key] for key in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')})
    metadata['execution_record'] = execution_record('cpp', backend_version, metadata,
        roles=case.metadata['model_roles'], **r['execution_facts'])
    return FieldResult(result_id=str(uuid4()), case_id=case.case_id, backend_id='cpp', backend_version=backend_version, grid=case.grid,
        fields=fields, field_metadata=field_metadata, model_refs=case.model_refs,
        boundary_fluxes=dict(mass_A=None if mass[0][0] is None else mass[0], mass_B=None if mass[1][0] is None else mass[1],
            mass_unit='kg/s', mass_axes=('x-face', 'y-face', 'z-face'), mass_sign='positive along physical coordinate axis', state='last thermal input',
            model_h=None if r['model_h'] is None else r['model_h']['_native_model_h'], true_h=true_h, report=report,
            energy=r.get('physical_ledger'),
            face_velocity_A=r['face_velocity'][0], face_velocity_B=r['face_velocity'][1] if r['flow'][1] else None,
            **({'temperature': r['temperature_evidence']} if 'temperature_evidence' in r else {})),
        pressure_evidence=pressure, run_status=dict(execution='completed', converged=r['converged'], outer_index=r['outer_index']),
        metadata=metadata)
