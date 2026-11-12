"""Build the existing CaseData contract from the owned native 2D stage."""
from contextlib import ExitStack
from copy import deepcopy
import ctypes as ct
from dataclasses import asdict, replace
import os

import numpy as np

from sjtu_tpmshx.preprocess.native_preparation import (
    PreparationCacheBridge, model_metadata, _kind, _flow_kind, _summary,
    _range_record, _records, _geometry_values, _cache_record_view, _GEOMETRY_NAMES, _PROPERTY_NAMES,
)
from sjtu_tpmshx.shared.domain.case_data import CaseData
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.shared.domain.model_refs import ModelRef
from sjtu_tpmshx.shared.domain.run_environment import capture_environment
from sjtu_tpmshx.shared.domain.run_warnings import (
    RangeRecord, current_warnings, merge_warnings, record_warning, _range_context,
)
from sjtu_tpmshx.shared.models import _native_preparation_case as native
from sjtu_tpmshx.shared.models import _native_flow, _native_geometry, _native_grid


def supports(config):
    """Keep unported physical modes on their explicit preparation route."""
    spatial = config.zones.enabled and config.zones.axis != 'continuous'
    return (not config.is_3d and config.geometry.delta_levelset == 0.
            and (not spatial or (config.fluid_A.type == 'air' and config.fluid_B.type == 'air')))


