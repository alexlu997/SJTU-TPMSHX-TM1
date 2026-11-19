"""Bind validated saved 3D inputs to the native run and capture lifecycle."""
import ctypes as ct
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.data_types.model_refs import freeze_value
from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE

from sjtu_tpmshx.cpp_interface._native_result_stage import Evidence, Input as Evaluation, record
from sjtu_tpmshx.cpp_interface._native_preparation_case import _Array as PreparedArray, _Evidence, _Text, _Kind, _Model, _Nu, pack_saved_resources
from ._native_grid import _Port
from sjtu_tpmshx.cpp_interface.solver_library._full_3d_abi import _Array, _Callbacks, _Control, _Input, _Result
from sjtu_tpmshx.cpp_interface.solver_library.enthalpy import _EnergyOptions
from sjtu_tpmshx.cpp_interface.solver_library.model_h import _IterationOptions
from ._native_preparation_case import borrow_array as _array, borrow_ranges as _ranges, borrow_text as _text
from .run_state import NativeRun

_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Size = record('SizeOption3D', [('present', _U), ('value', _Z)])
_Double = record('DoubleOption3D', [('present', _U), ('value', _D)])
_Uint = record('UintOption3D', [('present', _U), ('value', _U)])
_Request = record('StageRequest3D', [('abi_version', _U), ('struct_size', _Z),
    *((name, _Size) for name in ('max_iter_simple', 'max_outer_ltne', 'thermal_iterations',
        'coarse_iterations', 'parallel_threshold')),
    *((name, _Double) for name in ('outer_tol_K', 'thermal_relaxation', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K', 'roughness_height_m')),
    *((name, _Uint) for name in ('pressure_shooting', 'variable_rho_cp', 'conservative',
        'strict_mass_balance', 'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a',
        'coarse_bootstrap', 'adaptive_pressure_tolerance', 'track_momentum', 'roughness_mode', 'envelope_mode')),
    ('convergence_mode', ct.c_char_p), ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *((name, _Double) for name in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')),
    ('require_enthalpy_update_on_temperature', _U)])
_Host = record('StageControl3D', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _Z), ('callbacks', _Callbacks)])
_Saved = record('StageSaved3D', [('abi_version', _U), ('struct_size', _Z), ('input', ct.POINTER(_Input)),
    *((name, _D) for name in ('nominal_cell_length_mm', 'nominal_wall_thickness_mm', 'nominal_porosity')),
    ('wall_thickness_m', PreparedArray), ('preparation', _Evidence),
    ('notices', ct.POINTER(_Text)), ('notice_count', _Z), ('inlet_recorded', _U),
    ('range_captured', ct.POINTER(_U))])
_Axes = record('SavedAxes3D', [('solver_to_real', ct.c_int32 * 3), ('reverse', ct.c_int32),
    ('counts', _Z * 3), ('solver_counts', _Z * 3), ('lengths', _D * 3), ('solver_lengths', _D * 3),
    ('widths', PreparedArray * 3), ('port', _Port)])
_SavedV2 = record('StageSaved3Dv2', [('abi_version', _U), ('struct_size', _Z), ('values', _Saved),
    ('lengths_m', _D * 3), ('design_mode', _U), ('have_z_controls', _U),
    ('reference_kinds', _Kind * 3), ('field_kinds', _Kind * 3), ('axes', _Axes * 2),
    ('models', _Model * 4), ('resource_fluids', _Text * 2), ('resource_topology', _Text),
    ('sco2_nu', _Nu), ('resource_nu', _Nu * 2)])
_Summary = record('StageCapture3D', [('nu_available', _U * 2), ('model_h_cell_count', _Z),
    ('nu_floor', _D * 2), ('nu_floor_fraction', _D * 2), ('q_net', _D),
    ('pressure_clip_hits', _Z), ('audit_outlet', _Array * 2)])


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', _U), ('struct_size', _Z), ('owner', ct.c_void_p),
        ('raw', _Result), ('evidence', Evidence), ('resolved', _Control), ('evaluation', Evaluation)]

    def __init__(self):
        super().__init__(1, ct.sizeof(type(self)))


