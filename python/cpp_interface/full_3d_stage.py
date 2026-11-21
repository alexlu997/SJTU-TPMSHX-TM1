"""Bind validated saved 3D inputs to the native run and capture lifecycle."""
import ctypes as ct
from math import prod
import os
from pathlib import Path
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.data_types.compute_config import (
    Sco2NuConfig, reject_retired_research_options, uses_default_thermal_recipe, validate_simple_velocity_relaxation,
)
from sjtu_tpmshx.data_types.persistence_validation import (
    grid_axes, validate_axis_permutation, validate_grid, validate_thermal_geometry,
)
from sjtu_tpmshx.physical_models.field_coordinates_3d import _port_rectangles
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.run_environment import require_f2_mode, run_environment
from sjtu_tpmshx.run_control.run_warnings import current_warnings, merge_warnings
from sjtu_tpmshx.data_types.field_result import FieldResult, execution_record
from sjtu_tpmshx.data_types.model_refs import freeze_value
from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE

from sjtu_tpmshx.cpp_interface._native_result_stage import (Evidence, Input as Evaluation,
    detach_stage_fields, nu_observation, record, stage_closures, stage_ledger)
from sjtu_tpmshx.cpp_interface._native_preparation_case import _Array as PreparedArray, _Evidence, _Text, _Kind, _Model, _Nu
from .preparation_host import pack_saved_resources
from .solver_library._full_3d_abi import (_Array, _BootstrapTrace, _Callbacks, _Cancel, _Control, _EnergyEvidence,
    _FLAGS, _FLOW_ARRAYS, _Input, _OuterProgress, _PAIRS, _Progress, _Result)
from .solver_library._stage_capture_abi import (
    StageExecution,
    _decode_iteration_records,
    _decode_update_scale,
    _energy_native_state,
    _energy_result_info,
    _full_enthalpy_info,
    _volume_info,
    executed_inputs,
    executed_view,
    execution_sides,
    execution_view_query,
    replay_sco2_notices,
    sampling_records,
    execution_facts,
)
from .solver_library.closure_evidence import copy_nu_observation, copy_range_observations
from .solver_library._thermal_abi import (
    _EnergyOptions,
    _FullEnergyEffectiveSettings,
    _IterationOptions,
    _energy_options,
    _full_enthalpy_defaults,
    _iteration_options,
)
from .solver_library.simple_3d import _STOPS
from .preparation_host import borrow_ranges as _ranges
from ._native_values import TOPOLOGIES, GridPort, grid_count, borrow_array as _array, borrow_text as _text, iteration_count
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
    ('widths', PreparedArray * 3), ('port', GridPort)])
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


def bootstrap_query(library):
    try:
        query = library.tpmshx_full_3d_get_bootstrap_trace_v1
    except AttributeError as exc:
        raise ValueError('native full 3D library lacks bootstrap trace v1; rebuild the library for this binding') from exc
    query.argtypes = [ct.POINTER(_Result), ct.c_size_t, ct.POINTER(_BootstrapTrace)]
    query.restype = ct.c_int
    return query


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


def run_case(case, control, *, retained_run, resume_state=None, checkpoint=None, checkpoint_due=None):
    """Select the saved 3D protocol before execution."""
    if control.backend != 'cpp':
        raise ValueError('full native 3D requires backend=cpp')
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    control.check_cancelled()
    grid_axes(case.grid)
    for side, axes in case.parameters['prepared']['axes'].items():
        if axes is not None:
            validate_axis_permutation(axes, side)
    runtime = open_library(control.native_library, getattr(control, 'native_table_directory', None))
    _, library, abi, table_directory = runtime
    saved_v2 = hasattr(library, 'tpmshx_stage_run_3d_create_saved_v2')
    saved = has_saved_stage(library)
    if saved and saved_v2:
        query = execution_view_query(library, 3, _StageResult, _ExecutionView)
        if query is not None:
            return run_saved(case, control, library, abi, table_directory, query,
                resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)
    return retained_run(case, control, runtime, saved, saved_v2,
        resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)


def validate_saved_case(case):
    if case.grid.get('dimension') != 3:
        raise ValueError('3D execution requires a prepared 3D grid')
    cfg = case.parameters
    reject_retired_research_options(cfg)
    missing = {'thermal_geometry', 'roughness_resolved', 'df_application'} - cfg.keys()
    if missing:
        raise ValueError(f'incomplete prepared 3D execution data: {sorted(missing)}')
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
    cell_mm, wall_mm = cfg['L_cell_m'] * 1e3, cfg['t_wall_m'] * 1e3
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


