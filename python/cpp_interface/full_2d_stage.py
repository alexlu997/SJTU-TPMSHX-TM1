"""Run saved 2D inputs through one native lifecycle and capture owner."""
import ctypes as ct
from copy import deepcopy
from dataclasses import replace
from functools import partial
from pathlib import Path
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.cpp_interface._native_result_stage import Evidence, detach_stage_fields, record
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.data_types.compute_config import validate_simple_velocity_relaxation
from sjtu_tpmshx.run_control.run_environment import run_environment
from sjtu_tpmshx.cpp_interface._native_preparation_case import _Array, _Kind, _Nu, _ResultV2, _Text
from sjtu_tpmshx.physical_models.envelope import ChokedFlowError
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
)
from .solver_library._thermal_abi import (
    _EnergyOptions,
    _FullEnergyEffectiveSettings,
    _IterationOptions,
    _energy_algorithm_query,
    _energy_options,
    _iteration_options,
)
from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.data_types.validator import compute_volumetric_htc
from sjtu_tpmshx.run_control.run_warnings import current_warnings, merge_warnings, warning_messages, warning_scope
from . import _native_flow
from ._native_preparation_case import _ResultV1, pack_saved_resources, borrow_ranges
from ._native_values import TOPOLOGIES, borrow_array, borrow_text
from ._native_grid import _Scalar as GridScalar
from .run_state import NativeRun
from .solver_library._stage_capture_abi import (
    StageExecution,
    _copy_iteration_records,
    _copy_update_scale,
    _decode_iteration_records,
    _decode_update_scale,
    _energy_native_state,
    _energy_result_info,
    _executed_energy_settings,
    _full_enthalpy_info,
    _iteration_query,
    _model_h_algorithm,
    _plane_info,
    _update_scale_query,
    copy_sampling,
    executed_inputs,
    executed_view,
    execution_sides,
    execution_view_query,
    replay_sco2_notices,
    sampling_query,
    sampling_records,
    stage_records,
    thermal_execution,
)
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.run_environment import require_f2_mode
from .solver_library.physical_ledger import HeatLedger2D, heat_ledger_query, copy_heat_ledger
from .solver_library.simple_2d import _result_dict
from .solver_library.temperature_evidence import TemperatureEvidence2D, copy_temperature_evidence
from .solver_library.closure_evidence import copy_nu_observation, copy_range_observations, last_range_query, copy_last_ranges

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

_FlowGrid = record('SavedFlowGrid2D', [('cross', _Array), ('stream', _Array),
    ('cross_precision', _U), ('direction', _U), ('bounds', GridScalar * 4)])
_DesignField = record('SavedDesignField2D', [('name', _Text), ('values', _Array)])
_SavedV3 = record('SavedCaseV3', [('abi_version', _U), ('struct_size', _S),
    ('values', _SavedV2), ('lengths_m', _D * 2), ('flow_grid', _FlowGrid * 2),
    ('resource_fluids', _Text * 2), ('resource_topology', _Text), ('resource_nu', _Nu * 2),
    ('wall_reference_kind', _Kind), ('porosity_reference_kind', _Kind), ('radius_reference_kind', _Kind), ('additional_fields', ct.POINTER(_DesignField)), ('additional_count', _S)])

_Experiment = record('SavedExperiment2D', [('topology', _U), ('geometry_mode', _U), ('domain_count', _U),
    ('fluids', _U * 2), ('configured_flow', _U * 2), ('domain_m', _D * 3),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D), ('delta_levelset', _D), ('velocity_m_s', _D * 2)])
_SavedV4 = record('SavedCaseV4', [('abi_version', _U), ('struct_size', _S),
    ('values', _SavedV3), ('experiment', _Experiment)])


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