def has_saved_stage(library):
    """Select the protocol before execution; partial protocols are errors."""
    version = getattr(library, 'tpmshx_stage_capture_3d_abi_version', None)
    capture = getattr(library, 'tpmshx_stage_run_3d_get_capture_v1', None)
    create = getattr(library, 'tpmshx_stage_run_3d_create_saved_v2', None)
    restore = getattr(library, 'tpmshx_stage_run_3d_restore_saved_v2', None)
    if (create is None) != (restore is None) or (create is not None and capture is None):
        raise ValueError('native library has an incomplete saved 3D stage protocol')
    if version is None and capture is None:
        return False
    names = ('create_saved', 'restore_saved', 'advance_step', 'phase', 'snapshot',
             'take_result', 'release_run', 'release')
    if version is None or capture is None or not all(
            hasattr(library, 'tpmshx_stage_run_3d_' + name + '_v1') for name in names):
        raise ValueError('native library has an incomplete saved 3D stage protocol')
    version.argtypes, version.restype = [], _U
    abi = version()
    if abi != 1:
        raise ValueError(f'unsupported saved 3D capture ABI {abi}; expected 1')
    return True


def saved_inputs(case):
    from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig, reject_retired_research_options
    from sjtu_tpmshx.data_types.persistence_validation import validate_grid, validate_thermal_geometry

    if case.grid.get('dimension') != 3:
        raise ValueError('3D execution requires a prepared 3D grid')
    cfg = dict(case.parameters)
    reject_retired_research_options(cfg)
    missing = {'thermal_geometry', 'roughness_resolved', 'df_application'} - cfg.keys()
    if missing:
        raise ValueError(f'incomplete prepared 3D execution data: {sorted(missing)}')
    shape = validate_grid(case.grid)
    validate_thermal_geometry(cfg['thermal_geometry'], shape)
    prepared = dict(cfg.pop('prepared'))
    active = case.metadata.get('active_fluids')
    if active is not None and (tuple(prepared['axes']) != tuple(active)
            or set(prepared['openings']) != set(active)
            or tuple(side for side in 'AB' if cfg['fluid_' + side + '_cfg'] is not None) != tuple(active)):
        raise ValueError('prepared active fluids disagree with the ports and axis maps')
    for axis, count in zip('xyz', shape):
        if prepared['N' + axis] != count:
            raise ValueError(f'prepared {axis} count and grid disagree')
        prepared['d' + axis] = case.grid['d' + axis]
    cfg['Lcell'], cfg['t_wall'] = cfg['L_cell_m'] * 1e3, cfg['t_wall_m'] * 1e3
    for side in 'AB':
        axis = prepared['axes'].get(side)
        if axis is not None:
            for mask in prepared['openings'][side].values():
                if np.shape(mask) != (axis['N_cross1'], axis['N_cross2']):
                    raise ValueError(f'invalid prepared fluid {side} opening mask')
    cfg['sco2_nu'] = Sco2NuConfig(**cfg['sco2_nu'])
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
    prepared['design'] = case.design_fields
    return cfg, prepared


def pack_saved_v2(saved, case, cfg, prepared, keepalive):
    from ._native_fp import buffer_scalar
    from ._native_grid import _port

    value = _SavedV2(2, ct.sizeof(_SavedV2), saved)
    pack_saved_resources(case, value.models, value.sco2_nu, value, cfg['sco2_nu'], keepalive)
    value.lengths_m[:] = [cfg[key] for key in ('L', 'H', 'Lz')]
    value.design_mode = {'uniform': 0, 'xy_extruded': 1, 'continuous_xy_extruded': 1,
                         'continuous_xyz': 2}.get(case.metadata['design_mode'], 3)
    value.have_z_controls = 'n_ctrl_z' in (cfg.get('continuous_field') or {})
    for index, (key, name) in enumerate(zip(('Lcell', 't_wall', 'eps'), ('L_field_m', 't_field_m', 'eps_arr'))):
        scalar = buffer_scalar(cfg[key])
        value.reference_kinds[index] = _Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))
        dtype = np.asarray(prepared['design'][name]).dtype
        value.field_kinds[index] = _Kind(dtype.itemsize * 8, 1 if dtype.kind == 'f' else 2, 2)
    for index, side in enumerate('AB'):
        record = value.axes[index]
        record.port = _port(cfg['fluid_' + side + '_cfg'])
        if not record.port.active:
            continue
        axis = prepared['axes'][side]
        record.reverse = axis['is_reverse']
        record.solver_to_real[:] = axis['solver_to_real_perm']
        for i, name in enumerate(('cross1', 'stream', 'cross2')):
            width = np.asarray(axis['d' + name])
            if width.ndim != 1:
                raise ValueError(f'prepared fluid {side} axis widths disagree with grid')
            record.widths[i] = _array(width, keepalive)
            record.counts[i], record.lengths[i] = axis['N_' + name], axis['L_' + name]
            record.solver_counts[i] = axis['solver_init']['N' + 'xyz'[i]]
            record.solver_lengths[i] = axis['solver_init']['L' + 'xyz'[i]]
    return value


