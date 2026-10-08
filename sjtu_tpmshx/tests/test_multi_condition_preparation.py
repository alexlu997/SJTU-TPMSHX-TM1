"""Fixed mass-flow preparation agrees with the native 2D/3D inlet faces."""
from dataclasses import asdict, replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig,
    SolverConfig, ZoneInputConfig, ExtrapPolicy,
)
from sjtu_tpmshx.models.field_coordinates_3d import _solver_staggered_to_real
from sjtu_tpmshx.optimization.multi_condition import prepare_fixed_mass_flow_case
from sjtu_tpmshx.preprocess.three_d import preparation
from sjtu_tpmshx.preprocess.api import prepare_case, prepare_inlet_mass_capacities, resolve_fixed_mass_flow_config
from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity
from sjtu_tpmshx.solvers.backends.python.three_d import runtime
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('design_mode', ['uniform', 'grid', 'continuous'])
def test_fixed_flow_matches_native_faces_after_density_update(monkeypatch, direction, design_mode):
    shape, lengths = (6, 5, 4), (.04, .05, .06)
    widths = tuple(np.arange(1., count + 1.) * length / sum(range(1, count + 1))
                   for count, length in zip(shape, lengths))
    monkeypatch.setattr(preparation, '_build_grid_3d', lambda *args: (*widths, *shape))
    # Construct the real SIMPLE objects but do not run a numerical sweep.
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *args, **kwargs: None)
    port = PartialBCConfig(in_ctr=.018, in_w=.027, out_ctr=.023, out_w=.021,
                           in_z_ctr=.020, in_z_w=.031, out_z_ctr=.024, out_z_w=.019)
    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=340., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1],
                                Lz_m=lengths[2], L_cell_mm=6., t_wall_mm=.4),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], Nz=shape[2]),
        # direction=0 includes the Shanghai A:+x / B:-y orientation.
        bc_A=replace(port, dir=direction), bc_B=replace(port, dir=(direction + 3) % 6))
    if design_mode == 'grid':
        cells = [dict(x0=x0, x1=x1, y0=y0, y1=y1, L=cell, t=wall)
                 for x0, x1, y0, y1, cell, wall in (
                     (0., .4, 0., .6, 4., .3), (.4, 1., 0., .6, 6., .4),
                     (0., .4, .6, 1., 7., .5), (.4, 1., .6, 1., 8., .4))]
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': cells}))
    elif design_mode == 'continuous':
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [5., 5.4, 5.8, 5.3, 5.7, 6.1, 5.6, 6., 6.4] +
                          [.4, .42, .44, .41, .43, .45, .42, .44, .46],
            'n_ctrl_x': 3, 'n_ctrl_y': 3, 'symmetric_y': False,
            'spline_order': 2, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    original = asdict(config)
    targets = {'A': .002, 'B': .03}
    case = prepare_fixed_mass_flow_case(
        config, mass_flow_A_kg_s=targets['A'], mass_flow_B_kg_s=targets['B'],
        case_id='fixed-mass-flow')
    assert asdict(config) == original
    assert case.case_id == 'fixed-mass-flow'
    assert dict(case.config_snapshot['geometry']) == original['geometry']
    assert case.config_snapshot['df_mode'] == config.df_mode
    params, prepared = build_execution_inputs(case)
    problem = runtime.build_problem(params, prepared)
    for side, solver, axes in (('A', problem.sA, problem.axis_map),
                               ('B', problem.sB, problem.axis_map_B)):
        fluid = getattr(config, 'fluid_' + side)
        snapshot = case.config_snapshot['fluid_' + side]
        assert dict(snapshot) == {**asdict(fluid), 'u_mps': params['u_' + side]}
        assert snapshot['u_mps'] != fluid.u_mps
        assert dict(case.config_snapshot['bc_' + side]) == original['bc_' + side]
        fractions = prepared['openings'][side]['inlet']
        assert np.any((fractions > 0.) & (fractions < 1.))
        if design_mode != 'uniform':
            assert np.ptp(case.design_fields['eps_' + side]) > 0.
        # Air normally captures this target at solve() entry; the numerical
        # solve is deliberately skipped. Water's target is built by runtime.
        if side == 'A':
            solver._massflux_target = (solver.v_inlet_field * solver.rho_field[:, 0, :]).copy()
        assert hasattr(solver, '_massflux_target')
        for update_density in (False, True):
            if update_density:
                i, j, k = np.indices(solver.rho_field.shape)
                solver.rho_field *= 1.3 + .1*i + .02*j + .03*k
                solver._apply_massflux_inlet()
                solver.v[:, 0, :] = solver.v_inlet_field
            rho_real = solver.rho_field.transpose(axes['solver_to_real_perm'])
            if axes['is_reverse']:
                rho_real = np.flip(rho_real, axis=axes['stream_real_axis'])
            native_faces = face_mass_fluxes(
                *_solver_staggered_to_real(solver, axes, shape), rho_real,
                case.design_fields['eps_' + side], *widths)
            inward_sign = -1 if axes['is_reverse'] else 1
            inlet = np.take(native_faces[axes['stream_real_axis']],
                            -1 if axes['is_reverse'] else 0, axis=axes['stream_real_axis'])
            assert inward_sign * inlet.sum() == pytest.approx(targets[side], rel=2e-14)


