"""Bind validated saved 3D inputs to the native run and capture lifecycle."""
import ctypes as ct
from math import prod
import os
from pathlib import Path

import numpy as np

from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.run_environment import run_environment

from sjtu_tpmshx.cpp_interface._native_result_stage import (
    Evidence,
    Input as Evaluation,
    completed_report,
    detach_stage_fields,
    executed_view,
    execution_view_query as _execution_view_query,
    link_execution,
    nu_observation,
    record,
    stage_closures,
    stage_ledger,
)
from sjtu_tpmshx.cpp_interface._native_preparation_case import _Array as PreparedArray, _Evidence, _Text, _Model, _Nu
from .preparation_host import borrow_ranges as _ranges, borrow_solver_mesh, pack_saved_resources
from .solver_library._full_3d_abi import (
    _Array, _BootstrapTrace, _Callbacks, _Cancel, _Control, _EnergyEvidence,
    _FLAGS, _FLOW_ARRAYS, _Input, _OuterProgress, _PAIRS, _Progress, _Result,
)
from .solver_library._stage_capture_abi import (
    StageExecution,
    _energy_native_state,
    _energy_result_info,
    _full_enthalpy_info,
    _volume_info,
)
from .solver_library._thermal_abi import (
    _EnergyOptions,
    _FullEnergyEffectiveSettings,
    _IterationOptions,
    _energy_options,
    _full_enthalpy_defaults,
    _iteration_options,
)
from ._native_values import GridPort, grid_count, borrow_array as _array, borrow_text as _text, iteration_count
from .run_state import NativeRun

__all__ = [
    'open_library',
    'borrow_mesh',
    'require_saved_stage',
    'execution_view_query',
    'run_saved',
    'link_execution',
]