def _request(cfg, controls, energy, model_h):
    request = _Request(1, ct.sizeof(_Request))
    if cfg.get('max_iter_simple') is not None:
        request.max_iter_simple = _Size(1, controls.initial_simple_iterations)
    for target, source in (('max_outer_ltne', 'max_outer'), ('thermal_iterations', 'thermal_iterations'),
                           ('coarse_iterations', 'coarse_iterations')):
        setattr(request, target, _Size(1, getattr(controls, source)))
    request.parallel_threshold = _Size(1, 1 if controls.simple.ordering else ct.c_size_t(-1).value)
    for target, source in (('outer_tol_K', 'outer_temperature_tolerance'), ('thermal_relaxation', 'thermal_relaxation'),
                           ('roughness_height_m', 'roughness_height')):
        setattr(request, target, _Double(1, getattr(controls, source)))
    request.simple_velocity_relaxation = _Double(1, controls.simple.alpha_velocity)
    for target, source in (('mom_tol', 'momentum_tolerance'), ('mass_local_tol', 'local_mass_tolerance'), ('mass_global_tol', 'global_mass_tolerance')):
        setattr(request, target, _Double(1, getattr(controls.simple.convergence, source)))
    if controls.has_initial_solid_temperature:
        request.solid_seed_K = _Double(1, controls.initial_solid_temperature)
    for name in ('pressure_shooting', 'variable_rho_cp', 'conservative', 'strict_mass_balance',
                 'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a', 'coarse_bootstrap',
                 'roughness_mode', 'envelope_mode'):
        setattr(request, name, _Uint(1, getattr(controls, name)))
    request.adaptive_pressure_tolerance = _Uint(1, controls.simple.adaptive_pressure_tolerance)
    request.track_momentum = _Uint(1, controls.simple.track_momentum)
    request.convergence_mode = b'f2'
    if model_h is not None:
        request.model_h = model_h
    selected = _EnergyOptions(energy.algorithm, energy.temperature_update_tolerance)
    request.energy = ct.pointer(selected)
    for target, source in (('energy_iterations', 'ltne_enthalpy_outer'), ('energy_sweeps', 'ltne_enthalpy_nsweep')):
        if cfg.get(source) is not None:
            setattr(request, target, _Size(1, cfg[source]))
    for target, source in (('energy_omega', 'ltne_enthalpy_omega'), ('energy_update_tolerance', 'ltne_enthalpy_tol'),
                           ('energy_coupled_tolerance', 'ltne_enthalpy_coupled_energy_tol'),
                           ('energy_equation_tolerance', 'ltne_enthalpy_equation_energy_tol')):
        if cfg.get(source) is not None:
            setattr(request, target, _Double(1, cfg[source]))
    request.require_enthalpy_update_on_temperature = cfg.get('require_enthalpy_update_on_temperature', False)
    return request


