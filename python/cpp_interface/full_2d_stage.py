"""Bind validated saved 2D inputs to the native run and capture lifecycle."""
import ctypes as ct
from pathlib import Path

import numpy as np

from sjtu_tpmshx.run_control.cancellation import CancelledError
from ._native_preparation_case import _Array, _Nu, _Result as _PreparedCase2D, _Text
from ._native_result_stage import Evidence, _zone_temperatures, record
from ._native_values import TOPOLOGIES, borrow_array, borrow_text, real_scalar
from .preparation_host import borrow_ranges, borrow_solver_mesh, pack_saved_resources
from .run_state import NativeRun
from .solver_library import stage_capture
from .solver_library._full_2d_abi import (
    _Callbacks,
    _Cancel,
    _Config,
    _EnergyControl,
    _EnergyEvidence,
    _FINE_FLAGS,
    _FLAGS,
    _FLOW_ARRAYS,
    _FlowMethod,
    _Pressure,
    _Progress,
    _Residual,
    _Result,
    _result_dict,
)
from .solver_library._stage_capture_abi import (
    StageExecution,
    _energy_native_state,
    _energy_result_info,
    _executed_energy_settings,
    _full_enthalpy_info,
    _plane_info,
)
from .solver_library._thermal_abi import (
    _EnergyOptions,
    _FullEnergyEffectiveSettings,
    _IterationOptions,
    _energy_options,
    _full_enthalpy_defaults,
    _iteration_options,
)
from .solver_library.stage_capture import (
    _stage_array,
    completed_report,
    detach_stage_fields,
    executed_view,
    execution_view_query,
    nu_observation,
    stage_ledger,
)

__all__ = [
    'StageDriver',
    'borrow_mesh',
    'stage_entries',
    'check_experiment',
    'run_stage',
    'zone_temperatures',
]

_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Size = record('SizeOption', [('present', _U), ('value', _S)])
_Double = record('DoubleOption', [('present', _U), ('value', _D)])
_Request = record('RunRequestV4', [('abi_version', _U), ('struct_size', _S),
    ('max_iter_simple', _Size), ('max_outer_ltne', _Size),
    *[(key, _Double) for key in ('outer_tol_K', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K')],
    ('have_pressure_shooting', _U), ('pressure_shooting', _U),
    ('convergence_mode', ct.c_char_p), ('envelope_mode', ct.c_char_p),
    ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('explicit_energy', ct.POINTER(_EnergyControl)),
    ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *[(key, _Double) for key in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')],
    ('require_enthalpy_update_on_temperature', _U)])
_Control = record('StageControl', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _S), ('callbacks', _Callbacks)])
_FlowGrid = record('SavedFlowGrid2D', [('cross', _Array), ('stream', _Array),
    ('direction', _U), ('bounds', _D * 4)])
_DesignField = record('SavedDesignField2D', [('name', _Text), ('values', _Array)])
_Experiment = record('SavedExperiment2D', [('topology', _U), ('geometry_mode', _U), ('domain_count', _U),
    ('fluids', _U * 2), ('configured_flow', _U * 2), ('domain_m', _D * 3),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D), ('delta_levelset', _D), ('velocity_m_s', _D * 2)])
_Saved = record('SavedCaseV5', [('abi_version', _U), ('struct_size', _S),
    ('prepared', ct.POINTER(_PreparedCase2D)), ('area_density_per_m', _Array),
    ('hydraulic_diameter_m', _Array), ('fluid_conductivity', _Array * 2),
    ('inlet_recorded', _U), ('range_captured', ct.POINTER(_U)),
    ('have_side_geometry', _U), ('side_geometry', (_D * 4) * 2),
    ('lengths_m', _D * 2), ('flow_grid', _FlowGrid * 2),
    ('resource_fluids', _Text * 2), ('resource_topology', _Text), ('resource_nu', _Nu * 2),
    ('additional_fields', ct.POINTER(_DesignField)), ('additional_count', _S),
    ('experiment', _Experiment)])


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', _U), ('struct_size', _S), ('owner', ct.c_void_p),
               ('raw', _Result), ('evidence', Evidence), ('resolved', _Config)]

    def __init__(self):
        super().__init__(1, ct.sizeof(type(self)))


_ExecutionView = record('ExecutionView2D', [('execution', StageExecution),
    ('settings', _FullEnergyEffectiveSettings), ('energy', _EnergyEvidence)])

_Application = record('CaptureApplication', [
    ('area_density_per_m', _D * 2), ('surface_htc_W_m2K', _D * 2)])
_Summary = record('CaptureSummary', [
    ('model_h_available', _U * 2), ('nu_available', _U * 2), ('pressure_available', _U),
    ('model_h_cell_count', _S * 2), ('model_h_area_m2', _D * 2),
    ('nu_floor', _D * 2), ('nu_floor_fraction', _D * 2),
    ('pressure_min_Pa', _D * 2), ('pressure_max_Pa', _D * 2),
    ('q_net', _D), ('absolute_duty', _D * 2), ('application_hv', _D * 2),
    ('pressure_clip_hits', _S), ('have_finite_duty', _U), ('red_black', _U * 2)])


