"""Declare 3D preparation C layouts, pack inputs, and detach owned outputs."""
import ctypes as ct
from types import SimpleNamespace

import numpy as np

from ._native_values import TOPOLOGY_CODES, GridPort, grid_count, read_text, real_array, real_scalar
from . import _native_preparation_case as native, preparation_host as host


_U, _S, _D = native._U, native._S, native._D
_struct, _doubles = native._structure, native._doubles
_Inlet = _struct('Inlet3D', [('fluid', _U), *_doubles('velocity_m_s temperature_K pressure_Pa'),
    ('port', GridPort), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_Input = _struct('Input3D', [('abi_version', _U), ('struct_size', _S),
    ('lengths_m', _D * 3), ('counts', _S * 3), ('max_cells', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *_doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('geometry_mode', _U), ('df_mode', _U),
    ('sco2_nu', native._Nu)])
_Side = _struct('Side3D', [('axes', ct.c_int32 * 7),
    ('inlet_opening', native._Array), ('outlet_opening', native._Array),
    *_doubles('rho mu cp k_f'), ('have_drag_application', _U),
    ('drag_evidence', native._DragEvidence), ('drag_selection', native._Drag)])
_Result = _struct('Result3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('options', native._Options), ('widths', native._Array * 3),
    ('edges', native._Array * 3), ('geometry', native._GeometryCache),
    ('uniform_solid_conductivity', _D),
    *((name, native._Array) for name in ('cell_length', 'wall_thickness', 'total_porosity',
        'side_porosity', 'permeability', 'forchheimer', 'solid_conductivity')),
    ('sides', _Side * 2), ('models', native._Model * 4),
    ('evidence', native._Evidence), ('sco2_nu_model_version', native._Text),
    ('sco2_nu_interpretation', native._Text), ('sco2_nu_coefficients', (_D * 3) * 2),
    ('co2', native._Co2), ('notices', ct.POINTER(native._Text)), ('notice_count', _S)])
_Flow = _struct('Flow3D', [('input', _Input), ('have_capacities', _U),
    ('capacities', _D * 2), ('speeds', _D * 2), ('evidence', native._Evidence)])
_Controls = _struct('ContinuousControls3D', [('n_ctrl_x', _S), ('n_ctrl_y', _S), ('n_ctrl_z', _S),
    ('have_ctrl_z', _U), ('spline_order', _U), ('symmetric_y', _U),
    ('L_bounds_mm', _D * 2), ('t_bounds_mm', _D * 2), ('decision_mm', native._Array)])
_ContinuousInput = _struct('ContinuousInput3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2),
    ('controls', _Controls)])
_ContinuousFlow = _struct('ContinuousFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_ContinuousCase = _struct('ContinuousCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('controls', _Controls),
    ('area_density_per_m', native._Array), ('hydraulic_diameter_m', native._Array),
    ('thermal_porosity', native._Array), ('drag', native._ContinuousDrag * 2), ('owner', ct.c_void_p)])
_Cell = _struct('GridCell3D', [('bounds', _D * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D)])
_SpatialInput = _struct('SpatialInput3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2),
    ('cells', ct.POINTER(_Cell)), ('cell_count', _S)])
_SpatialFlow = _struct('SpatialFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S), ('owner', ct.c_void_p)])
_SpatialCase = _struct('SpatialCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S),
    ('side_b_porosity', native._Array), ('area_density_per_m', native._Array),
    ('hydraulic_diameter_m', native._Array), ('thermal_porosity', native._Array),
    ('split_a', _D), ('have_side_geometry', _U), ('side_geometry', (_D * 4) * 2),
    ('owner', ct.c_void_p)])


FAMILIES = (
    ('continuous', _ContinuousInput, _ContinuousFlow, _ContinuousCase),
    ('spatial', _SpatialInput, _SpatialFlow, _SpatialCase),
)


def _real(value, name):
    # Native validation rejects nonfinite physical inputs with ValueError.
    return real_scalar(value, name=name, allow_nonfinite=True)


