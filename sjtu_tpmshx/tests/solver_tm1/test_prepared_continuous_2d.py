"""Formal 2D spline evaluation preserves local geometry and both fluid closures."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig,
    SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs


def _config(*, uniform=False, df_mode='cfd_smooth'):
    return ComputeConfig(
        geometry=GeometryConfig(tpms='Gyroid', L_dom_m=.182, H_dom_m=.042,
                                Lz_m=.042, L_cell_mm=7., t_wall_mm=.6, k_s_W_mK=16.),
        fluid_A=FluidConfig(type='air', u_mps=8.5, T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        bc_A=PartialBCConfig(dir=0, in_ctr=.021, in_w=.017, out_ctr=.021, out_w=.017,
                            uniform_inlet_2d=True),
        bc_B=PartialBCConfig(dir=3, in_ctr=.091, in_w=.068, out_ctr=.091, out_w=.068,
                            uniform_inlet_2d=True),
        solver=SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=2, max_iter_simple=10),
        zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [7.]*4 + [.6]*4 if uniform else [6., 6.4, 7., 7.4, .35, .39, .38, .42],
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False, 'spline_order': 1,
            'L_bounds': [4., 8.], 't_bounds': [.3, .6]}),
        df_mode=df_mode, extrap=ExtrapPolicy(allow=True))


@pytest.mark.parametrize('directions', [(0, 3), (1, 2), (2, 1), (3, 0)])
def test_physical_cells_feed_full_local_drag_for_every_direction(monkeypatch, directions):
    from sjtu_tpmshx.models.tpms_props import geometry
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
    from sjtu_tpmshx.solvers import simple_solver
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    config = _config(df_mode='experimental')
    config = replace(config,
        bc_A=replace(config.bc_A, dir=directions[0], in_ctr=.021, out_ctr=.021, in_w=.017, out_w=.017),
        bc_B=replace(config.bc_B, dir=directions[1], in_ctr=.021, out_ctr=.021, in_w=.017, out_w=.017))
    case = prepare_case(config, case_id='local-xy')
    dx, dy = case.grid['dx'], case.grid['dy']
    x, y = (np.cumsum(dx) - dx / 2.) / .182, (np.cumsum(dy) - dy / 2.) / .042
    L = 6. + x[:, None] + .4*y[None, :]
    t = .35 + .03*x[:, None] + .04*y[None, :]
    np.testing.assert_allclose(case.design_fields['L_field_m'], L * 1e-3, rtol=1e-14)
    np.testing.assert_allclose(case.design_fields['t_field_m'], t * 1e-3, rtol=1e-14)
    assert not np.allclose(dx, dx.mean()) or not np.allclose(dy, dy.mean())
    eps = np.array([[geometry('Gyroid', cell, wall, 16.)['epsilon']
                     for cell, wall in zip(lrow, trow)] for lrow, trow in zip(L, t)])
    np.testing.assert_array_equal(case.design_fields['eps_arr'], eps)
    local_K, local_cF = predict_K_cF_vec('Gyroid', L, t, eps / 2.)
    cfg, grid = build_execution_inputs(case)
    monkeypatch.setattr(simple_solver.SIMPLESolver, 'solve', lambda *a, **k: (True, 1))
    run = build_runtime(cfg, grid)['_run_simple']
    for side, direction, factor in zip(('A', 'B'), directions, (2.649010286988306, 4.198913430360186)):
        expected_K, expected_cF = ((v.T if direction < 2 else v) for v in (local_K, local_cF * factor))
        expected_eps = eps.T if direction < 2 else eps
        if direction in (1, 3):
            expected_K, expected_cF, expected_eps = (v[:, ::-1] for v in (expected_K, expected_cF, expected_eps))
        flow = case.parameters['flow_inputs'][side]
        np.testing.assert_allclose(flow['K_field_m2'], expected_K, rtol=1e-12)
        np.testing.assert_allclose(flow['cF_field_per_m'], expected_cF, rtol=1e-12)
        assert flow['metadata']['geometry_application'] == 'continuous-field-extrapolation'
        prop = case.parameters['static_properties'][side]
        fluid = getattr(config, 'fluid_' + side)
        solver = run(cfg['cfg' + side], prop['rho'], prop['mu'], fluid.T_in_K, fluid.u_mps,
                     side, P_in_abs=fluid.P_in_Pa,
                     fluid_type='ideal_gas' if side == 'A' else 'incompressible')[2]
        np.testing.assert_array_equal(solver._K_field2d, flow['K_field_m2'])
        np.testing.assert_array_equal(solver._cF_field2d, flow['cF_field_per_m'])
        np.testing.assert_array_equal(solver.eps_field, expected_eps)
        np.testing.assert_allclose(solver._mu_eff_field, prop['mu'] / expected_eps)


@pytest.mark.parametrize('df_mode', ['cfd_smooth', 'experimental'])
def test_constant_controls_match_uniform_geometry_and_mesh(df_mode):
    config = _config(uniform=True, df_mode=df_mode)
    # Full ports exercise the automatic wall-refined mesh in both modes.
    config = replace(config, bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=3))
    spline = prepare_case(config, case_id='constant-controls')
    uniform = prepare_case(replace(config, zones=ZoneInputConfig()), case_id='uniform')
    for axis in ('dx', 'dy'):
        np.testing.assert_array_equal(spline.grid[axis], uniform.grid[axis])
    for key in uniform.design_fields:
        np.testing.assert_array_equal(spline.design_fields[key], uniform.design_fields[key])
    for side in ('A', 'B'):
        expected = uniform.parameters['flow_inputs'][side]
        actual = spline.parameters['flow_inputs'][side]
        np.testing.assert_allclose(actual['K_field_m2'], np.broadcast_to(expected['K_m2'], actual['K_field_m2'].shape), rtol=1e-14)
        np.testing.assert_allclose(actual['cF_field_per_m'], np.broadcast_to(expected['cF_per_m'], actual['cF_field_per_m'].shape), rtol=1e-14)
        np.testing.assert_array_equal(spline.design_fields['K_ff' + side + '_arr'],
                                      np.full_like(spline.design_fields['eps_arr'],
                                                   uniform.parameters['static_properties'][side]['K_ff']))


def test_case_replay_and_local_water_thermal_inputs(monkeypatch, tmp_path):
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.models import tpms_props, fluid_props
    from sjtu_tpmshx.models.local_heat_transfer import local_nusselt
    from sjtu_tpmshx.solvers import simple_solver
    from sjtu_tpmshx.solvers.backends.python.two_d import coupling
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    case = prepare_case(_config(), case_id='continuous-replay')
    save_case(case, tmp_path / 'case.yaml')
    restored = load_case(tmp_path / 'case.yaml')
    assert mutable_data(restored.config_snapshot) == mutable_data(case.config_snapshot)
    assert mutable_data(restored.parameters['continuous_field']) == mutable_data(case.parameters['continuous_field'])
    assert restored.metadata['quantity_basis'] == 'per_unit_depth'
    for name, values in case.design_fields.items():
        np.testing.assert_array_equal(restored.design_fields[name], values)
    cfg, grid = build_execution_inputs(replace(restored, config_snapshot={}))
    monkeypatch.setattr(tpms_props, 'geometry', lambda *a, **k: pytest.fail('runtime rebuilt geometry'))
    monkeypatch.setattr(simple_solver.SIMPLESolver, 'solve', lambda *a, **k: (True, 1))
    class ReachedThermal(Exception):
        pass
    captured = {}
    def capture(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        raise ReachedThermal
    monkeypatch.setattr(coupling, 'solve_full_domain', capture)
    with pytest.raises(ReachedThermal):
        coupling._run_solvers(cfg, build_runtime(cfg, grid))
    args, kwargs = captured['args'], captured['kwargs']
    assert kwargs['model_fluids'] == ('air', 'water')
    assert kwargs['mass_flux_A'] is not None and kwargs['mass_flux_B'] is not None
    geom = case.parameters['thermal_geometry']['fields']
    for side, temp, pressure, hv_index, velocity_index in (
            ('A', 380., 160000., 9, 14), ('B', 300., 200000., 10, 16)):
        model = fluid_props.get('air' if side == 'A' else 'water')
        mu, k, cp = (float(getattr(model, name)(temp, pressure)) for name in ('mu', 'k', 'cp'))
        speed = np.hypot(args[velocity_index], args[velocity_index + 1])
        Re = float(model.rho(temp, pressure)) * (speed + 1e-12) * geom['D_h'] / mu
        Nu = local_nusselt(model, 'Gyroid', Re, geom['epsilon'] / 2.,
                          cfg['za']['L_field'], geom['D_h'] * 1e3,
                          mu * cp / k if side == 'B' else None)
        np.testing.assert_allclose(args[hv_index], geom['A_0'] * Nu * k / geom['D_h'], rtol=1e-12)
        np.testing.assert_array_equal(args[6 if side == 'A' else 7], case.design_fields['K_ff' + side + '_arr'])
    np.testing.assert_array_equal(args[8], case.design_fields['K_ss_arr'])
    np.testing.assert_array_equal(args[13], case.design_fields['eps_arr'])


def test_continuous_replay_requires_full_local_drag():
    case = prepare_case(_config(), case_id='missing-drag')
    parameters = mutable_data(case.parameters)
    del parameters['flow_inputs']['B']['K_field_m2']
    with pytest.raises(ValueError, match='local flow B K_field_m2'):
        build_execution_inputs(replace(case, parameters=parameters))


def test_replay_retains_continuous_calibration_transfer_policy(tmp_path):
    from sjtu_tpmshx.io.case_io import save_case, load_case
    config = _config(df_mode='experimental')
    config = replace(config, fluid_A=replace(config.fluid_A, u_mps=3.7))
    case = prepare_case(config, case_id='continuous-transfer-replay')
    save_case(case, tmp_path / 'case.yaml')
    cfg, _ = build_execution_inputs(replace(load_case(tmp_path / 'case.yaml'), config_snapshot={}))
    assert cfg['compute_cfg'].zones.enabled
    assert cfg['compute_cfg'].zones.axis == 'continuous'
    assert cfg['compute_cfg'].zones.config == config.zones.config
    assert cfg['compute_cfg'].fluid_A.u_mps == 3.7
    with pytest.raises(ValueError, match='experimental calibration unavailable'):
        prepare_case(replace(config, zones=ZoneInputConfig()), case_id='uniform-window-unchanged')


def test_constant_controls_match_uniform_native_numerics():
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate
    config = _config(uniform=True, df_mode='experimental')
    config = replace(config, solver=replace(config.solver, max_outer_ltne=3, max_iter_simple=500))
    uniform = run_case(prepare_case(replace(config, zones=ZoneInputConfig()), case_id='uniform-native'))
    spline = run_case(prepare_case(config, case_id='spline-native'))
    assert uniform.metadata['thermal_mode'] == spline.metadata['thermal_mode'] == 'model_h'
    assert uniform.run_status['converged'] == spline.run_status['converged']
    for name in ('Ta', 'Tb', 'Ts', 'h_vA', 'h_vB', 'K_ss'):
        np.testing.assert_allclose(spline.fields[name], uniform.fields[name], rtol=1e-10, atol=1e-10)
    uniform_metrics, spline_metrics = evaluate(uniform).metrics, evaluate(spline).metrics
    for name in ('Q_A', 'Q_B', 'dP_A', 'dP_B', 'mass_flow_A', 'mass_flow_B'):
        assert spline_metrics[name].spec.unit == uniform_metrics[name].spec.unit
        assert spline_metrics[name].value == pytest.approx(uniform_metrics[name].value, rel=1e-10, abs=1e-10)
    assert spline_metrics['Q_B'].spec.unit == 'W/m'