def pack_input(cfg, prepared, grid, design, shape, cell_mm, nu, keepalive, *, saved_v2=False):
    """Borrow contiguous arrays. Convert only when the full solver layout requires it."""
    def view(value, expected=None):
        value = np.asarray(value, dtype=np.float64)
        if expected is not None:
            value = np.broadcast_to(value, expected)
        value = np.require(value, requirements=['C', 'A'])
        keepalive.append(value)
        return _Array(value.ctypes.data_as(ct.POINTER(ct.c_double)), value.size)
    data = _Input()
    data.shape[:] = shape
    data.widths[:] = [view(grid['d'+axis]) for axis in 'xyz']
    for key, source in zip(('epsilon', 'epsilon_a', 'epsilon_b', 'permeability', 'forchheimer', 'solid_conductivity', 'cell_length'),
                           ('eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m', 'K_ss', 'L_field_m')):
        setattr(data, key, view(design[source], shape))
    thermal = cfg['thermal_geometry']
    spatial = bool(cfg.get('zone_grid_cells') or cfg.get('continuous_field'))
    geometry = thermal['fields' if spatial else 'uniform']
    data.area_density, data.hydraulic_diameter = view(geometry['A_0'], shape), view(geometry['D_h'], shape)
    data.reference_cell_length, data.reference_hydraulic_diameter = cell_mm*1e-3, prepared['geometry']['D_h']
    data.topology = TOPOLOGIES.index(cfg['tpms_type'])
    data.spatial, data.asymmetric, data.solve_b = spatial, cfg.get('delta_levelset', 0.) != 0., cfg.get('fluid_B_cfg') is not None
    for s, label in enumerate('AB'):
        a = data.sides[s];axis = prepared['axes'][label];bc = cfg['fluid_'+label+'_cfg']
        a.fluid = ('air', 'water', 'sco2', 'co2').index(cfg['fluid_type_'+label]);a.direction = 3 if bc is None else bc['dir']
        a.solver_axes[:] = [axis[key+'_real_axis'] for key in ('cross1', 'stream', 'cross2')]
        a.inlet_temperature, a.inlet_pressure, a.inlet_velocity = cfg['T_in'+label], cfg['P_in'+label], cfg['u_'+label]
        if not saved_v2 or bc is None:
            rectangles = _port_rectangles(bc, float(sum(axis['dcross2']))) if bc is not None else dict(inlet_rect=(0.,1.,0.,1.),outlet_rect=(0.,1.,0.,1.))
            a.inlet_rectangle[:], a.outlet_rectangle[:] = rectangles['inlet_rect'], rectangles['outlet_rect']
        a.inlet_opening, a.outlet_opening = (view(prepared['openings'][label][end]) for end in ('inlet', 'outlet'))
        correction = (cfg.get('df_application') or {}).get(label, {})
        a.permeability_scale, a.forchheimer_scale = correction.get('scale_K', 1.), correction.get('scale_F', 1.)
        a.dispersion = cfg.get('disp_C_'+label, 0.)
        a.sco2_nusselt_multiplier = getattr(nu, 'alpha_D' if data.topology == 0 else 'alpha_G') if nu.mode == 'experimental' else 1.
        a.heat_transfer_geometry[:] = thermal['side_geometry'][label] if data.asymmetric else (1.,1.,1.,1.)
    data.sources[:] = [view(cfg.get('mms_S_'+s+'_field', np.empty(0))) for s in ('A', 'B', 's')]
    return data


