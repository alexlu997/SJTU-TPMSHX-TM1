"""Build immutable 3D CaseData from detached native preparation values."""
from copy import deepcopy
from dataclasses import asdict
from functools import partial
import os
from typing import get_args

from sjtu_tpmshx.cpp_interface import native_preparation
from sjtu_tpmshx.data_types.case_data import CaseData
from sjtu_tpmshx.data_types.compute_config import ComputeConfig, TPMSType
from sjtu_tpmshx.data_types.model_refs import ModelRef
from sjtu_tpmshx.physical_models.fluid_props import WaterStateError, validate_fluid_type
from sjtu_tpmshx.run_control.run_environment import capture_environment
from .. import preparation as shared


_TOPOLOGIES = get_args(TPMSType)


def _max_cells_3d():
    cap_text = os.environ.get('TPMSHX_MAX_CELLS_3D', '2000000')
    try:
        return int(cap_text), None
    except ValueError as problem:
        return 0, problem


def _inlet_speed(action, targets, fluid):
    if action == 'prepare_inlet_mass_capacities' or targets is not None or fluid.mass_flow_kg_s is not None:
        return 0.
    return fluid.u_mps


def _axis_data(axes, widths, lengths):
    cross1, stream, cross2, p0, p1, p2, reverse = axes
    counts = tuple([len(values) for values in widths])
    return dict(is_x_stream=stream == 0, is_y_stream=stream == 1, is_z_stream=stream == 2,
        is_reverse=bool(reverse),
        solver_init=dict(Lx=lengths[cross1], Ly=lengths[stream], Lz=lengths[cross2],
                         Nx=counts[cross1], Ny=counts[stream], Nz=counts[cross2]),
        N_stream=counts[stream], N_cross1=counts[cross1], N_cross2=counts[cross2],
        L_stream=lengths[stream], L_cross1=lengths[cross1], L_cross2=lengths[cross2],
        dstream=widths[stream], dcross1=widths[cross1], dcross2=widths[cross2],
        stream_real_axis=stream, cross1_real_axis=cross1, cross2_real_axis=cross2,
        solver_to_real_perm=(p0, p1, p2))


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
        L_cell_m=float(geometry.L_cell_mm) * 1e-3, t_wall_m=float(geometry.t_wall_mm) * 1e-3,
        k_s=geometry.k_s_W_mK, tpms_type=geometry.tpms, eps=uniform['epsilon'], D_h=uniform['D_h'],
        delta_levelset=float(geometry.delta_levelset),
        port_wall_refine=config.flags.port_wall_refine, variable_rho_cp=bool(config.flags.variable_rho_cp),
        max_iter_simple=solver.max_iter_simple, simple_velocity_relaxation=solver.simple_velocity_relaxation,
        max_outer_ltne=solver.max_outer_ltne, outer_tol_K=solver.outer_tol_K,
        enthalpy_algorithm=solver.enthalpy_algorithm, enthalpy_temperature_tol_K=solver.enthalpy_temperature_tol_K,
        zone_grid_cells=([{('L_m' if key == 'L' else 't_m' if key == 't' else key):
                            float(value) * 1e-3 if key in ('L', 't') else value for key, value in cell.items()}
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


def _case(detached, config, case_id, context):
    widths, shape = detached.widths, detached.shape
    grid = dict(dimension=3, axis_order=('x', 'y', 'z'), length_unit='m')
    for index, axis in enumerate('xyz'):
        grid['d' + axis], grid[axis + '_edges'] = widths[index], detached.edges[index]
    design = {key: getattr(detached, name)
              for name, key in (
                  ('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'),
                  ('total_porosity', 'eps_arr'), ('side_porosity', 'eps_A'),
                  ('permeability', 'K_m2'), ('forchheimer', 'cF_per_m'), ('solid_conductivity', 'K_ss'))}
    design['eps_B'] = design['eps_A'] if detached.continuous else detached.side_b_porosity
    uniform = shared.geometry_values(detached.geometry, detached.co2_active)
    uniform['K_ss'] = detached.uniform_solid_conductivity
    params = _parameters(config, uniform, context)
    thermal = dict(uniform=uniform, fields=None,
                   split_A=detached.split_a, side_geometry=None)
    if detached.thermal_fields is not None:
        thermal['fields'] = {key: getattr(detached.thermal_fields, name) for name, key in (
            ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'), ('thermal_porosity', 'epsilon'))}
    if detached.side_geometry is not None:
        thermal['side_geometry'] = {side: detached.side_geometry[index] for index, side in enumerate('AB')}
    axes, openings, properties, drag = {}, {}, {}, {}
    lengths = params['L'], params['H'], params['Lz']
    for index, side in enumerate('AB'):
        current = detached.sides[index]
        native_port = current.port
        port = shared.prepared_port(native_port.direction,
            [row[0] for row in native_port.values], [row[1] for row in native_port.values])
        for row, end in enumerate(('in', 'out')):
            for column, suffix in ((2, '_z_ctr'), (3, '_z_w')):
                if native_port.present[row][column]:
                    port[end + suffix] = native_port.values[row][column]
        params['fluid_' + side + '_cfg'] = port
        axes[side] = _axis_data(current.axes, widths, lengths)
        openings[side] = {'inlet': current.inlet_opening, 'outlet': current.outlet_opening}
        properties[side] = {key: getattr(current, name) for name, key in
                            (('rho', 'rho'), ('mu', 'mu'), ('cp', 'cp'), ('k_f', 'k'))}
        if current.drag is not None:
            drag[side] = shared.drag_application_metadata(current.drag, params['u_' + side])
    params.update(thermal_geometry=thermal, df_application=drag or None,
        prepared=dict(Nx=shape[0], Ny=shape[1], Nz=shape[2],
            max_outer=None if config.solver.max_outer_ltne is None else int(config.solver.max_outer_ltne),
            ltne_max_iter=20000, compact=False,
            geometry=uniform, axes=axes, openings=openings, properties=properties))
    refs = tuple([ModelRef(name, version,
        {'fluid': getattr(config, 'fluid_' + 'AB'[index]).type, 'sco2_nu': asdict(config.sco2_nu)}
        if index < 2 else {'topology': config.geometry.tpms} if index == 3 else {},
        applicability='side ' + 'AB'[index] if index < 2 else '')
        for index, (name, version) in enumerate(detached.models)])
    mode = ('continuous_xyz' if 'n_ctrl_z' in config.zones.config else 'continuous_xy_extruded') if detached.continuous else (
        'xy_extruded' if config.zones.enabled else 'uniform')
    return CaseData.from_compute_config(case_id, config, grid=grid, design_fields=design, parameters=params,
        model_refs=refs, metadata=dict(preprocessor='three_d_v1', quantity_basis='total', design_mode=mode,
            model_metadata=shared.model_metadata(detached.model_evidence, config),
            notices=list(detached.notices),
            model_roles={'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}))


def _execute(config, action, *, targets=None, case_id=None, start_observations=None):
    from sjtu_tpmshx.run_control.run_environment import _resolve_chi_s
    cell_cap, cap_error = _max_cells_3d()
    source, input_errors = native_preparation.pack_volume_input(
        config, targets, partial(_inlet_speed, action, targets), cell_cap)
    chi_error = None
    try:
        chi = _resolve_chi_s()
    except ValueError as problem:
        chi, chi_error = None, problem
    allow = config.extrap.allow or os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    cache = shared.PreparationCache(chi_error)
    context = {'extrap_reasons': cache.extrap_reasons}
    if start_observations is not None:
        start_observations()

    def host_input(stage, side):
        if stage == 10:
            if 'co2' not in (config.fluid_A.type, config.fluid_B.type):
                hash((config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128))
            elif chi_error is not None:
                raise chi_error
            if config.geometry.tpms not in _TOPOLOGIES:
                from sjtu_tpmshx.physical_models import tpms_props, co2_correlations
                geometry_check = (co2_correlations.geometry if 'co2' in
                    (config.fluid_A.type, config.fluid_B.type) else tpms_props.geometry)
                geometry_check(config.geometry.tpms, config.geometry.L_cell_mm,
                               config.geometry.t_wall_mm, config.geometry.k_s_W_mK)
        elif stage == 11:
            return  # Older preparation libraries also issue this port notification.
        elif stage == 12:
            for name in 'AB':
                validate_fluid_type(getattr(config, 'fluid_' + name).type, name)
            if config.zones.enabled and config.zones.axis not in ('continuous', 'grid'):
                raise NotImplementedError('3D zones support grid or continuous mode only')
        elif stage == 13:
            if action == 'prepare_flow_case':
                context['environment'] = capture_environment()
        elif stage == 14:
            if cap_error is not None:
                raise cap_error
            if cell_cap < 0:
                shape = config.solver.Nx, config.solver.Ny, config.solver.Nz
                raise ValueError(f'3D grid {shape[0]}x{shape[1]}x{shape[2]} exceeds the {cell_cap}-cell cap')
        elif stage == 15:
            from sjtu_tpmshx.physical_models.roughness import resolve_mode_from_env
            mode, eps_um = resolve_mode_from_env(default='norris_1a')
            context['roughness'] = {'mode': mode, 'eps_m': eps_um * 1e-6}
        elif stage == 16:
            if 'cells' in input_errors:
                raise input_errors['cells']
        elif stage in (17, 18, 19):
            key = 'count' + str(stage - 17)
            if key in input_errors:
                raise input_errors[key]
        else:
            raise RuntimeError(f'unknown 3D preparation host stage {stage}')

    output = native_preparation.run_volume_preparation(
        action, source, chi=chi, allow=allow, validate=host_input, policy=cache, water_error=WaterStateError)
    if action == 'prepare_inlet_mass_capacities':
        return {side: output[index] for index, side in enumerate('AB')}
    if action == 'resolve_inlet_flow':
        return shared.resolved_flow_config(config, output, targets)
    speeds, detached = output
    resolved = shared.resolved_flow_config(config, speeds, targets)
    return _case(detached, resolved, case_id, context)


def prepare_case(config: ComputeConfig, *, case_id: str):
    config = ComputeConfig.from_dict(asdict(config), _native_preparation=True)
    if not config.is_3d:
        raise ValueError('3D preparation requires solver.Nz >= 2')
    return _execute(config, 'prepare_flow_case', case_id=case_id)


def prepare_mass_flow_case(config, targets, *, case_id, start_observations):
    config = deepcopy(config).validate_static_inputs()
    explicit = (tuple([targets[side] for side in 'AB'])
                if all([getattr(config, 'fluid_' + side).mass_flow_kg_s is None for side in 'AB']) else None)
    return _execute(config, 'prepare_flow_case', targets=explicit, case_id=case_id,
                    start_observations=start_observations)


def capacities(config):
    return _execute(config, 'prepare_inlet_mass_capacities')


def resolve(config, *, targets=None):
    return _execute(deepcopy(config).validate_static_inputs(), 'resolve_inlet_flow', targets=targets)