def borrow_mesh(case, library):
    return borrow_solver_mesh(case, library, 2)


def zone_temperatures(widths, temperatures, zone_id, zones, lengths, fractions, *, solver_library=None):
    """Query native 2D zone temperature statistics while keeping caller warning provenance."""
    return _zone_temperatures(
        widths, temperatures, zone_id, zones, lengths, fractions,
        solver_library=solver_library, stacklevel=5)


def pack_saved_design(case, uniform, saved, keepalive):
    shape = uniform.nx, uniform.ny
    canonical = ('L_field_m', 't_field_m', 'eps_arr', 'K_ss_arr', 'r_h_arr')
    native_names = ('cell_length', 'wall_thickness', 'total_porosity', 'solid_conductivity', 'hydraulic_radius')
    extra = []
    for name, field in case.design_fields.items():
        if name not in canonical and not (isinstance(field, np.ndarray) and field.ndim == 2):
            continue
        if np.shape(field) != shape:
            raise ValueError(f'prepared design field {name} does not match the physical grid')
        if name in canonical:
            index = canonical.index(name)
            if not getattr(uniform, native_names[index]).size:
                setattr(uniform, native_names[index], borrow_array(field, keepalive))
        else:
            extra.append(_DesignField(borrow_text(name, keepalive), borrow_array(field, keepalive)))
    saved.additional_fields = storage = (_DesignField * len(extra))(*extra)
    keepalive.append(storage)
    saved.additional_count = len(extra)
    uniform.hydraulic_radius_m = case.parameters['r_h']
    uniform.epsilon = case.parameters['eps']


def _run_settings(cfg):
    settings = cfg['compute_cfg']
    return settings if isinstance(settings, dict) else vars(settings)


