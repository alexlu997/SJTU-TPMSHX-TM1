"""Prepare planar cases, inlet speeds and capacities with the native stage."""
from copy import deepcopy
from dataclasses import asdict
import os
import ctypes as ct

import numpy as np

from sjtu_tpmshx.data_types.case_data import CaseData
from sjtu_tpmshx.data_types.compute_config import ComputeConfig
from sjtu_tpmshx.data_types.model_refs import ModelRef
from sjtu_tpmshx.run_control.run_environment import capture_environment
from . import _native_geometry, _native_preparation_case as native, preparation_host as host
from ._native_values import TOPOLOGIES, count, geometry_topology, borrow_text, copy_array, read_text, real_array, real_scalar


def _real(value, name):
    """Normalize one real input. Native validation rejects nonfinite physical inputs."""
    return real_scalar(value, name=name, allow_nonfinite=True)


def _input(config, targets, operation):
    geometry = config.geometry
    value = native._InputV1(1, ct.sizeof(native._InputV1), _real(geometry.L_dom_m, 'geometry.L_dom_m'),
        _real(geometry.H_dom_m, 'geometry.H_dom_m'), count(config.solver.Nx, name='solver.Nx'),
        count(config.solver.Ny, name='solver.Ny'), config.flags.port_wall_refine,
        geometry_topology(geometry.tpms), _real(geometry.L_cell_mm, 'geometry.L_cell_mm'),
        _real(geometry.t_wall_mm, 'geometry.t_wall_mm'), _real(geometry.k_s_W_mK, 'geometry.k_s_W_mK'),
        _real(geometry.delta_levelset, 'geometry.delta_levelset'))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        # Capacity queries never consume an obsolete inlet speed.
        speed = 0. if operation == 'prepare_inlet_mass_capacities' or (
            targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
        prefix = 'fluid_' + side + '.'
        mass = fluid.mass_flow_kg_s
        windows = (_real(getattr(port, name), f'bc_{side}.{name}') for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w'))
        value.sides[index] = native._Inlet(native._FLUIDS.index(fluid.type), _real(speed, prefix + 'u_mps'),
            _real(fluid.T_in_K, prefix + 'T_in_K'), _real(fluid.P_in_Pa, prefix + 'P_in_Pa'),
            native._Port(port.dir, *windows, port.uniform_inlet_2d),
            mass is not None, 0. if mass is None else _real(mass, prefix + 'mass_flow_kg_s'))
    value.have_physical_depth = geometry.Lz_m is not None
    value.physical_depth_m = 0. if geometry.Lz_m is None else _real(geometry.Lz_m, 'geometry.Lz_m')
    value.geometry_mode = int(config.zones.enabled)
    value.df_mode = int(config.df_mode == 'experimental')
    typed = native._InputV2(2, ct.sizeof(native._InputV2), value)
    buffers = []
    host.pack_nu(typed.sco2_nu, config.sco2_nu, buffers)
    flow = native._FlowInput(3, ct.sizeof(native._FlowInput), typed)
    flow.have_explicit_targets = targets is not None
    if targets is not None:
        for index, side in enumerate('AB'):
            flow.explicit_targets_kg_s[index] = _real(targets[index], f'mass_flow_{side}_kg_s')
    if config.zones.enabled and config.zones.axis == 'continuous':
        spec = config.zones.config
        decision = real_array(spec['x_decision'], name='x_decision', allow_nonfinite=True)
        controls = native._Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['spline_order'], spec['symmetric_y'],
            (native._D * 2)(*(_real(item, 'L_bounds') for item in spec['L_bounds'])),
            (native._D * 2)(*(_real(item, 't_bounds') for item in spec['t_bounds'])),
            native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size))
        source = native._ContinuousInput(4, ct.sizeof(native._ContinuousInput), flow, controls)
        buffers.append(decision)
    elif config.zones.enabled:
        source = _spatial_input(config, flow, buffers)
    else:
        source = flow
    source._buffers = buffers
    return source