@pytest.mark.parametrize('direction', range(4))
@pytest.mark.parametrize('design_mode', ['uniform', 'continuous'])
@pytest.mark.parametrize('port_profile', ['full', 'uniform-partial', 'tapered-partial'])
def test_fixed_flow_2d_matches_actual_inlet_faces(monkeypatch, direction, design_mode,
                                                port_profile):
    from sjtu_tpmshx.preprocess.two_d import preparation as preparation_2d
    from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    from sjtu_tpmshx.solvers.backends.python.two_d.coupling import (
        _simple_scalar_to_real_2d, _simple_staggered_to_real_2d,
    )

    shape, lengths = (9, 10), (.04, .05)
    widths = tuple(np.linspace(.3, 1.7, count) * length / count
                   for count, length in zip(shape, lengths))
    monkeypatch.setattr(preparation_2d, '_prepare_mesh', lambda cfg: dict(
        energy_dx=widths[0], energy_dy=widths[1], _x_breaks=(), _y_breaks=()))

    def port(d):
        span = lengths[1 if d < 2 else 0]
        full = port_profile == 'full'
        return PartialBCConfig(
            dir=d, in_ctr=(.5 if full else .47) * span,
            in_w=(1. if full else .53) * span,
            out_ctr=(.5 if full else .55) * span,
            out_w=(1. if full else .49) * span,
            uniform_inlet_2d=port_profile == 'uniform-partial')

    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1], Lz_m=.02),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], max_iter_simple=1),
        bc_A=port(direction), bc_B=port((direction + 1) % 4),
        extrap=ExtrapPolicy(allow=True))
    if design_mode == 'continuous':
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [5., 6., 7., 7.5, .3, .4, .45, .6],
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    targets = {'A': .001, 'B': .03}
    case = prepare_fixed_mass_flow_case(
        config, mass_flow_A_kg_s=targets['A'], mass_flow_B_kg_s=targets['B'],
        case_id='fixed-mass-2d')
    cfg, grid = build_execution_inputs(case)
    run = build_runtime(cfg, grid)['_run_simple']
    for side in ('A', 'B'):
        fluid = getattr(config, 'fluid_' + side)
        props = cfg['static_properties'][side]
        d = cfg['cfg' + side]['dir']
        # One real iteration exercises the solver's mass-target capture. This
        # test qualifies the imposed inlet, not convergence of the full case.
        solver = run(cfg['cfg' + side], props['rho'], props['mu'], fluid.T_in_K,
                     cfg['u_' + side], side, P_in_abs=fluid.P_in_Pa,
                     fluid_type='ideal_gas' if side == 'A' else 'incompressible',
                     rho_inlet_ref=props['rho'])[2]
        if port_profile == 'tapered-partial':
            assert solver._inlet_taper_flux_scale > 1.
        else:
            assert solver._inlet_taper_flux_scale == 1.
        eps = np.asarray(case.design_fields['eps_arr']) / 2.
        if design_mode == 'continuous':
            assert np.ptp(np.take(eps, -1 if d % 2 else 0, axis=d // 2)) > 0.
        for update_density in (False, True):
            if update_density:
                i, j = np.indices(solver.rho_field.shape)
                solver.rho_field *= 1.3 + .1 * i + .02 * j
            # Apply the actual solver inlet after the density update. No
            # capacity/profile formula participates in the measured flux.
            solver._apply_massflux_inlet()
            solver._set_bc()
            faces = _simple_staggered_to_real_2d(solver, d)
            rho = _simple_scalar_to_real_2d(solver.rho_field, d)
            axis, edge = d // 2, -1 if d % 2 else 0
            inward = -1 if d % 2 else 1
            actual = inward * np.sum(
                np.take(rho * eps, edge, axis=axis)
                * np.take(faces[axis], edge, axis=axis) * widths[1 - axis]) * .02
            assert actual == pytest.approx(targets[side], rel=2e-14)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('invalid', [0., -1., np.inf, np.nan])
def test_fixed_flow_rejects_invalid_targets(side, invalid):
    targets = {'mass_flow_A_kg_s': .01, 'mass_flow_B_kg_s': .02}
    targets['mass_flow_' + side + '_kg_s'] = invalid
    with pytest.raises(ValueError, match='mass_flow_' + side + '_kg_s must be finite and positive'):
        prepare_fixed_mass_flow_case(
            ComputeConfig(solver=SolverConfig(Nz=2)), **targets, case_id='invalid-flow')


@pytest.mark.parametrize('config, message', [(ComputeConfig(), 'positive physical Lz_m'),
    (ComputeConfig(solver=SolverConfig(Nz=2), fluid_B=None), 'dual-fluid')])
def test_fixed_flow_requires_dual_fluid_and_explicit_2d_depth(config, message):
    with pytest.raises(ValueError, match=message):
        prepare_fixed_mass_flow_case(
            config, mass_flow_A_kg_s=.01, mass_flow_B_kg_s=.02, case_id='invalid-config')


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('design_mode', ['uniform', 'continuous'])
@pytest.mark.parametrize('df_mode', ['cfd_smooth', 'experimental'])
def test_fixed_flow_uses_only_resolved_velocities(monkeypatch, dimension, design_mode, df_mode):
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.182, H_dom_m=.042, Lz_m=.042),
        solver=SolverConfig(Nx=4, Ny=4, Nz=2 if dimension == 3 else 1),
        fluid_A=FluidConfig(type='air', u_mps=6., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        df_mode=df_mode)
    if design_mode == 'continuous':
        count = 4 if dimension == 2 else 8
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': np.linspace(6.8, 7.2, count).tolist()
                          + np.linspace(.5, .58, count).tolist(),
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6],
            **({'n_ctrl_z': 2} if dimension == 3 else {})})
    reference = prepare_case(config, case_id='reference')
    targets = {'mass_flow_' + side + '_kg_s': getattr(config, 'fluid_' + side).u_mps
               * total_inlet_mass_capacity(reference.design_fields, reference.parameters,
                                          reference.grid, side) for side in ('A', 'B')}
    expected = prepare_case(resolve_fixed_mass_flow_config(config, **targets), case_id='fixed')
    old = replace(config, fluid_A=replace(config.fluid_A, u_mps=.001),
                  fluid_B=replace(config.fluid_B, u_mps=.00001))
    snapshot = asdict(old)
    from unittest.mock import patch
    with patch.object(preparation, '_prepare_geometry_data', wraps=preparation._prepare_geometry_data) as geometry:
        actual = prepare_fixed_mass_flow_case(old, **targets, case_id='fixed')
    if dimension == 3:
        assert geometry.call_count == 1
    assert asdict(old) == snapshot
    assert actual.config_snapshot == expected.config_snapshot
    assert actual.metadata['warnings'] == expected.metadata['warnings']
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import compare
    compare(actual.parameters, expected.parameters)
    compare(actual.grid, expected.grid)
    assert actual.model_refs == expected.model_refs
    for key in expected.design_fields:
        np.testing.assert_equal(actual.design_fields[key], expected.design_fields[key])
    for side in ('A', 'B'):
        assert actual.parameters['u_' + side] == pytest.approx(getattr(config, 'fluid_' + side).u_mps)
    # The resolved velocity still passes through both original physical gates.
    invalid = {**targets, 'mass_flow_A_kg_s': targets['mass_flow_A_kg_s'] * 1e-6}
    message = 'HX experiment calibration' if df_mode == 'experimental' and design_mode == 'uniform' else 'outside air Nu window'
    with pytest.raises(ValueError, match=message):
        prepare_fixed_mass_flow_case(old, **invalid, case_id='invalid-final-speed')


