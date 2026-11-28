"""Prepare a full planar case and its inlet flows."""
import os
import warnings
from copy import deepcopy
from dataclasses import asdict
import numpy as np
from tm1.cpp_interface import native_preparation
from tm1.data_types.compute_config import ComputeConfig
from .. import preparation as shared

def _nominal_grid_warning(axis, message):
    # The default warning filter uses the line number to distinguish the two axes.
    if axis == 'x':
        warnings.warn(message, RuntimeWarning)
    else:
        warnings.warn(message, RuntimeWarning)


__all__ = ["prepare_case", "prepare_mass_flow_case", "capacities", "resolve"]


def _spatial_rows(config):
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
            from tm1.physical_models.zone_config import Zone, ZoneConfig
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
    return model, rows, sigmoid, zone_error



def _case(result, copy_metadata, config, case_id, extrap_reasons=()):
    from tm1.data_types.case_data import CaseData
    from tm1.data_types.model_refs import ModelRef
    from tm1.physical_models.zone_units import _zone_data_si
    from tm1.run_control.run_environment import capture_environment
    value = result.prepared
    continuous, spatial = result.continuous, result.spatial
    grid = {name: getattr(value, name) for name in ('dx', 'dy', 'x_edges', 'y_edges', 'x_breaks', 'y_breaks')}
    for name in ('x_breaks', 'y_breaks'):
        grid[name] = grid[name].tolist()
    grid.update(dimension=2, axis_order=('x', 'y'), length_unit='m')
    design = {key: getattr(value, name)
              for name, key in (
                  ('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'), ('total_porosity', 'eps_arr'),
                  ('solid_conductivity', 'K_ss_arr'), ('hydraulic_radius', 'r_h_arr'))}
    if continuous:
        design.update(axis='continuous', eps_f_arr=result.design_pore_porosity)
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = result.fluid_conductivity[index]
    if spatial:
        design.update(axis='continuous' if result.kind == 2 else 'grid' if result.kind else 'xy'[result.axis],
                      eps_f_arr=result.design_pore_porosity,
                      A_0_arr=result.design_area_density_per_m,
                      zone_id=result.zone_id)
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = result.fluid_conductivity[index]
            design['h_v' + side + '_arr'] = result.volumetric_transfer[index]
        if result.kind == 0:
            zone_rows, zone_params = [], []
            for zone_index, region in enumerate(result.regions):
                descriptor = region.region
                row = dict(name=descriptor.name,
                    y_frac_start=descriptor.bounds[0], y_frac_end=descriptor.bounds[1],
                    L_mm=descriptor.cell_length_mm, t_mm=descriptor.wall_thickness_mm)
                for index, side in enumerate('AB'):
                    properties = shared.geometry_values(region.property_geometry[index])
                    properties.update(zip((*shared.PROPERTIES, 'K_ss'), region.properties[index], strict=True))
                    row['props_' + side] = properties
                zone_rows.append(row)
                properties = row['props_A']
                zone_params.append({**{key: row[key] for key in ('name', 'y_frac_start', 'y_frac_end', 'L_mm', 't_mm')},
                    **{key: properties[key] for key in ('epsilon', 'D_h', 'A_0', 'mu', 'rho')},
                    'r_h': result.region_hydraulic_radii_m[zone_index]})
            design['zone_params'] = _zone_data_si(zone_params)
        elif result.kind == 1:
            cells = config.zones.grid['cells']
            design['grid_cells'] = _zone_data_si(dict(grid_cells=cells))['grid_cells']
            for axis in 'xy':
                design[axis + '_bounds'] = sorted({cell[axis + end] for cell in cells for end in ('0', '1')} - {0., 1.})
    uniform = shared.geometry_values((value.epsilon, value.epsilon_a, value.epsilon_b,
                                      value.area_density_per_m, value.hydraulic_diameter_m), value.co2_active)
    uniform['K_ss'] = value.uniform_solid_conductivity
    thermal = dict(uniform=uniform, fields=None, split_A=value.split_a, side_geometry=None)
    if result.side_geometry is not None:
        thermal['side_geometry'] = dict(zip('AB', result.side_geometry, strict=True))
    if continuous or spatial:
        thermal['fields'] = dict(A_0=result.area_density_per_m,
            D_h=result.hydraulic_diameter_m,
            epsilon=result.thermal_porosity if spatial else design['eps_arr'])
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
        native_port = inlet.port
        port = shared.prepared_port(native_port.direction,
            (native_port.inlet_center_m, native_port.outlet_center_m),
            (native_port.inlet_width_m, native_port.outlet_width_m))
        if native_port.uniform_inlet:
            port['uniform_inlet_2d'] = True
        params['cfg' + side], params['dir_' + side] = port, port['dir']
        flow = {key: getattr(inlet, name) for name, key in (
            ('cross_widths', 'dx'), ('stream_widths', 'dy'), ('row_permeability', 'K_m2'), ('row_forchheimer', 'cF_per_m'))}
        seed_type = np.float64 if getattr(config, 'fluid_' + side).type == 'co2' else float
        flow.update(seed_K_m2=seed_type(inlet.seed_permeability_m2),
                    seed_cF_per_m=seed_type(inlet.seed_forchheimer_per_m),
                    metadata=shared.drag_application_metadata(inlet.drag, inlet.velocity_m_s))
        if continuous:
            flow.update(K_field_m2=inlet.permeability, cF_field_per_m=inlet.forchheimer)
        params['flow_inputs'][side] = flow
        params['boundary_openings'][side] = {key: getattr(inlet, name) for name, key in (
            ('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'),
            ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac'))}
        properties = shared.geometry_values(value.property_geometry[index], value.co2_active)
        properties.update(zip((*shared.PROPERTIES, 'K_ss'), inlet.properties, strict=True))
        params['static_properties'][side] = properties
    params['static_properties']['geometry'] = uniform
    refs = []

    def add_model(index, name, version):
        parameters = ({'fluid': getattr(config, 'fluid_' + 'AB'[index]).type, 'sco2_nu': asdict(config.sco2_nu)}
                      if index < 2 else {'topology': geometry.tpms} if index == 3 else {})
        refs.append(ModelRef(name, version, parameters, applicability='side ' + 'AB'[index] if index < 2 else ''))

    evidence, notices = copy_metadata(add_model)
    return CaseData.from_compute_config(case_id, config, grid=grid, design_fields=design, parameters=params,
        model_refs=tuple(refs), metadata=dict(preprocessor='two_d_v1', quantity_basis='per_unit_depth',
            model_metadata=shared.model_metadata(evidence, config), notices=notices,
            design_mode=design['axis'] if continuous or spatial else 'uniform',
            model_roles={'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}))


def _inlet_speed(operation, targets, fluid):
    # A capacity query must not read an obsolete inlet speed.
    if operation == 'prepare_inlet_mass_capacities' or targets is not None or fluid.mass_flow_kg_s is not None:
        return 0.
    return fluid.u_mps


def _execute(config, operation, *, targets=None, case_id=None, start_observations=None):
    from functools import partial
    from tm1.physical_models.fluid_props import validate_fluid_type, WaterStateError
    from tm1.run_control.run_environment import _resolve_chi_s
    for side in 'AB':
        validate_fluid_type(getattr(config, 'fluid_' + side).type, side)
    source, zone_error = native_preparation.pack_input(config, targets, partial(_inlet_speed, operation, targets), _spatial_rows)
    chi_error = None
    try:
        chi = _resolve_chi_s()
    except ValueError as problem:
        chi, chi_error = None, problem
    allow = config.extrap.allow or os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    observers = shared.PreparationObservers(chi_error, _nominal_grid_warning)

    def host_input(stage, side):
        if stage == 0:
            if start_observations is not None:
                start_observations()
        elif stage == 3:
            pass
        elif stage == 4:
            if config.zones.axis != 'grid' and config.zones.config is None:
                raise ValueError('Enabled 1D zones require a ZoneConfig')
            if zone_error is not None:
                raise zone_error
        else:
            raise RuntimeError(f'unknown preparation host stage {stage}')

    def finish(capacities, speeds, copy_case, copy_metadata):
        if operation == 'prepare_inlet_mass_capacities':
            return {side: capacities[index] for index, side in enumerate('AB')}
        resolved = shared.resolved_flow_config(config, speeds, targets)
        if operation == 'resolve_inlet_flow':
            return resolved
        resolved = ComputeConfig.from_dict(asdict(resolved), _native_preparation=True)
        return _case(copy_case(), copy_metadata, resolved, case_id, observers.extrap_reasons)

    def load_table(topology, resolution, lengths, walls, image):
        from tm1.physical_models.sigmoid_field import load_default_table
        return load_default_table(topology, resolution, lengths, walls, image)

    return native_preparation.run_preparation(operation, source, chi=chi, allow=allow, validate=host_input,
        policy=observers, load_table=load_table, water_error=WaterStateError, finish=finish)


def prepare_case(config, *, case_id):
    config = ComputeConfig.from_dict(asdict(config), _native_preparation=True)
    if config.is_3d:
        raise ValueError('2D preparation requires solver.Nz == 1')
    return _execute(config, 'prepare_flow_case', case_id=case_id)


def _prepare_mass_flow_case(config, targets, *, case_id, start_observations):
    config = deepcopy(config).validate_static_inputs()
    explicit = (tuple(targets[side] for side in 'AB')
                if all(getattr(config, 'fluid_' + side).mass_flow_kg_s is None for side in 'AB') else None)
    return _execute(config, 'prepare_flow_case', targets=explicit, case_id=case_id,
                    start_observations=start_observations)


def prepare_mass_flow_case(config, targets, *, case_id):
    from .._metadata import prepare_fixed_flow_with_metadata
    return prepare_fixed_flow_with_metadata(_prepare_mass_flow_case, config, targets, case_id=case_id)


def capacities(config):
    return _execute(config, 'prepare_inlet_mass_capacities')


def resolve(config, *, targets=None):
    return _execute(deepcopy(config).validate_static_inputs(), 'resolve_inlet_flow',
                    targets=targets)