class SavedRun(NativeRun):
    api_prefix = 'tpmshx_stage_run_3d'
    creation_version = 1
    advance_name = 'advance_step'
    entry_names = {'create': 'create_saved', 'restore': 'restore_saved', 'release': 'release_run'}
    result_type = _StageResult
    result_release_name = 'tpmshx_stage_run_3d_release_v1'

    def __init__(self, library, case, cfg, prepared, data, controls, energy, model_h, callbacks, errors, control, state):
        self.errors, self.keepalive = errors, []
        ranges, captured = _ranges(case.metadata.get('applicability_inputs', ()), self.keepalive)
        notices = (_Text * len(case.metadata['notices']))(*(
            _text(notice, self.keepalive) for notice in case.metadata['notices']))
        evidence = _Evidence(ranges=ranges, range_count=len(ranges))
        saved = _Saved(1, ct.sizeof(_Saved), ct.pointer(data), cfg['Lcell'], cfg['t_wall'], cfg['eps'],
            _array(prepared['design']['t_field_m'], self.keepalive), evidence, notices, len(notices),
            'applicability_inputs' in case.metadata, captured)
        if getattr(library, 'tpmshx_stage_run_3d_create_saved_v2', None) is not None:
            self.creation_version = 2
            saved = pack_saved_v2(saved, case, cfg, prepared, self.keepalive)
        request = _request(cfg, controls, energy, model_h)
        host = _Host(case.case_id.encode(), controls.table_directory, control.native_cpu_threads(), callbacks)
        self.keepalive.extend((saved, request, host, notices))
        super().__init__(library, [ct.POINTER(type(saved)), ct.POINTER(_Request), ct.POINTER(_Host)],
            [ct.byref(saved), ct.byref(request), ct.byref(host)], callbacks, state)

    def _call(self, function, *args):
        error = ct.create_string_buffer(2048)
        code = function(*args, error, len(error))
        if self.errors:
            raise self.errors[0]
        if code:
            raise self.error_types.get(code, RuntimeError)(error.value.decode())


def copy_summary(library, result, *, emit_audit, copy_array):
    query = library.tpmshx_stage_run_3d_get_capture_v1
    query.argtypes, query.restype = [ct.POINTER(_StageResult), _U, ct.POINTER(_Summary)], ct.c_int
    summary = _Summary()
    if query(ct.byref(result), emit_audit, ct.byref(summary)):
        raise RuntimeError('native full 3D capture query failed')
    return dict(model_h_cell_count=summary.model_h_cell_count, q_net=summary.q_net,
        pressure_clip_hits=summary.pressure_clip_hits,
        nu=[dict(floor=summary.nu_floor[i], floor_fraction=summary.nu_floor_fraction[i])
            if summary.nu_available[i] else None for i in range(2)],
        audit_outlet=[copy_array(value, (result.raw.flow[i].widths[0].size, result.raw.flow[i].widths[2].size))
                      for i, value in enumerate(summary.audit_outlet)])


def release_result(library, result):
    release = library.tpmshx_stage_run_3d_release_v1
    release.argtypes, release.restype = [ct.POINTER(_StageResult)], None
    release(ct.byref(result))


def diagnostics(records, evidence, config, design):
    def drag(value):
        return value.minimum if value.scalar else dict(min=value.minimum, max=value.maximum)
    mode = config.get('df_mode', 'cfd_smooth')
    base_k, base_cf = (value.minimum if np.size(design[name]) == 1 else drag(value)
                       for name, value in zip(('K_m2', 'cF_per_m'), records.base_drag))
    summary = dict(mode=mode)
    ratios = {}
    for index, side in enumerate('AB'):
        for offset, suffix in enumerate(('', '_cellmax')):
            ratio = evidence.strict_ratios[2 * index + offset]
            ratios['eps_' + side + '_strict' + suffix] = ratio[0] if ratio else None
        summary[side] = None
        if not evidence.executed_sides[index].solved:
            continue
        applied_k, applied_cf = map(drag, records.applied_drag[index])
        if mode == 'experimental':
            row = dict((config.get('df_application') or {}).get(side, {}))
        else:
            row = dict(scale_K=1., scale_F=1., campaign=CFD_CAMPAIGN, scope=CFD_SCOPE)
        summary[side] = dict(row, base_K=base_k, base_cF=base_cf, applied_K=applied_k, applied_cF=applied_cf)
    return dict(df_metadata=summary, strict_ratios=ratios, history_converged=bool(records.thermal_history_converged),
                transient=[records.transient_failures[i].decode() for i in range(records.transient_count)],
                final=[records.final_failures[i].decode() for i in range(records.final_count)])