@pytest.mark.parametrize('design_mode', ['x', 'y', 'grid', 'sigmoid'])
def test_fixed_flow_preserves_legacy_2d_geometry_and_input(monkeypatch, tmp_path, design_mode):
    from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig

    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.04, H_dom_m=.05, Lz_m=.02),
        solver=SolverConfig(Nx=12, Ny=12),
        fluid_A=FluidConfig(u_mps=5., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(u_mps=5., T_in_K=300., P_in_Pa=200000.),
        bc_A=PartialBCConfig(dir=1, in_ctr=.023, in_w=.021, out_ctr=.025, out_w=.019),
        bc_B=PartialBCConfig(dir=3, in_ctr=.018, in_w=.027, out_ctr=.023, out_w=.021))
    config.zones = ZoneInputConfig(enabled=True, axis='grid' if design_mode == 'sigmoid' else design_mode)
    if design_mode in ('x', 'y'):
        config.zones.config = ZoneConfig([
            Zone('outlet', .5, 1., 7., .5), Zone('inlet', 0., .5, 6., .4)], 'Gyroid', 16.)
    else:
        config.zones.grid = {'cells': [
            dict(x0=0., x1=.5, y0=0., y1=1., L=6., t=.4),
            dict(x0=.5, x1=1., y0=0., y1=1., L=7., t=.5)],
            'tpms_type': 'Gyroid', 'k_s': 16.}
    if design_mode == 'sigmoid':
        from sjtu_tpmshx.models import sigmoid_field
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=3, N=16, cache_dir=str(tmp_path))
        monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *_: lut)
        config.zones.pareto_x_decision = [value for cell in np.linspace(6., 7., 18)
                                        for value in (float(cell), .4)]
    snapshot = asdict(config)
    reference = prepare_case(config, case_id='legacy-reference')
    assert 'optimizer' not in reference.config_snapshot
    assert 'optimizer' not in reference.parameters['run_settings']
    targets = {'mass_flow_' + side + '_kg_s': getattr(config, 'fluid_' + side).u_mps
               * total_inlet_mass_capacity(reference.design_fields, reference.parameters,
                                          reference.grid, side) for side in ('A', 'B')}
    old = replace(config, fluid_A=replace(config.fluid_A, u_mps=.001))
    actual = prepare_fixed_mass_flow_case(old, **targets, case_id='legacy-fixed')
    assert asdict(config) == snapshot
    assert old.fluid_A.u_mps == .001
    for key in reference.design_fields:
        np.testing.assert_equal(actual.design_fields[key], reference.design_fields[key])
    for side in ('A', 'B'):
        assert actual.parameters['u_' + side] == pytest.approx(5.)