def _input(config, targets, operation):
    geometry = config.geometry
    value = native._InputV1(1, ct.sizeof(native._InputV1), geometry.L_dom_m, geometry.H_dom_m,
        config.solver.Nx, config.solver.Ny, config.flags.port_wall_refine,
        _native_geometry._topology(geometry.tpms), geometry.L_cell_mm, geometry.t_wall_mm,
        geometry.k_s_W_mK, geometry.delta_levelset)
    kinds = native._Kinds(_kind(geometry.L_cell_mm), _kind(geometry.t_wall_mm), _kind(geometry.k_s_W_mK))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        # Capacity queries never consume an obsolete inlet speed.
        speed = 0. if operation == 'prepare_inlet_mass_capacities' or (
            targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
        value.sides[index] = native._Inlet(native._FLUIDS.index(fluid.type), speed,
            fluid.T_in_K, fluid.P_in_Pa, native._Port(
                port.dir, port.in_ctr, port.in_w, port.out_ctr, port.out_w, port.uniform_inlet_2d),
            fluid.mass_flow_kg_s is not None, fluid.mass_flow_kg_s or 0.)
        kinds.sides[index] = native._InletKinds(*map(_kind, (speed, fluid.T_in_K, fluid.P_in_Pa)))
    value.have_physical_depth = geometry.Lz_m is not None
    value.physical_depth_m = geometry.Lz_m if geometry.Lz_m is not None else 0.
    value.geometry_mode = int(config.zones.enabled)
    value.df_mode = int(config.df_mode == 'experimental')
    typed = native._InputV2(2, ct.sizeof(native._InputV2), value)
    typed.kinds = kinds
    settings = config.sco2_nu
    typed.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        selected = getattr(settings, name)
        typed.sco2_nu.have_alpha[index] = selected is not None
        typed.sco2_nu.alpha[index] = selected or 0.
    buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        encoded = getattr(settings, name).encode('utf-8')
        buffer = ct.create_string_buffer(encoded)
        buffers.append(buffer)
        setattr(typed.sco2_nu, name, native._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(encoded)))
    flow = native._FlowInput(3, ct.sizeof(native._FlowInput), typed)
    flow.physical_depth_kind = _flow_kind(geometry.Lz_m if geometry.Lz_m is not None else 0.)
    flow.have_explicit_targets = targets is not None
    for index, side in enumerate('AB'):
        target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
        flow.target_kinds[index] = _flow_kind(target if target is not None else 0.)
        if targets is not None:
            flow.explicit_targets_kg_s[index] = target
    if config.zones.enabled and config.zones.axis == 'continuous':
        spec = config.zones.config
        decision = np.asarray(spec['x_decision'], dtype=np.float64)
        controls = native._Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['spline_order'], spec['symmetric_y'],
            (native._D * 2)(*spec['L_bounds']), (native._D * 2)(*spec['t_bounds']),
            native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size))
        source = native._ContinuousInput(4, ct.sizeof(native._ContinuousInput), flow, controls)
        buffers.append(decision)
    elif config.zones.enabled:
        source = _spatial_input(config, flow, buffers)
    else:
        source = flow
    source._grid_error = None

    def grid_kind(value):
        try:
            scalar = _native_grid._scalar(value)
        except TypeError as error:
            if source._grid_error is None:
                source._grid_error = str(error)
            return native._Kind(64, 0, 0)
        return native._Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))

    source._grid_kinds = native._GridKinds(7, ct.sizeof(native._GridKinds),
        (native._Kind * 2)(*map(grid_kind, (geometry.L_dom_m, geometry.H_dom_m))))
    for index, side in enumerate('AB'):
        port = getattr(config, 'bc_' + side)
        source._grid_kinds.ports[index] = (native._Kind * 4)(
            *(grid_kind(getattr(port, name)) if port.in_w > 0. and port.out_w > 0.
              else native._Kind(64, 0, 0) for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w')))
    source._buffers = buffers
    return source


def _spatial_input(config, flow, buffers):
    zones = config.zones
    sigmoid = zones.axis == 'grid' and zones.pareto_x_decision is not None
    if zones.axis == 'grid':
        model = dict(k_s=config.geometry.k_s_W_mK) if sigmoid else zones.grid
        rows = [('', [cell[key] for key in ('x0', 'x1', 'y0', 'y1')],
                                    cell['L'], cell['t']) for cell in zones.grid['cells']]
    else:
        model = asdict(zones.config) if hasattr(zones.config, '__dataclass_fields__') else zones.config
        if model is None:
            model = dict(zones=[], k_s=config.geometry.k_s_W_mK)
        rows = [(row['name'], [row['y_frac_start'], row['y_frac_end'], 0., 0.], row['L_mm'], row['t_mm'])
                for row in model['zones']]
    regions = []
    for name, bounds, cell, wall in rows:
        encoded = name.encode('utf-8')
        text = ct.create_string_buffer(encoded)
        buffers.append(text)
        regions.append(native._Region(native._Text(ct.cast(text, ct.POINTER(ct.c_char)), len(encoded)),
            (native._GridScalar * 4)(*map(_native_grid._scalar, bounds)), cell, wall, _kind(cell), _kind(wall)))
    regions = (native._Region * len(regions))(*regions)
    buffers.append(regions)
    values = flow.values
    values.values.geometry_mode = 2
    zoned = native._ZonedInput(5, ct.sizeof(native._ZonedInput), values,
        int(zones.axis == 'grid'), int(zones.axis == 'y'), regions, len(regions))
    if sigmoid:
        decision = np.asarray(zones.pareto_x_decision, dtype=np.float64)
        buffers.append(decision)
        controls = native._SigmoidControls(native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size),
            _native_grid._scalar(zones.pareto_y_trans_inlet), _native_grid._scalar(zones.pareto_y_trans_outlet))
        zoned = native._SigmoidInput(6, ct.sizeof(native._SigmoidInput), zoned, controls, native._LUTView())
        flow_type, host_type = native._SigmoidFlowInput, native._SigmoidHostInput
    else:
        flow_type, host_type = native._ZonedFlowInput, native._ZonedHostInput
    spatial_flow = flow_type(8, ct.sizeof(flow_type), zoned, flow.physical_depth_kind,
        flow.target_kinds, flow.have_explicit_targets, flow.explicit_targets_kg_s)
    return host_type(9, ct.sizeof(host_type), spatial_flow,
        native._SpatialModel(_kind(model['k_s']), bool(config.extrap.allow), sigmoid))


def _lut_cache():
    from sjtu_tpmshx.shared.models import sigmoid_field, _native_lut
    buffers, pending = [], {}

    def cache(action, topology, resolution, value):
        name = ('Diamond', 'Gyroid')[topology]
        key = (name,)
        if action:
            lut = pending.pop(key)
            shape = len(lut.L_vals), len(lut.t_vals)
            lut.eps_table = native._array(value.porosity, shape)
            lut.A0_table = native._array(value.area_density_per_m, shape)
            lut._save()
            lut._native_lut = _native_lut.LUT(lut.L_vals, lut.t_vals, lut.eps_table, lut.A0_table)
            sigmoid_field._lut_cache[key] = lut
            return False
        lut = sigmoid_field._lut_cache.get(key)
        if lut is None:
            lut = object.__new__(sigmoid_field.GeometryLUT)
            lut.L_vals, lut.t_vals = native._array(value.cell_mm), native._array(value.wall_mm)
            lut._initialize_cache(name, resolution)
            if not lut._load():
                pending[key] = lut
                return False
            lut._native_lut = _native_lut.LUT(lut.L_vals, lut.t_vals, lut.eps_table, lut.A0_table)
            sigmoid_field._lut_cache[key] = lut
        table = lut._native_lut
        shape = tuple(axis.size for axis in table.axes)
        if table.epsilon.shape != shape or table.area.shape != shape:
            raise ValueError('LUT table shape no longer matches its captured axes')
        value.porosity_fast, value.area_fast = _native_lut._fast(table.epsilon), _native_lut._fast(table.area)
        for field, array in zip(('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m'),
                                (*table.axes, table.epsilon, table.area)):
            array = np.ascontiguousarray(array, dtype=np.float64)
            buffers.append(array)
            setattr(value, field, native._Array(array.ctypes.data_as(ct.POINTER(native._D)), array.size))
        return True

    return cache


def _resolved(config, flow, targets):
    fluids = {}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        if targets is not None or fluid.mass_flow_kg_s is not None:
            fluids['fluid_' + side] = replace(fluid, u_mps=_native_flow._restore(flow.speeds[index]),
                mass_flow_kg_s=None if targets is not None else fluid.mass_flow_kg_s)
    return replace(config, **fluids).validate(resolved_inlet_speeds=True) if fluids else config


def _drag(result, index, continuous):
    side, extra = result.prepared.values.sides[index], result.prepared.drag[index]
    value = side.drag_evidence
    metadata = {key: _summary(getattr(value, name)) for name, key in (
        ('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
        ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF'))}
    metadata.update(scale_K=value.scale_permeability, scale_F=value.scale_forchheimer,
                    campaign=native._text(value.campaign), scope=native._text(value.scope))
    for name in ('application_scope', 'fluid'):
        text = native._text(getattr(extra, name))
        if text:
            metadata[name] = text
    if extra.calibration_count:
        metadata['calibration'] = {native._text(item.key): native._text(item.value)
                                   for item in extra.calibration[:extra.calibration_count]}
    if extra.have_selection and extra.selection.scope:
        metadata.update(inlet_u_mps=side.inlet.velocity_m_s, extrapolated=bool(extra.selection.flags & 2))
        for name, key in (('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')):
            values = getattr(extra.selection, name)
            metadata[key] = {'min': values[0], 'max': values[1]}
    if continuous:
        extension = result.drag[index]
        for name in ('transfer_policy', 'geometry_application'):
            text = native._text(getattr(extension, name))
            if text:
                metadata[name] = text
        if extension.have_reference_geometry:
            metadata['reference_geometry_mm'] = dict(zip(('L', 't'), extension.reference_geometry_mm))
    return metadata


def _case(result, config, case_id, side_geometry=None, pore_porosity=None, extrap_reasons=()):
    from .preparation import _zone_data_si
    value = result.prepared.values
    continuous = isinstance(result, native._ContinuousCase)
    spatial = isinstance(result, native._ZonedCase)
    shape = value.nx, value.ny
    grid = {name: native._array(getattr(value, name))
            for name in ('dx', 'dy', 'x_edges', 'y_edges', 'x_breaks', 'y_breaks')}
    for name in ('x_breaks', 'y_breaks'):
        grid[name] = grid[name].tolist()
    grid.update(dimension=2, axis_order=('x', 'y'), length_unit='m')
    design = {key: native._array(getattr(value, name), shape, precision=result.prepared.field_kinds[index].precision)
              for index, (name, key) in enumerate((
                  ('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'), ('total_porosity', 'eps_arr'),
                  ('solid_conductivity', 'K_ss_arr'), ('hydraulic_radius', 'r_h_arr')))}
    if continuous:
        design.update(axis='continuous', eps_f_arr=_native_geometry.split_fields(design['eps_arr'], .5)['epsilon_A'])
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = native._array(result.fluid_conductivity[index], shape)
    if spatial:
        design.update(axis='continuous' if result.kind == 2 else 'grid' if result.kind else 'xy'[result.axis],
                      eps_f_arr=native._array(pore_porosity, shape),
                      A_0_arr=native._array(result.design_area_density_per_m, shape),
                      zone_id=np.ctypeslib.as_array(result.zone_id, shape=(result.cell_count,)).copy().reshape(shape))
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = native._array(result.fluid_conductivity[index], shape)
            design['h_v' + side + '_arr'] = native._array(result.volumetric_transfer[index], shape)
        if result.kind == 0:
            zone_rows, zone_params = [], []
            for region in result.regions[:result.region_count]:
                descriptor = region.region
                row = dict(name=native._text(descriptor.name),
                    y_frac_start=_native_grid._restore(descriptor.bounds[0]),
                    y_frac_end=_native_grid._restore(descriptor.bounds[1]),
                    L_mm=native._restore(descriptor.cell_length_mm, descriptor.cell_kind),
                    t_mm=native._restore(descriptor.wall_thickness_mm, descriptor.wall_kind))
                for index, side in enumerate('AB'):
                    properties = _geometry_values(region.property_geometry[index])
                    for name, key in (*_PROPERTY_NAMES, ('solid_conductivity_W_mK', 'K_ss')):
                        column = [item[0] for item in native._Properties._fields_].index(name)
                        properties[key] = native._restore(getattr(region.properties[index], name),
                                                          region.property_kinds[index][column])
                    row['props_' + side] = properties
                zone_rows.append(row)
                properties = row['props_A']
                zone_params.append({**{key: row[key] for key in ('name', 'y_frac_start', 'y_frac_end', 'L_mm', 't_mm')},
                    **{key: properties[key] for key in ('epsilon', 'D_h', 'A_0', 'mu', 'rho')},
                    'r_h': _native_geometry.hydraulic_radius(properties['D_h'])[()]})
            design['zone_params'] = _zone_data_si(zone_params)
        elif result.kind == 1:
            cells = config.zones.grid['cells']
            design['grid_cells'] = _zone_data_si(dict(grid_cells=cells))['grid_cells']
            for axis in 'xy':
                design[axis + '_bounds'] = sorted({cell[axis + end] for cell in cells for end in ('0', '1')} - {0., 1.})
    uniform = {key: getattr(value, name) for name, key in (
        ('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
        ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'), ('uniform_solid_conductivity', 'K_ss'))}
    co2_geometry = bool(result.prepared.co2.active)
    for name in (('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h') if co2_geometry else ('A_0', 'D_h')):
        uniform[name] = np.float64(uniform[name])
    uniform['K_ss'] = native._restore(value.uniform_solid_conductivity, result.prepared.property_kinds[0][12])
    thermal = dict(uniform=uniform, fields=None, split_A=value.split_a, side_geometry=None)
    if continuous or spatial:
        thermal['fields'] = dict(A_0=native._array(result.area_density_per_m, shape),
            D_h=native._array(result.hydraulic_diameter_m, shape),
            epsilon=native._array(result.thermal_porosity, shape) if spatial else design['eps_arr'])
    geometry = config.geometry
    # Native preparation has already emitted these nominal-grid events.
    with np.errstate(all='ignore'):
        dx, dy = geometry.L_dom_m/config.solver.Nx, geometry.H_dom_m/config.solver.Ny
    params = dict(L=geometry.L_dom_m, H=geometry.H_dom_m, N_x=value.nx, N_y=value.ny,
        dx=dx, dy=dy,
        u_A=config.fluid_A.u_mps, u_B=config.fluid_B.u_mps,
        T_inA=config.fluid_A.T_in_K, T_inB=config.fluid_B.T_in_K, T_s_init=config.solver.T_s_init_K,
        envelope_mode=getattr(config, 'envelope_mode', 'raise'), tpms_type=geometry.tpms,
        L_cell_m=native._restore(value.cell_length_m, result.prepared.input_kinds.cell_length),
        t_wall_m=native._restore(value.wall_thickness_m, result.prepared.input_kinds.wall_thickness),
        k_s=geometry.k_s_W_mK, eps=uniform['epsilon'], r_h=np.float64(value.hydraulic_radius_m),
        z_axis='continuous' if continuous else 'y',
        continuous_field=dict(config.zones.config) if continuous else None,
        fluid_A=config.fluid_A.type, fluid_B=config.fluid_B.type, warnings_list=[], extrap_reasons=list(extrap_reasons),
        _environment=capture_environment(), thermal_geometry=thermal,
        zone_config='continuous' if continuous else None, flow_inputs={}, boundary_openings={}, static_properties={})
    if spatial:
        params['z_axis'] = config.zones.axis
        if result.kind == 0:
            model = asdict(config.zones.config) if hasattr(config.zones.config, '__dataclass_fields__') else config.zones.config
            params['zone_config'] = _zone_data_si(dict(zones=zone_rows, tpms_type=model['tpms_type'], k_s=model['k_s']))
        else:
            params['zone_config'] = 'grid'
    params['run_settings'] = _zone_data_si(config.to_dict())
    params['run_settings'].pop('zones')
    for index, side in enumerate('AB'):
        port = bc_to_dict(getattr(config, 'bc_' + side), geometry.L_dom_m, geometry.H_dom_m, side='A')
        params['cfg' + side], params['dir_' + side] = port, port['dir']
        inlet = value.sides[index]
        flow = {key: native._array(getattr(inlet, name)) for name, key in (
            ('cross_widths', 'dx'), ('stream_widths', 'dy'), ('row_permeability', 'K_m2'), ('row_forchheimer', 'cF_per_m'))}
        seed_type = np.float64 if getattr(config, 'fluid_' + side).type == 'co2' else float
        flow.update(seed_K_m2=seed_type(inlet.seed_permeability_m2),
                    seed_cF_per_m=seed_type(inlet.seed_forchheimer_per_m),
                    metadata=_drag(result, index, continuous))
        if continuous:
            field_shape = inlet.cross_widths.size, inlet.stream_widths.size
            flow.update(K_field_m2=native._array(inlet.permeability, field_shape),
                        cF_field_per_m=native._array(inlet.forchheimer, field_shape))
        params['flow_inputs'][side] = flow
        params['boundary_openings'][side] = {key: native._array(getattr(inlet, name)) for name, key in (
            ('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'),
            ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac'))}
        properties = dict(uniform) if side_geometry is None else dict(side_geometry[index])
        for name, key in (('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
                          ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'),
                          ('pressure_gradient_Pa_m', 'dP_per_L'), ('surface_transfer_W_m2K', 'H_sf'),
                          ('fluid_conductivity_W_mK', 'K_ff'), ('solid_conductivity_W_mK', 'K_ss')):
            column = [item[0] for item in native._Properties._fields_].index(name)
            properties[key] = native._restore(getattr(inlet.properties, name), result.prepared.property_kinds[index][column])
        params['static_properties'][side] = properties
    params['static_properties']['geometry'] = uniform
    refs = tuple(ModelRef(native._text(model.name), native._text(model.version),
        {'fluid': getattr(config, 'fluid_' + 'AB'[index]).type, 'sco2_nu': asdict(config.sco2_nu)}
        if index < 2 else {'topology': geometry.tpms} if index == 3 else {},
        applicability='side ' + 'AB'[index] if index < 2 else '') for index, model in enumerate(value.models))
    return CaseData.from_compute_config(case_id, config, grid=grid, design_fields=design, parameters=params,
        model_refs=refs, metadata=dict(preprocessor='two_d_v1', quantity_basis='per_unit_depth',
            model_metadata=model_metadata(result.prepared, result.prepared.sco2_nu, config),
            notices=[native._text(item) for item in result.prepared.notices[:result.prepared.notice_count]],
            design_mode=design['axis'] if continuous or spatial else 'uniform',
            model_roles={'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}))


def _execute(config, operation, *, targets=None, case_id=None, own_metadata=False):
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.shared.models.tpms_props import _resolve_chi_s
    # Preserve the original physical guard before object-key checks.
    from sjtu_tpmshx.shared.models.tpms_calc import validate_fluid_type
    for side in 'AB':
        validate_fluid_type(getattr(config, 'fluid_' + side).type, side)
    source = _input(config, targets, operation)
    chi_error = None
    try:
        chi = _resolve_chi_s()
    except ValueError as problem:
        chi, chi_error = None, problem
    allow = config.extrap.allow or os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    options = native._Options(1, ct.sizeof(native._Options), chi is not None, allow, chi or 0.)
    metadata = {}
    extrap_reasons = []
    cache_buffers, cache_keys, side_geometry = [], {}, {}
    from sjtu_tpmshx.shared.models.tpms_geometry import _compute_geometry_cached
    from sjtu_tpmshx.shared.models.tpms_calc import _compute_cached, _InletCacheValue
    co2 = 'co2' in (config.fluid_A.type, config.fluid_B.type)
    geometry_key = (config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128)

    def geometry_cache(action, value):
        if action:
            _compute_geometry_cached.store(geometry_key, None, _geometry_values(value))
            hit = False
        else:
            hit, saved = _compute_geometry_cached.lookup(geometry_key)
            if hit:
                for name, key in _GEOMETRY_NAMES:
                    setattr(value, name, saved[key])
        if (action or hit) and chi_error is not None:
            raise chi_error
        return hit

    def inlet_cache(action, side, inlet, speed_kind, value):
        if not action:
            fluid = getattr(config, 'fluid_' + 'AB'[side])
            speed = native._restore(inlet.velocity_m_s, speed_kind) if (
                targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
            key = (config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm,
                   speed, fluid.T_in_K, fluid.P_in_Pa, fluid.type, config.sco2_nu, co2)
            cache_keys[side] = key
            hit, saved = _compute_cached.lookup(key)
            if not hit:
                return False
            properties, records = saved
            for name, key in _GEOMETRY_NAMES:
                setattr(value.geometry, name, properties[key])
            for name, key in (*_PROPERTY_NAMES, ('cp', None), ('pr', None)):
                scalar = properties[key] if key is not None else getattr(saved, name)
                setattr(value.properties, name, scalar)
                column = [item[0] for item in native._Properties._fields_].index(name)
                value.kinds[column] = _kind(scalar)
            value.evidence, buffers = _cache_record_view(records)
            cache_buffers.extend(buffers)
            side_geometry[side] = _geometry_values(value.geometry, co2)
            return True
        properties = _geometry_values(value.geometry, co2)
        for name, key in _PROPERTY_NAMES:
            column = [item[0] for item in native._Properties._fields_].index(name)
            properties[key] = native._restore(getattr(value.properties, name), value.kinds[column])
        bound = _records(value.evidence, value.evidence.range_bounds_list)
        records = {key[:-1] if isinstance(record, RangeRecord) else key: record for key, record in bound.items()}
        _compute_cached.store(cache_keys[side], None,
            _InletCacheValue(properties, records, value.properties.cp, value.properties.pr))
        side_geometry[side] = _geometry_values(value.geometry, co2)
        return False

    def observe_range(value, bounds_list, cached, scalar):
        key, record = _range_record(value, bounds_list)
        if key[-1] == ('unbound', 'unbound', 'source'):
            key = (*key[:-1], _range_context.get())
        merge_warnings(current_warnings(), [{key: record}])
        if cached or current_warnings() is not None or scalar is None:
            return
        from sjtu_tpmshx.shared.models import tpms_props, fluid_props, nu_correlations, co2_correlations
        source = key[:-2]
        if source[0] == 'property':
            fluid, property_name = source[1].split('_', 1)
            notice = tpms_props._range_notice(source[1], scalar, scalar, *record.bounds)
            if notice is not None:
                attribute = {'density': 'rho', 'viscosity': 'mu', 'conductivity': 'k', 'cp': 'cp'}[property_name]
                native._source_warning(getattr(fluid_props.get(fluid), attribute), notice)
        elif source[0] in ('nu', 'nu_pr') and native._text(value.stage) == 'inlet':
            fluid, topology = source[1:]
            if fluid == 'air':
                notices = nu_correlations._extrap_notices(topology, scalar, scalar)
                origin = fluid_props._nu_air
            elif fluid == 'water':
                notices = nu_correlations._water_nu_notices(scalar, scalar, topology)
                origin = fluid_props._nu_water
            elif fluid == 'sco2':
                notices = nu_correlations._sco2_nu_notices(scalar, scalar, topology)
                origin = (nu_correlations.nu_sco2_selected if config.sco2_nu.mode != 'cfd_smooth'
                          else nu_correlations.nu_sco2_topo)
            else:
                notices = ([co2_correlations._calibration_notice(record.quantity, record.bounds)]
                           if scalar < record.bounds[0] or scalar > record.bounds[1] else [])
                origin = fluid_props._nu_co2
            for notice in notices:
                native._source_warning(origin, notice)

    def observe_notice(kind, side, value, message):
        if kind == 1:
            record_warning(('nu_preflight', 'AB'[side]), message)
        elif kind == 2:
            extrap_reasons.append(message)
        elif kind == 0:
            if current_warnings() is None:
                from sjtu_tpmshx.shared.models import tpms_calc
                fluid = getattr(config, 'fluid_' + 'AB'[side]).type
                notice = tpms_calc._reynolds_notice(config.geometry.tpms, value, fluid)
                if notice is not None:
                    native._source_warning(tpms_calc.compute, notice, call='_compute_cached')
        else:
            raise RuntimeError(f'unknown preparation notice kind {kind}')

    def nominal_grid_warning(axis, message):
        from .preparation import _parse_geometry_inputs_cfg
        native._source_warning(_parse_geometry_inputs_cfg, message,
                               binary=('/', int(axis == 'y')), category=RuntimeWarning)

    with ExitStack() as scopes:
        def host_input(stage, side):
            if stage == 0:
                if own_metadata:
                    metadata['provenance'] = api.source_context()
                    metadata['records'] = scopes.enter_context(api.warning_scope({}))
            elif stage == 1:
                if 'co2' not in (config.fluid_A.type, config.fluid_B.type):
                    hash((config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128))
                if co2 and chi_error is not None:
                    raise chi_error
            elif stage == 2:
                fluid = getattr(config, 'fluid_' + 'AB'[side])
                speed = 0. if targets is not None or fluid.mass_flow_kg_s is not None else fluid.u_mps
                hash((config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm,
                      speed, fluid.T_in_K, fluid.P_in_Pa, config.sco2_nu,
                      'co2' in (config.fluid_A.type, config.fluid_B.type)))
            elif stage == 3:
                if source._grid_error is not None:
                    raise TypeError(source._grid_error)
            elif stage == 4:
                if config.zones.axis != 'grid' and config.zones.config is None:
                    raise ValueError('Enabled 1D zones require a ZoneConfig')
            else:
                raise RuntimeError(f'unknown preparation host stage {stage}')

        spatial = source.abi_version == 9
        bridge = PreparationCacheBridge(config, chi_error) if spatial else None
        hooks = dict(geometry_cache_at=bridge.geometry_at, inlet_cache_at=bridge.inlet_at,
                     sigmoid_lut_cache=_lut_cache(), observe_range=bridge.observe_range,
                     observe_notice=bridge.observe_notice) if spatial else dict(
                         geometry_cache=geometry_cache, inlet_cache=inlet_cache,
                         observe_range=observe_range, observe_notice=observe_notice)
        with native.operation(operation, source, options, host_input,
                              nominal_grid_warning=nominal_grid_warning, **hooks) as result:
            if spatial:
                flow = result.values.flow
                if operation == 'prepare_flow_case':
                    flow = flow.flow
            else:
                flow = result.flow if hasattr(result, 'flow') else result
            if operation == 'prepare_inlet_mass_capacities':
                return {side: _native_flow._restore(flow.capacities[index]) for index, side in enumerate('AB')}
            resolved = _resolved(config, flow, targets)
            if operation == 'resolve_inlet_flow':
                return resolved
            resolved = ComputeConfig.from_dict(asdict(resolved))
            if spatial:
                for index, side in enumerate('AB'):
                    fluid = getattr(resolved, 'fluid_' + side)
                    key = (resolved.geometry.tpms, resolved.geometry.L_cell_mm, resolved.geometry.t_wall_mm,
                           fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa, fluid.type, resolved.sco2_nu, False)
                    side_geometry[index] = bridge.inlet_geometry[key]
                prepared = result.values.prepared
                if isinstance(result, native._SigmoidHostCase):
                    prepared = prepared.values
                case = _case(prepared, resolved, case_id, side_geometry, result.design_pore_porosity, bridge.extrap_reasons)
            else:
                case = _case(result, resolved, case_id, side_geometry, extrap_reasons=extrap_reasons)
            return api._finish_metadata(case, metadata['provenance'], metadata['records']) if own_metadata else case


def prepare_case(config, *, case_id):
    config = ComputeConfig.from_dict(asdict(config))
    return _execute(config, 'prepare_flow_case', case_id=case_id)


def prepare_mass_flow_case(config, targets, *, case_id):
    config = deepcopy(config).validate_static_inputs()
    explicit = (tuple(targets[side] for side in 'AB')
                if all(getattr(config, 'fluid_' + side).mass_flow_kg_s is None for side in 'AB') else None)
    return _execute(config, 'prepare_flow_case', targets=explicit, case_id=case_id, own_metadata=True)


def capacities(config):
    return _execute(config, 'prepare_inlet_mass_capacities')


def resolve(config, *, targets=None):
    return _execute(deepcopy(config).validate_static_inputs(), 'resolve_inlet_flow', targets=targets)