_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Size = record('SizeOption3D', [('present', _U), ('value', _Z)])
_Double = record('DoubleOption3D', [('present', _U), ('value', _D)])
_Uint = record('UintOption3D', [('present', _U), ('value', _U)])
_Request = record('StageRequest3D', [('abi_version', _U), ('struct_size', _Z),
    *[(name, _Size) for name in ('max_iter_simple', 'max_outer_ltne', 'thermal_iterations',
        'coarse_iterations', 'parallel_threshold')],
    *[(name, _Double) for name in ('outer_tol_K', 'thermal_relaxation', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K', 'roughness_height_m')],
    *[(name, _Uint) for name in ('pressure_shooting', 'variable_rho_cp', 'conservative',
        'strict_mass_balance', 'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a',
        'coarse_bootstrap', 'adaptive_pressure_tolerance', 'track_momentum', 'roughness_mode', 'envelope_mode')],
    ('convergence_mode', ct.c_char_p), ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *[(name, _Double) for name in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')],
    ('require_enthalpy_update_on_temperature', _U)])
_Host = record('StageControl3D', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _Z), ('callbacks', _Callbacks)])
_Axes = record('SavedAxes3D', [('solver_to_real', ct.c_int32 * 3), ('reverse', ct.c_int32),
    ('counts', _Z * 3), ('solver_counts', _Z * 3), ('lengths', _D * 3), ('solver_lengths', _D * 3),
    ('widths', PreparedArray * 3), ('port', GridPort)])
_Saved = record('StageSaved3Dv3', [('abi_version', _U), ('struct_size', _Z), ('input', ct.POINTER(_Input)),
    *[(name, _D) for name in ('nominal_cell_length_mm', 'nominal_wall_thickness_mm', 'nominal_porosity')],
    ('wall_thickness_m', PreparedArray), ('preparation', _Evidence),
    ('notices', ct.POINTER(_Text)), ('notice_count', _Z), ('inlet_recorded', _U),
    ('range_captured', ct.POINTER(_U)),
    ('lengths_m', _D * 3), ('design_mode', _U), ('have_z_controls', _U),
    ('axes', _Axes * 2),
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


_ExecutionView = record('ExecutionView3D', [('execution', StageExecution),
    ('settings', _FullEnergyEffectiveSettings), ('energy', _EnergyEvidence)])


def open_library(library, table_directory):
    path = Path(library)
    if not path.is_absolute():
        raise ValueError('native full 3D library must be an absolute path')
    path = path.resolve(strict=True)
    library = ct.CDLL(str(path))
    version = library.tpmshx_full_3d_abi_version
    version.argtypes, version.restype = [], _U
    abi = version()
    if abi != 2:
        raise ValueError(f'unsupported full 3D ABI {abi}; expected 2')
    if table_directory is not None and not Path(table_directory).is_absolute():
        raise ValueError('native full 3D table directory must be an absolute path')
    return path, library, abi, None if table_directory is None else str(table_directory).encode()


def borrow_mesh(case, library):
    return borrow_solver_mesh(case, library, 3)


def execution_view_query(library):
    return _execution_view_query(library, 3, _StageResult, _ExecutionView)


def bootstrap_query(library):
    try:
        query = library.tpmshx_full_3d_get_bootstrap_trace_v1
    except AttributeError as exc:
        raise ValueError('native full 3D library lacks bootstrap trace v1; rebuild the library for this binding') from exc
    query.argtypes = [ct.POINTER(_Result), ct.c_size_t, ct.POINTER(_BootstrapTrace)]
    query.restype = ct.c_int
    return query


def require_saved_stage(library):
    """Bind the saved v3 protocol. A library without it is a deployment error."""
    names = ('create_saved_v3', 'restore_saved_v3', 'advance_step_v1', 'phase_v1', 'snapshot_v1',
             'take_result_v1', 'release_run_v1', 'release_v1', 'get_capture_v1')
    try:
        stage_version = library.tpmshx_stage_run_3d_abi_version
        version = library.tpmshx_stage_capture_3d_abi_version
        for name in names:
            getattr(library, 'tpmshx_stage_run_3d_' + name)
        library.tpmshx_run_saved_case_3d_v3
    except AttributeError as error:
        raise ValueError('native library has an incomplete saved 3D stage protocol') from error
    stage_version.argtypes, stage_version.restype = [], _U
    stage_abi = stage_version()
    if stage_abi != 3:
        raise ValueError(f'unsupported saved 3D stage ABI {stage_abi}; expected 3')
    version.argtypes, version.restype = [], _U
    abi = version()
    if abi != 2:
        raise ValueError(f'unsupported saved 3D capture ABI {abi}; expected 2')


def pack_input(cfg, prepared, grid, design, shape, cell_mm, topology, sco2_multiplier, keepalive, *, mesh=None):
    """Borrow contiguous arrays. Convert only when the full solver layout requires it."""
    def view(value, expected=None):
        value = np.asarray(value, dtype=np.float64)
        if expected is not None:
            value = np.broadcast_to(value, expected)
        value = np.require(value, requirements=['C', 'A'])
        keepalive.append(value)
        return _Array(value.ctypes.data_as(ct.POINTER(ct.c_double)), value.size)
    data = _Input()
    data.topology = topology
    data.shape[:] = shape
    data.widths[:] = ([view(grid['d' + axis]) for axis in 'xyz'] if mesh is None else
                      [_Array(width.data, width.size) for width in mesh.solver_widths])
    for key, source in zip(('epsilon', 'epsilon_a', 'epsilon_b', 'permeability', 'forchheimer', 'solid_conductivity', 'cell_length'),
                           ('eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m', 'K_ss', 'L_field_m')):
        setattr(data, key, view(design[source], shape))
    thermal = cfg['thermal_geometry']
    spatial = bool(cfg.get('zone_grid_cells') or cfg.get('continuous_field'))
    geometry = thermal['fields' if spatial else 'uniform']
    if mesh is None or spatial != (thermal['fields'] is not None):
        data.area_density, data.hydraulic_diameter = view(geometry['A_0'], shape), view(geometry['D_h'], shape)
    else:
        data.area_density = _Array(mesh.solver_area.data, mesh.solver_area.size)
        data.hydraulic_diameter = _Array(mesh.solver_diameter.data, mesh.solver_diameter.size)
    data.reference_cell_length, data.reference_hydraulic_diameter = cell_mm * 1e-3, prepared['geometry']['D_h']
    data.spatial, data.asymmetric, data.solve_b = spatial, cfg.get('delta_levelset', 0.) != 0., cfg.get('fluid_B_cfg') is not None
    for s, label in enumerate('AB'):
        a = data.sides[s]
        axis = prepared['axes'][label]
        bc = cfg['fluid_' + label + '_cfg']
        a.fluid = ('air', 'water', 'sco2', 'co2').index(cfg['fluid_type_' + label])
        a.direction = 3 if bc is None else bc['dir']
        a.solver_axes[:] = [axis[key + '_real_axis'] for key in ('cross1', 'stream', 'cross2')]
        a.inlet_temperature, a.inlet_pressure, a.inlet_velocity = cfg['T_in' + label], cfg['P_in' + label], cfg['u_' + label]
        # The saved v3 stage builds the port rectangles of an active side from its saved axis record.
        if bc is None:
            a.inlet_rectangle[:] = a.outlet_rectangle[:] = (0., 1., 0., 1.)
        a.inlet_opening = view(prepared['openings'][label]['inlet'])
        a.outlet_opening = view(prepared['openings'][label]['outlet'])
        correction = (cfg.get('df_application') or {}).get(label, {})
        a.permeability_scale, a.forchheimer_scale = correction.get('scale_K', 1.), correction.get('scale_F', 1.)
        a.dispersion = cfg.get('disp_C_' + label, 0.)
        a.sco2_nusselt_multiplier = sco2_multiplier
        a.heat_transfer_geometry[:] = thermal['side_geometry'][label] if data.asymmetric else (1., 1., 1., 1.)
    data.sources[:] = [view(cfg.get('mms_S_' + s + '_field', np.empty(0))) for s in ('A', 'B', 's')]
    return data


def energy_request(cfg):
    return _energy_options(cfg.get('enthalpy_algorithm', 'temperature_sou'),
                           cfg.get('enthalpy_temperature_tol_K', 1e-8))


def model_h_request(cfg, strict):
    options = _iteration_options(cfg)
    if options is not None and (strict or any(cfg.get(name) is not None for name in (
            'ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega', 'ltne_enthalpy_tol'))):
        raise ValueError('model-h iteration controls cannot be combined with EOS controls')
    return options


def _request(cfg, energy, model_h):
    request = _Request(1, ct.sizeof(_Request))
    request.energy = ct.pointer(_EnergyOptions(energy.algorithm, energy.temperature_update_tolerance))
    if model_h is not None:
        request.model_h = model_h
    for target, source in (('energy_coupled_tolerance', 'ltne_enthalpy_coupled_energy_tol'),
                           ('energy_equation_tolerance', 'ltne_enthalpy_equation_energy_tol')):
        value = cfg.get(source)
        if value is not None:
            setattr(request, target, _Double(1, value))
    request.require_enthalpy_update_on_temperature = cfg.get('require_enthalpy_update_on_temperature', False)
    return request


def pack_run_controls(request, cfg, prepared, shape, *, validate_velocity_relaxation):
    outer = prepared['max_outer']
    if outer is not None:
        request.max_outer_ltne = _Size(1, iteration_count(outer))
    iterations = cfg.get('max_iter_simple')
    if iterations is not None:
        request.max_iter_simple = _Size(1, iteration_count(iterations))
    request.thermal_iterations = _Size(1, iteration_count(prepared['ltne_max_iter']))
    outer_tol = cfg.get('outer_tol_K')
    if outer_tol is not None:
        request.outer_tol_K = _Double(1, outer_tol)
    if 'ltne_alpha_T' in cfg:
        request.thermal_relaxation = _Double(1, cfg['ltne_alpha_T'])
    request.pressure_shooting = _Uint(1, run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') != '0')
    vrho = run_environment(cfg, 'TPMSHX_VAR_RHOCP')
    request.variable_rho_cp = _Uint(1, vrho == '1' if vrho in ('0', '1') else bool(cfg.get('variable_rho_cp', True)))
    for target, source, default in (
            ('conservative', 'conservative_ltne', True), ('strict_mass_balance', 'strict_mass_balance', True),
            ('force_cell_centered', 'force_cc_ltne', True), ('refined_port_energy', 'port_wall_refine', False),
            ('coarse_bootstrap', 'use_coarse_bootstrap', False)):
        setattr(request, target, _Uint(1, bool(cfg.get(source, default))))
    request.sco2_local_pressure_a = _Uint(1, run_environment(
        cfg, 'TPMSHX_SCO2_COMPRESSIBLE', '').lower() in ('1', 'true', 'yes'))
    if 'coarse_bootstrap_max_iter' in cfg:
        request.coarse_iterations = _Size(1, iteration_count(cfg['coarse_bootstrap_max_iter']))
    request.roughness_mode = _Uint(1, ('baseline', 'norris_1a', 'bhatti_shah_1b').index(cfg['roughness_resolved']['mode']))
    request.envelope_mode = _Uint(1, ('raise', 'warn', 'off').index(cfg.get('envelope_mode', 'raise')))
    request.roughness_height_m = _Double(1, cfg['roughness_resolved']['eps_m'])
    solid = cfg.get('T_s_init')
    if solid is not None:
        request.solid_seed_K = _Double(1, solid or 0.)
    relaxation = cfg.get('simple_velocity_relaxation')
    validate_velocity_relaxation(relaxation)
    if relaxation is not None:
        request.simple_velocity_relaxation = _Double(1, relaxation)
    request.adaptive_pressure_tolerance = _Uint(1, bool(cfg.get('use_adaptive_amg_tol', True)))
    request.track_momentum = _Uint(1, bool(cfg.get('track_momentum_residual', False)))
    threshold = int(os.environ.get('TPMSHX_PARALLEL_THRESHOLD', '200000'))
    request.parallel_threshold = _Size(1, 1 if prod(shape) >= threshold else ct.c_size_t(-1).value)
    for name in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        tolerance = cfg.get(name)
        if tolerance:
            setattr(request, name, _Double(1, tolerance))
    request.convergence_mode = b'f2'
    for target, source in (('energy_iterations', 'ltne_enthalpy_outer'), ('energy_sweeps', 'ltne_enthalpy_nsweep')):
        if source in cfg:
            setattr(request, target, _Size(1, iteration_count(cfg[source], zero=target == 'energy_sweeps')))
    for target, source in (('energy_omega', 'ltne_enthalpy_omega'), ('energy_update_tolerance', 'ltne_enthalpy_tol')):
        if source in cfg:
            setattr(request, target, _Double(1, cfg[source]))


def pack_saved_case(case, data, cell_mm, wall_mm, nu, keepalive):
    cfg = case.parameters
    ranges, captured = _ranges(case.metadata.get('applicability_inputs', ()), keepalive)
    notice_items = [_text(notice, keepalive) for notice in case.metadata['notices']]
    notices = (_Text * len(notice_items))(*notice_items)
    evidence = _Evidence(ranges=ranges, range_count=len(ranges))
    value = _Saved(3, ct.sizeof(_Saved), ct.pointer(data), cell_mm, wall_mm, cfg['eps'],
        _array(case.design_fields['t_field_m'], keepalive), evidence, notices, len(notices),
        'applicability_inputs' in case.metadata, captured)
    pack_saved_resources(case, value.models, value.sco2_nu, value, nu, keepalive)
    value.lengths_m[:] = [cfg[key] for key in ('L', 'H', 'Lz')]
    value.design_mode = {'uniform': 0, 'xy_extruded': 1, 'continuous_xy_extruded': 1,
                         'continuous_xyz': 2}.get(case.metadata['design_mode'], 3)
    value.have_z_controls = 'n_ctrl_z' in (cfg.get('continuous_field') or {})
    for index, side in enumerate('AB'):
        axis_record = value.axes[index]
        boundary = cfg['fluid_' + side + '_cfg']
        if boundary is not None and boundary['dir'] not in range(6):
            raise ValueError(f'prepared fluid {side} direction is invalid')
        axis_record.port = GridPort.from_mapping(boundary)
        if not axis_record.port.active:
            continue
        axis = cfg['prepared']['axes'][side]
        if axis['is_reverse'] not in (0, 1):
            raise ValueError(f'prepared fluid {side} reverse direction is invalid')
        if (any(item not in range(3) for item in axis['solver_to_real_perm'])
                or any(axis[name + '_real_axis'] not in range(3) for name in ('cross1', 'stream', 'cross2'))):
            raise ValueError(f'prepared fluid {side} axis permutation is invalid')
        axis_record.reverse = axis['is_reverse']
        axis_record.solver_to_real[:] = axis['solver_to_real_perm']
        for i, name in enumerate(('cross1', 'stream', 'cross2')):
            width = np.asarray(axis['d' + name])
            if width.ndim != 1:
                raise ValueError(f'prepared fluid {side} axis widths disagree with grid')
            axis_record.widths[i] = _array(width, keepalive)
            axis_record.counts[i], axis_record.lengths[i] = grid_count(axis['N_' + name]), axis['L_' + name]
            axis_record.solver_counts[i] = grid_count(axis['solver_init']['N' + 'xyz'[i]])
            axis_record.solver_lengths[i] = axis['solver_init']['L' + 'xyz'[i]]
    keepalive.append(notices)
    return value


class SavedRun(NativeRun):
    api_prefix = 'tpmshx_stage_run_3d'
    advance_name = 'advance_step'
    entry_names = {'create': 'create_saved', 'restore': 'restore_saved', 'release': 'release_run'}
    result_type = _StageResult
    result_release_name = 'tpmshx_stage_run_3d_release_v1'

    def __init__(self, library, saved, request, host, errors, state, error_types):
        self.errors = errors
        self.error_types = error_types
        self.creation_version = saved.abi_version
        super().__init__(library, [ct.POINTER(type(saved)), ct.POINTER(_Request), ct.POINTER(_Host)],
            [ct.byref(saved), ct.byref(request), ct.byref(host)], host.callbacks, state)

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


def copy_diagnostics(records, evidence):
    """Detach native drag bounds, strict ratios, and solver failure text before release."""
    def drag(value):
        return dict(scalar=bool(value.scalar), minimum=value.minimum, maximum=value.maximum)
    base_drag = [drag(value) for value in records.base_drag]
    executed_sides = [bool(evidence.executed_sides[index].solved) for index in range(2)]
    applied_drag = [
        [drag(value) for value in records.applied_drag[index]] if executed_sides[index] else None
        for index in range(2)
    ]
    strict_ratios = [
        evidence.strict_ratios[index][0] if evidence.strict_ratios[index] else None
        for index in range(4)
    ]
    transient = [records.transient_failures[i].decode() for i in range(records.transient_count)]
    final = [records.final_failures[i].decode() for i in range(records.final_count)]
    return dict(
        base_drag=base_drag,
        applied_drag=applied_drag,
        executed_sides=executed_sides,
        strict_ratios=strict_ratios,
        history_converged=bool(records.thermal_history_converged),
        transient=transient,
        final=final,
    )


def _copy(v, shape=None):
    if not v.size:
        return None
    result = np.ctypeslib.as_array(v.data, (v.size,)).copy()
    return result if shape is None else result.reshape(shape)


def _pressure(p):
    if not p.available:
        return None
    return dict(specified_Pa=p.specified, realized_Pa=p.realized, outlet_Pa=p.outlet,
                outlet_gauge_Pa=p.outlet_gauge, minimum_Pa=p.minimum,
                relative_error=p.relative_error, relative_tolerance=p.relative_tolerance,
                passed=bool(p.passed), definition=p.definition.decode())


def _model_info(r, shape, *, include_faces, capture_scalars=None, info=None):
    if info is None:
        info = _volume_info(r, shape, include_faces=include_faces,
            cell_count=None if capture_scalars is None else capture_scalars['model_h_cell_count'])
    else:
        faces = {'A': {}, 'B': {}}
        if include_faces:
            for label, side in zip('AB', r.volume.sides):
                for index, name in enumerate(('x-', 'x+', 'y-', 'y+', 'z-', 'z+')):
                    extent = shape[:index // 2] + shape[index // 2 + 1:]
                    faces[label][name] = _copy(side.boundaries[index].enthalpy_faces, extent)
        info['_native_model_h'] = faces
    names = [f'{side} strict {metric} < 1 %' for side in ('A', 'B') for metric in ('global', 'cellmax')]
    names += ['full-volume LTNE source balance < 1 %', 'physical boundary data complete']
    info['energy_finishing_checks'] = [dict(iterations=r.finishing_checks[i].iterations,
        gates=[(name, bool(value)) for name, value in zip(names, r.finishing_checks[i].gates)]) for i in range(r.finishing_count)]
    return info


def bootstrap_traces(query, result):
    traces = {}
    for side, label in enumerate('AB'):
        view = _BootstrapTrace()
        if query(ct.byref(result), side, ct.byref(view)):
            raise RuntimeError('native full 3D bootstrap trace query failed')
        if not view.available:
            traces[label] = None
            continue
        trace = dict(policy=view.policy.decode(), decision=view.decision.decode(),
                     selected=bool(view.selected), fine_shape=tuple(view.fine_shape))
        trace.update({key: getattr(view, key) for key in ('coarse_iteration_cap', 'recursive_iteration_cap',
            'auto_cell_threshold', 'min_coarse_axis', 'actual_levels', 'started_cap_sum', 'total_charged_iterations')})
        trace['levels'] = []
        for index in range(view.level_count):
            row = view.levels[index]
            entry = dict(depth=row.depth, fine_shape=tuple(row.fine_shape), coarse_shape=tuple(row.coarse_shape),
                         iteration_cap=row.iteration_cap, charged_iterations=row.charged_iterations, stop=row.stop.decode())
            entry.update({key: bool(getattr(row, key)) for key in ('solve_started', 'applied', 'converged', 'child_selected')})
            trace['levels'].append(entry)
        traces[label] = trace
    return traces


def require_completed(result, bootstrap_traces):
    if result.stop == 2:
        cancelled_error = CancelledError('compute cancelled by user')
        cancelled_error.coarse_bootstrap_trace = bootstrap_traces
        raise cancelled_error
    if result.stop not in (0, 1):
        raise RuntimeError('invalid native full 3D exit')


def make_callbacks(*, cancel_check=None, report_progress=None, iteration=None, outer_iteration=None):
    callback_errors = []

    def callback(fn, *args):
        if not callback_errors:
            try:
                return fn(*args)
            except BaseException as error:
                callback_errors.append(error)
        return None

    @_Cancel
    def cancelled(_):
        return int(bool(callback_errors) or bool(callback(cancel_check) if cancel_check else False))

    @_Progress
    def progress(_, percent):
        if report_progress is not None:
            callback(report_progress, int(percent))

    @_OuterProgress
    def outer(_, done, total):
        if iteration is not None:
            callback(iteration, f'outer {done}/{total}')
        if outer_iteration is not None:
            callback(outer_iteration, done, total)

    callbacks = _Callbacks(cancelled, progress, outer, None)
    return callbacks, callback_errors


def add_energy_evidence(detached, extra, settings, entry_version, shape, *, version):
    if detached['true_h'] is None or extra.outer_count != len(detached['outer']):
        raise RuntimeError('native full 3D energy evidence does not match the thermal history')
    _energy_result_info(detached['true_h'], extra.energy,
        temperature_tol=settings.last.temperature_update_tolerance, abi=entry_version,
        version=version, state_update='per_side_energy_relation')
    _energy_native_state(detached['true_h'], extra, shape, 'W')
    for index, row in enumerate(detached['outer']):
        _energy_result_info(row['true_h_info'], extra.outer[index],
            temperature_tol=settings.outer[index].temperature_update_tolerance, abi=entry_version,
            version=version, state_update='per_side_energy_relation')
    detached['mode'] = 'conservative_energy'


def _detach(r, shape, settings, energy_settings, entry_version, *, emit_audit, capture_scalars, stage_fields,
            records, report):
    """Copy the raw result arrays that the application capture and its audit need."""
    result = {name: getattr(r, name) if name == 'stop' else bool(getattr(r, name)) for name in _FLAGS}
    result.update({name: list(getattr(r, name)) for name in _PAIRS})
    result.update({name: getattr(r, name) for name in ('energy_imbalance', 'interior_duty', 'interior_imbalance', 'enthalpy_imbalance')})
    result['mode'], result['outer_index'] = ('temperature', 'model_h', 'true_h')[r.thermal_mode], r.thermal_outer_index
    result['stage_fields'] = stage_fields
    result['enthalpy'] = tuple([_copy(value, shape) for value in r.enthalpy])
    face_shapes = tuple([tuple([n + int(d == axis) for d, n in enumerate(shape)]) for axis in range(3)])
    for key in ('mass', 'face_velocity'):
        result[key] = tuple([
            tuple([_copy(value, sh) for value, sh in zip(side, face_shapes)])
            for side in getattr(r, key)
        ])
    result['flow'] = []
    for side, f in enumerate(r.flow):
        if not f.widths[0].size:
            result['flow'].append(None)
            continue
        flow = dict(widths=tuple([_copy(value) for value in f.widths]), pressure_reference=f.pressure_reference)
        nx, ny, nz = fshape = tuple([len(w) for w in flow['widths']])
        sizes = {key: fshape for key in _FLOW_ARRAYS}
        for axis, names in enumerate((('u', 'd_u'), ('v', 'd_v'), ('w', 'd_w'))):
            for key in names:
                sizes[key] = tuple([n + int(d == axis) for d, n in enumerate(fshape)])
        for key in ('inlet_velocity', 'inlet_opening', 'outlet_opening', 'fixed_inlet_massflux'):
            sizes[key] = (nx, nz)
        sizes['outlet_u_fraction'], sizes['outlet_w_fraction'] = (nx + 1, nz), (nx, nz + 1)
        for key in ('pressure_real', 'density_real', 'speed_real'):
            sizes[key] = shape
        application_arrays = ('pressure', 'inlet_opening', 'outlet_opening')
        audit_arrays = ('u', 'v', 'w', 'density', 'epsilon') if emit_audit else ()
        flow.update({key: _copy(getattr(f, key), sizes[key]) for key in _FLOW_ARRAYS
                     if key in application_arrays + audit_arrays})
        flow['legacy'] = _copy(f.legacy)
        last = f.last
        pressure = {name: getattr(last.pressure, name) for name, _ in last.pressure._fields_}
        flow['last'] = dict(exit_reason=records.simple_stop[side].decode(), converged=bool(last.converged),
            post_closure_measured=bool(last.post_closure_measured), post_closure_certified=bool(last.post_closure_certified),
            iterations=last.iterations, pressure_clip_hits=last.pressure_clip_hits, post_closure_rejections=last.post_closure_rejections,
            final_res=last.legacy_residual, res_norm_ref=last.legacy_reference,
            final_res_mom=last.momentum.maximum, final_res_mass_local=last.mass.local_residual,
            final_res_mass_global=last.mass.global_residual, outlet_backflow_frac=last.mass.backflow_fraction,
            pressure={name: value.decode() if isinstance(value, bytes) else value for name, value in pressure.items()})
        history = []
        for i in range(f.pressure_iteration_count):
            p = f.pressure_iterations[i]
            row = dict(stage=p.stage.decode(), anchor_Pa=p.anchor)
            for source, key in (('estimate', 'estimate_Pa2'), ('relative_error', 'relative_error'), ('target', 'target_Pa2'), ('step_fraction', 'step_fraction')):
                if getattr(p, 'has_' + source):
                    row[key] = getattr(p, source)
            if p.method:
                row['method'] = p.method.decode()
            history.append(row)
        flow['pressure_iterations'] = history
        flow['inlet_pressure'] = _pressure(f.inlet_pressure)
        if flow['inlet_pressure'] is not None:
            flow['inlet_pressure']['iterations'] = history
        b = f.bootstrap
        flow['bootstrap'] = None if not b.available else dict(applied=bool(b.applied), coarse_converged=bool(b.converged),
            coarse_iters=b.iterations, coarse_shape=tuple(b.shape), coarse_residual=b.residual, reason=b.reason.decode())
        result['flow'].append(flow)
    result['model_h'] = _model_info(r.model_h, shape, include_faces=True, capture_scalars=capture_scalars,
        info=report['model_h'][0]) if r.has_model_h else None
    result['true_h'] = _full_enthalpy_info(r.true_h, energy_settings.last, entry_version) if r.has_true_h else None
    if r.has_true_h:
        true_h = result['true_h']
        true_h['_native_state'] = dict(h_A=result['enthalpy'][0], h_B=result['enthalpy'][1],
            h_in_A=r.true_h.inlet_enthalpy[0], h_in_B=r.true_h.inlet_enthalpy[1],
            mass_flux_A=result['mass'][0], mass_flux_B=result['mass'][1])
        used = [s for s, flag in zip('AB', r.true_h.used_bicubic) if flag]
        if used:
            true_h['_native_state']['enthalpy_eos'] = dict(algorithm='bicubic_iteration_heos_polish_v2',
                iteration_backend='BICUBIC&HEOS', final_backend='HEOS', transport_backend='HEOS',
                coolprop_version=r.true_h.coolprop_version.decode(), sides=used, heos_polish=bool(r.true_h.heos_polish))
    result['staggered'] = []
    for p in r.staggered:
        result['staggered'].append(None if not p.available else dict(skipped=bool(p.skipped), used_bordered_lu=bool(p.used_bordered_lu),
            cg_iterations=p.cg_iterations, rhs_mean=p.rhs_mean, residual_relative=p.residual_relative,
            residual_available=bool(p.residual_available), residual_cells=_copy(p.residual_cells, shape),
            residual_sum=p.residual_sum, residual_max=p.residual_max, exchange=p.exchange, global_ratio=p.global_ratio, cell_ratio=p.cell_ratio))
    result['outer'] = []
    for i in range(r.outer_count):
        h = r.outer[i]
        row = dict(outer=h.outer_index, iters=h.thermal_iterations, residual=h.thermal_residual, converged=bool(h.thermal_converged),
                   coupling_converged=bool(h.coupling_converged), temperature_change=dict(zip(('Ta', 'Tb', 'Ts'), h.temperature_change)),
                   inlet_pressure=tuple([_pressure(p) for p in h.inlet_pressure]), pressure_reference=list(h.pressure_reference),
                   pressure_range=[list(p) for p in h.pressure_range])
        if h.startup_total_iterations:
            row['coupling_startup'] = dict(rejected_attempts=[dict(iterations=h.rejected_startup_iterations[k],
                reason=h.rejected_startup_reasons[k].decode()) for k in range(h.rejected_startup_count)],
                total_iterations=h.startup_total_iterations, iteration_budget=settings.thermal_iterations)
        if h.has_model_h:
            info = _model_info(h.model_h, shape, include_faces=False, capture_scalars=capture_scalars,
                               info=report['model_h'][i + 1])
            row['energy_finishing_checks'] = info['energy_finishing_checks']
            row['model_h_balance'] = dict(info['model_h_balance'], outer_index=h.outer_index, converged=bool(h.thermal_converged), iterations=h.thermal_iterations)
        if h.has_true_h:
            row['true_h_info'] = _full_enthalpy_info(h.true_h, energy_settings.outer[i], entry_version)
        result['outer'].append(row)
    result['simple_failures'] = [r.simple_failures[i].decode() for i in range(r.simple_failure_count)]
    result['warnings'] = [r.warnings[i].decode() for i in range(r.warning_count)]
    result['envelope_reasons'] = [r.envelope_reasons[i].decode() for i in range(r.envelope_reason_count)]
    result['nu_observations'] = {label: nu_observation(value, shape, capture_scalars['nu'][side])
        for side, (label, value) in enumerate(zip('AB', r.nu_observations))}
    result['final_conductivity'] = tuple([_copy(v, shape) if emit_audit else None for v in r.final_conductivity])
    result['final_rho_cp'] = tuple([_copy(v, shape) if emit_audit else None for v in r.final_rho_cp])
    result['inlet_cp'] = list(r.inlet_cp)
    return result


def run_saved(case, library, abi, table_directory, execution_query, *,
              mesh=None, cpu_threads,
              resume_state=None, checkpoint=None, checkpoint_due=None,
              checkpoint_phases=(1, 2, 6, 7, 8, 9, 10),
              error_types,
              validate_case, check_cancelled, validate_energy, validate_flow,
              select_nu, validate_velocity_relaxation,
              cancel_check=None, report_progress=None, iteration=None, outer_iteration=None):
    """Run the saved 3D stage and detach every native output before release."""
    from ._native_result_stage import copy_applicability

    query_bootstrap = bootstrap_query(library)
    shape, cell_mm, wall_mm, nu = validate_case(case, None if mesh is None else mesh.shape)
    cfg, prepared = case.parameters, case.parameters['prepared']
    emit_audit = bool(cfg.get('_emit_audit', False))
    check_cancelled()
    complete = library.tpmshx_run_saved_case_3d_v3
    energy = energy_request(cfg)
    has_water = 'water' in (cfg['fluid_type_A'], cfg['fluid_type_B'])
    if cfg.get('enthalpy_algorithm', 'temperature_sou') != 'temperature_sou':
        _full_enthalpy_defaults(library, 3, energy.algorithm, has_water)
    _, strict = validate_energy(cfg)
    model_h = model_h_request(cfg, strict)
    request = _request(cfg, energy, model_h)
    validate_flow(cfg)
    topology, sco2_multiplier = select_nu(cfg, nu)
    keepalive = []
    data = pack_input(cfg, prepared, case.grid, case.design_fields, shape, cell_mm,
                      topology, sco2_multiplier, keepalive, mesh=mesh)
    pack_run_controls(request, cfg, prepared, shape,
                      validate_velocity_relaxation=validate_velocity_relaxation)
    callbacks, errors = make_callbacks(
        cancel_check=cancel_check, report_progress=report_progress,
        iteration=iteration, outer_iteration=outer_iteration)
    host = _Host(case.case_id.encode(), table_directory, cpu_threads, callbacks)
    result = None
    try:
        saved = pack_saved_case(case, data, cell_mm, wall_mm, nu, keepalive)
        if checkpoint is None and resume_state is None:
            complete.argtypes = [ct.POINTER(_Saved), ct.POINTER(_Request), ct.POINTER(_Host),
                                 ct.POINTER(_StageResult), ct.POINTER(ct.c_char), ct.c_size_t]
            complete.restype = ct.c_int
            result = _StageResult()
            error = ct.create_string_buffer(2048)
            code = complete(ct.byref(saved), ct.byref(request), ct.byref(host), ct.byref(result), error, len(error))
            if errors:
                raise errors[0]
            if code:
                raise error_types.get(code, RuntimeError)(error.value.decode())
        else:
            with SavedRun(library, saved, request, host, errors, resume_state, error_types) as run:
                run.finish(checkpoint, checkpoint_due, checkpoint_phases)
                result = run.take_result()
        bootstrap = bootstrap_traces(query_bootstrap, result.raw)
        require_completed(result.raw, bootstrap)
        summary = copy_summary(library, result, emit_audit=emit_audit, copy_array=_copy)
        execution = executed_view(execution_query, result)
        report = completed_report(library, result)
        settings, executed, evidence = execution.settings, execution.execution, result.evidence
        if settings.outer_count != result.raw.outer_count:
            raise RuntimeError('native full 3D effective settings do not match the thermal history')
        records = executed.records.contents
        fields = detach_stage_fields(evidence, shape, prepared_fields={'K_ss': np.asarray(case.design_fields['K_ss'])})
        # Keep the complete-driver version used in published full_3d_v5 result records.
        entry_version = 5
        detached = _detach(result.raw, shape, result.resolved, settings, entry_version,
                           emit_audit=emit_audit,
                           capture_scalars=summary, stage_fields=fields, records=records, report=report)
        if settings.last.available:
            version = evidence.thermal.true_h.contents.energy_algorithm_version[0]
            add_energy_evidence(detached, execution.energy, settings, entry_version, shape, version=version)
        resolved = dict(
            simple_velocity_relaxation=result.resolved.simple.alpha_velocity,
            max_outer=result.resolved.max_outer,
            thermal_iterations=result.resolved.thermal_iterations,
        )
        output = dict(
            detached=detached,
            report=report,
            resolved=resolved,
            entry_version=entry_version,
            summary=summary,
            bootstrap=bootstrap,
        )
        if detached['mode'] in ('model_h', 'temperature'):
            if evidence.thermal.temperature:
                output['temperature_evidence'] = stage_ledger(evidence.thermal, records.temperature[0], shape)
            output['native_metadata'] = dict(abi=abi, algorithm=executed.algorithm.decode(),
                                             red_black=bool(executed.red_black))
        _, closure_warnings, last_closure_ranges = stage_closures(records)
        output['closure_warnings'] = closure_warnings
        output['last_closure_ranges'] = last_closure_ranges
        output['raw_diagnostics'] = copy_diagnostics(records, evidence)
        output['native_applicability'] = copy_applicability(
            evidence.applicability, case.metadata.get('applicability_inputs', ()))
        if 'temperature_evidence' not in output:
            output['physical_ledger'] = stage_ledger(evidence.thermal, None, shape)
        output['sco2_notices'] = tuple([None if raw is None else bytes(raw) for raw in executed.sco2_notices])
    finally:
        if result is not None:
            release_result(library, result)
    return output
