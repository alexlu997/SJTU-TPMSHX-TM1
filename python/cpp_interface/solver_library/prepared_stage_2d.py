"""Borrow validated saved 2D inputs without running preparation again."""
import ctypes as ct

import numpy as np

from sjtu_tpmshx.cpp_interface import _native_flow
from sjtu_tpmshx.cpp_interface._native_preparation_case import (
    _Array, _Kind, _Range, _ResultV1, _ResultV2, _Text,
)


def _array(value, keepalive):
    storage = np.require(value, dtype=np.float64, requirements=['C', 'A'])
    keepalive.append(storage)
    return _Array(storage.ctypes.data_as(ct.POINTER(ct.c_double)), storage.size)


def _text(value, keepalive):
    encoded = value.encode('utf-8')
    storage = ct.create_string_buffer(encoded)
    keepalive.append(storage)
    return _Text(ct.cast(storage, ct.POINTER(ct.c_char)), len(encoded))


def _pack_nu(target, settings, keepalive):
    target.mode = settings.mode == 'experimental'
    for index, value in enumerate((settings.alpha_D, settings.alpha_G)):
        target.have_alpha[index] = value is not None
        target.alpha[index] = value or 0.
    for name in ('parameter_version', 'source', 'applicability'):
        setattr(target, name, _text(getattr(settings, name), keepalive))


def pack_saved_resources(case, uniform, saved, settings, keepalive):
    from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
    from sjtu_tpmshx.data_types.model_refs import ModelRef

    roles = case.metadata['model_roles']
    names = ('fluid_A', 'fluid_B', 'geometry', 'darcy_forchheimer')
    if set(roles) != set(names) or sorted(roles.values()) != list(range(len(case.model_refs))):
        raise ValueError('2D model roles must account for every recorded resource')
    _pack_nu(uniform.sco2_nu, settings, keepalive)
    for index, role in enumerate(names):
        ref = case.model_refs[roles[role]]
        if not isinstance(ref, ModelRef):
            raise TypeError('model resource must be a ModelRef')
        model = uniform.values.models[index]
        model.name, model.version = _text(ref.name, keepalive), _text(ref.version, keepalive)
        params = ref.parameters
        if index < 2:
            if set(params) - {'fluid', 'sco2_nu'} or 'fluid' not in params:
                raise ValueError('fluid model requires fluid and optional sco2_nu parameters')
            fluid = params['fluid']
            if (ref.name == 'co2_fluid') != (fluid == 'co2'):
                raise ValueError('CO2 requires its versioned fluid resource')
            saved.resource_fluids[index] = _text(fluid.strip().lower(), keepalive)
            selection = Sco2NuConfig(**params['sco2_nu']).validate()
            if set(params['sco2_nu']) != set(vars(settings)):
                raise ValueError(f'prepared Nu settings and fluid {"AB"[index]} resource disagree')
            _pack_nu(saved.resource_nu[index], selection, keepalive)
        elif index == 2 and params:
            raise ValueError('geometry resource takes no fixed parameters')
        elif index == 3:
            if set(params) != {'topology'}:
                raise ValueError('Darcy-Forchheimer resource requires topology')
            saved.resource_topology = _text(params['topology'], keepalive)


def _ranges(rows, keepalive):
    values = (_Range * len(rows))()
    captured = (ct.c_uint32 * len(rows))()
    keepalive.extend((values, captured))
    for index, row in enumerate(rows):
        value = values[index]
        source = (_Text * len(row['source']))(*(_text(item, keepalive) for item in row['source']))
        shape = (ct.c_size_t * len(row['shape']))(*row['shape'])
        keepalive.extend((source, shape))
        value.source, value.source_count = source, len(source)
        value.shape, value.rank = shape, len(shape)
        for name in ('side', 'stage', 'layout', 'quantity', 'unit'):
            setattr(value, name, _text(row[name], keepalive))
        value.bounds[:] = row['bounds']
        if type(row['captured']) is not bool:
            raise ValueError('range evidence requires an explicit capture flag')
        captured[index] = row['captured']
        if not row['captured']:
            continue
        sample = value.sample
        for name in ('low', 'high', 'size', 'nonfinite'):
            setattr(sample, name, row[name])
        sample.have_finite = row['minimum'] is not None
        if sample.have_finite:
            for name in ('minimum', 'maximum'):
                scalar, position = row[name]
                setattr(sample, name, scalar)
                setattr(sample, name + '_index', int(np.ravel_multi_index(position, row['shape'])))
    return values, captured