def pack_saved_design(case, uniform, saved, keepalive):
    values = uniform.values
    shape = values.nx, values.ny
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
            dtype = np.asarray(field).dtype
            uniform.field_kinds[index] = _Kind(dtype.itemsize * 8, 1 if dtype.kind == 'f' else 2, 2)
            if not getattr(values, native_names[index]).size:
                setattr(values, native_names[index], borrow_array(field, keepalive))
        else:
            extra.append(_DesignField(borrow_text(name, keepalive), borrow_array(field, keepalive)))
    for attr, key in (('wall_reference_kind', 't_wall_m'), ('porosity_reference_kind', 'eps'),
                      ('radius_reference_kind', 'r_h')):
        reference = _native_flow._scalar(case.parameters[key])
        setattr(saved, attr, _Kind(reference.precision, reference.strong, int(bool(reference.strong))))
    saved.additional_fields = storage = (_DesignField * len(extra))(*extra)
    keepalive.append(storage)
    saved.additional_count = len(extra)
    values.hydraulic_radius_m = case.parameters['r_h']
    values.epsilon = case.parameters['eps']


def _run_settings(cfg):
    settings = cfg['compute_cfg']
    return settings if isinstance(settings, dict) else vars(settings)


def prepare_stage(case, cfg, prepared, *, saved_flow_grid=None):
    """Keep the borrowed case fields alive until the native result is captured."""
    settings = _run_settings(cfg)
    uniform = _ResultV2(2, ct.sizeof(_ResultV2))
    uniform.values = _ResultV1(1, ct.sizeof(_ResultV1))
    keepalive = [uniform]
    values = uniform.values
    values.input.abi_version, values.input.struct_size = 1, ct.sizeof(values.input)
    values.input.topology = TOPOLOGIES.index(cfg['tpms_type'])
    values.input.geometry_mode = (0 if cfg['za'] is None else 1 if cfg['z_axis'] == 'continuous' else 2)
    values.input.delta_levelset = settings['geometry'].delta_levelset
    values.input.df_mode = ('cfd_smooth', 'experimental').index(settings['df_mode'])
    values.nx, values.ny = len(prepared['energy_dx']), len(prepared['energy_dy'])
    values.dx = borrow_array(prepared['energy_dx'], keepalive)
    values.dy = borrow_array(prepared['energy_dy'], keepalive)
    reference = _native_flow._scalar(case.parameters['L_cell_m'])
    values.cell_length_m = reference.value
    reference_kind = _Kind(reference.precision, reference.strong, int(bool(reference.strong)))
    values.wall_thickness_m = case.parameters['t_wall_m']
    values.epsilon = cfg['eps']
    values.total_porosity = borrow_array(case.design_fields['eps_arr'], keepalive)
    values.solid_conductivity = borrow_array(case.design_fields['K_ss_arr'], keepalive)
    geometry = cfg['thermal_geometry']
    values.split_a = geometry['split_A']
    values.area_density_per_m = geometry['uniform']['A_0']
    values.hydraulic_diameter_m = geometry['uniform']['D_h']
    area, diameter = _Array(), _Array()
    selected_geometry = geometry['uniform'] if geometry['fields'] is None else geometry['fields']
    diameter_storage, diameter_values = _native_flow._values(selected_geometry['D_h'], preserve_scalar=True)
    diameter_kind = _Kind(diameter_values.precision, diameter_values.strong,
        2 if isinstance(selected_geometry['D_h'], np.ndarray) else int(bool(diameter_values.strong)))
    if geometry['fields'] is not None:
        area = borrow_array(geometry['fields']['A_0'], keepalive)
        diameter = borrow_array(diameter_storage, keepalive)
    conductivity = (_Array(), _Array())
    cell_field_kind = _Kind(64, 1, 2)
    if values.input.geometry_mode:
        cell_storage, cell_values = _native_flow._values(case.design_fields['L_field_m'])
        values.cell_length = borrow_array(cell_storage, keepalive)
        cell_field_kind = _Kind(cell_values.precision, cell_values.strong, 2)
        conductivity = tuple(borrow_array(cfg['za']['K_ff' + side + '_arr'], keepalive) for side in 'AB')
    nu = settings['sco2_nu']
    uniform.sco2_nu.mode = nu.mode != 'cfd_smooth'
    if uniform.sco2_nu.mode:
        uniform.sco2_nu.alpha[:] = (nu.alpha_D, nu.alpha_G)
    for index, side in enumerate('AB'):
        flow, opening, port = cfg['flow_inputs'][side], cfg['boundary_openings'][side], cfg['cfg' + side]
        target = values.sides[index]
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
        if not values.input.geometry_mode:
            target.properties.fluid_conductivity_W_mK = properties['K_ff']
        if saved_flow_grid is not None:
            cross, stream = (values.ny, values.nx) if port['dir'] in (0, 1) else (values.nx, values.ny)
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
        if saved_flow_grid is None:
            from sjtu_tpmshx.solvers.backends.prepared_2d import _validated_outlet_fraction
            target.outlet_u_fraction = borrow_array(_validated_outlet_fraction(flow, opening, port, side), keepalive)
        else:
            grid = saved_flow_grid[index]
            from sjtu_tpmshx.cpp_interface import _native_grid
            grid.direction = port['dir']
            cross, stream = (np.asarray(flow[name]) for name in ('dx', 'dy'))
            if any(axis.ndim != 1 or axis.dtype.kind not in 'fiu' for axis in (cross, stream)):
                raise ValueError(f'prepared flow {side} grid disagrees with the thermal grid')
            widths, grid.cross_precision = _native_grid._widths(cross)
            grid.cross = borrow_array(widths, keepalive)
            grid.stream = borrow_array(stream, keepalive)
            for end, prefix in enumerate(('in', 'out')):
                center, half = port[prefix + '_ctr'], port[prefix + '_w'] / 2
                grid.bounds[2*end] = _native_grid._scalar(center - half)
                grid.bounds[2*end+1] = _native_grid._scalar(center + half)
            for name in ('in_geom_frac', 'out_geom_frac', 'in_profile_frac', 'out_profile_frac'):
                if np.ndim(opening[name]) != 1:
                    raise ValueError(f'prepared Fluid {side} {name} disagrees with its grid and port geometry')
    ranges, captured = borrow_ranges(case.metadata.get('applicability_inputs', ()), keepalive)
    values.ranges, values.range_count = ranges, len(ranges)
    notices = (_Text * len(case.metadata['notices']))(*(
        borrow_text(notice, keepalive) for notice in case.metadata['notices']))
    keepalive.append(notices)
    uniform.notices, uniform.notice_count = notices, len(notices)
    kinds = reference_kind, cell_field_kind, diameter_kind
    return uniform, area, diameter, conductivity, 'applicability_inputs' in case.metadata, captured, kinds, keepalive