def test_capacity_preparation_validates_static_inputs_before_building_fields(monkeypatch):
    from sjtu_tpmshx.preprocess.two_d import preparation as preparation_2d

    def forbidden(*args):
        raise AssertionError('invalid static input reached field construction')

    monkeypatch.setattr(preparation_2d, '_prepare_inlet_data', forbidden)
    monkeypatch.setattr(preparation, '_prepare_geometry_data', forbidden)
    for dimension in (2, 3):
        config = ComputeConfig(geometry=GeometryConfig(Lz_m=.042),
                               solver=SolverConfig(Nz=dimension - 1))
        invalid = (
            (replace(config, solver=replace(config.solver, Nx=True)), 'must be an integer'),
            (replace(config, geometry=replace(config.geometry, L_cell_mm=9.)), 'V2 geometry'),
            (replace(config, fluid_B=replace(config.fluid_B, T_in_K=np.nan)), 'T_in_K'),
        )
        for candidate, message in invalid:
            with pytest.raises(ValueError, match=message):
                prepare_inlet_mass_capacities(candidate)
            with pytest.raises(ValueError, match=message):
                prepare_fixed_mass_flow_case(candidate, mass_flow_A_kg_s=.01,
                                             mass_flow_B_kg_s=.02, case_id='invalid-static')