def prepare_stage(case, cfg, prepared, *, saved_flow_grid=None):
    """Pack outputs from build_execution_inputs; keep all views alive through capture."""
    uniform = _ResultV2(2, ct.sizeof(_ResultV2))
    uniform.values = _ResultV1(1, ct.sizeof(_ResultV1))
    keepalive = [uniform]
    values = uniform.values
    values.input.abi_version, values.input.struct_size = 1, ct.sizeof(values.input)
    values.input.topology = ('Diamond', 'Gyroid').index(cfg['tpms_type'])
    values.input.geometry_mode = (0 if cfg['za'] is None else 1 if cfg['z_axis'] == 'continuous' else 2)
    values.input.delta_levelset = cfg['compute_cfg'].geometry.delta_levelset
    values.input.df_mode = ('cfd_smooth', 'experimental').index(cfg['compute_cfg'].df_mode)
    values.nx, values.ny = len(prepared['energy_dx']), len(prepared['energy_dy'])
    values.dx = _array(prepared['energy_dx'], keepalive)
    values.dy = _array(prepared['energy_dy'], keepalive)
    reference = _native_flow._scalar(case.parameters['L_cell_m'])
    values.cell_length_m = reference.value
    reference_kind = _Kind(reference.precision, reference.strong, int(bool(reference.strong)))
    values.wall_thickness_m = case.parameters['t_wall_m']
    values.epsilon = cfg['eps']
    values.total_porosity = _array(case.design_fields['eps_arr'], keepalive)
    values.solid_conductivity = _array(case.design_fields['K_ss_arr'], keepalive)
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
        area = _array(geometry['fields']['A_0'], keepalive)
        diameter = _array(diameter_storage, keepalive)
    conductivity = (_Array(), _Array())
    cell_field_kind = _Kind(64, 1, 2)
    if values.input.geometry_mode:
        cell_storage, cell_values = _native_flow._values(case.design_fields['L_field_m'])
        values.cell_length = _array(cell_storage, keepalive)
        cell_field_kind = _Kind(cell_values.precision, cell_values.strong, 2)
        conductivity = tuple(_array(cfg['za']['K_ff' + side + '_arr'], keepalive) for side in 'AB')
    nu = cfg['compute_cfg'].sco2_nu
    uniform.sco2_nu.mode = nu.mode != 'cfd_smooth'
    if uniform.sco2_nu.mode:
        uniform.sco2_nu.alpha[:] = (nu.alpha_D, nu.alpha_G)
    for index, side in enumerate('AB'):
        flow, opening, port = cfg['flow_inputs'][side], cfg['boundary_openings'][side], cfg['cfg' + side]
        target = values.sides[index]
        target.inlet.fluid = ('air', 'water', 'sco2', 'co2').index(cfg['fluid_' + side])
        target.inlet.temperature_K = cfg['T_in' + side]
        target.inlet.pressure_Pa = getattr(cfg['compute_cfg'], 'fluid_' + side).P_in_Pa
        target.inlet.velocity_m_s = cfg['u_' + side]
        target.inlet.port.direction = cfg['dir_' + side]
        target.inlet.port.uniform_inlet = int(port.get('uniform_inlet_2d', False))
        target.inlet_bounds[:] = (port['in_ctr'] - port['in_w'] / 2, port['in_ctr'] + port['in_w'] / 2)
        target.outlet_bounds[:] = (port['out_ctr'] - port['out_w'] / 2, port['out_ctr'] + port['out_w'] / 2)
        properties = cfg['static_properties'][side]
        target.properties.mu = properties['mu']
        if not values.input.geometry_mode:
            target.properties.fluid_conductivity_W_mK = properties['K_ff']
        target.seed_permeability_m2, target.seed_forchheimer_per_m = flow['seed_K_m2'], flow['seed_cF_per_m']
        target.row_permeability = _array(flow['K_m2'], keepalive)
        target.row_forchheimer = _array(flow['cF_per_m'], keepalive)
        for name, key in (('permeability', 'K_field_m2'), ('forchheimer', 'cF_field_per_m')):
            if key in flow:
                setattr(target, name, _array(flow[key], keepalive))
        for name, key in (('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'),
                          ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac')):
            setattr(target, name, _array(opening[key], keepalive))
        if saved_flow_grid is None:
            from sjtu_tpmshx.solvers.backends.prepared_2d import _validated_outlet_fraction
            target.outlet_u_fraction = _array(_validated_outlet_fraction(flow, opening, port, side), keepalive)
        else:
            grid = saved_flow_grid[index]
            from sjtu_tpmshx.cpp_interface import _native_grid
            grid.direction = port['dir']
            cross, stream = (np.asarray(flow[name]) for name in ('dx', 'dy'))
            if any(axis.ndim != 1 or axis.dtype.kind not in 'fiu' for axis in (cross, stream)):
                raise ValueError(f'prepared flow {side} grid disagrees with the thermal grid')
            widths, grid.cross_precision = _native_grid._widths(cross)
            grid.cross = _array(widths, keepalive)
            grid.stream = _array(stream, keepalive)
            for end, prefix in enumerate(('in', 'out')):
                center, half = port[prefix + '_ctr'], port[prefix + '_w'] / 2
                grid.bounds[2*end] = _native_grid._scalar(center - half)
                grid.bounds[2*end+1] = _native_grid._scalar(center + half)
            for name in ('in_geom_frac', 'out_geom_frac', 'in_profile_frac', 'out_profile_frac'):
                if np.ndim(opening[name]) != 1:
                    raise ValueError(f'prepared Fluid {side} {name} disagrees with its grid and port geometry')
    ranges, captured = _ranges(case.metadata.get('applicability_inputs', ()), keepalive)
    values.ranges, values.range_count = ranges, len(ranges)
    notices = (_Text * len(case.metadata['notices']))(*(
        _text(notice, keepalive) for notice in case.metadata['notices']))
    keepalive.append(notices)
    uniform.notices, uniform.notice_count = notices, len(notices)
    kinds = reference_kind, cell_field_kind, diameter_kind
    return uniform, area, diameter, conductivity, 'applicability_inputs' in case.metadata, captured, kinds, keepalive