def pack_saved_v2(saved, case, cell_mm, wall_mm, nu, keepalive):
    cfg = case.parameters
    from ._native_values import buffer_scalar

    value = _SavedV2(2, ct.sizeof(_SavedV2), saved)
    pack_saved_resources(case, value.models, value.sco2_nu, value, nu, keepalive)
    value.lengths_m[:] = [cfg[key] for key in ('L', 'H', 'Lz')]
    value.design_mode = {'uniform': 0, 'xy_extruded': 1, 'continuous_xy_extruded': 1,
                         'continuous_xyz': 2}.get(case.metadata['design_mode'], 3)
    value.have_z_controls = 'n_ctrl_z' in (cfg.get('continuous_field') or {})
    nominal = (cell_mm, wall_mm, cfg['eps'])
    for index, (reference, name) in enumerate(zip(nominal, ('L_field_m', 't_field_m', 'eps_arr'))):
        scalar = buffer_scalar(reference)
        value.reference_kinds[index] = _Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))
        dtype = np.asarray(case.design_fields[name]).dtype
        value.field_kinds[index] = _Kind(dtype.itemsize * 8, 1 if dtype.kind == 'f' else 2, 2)
    for index, side in enumerate('AB'):
        record = value.axes[index]
        boundary = cfg['fluid_' + side + '_cfg']
        if boundary is not None and boundary['dir'] not in range(6):
            raise ValueError(f'prepared fluid {side} direction is invalid')
        record.port = GridPort.from_mapping(boundary)
        if not record.port.active:
            continue
        axis = cfg['prepared']['axes'][side]
        if axis['is_reverse'] not in (0, 1):
            raise ValueError(f'prepared fluid {side} reverse direction is invalid')
        if (any(value not in range(3) for value in axis['solver_to_real_perm'])
                or any(axis[name + '_real_axis'] not in range(3) for name in ('cross1', 'stream', 'cross2'))):
            raise ValueError(f'prepared fluid {side} axis permutation is invalid')
        record.reverse = axis['is_reverse']
        record.solver_to_real[:] = axis['solver_to_real_perm']
        for i, name in enumerate(('cross1', 'stream', 'cross2')):
            width = np.asarray(axis['d' + name])
            if width.ndim != 1:
                raise ValueError(f'prepared fluid {side} axis widths disagree with grid')
            record.widths[i] = _array(width, keepalive)
            record.counts[i], record.lengths[i] = grid_count(axis['N_' + name]), axis['L_' + name]
            record.solver_counts[i] = grid_count(axis['solver_init']['N' + 'xyz'[i]])
            record.solver_lengths[i] = axis['solver_init']['L' + 'xyz'[i]]
    return value


def energy_request(cfg):
    return _energy_options(cfg.get('enthalpy_algorithm', 'temperature_sou'),
                           cfg.get('enthalpy_temperature_tol_K', 1e-8))


def validate_energy_controls(cfg):
    require_h = cfg.get('require_enthalpy_update_on_temperature', False)
    if type(require_h) is not bool:
        raise ValueError('require_enthalpy_update_on_temperature must be boolean')
    strict = require_h or any(cfg.get(name) is not None for name in (
        'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol'))
    return require_h, strict


def model_h_request(cfg, strict):
    options = _iteration_options(cfg)
    if options is not None and (strict or any(cfg.get(name) is not None for name in (
            'ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega', 'ltne_enthalpy_tol'))):
        raise ValueError('model-h iteration controls cannot be combined with EOS controls')
    return options


def validate_flow_options(cfg):
    require_f2_mode(cfg.get('convergence_mode') or run_environment(cfg, 'TPMSHX_CONV_MODE', 'f2'))
    if cfg.get('use_anderson', False):
        raise ValueError('use_anderson=True in SIMPLE has been retired; disable TPMSHX_PHASE_B/use_anderson')


def _request(cfg, energy, model_h):
    request = _Request(1, ct.sizeof(_Request))
    if energy is not None:
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


def pack_run_controls(request, cfg, prepared, shape):
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
    validate_simple_velocity_relaxation(relaxation)
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


def pack_saved_case(case, data, cell_mm, wall_mm, nu, keepalive, version):
    ranges, captured = _ranges(case.metadata.get('applicability_inputs', ()), keepalive)
    notices = (_Text * len(case.metadata['notices']))(*(
        _text(notice, keepalive) for notice in case.metadata['notices']))
    evidence = _Evidence(ranges=ranges, range_count=len(ranges))
    saved = _Saved(1, ct.sizeof(_Saved), ct.pointer(data), cell_mm, wall_mm, case.parameters['eps'],
        _array(case.design_fields['t_field_m'], keepalive), evidence, notices, len(notices),
        'applicability_inputs' in case.metadata, captured)
    if version == 2:
        saved = pack_saved_v2(saved, case, cell_mm, wall_mm, nu, keepalive)
    keepalive.append(notices)
    return saved


class SavedRun(NativeRun):
    api_prefix = 'tpmshx_stage_run_3d'
    advance_name = 'advance_step'
    entry_names = {'create': 'create_saved', 'restore': 'restore_saved', 'release': 'release_run'}
    result_type = _StageResult
    result_release_name = 'tpmshx_stage_run_3d_release_v1'

    def __init__(self, library, saved, request, host, errors, state):
        self.errors = errors
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


