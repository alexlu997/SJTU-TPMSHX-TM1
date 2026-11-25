"""Pack full 2D preparation inputs and detach the owned native output."""
import ctypes as ct
from functools import partial
from types import SimpleNamespace

import numpy as np

from . import _native_preparation_case as native, preparation_host as host
from ._native_values import TOPOLOGIES, borrow_text, copy_array, count, geometry_topology, real_array, real_scalar, read_text


def _real(value, name):
    """Normalize one real input. Native validation rejects nonfinite physical inputs."""
    return real_scalar(value, name=name, allow_nonfinite=True)


def pack_input(config, targets, inlet_speed, spatial_rows):
    geometry = config.geometry
    value = native._Input(1, ct.sizeof(native._Input), _real(geometry.L_dom_m, 'geometry.L_dom_m'),
        _real(geometry.H_dom_m, 'geometry.H_dom_m'), count(config.solver.Nx, name='solver.Nx'),
        count(config.solver.Ny, name='solver.Ny'), config.flags.port_wall_refine,
        geometry_topology(geometry.tpms), _real(geometry.L_cell_mm, 'geometry.L_cell_mm'),
        _real(geometry.t_wall_mm, 'geometry.t_wall_mm'), _real(geometry.k_s_W_mK, 'geometry.k_s_W_mK'),
        _real(geometry.delta_levelset, 'geometry.delta_levelset'))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        speed = inlet_speed(fluid)
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
    buffers = []
    host.pack_nu(value.sco2_nu, config.sco2_nu, buffers)
    have_targets = targets is not None
    explicit = (native._D * 2)()
    if have_targets:
        for index, side in enumerate('AB'):
            explicit[index] = _real(targets[index], f'mass_flow_{side}_kg_s')
    zone_error = None
    if config.zones.enabled and config.zones.axis == 'continuous':
        spec = config.zones.config
        decision = real_array(spec['x_decision'], name='x_decision', allow_nonfinite=True)
        controls = native._Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['spline_order'], spec['symmetric_y'],
            (native._D * 2)(*(_real(item, 'L_bounds') for item in spec['L_bounds'])),
            (native._D * 2)(*(_real(item, 't_bounds') for item in spec['t_bounds'])),
            native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size))
        source = native._ContinuousInput(1, ct.sizeof(native._ContinuousInput), value, have_targets, explicit, controls)
        buffers.append(decision)
    elif config.zones.enabled:
        source, zone_error = _spatial_input(config, value, have_targets, explicit, buffers, spatial_rows)
    else:
        source = native._UniformInput(1, ct.sizeof(native._UniformInput), value, have_targets, explicit)
    source._buffers = buffers
    return source, zone_error


def _spatial_input(config, value, have_targets, explicit, buffers, spatial_rows):
    zones = config.zones
    model, rows, sigmoid, zone_error = spatial_rows(config)
    regions = []
    for name, bounds, cell, wall in rows:
        regions.append(native._Region(borrow_text(name, buffers),
            (native._D * 4)(*(_real(item, 'zone bounds') for item in bounds)),
            _real(cell, 'zone L_mm'), _real(wall, 'zone t_mm')))
    regions = (native._Region * len(regions))(*regions)
    buffers.append(regions)
    value.geometry_mode = 2
    kind = int(zones.axis == 'grid')
    axis = int(zones.axis == 'y')
    spatial_model = native._SpatialModel(_real(model['k_s'], 'k_s'), bool(config.extrap.allow), sigmoid)
    if sigmoid:
        decision = real_array(zones.pareto_x_decision, name='pareto_x_decision', allow_nonfinite=True)
        buffers.append(decision)
        controls = native._SigmoidControls(native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size),
            _real(zones.pareto_y_trans_inlet, 'pareto_y_trans_inlet'),
            _real(zones.pareto_y_trans_outlet, 'pareto_y_trans_outlet'))
        source = native._SigmoidInput(1, ct.sizeof(native._SigmoidInput), value, have_targets, explicit,
            kind, axis, regions, len(regions), controls, native._LUTView(), spatial_model)
    else:
        source = native._ZonedInput(1, ct.sizeof(native._ZonedInput), value, have_targets, explicit,
            kind, axis, regions, len(regions), spatial_model)
    return source, zone_error


def _lut_cache(policy):
    buffers = []

    def cache(action, topology, resolution, value):
        def axes():
            return copy_array(value.cell_mm), copy_array(value.wall_mm)

        def tables(shape):
            return copy_array(value.porosity, shape), copy_array(value.area_density_per_m, shape)

        hit = policy(action, TOPOLOGIES[topology], resolution, axes, tables)
        if hit is None:
            return False
        arrays, flags = hit
        value.porosity_fast, value.area_fast = flags
        for name, array in zip(('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m'), arrays):
            array = np.ascontiguousarray(array, dtype=np.float64)
            buffers.append(array)
            setattr(value, name, native._Array(array.ctypes.data_as(ct.POINTER(native._D)), array.size))
        return True

    return cache