def _detach_array(value, shape=None):
    """Copy one native float64 array into an immutable bytes buffer."""
    if value.size and not value.data:
        raise RuntimeError('native 3D preparation returned a null array pointer')
    raw = ct.string_at(value.data, value.size * ct.sizeof(_D)) if value.size else b''
    values = np.frombuffer(raw, dtype=np.float64)
    return values if shape is None else values.reshape(shape)


def pack_input(config, targets, inlet_speed, max_cells):
    """Pack one 3D preparation input record and keep its borrowed buffers alive."""
    geometry = config.geometry
    value = _Input(1, ct.sizeof(_Input))
    errors = {}
    value.lengths_m[:] = [
        _real(geometry.L_dom_m, 'geometry.L_dom_m'),
        _real(geometry.H_dom_m, 'geometry.H_dom_m'),
        _real(geometry.Lz_m, 'geometry.Lz_m'),
    ]
    counts = []
    for axis, count in enumerate((config.solver.Nx, config.solver.Ny, config.solver.Nz)):
        try:
            counts.append(grid_count(count))
        except (TypeError, ValueError, OverflowError) as problem:
            errors['count' + str(axis)] = problem
            counts.append(2)
    value.counts[:] = counts
    value.max_cells = min(max(max_cells, 0), _S(-1).value)
    value.port_wall_refine = config.flags.port_wall_refine
    value.topology = TOPOLOGY_CODES.get(geometry.tpms, 0)
    value.cell_length_mm = _real(geometry.L_cell_mm, 'geometry.L_cell_mm')
    value.wall_thickness_mm = _real(geometry.t_wall_mm, 'geometry.t_wall_mm')
    value.solid_conductivity_W_mK = _real(geometry.k_s_W_mK, 'geometry.k_s_W_mK')
    value.delta_levelset = _real(geometry.delta_levelset, 'geometry.delta_levelset')
    continuous = config.zones.enabled and config.zones.axis == 'continuous'
    value.geometry_mode = 1 if continuous else 2 if config.zones.enabled and config.zones.axis == 'grid' else 0
    value.df_mode = int(config.df_mode == 'experimental')
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        raw_port = GridPort(port.dir, 1)
        raw_port.set_windows(lambda key: getattr(port, key), full_width=port.in_w <= 0. and port.out_w <= 0.)
        speed = inlet_speed(fluid)
        prefix, mass = 'fluid_' + side + '.', fluid.mass_flow_kg_s
        value.sides[index] = _Inlet(
            native._FLUIDS.index(fluid.type) if fluid.type in native._FLUIDS else 0,
            _real(speed, prefix + 'u_mps'),
            _real(fluid.T_in_K, prefix + 'T_in_K'),
            _real(fluid.P_in_Pa, prefix + 'P_in_Pa'),
            raw_port,
            mass is not None,
            0. if mass is None else _real(mass, prefix + 'mass_flow_kg_s'),
        )
    buffers = []
    host.pack_nu(value.sco2_nu, config.sco2_nu, buffers)
    have_targets = targets is not None
    explicit = (_D * 2)()
    if have_targets:
        for index, side in enumerate('AB'):
            explicit[index] = _real(targets[index], f'mass_flow_{side}_kg_s')
    if continuous:
        spec = config.zones.config
        decision = real_array(spec['x_decision'], name='x_decision', allow_nonfinite=True)
        controls = _Controls(
            spec['n_ctrl_x'], spec['n_ctrl_y'], spec.get('n_ctrl_z', 1),
            'n_ctrl_z' in spec, spec['spline_order'], spec['symmetric_y'],
            (_D * 2)(*[_real(item, 'L_bounds') for item in spec['L_bounds']]),
            (_D * 2)(*[_real(item, 't_bounds') for item in spec['t_bounds']]),
            native._Array(decision.ctypes.data_as(ct.POINTER(_D)), decision.size),
        )
        source = _ContinuousInput(1, ct.sizeof(_ContinuousInput), value, have_targets, explicit, controls)
        buffers.append(decision)
    else:
        rows = config.zones.grid['cells'] if config.zones.enabled and config.zones.axis == 'grid' else []
        cells = (_Cell * len(rows))()
        for index, row in enumerate(rows):
            cells[index].bounds[:] = [_real(row[key], 'grid cell ' + key) for key in ('x0', 'x1', 'y0', 'y1')]
        for key, field in (('L', 'cell_length_mm'), ('t', 'wall_thickness_mm')):
            for index, row in enumerate(rows):
                try:
                    setattr(cells[index], field, float(row[key]))
                except (KeyError, TypeError, ValueError, OverflowError) as problem:
                    errors.setdefault('cells', problem)
        source = _SpatialInput(1, ct.sizeof(_SpatialInput), value, have_targets, explicit, cells, len(cells))
        buffers.append(cells)
    source._buffers = buffers
    return source, errors