def _model_info(r, shape, *, include_faces, capture_scalars=None):
    info = _volume_info(r, shape, include_faces=include_faces,
        cell_count=None if capture_scalars is None else capture_scalars['model_h_cell_count'])
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
            record = dict(depth=row.depth, fine_shape=tuple(row.fine_shape), coarse_shape=tuple(row.coarse_shape),
                          iteration_cap=row.iteration_cap, charged_iterations=row.charged_iterations, stop=row.stop.decode())
            record.update({key: bool(getattr(row, key)) for key in ('solve_started', 'applied', 'converged', 'child_selected')})
            trace['levels'].append(record)
        traces[label] = trace
    return traces


def require_completed(result, bootstrap_traces):
    if result.stop == 2:
        cancelled_error = CancelledError('compute cancelled by user')
        cancelled_error.coarse_bootstrap_trace = bootstrap_traces
        raise cancelled_error
    if result.stop not in (0,1):
        raise RuntimeError('invalid native full 3D exit')


def make_callbacks(control):
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
        return int(bool(callback_errors) or bool(callback(control.cancel_check) if control.cancel_check else False))
    @_Progress
    def progress(_, percent):
        callback(control.report_progress, int(percent))
    @_OuterProgress
    def outer(_, done, total):
        if control.iteration is not None:
            callback(control.iteration, f'outer {done}/{total}')
        if control.outer_iteration is not None:
            callback(control.outer_iteration, done, total)
    callbacks = _Callbacks(cancelled, progress, outer, None)
    return callbacks, callback_errors


def add_energy_evidence(detached, extra, settings, entry_version, shape, *, version_query=None, version=None):
    if detached['true_h'] is None or extra.outer_count != len(detached['outer']):
        raise RuntimeError('native full 3D energy evidence does not match the thermal history')
    _energy_result_info(detached['true_h'], extra.energy,
        temperature_tol=settings.last.temperature_update_tolerance, abi=entry_version,
        version_query=version_query, version=version, state_update='per_side_energy_relation')
    _energy_native_state(detached['true_h'], extra, shape, 'W')
    for index, row in enumerate(detached['outer']):
        _energy_result_info(row['true_h_info'], extra.outer[index],
            temperature_tol=settings.outer[index].temperature_update_tolerance, abi=entry_version,
            version_query=version_query, version=version, state_update='per_side_energy_relation')
    detached['mode'] = 'conservative_energy'


def add_run_evidence(detached, resolved, entry_version, control, cpu_thread_limit, resume_state):
    if resume_state is not None:
        detached['continuation'] = dict(format='full_3d_continuation_v1', build=resume_state['build'],
            completed_outer_steps=int(resume_state['state.result.outer.size'][0]),
            saved_phase=int(resume_state['state.phase'][0]))
    detached['simple_velocity_relaxation'] = resolved.simple.alpha_velocity
    detached['max_outer'] = resolved.max_outer
    detached['thermal_iterations'] = resolved.thermal_iterations
    budgets = {row['outer_index']: row['settings']['total_iteration_budget']
               for row in detached['model_h_iterations']['records']}
    for row in detached['outer']:
        if 'coupling_startup' in row:
            row['coupling_startup']['iteration_budget'] = budgets[row['outer']]
    detached['entry_version'] = entry_version
    if cpu_thread_limit is not None:
        detached['runtime_resources'] = dict(cpu_thread_limit=cpu_thread_limit,
            requested_cpu_threads=control.cpu_threads, policy='native_cpu_limit_v1')



def add_saved_evidence(detached, case, evidence, records, fields, shape, *, executed=None):
    from ._native_result_stage import copy_applicability

    warnings = None
    if records is not None:
        _, warnings, detached['last_closure_ranges'] = stage_closures(records)
        detached['stage_diagnostics'] = diagnostics(records, evidence, case.parameters, case.design_fields)
    if executed is not None:
        detached['execution_facts'] = execution_facts(executed, evidence, case, fields[1],
            detached['model_h_iterations'], detached['true_h'])
    elif records is not None:
        detached['_native_execution_sides'] = execution_sides(records, evidence, case, fields[1])
    detached['_native_applicability'] = copy_applicability(evidence.applicability,
        case.metadata.get('applicability_inputs', ()))
    if records is not None and 'temperature_evidence' not in detached:
        detached['physical_ledger'] = stage_ledger(evidence.thermal, None, shape)
    return warnings