def execution_grid(case):
    from sjtu_tpmshx.data_types.persistence_validation import validate_grid
    if case.grid.get('dimension') != 2:
        raise ValueError('2D execution requires a prepared 2D grid')
    missing = {'thermal_geometry', 'flow_inputs'} - case.parameters.keys()
    if missing:
        raise ValueError(f'incomplete prepared 2D execution data: {sorted(missing)}')
    return validate_grid(case.grid)


def _can_pack_settings(settings):
    if not isinstance(settings, dict) or 'domain' in settings:
        return False
    mode = settings.get('df_mode', 'cfd_smooth')
    if type(mode) is not str or mode != 'experimental':
        return type(mode) is str
    geometry, fa, fb = (settings.get(key) for key in ('geometry', 'fluid_A', 'fluid_B'))
    if not all(type(part) is dict for part in (geometry, fa, fb)):
        return False
    if type(geometry.get('tpms')) is not str or geometry['tpms'] not in TOPOLOGIES:
        return False
    if not all(type(geometry.get(name)) in (int, float) for name in
               ('L_dom_m', 'H_dom_m', 'L_cell_mm', 't_wall_mm', 'delta_levelset')):
        return False
    if geometry.get('Lz_m') is not None and type(geometry['Lz_m']) not in (int, float):
        return False
    return all(type(fluid.get('type')) is str and fluid['type'] in ('air', 'water', 'sco2', 'co2')
               and (fluid.get('mass_flow_kg_s') is not None or type(fluid.get('u_mps')) in (int, float))
               for fluid in (fa, fb))


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


def _zone_objects(zone):
    from sjtu_tpmshx.physical_models.zone_config import Zone, ZoneConfig

    return ZoneConfig(**{**zone, 'zones': [Zone(**item) for item in zone['zones']]})