def _copy_side(current, native_port, shape, extension):
    port = host.fixed_record(native_port)
    axes = tuple(current.axes)
    cross_shape = shape[axes[0]], shape[axes[2]]
    inlet_opening = _detach_array(current.inlet_opening, cross_shape)
    outlet_opening = _detach_array(current.outlet_opening, cross_shape)
    drag = (host.drag_evidence(current.drag_evidence, current.drag_selection, extension)
            if current.have_drag_application else None)
    return SimpleNamespace(
        port=port,
        axes=axes,
        inlet_opening=inlet_opening,
        outlet_opening=outlet_opening,
        rho=current.rho,
        mu=current.mu,
        cp=current.cp,
        k_f=current.k_f,
        drag=drag,
    )


def _copy_case(result):
    """Copy every native 3D preparation field while its owner is live."""
    value = result.prepared
    widths = tuple([_detach_array(item) for item in value.widths])
    shape = tuple([len(item) for item in widths])
    edges = tuple([_detach_array(item) for item in value.edges])
    fields = {
        name: _detach_array(getattr(value, name), shape)
        for name in (
            'cell_length', 'wall_thickness', 'total_porosity', 'side_porosity',
            'permeability', 'forchheimer', 'solid_conductivity',
        )
    }
    continuous = isinstance(result, _ContinuousCase)
    side_b_porosity = None if continuous else _detach_array(result.side_b_porosity, shape)
    geometry = host.geometry_scalars(value.geometry)
    co2_active = bool(value.co2.active)
    uniform_solid_conductivity = value.uniform_solid_conductivity
    split_a = .5 if continuous else result.split_a
    thermal_fields = None
    if result.area_density_per_m.size:
        thermal_fields = SimpleNamespace(
            area_density_per_m=_detach_array(result.area_density_per_m, shape),
            hydraulic_diameter_m=_detach_array(result.hydraulic_diameter_m, shape),
            thermal_porosity=_detach_array(result.thermal_porosity, shape),
        )
    side_geometry = None
    if not continuous and result.have_side_geometry:
        side_geometry = tuple([tuple(row) for row in result.side_geometry])
    sides = tuple([
        _copy_side(value.sides[index], value.input.sides[index].port, shape,
                   result.drag[index] if continuous else None)
        for index in range(2)
    ])
    models = [(read_text(model.name), read_text(model.version)) for model in value.models]
    model_evidence = host.model_evidence(value, value.input.sco2_nu)
    notices = [read_text(item) for item in value.notices[:value.notice_count]]
    return SimpleNamespace(
        continuous=continuous,
        widths=widths,
        edges=edges,
        shape=shape,
        **fields,
        side_b_porosity=side_b_porosity,
        geometry=geometry,
        co2_active=co2_active,
        uniform_solid_conductivity=uniform_solid_conductivity,
        split_a=split_a,
        thermal_fields=thermal_fields,
        side_geometry=side_geometry,
        sides=sides,
        models=models,
        model_evidence=model_evidence,
        notices=notices,
    )


def run_preparation(action, source, *, chi, allow, validate, policy, water_error):
    """Run one 3D preparation operation and return detached Python values."""
    options = native._Options(1, ct.sizeof(native._Options), 2 if policy.chi_error is not None else int(chi is not None), allow, chi or 0.)
    with host.volume_operation(action, source, options, validate, policy, water_error) as result:
        flow = result.flow
        if action == 'prepare_inlet_mass_capacities':
            return tuple(flow.capacities)
        speeds = tuple(flow.speeds)
        if action == 'resolve_inlet_flow':
            return speeds
        return speeds, _copy_case(result)