def _detach(r, shape, settings, energy_settings, entry_version, *, emit_audit=False, application_only=False, capture_scalars=None, stage_fields=None, records=None):
    result = {name: getattr(r, name) if name == 'stop' else bool(getattr(r, name)) for name in _FLAGS}
    result.update({name: list(getattr(r, name)) for name in _PAIRS})
    result.update({name: getattr(r, name) for name in ('energy_imbalance', 'interior_duty', 'interior_imbalance', 'enthalpy_imbalance')})
    result['mode'], result['outer_index'] = ('temperature', 'model_h', 'true_h')[r.thermal_mode], r.thermal_outer_index
    if stage_fields is None:
        result['temperature'] = tuple(_copy(value, shape) for value in r.temperature)
    else:
        result['stage_fields'] = stage_fields
    for key in ('thermal_pressure', 'hv', 'rho_cp', 'conductivity', 'enthalpy'):
        if stage_fields is not None and key in ('thermal_pressure', 'hv'):
            continue
        if application_only and key in ('rho_cp', 'conductivity'):
            continue
        result[key] = tuple(_copy(value, shape) for value in getattr(r, key))
    if not application_only:
        result['inlet_capacity'] = tuple(_copy(value) for value in r.inlet_capacity)
    face_shapes = tuple(tuple(n+int(d==axis) for d,n in enumerate(shape)) for axis in range(3))
    for key in ('mass', 'face_velocity'):
        result[key] = tuple(tuple(_copy(value, sh) for value,sh in zip(side,face_shapes)) for side in getattr(r,key))
    result['flow'] = []
    for side, f in enumerate(r.flow):
        if not f.widths[0].size:
            result['flow'].append(None)
            continue
        flow = dict(widths=tuple(_copy(value) for value in f.widths), pressure_reference=f.pressure_reference)
        nx, ny, nz = fshape = tuple(len(w) for w in flow['widths'])
        sizes = {key:fshape for key in _FLOW_ARRAYS}
        for axis, names in enumerate((('u','d_u'),('v','d_v'),('w','d_w'))):
            for key in names:
                sizes[key] = tuple(n+int(d==axis) for d,n in enumerate(fshape))
        for key in ('inlet_velocity','inlet_opening','outlet_opening','fixed_inlet_massflux'):
            sizes[key] = (nx,nz)
        sizes['outlet_u_fraction'], sizes['outlet_w_fraction'] = (nx+1,nz),(nx,nz+1)
        for key in ('pressure_real','density_real','speed_real'):
            sizes[key] = shape
        application_arrays = ('permeability', 'forchheimer', 'pressure', 'pressure_real',
                              'speed_real', 'inlet_opening', 'outlet_opening')
        if stage_fields is not None:
            application_arrays = ('pressure', 'inlet_opening', 'outlet_opening')
            if records is None:
                application_arrays += ('permeability', 'forchheimer')
        audit_arrays = ('u', 'v', 'w', 'density', 'epsilon') if emit_audit else ()
        flow.update({key:_copy(getattr(f,key),sizes[key]) for key in _FLOW_ARRAYS
                     if not application_only or key in application_arrays + audit_arrays})
        if stage_fields is None:
            flow['velocity_real'] = tuple(_copy(value,shape) for value in f.velocity_real)
        if not application_only:
            flow['face_velocity_real'] = tuple(_copy(value,sh) for value,sh in zip(f.face_velocity_real,face_shapes))
        for key in (('legacy',) if application_only else ('legacy','local_mass','global_mass','momentum')):
            flow[key] = _copy(getattr(f,key))
        if flow.get('momentum') is not None:
            flow['momentum'] = flow['momentum'].reshape(-1,11)
        last = f.last
        pressure = {name:getattr(last.pressure,name) for name,_ in last.pressure._fields_}
        flow['last'] = dict(exit_reason=records.simple_stop[side].decode() if records is not None else _STOPS.get(last.stop,'ongoing'), converged=bool(last.converged),
            post_closure_measured=bool(last.post_closure_measured), post_closure_certified=bool(last.post_closure_certified),
            iterations=last.iterations, pressure_clip_hits=last.pressure_clip_hits, post_closure_rejections=last.post_closure_rejections,
            final_res=last.legacy_residual, res_norm_ref=last.legacy_reference,
            final_res_mom=last.momentum.maximum, final_res_mass_local=last.mass.local_residual,
            final_res_mass_global=last.mass.global_residual, outlet_backflow_frac=last.mass.backflow_fraction,
            pressure={name:value.decode() if isinstance(value,bytes) else value for name,value in pressure.items()})
        history = []
        for i in range(f.pressure_iteration_count):
            p=f.pressure_iterations[i];row=dict(stage=p.stage.decode(),anchor_Pa=p.anchor)
            for source,key in (('estimate','estimate_Pa2'),('relative_error','relative_error'),('target','target_Pa2'),('step_fraction','step_fraction')):
                if getattr(p,'has_'+source):
                    row[key]=getattr(p,source)
            if p.method:
                row['method']=p.method.decode()
            history.append(row)
        flow['pressure_iterations']=history;flow['inlet_pressure']=_pressure(f.inlet_pressure)
        if flow['inlet_pressure'] is not None:
            flow['inlet_pressure']['iterations']=history
        b=f.bootstrap
        flow['bootstrap']=None if not b.available else dict(applied=bool(b.applied),coarse_converged=bool(b.converged),
            coarse_iters=b.iterations,coarse_shape=tuple(b.shape),coarse_residual=b.residual,reason=b.reason.decode())
        result['flow'].append(flow)
    result['model_h'] = _model_info(r.model_h,shape,include_faces=True,capture_scalars=capture_scalars) if r.has_model_h else None
    result['true_h'] = _full_enthalpy_info(r.true_h,energy_settings.last,entry_version) if r.has_true_h else None
    if r.has_true_h:
        true_h=result['true_h']
        true_h['_native_state']=dict(h_A=result['enthalpy'][0],h_B=result['enthalpy'][1],
            h_in_A=r.true_h.inlet_enthalpy[0],h_in_B=r.true_h.inlet_enthalpy[1],
            mass_flux_A=result['mass'][0],mass_flux_B=result['mass'][1])
        used=[s for s,flag in zip('AB',r.true_h.used_bicubic) if flag]
        if used:
            true_h['_native_state']['enthalpy_eos']=dict(algorithm='bicubic_iteration_heos_polish_v2',
                iteration_backend='BICUBIC&HEOS',final_backend='HEOS',transport_backend='HEOS',
                coolprop_version=r.true_h.coolprop_version.decode(),sides=used,heos_polish=bool(r.true_h.heos_polish))
    result['staggered'] = []
    for p in r.staggered:
        result['staggered'].append(None if not p.available else dict(skipped=bool(p.skipped),used_bordered_lu=bool(p.used_bordered_lu),
            cg_iterations=p.cg_iterations,rhs_mean=p.rhs_mean,residual_relative=p.residual_relative,
            residual_available=bool(p.residual_available),residual_cells=_copy(p.residual_cells,shape),
            residual_sum=p.residual_sum,residual_max=p.residual_max,exchange=p.exchange,global_ratio=p.global_ratio,cell_ratio=p.cell_ratio))
    result['outer'] = []
    for i in range(r.outer_count):
        h=r.outer[i]
        row=dict(outer=h.outer_index,iters=h.thermal_iterations,residual=h.thermal_residual,converged=bool(h.thermal_converged),
                 coupling_converged=bool(h.coupling_converged),temperature_change=dict(zip(('Ta','Tb','Ts'),h.temperature_change)),
                 inlet_pressure=tuple(_pressure(p) for p in h.inlet_pressure),pressure_reference=list(h.pressure_reference),
                 pressure_range=[list(p) for p in h.pressure_range])
        if h.startup_total_iterations:
            row['coupling_startup']=dict(rejected_attempts=[dict(iterations=h.rejected_startup_iterations[k],
                reason=h.rejected_startup_reasons[k].decode()) for k in range(h.rejected_startup_count)],
                total_iterations=h.startup_total_iterations,iteration_budget=settings.thermal_iterations)
        if h.has_model_h:
            info=_model_info(h.model_h,shape,include_faces=False,capture_scalars=capture_scalars)
            row['energy_finishing_checks']=info['energy_finishing_checks']
            row['model_h_balance']=dict(info['model_h_balance'],outer_index=h.outer_index,converged=bool(h.thermal_converged),iterations=h.thermal_iterations)
        if h.has_true_h:
            row['true_h_info']=_full_enthalpy_info(h.true_h,energy_settings.outer[i],entry_version)
        result['outer'].append(row)
    result['simple_failures']=[r.simple_failures[i].decode() for i in range(r.simple_failure_count)]
    result['warnings']=[r.warnings[i].decode() for i in range(r.warning_count)]
    result['envelope_reasons']=[r.envelope_reasons[i].decode() for i in range(r.envelope_reason_count)]
    if records is None:
        result['nu_observations']={label:copy_nu_observation(n,shape,
            capture_scalars=None if capture_scalars is None else capture_scalars['nu'][side])
            for side,(label,n) in enumerate(zip('AB',r.nu_observations))}
    else:
        result['nu_observations'] = {label: nu_observation(value, shape, capture_scalars['nu'][side])
            for side, (label, value) in enumerate(zip('AB', r.nu_observations))}
    if stage_fields is None:
        result['range_observations']=copy_range_observations(r.range_observations,r.range_observation_count)
    result['final_conductivity']=tuple(_copy(v,shape) if emit_audit else None for v in r.final_conductivity)
    result['final_rho_cp']=tuple(_copy(v,shape) if emit_audit else None for v in r.final_rho_cp)
    result['inlet_cp']=list(r.inlet_cp)
    return result