def _spatial_input(config, flow, buffers):
    zones = config.zones
    zone_error = None
    sigmoid = zones.axis == 'grid' and zones.pareto_x_decision is not None
    if zones.axis == 'grid':
        model = dict(k_s=config.geometry.k_s_W_mK) if sigmoid else zones.grid
        rows = [('', [cell[key] for key in ('x0', 'x1', 'y0', 'y1')],
                 config.geometry.L_cell_mm if sigmoid else cell['L'],
                 config.geometry.t_wall_mm if sigmoid else cell['t']) for cell in zones.grid['cells']]
    else:
        model = asdict(zones.config) if hasattr(zones.config, '__dataclass_fields__') else zones.config
        if isinstance(zones.config, dict):
            from sjtu_tpmshx.physical_models.zone_config import Zone, ZoneConfig
            try:
                zone_data = deepcopy(model)
                zone_data['zones'] = [Zone(**row) for row in zone_data['zones']]
                ZoneConfig(**zone_data)
            except (KeyError, TypeError) as error:
                # Keep constructor errors at the original region checkpoint.
                zone_error = error
                model = None
        if model is None:
            model = dict(zones=[], k_s=config.geometry.k_s_W_mK)
        rows = [(row['name'], [row['y_frac_start'], row['y_frac_end'], 0., 0.], row['L_mm'], row['t_mm'])
                for row in model['zones']]
    regions = []
    for name, bounds, cell, wall in rows:
        regions.append(native._Region(borrow_text(name, buffers),
            (native._D * 4)(*(_real(item, 'zone bounds') for item in bounds)),
            _real(cell, 'zone L_mm'), _real(wall, 'zone t_mm')))
    regions = (native._Region * len(regions))(*regions)
    buffers.append(regions)
    values = flow.values
    values.values.geometry_mode = 2
    zoned = native._ZonedInput(5, ct.sizeof(native._ZonedInput), values,
        int(zones.axis == 'grid'), int(zones.axis == 'y'), regions, len(regions))
    if sigmoid:
        decision = real_array(zones.pareto_x_decision, name='pareto_x_decision', allow_nonfinite=True)
        buffers.append(decision)
        controls = native._SigmoidControls(native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size),
            _real(zones.pareto_y_trans_inlet, 'pareto_y_trans_inlet'),
            _real(zones.pareto_y_trans_outlet, 'pareto_y_trans_outlet'))
        zoned = native._SigmoidInput(6, ct.sizeof(native._SigmoidInput), zoned, controls, native._LUTView())
        flow_type, host_type = native._SigmoidFlowInput, native._SigmoidHostInput
    else:
        flow_type, host_type = native._ZonedFlowInput, native._ZonedHostInput
    spatial_flow = flow_type(8, ct.sizeof(flow_type), zoned, flow.have_explicit_targets, flow.explicit_targets_kg_s)
    source = host_type(9, ct.sizeof(host_type), spatial_flow,
        native._SpatialModel(_real(model['k_s'], 'k_s'), bool(config.extrap.allow), sigmoid))
    source._zone_error = zone_error
    return source


def _lut_cache():
    from sjtu_tpmshx.physical_models import sigmoid_field
    from sjtu_tpmshx.cpp_interface import _native_lut
    buffers, pending = [], {}

    def cache(action, topology, resolution, value):
        name = TOPOLOGIES[topology]
        key = (name,)
        if action:
            lut = pending.pop(key)
            shape = len(lut.L_vals), len(lut.t_vals)
            lut.eps_table = copy_array(value.porosity, shape)
            lut.A0_table = copy_array(value.area_density_per_m, shape)
            lut._save()
            lut._native_lut = _native_lut.LUT(lut.L_vals, lut.t_vals, lut.eps_table, lut.A0_table)
            sigmoid_field._lut_cache[key] = lut
            return False
        lut = sigmoid_field._lut_cache.get(key)
        if lut is None:
            lut = object.__new__(sigmoid_field.GeometryLUT)
            lut.L_vals, lut.t_vals = copy_array(value.cell_mm), copy_array(value.wall_mm)
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