def _plain_zone(zone):
    if set(zone) != {'zones', 'tpms_type', 'k_s'} or not isinstance(zone['zones'], list):
        return False
    required = {'name', 'y_frac_start', 'y_frac_end', 'L_mm', 't_mm'}
    optional = {'props_A', 'props_B'}
    return all(isinstance(row, dict) and required <= row.keys() <= required | optional
               for row in zone['zones'])


def saved_inputs(case, shape, *, check_experiment=None, port_windows_fit=None):
    from sjtu_tpmshx.data_types.compute_config import ComputeConfig, _checked_saved_2d_settings
    from sjtu_tpmshx.data_types.persistence_validation import validate_thermal_geometry
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.physical_models.zone_units import _legacy_zone_units

    cfg = dict(case.parameters)
    validate_thermal_geometry(cfg['thermal_geometry'], shape)
    if set(cfg['flow_inputs']) != {'A', 'B'}:
        raise ValueError('prepared flow inputs require both physical sides')
    settings = _legacy_zone_units(mutable_data(cfg['run_settings']))
    if cfg['z_axis'] == 'continuous':
        settings['zones'] = dict(enabled=True, axis='continuous', config=mutable_data(cfg['continuous_field']))
    experiment = None
    if check_experiment is not None and _can_pack_settings(settings):
        values = cfg['compute_cfg'] = _checked_saved_2d_settings(settings, port_windows_fit=port_windows_fit)
        experiment = _Experiment()
        if values['df_mode'] == 'experimental':
            experiment = _experiment_request(values)
            error = ct.create_string_buffer(2048)
            check_experiment.argtypes = [ct.POINTER(_Experiment), ct.POINTER(ct.c_char), _S]
            check_experiment.restype = ct.c_int
            status = check_experiment(ct.byref(experiment), error, len(error))
            if status:
                _raise_stage_error(status, error, _Run.error_types)
    else:
        cfg['compute_cfg'] = ComputeConfig.from_dict(settings, prepared_grid=True)
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
    if isinstance(zone, dict) and (experiment is None or not _plain_zone(zone)):
        zone = _zone_objects(zone)
    cfg['zone_config'] = zone
    return cfg, dict(energy_dx=case.grid['dx'], energy_dy=case.grid['dy']), experiment


def _request(cfg):
    solver = _run_settings(cfg)['solver']
    request = _Request(3, ct.sizeof(_Request),
        _RequestV2(2, ct.sizeof(_RequestV2), _RequestV1(1, ct.sizeof(_RequestV1))))
    values = request.values.values
    for name in ('max_iter_simple', 'max_outer_ltne'):
        value = getattr(solver, name)
        setattr(values, name, _Size(bool(value), value or 0))
    value = solver.outer_tol_K
    values.outer_tol_K = _Double(bool(value), value or 0.)
    mode, tolerances = convergence_controls(cfg, solver)
    values.convergence_mode = mode.encode()
    for name, tolerance in tolerances.items():
        setattr(values, name, _Double(1, tolerance))
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