def run_saved(case, control, library, abi, table_directory, execution_query, *,
              resume_state=None, checkpoint=None, checkpoint_due=None):
    """Run the current saved case with the matched stage and execution view."""
    query_bootstrap = bootstrap_query(library)
    shape, cell_mm, wall_mm, nu = validate_saved_case(case)
    cfg, prepared = case.parameters, case.parameters['prepared']
    control.check_cancelled()
    complete = getattr(library, 'tpmshx_run_saved_case_3d_v2', None)
    native_defaults = complete is not None and uses_default_thermal_recipe(cfg)
    energy = None if native_defaults else energy_request(cfg)
    has_water = 'water' in (cfg['fluid_type_A'], cfg['fluid_type_B'])
    if cfg.get('enthalpy_algorithm', 'temperature_sou') != 'temperature_sou':
        _full_enthalpy_defaults(library, 3, energy.algorithm, has_water)
    _, strict = validate_energy_controls(cfg)
    model_h = None if native_defaults else model_h_request(cfg, strict)
    request = _request(cfg, energy, model_h)
    validate_flow_options(cfg)
    keepalive = []
    data = pack_input(cfg, prepared, case.grid, case.design_fields, shape, cell_mm, nu,
                      keepalive, saved_v2=True)
    pack_run_controls(request, cfg, prepared, shape)
    callbacks, errors = make_callbacks(control)
    cpu_threads = control.native_cpu_threads()
    host = _Host(case.case_id.encode(), table_directory, cpu_threads, callbacks)
    result = None
    try:
        saved = pack_saved_case(case, data, cell_mm, wall_mm, nu, keepalive, 2)
        if complete is not None and checkpoint is None and resume_state is None:
            complete.argtypes = [ct.POINTER(_SavedV2), ct.POINTER(_Request), ct.POINTER(_Host),
                                 ct.POINTER(_StageResult), ct.POINTER(ct.c_char), ct.c_size_t]
            complete.restype = ct.c_int
            result = _StageResult()
            error = ct.create_string_buffer(2048)
            code = complete(ct.byref(saved), ct.byref(request), ct.byref(host), ct.byref(result), error, len(error))
            if errors:
                raise errors[0]
            if code:
                raise SavedRun.error_types.get(code, RuntimeError)(error.value.decode())
        else:
            with SavedRun(library, saved, request, host, errors, resume_state) as run:
                run.finish(checkpoint, checkpoint_due, (1, 2, 6, 7, 8, 9, 10))
                result = run.take_result()
        bootstrap = bootstrap_traces(query_bootstrap, result.raw)
        require_completed(result.raw, bootstrap)
        summary = copy_summary(library, result, emit_audit=bool(cfg.get('_emit_audit', False)), copy_array=_copy)
        execution = executed_view(execution_query, result)
        settings, executed, evidence = execution.settings, execution.execution, result.evidence
        if settings.outer_count != result.raw.outer_count:
            raise RuntimeError('native full 3D effective settings do not match the thermal history')
        records = executed.records.contents
        fields = detach_stage_fields(evidence, shape, prepared_fields={'K_ss': np.asarray(case.design_fields['K_ss'])})
        # Keep the complete-driver version used in published full_3d_v5 result records.
        entry_version = 5
        detached = _detach(result.raw, shape, result.resolved, settings, entry_version,
                           emit_audit=bool(cfg.get('_emit_audit', False)), application_only=True,
                           capture_scalars=summary, stage_fields=fields, records=records)
        if settings.last.available:
            version = evidence.thermal.true_h.contents.energy_algorithm_version[0]
            add_energy_evidence(detached, execution.energy, settings, entry_version, shape, version=version)
        detached['property_sampling'] = sampling_records(records.sampling)
        detached['enthalpy_update_normalization'] = _decode_update_scale(executed.update_scale)
        detached['model_h_iterations'] = _decode_iteration_records(executed.model_h, executed.acceleration)
        add_run_evidence(detached, result.resolved, entry_version, control, cpu_threads, resume_state)
        if detached['mode'] in ('model_h', 'temperature'):
            if evidence.thermal.temperature:
                detached['temperature_evidence'] = stage_ledger(evidence.thermal, records.temperature[0], shape)
            detached['native_metadata'] = dict(abi=abi, algorithm=executed.algorithm.decode(),
                                               red_black=bool(executed.red_black))
        detached['_input_resolution'] = executed_inputs(case, evidence)
        warnings = add_saved_evidence(detached, case, evidence, records, fields, shape, executed=executed)
        detached.update(capture_scalars=summary, bootstrap_trace=bootstrap)
        merge_warnings(current_warnings(), [warnings])
        replay_sco2_notices(executed.sco2_notices, '3D h_v property refresh')
    finally:
        if result is not None:
            release_result(library, result)
    control.check_cancelled()
    return capture_result(case, cfg, prepared, detached, abi)