def prepare_stage(case, cfg, prepared, saved_flow_grid):
    """Keep the borrowed case fields alive until the native result is captured."""
    settings = _run_settings(cfg)
    uniform = _PreparedCase2D(1, ct.sizeof(_PreparedCase2D))
    keepalive = [uniform]
    uniform.input.abi_version, uniform.input.struct_size = 1, ct.sizeof(uniform.input)
    uniform.input.topology = TOPOLOGIES.index(cfg['tpms_type'])
    uniform.input.geometry_mode = (0 if cfg['za'] is None else 1 if cfg['z_axis'] == 'continuous' else 2)
    uniform.input.delta_levelset = settings['geometry'].delta_levelset
    uniform.input.df_mode = ('cfd_smooth', 'experimental').index(settings['df_mode'])
    mesh = prepared.get('solver_mesh')
    if mesh is None:
        uniform.dx = borrow_array(prepared['energy_dx'], keepalive)
        uniform.dy = borrow_array(prepared['energy_dy'], keepalive)
    else:
        keepalive.append(mesh)
        uniform.dx, uniform.dy = mesh.solver_widths[:2]
    uniform.nx, uniform.ny = uniform.dx.size, uniform.dy.size
    uniform.cell_length_m = real_scalar(case.parameters['L_cell_m'], name='L_cell_m')
    uniform.wall_thickness_m = real_scalar(case.parameters['t_wall_m'], name='t_wall_m')
    uniform.epsilon = cfg['eps']
    uniform.total_porosity = borrow_array(case.design_fields['eps_arr'], keepalive)
    uniform.solid_conductivity = borrow_array(case.design_fields['K_ss_arr'], keepalive)
    geometry = cfg['thermal_geometry']
    uniform.split_a = geometry['split_A']
    uniform.area_density_per_m = geometry['uniform']['A_0']
    uniform.hydraulic_diameter_m = geometry['uniform']['D_h']
    area, diameter = _Array(), _Array()
    selected_geometry = geometry['uniform'] if geometry['fields'] is None else geometry['fields']
    if geometry['fields'] is not None:
        if mesh is None:
            area = borrow_array(geometry['fields']['A_0'], keepalive)
            diameter = borrow_array(selected_geometry['D_h'], keepalive)
        else:
            area, diameter = mesh.solver_area, mesh.solver_diameter
    conductivity = (_Array(), _Array())
    if uniform.input.geometry_mode:
        uniform.cell_length = borrow_array(case.design_fields['L_field_m'], keepalive)
        conductivity = tuple([borrow_array(cfg['za']['K_ff' + side + '_arr'], keepalive) for side in 'AB'])
    nu = settings['sco2_nu']
    uniform.sco2_nu.mode = nu.mode != 'cfd_smooth'
    if uniform.sco2_nu.mode:
        uniform.sco2_nu.alpha[:] = (nu.alpha_D, nu.alpha_G)
    for index, side in enumerate('AB'):
        flow, opening, port = cfg['flow_inputs'][side], cfg['boundary_openings'][side], cfg['cfg' + side]
        target = uniform.sides[index]
        target.inlet.fluid = ('air', 'water', 'sco2', 'co2').index(cfg['fluid_' + side])
        target.inlet.temperature_K = cfg['T_in' + side]
        target.inlet.pressure_Pa = settings['fluid_' + side].P_in_Pa
        target.inlet.velocity_m_s = cfg['u_' + side]
        target.inlet.port.direction = cfg['dir_' + side]
        target.inlet.port.uniform_inlet = int(port.get('uniform_inlet_2d', False))
        target.inlet_bounds[:] = (port['in_ctr'] - port['in_w'] / 2, port['in_ctr'] + port['in_w'] / 2)
        target.outlet_bounds[:] = (port['out_ctr'] - port['out_w'] / 2, port['out_ctr'] + port['out_w'] / 2)
        properties = cfg['static_properties'][side]
        target.properties.mu = properties['mu']
        if not uniform.input.geometry_mode:
            target.properties.fluid_conductivity_W_mK = properties['K_ff']
        cross, stream = (uniform.ny, uniform.nx) if port['dir'] in (0, 1) else (uniform.nx, uniform.ny)
        for key in ('K_m2', 'cF_per_m'):
            if np.shape(flow[key]) != (stream,):
                raise ValueError(f'invalid prepared flow {side} {key}')
        for key in ('seed_K_m2', 'seed_cF_per_m'):
            if not np.isscalar(flow[key]):
                raise ValueError(f'invalid prepared flow {side} {key}')
        if cfg['z_axis'] == 'continuous':
            for key in ('K_field_m2', 'cF_field_per_m'):
                if np.shape(flow.get(key)) != (cross, stream):
                    raise ValueError(f'invalid prepared local flow {side} {key}')
        target.seed_permeability_m2, target.seed_forchheimer_per_m = flow['seed_K_m2'], flow['seed_cF_per_m']
        target.row_permeability = borrow_array(flow['K_m2'], keepalive)
        target.row_forchheimer = borrow_array(flow['cF_per_m'], keepalive)
        for name, key in (('permeability', 'K_field_m2'), ('forchheimer', 'cF_field_per_m')):
            if key in flow:
                setattr(target, name, borrow_array(flow[key], keepalive))
        for name, key in (('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'),
                          ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac')):
            setattr(target, name, borrow_array(opening[key], keepalive))
        # The native saved run computes the staggered outlet fraction from this grid.
        grid = saved_flow_grid[index]
        grid.direction = port['dir']
        cross_axis = np.asarray(flow['dx'])
        stream_axis = np.asarray(flow['dy'])
        if any([axis.ndim != 1 or axis.dtype.kind not in 'fiu' for axis in (cross_axis, stream_axis)]):
            raise ValueError(f'prepared flow {side} grid disagrees with the thermal grid')
        grid.cross = borrow_array(cross_axis, keepalive)
        grid.stream = borrow_array(stream_axis, keepalive)
        for end, prefix in enumerate(('in', 'out')):
            center, half = port[prefix + '_ctr'], port[prefix + '_w'] / 2
            grid.bounds[2*end] = real_scalar(center - half, allow_nonfinite=True)
            grid.bounds[2*end+1] = real_scalar(center + half, allow_nonfinite=True)
        for name in ('in_geom_frac', 'out_geom_frac', 'in_profile_frac', 'out_profile_frac'):
            if np.ndim(opening[name]) != 1:
                raise ValueError(f'prepared Fluid {side} {name} disagrees with its grid and port geometry')
    ranges, captured = borrow_ranges(case.metadata.get('applicability_inputs', ()), keepalive)
    uniform.ranges, uniform.range_count = ranges, len(ranges)
    notice_items = [borrow_text(notice, keepalive) for notice in case.metadata['notices']]
    notices = (_Text * len(notice_items))(*notice_items)
    keepalive.append(notices)
    uniform.notices, uniform.notice_count = notices, len(notices)
    return uniform, area, diameter, conductivity, 'applicability_inputs' in case.metadata, captured, keepalive


def _experiment_request(settings):
    geometry, zones = settings['geometry'], settings['zones']
    depth = geometry.Lz_m if settings['solver'].Nz >= 2 else None
    fluids = settings['fluid_A'], settings['fluid_B']
    packed = _Experiment()
    packed.topology = TOPOLOGIES.index(geometry.tpms)
    packed.geometry_mode = (1 if zones.axis == 'continuous' else 2) if zones.enabled else 0
    packed.domain_count = 2 if depth is None else 3
    packed.domain_m[:] = geometry.L_dom_m, geometry.H_dom_m, depth or 0.
    packed.cell_length_mm, packed.wall_thickness_mm = geometry.L_cell_mm, geometry.t_wall_mm
    packed.delta_levelset = geometry.delta_levelset
    for index, fluid in enumerate(fluids):
        packed.fluids[index] = ('air', 'water', 'sco2', 'co2').index(fluid.type)
        packed.configured_flow[index] = fluid.mass_flow_kg_s is not None
        if not packed.configured_flow[index]:
            packed.velocity_m_s[index] = fluid.u_mps
    return packed


def _raise_stage_error(code, error, error_types):
    message = error.value.decode()
    if code in (7, 8):
        reason = ValueError(message.partition(': ')[2])
        if code == 8:
            reason.__cause__ = ValueError('HX velocity outside application window')
        raise ValueError(message) from reason
    raise error_types.get(code, RuntimeError)(message)


def check_experiment(entries, settings, error_types):
    """Validate experimental D-F applicability with the solver library."""
    experiment = _experiment_request(settings)
    error = ct.create_string_buffer(2048)
    status = entries['check_experiment'](ct.byref(experiment), error, len(error))
    if status:
        _raise_stage_error(status, error, error_types)


def _request(cfg, library, resolve_controls):
    solver = _run_settings(cfg)['solver']
    request = _Request(4, ct.sizeof(_Request))
    for name in ('max_iter_simple', 'max_outer_ltne'):
        value = getattr(solver, name)
        setattr(request, name, _Size(bool(value), value or 0))
    value = solver.outer_tol_K
    request.outer_tol_K = _Double(bool(value), value or 0.)
    mode, tolerances, pressure_shooting, envelope_mode = resolve_controls(cfg, solver)
    request.convergence_mode = mode.encode()
    for name, tolerance in tolerances.items():
        setattr(request, name, _Double(1, tolerance))
    if solver.simple_velocity_relaxation is not None:
        request.simple_velocity_relaxation = _Double(1, solver.simple_velocity_relaxation)
    if cfg.get('T_s_init') is not None:
        request.solid_seed_K = _Double(1, cfg['T_s_init'])
    request.have_pressure_shooting = 1
    request.pressure_shooting = pressure_shooting
    request.envelope_mode = envelope_mode.encode()
    energy = _energy_options(solver.enthalpy_algorithm, solver.enthalpy_temperature_tol_K)
    has_water = 'water' in (cfg['fluid_A'], cfg['fluid_B'])
    if solver.enthalpy_algorithm != 'temperature_sou':
        _full_enthalpy_defaults(library, 2, energy.algorithm, has_water)
    model_h = _iteration_options(vars(solver))
    if model_h is not None:
        request.model_h = model_h
    else:
        request.energy = ct.pointer(energy)
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
    creation_version = 5
    result_type = _StageResult
    result_release_name = 'tpmshx_stage_run_2d_release_v1'

    def __init__(self, library, saved, request, control, errors, state, error_types):
        self.errors = errors
        self.creation_version = saved.abi_version
        common = [ct.POINTER(type(saved)), ct.POINTER(_Request), ct.POINTER(_Control)]
        super().__init__(
            library, common, [ct.byref(saved), ct.byref(request), ct.byref(control)],
            control, state, error_types=error_types)

    def _call(self, function, *args):
        error = ct.create_string_buffer(2048)
        code = function(*args, error, len(error))
        if self.errors:
            raise self.errors[0]
        if code:
            _raise_stage_error(code, error, self.error_types)


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


def stage_entries(library):
    """Bind the saved v5 lifecycle. A library without it is a deployment error."""
    try:
        version = library.tpmshx_stage_run_2d_abi_version
        entries = dict(release=library.tpmshx_stage_run_2d_release_v1, query=library.tpmshx_stage_run_2d_get_capture_v1,
                       complete=library.tpmshx_run_saved_case_2d_v5,
                       check_experiment=library.tpmshx_stage_run_2d_check_experiment_v4,
                       port_windows_fit=library.tpmshx_stage_port_windows_fit_2d_v1)
    except AttributeError as error:
        raise ValueError('native library has an incomplete saved 2D stage protocol') from error
    version.argtypes, version.restype = [], _U
    abi = version()
    if abi != 5:
        raise ValueError(f'unsupported saved 2D stage ABI {abi}; expected 5')
    entries['release'].argtypes, entries['release'].restype = [ct.POINTER(_StageResult)], None
    entries['query'].argtypes = [ct.POINTER(_StageResult), ct.POINTER(_Application), ct.POINTER(_Summary)]
    entries['query'].restype = ct.c_int
    entries['complete'].argtypes = [ct.POINTER(_Saved), ct.POINTER(_Request), ct.POINTER(_Control),
                                    ct.POINTER(_StageResult), ct.POINTER(ct.c_char), _S]
    entries['complete'].restype = ct.c_int
    entries['check_experiment'].argtypes = [ct.POINTER(_Experiment), ct.POINTER(ct.c_char), _S]
    entries['check_experiment'].restype = ct.c_int
    entries['port_windows_fit'].argtypes, entries['port_windows_fit'].restype = [ct.c_double] * 5, ct.c_int
    return entries


def pack_saved(case, cfg, prepared, experiment_spec):
    """Pack the saved v5 case. The caller keeps the returned owners alive during the run."""
    flow_grid = (_FlowGrid * 2)()
    uniform, area, diameter, conductivity, recorded, captured, keepalive = prepare_stage(
        case, cfg, prepared, flow_grid)
    sides = cfg['thermal_geometry']['side_geometry']
    saved = _Saved(5, ct.sizeof(_Saved), ct.pointer(uniform), area, diameter,
                   (_Array * 2)(*conductivity), recorded, captured, sides is not None)
    if sides is not None:
        for index, side in enumerate('AB'):
            saved.side_geometry[index][:] = sides[side]
    saved.lengths_m[:] = (cfg['L'], cfg['H'])
    saved.flow_grid = flow_grid
    pack_saved_design(case, uniform, saved, keepalive)
    pack_saved_resources(case, uniform.models, uniform.sco2_nu, saved, _run_settings(cfg)['sco2_nu'], keepalive)
    saved.experiment = _Experiment() if experiment_spec is None else _experiment_request(experiment_spec)
    return saved, uniform, keepalive


def run_stage(driver, case, cfg, prepared, control, entries, experiment_spec, *,
              resolve_controls, error_types, resume_state=None, checkpoint=None, checkpoint_due=None):
    """Run the saved 2D stage and detach every native output before release."""
    library = driver.library
    release, query = entries['release'], entries['query']
    control.check_cancelled()
    saved, uniform, keepalive = pack_saved(case, cfg, prepared, experiment_spec)
    request, energy = _request(cfg, library, resolve_controls)
    keepalive.append(energy)
    callbacks, errors = _callbacks(control)
    keepalive.append(callbacks)
    stage_control = _Control(case.case_id.encode(), driver.table_directory, control.native_cpu_threads(), callbacks)
    result = _StageResult()
    try:
        if checkpoint is None and resume_state is None:
            error = ct.create_string_buffer(2048)
            code = entries['complete'](ct.byref(saved), ct.byref(request), ct.byref(stage_control),
                                       ct.byref(result), error, len(error))
            if errors:
                raise errors[0]
            if code:
                _raise_stage_error(code, error, error_types)
        else:
            with _Run(library, saved, request, stage_control, errors, resume_state, error_types) as run:
                run.finish(checkpoint, checkpoint_due, (1, 2, 6, 7, 8))
                result = run.take_result()
        report = completed_report(library, result)
        summary = _Summary()
        if query(ct.byref(result), ct.byref(_Application()), ct.byref(summary)):
            raise RuntimeError('native full 2D capture query failed')
        shape = (uniform.nx, uniform.ny)
        fields, declarations = detach_stage_fields(result.evidence, shape)
        # The Python result preserves its published field order.
        names = ('Ta', 'Tb', 'Ts', 'P_thermal_A', 'P_thermal_B', 'P_report_A', 'P_report_B',
                 'h_vA', 'h_vB', 'K_ss', 'Ta_display', 'Tb_display', 'Ts_display',
                 'P_fA_display', 'ucA', 'vcA', 'P_fB_display', 'ucB', 'vcB')
        stage_fields = {key: fields[key] for key in names}, {key: declarations[key] for key in names}
        execution = executed_view(driver.execution_query, result)
        records = execution.execution.records.contents
        native = driver.copy_result(result.raw, shape, result.resolved,
            entry_version=6, control=control, cpu_thread_limit=stage_control.cpu_threads,
            resume_state=resume_state, capture_scalars=_scalars(summary), fields=stage_fields[0],
            records=records, evidence=result.evidence, execution=execution, report=report)
        native['sco2_notices'] = tuple([
            None if raw is None else bytes(raw) for raw in execution.execution.sco2_notices])
        control.check_cancelled()
        native['_native_applicability'] = stage_capture.copy_applicability(
            result.evidence.applicability, case.metadata.get('applicability_inputs', ()))
        properties = cfg['static_properties']
        application_hv = []
        for side in 'AB':
            area_density = properties[side]['A_0']
            surface_htc = properties[side]['H_sf']
            if area_density < 0 or surface_htc < 0:
                raise ValueError(f'A_0={area_density}, H_sf={surface_htc} must both be >= 0')
            application = _Application((_D * 2)(float(area_density), 0.), (_D * 2)(float(surface_htc), 0.))
            values = _Summary()
            if query(ct.byref(result), ct.byref(application), ct.byref(values)):
                raise RuntimeError('native full 2D application capture query failed')
            application_hv.append(values.application_hv[0])
        return native, stage_fields, report, tuple(application_hv)
    finally:
        if result.owner:
            release(ct.byref(result))
        del keepalive


def _copy(view, shape=None):
    if not view.size:
        return None
    value = np.ctypeslib.as_array(view.data, (view.size,)).copy()
    return value if shape is None else value.reshape(shape)


def _flow(f, physical_shape, fields, label, stop):
    nx, ny = f.dx.size, f.dy.size
    out = {}
    names = ('pressure', 'absolute_pressure', 'uc', 'vc') if stop else _FLOW_ARRAYS
    for name in names:
        shape = (nx+1, ny) if name in ('u', 'd_u') else (nx, ny+1) if name in ('v', 'd_v') else (nx, ny)
        if name in ('dx', 'dy', 'inlet_velocity'):
            shape = None
        elif name in ('uc', 'vc', 'absolute_pressure'):
            shape = physical_shape
        elif name in ('mass_x', 'mass_y'):
            shape = tuple([n + int(axis == (name == 'mass_y')) for axis, n in enumerate(physical_shape)])
        if fields is not None and name in ('absolute_pressure', 'uc', 'vc'):
            out[name] = fields[('P_report_' if name == 'absolute_pressure' else name) + label]
        else:
            out[name] = _copy(getattr(f, name), shape)
    out.update(reference_pressure=f.reference_pressure, taper_flux_scale=f.taper_flux_scale,
        result=(dict(exit_reason=stop.decode(), converged=bool(f.result.converged), iterations=f.result.iterations,
                     momentum=dict(maximum=f.result.momentum.maximum),
                     mass=dict(local_residual=f.result.mass.local_residual, global_residual=f.result.mass.global_residual))
                if stop else _result_dict(f.result, 1)),
        history={name: _copy(value, (-1, 8) if name == 'momentum' else None)
                 for name, value in zip(('legacy', 'local_mass', 'global_mass', 'momentum'), f.history)
                 if not stop or name == 'legacy'},
        envelope_valid=bool(f.envelope_valid),
        envelope_reasons=[f.envelope_reasons[i].decode() for i in range(f.envelope_reason_count)])
    iterations = []
    for i in range(f.pressure_iteration_count):
        p = f.pressure_iterations[i]
        row = dict(stage=p.stage.decode(), anchor_Pa=p.anchor_Pa)
        for flag, name in zip(('have_estimate', 'have_relative_error', 'have_target', 'have_step'),
                              ('estimate_Pa2', 'relative_error', 'target_Pa2', 'step_fraction')):
            if getattr(p, flag):
                row[name] = getattr(p, name)
        if p.method:
            row['method'] = p.method.decode()
        iterations.append(row)
    out['pressure_iterations'] = iterations
    p = f.inlet_pressure
    out['inlet_pressure'] = None
    if p.available:
        out['inlet_pressure'] = {name: getattr(p, name) for name, _ in _Pressure._fields_[2:-1]}
        out['inlet_pressure'].update(passed=bool(p.passed), definition=p.definition.decode(), iterations=iterations)
    return out


def _thermal(t, actual, abi, *, capture_scalars=None, level=0, fields=None, balance=None):
    shape = (t.nx, t.ny)
    out = dict(shape=shape, mode=('temperature', 'model_h', 'true_h')[t.mode], stop=t.stop,
               iterations=t.iterations, residual=t.residual, q_b=t.q_b)
    for name in ('dx', 'dy', 'epsilon', 'solid_conductivity'):
        if fields is not None and name == 'solid_conductivity':
            out[name] = fields['K_ss']
        else:
            out[name] = _copy(getattr(t, name), shape if name not in ('dx', 'dy') else None)
    for name in ('temperature', 'hv', 'conductivity', 'pressure', 'rho_cp', 'enthalpy', 'uc', 'vc',
                 'mass_x', 'mass_y', 'inlet_capacity', 'inlet_profile', 'outlet_profile'):
        extent = shape
        if name in ('mass_x', 'mass_y'):
            extent = tuple([n + int(axis == (name == 'mass_y')) for axis, n in enumerate(shape)])
        elif name in ('inlet_capacity', 'inlet_profile', 'outlet_profile'):
            extent = None
        if fields is not None and name in ('temperature', 'hv', 'pressure'):
            keys = {'temperature': ('Ta', 'Tb', 'Ts'), 'hv': ('h_vA', 'h_vB'),
                    'pressure': ('P_thermal_A', 'P_thermal_B')}[name]
            out[name] = [fields[key] for key in keys]
        else:
            out[name] = [_copy(value, extent) for value in getattr(t, name)]
    out['model_h'], out['true_h'] = None, None
    masses = list(zip(out['mass_x'], out['mass_y']))
    if t.mode == 1:
        scalar = None if capture_scalars is None else capture_scalars['model_h'][level]
        if capture_scalars is not None and scalar is None:
            raise RuntimeError('native full 2D model-h capture is unavailable')
        if balance is None:
            balance = _plane_info(t.model_h, shape, (out['dx'], out['dy']), masses, capture_scalars=scalar)
        else:
            balance.update(dx_m=out['dx'].tolist(), dy_m=out['dy'].tolist())
            for label, side, mass in zip('AB', t.model_h.plane.sides, masses):
                balance[label].update(
                    boundary_mass_out_kg_s_per_m=[_copy(x).tolist() for x in side.boundary_mass_out],
                    boundary_h_out_W_per_m=[_copy(x).tolist() for x in side.boundary_h_out],
                    mass_faces_kg_s_per_m=[x.tolist() for x in mass],
                    h_faces_W_per_m=[_copy(x, m.shape).tolist() for x, m in zip(side.h_faces, mass)],
                    inlet_conduction_faces_W_per_m=_copy(side.inlet_conduction_faces).tolist())
        out['model_h'] = balance
        out['model_h']['energy_finishing_checks'] = [dict(iterations=t.model_h.finishing_checks[i].iterations,
            passed=bool(t.model_h.finishing_checks[i].gates[0]), equations_ok=bool(t.model_h.finishing_checks[i].gates[1]))
            for i in range(t.model_h.finishing_count)]
    elif t.mode == 2:
        h = t.true_h
        out['true_h'] = _full_enthalpy_info(h, actual, abi)
        mass3 = [(*[face[..., None] for face in pair], np.zeros((*shape, 2))) for pair in masses]
        out['true_h']['_native_state'] = state = dict(h_A=out['enthalpy'][0][..., None], h_B=out['enthalpy'][1][..., None],
            h_in_A=h.inlet_enthalpy[0], h_in_B=h.inlet_enthalpy[1], mass_flux_A=mass3[0], mass_flux_B=mass3[1])
        sides = [side for side, used in zip(('A', 'B'), h.used_bicubic) if used]
        if sides:
            state['enthalpy_eos'] = dict(algorithm='bicubic_iteration_heos_polish_v2',
                iteration_backend='BICUBIC&HEOS', final_backend='HEOS', transport_backend='HEOS',
                coolprop_version=h.coolprop_version.decode(), sides=sides, heos_polish=bool(h.heos_polish))
    return out


def _set_native_metadata(result, abi, algorithm, red_black, *, captured_red_black=None):
    for level, stage in enumerate((result['main'], result['fine'])):
        if stage is not None:
            actual = stage['temperature_evidence']['algorithm'] if 'temperature_evidence' in stage else algorithm
            stage['native_metadata'] = dict(abi=abi, algorithm=actual,
                red_black=(bool(red_black and np.prod(stage['shape']) > 30000)
                           if captured_red_black is None else captured_red_black[level]))
    result['native_metadata'] = result['main']['native_metadata']


def _callbacks(control):
    errors = []

    @_Cancel
    def cancelled(_):
        if errors:
            return 1
        try:
            return int(bool(control.cancel_check())) if control.cancel_check is not None else 0
        except BaseException as error:
            errors.append(error)
            return 1

    @_Progress
    def progress(_, done, total):
        if errors:
            return
        try:
            control.report_progress(10 + int(80 * done / total))
            if control.iteration is not None:
                control.iteration(f'iter {done + 1}/{total}')
            if control.outer_iteration is not None:
                control.outer_iteration(done, total)
        except BaseException as error:
            errors.append(error)

    @_Residual
    def residual(_, side, iteration, value):
        if errors:
            return
        try:
            if control.residual is not None:
                control.residual(('A', 'B')[side], iteration, value)
        except BaseException as error:
            errors.append(error)

    return _Callbacks(cancelled, progress, residual, None), errors


class StageDriver:
    def __init__(self, library, *, table_directory=None):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native full 2D library must be an absolute path')
        self.path = path.resolve(strict=True)
        if table_directory is not None and not Path(table_directory).is_absolute():
            raise ValueError('native full 2D table directory must be an absolute path')
        self.table_directory = None if table_directory is None else str(table_directory).encode()
        self.library = ct.CDLL(str(self.path))
        version = self.library.tpmshx_full_2d_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 2:
            raise ValueError(f'unsupported full 2D ABI {self.abi}; expected 2')
        self.execution_query = execution_view_query(self.library, 2, _StageResult, _ExecutionView)
        self.query_flow_methods = self.library.tpmshx_full_2d_get_flow_methods_v1
        self.query_flow_methods.argtypes = [ct.POINTER(_Result), ct.POINTER(_FlowMethod)]
        self.query_flow_methods.restype = ct.c_int

    def copy_result(self, result, shape, config, *, entry_version, control, cpu_thread_limit, resume_state,
                    capture_scalars, fields, records, evidence, execution, report):
        """Copy the borrowed raw result views and the saved-stage execution records."""
        if result.cancelled:
            raise CancelledError('compute cancelled by user')
        actual = execution.settings
        if actual.outer_count != result.outer_history_count:
            raise RuntimeError('native full 2D effective settings do not match the thermal history')
        out = {name: bool(getattr(result, name)) for name in (*_FLAGS, *_FINE_FLAGS)}
        out.update(iterations=result.iterations, flow=[_flow(f, shape, fields, label, records.simple_stop[i])
            for i, (f, label) in enumerate(zip(result.flow, 'AB'))],
                   main=_thermal(result.main, actual.last, entry_version, capture_scalars=capture_scalars, fields=fields,
                                 balance=report['model_h'][0]),
                   fine=_thermal(result.fine, actual.last, entry_version, capture_scalars=capture_scalars, level=1,
                                 balance=report['model_h'][1])
                   if result.have_fine else None)
        out['simple_velocity_relaxation'] = config.alpha_velocity
        out.update({name: report[name] for name in ('property_sampling', 'model_h_iterations',
                                                    'enthalpy_update_normalization')})
        for name in ('fine_duty', 'extrapolated_duty', 'pressure_drop', 'outlet_temperature', 'inlet_mass', 'duty'):
            out[name] = list(getattr(result, name))
        for name in ('q_total', 'q_solid', 'energy_imbalance'):
            out[name] = getattr(result, name)
        out['range_observations'], out['range_warnings'], out['last_closure_ranges'] = stage_capture.stage_closures(records)
        out['sco2_nu_observations'] = {}
        for i, (side, value) in enumerate(zip('AB', result.nu_observations)):
            scalar = capture_scalars['nu'][i]
            if value.available and scalar is None:
                raise RuntimeError('native full 2D Nu capture is unavailable')
            out['sco2_nu_observations'][side] = nu_observation(value, shape, scalar)
        out['outer_history'] = []
        for i in range(result.outer_history_count):
            h = result.outer_history[i]
            out['outer_history'].append(dict(iteration=h.iteration, thermal_iterations=h.thermal_iterations,
                thermal_converged=bool(h.thermal_converged), outer_converged=bool(h.outer_converged),
                relative_density_change=list(h.relative_density_change), temperature_change=list(h.temperature_change)))
            if out['main']['true_h'] is not None:
                info = dict(effective_settings={})
                _executed_energy_settings(info, actual.outer[i], entry_version)
                out['outer_history'][-1]['energy_info'] = info
        if resume_state is not None:
            out['continuation'] = dict(format='full_2d_continuation_v1', build=resume_state['build'],
                completed_outer_steps=int(resume_state['state.result.outer_history.size'][0]),
                saved_phase=int(resume_state['state.phase'][0]))
        methods = (_FlowMethod*2)()
        if self.query_flow_methods(ct.byref(result), methods):
            raise RuntimeError('native full 2D flow method query failed')
        out['simple_flow'] = {side: dict(algorithm=value.algorithm.decode() if value.algorithm else None,
            iterations=value.iterations, proposal_steps=value.proposal_steps,
            accepted_proposals=value.accepted_proposals) for side, value in zip('AB', methods)}
        out['entry_version'] = entry_version
        out['runtime_resources'] = dict(cpu_thread_limit=cpu_thread_limit,
            requested_cpu_threads=control.cpu_threads, policy='native_cpu_limit_v1')
        if actual.last.available:
            extra = execution.energy
            version = evidence.thermal.true_h.contents.energy_algorithm_version[0]
            if out['main']['true_h'] is None or extra.outer_count != len(out['outer_history']):
                raise RuntimeError('native full 2D energy evidence does not match the thermal history')
            info = out['main']['true_h']
            _energy_result_info(info, extra.main.energy,
                temperature_tol=actual.last.temperature_update_tolerance, abi=entry_version,
                version=version, state_update='per_side_energy_relation')
            _energy_native_state(info, extra.main, (*shape, 1), 'W/m')
            out['main']['mode'] = 'conservative_energy'
            if out['fine'] is not None:
                raise RuntimeError('native conservative energy unexpectedly returned Richardson evidence')
            for index, row in enumerate(out['outer_history']):
                _energy_result_info(row['energy_info'], extra.outer[index],
                    temperature_tol=actual.outer[index].temperature_update_tolerance, abi=entry_version,
                    version=version)
        out['outer_index'] = evidence.outer_index[0]
        mass = []
        for side in range(2):
            faces = []
            for axis, name in enumerate(('mass_x', 'mass_y')):
                view = evidence.thermal.mass[side][axis]
                thermal_face = getattr(result.main, name)[side]
                if view.data == ct.cast(thermal_face.data, ct.c_void_p).value:
                    face = out['main'][name][side]
                else:
                    extent = tuple([n + int(i == axis) for i, n in enumerate(shape)])
                    face = _stage_array(view, extent)
                faces.append(face)
            mass.append(tuple(faces))
        out['thermal_mass'] = mass
        for index, name in enumerate(('main', 'fine')):
            level = out[name]
            if level is None:
                continue
            thermal = evidence.thermal if index == 0 else evidence.fine.contents.thermal
            key = 'temperature_evidence' if thermal.temperature else 'physical_ledger'
            level[key] = stage_ledger(thermal, records.temperature[index], level['shape'])
        if out['main']['mode'] in ('model_h', 'temperature'):
            _set_native_metadata(out, self.abi, execution.execution.algorithm.decode(), config.red_black,
                                 captured_red_black=capture_scalars['red_black'])
        out['capture_scalars'] = capture_scalars
        return out
