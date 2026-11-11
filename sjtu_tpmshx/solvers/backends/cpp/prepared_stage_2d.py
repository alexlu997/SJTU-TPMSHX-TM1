"""Borrow validated saved 2D inputs without running preparation again."""
import ctypes as ct

import numpy as np

from sjtu_tpmshx.shared.models import _native_flow
from sjtu_tpmshx.shared.models._native_preparation_case import (
    _Array, _Kind, _Range, _ResultV1, _ResultV2, _Text,
)
from ..prepared_2d import _validated_outlet_fraction


def _array(value, keepalive):
    storage = np.require(value, dtype=np.float64, requirements=['C', 'A'])
    keepalive.append(storage)
    return _Array(storage.ctypes.data_as(ct.POINTER(ct.c_double)), storage.size)


def _text(value, keepalive):
    encoded = value.encode('utf-8')
    storage = ct.create_string_buffer(encoded)
    keepalive.append(storage)
    return _Text(ct.cast(storage, ct.POINTER(ct.c_char)), len(encoded))


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


def prepare_stage(case, cfg, prepared):
    """Pack outputs from build_execution_inputs; keep all views alive through capture."""
    uniform = _ResultV2(2, ct.sizeof(_ResultV2))
    uniform.values = _ResultV1(1, ct.sizeof(_ResultV1))
    keepalive = [uniform]
    values = uniform.values
    values.input.abi_version, values.input.struct_size = 1, ct.sizeof(values.input)
    values.input.topology = ('Diamond', 'Gyroid').index(cfg['tpms_type'])
    values.input.geometry_mode = ('uniform', 'continuous').index(case.metadata['design_mode'])
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
        outlet_fraction = _validated_outlet_fraction(flow, opening, port, side)
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
        target.outlet_u_fraction = _array(outlet_fraction, keepalive)
    ranges, captured = _ranges(case.metadata.get('applicability_inputs', ()), keepalive)
    values.ranges, values.range_count = ranges, len(ranges)
    notices = (_Text * len(case.metadata['notices']))(*(
        _text(notice, keepalive) for notice in case.metadata['notices']))
    keepalive.append(notices)
    uniform.notices, uniform.notice_count = notices, len(notices)
    kinds = reference_kind, cell_field_kind, diameter_kind
    return uniform, area, diameter, conductivity, 'applicability_inputs' in case.metadata, captured, kinds, keepalive