def _case(result, config, case_id, side_geometry=None, pore_porosity=None, extrap_reasons=(), thermal_sides=None,
          *, region_radii=None):
    from sjtu_tpmshx.physical_models.zone_units import _zone_data_si
    value = result.prepared.values
    continuous = isinstance(result, native._ContinuousCase)
    spatial = isinstance(result, native._ZonedCase)
    shape = value.nx, value.ny
    grid = {name: copy_array(getattr(value, name))
            for name in ('dx', 'dy', 'x_edges', 'y_edges', 'x_breaks', 'y_breaks')}
    for name in ('x_breaks', 'y_breaks'):
        grid[name] = grid[name].tolist()
    grid.update(dimension=2, axis_order=('x', 'y'), length_unit='m')
    design = {key: copy_array(getattr(value, name), shape)
              for name, key in (
                  ('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'), ('total_porosity', 'eps_arr'),
                  ('solid_conductivity', 'K_ss_arr'), ('hydraulic_radius', 'r_h_arr'))}
    if continuous:
        eps_f = (copy_array(pore_porosity, shape) if pore_porosity is not None else
                 _native_geometry.split_fields(design['eps_arr'], .5)['epsilon_A'])
        design.update(axis='continuous', eps_f_arr=eps_f)
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = copy_array(result.fluid_conductivity[index], shape)
    if spatial:
        design.update(axis='continuous' if result.kind == 2 else 'grid' if result.kind else 'xy'[result.axis],
                      eps_f_arr=copy_array(pore_porosity, shape),
                      A_0_arr=copy_array(result.design_area_density_per_m, shape),
                      zone_id=np.ctypeslib.as_array(result.zone_id, shape=(result.cell_count,)).copy().reshape(shape))
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = copy_array(result.fluid_conductivity[index], shape)
            design['h_v' + side + '_arr'] = copy_array(result.volumetric_transfer[index], shape)
        if result.kind == 0:
            zone_rows, zone_params = [], []
            if region_radii is not None:
                region_radii = copy_array(region_radii, (result.region_count,))
            for zone_index, region in enumerate(result.regions[:result.region_count]):
                descriptor = region.region
                row = dict(name=read_text(descriptor.name),
                    y_frac_start=descriptor.bounds[0], y_frac_end=descriptor.bounds[1],
                    L_mm=descriptor.cell_length_mm, t_mm=descriptor.wall_thickness_mm)
                for index, side in enumerate('AB'):
                    properties = host._geometry_values(region.property_geometry[index])
                    for name, key in (*host._PROPERTY_NAMES, ('solid_conductivity_W_mK', 'K_ss')):
                        properties[key] = getattr(region.properties[index], name)
                    row['props_' + side] = properties
                zone_rows.append(row)
                properties = row['props_A']
                zone_params.append({**{key: row[key] for key in ('name', 'y_frac_start', 'y_frac_end', 'L_mm', 't_mm')},
                    **{key: properties[key] for key in ('epsilon', 'D_h', 'A_0', 'mu', 'rho')},
                    'r_h': (region_radii[zone_index] if region_radii is not None else
                            _native_geometry.hydraulic_radius(properties['D_h'])[()])})
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
    thermal = dict(uniform=uniform, fields=None, split_A=value.split_a, side_geometry=None)
    if thermal_sides is not None and thermal_sides.have_side_geometry:
        thermal['side_geometry'] = {side: tuple(thermal_sides.side_geometry[index]) for index, side in enumerate('AB')}
    if continuous or spatial:
        thermal['fields'] = dict(A_0=copy_array(result.area_density_per_m, shape),
            D_h=copy_array(result.hydraulic_diameter_m, shape),
            epsilon=copy_array(result.thermal_porosity, shape) if spatial else design['eps_arr'])
    geometry = config.geometry
    # Native preparation has already emitted these nominal-grid events.
    with np.errstate(all='ignore'):
        dx, dy = geometry.L_dom_m/config.solver.Nx, geometry.H_dom_m/config.solver.Ny
    params = dict(L=geometry.L_dom_m, H=geometry.H_dom_m, N_x=value.nx, N_y=value.ny,
        dx=dx, dy=dy,
        u_A=config.fluid_A.u_mps, u_B=config.fluid_B.u_mps,
        T_inA=config.fluid_A.T_in_K, T_inB=config.fluid_B.T_in_K, T_s_init=config.solver.T_s_init_K,
        envelope_mode=getattr(config, 'envelope_mode', 'raise'), tpms_type=geometry.tpms,
        L_cell_m=value.cell_length_m, t_wall_m=value.wall_thickness_m,
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
        inlet = value.sides[index]
        native_port = inlet.inlet.port
        port = host.prepared_port(native_port.direction,
            (native_port.inlet_center_m, native_port.outlet_center_m),
            (native_port.inlet_width_m, native_port.outlet_width_m))
        if native_port.uniform_inlet:
            port['uniform_inlet_2d'] = True
        params['cfg' + side], params['dir_' + side] = port, port['dir']
        flow = {key: copy_array(getattr(inlet, name)) for name, key in (
            ('cross_widths', 'dx'), ('stream_widths', 'dy'), ('row_permeability', 'K_m2'), ('row_forchheimer', 'cF_per_m'))}
        seed_type = np.float64 if getattr(config, 'fluid_' + side).type == 'co2' else float
        flow.update(seed_K_m2=seed_type(inlet.seed_permeability_m2),
                    seed_cF_per_m=seed_type(inlet.seed_forchheimer_per_m),
                    metadata=host.drag_application_metadata(inlet.drag_evidence, result.prepared.drag[index],
                        inlet.inlet.velocity_m_s, result.drag[index] if continuous else None))
        if continuous:
            field_shape = inlet.cross_widths.size, inlet.stream_widths.size
            flow.update(K_field_m2=copy_array(inlet.permeability, field_shape),
                        cF_field_per_m=copy_array(inlet.forchheimer, field_shape))
        params['flow_inputs'][side] = flow
        params['boundary_openings'][side] = {key: copy_array(getattr(inlet, name)) for name, key in (
            ('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'),
            ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac'))}
        properties = dict(uniform) if side_geometry is None else dict(side_geometry[index])
        for name, key in (('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
                          ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'),
                          ('pressure_gradient_Pa_m', 'dP_per_L'), ('surface_transfer_W_m2K', 'H_sf'),
                          ('fluid_conductivity_W_mK', 'K_ff'), ('solid_conductivity_W_mK', 'K_ss')):
            properties[key] = getattr(inlet.properties, name)
        params['static_properties'][side] = properties
    params['static_properties']['geometry'] = uniform
    refs = tuple(ModelRef(read_text(model.name), read_text(model.version),
        {'fluid': getattr(config, 'fluid_' + 'AB'[index]).type, 'sco2_nu': asdict(config.sco2_nu)}
        if index < 2 else {'topology': geometry.tpms} if index == 3 else {},
        applicability='side ' + 'AB'[index] if index < 2 else '') for index, model in enumerate(value.models))
    return CaseData.from_compute_config(case_id, config, grid=grid, design_fields=design, parameters=params,
        model_refs=refs, metadata=dict(preprocessor='two_d_v1', quantity_basis='per_unit_depth',
            model_metadata=host.model_metadata(result.prepared, result.prepared.sco2_nu, config),
            notices=[read_text(item) for item in result.prepared.notices[:result.prepared.notice_count]],
            design_mode=design['axis'] if continuous or spatial else 'uniform',
            model_roles={'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}))


def _execute(config, operation, *, targets=None, case_id=None, start_observations=None):
    from sjtu_tpmshx.preprocess.two_d.preparation import _nominal_grid_warning
    from sjtu_tpmshx.run_control.run_environment import _resolve_chi_s
    # Preserve the original physical guard before object-key checks.
    for side in 'AB':
        host.validate_fluid_type(getattr(config, 'fluid_' + side).type, side)
    source = _input(config, targets, operation)
    chi_error = None
    try:
        chi = _resolve_chi_s()
    except ValueError as problem:
        chi, chi_error = None, problem
    allow = config.extrap.allow or os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    options = native._Options(1, ct.sizeof(native._Options), chi is not None, allow, chi or 0.)
    bridge = host.PreparationCacheBridge(config, chi_error)
    cache_keys, side_geometry = {}, {}
    co2 = 'co2' in (config.fluid_A.type, config.fluid_B.type)
    geometry_key = (config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128)

    def geometry_cache(action, value):
        return bridge.geometry(action, geometry_key, value)

    def inlet_cache(action, side, inlet, value):
        if not action:
            fluid = getattr(config, 'fluid_' + 'AB'[side])
            speed = inlet.velocity_m_s if (
                targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
            cache_keys[side] = (*geometry_key[:3], speed, fluid.T_in_K, fluid.P_in_Pa,
                                fluid.type, config.sco2_nu, co2)
        key = cache_keys[side]
        hit = bridge.inlet(action, key, value, co2)
        if action or hit:
            side_geometry[side] = bridge.inlet_geometry[key]
        return hit

    def host_input(stage, side):
        if stage == 0:
            if start_observations is not None:
                start_observations()
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
            pass
        elif stage == 4:
            if config.zones.axis != 'grid' and config.zones.config is None:
                raise ValueError('Enabled 1D zones require a ZoneConfig')
            if source._zone_error is not None:
                raise source._zone_error
        else:
            raise RuntimeError(f'unknown preparation host stage {stage}')

    spatial = source.abi_version == 9
    hooks = dict(geometry_cache_at=bridge.geometry_at, inlet_cache_at=bridge.inlet_at,
                 sigmoid_lut_cache=_lut_cache(), observe_range=bridge.observe_range,
                 observe_notice=bridge.observe_notice) if spatial else dict(
                     geometry_cache=geometry_cache, inlet_cache=inlet_cache,
                     observe_range=bridge.observe_range, observe_notice=bridge.observe_notice)
    with host.operation(operation, source, options, host_input,
                          nominal_grid_warning=_nominal_grid_warning, **hooks) as result:
        pore_porosity = region_radii = thermal_sides = None
        if isinstance(result, native._ContinuousGeometryCase):
            pore_porosity, result = result.design_pore_porosity, result.values
        elif isinstance(result, native._StripeGeometryCase):
            region_radii, result = result.region_hydraulic_radii_m, result.values
        if result.abi_version == 10:
            thermal_sides, result = result.thermal, result.values
        if spatial:
            flow = result.values.flow
            if operation == 'prepare_flow_case':
                flow = flow.flow
        else:
            flow = result.flow if hasattr(result, 'flow') else result
        if operation == 'prepare_inlet_mass_capacities':
            return {side: flow.capacities[index] for index, side in enumerate('AB')}
        resolved = host.resolved_flow_config(config, flow, targets)
        if operation == 'resolve_inlet_flow':
            return resolved
        resolved = ComputeConfig.from_dict(asdict(resolved), _native_preparation=True)
        if spatial:
            for index, side in enumerate('AB'):
                fluid = getattr(resolved, 'fluid_' + side)
                key = (resolved.geometry.tpms, resolved.geometry.L_cell_mm, resolved.geometry.t_wall_mm,
                       fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa, fluid.type, resolved.sco2_nu, False)
                side_geometry[index] = bridge.inlet_geometry[key]
            prepared = result.values.prepared
            if isinstance(result, native._SigmoidHostCase):
                prepared = prepared.values
            case = _case(prepared, resolved, case_id, side_geometry, result.design_pore_porosity,
                         bridge.extrap_reasons, thermal_sides, region_radii=region_radii)
        else:
            case = _case(result, resolved, case_id, side_geometry, pore_porosity, bridge.extrap_reasons, thermal_sides)
        return case


def prepare_case(config, *, case_id):
    config = ComputeConfig.from_dict(asdict(config), _native_preparation=True)
    if config.is_3d:
        raise ValueError('2D preparation requires solver.Nz == 1')
    return _execute(config, 'prepare_flow_case', case_id=case_id)


def prepare_mass_flow_case(config, targets, *, case_id, start_observations):
    config = deepcopy(config).validate_static_inputs()
    explicit = (tuple(targets[side] for side in 'AB')
                if all(getattr(config, 'fluid_' + side).mass_flow_kg_s is None for side in 'AB') else None)
    return _execute(config, 'prepare_flow_case', targets=explicit, case_id=case_id,
                    start_observations=start_observations)


def capacities(config):
    return _execute(config, 'prepare_inlet_mass_capacities')


def resolve(config, *, targets=None):
    return _execute(deepcopy(config).validate_static_inputs(), 'resolve_inlet_flow', targets=targets)