def capture_result(case, cfg, p, r, abi):
    scalars = r.get('capture_scalars')
    if 'stage_fields' in r:
        fields, field_metadata = r['stage_fields']
    else:
        from .solver_library.full_3d_capture import _legacy_fields
        fields, field_metadata = _legacy_fields(case, p, r)
    pressure,report={},{}
    for s,label in enumerate('AB'):
        f=r['flow'][s]
        if f is None:
            continue
        axis=case.parameters['prepared']['axes'][label]
        pressure[label]=dict(P=f['pressure'],dx=f['widths'][0],dy=f['widths'][1],dz=f['widths'][2],
            inlet_frac=f['inlet_opening'],outlet_frac=f['outlet_opening'],P_ref_abs=f['pressure_reference'],axis_map=axis,
            unit='Pa',axes=('solver_x','solver_y','solver_z'),stream_axis=1,state='final SIMPLE flow',method='face_extrapolation_v1')
        report[label]=dict(direction=cfg['fluid_'+label+'_cfg']['dir'])
    captured = r.get('stage_diagnostics')
    if captured is None:
        from .solver_library.full_3d_capture import _legacy_drag, _legacy_ratios
        df_metadata = _legacy_drag(cfg, p, r)
        strict = _legacy_ratios(r)
    else:
        df_metadata, strict = captured['df_metadata'], captured['strict_ratios']
    model_h_calls=r['model_h_iterations']['records']
    thermal_budget=(model_h_calls[-1]['settings']['total_iteration_budget'] if model_h_calls else p['ltne_max_iter'])
    ltne=[]
    for h in r['outer']:
        row={key:h[key] for key in ('outer','iters','converged','residual')}
        for key in ('coupling_startup','energy_finishing_checks','model_h_balance'):
            if key in h:
                row[key]=h[key]
        if 'true_h_info' in h:
            info=h['true_h_info']
            row['true_h_balance']=dict(Q_A=info['Q_A'],Q_B=info['Q_B'],units='W',outer_index=h['outer'],
                converged=h['converged'],iterations=h['iters'],residual=h['residual'],
                pressure_source='completed SIMPLE P_ref_abs + gauge',P_in_A_Pa=cfg['P_inA'],P_in_B_Pa=cfg['P_inB'],
                P_A_offset_Pa=h['pressure_reference'][0],P_B_offset_Pa=h['pressure_reference'][1],
                P_A_range_Pa=h['pressure_range'][0],P_B_range_Pa=h['pressure_range'][1])
            row['true_h_balance'].update({key:info[key] for key in ('exit_reason','enthalpy_clip_counts','effective_settings',
                'coupled_energy_balance','equation_energy_balance','energy_algorithm',
                'energy_algorithm_version','temperature_update_K') if key in info})
        ltne.append(row)
    final_info=ltne[-1]
    diagnostics=dict(dP=r['pressure_drop'][0],dP_A=r['pressure_drop'][0],dP_B=r['pressure_drop'][1],
        Lx=cfg['L'],Ly=cfg['H'],Lz=cfg['Lz'],Q=r['duty'][0],Q_total=r['duty'][0],
        Q_enthalpy_A=r['duty'][0],Q_enthalpy_B=r['duty'][1],Q_solid_B=r['solid_exchange'][1],
        mass_flow_A_kg_s=r['inlet_mass'][0],mass_flow_B_kg_s=r['inlet_mass'][1] if r['flow'][1] else None,
        u_A=cfg['u_A'],T_in=cfg['T_inA'],T_A_out=r['outlet_temperature'][0],T_B_out=r['outlet_temperature'][1] if r['flow'][1] else None,
        T_out_A=r['outlet_temperature'][0],T_out_B=r['outlet_temperature'][1] if r['flow'][1] else None,
        dir_A=cfg['fluid_A_cfg']['dir'],dir_B=cfg['fluid_B_cfg']['dir'] if r['flow'][1] else None,
        Q_sA=r['solid_exchange'][0],Q_sB=r['solid_exchange'][1],Q_net=sum(r['solid_exchange']) if scalars is None else scalars['q_net'],
        energy_imbalance_rel=r['energy_imbalance'],mass_imbalance_rel_A=r['mass_imbalance'][0],mass_imbalance_rel_B=r['mass_imbalance'][1],
        Q_AB_imbalance_rel=r['enthalpy_imbalance'],Q_sA_interior=r['interior_exchange'][0],Q_sB_interior=r['interior_exchange'][1],
        Q_interior=r['interior_duty'],AB_interior=r['interior_imbalance'],**strict,_ltne_info=ltne,
        _max_outer=p['max_outer'] if p['max_outer'] is not None else 12,_ltne_max_iter=thermal_budget,
        _needs_full_validate=bool(p.get('compact',False) and not (captured['history_converged'] if captured is not None else all(h['converged'] for h in ltne))),
        sco2_nu_observations=r['nu_observations'],df_metadata=df_metadata,
        solver_converged=r['converged'],envelope_valid=r['envelope_ok'],envelope_reasons=r['envelope_reasons'],
        envelope_warnings=list(r['warnings']),p_clip_hits=(sum(f['last']['pressure_clip_hits'] for f in r['flow'] if f is not None)
            if scalars is None else scalars['pressure_clip_hits']))
    pressure_states={label:None if f is None else f['inlet_pressure'] for label,f in zip('AB',r['flow'])}
    for label in 'AB':
        state=pressure_states[label]
        diagnostics['P_in_realized_'+label]=np.nan if state is None else state['realized_Pa']
        diagnostics['P_in_shoot_resid_'+label]=np.nan if state is None else state['relative_error']
    def simple_detail(f):
        if f is None:
            return None
        last=f['last']
        return dict(**{key:last[key] for key in ('exit_reason','final_res','res_norm_ref','final_res_mom',
            'final_res_mass_local','final_res_mass_global','outlet_backflow_frac')},convergence_mode='f2',iterations=len(f['legacy']))
    if captured is not None:
        transient, final = captured['transient'], captured['final']
    else:
        transient=[name for name in r['simple_failures'] if name.startswith(('A@init','B@init'))]
        final=[name for name in r['simple_failures'] if name not in transient]
    if not r['simple_ok']:
        diagnostics['envelope_warnings'].append('SIMPLE momentum solve did not converge in the FINAL solve: '
            + ', '.join(final or r['simple_failures'])
            + ' — the reported velocity/pressure field is not converged (inspect the F2 residuals and iteration budget).')
    elif transient:
        diagnostics['envelope_warnings'].append('SIMPLE momentum solve stalled in a TRANSIENT (superseded) solve: '
            + ', '.join(transient) + ' — the cold-start field was re-solved by the outer loop and the '
            'reported field DID converge, so this is informational. It does flag a hard cold start (typically high u).')
    if not r['finite_fields']:
        diagnostics['envelope_warnings'].append('Non-finite (NaN/inf) cells in the converged temperature or '
            'velocity field — the result is not physical; solver_converged is forced False.')
    diagnostics['envelope_warnings']=list(dict.fromkeys(diagnostics['envelope_warnings']))
    diagnostics['convergence_detail']=dict(inlet_pressure=pressure_states,
        simple_A=simple_detail(r['flow'][0]),simple_B=simple_detail(r['flow'][1]),simple_nonconv=r['simple_failures'],
        outer_dT=[h['temperature_change'] for h in r['outer']],outer_converged=r['outer_ok'],outer_iters=len(r['outer']),
        outer_hit_cap=not r['outer_ok'],simple_ok=r['simple_ok'],simple_nonconv_final=final,simple_nonconv_transient=transient,
        simple_exit_A=r['flow'][0]['last']['exit_reason'],simple_exit_B=None if r['flow'][1] is None else r['flow'][1]['last']['exit_reason'],
        ltne_ok=r['thermal_ok'],fields_finite=r['finite_fields'],envelope_ok=r['envelope_ok'])
    for mode in ('true_h','model_h'):
        key=mode+'_balance'
        diagnostics[key]=dict(final_info[key],outer_converged=r['outer_ok'],post_after_last_thermal=r['post_after_last_thermal'],
            state='last true-h solve, before any final post update' if mode=='true_h' else 'last model-h thermal solve, before any final post update') if key in final_info else None
    diagnostics['native_full_3d']=dict(abi=abi,entry_version=r['entry_version'],numerical_driver='cpp',
        coarse_bootstrap={label:None if f is None else f['bootstrap'] for label,f in zip('AB',r['flow'])},
        pressure={label:None if f is None else f['last']['pressure'] for label,f in zip('AB',r['flow'])})
    diagnostics['coarse_bootstrap_trace'] = r['bootstrap_trace']
    model_metadata=dict(case.metadata['model_metadata'])
    mass=freeze_value(r['mass'])
    true_h=None if r['true_h'] is None else dict(r['true_h']['_native_state'],
        mass_flux_A=mass[0], mass_flux_B=mass[1])
    if true_h and 'enthalpy_eos' in true_h:
        model_metadata['enthalpy_eos']=true_h['enthalpy_eos']
    emit_audit=bool(cfg.get('_emit_audit',False))
    if emit_audit:
        for s,label in enumerate('AB'):
            f=r['flow'][s];bc=cfg['fluid_'+label+'_cfg'];axes=p['axes'][label]
            outlet_coeff=None if f is None else f['outlet_opening']
            if scalars is not None:
                outlet_coeff = scalars['audit_outlet'][s]
            elif f is not None and cfg['fluid_type_'+label] not in ('sco2', 'co2'):
                # Legacy audit-only display weight; raw opening owns every solved face.
                from .solver_library.full_3d_capture import _build_outlet_frac_taper
                outlet_coeff=outlet_coeff*_build_outlet_frac_taper(*outlet_coeff.shape)
            diagnostics['_audit_s'+label+'_face']=None if f is None else dict(
                u=f['u'],v=f['v'],w=f['w'],rho=f['density'],outlet_coeff=outlet_coeff,
                inlet_frac=f['inlet_opening'],outlet_frac=f['outlet_opening'],eps=f['epsilon'],
                dx=f['widths'][0],dy=f['widths'][1],dz=f['widths'][2],dir_real=bc['dir'],solver_to_real_perm=axes['solver_to_real_perm'])
            for key,value in (('m_dot_'+label+'_simple',r['inlet_mass'][s]),('cp_'+label,r['inlet_cp'][s]),
                ('T_in'+label,cfg['T_in'+label]),('u_'+label,cfg['u_'+label]),('f'+label,bc)):
                diagnostics['_audit_'+key]=value if f is not None else None
            diagnostics['_audit_P_in'+label]=cfg['P_in'+label]
        diagnostics['_audit_eps']=float(cfg['eps'])
        diagnostics['_audit_m_dot_B_phys_in']=r['physical_mass_in'][1] if r['flow'][1] else None
        diagnostics['_audit_m_dot_B_phys_out']=r['physical_mass_out'][1] if r['flow'][1] else None
    return FieldResult(result_id=str(uuid4()),case_id=case.case_id,backend_id='cpp',backend_version=f"full_3d_v{r['entry_version']}",grid=case.grid,
        fields=fields,field_metadata=field_metadata,model_refs=case.model_refs,
        boundary_fluxes=dict(mass_A=None if mass[0][0] is None else mass[0],mass_B=None if mass[1][0] is None else mass[1],
            mass_unit='kg/s',mass_axes=('x-face','y-face','z-face'),mass_sign='positive along physical coordinate axis',state='last thermal input',
            model_h=None if r['model_h'] is None else r['model_h']['_native_model_h'],true_h=true_h,report=report,
            energy=r.get('physical_ledger'),
            face_velocity_A=r['face_velocity'][0],face_velocity_B=r['face_velocity'][1] if r['flow'][1] else None,
            **({'temperature':r['temperature_evidence']} if 'temperature_evidence' in r else {})),
        pressure_evidence=pressure,run_status=dict(execution='completed',converged=r['converged'],outer_index=r['outer_index']),
        metadata=dict(**({'continuation':r['continuation']} if 'continuation' in r else {}),
            **({'runtime_resources':r['runtime_resources']} if 'runtime_resources' in r else {}),
            _last_closure_ranges=r['last_closure_ranges'],dimension=3,quantity_basis='total',thermal_mode=r['mode'],parameters=case.parameters,design_fields=case.design_fields,
            **({'temperature_transport':r['temperature_evidence']['definition']} if 'temperature_evidence' in r else {}),
            input_resolution=cfg['_input_resolution'], property_sampling=r['property_sampling'],
            enthalpy_update_normalization=r['enthalpy_update_normalization'],
            simple_velocity_relaxation=r['simple_velocity_relaxation'],
            model_h_iterations=r['model_h_iterations'],
            design_mode=case.metadata['design_mode'],model_metadata=model_metadata,notices=case.metadata['notices'],
            application=dict(coeffs=dict(K_ffA=r['final_conductivity'][0],K_ffB=r['final_conductivity'][1],
                K_ss=np.asarray(p['design']['K_ss']) if emit_audit else None),
                props=dict(rho_cp_A=r['final_rho_cp'][0],rho_cp_B=r['final_rho_cp'][1],u_A_in_mps=cfg['u_A'],T_in_A_K=cfg['T_inA'])),
            **({'native':r['native_metadata']} if 'native_metadata' in r else {}),
            diagnostics=diagnostics,df_metadata=df_metadata,model_roles=case.metadata['model_roles'],
            reporting_reference={key:diagnostics[key] for key in ('Q','dP_A','dP_B','T_out_A','T_out_B')}))
