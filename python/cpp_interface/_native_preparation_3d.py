"""Transport owned 3D preparation data through the native C interface."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import os

import numpy as np
import ctypes as ct
from functools import lru_cache

from sjtu_tpmshx.data_types.case_data import CaseData
from sjtu_tpmshx.data_types.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.data_types.model_refs import ModelRef
from sjtu_tpmshx.run_control.run_environment import capture_environment
from . import native_preparation as common
from ._native_fp import restore_buffer_scalar
from . import _native_grid as grid
from . import _native_preparation
from . import _native_preparation_case as native


_U, _S, _D = native._U, native._S, native._D
_struct, _doubles = native._structure, native._doubles
_Inlet = _struct('Inlet3D', [('fluid', _U), *_doubles('velocity_m_s temperature_K pressure_Pa'),
    ('port', grid._Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_Input = _struct('Input3D', [('abi_version', _U), ('struct_size', _S),
    ('lengths_m', grid._Scalar * 3), ('counts', _S * 3), ('max_cells', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *_doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('geometry_mode', _U), ('df_mode', _U),
    ('kinds', native._Kinds), ('sco2_nu', native._Nu)])
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
    ('length_kinds', native._Kind * 2), ('sides', _Side * 2), ('models', native._Model * 4),
    ('evidence', native._Evidence), ('sco2_nu_model_version', native._Text),
    ('sco2_nu_interpretation', native._Text), ('sco2_nu_coefficients', (_D * 3) * 2),
    ('co2', native._Co2), ('notices', ct.POINTER(native._Text)), ('notice_count', _S),
    ('owner', ct.c_void_p)])
_FlowInput = _struct('FlowInput3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('target_kinds', native._Kind * 2),
    ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)])
_Flow = _struct('Flow3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('have_capacities', _U),
    ('capacities', grid._Scalar * 2), ('speeds', grid._Scalar * 2),
    ('evidence', native._Evidence), ('owner', ct.c_void_p)])
_Controls = _struct('ContinuousControls3D', [('n_ctrl_x', _S), ('n_ctrl_y', _S), ('n_ctrl_z', _S),
    ('have_ctrl_z', _U), ('spline_order', _U), ('symmetric_y', _U),
    ('L_bounds_mm', _D * 2), ('t_bounds_mm', _D * 2), ('decision_mm', native._Array)])
_ContinuousInput = _struct('ContinuousInput3D', [('abi_version', _U), ('struct_size', _S),
    ('values', _FlowInput), ('controls', _Controls)])
_ContinuousFlow = _struct('ContinuousFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_ContinuousCase = _struct('ContinuousCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('controls', _Controls),
    ('area_density_per_m', native._Array), ('hydraulic_diameter_m', native._Array),
    ('thermal_porosity', native._Array), ('drag', native._ContinuousDrag * 2), ('owner', ct.c_void_p)])
_Cell = _struct('GridCell3D', [('bounds', grid._Scalar * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D)])
_SpatialInput = _struct('SpatialInput3D', [('abi_version', _U), ('struct_size', _S),
    ('values', _FlowInput), ('cells', ct.POINTER(_Cell)), ('cell_count', _S)])
_SpatialFlow = _struct('SpatialFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S), ('owner', ct.c_void_p)])
_SpatialCase = _struct('SpatialCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S),
    ('side_b_porosity', native._Array), ('area_density_per_m', native._Array),
    ('hydraulic_diameter_m', native._Array), ('thermal_porosity', native._Array),
    ('split_a', _D), ('have_side_geometry', _U), ('side_geometry', (_D * 4) * 2),
    ('owner', ct.c_void_p)])


class _Bindings:
    def __init__(self, path):
        self.owner = _native_preparation._load_library(path)
        version = self.owner.bind('tpmshx_preparation_host_3d_abi_version_v5', [], _U)()
        if version != 5:
            raise ValueError(f'unsupported native 3D preparation host ABI {version}; expected 5')
        self.operations, self.releases = {}, {}
        for version, source, flow, full, prefix in (
                (3, _ContinuousInput, _ContinuousFlow, _ContinuousCase, 'continuous'),
                (4, _SpatialInput, _SpatialFlow, _SpatialCase, 'spatial')):
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case'):
                result = full if name == 'prepare_flow_case' else flow
                self.operations[version, name] = self.owner.bind(f'tpmshx_{name}_3d_v{version}',
                    [ct.POINTER(source), ct.POINTER(native._Options), ct.POINTER(native._Callbacks),
                     ct.POINTER(result), ct.POINTER(native._Failure), ct.POINTER(ct.c_char), _S])
            for result, suffix in ((flow, 'flow'), (full, 'case')):
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_{prefix}_{suffix}_3d_release_v{version}', [ct.POINTER(result)], None)


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


@contextmanager
def operation(name, source, options, validate_host_input, cache):
    """Keep the native owner alive through immutable CaseData construction."""
    version = source.abi_version
    result_type = ((_ContinuousCase if name == 'prepare_flow_case' else _ContinuousFlow)
                   if version == 3 else (_SpatialCase if name == 'prepare_flow_case' else _SpatialFlow))
    result = result_type(version, ct.sizeof(result_type))
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    bindings = _bindings(_native_preparation._library().path)
    callbacks, descriptor, callback_errors = native._callback_bridge(validate_host_input,
        observe_range=cache.observe_range, observe_notice=cache.observe_notice,
        geometry_cache_at=cache.geometry_at, inlet_cache_at=cache.inlet_at)
    try:
        status = bindings.operations[version, name](ct.byref(source), ct.byref(options), ct.byref(descriptor),
            ct.byref(result), ct.byref(failure), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        native._check_status(status, error, failure)
        yield result
    finally:
        bindings.releases[result_type](ct.byref(result))


def _input(config, targets, operation):
    geometry = config.geometry
    value = _Input(1, ct.sizeof(_Input))
    errors = {}

    def transport(item):
        return item.item() if isinstance(item, np.ndarray) and item.size == 1 else item

    def scalar(item):
        try:
            return grid._scalar(item)
        except TypeError as problem:
            errors.setdefault('grid', problem)
            return grid._Scalar(float(transport(item)), 64, 0)

    value.lengths_m[:] = [scalar(geometry.L_dom_m), scalar(geometry.H_dom_m),
                          grid._Scalar(float(geometry.Lz_m), 64, 0)]
    counts = []
    for axis, count in enumerate((config.solver.Nx, config.solver.Ny, config.solver.Nz)):
        try:
            counts.append(grid._count(count))
        except (TypeError, ValueError, OverflowError) as problem:
            errors['count' + str(axis)] = problem
            counts.append(2)
    value.counts[:] = counts
    cap_text = os.environ.get('TPMSHX_MAX_CELLS_3D', '2000000')
    try:
        cap = int(cap_text)
    except ValueError as problem:
        errors['cap'], cap = problem, 0
    value.max_cells = min(max(cap, 0), native._S(-1).value)
    value.port_wall_refine = config.flags.port_wall_refine
    value.topology = {'Diamond': 0, 'Gyroid': 1}.get(geometry.tpms, 0)
    value.cell_length_mm, value.wall_thickness_mm = map(transport, (geometry.L_cell_mm, geometry.t_wall_mm))
    value.solid_conductivity_W_mK, value.delta_levelset = map(transport, (geometry.k_s_W_mK, geometry.delta_levelset))
    continuous = config.zones.enabled and config.zones.axis == 'continuous'
    value.geometry_mode = 1 if continuous else 2 if config.zones.enabled and config.zones.axis == 'grid' else 0
    value.df_mode = int(config.df_mode == 'experimental')
    value.kinds = native._Kinds(*map(common._kind,
        (geometry.L_cell_mm, geometry.t_wall_mm, geometry.k_s_W_mK)))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        raw_port = grid._Port()
        raw_port.active, raw_port.direction = 1, port.dir
        full = port.in_w <= 0. and port.out_w <= 0.
        for end_index, end in enumerate(('in', 'out')):
            for column, name in enumerate(('ctr', 'w', 'z_ctr', 'z_w')):
                item = getattr(port, end + '_' + name)
                if full and column < 2:
                    item = 0.
                if item is not None:
                    raw_port.present[end_index][column] = 1
                    raw_port.values[end_index][column] = scalar(item)
        speed = 0. if operation == 'prepare_inlet_mass_capacities' or (
            targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
        value.sides[index] = _Inlet(native._FLUIDS.index(fluid.type) if fluid.type in native._FLUIDS else 0,
            transport(speed), transport(fluid.T_in_K), transport(fluid.P_in_Pa), raw_port,
            fluid.mass_flow_kg_s is not None, fluid.mass_flow_kg_s or 0.)
        value.kinds.sides[index] = native._InletKinds(*map(common._kind,
            (speed, fluid.T_in_K, fluid.P_in_Pa)))
    settings = config.sco2_nu
    value.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        selected = getattr(settings, name)
        value.sco2_nu.have_alpha[index], value.sco2_nu.alpha[index] = selected is not None, selected or 0.
    buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        encoded = getattr(settings, name).encode('utf-8')
        buffer = ct.create_string_buffer(encoded)
        buffers.append(buffer)
        setattr(value.sco2_nu, name, native._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(encoded)))
    flow = _FlowInput(2, ct.sizeof(_FlowInput), value)
    flow.have_explicit_targets = targets is not None
    for index, side in enumerate('AB'):
        target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
        flow.target_kinds[index] = common._flow_kind(0. if target is None else target)
        if targets is not None:
            flow.explicit_targets_kg_s[index] = target
    if continuous:
        spec = config.zones.config
        decision = np.asarray(spec['x_decision'], dtype=np.float64)
        controls = _Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec.get('n_ctrl_z', 1),
            'n_ctrl_z' in spec, spec['spline_order'], spec['symmetric_y'],
            (native._D * 2)(*spec['L_bounds']), (native._D * 2)(*spec['t_bounds']),
            native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size))
        source = _ContinuousInput(3, ct.sizeof(_ContinuousInput), flow, controls)
        buffers.append(decision)
    else:
        rows = config.zones.grid['cells'] if config.zones.enabled and config.zones.axis == 'grid' else []
        cells = (_Cell * len(rows))()
        for index, row in enumerate(rows):
            cells[index].bounds[:] = [scalar(row[key]) for key in ('x0', 'x1', 'y0', 'y1')]
        for key, field in (('L', 'cell_length_mm'), ('t', 'wall_thickness_mm')):
            for index, row in enumerate(rows):
                try:
                    setattr(cells[index], field, float(row[key]))
                except (KeyError, TypeError, ValueError, OverflowError) as problem:
                    errors.setdefault('cells', problem)
        source = _SpatialInput(4, ct.sizeof(_SpatialInput), flow, cells, len(cells))
        buffers.append(cells)
    source._buffers, source._errors, source._cell_cap = buffers, errors, cap
    return source


def _array(value, shape=None, *, precision=64):
    """Borrow native storage until CaseData makes its immutable copy."""
    values = (np.ctypeslib.as_array(value.data, shape=(value.size,))
              if value.size else np.empty(0))
    if precision != 64:
        values = values.astype(f'float{precision}')
    return values if shape is None else values.reshape(shape)


def _axis_data(axes, widths, lengths):
    cross1, stream, cross2, p0, p1, p2, reverse = axes
    counts = tuple(len(values) for values in widths)
    return dict(is_x_stream=stream == 0, is_y_stream=stream == 1, is_z_stream=stream == 2,
        is_reverse=bool(reverse),
        solver_init=dict(Lx=lengths[cross1], Ly=lengths[stream], Lz=lengths[cross2],
                         Nx=counts[cross1], Ny=counts[stream], Nz=counts[cross2]),
        N_stream=counts[stream], N_cross1=counts[cross1], N_cross2=counts[cross2],
        L_stream=lengths[stream], L_cross1=lengths[cross1], L_cross2=lengths[cross2],
        dstream=widths[stream], dcross1=widths[cross1], dcross2=widths[cross2],
        stream_real_axis=stream, cross1_real_axis=cross1, cross2_real_axis=cross2,
        solver_to_real_perm=(p0, p1, p2))


def _drag(side, config, name, continuous):
    value, extra = side.drag_evidence, side.drag_selection
    metadata = {key: common._summary(getattr(value, field)) for field, key in (
        ('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
        ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF'))}
    metadata.update(scale_K=value.scale_permeability, scale_F=value.scale_forchheimer,
                    campaign=native._text(value.campaign), scope=native._text(value.scope))
    for field in ('application_scope', 'fluid'):
        text = native._text(getattr(extra, field))
        if text:
            metadata[field] = text
    if extra.calibration_count:
        metadata['calibration'] = {native._text(item.key): native._text(item.value)
                                   for item in extra.calibration[:extra.calibration_count]}
    if extra.have_selection and extra.selection.scope:
        metadata.update(inlet_u_mps=getattr(config, 'fluid_' + name).u_mps,
                        extrapolated=bool(extra.selection.flags & 2))
        for field, key in (('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')):
            values = getattr(extra.selection, field)
            metadata[key] = {'min': values[0], 'max': values[1]}
    if continuous is not None:
        for field in ('transfer_policy', 'geometry_application'):
            text = native._text(getattr(continuous, field))
            if text:
                metadata[field] = text
        if continuous.have_reference_geometry:
            metadata['reference_geometry_mm'] = dict(zip(('L', 't'), continuous.reference_geometry_mm))
    return metadata


def _parameters(config, uniform, context):
    geometry, solver = config.geometry, config.solver
    continuous = config.zones.enabled and config.zones.axis == 'continuous'
    cells = config.zones.grid['cells'] if config.zones.enabled and not continuous else None
    params = dict(L=geometry.L_dom_m, H=geometry.H_dom_m, Lz=float(geometry.Lz_m),
        Nx=solver.Nx, Ny=solver.Ny, Nz=solver.Nz,
        u_A=config.fluid_A.u_mps, u_B=config.fluid_B.u_mps,
        T_inA=config.fluid_A.T_in_K, T_inB=config.fluid_B.T_in_K,
        P_inA=config.fluid_A.P_in_Pa, P_inB=config.fluid_B.P_in_Pa,
        T_s_init=solver.T_s_init_K, envelope_mode=getattr(config, 'envelope_mode', 'raise'),
        L_cell_m=geometry.L_cell_mm * 1e-3, t_wall_m=geometry.t_wall_mm * 1e-3,
        k_s=geometry.k_s_W_mK, tpms_type=geometry.tpms, eps=uniform['epsilon'], D_h=uniform['D_h'],
        delta_levelset=float(geometry.delta_levelset),
        fluid_A_cfg=context['ports']['A'], fluid_B_cfg=context['ports']['B'],
        port_wall_refine=config.flags.port_wall_refine, variable_rho_cp=bool(config.flags.variable_rho_cp),
        max_iter_simple=solver.max_iter_simple, simple_velocity_relaxation=solver.simple_velocity_relaxation,
        max_outer_ltne=solver.max_outer_ltne, outer_tol_K=solver.outer_tol_K,
        enthalpy_algorithm=solver.enthalpy_algorithm, enthalpy_temperature_tol_K=solver.enthalpy_temperature_tol_K,
        zone_grid_cells=([{('L_m' if key == 'L' else 't_m' if key == 't' else key):
                            value * 1e-3 if key in ('L', 't') else value for key, value in cell.items()}
                          for cell in cells] if cells else None),
        continuous_field=deepcopy(config.zones.config) if continuous else None,
        fluid_type_A=config.fluid_A.type, fluid_type_B=config.fluid_B.type,
        df_mode=config.df_mode, sco2_nu=asdict(config.sco2_nu), extrap_reasons=context['extrap_reasons'],
        roughness_resolved=context['roughness'], _environment=context['environment'])
    for name in ('ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega',
                 'ltne_enthalpy_tol', 'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol',
                 'model_h_max_iterations', 'model_h_temperature_tol_K', 'model_h_q_relative_tol',
                 'convergence_mode', 'mom_tol', 'mass_local_tol', 'mass_global_tol'):
        value = getattr(solver, name)
        if value is not None:
            params[name] = value
    if solver.require_enthalpy_update_on_temperature:
        params['require_enthalpy_update_on_temperature'] = True
    for name, variable, default, selected in (
            ('use_adaptive_amg_tol', 'TPMSHX_PHASE_A', '1', '1'),
            ('use_anderson', 'TPMSHX_PHASE_B', '0', '1'),
            ('use_coarse_bootstrap', 'TPMSHX_PHASE_C', '0', '1')):
        current = params['_environment'][variable] or default
        params[name] = current != '0' if name == 'use_adaptive_amg_tol' else current == selected
    return params


def _case(result, config, case_id, context):
    value = result.prepared
    widths = tuple(_array(item) for item in value.widths)
    shape = tuple(len(item) for item in widths)
    grid = dict(dimension=3, axis_order=('x', 'y', 'z'), length_unit='m')
    for index, axis in enumerate('xyz'):
        grid['d' + axis], grid[axis + '_edges'] = widths[index], _array(value.edges[index])
    design = {key: _array(getattr(value, name), shape,
                         precision=value.length_kinds[index].precision if index < 2 else 64)
              for index, (name, key) in enumerate((
                  ('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'),
                  ('total_porosity', 'eps_arr'), ('side_porosity', 'eps_A'),
                  ('permeability', 'K_m2'), ('forchheimer', 'cF_per_m'), ('solid_conductivity', 'K_ss')))}
    continuous = isinstance(result, _ContinuousCase)
    design['eps_B'] = design['eps_A'] if continuous else _array(result.side_b_porosity, shape)
    uniform = common._geometry_values(value.geometry, bool(value.co2.active))
    solid_kind = (native._Kind(64, 1, 1) if value.co2.active else
                  common._kind(config.geometry.k_s_W_mK) if isinstance(config.geometry.k_s_W_mK, np.generic)
                  else native._Kind(64, 0, 0))
    uniform['K_ss'] = native._restore(value.uniform_solid_conductivity, solid_kind)
    params = _parameters(config, uniform, context)
    thermal = dict(uniform=uniform, fields=None,
                   split_A=.5 if continuous else result.split_a, side_geometry=None)
    if result.area_density_per_m.size:
        thermal['fields'] = {key: _array(getattr(result, name), shape) for name, key in (
            ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'), ('thermal_porosity', 'epsilon'))}
    if not continuous and result.have_side_geometry:
        thermal['side_geometry'] = {side: tuple(result.side_geometry[index]) for index, side in enumerate('AB')}
    axes, openings, properties, drag = {}, {}, {}, {}
    lengths = params['L'], params['H'], params['Lz']
    for index, side in enumerate('AB'):
        current = value.sides[index]
        axes[side] = _axis_data(current.axes, widths, lengths)
        cross_shape = axes[side]['N_cross1'], axes[side]['N_cross2']
        openings[side] = {end: _array(getattr(current, end + '_opening'), cross_shape)
                          for end in ('inlet', 'outlet')}
        properties[side] = {key: getattr(current, name) for name, key in
                            (('rho', 'rho'), ('mu', 'mu'), ('cp', 'cp'), ('k_f', 'k'))}
        if current.have_drag_application:
            drag[side] = _drag(current, config, side, result.drag[index] if continuous else None)
    params.update(thermal_geometry=thermal, df_application=drag or None,
        prepared=dict(Nx=shape[0], Ny=shape[1], Nz=shape[2],
            max_outer=None if config.solver.max_outer_ltne is None else int(config.solver.max_outer_ltne),
            ltne_max_iter=20000, compact=False,
            geometry=uniform, axes=axes, openings=openings, properties=properties))
    refs = tuple(ModelRef(native._text(model.name), native._text(model.version),
        {'fluid': getattr(config, 'fluid_' + 'AB'[index]).type, 'sco2_nu': asdict(config.sco2_nu)}
        if index < 2 else {'topology': config.geometry.tpms} if index == 3 else {},
        applicability='side ' + 'AB'[index] if index < 2 else '') for index, model in enumerate(value.models))
    mode = ('continuous_xyz' if 'n_ctrl_z' in config.zones.config else 'continuous_xy_extruded') if continuous else (
        'xy_extruded' if config.zones.enabled else 'uniform')
    return CaseData.from_compute_config(case_id, config, grid=grid, design_fields=design, parameters=params,
        model_refs=refs, metadata=dict(preprocessor='three_d_v1', quantity_basis='total', design_mode=mode,
            model_metadata=common.model_metadata(value, value.input.sco2_nu, config),
            notices=[native._text(item) for item in value.notices[:value.notice_count]],
            model_roles={'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}))


def _resolved(config, flow, targets):
    fluids = {}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        if targets is not None or fluid.mass_flow_kg_s is not None:
            fluids['fluid_' + side] = replace(fluid, u_mps=restore_buffer_scalar(flow.speeds[index]),
                mass_flow_kg_s=None if targets is not None else fluid.mass_flow_kg_s)
    return replace(config, **fluids).validate(resolved_inlet_speeds=True) if fluids else config


def _execute(config, action, *, targets=None, case_id=None, own_metadata=False):
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.run_control.run_environment import _resolve_chi_s
    source = _input(config, targets, action)
    chi_error = None
    try:
        chi = _resolve_chi_s()
    except ValueError as problem:
        chi, chi_error = None, problem
    allow = config.extrap.allow or os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    options = native._Options(1, ct.sizeof(native._Options), chi is not None, allow, chi or 0.)
    cache = common.PreparationCacheBridge(config, chi_error)
    context = {'extrap_reasons': cache.extrap_reasons}
    with ExitStack() as scopes:
        if own_metadata:
            context['provenance'] = api.source_context()
            context['records'] = scopes.enter_context(api.warning_scope({}))

        def host_input(stage, side):
            if stage == 10:
                if 'co2' not in (config.fluid_A.type, config.fluid_B.type):
                    hash((config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128))
                elif chi_error is not None:
                    raise chi_error
                if config.geometry.tpms not in ('Diamond', 'Gyroid'):
                    from sjtu_tpmshx.physical_models import tpms_props, co2_correlations
                    geometry_check = (co2_correlations.geometry if 'co2' in
                        (config.fluid_A.type, config.fluid_B.type) else tpms_props.geometry)
                    geometry_check(config.geometry.tpms, config.geometry.L_cell_mm,
                                   config.geometry.t_wall_mm, config.geometry.k_s_W_mK)
            elif stage == 11:
                context['ports'] = {name: bc_to_dict(getattr(config, 'bc_' + name),
                    config.geometry.L_dom_m, config.geometry.H_dom_m, side='A', with_z=True) for name in 'AB'}
            elif stage == 12:
                from sjtu_tpmshx.cpp_interface._native_preparation_case import validate_fluid_type
                for name in 'AB':
                    validate_fluid_type(getattr(config, 'fluid_' + name).type, name)
                if config.zones.enabled and config.zones.axis not in ('continuous', 'grid'):
                    raise NotImplementedError('3D zones support grid or continuous mode only')
            elif stage == 13:
                if 'grid' in source._errors:
                    raise source._errors['grid']
                if action == 'prepare_flow_case':
                    context['environment'] = capture_environment()
            elif stage == 14:
                if 'cap' in source._errors:
                    raise source._errors['cap']
                if source._cell_cap < 0:
                    shape = config.solver.Nx, config.solver.Ny, config.solver.Nz
                    raise ValueError(f'3D grid {shape[0]}x{shape[1]}x{shape[2]} exceeds the {source._cell_cap}-cell cap')
            elif stage == 15:
                from sjtu_tpmshx.physical_models.roughness import resolve_mode_from_env
                mode, eps_um = resolve_mode_from_env(default='norris_1a')
                context['roughness'] = {'mode': mode, 'eps_m': eps_um * 1e-6}
            elif stage == 16:
                if 'cells' in source._errors:
                    raise source._errors['cells']
            elif stage in (17, 18, 19):
                key = 'count' + str(stage - 17)
                if key in source._errors:
                    raise source._errors[key]
            else:
                raise RuntimeError(f'unknown 3D preparation host stage {stage}')

        with operation(action, source, options, host_input, cache) as result:
            flow = result.flow
            if action == 'prepare_inlet_mass_capacities':
                return {side: restore_buffer_scalar(flow.capacities[index]) for index, side in enumerate('AB')}
            resolved = _resolved(config, flow, targets)
            if action == 'resolve_inlet_flow':
                return resolved
            case = _case(result, resolved, case_id, context)
            return api._finish_metadata(case, context['provenance'], context['records']) if own_metadata else case


def prepare_case(config: ComputeConfig, *, case_id: str):
    config = ComputeConfig.from_dict(asdict(config))
    if not config.is_3d:
        raise ValueError('3D preparation requires solver.Nz >= 2')
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