def _copy_grids(value, names, shape=None):
    return {name: copy_array(getattr(value, name), shape) for name in names.split()}


def _copy_side(inlet, prepared_drag, extension):
    values = _copy_grids(inlet, 'cross_widths stream_widths row_permeability row_forchheimer '
                                'inlet_geometry outlet_geometry inlet_profile outlet_profile')
    if extension is not None:
        shape = inlet.cross_widths.size, inlet.stream_widths.size
        values.update(_copy_grids(inlet, 'permeability forchheimer', shape))
    return SimpleNamespace(**values, port=host.fixed_record(inlet.inlet.port), velocity_m_s=inlet.inlet.velocity_m_s,
        seed_permeability_m2=inlet.seed_permeability_m2, seed_forchheimer_per_m=inlet.seed_forchheimer_per_m,
        properties=host.property_scalars(inlet.properties),
        drag=host.drag_evidence(inlet.drag_evidence, prepared_drag, extension))


def _copy_case(result):
    """Detach the fields present in this result family while its owner is live."""
    value = result.prepared
    shape = value.nx, value.ny
    continuous = isinstance(result, native._ContinuousCase)
    spatial = isinstance(result, (native._ZonedCase, native._SigmoidCase, native._StripeCase))
    fields = _copy_grids(value, 'dx dy x_edges y_edges x_breaks y_breaks')
    fields.update(_copy_grids(value, 'cell_length wall_thickness total_porosity solid_conductivity hydraulic_radius', shape))
    for name in ('nx', 'ny', 'epsilon', 'epsilon_a', 'epsilon_b', 'area_density_per_m', 'hydraulic_diameter_m',
                 'uniform_solid_conductivity', 'hydraulic_radius_m', 'cell_length_m', 'wall_thickness_m', 'split_a'):
        fields[name] = getattr(value, name)
    try:
        models = [(read_text(item.name), read_text(item.version)) for item in value.models]
    except StopIteration as problem:
        # The original ModelRef iterator exposed this cause for a failed name or version read.
        raise RuntimeError('generator raised StopIteration') from problem
    prepared = SimpleNamespace(**fields, co2_active=bool(value.co2.active),
        models=models, notices=[read_text(item) for item in value.notices[:value.notice_count]],
        model_evidence=host.model_evidence(value, value.sco2_nu),
        sides=[_copy_side(item, value.drag[i], result.drag[i] if continuous else None)
               for i, item in enumerate(value.sides)])
    case = SimpleNamespace(prepared=prepared, continuous=continuous, spatial=spatial, side_geometry=None)
    if not continuous and result.thermal.have_side_geometry:
        case.side_geometry = [tuple(side) for side in result.thermal.side_geometry]
    if continuous or spatial:
        vars(case).update(_copy_grids(result, 'design_pore_porosity area_density_per_m hydraulic_diameter_m', shape))
        case.fluid_conductivity = [copy_array(item, shape) for item in result.fluid_conductivity]
    if spatial:
        case.kind, case.axis = result.kind, result.axis
        vars(case).update(_copy_grids(result, 'thermal_porosity design_area_density_per_m', shape))
        case.zone_id = np.ctypeslib.as_array(result.zone_id, shape=(result.cell_count,)).copy().reshape(shape)
        case.volumetric_transfer = [copy_array(item, shape) for item in result.volumetric_transfer]
        if result.kind == 0:
            case.regions = [SimpleNamespace(region=host.fixed_record(item.region),
                property_geometry=[host.geometry_scalars(row) for row in item.property_geometry],
                properties=[host.property_scalars(row) for row in item.properties])
                for item in result.regions[:result.region_count]]
            case.region_hydraulic_radii_m = copy_array(result.region_hydraulic_radii_m, (result.region_count,))
    return case


def run_preparation(name, source, *, chi, allow, validate, policy, geometry_key, inlet_cache, lut, water_error, finish):
    """Run one planar operation and deliver its flow or detached case to the host."""
    options = native._Options(1, ct.sizeof(native._Options), chi is not None, allow, chi or 0.)
    cache = host.PreparationCacheBridge(policy)
    if isinstance(source, (native._ZonedInput, native._SigmoidInput)):
        hooks = dict(geometry_cache_at=cache.geometry_at, inlet_cache_at=cache.inlet_at, sigmoid_lut_cache=_lut_cache(lut))
    else:
        def inlet(action, side, source_inlet, value):
            def transfer(key):
                return cache.inlet(action, key, value)
            return inlet_cache(action, side, source_inlet.velocity_m_s, transfer)

        hooks = dict(geometry_cache=lambda action, value: cache.geometry(action, geometry_key, value), inlet_cache=inlet)
    with host.operation(name, source, options, validate, water_error, observe_range=policy.observe_range,
                        observe_notice=policy.observe_notice, observe_event=policy.observe_event, **hooks) as result:
        return finish(tuple(result.flow.capacities), tuple(result.flow.speeds), partial(_copy_case, result))