def capture_result(case, cfg, p, r, abi, *, legacy_fields=None, legacy_drag=None, legacy_ratios=None, legacy_taper=None):
    scalars = r.get('capture_scalars')
    if 'stage_fields' in r:
        fields, field_metadata = r['stage_fields']
    else:
        fields, field_metadata = legacy_fields(case, p, r)
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
        df_metadata = legacy_drag(cfg, p, r)
        strict = legacy_ratios(r)
    else:
        df_metadata, strict = captured['df_metadata'], captured['strict_ratios']
    model_h_calls=r['model_h_iterations']['records']
    thermal_budget=(model_h_calls[-1]['settings']['total_iteration_budget'] if model_h_calls else r['thermal_iterations'])
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
        _max_outer=r['max_outer'],_ltne_max_iter=thermal_budget,
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
                outlet_coeff=outlet_coeff*legacy_taper(*outlet_coeff.shape)
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
    backend_version = f"full_3d_v{r['entry_version']}"
    metadata = dict(**({'continuation':r['continuation']} if 'continuation' in r else {}),
        **({'runtime_resources':r['runtime_resources']} if 'runtime_resources' in r else {}),
        _last_closure_ranges=r['last_closure_ranges'],dimension=3,quantity_basis='total',thermal_mode=r['mode'],parameters=case.parameters,design_fields=case.design_fields,
        **({'temperature_transport':r['temperature_evidence']['definition']} if 'temperature_evidence' in r else {}),
        input_resolution=r['_input_resolution'] if '_input_resolution' in r else cfg['_input_resolution'], property_sampling=r['property_sampling'],
        enthalpy_update_normalization=r['enthalpy_update_normalization'],
        simple_velocity_relaxation=r['simple_velocity_relaxation'],
        model_h_iterations=r['model_h_iterations'],
        design_mode=case.metadata['design_mode'],model_metadata=model_metadata,notices=case.metadata['notices'],
        application=dict(coeffs=dict(K_ffA=r['final_conductivity'][0],K_ffB=r['final_conductivity'][1],
            K_ss=fields['K_ss'] if emit_audit else None),
            props=dict(rho_cp_A=r['final_rho_cp'][0],rho_cp_B=r['final_rho_cp'][1],u_A_in_mps=cfg['u_A'],T_in_A_K=cfg['T_inA'])),
        **({'native':r['native_metadata']} if 'native_metadata' in r else {}),
        **{key: r[key] for key in ('_native_applicability', '_native_execution_sides') if key in r},
        diagnostics=diagnostics,df_metadata=df_metadata,model_roles=case.metadata['model_roles'],
        reporting_reference={key:diagnostics[key] for key in ('Q','dP_A','dP_B','T_out_A','T_out_B')})
    if 'execution_facts' in r:
        metadata['execution_record'] = execution_record('cpp', backend_version, metadata,
            roles=case.metadata['model_roles'], **r['execution_facts'])
    return FieldResult(result_id=str(uuid4()),case_id=case.case_id,backend_id='cpp',backend_version=backend_version,grid=case.grid,
        fields=fields,field_metadata=field_metadata,model_refs=case.model_refs,
        boundary_fluxes=dict(mass_A=None if mass[0][0] is None else mass[0],mass_B=None if mass[1][0] is None else mass[1],
            mass_unit='kg/s',mass_axes=('x-face','y-face','z-face'),mass_sign='positive along physical coordinate axis',state='last thermal input',
            model_h=None if r['model_h'] is None else r['model_h']['_native_model_h'],true_h=true_h,report=report,
            energy=r.get('physical_ledger'),
            face_velocity_A=r['face_velocity'][0],face_velocity_B=r['face_velocity'][1] if r['flow'][1] else None,
            **({'temperature':r['temperature_evidence']} if 'temperature_evidence' in r else {})),
        pressure_evidence=pressure,run_status=dict(execution='completed',converged=r['converged'],outer_index=r['outer_index']),
        metadata=metadata)