def run_stage(driver, case, cfg, prepared, control, *, saved_version=1,
              resume_state=None, checkpoint=None, checkpoint_due=None, experiment=None):
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
    flow_grid = (_FlowGrid * 2)() if saved_version >= 3 else None
    uniform, area, diameter, conductivity, recorded, captured, kinds, keepalive = prepare_stage(
        case, cfg, prepared, saved_flow_grid=flow_grid)
    saved = _Saved(1, ct.sizeof(_Saved), ct.pointer(uniform), area, diameter,
                   (_Array * 2)(*conductivity), recorded, captured, *kinds)
    if saved_version >= 2:
        sides = cfg['thermal_geometry']['side_geometry']
        saved = _SavedV2(2, ct.sizeof(_SavedV2), saved, sides is not None)
        if sides is not None:
            for index, side in enumerate('AB'):
                saved.side_geometry[index][:] = sides[side]
    if flow_grid is not None:
        saved = _SavedV3(3, ct.sizeof(_SavedV3), saved, (_D * 2)(cfg['L'], cfg['H']), flow_grid)
        pack_saved_design(case, uniform, saved, keepalive)
        pack_saved_resources(case, uniform.values.models, uniform.sco2_nu, saved, _run_settings(cfg)['sco2_nu'], keepalive)
    if saved_version == 4:
        saved = _SavedV4(4, ct.sizeof(_SavedV4), saved, experiment)
    request, energy = _request(cfg)
    callbacks, errors = _callbacks(control)
    stage_control = _Control(case.case_id.encode(), driver.table_directory, control.native_cpu_threads(), callbacks)
    execution_query = driver.execution_query
    energy_query = version_query = None
    if execution_query is None and energy.algorithm:
        energy_query = library.tpmshx_full_2d_get_energy_evidence_v1
        energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
        energy_query.restype = ct.c_int
        version_query = _energy_algorithm_query(library)
    result = _StageResult()
    try:
        complete = getattr(library, 'tpmshx_run_saved_case_2d_v4', None) if saved_version == 4 else None
        if complete is not None and checkpoint is None and resume_state is None:
            complete.argtypes = [ct.POINTER(_SavedV4), ct.POINTER(_Request), ct.POINTER(_Control),
                                 ct.POINTER(_StageResult), ct.POINTER(ct.c_char), _S]
            complete.restype = ct.c_int
            error = ct.create_string_buffer(2048)
            code = complete(ct.byref(saved), ct.byref(request), ct.byref(stage_control),
                            ct.byref(result), error, len(error))
            if errors:
                raise errors[0]
            if code:
                _raise_stage_error(code, error, _Run.error_types)
        else:
            with _Run(library, saved, request, stage_control, errors, resume_state) as run:
                run.finish(checkpoint, checkpoint_due, (1, 2, 6, 7, 8))
                result = run.take_result()
        if saved_version >= 3:
            cfg['_input_resolution'] = executed_inputs(case, result.evidence)
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
        execution = executed_view(execution_query, result) if execution_query is not None else None
        records = stage_records(library, result) if execution is None else execution.execution.records.contents
        native = driver.copy_result(result.raw, shape, result.resolved,
            entry_version=6, control=control, cpu_thread_limit=stage_control.cpu_threads, energy_query=energy_query,
            version_query=version_query, resume_state=resume_state, capture_scalars=_scalars(summary), fields=stage_fields[0],
            records=records, evidence=result.evidence, execution=execution)
        if execution is not None and saved_version >= 3:
            native['sco2_notices'] = tuple(execution.execution.sco2_notices)
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
            continuous = saved_version == 4 and cfg['z_axis'] == 'continuous'
            if continuous:
                zone_summary = result_stage.zone_result
            elif hasattr(library, 'tpmshx_stage_run_2d_zone_temperatures_v1'):
                zone_summary = partial(result_stage.zone_result, solver_library=library)
            elif hasattr(result_stage.core.result_library.get().library, 'tpmshx_result_zone_temperatures_2d_v1'):
                zone_summary = result_stage.zone_result
        field = capture_result(case, cfg, prepared, native, application_hv=application_hv,
                               zone_summary=zone_summary, stage_fields=stage_fields)
        from sjtu_tpmshx.cpp_interface._native_result_stage import copy_applicability
        applicability = copy_applicability(result.evidence.applicability, case.metadata.get(
            'applicability_inputs', ()))
        metadata = dict(field.metadata, _native_applicability=applicability)
        if records is not None:
            metadata['_native_execution_sides'] = execution_sides(records, result.evidence, case, declarations)
        if execution is not None:
            metadata['_native_thermal_execution'] = thermal_execution(execution.execution, result.evidence,
                                                                       native['model_h_iterations'], native['main']['true_h'])
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
    settings = _run_settings(cfg)
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
            P_in_A_Pa=settings['fluid_A'].P_in_Pa,
            P_in_B_Pa=settings['fluid_B'].P_in_Pa,
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
        if 'sco2_notices' in native:
            replay_sco2_notices(native['sco2_notices'], '2D main-hv')
        else:
            from sjtu_tpmshx.physical_models.nu_correlations import warn_sco2_nu_evidence
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
        zone = cfg['zone_config']
        if isinstance(zone, dict):
            zone = _zone_objects(zone)
        application['zones'] = zone_statistics_2d(cfg['z_axis'], zone, cfg['za'], cfg['L'], cfg['H'],
            prepared['energy_dx'], prepared['energy_dy'], *main['temperature'])
    evidence.update(input_resolution=cfg['_input_resolution'], property_sampling=native['property_sampling'])
    if stage_fields is None:
        stage_fields = legacy_fields(evidence, main, native)
    result = _capture_result(case, stage_fields, evidence, application, diagnostics, backend_id='cpp',
                             backend_version=f"full_2d_v{native.get('entry_version', 2)}")
    extras = {key: native[key] for key in ('continuation', 'runtime_resources') if key in native}
    if 'native_metadata' in native:
        extras['native'] = native['native_metadata']
    return replace(result, metadata=dict(result.metadata, **extras, _last_closure_ranges=native['last_closure_ranges'],
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
            shape = tuple(n + int(axis == (name == 'mass_y')) for axis, n in enumerate(physical_shape))
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


def _thermal(t, actual, abi, *, capture_scalars=None, level=0, fields=None):
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
            extent = tuple(n+int(axis == (name == 'mass_y')) for axis, n in enumerate(shape))
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
        out['model_h'] = _plane_info(t.model_h, shape, (out['dx'], out['dy']), masses,
                                   capture_scalars=scalar)
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
    require_legacy_evidence = False

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
        if self.require_legacy_evidence or self.execution_query is None:
            self._bind_legacy_evidence()
        self.query_flow_methods = self.library.tpmshx_full_2d_get_flow_methods_v1
        self.query_flow_methods.argtypes = [ct.POINTER(_Result), ct.POINTER(_FlowMethod)]
        self.query_flow_methods.restype = ct.c_int

    def _bind_legacy_evidence(self):
        try:
            self.query_settings = self.library.tpmshx_full_2d_get_energy_effective_settings_v1
        except AttributeError as exc:
            raise ValueError('native full 2D library lacks executed settings; rebuild the library') from exc
        self.query_settings.argtypes = [ct.POINTER(_Result), ct.POINTER(_FullEnergyEffectiveSettings)]
        self.query_settings.restype = ct.c_int
        self.query_update_scale = _update_scale_query(self.library, 2, _Result)
        self.query_model_h = _iteration_query(self.library, 2, _Result)

    def copy_result(self, result, shape, config, *, entry_version, control=RunControl(),
                    cpu_thread_limit=None, energy_query=None, version_query=None, resume_state=None,
                    capture_scalars=None, fields=None, records=None, evidence=None, execution=None):
        """Copy borrowed result views through queries from their selected library."""
        if result.cancelled:
            raise CancelledError('compute cancelled by user')
        if execution is not None:
            actual = execution.settings
        else:
            actual = _FullEnergyEffectiveSettings()
            if self.query_settings(ct.byref(result), ct.byref(actual)):
                raise RuntimeError('native full 2D effective settings query failed')
        if actual.outer_count != result.outer_history_count:
            raise RuntimeError('native full 2D effective settings do not match the thermal history')
        out = {name: bool(getattr(result, name)) for name in (*_FLAGS, *_FINE_FLAGS)}
        out.update(iterations=result.iterations, flow=[_flow(f, shape, fields, label, records.simple_stop[i] if records is not None else None)
            for i, (f, label) in enumerate(zip(result.flow, 'AB'))],
                   main=_thermal(result.main, actual.last, entry_version, capture_scalars=capture_scalars, fields=fields),
                   fine=_thermal(result.fine, actual.last, entry_version, capture_scalars=capture_scalars, level=1)
                   if result.have_fine else None)
        if records is None:
            out['property_sampling'] = copy_sampling(sampling_query(self.library, 2, _Result), result)
        else:
            out['property_sampling'] = sampling_records(records.sampling)
        out['simple_velocity_relaxation'] = config.alpha_velocity
        if execution is not None:
            executed = execution.execution
            out['enthalpy_update_normalization'] = _decode_update_scale(executed.update_scale)
            out['model_h_iterations'] = _decode_iteration_records(executed.model_h)
        else:
            out['enthalpy_update_normalization'] = _copy_update_scale(self.query_update_scale, result)
            out['model_h_iterations'] = _copy_iteration_records(self.query_model_h, result)
        if records is None:
            for name in ('density', 'viscosity', 'rho_cp'):
                out[name] = [_copy(x, shape) for x in getattr(result, name)]
        for name in ('fine_duty', 'extrapolated_duty', 'pressure_drop', 'outlet_temperature', 'inlet_mass', 'duty'):
            out[name] = list(getattr(result, name))
        for name in ('q_total', 'q_solid', 'energy_imbalance'):
            out[name] = getattr(result, name)
        if records is None:
            out['last_closure_ranges'] = copy_last_ranges(last_range_query(self.library, 2, _Result), result)
        else:
            from ._native_result_stage import stage_closures
            out['range_observations'], out['range_warnings'], out['last_closure_ranges'] = stage_closures(records)
        out['sco2_nu_observations'] = {}
        for i, (side, value) in enumerate(zip('AB', result.nu_observations)):
            scalar = None if capture_scalars is None else capture_scalars['nu'][i]
            if capture_scalars is not None and value.available and scalar is None:
                raise RuntimeError('native full 2D Nu capture is unavailable')
            if records is None:
                observation = copy_nu_observation(value, shape, capture_scalars=scalar)
            else:
                from ._native_result_stage import nu_observation
                observation = nu_observation(value, shape, scalar)
            out['sco2_nu_observations'][side] = observation
        if capture_scalars is None:
            from sjtu_tpmshx.physical_models.co2_correlations import NU_MULTIPLIER
            for i, side in enumerate('AB'):
                if config.sides[i].fluid == 3 and out['sco2_nu_observations'][side]:
                    out['sco2_nu_observations'][side]['floor'] *= NU_MULTIPLIER
        if records is None:
            out['range_observations'] = copy_range_observations(result.range_observations, result.range_observation_count)
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
        if cpu_thread_limit is not None:
            out['runtime_resources'] = dict(cpu_thread_limit=cpu_thread_limit,
                requested_cpu_threads=control.cpu_threads, policy='native_cpu_limit_v1')
        if actual.last.available and (execution is not None or energy_query):
            version = None
            if execution is not None:
                extra = execution.energy
                version = evidence.thermal.true_h.contents.energy_algorithm_version[0]
            else:
                extra = _EnergyEvidence()
                if energy_query(ct.byref(result), ct.byref(extra)):
                    raise RuntimeError('native full 2D energy evidence query failed')
            if out['main']['true_h'] is None or extra.outer_count != len(out['outer_history']):
                raise RuntimeError('native full 2D energy evidence does not match the thermal history')
            info = out['main']['true_h']
            _energy_result_info(info, extra.main.energy,
                temperature_tol=actual.last.temperature_update_tolerance, abi=entry_version,
                version_query=version_query, version=version, state_update='per_side_energy_relation')
            _energy_native_state(info, extra.main, (*shape, 1), 'W/m')
            out['main']['mode'] = 'conservative_energy'
            if out['fine'] is not None:
                raise RuntimeError('native conservative energy unexpectedly returned Richardson evidence')
            for index, row in enumerate(out['outer_history']):
                _energy_result_info(row['energy_info'], extra.outer[index],
                    temperature_tol=actual.outer[index].temperature_update_tolerance, abi=entry_version,
                    version_query=version_query, version=version)
        if records is not None:
            from ._native_result_stage import _stage_array, stage_ledger
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
                        extent = tuple(n + int(i == axis) for i, n in enumerate(shape))
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
        elif out['main']['mode'] == 'temperature':
            query = self.library.tpmshx_full_2d_get_model_enthalpy_evidence_v1
            query.argtypes = [ct.POINTER(_Result), ct.POINTER(TemperatureEvidence2D)]
            query.restype = ct.c_int
            extra = TemperatureEvidence2D()
            if query(ct.byref(result), ct.byref(extra)):
                raise RuntimeError('native full 2D temperature evidence query failed')
            out['main']['temperature_evidence'] = copy_temperature_evidence(extra.main, (*shape, 1), 2)
            if out['fine'] is not None:
                fine_shape = (len(out['fine']['dx']), len(out['fine']['dy']), 1)
                out['fine']['temperature_evidence'] = copy_temperature_evidence(extra.fine, fine_shape, 2)
        if records is None and 'temperature_evidence' not in out['main']:
            ledger = HeatLedger2D()
            if heat_ledger_query(self.library, 2, _Result)(ct.byref(result), ct.byref(ledger)):
                raise RuntimeError('native full 2D heat ledger query failed')
            out['main']['physical_ledger'] = copy_heat_ledger(ledger.main, (*shape, 1), 2)
            if out['fine'] is not None:
                fine_shape = (len(out['fine']['dx']), len(out['fine']['dy']), 1)
                out['fine']['physical_ledger'] = copy_heat_ledger(ledger.fine, fine_shape, 2)
        if out['main']['mode'] in ('model_h', 'temperature'):
            if execution is not None:
                algorithm = execution.execution.algorithm.decode()
            else:
                algorithm = (_model_h_algorithm(self.library, 2) if out['main']['mode'] == 'model_h'
                             else out['main']['temperature_evidence']['algorithm'])
            _set_native_metadata(out, self.abi, algorithm, config.red_black,
                captured_red_black=None if capture_scalars is None else capture_scalars['red_black'])
        if capture_scalars is not None:
            out['capture_scalars'] = capture_scalars
        return out


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


def run_case(case, control=RunControl(), *, direct_run, resume_state=None, checkpoint=None, checkpoint_due=None):
    if control.backend != 'cpp' or control.native_library is None:
        raise ValueError('full native 2D requires backend=cpp and an explicit native_library')
    control.check_cancelled()
    shape = execution_grid(case)
    driver = StageDriver(control.native_library, table_directory=control.native_table_directory)
    check_experiment = getattr(driver.library, 'tpmshx_stage_run_2d_check_experiment_v4', None)
    v4 = [check_experiment is not None,
          *(hasattr(driver.library, f'tpmshx_stage_run_2d_{name}_saved_v4') for name in ('create', 'restore'))]
    if any(v4) and not all(v4):
        raise ValueError('native library has an incomplete saved 2D stage protocol')
    experiment = None
    if check_experiment is not None or hasattr(driver.library, 'tpmshx_stage_run_2d_create_saved_v3'):
        port_windows_fit = getattr(driver.library, 'tpmshx_stage_port_windows_fit_2d_v1', None)
        if port_windows_fit is not None:
            port_windows_fit.argtypes, port_windows_fit.restype = [ct.c_double] * 5, ct.c_int
        cfg, prepared, experiment = saved_inputs(case, shape, check_experiment=check_experiment,
                                                port_windows_fit=port_windows_fit)
    else:
        from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
        cfg, prepared = build_execution_inputs(case, copy_design=False)
    settings = _run_settings(cfg)
    stage_layout = (case.metadata['design_mode'] in ('uniform', 'continuous')
        and settings['geometry'].delta_levelset == 0
        and (cfg['zone_config'] is None or cfg['z_axis'] == 'continuous'))
    saved_version = 4 if experiment is not None else 0
    for version in (() if saved_version else (3, 2, 1)):
        if version == 1 and not stage_layout:
            continue
        saved_entries = [hasattr(driver.library, f'tpmshx_stage_run_2d_{name}_saved_v{version}')
                         for name in ('create', 'restore')]
        if any(saved_entries) and not all(saved_entries):
            raise ValueError('native library has an incomplete saved 2D stage protocol')
        if all(saved_entries):
            saved_version = version
            break
    if saved_version:
        result = run_stage(driver, case, cfg, prepared, control, resume_state=resume_state,
            checkpoint=checkpoint, checkpoint_due=checkpoint_due, saved_version=saved_version, experiment=experiment)
    else:
        result = direct_run(case, cfg, prepared, control, resume_state, checkpoint, checkpoint_due)
    control.report_progress(100)
    return result
