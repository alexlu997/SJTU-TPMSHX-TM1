"""Continuous fields retain their physical coordinates and portable inputs."""
from dataclasses import asdict, replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FeatureFlags, FluidConfig, GeometryConfig,
    PartialBCConfig, SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.models.tpms_props import geometry
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.preprocess.api import prepare_case


def _spec(volume=False):
    coordinates = np.meshgrid(*([np.linspace(0., 1., 3)] * (3 if volume else 2)), indexing='ij')
    x, y = coordinates[:2]
    z = coordinates[2] if volume else 0.
    result = dict(x_decision=np.r_[(4.5 + 1.7*x + .8*y*y + .5*z + .2*x*z).ravel(),
                                   (.32 + .1*x*x + .12*y + .04*z*z + .01*x*z).ravel()].tolist(),
                n_ctrl_x=3, n_ctrl_y=3, symmetric_y=False, spline_order=2,
                L_bounds=[4., 8.], t_bounds=[.3, .6])
    if volume:
        result['n_ctrl_z'] = 3
    return result


def _config(volume=False):
    return ComputeConfig(
        geometry=GeometryConfig(tpms='Diamond', k_s_W_mK=22., L_dom_m=.06,
                                H_dom_m=.03, Lz_m=.02, L_cell_mm=7., t_wall_mm=.6),
        fluid_A=FluidConfig(type='air', u_mps=4., T_in_K=380., P_in_Pa=120000.),
        fluid_B=FluidConfig(type='water', u_mps=.03, T_in_K=300., P_in_Pa=150000.),
        bc_A=PartialBCConfig(dir=0),
        bc_B=PartialBCConfig(dir=3, in_ctr=.044, in_w=.019,
                            out_ctr=.016, out_w=.019),
        solver=SolverConfig(Nx=8, Ny=6, Nz=3),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis='continuous', config=_spec(volume)))


@pytest.mark.parametrize('volume', [False, True])
def test_nonuniform_3d_preparation_samples_exact_polynomial_and_replays_case(tmp_path, monkeypatch, volume):
    from sjtu_tpmshx.preprocess.three_d import preparation
    cfg = _config(volume)
    cfg.flags = FeatureFlags(port_wall_refine=True)
    cfg.solver = SolverConfig(Nx=50, Ny=10, Nz=10)
    observations = []
    original = preparation._record_air_bulk_ranges

    def record(inputs, local_L, local_t, shape):
        observations.append((local_L.copy(), local_t.copy()))
        return original(inputs, local_L, local_t, shape)

    monkeypatch.setattr(preparation, '_record_air_bulk_ranges', record)
    case = prepare_case(cfg, case_id='continuous-physical-coordinates')
    dx, dy, dz = (case.grid['d' + axis] for axis in 'xyz')
    assert not np.allclose(dx, np.mean(dx))
    assert not np.allclose(dy, np.mean(dy))
    x = (np.cumsum(dx) - dx/2)[:, None, None] / cfg.geometry.L_dom_m
    y = (np.cumsum(dy) - dy/2)[None, :, None] / cfg.geometry.H_dom_m
    z = (np.cumsum(dz) - dz/2)[None, None, :] / cfg.geometry.Lz_m if volume else np.zeros((1, 1, len(dz)))
    expected_L = 4.5 + 1.7*x + .8*y*y + .5*z + .2*x*z
    expected_t = .32 + .1*x*x + .12*y + .04*z*z + .01*x*z
    np.testing.assert_allclose(case.design_fields['L_field_m'], expected_L * 1e-3, rtol=2e-14)
    np.testing.assert_allclose(case.design_fields['t_field_m'], expected_t * 1e-3, rtol=2e-14)
    np.testing.assert_array_equal(observations[0][0], case.design_fields['L_field_m'] * 1e3)
    np.testing.assert_array_equal(observations[0][1], case.design_fields['t_field_m'] * 1e3)
    thermal = case.parameters['thermal_geometry']['fields']
    for index in ((0, 0, 0), (len(dx)//2, len(dy)//2, len(dz)//2),
                  (len(dx)-1, len(dy)-1, len(dz)-1)):
        expected = geometry('Diamond', expected_L[index], expected_t[index], 22.)
        for key in ('epsilon', 'A_0', 'D_h'):
            np.testing.assert_allclose(thermal[key][index], expected[key], rtol=2e-14)
        np.testing.assert_allclose(case.design_fields['eps_arr'][index], expected['epsilon'], rtol=2e-14)
        drag = predict_K_cF('Diamond', expected_L[index], expected_t[index], expected['epsilon']/2)
        for key, value in zip(('K_m2', 'cF_per_m'), drag):
            np.testing.assert_allclose(case.design_fields[key][index], value, rtol=2e-14)
    assert case.metadata['design_mode'] == ('continuous_xyz' if volume else 'continuous_xy_extruded')
    if volume:
        for values in case.design_fields.values():
            assert np.any(values[:, :, 0] != values[:, :, -1])
    assert mutable_data(case.config_snapshot['zones']['config']) == cfg.zones.config
    assert mutable_data(case.parameters['continuous_field']) == cfg.zones.config

    save_case(case, tmp_path / 'case.yaml')
    loaded = load_case(tmp_path / 'case.yaml')
    assert mutable_data(loaded.config_snapshot) == mutable_data(case.config_snapshot)
    assert mutable_data(loaded.parameters['continuous_field']) == cfg.zones.config
    for name, values in case.design_fields.items():
        np.testing.assert_array_equal(loaded.design_fields[name], values)
    for name in ('epsilon', 'A_0', 'D_h'):
        np.testing.assert_array_equal(loaded.parameters['thermal_geometry']['fields'][name], thermal[name])
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    _, replay = build_execution_inputs(replace(loaded, config_snapshot={}))
    for name, values in case.design_fields.items():
        np.testing.assert_array_equal(replay['design'][name], values)


@pytest.mark.parametrize('tpms', ['Gyroid', 'Diamond'])
@pytest.mark.parametrize('volume', [False, True])
def test_uniform_controls_match_uniform_prepared_geometry(tpms, monkeypatch, volume):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    cfg = _config(volume)
    cfg.geometry.tpms = tpms
    count = 27 if volume else 9
    cfg.zones.config['x_decision'] = [7.] * count + [.6] * count
    continuous = prepare_case(cfg, case_id='uniform-controls')
    uniform = prepare_case(replace(cfg, zones=ZoneInputConfig()), case_id='uniform-reference')
    for name, values in uniform.design_fields.items():
        np.testing.assert_array_equal(continuous.design_fields[name], values)
    for name in ('epsilon', 'A_0', 'D_h'):
        np.testing.assert_allclose(continuous.parameters['thermal_geometry']['fields'][name],
                                   uniform.parameters['thermal_geometry']['uniform'][name], rtol=2e-14)
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *a, **k: None)
    coefficients = []
    for case in (uniform, continuous):
        inputs, prepared = build_execution_inputs(case)
        prob = runtime.build_problem(inputs, prepared)
        hv = runtime._build_hv_machinery(prob)
        speed = np.linspace(0., 8., prob.Nx * prob.Ny * prob.Nz).reshape(prob.Nx, prob.Ny, prob.Nz)
        coefficients.append([hv._build_hv_local_3d(prob.L_mm_field, speed,
            fluid.T_in_K, fluid.P_in_Pa, fluid.type) for fluid in (cfg.fluid_A, cfg.fluid_B)])
    for uniform_h, continuous_h in zip(*coefficients):
        np.testing.assert_array_equal(uniform_h, continuous_h)


@pytest.mark.parametrize('tpms', ['Gyroid', 'Diamond'])
@pytest.mark.parametrize('volume', [False, True])
def test_nonuniform_local_hv_matches_independent_cell_formula(tpms, monkeypatch, volume):
    from sjtu_tpmshx.domain.run_warnings import range_context, warning_scope
    from sjtu_tpmshx.models.fluid_props import get
    from sjtu_tpmshx.models.nu_correlations import (
        NU_COEFFS, NU_LAM_FLOOR, NU_ROUGHNESS_FACTOR, Pr_AIR, WATER_NU_COEFFS,
    )
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs

    cfg = _config(volume)
    cfg.geometry.tpms = tpms
    case = prepare_case(cfg, case_id='nonuniform-local-hv')
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *a, **k: None)
    with warning_scope({}):
        prob = runtime.build_problem(*build_execution_inputs(case))
        hv = runtime._build_hv_machinery(prob)
    shape = (prob.Nx, prob.Ny, prob.Nz)
    dx, dy, dz = (case.grid['d' + axis] for axis in 'xyz')
    x = (np.cumsum(dx) - dx/2) / cfg.geometry.L_dom_m
    y = (np.cumsum(dy) - dy/2) / cfg.geometry.H_dom_m
    z = (np.cumsum(dz) - dz/2) / cfg.geometry.Lz_m if volume else np.zeros(len(dz))
    for side, fluid in (('A', cfg.fluid_A), ('B', cfg.fluid_B)):
        model = get(fluid.type)
        rho = float(model.rho(fluid.T_in_K, fluid.P_in_Pa))
        mu = float(model.mu(fluid.T_in_K, fluid.P_in_Pa))
        k_f = float(model.k(fluid.T_in_K, fluid.P_in_Pa))
        Pr = Pr_AIR if side == 'A' else float(model.cp(fluid.T_in_K, fluid.P_in_Pa)) * mu / k_f
        speed = np.geomspace(1e-6, 15. if side == 'A' else .3, np.prod(shape)).reshape(shape)
        speed[::2] *= -1.
        speed.flat[0] = 0.
        expected, raw_re, raw_nu = (np.empty(shape) for _ in range(3))
        for i, j, k in np.ndindex(shape):
            # Independent scalar geometry and published formula: neither
            # prepared thermal fields nor local_nusselt supply this oracle.
            length = 4.5 + 1.7*x[i] + .8*y[j]**2 + .5*z[k] + .2*x[i]*z[k]
            wall = .32 + .1*x[i]**2 + .12*y[j] + .04*z[k]**2 + .01*x[i]*z[k]
            g = geometry(tpms, length, wall, cfg.geometry.k_s_W_mK)
            reynolds = rho * (abs(float(speed[i, j, k])) + 1e-12) * g['D_h'] / mu
            re_eff = max(reynolds, 1.)
            coeff = NU_COEFFS[tpms] if side == 'A' else WATER_NU_COEFFS[tpms]
            nu = coeff['c'] * re_eff**coeff['a'] * Pr**(1/3)
            if side == 'A':
                nu *= NU_ROUGHNESS_FACTOR * (g['D_h'] * 1e3 / length)**coeff['d']
            expected[i, j, k] = g['A_0'] * max(nu, NU_LAM_FLOOR) * k_f / g['D_h']
            raw_re[i, j, k], raw_nu[i, j, k] = reynolds, nu
        assert raw_re.min() < 1. < raw_re.max()
        assert 0 < np.count_nonzero(raw_nu < NU_LAM_FLOOR) < raw_nu.size
        context = (side, 'local-hv-test', 'real-cell(x,y,z)')
        with warning_scope({}) as records, range_context(
                side=context[0], stage=context[1], layout=context[2]):
            actual = hv._build_hv_local_3d(
                prob.L_mm_field, speed, fluid.T_in_K, fluid.P_in_Pa, fluid.type)
        np.testing.assert_allclose(actual, expected, rtol=2e-14, atol=0.)
        raw = records[('nu_raw', fluid.type, tpms, shape, context)]
        source = records[('nu', fluid.type, tpms, shape, context)]
        assert raw.size == source.size == np.prod(shape)
        assert raw.minimum[0] == pytest.approx(raw_re.min(), rel=2e-14)
        assert raw.maximum[0] == pytest.approx(raw_re.max(), rel=2e-14)
        assert raw.low == np.count_nonzero(raw_re < raw.bounds[0])
        assert raw.high == np.count_nonzero(raw_re > raw.bounds[1])
        assert source.minimum[0] == 1.


@pytest.mark.parametrize('change', [
    {'n_ctrl_x': 1}, {'n_ctrl_y': 2}, {'n_ctrl_x': 3.0}, {'n_ctrl_y': True},
    {'spline_order': 0}, {'spline_order': 4}, {'spline_order': True}, {'symmetric_y': 1},
    {'x_decision': [7.] * 8 + [.6] * 9}, {'x_decision': [[7.]*9, [.6]*9]},
    {'x_decision': [float('nan')] + [7.]*8 + [.6]*9},
    {'x_decision': [float('inf')] + [7.]*8 + [.6]*9},
    {'x_decision': ['7'] + [7.]*8 + [.6]*9},
    {'x_decision': [True] + [7.]*8 + [.6]*9},
    {'x_decision': [3.9] + [7.]*8 + [.6]*9},
    {'x_decision': [7.]*9 + [.61]*9},
    {'L_bounds': [3.9, 8.]}, {'L_bounds': [4., 8.1]}, {'L_bounds': [8., 4.]},
    {'L_bounds': [4., 4.]}, {'L_bounds': [4.]}, {'L_bounds': [4., float('nan')]},
    {'t_bounds': [.29, .6]}, {'t_bounds': [.3, .61]}, {'t_bounds': ['.3', .6]},
    {'tpms_type': 'Gyroid'}, {'L_domain': .2},
])
def test_invalid_canonical_continuous_inputs_are_rejected(change):
    data = asdict(_config())
    data['zones']['config'].update(change)
    with pytest.raises(ValueError, match='Continuous field'):
        ComputeConfig.from_dict(data)


def test_missing_or_conflicting_continuous_input_is_rejected():
    for field in ('x_decision', 'spline_order'):
        data = asdict(_config())
        del data['zones']['config'][field]
        with pytest.raises(ValueError, match='Continuous field config requires'):
            ComputeConfig.from_dict(data)
    for field, value in (('grid', {'cells': []}), ('pareto_x_decision', [7.] * 36)):
        data = asdict(_config())
        data['zones'][field] = value
        with pytest.raises(ValueError, match='cannot also supply'):
            ComputeConfig.from_dict(data)


@pytest.mark.parametrize('symmetric_y,order,nx,ny', [(True, 2, 3, 3), (False, 1, 2, 2), (False, 3, 4, 4)])
def test_explicit_supported_layouts_keep_their_original_spec(symmetric_y, order, nx, ny):
    data = asdict(_config())
    count = nx * ((ny + 1)//2 if symmetric_y else ny)
    data['zones']['config'].update(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=symmetric_y,
                                  spline_order=order, x_decision=[7.]*count + [.6]*count)
    assert asdict(ComputeConfig.from_dict(data))['zones']['config'] == data['zones']['config']


@pytest.mark.parametrize('mode', ['delta', 'sco2'])
def test_continuous_fields_preserve_spatial_applicability_guards(mode):
    cfg = _config()
    if mode == 'delta':
        cfg.geometry.delta_levelset = .05
    else:
        cfg.fluid_A = FluidConfig(type='sco2', u_mps=1., T_in_K=400., P_in_Pa=8e6)
    with pytest.raises(ValueError, match='uniform L/t|delta_levelset=0|does not support zones'):
        prepare_case(cfg, case_id='unsupported-continuous')


@pytest.mark.parametrize('constant', [False, True])
@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('volume', [False, True])
def test_continuous_experimental_factors_reach_both_local_solver_fields(
        monkeypatch, tmp_path, constant, direction, volume):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    cfg = _config(volume)
    cfg.geometry = GeometryConfig(tpms='Gyroid', L_dom_m=.182, H_dom_m=.042,
                                  Lz_m=.042, L_cell_mm=7., t_wall_mm=.6)
    cfg.df_mode = 'experimental'
    cfg.bc_A = PartialBCConfig(dir=direction)
    cfg.bc_B = PartialBCConfig(dir=(direction + 3) % 6)
    if constant:
        count = 27 if volume else 9
        cfg.zones.config['x_decision'] = [7.] * count + [.6] * count
    case = prepare_case(cfg, case_id='continuous-calibrated')
    save_case(case, tmp_path / 'case.yaml')
    case = load_case(tmp_path / 'case.yaml')
    if volume and not constant:
        for values in case.design_fields.values():
            assert np.any(values[:, :, 0] != values[:, :, -1])
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *args, **kwargs: None)
    problem = runtime.build_problem(*build_execution_inputs(case))
    for side, solver, direction, factor in (
            ('A', problem.sA, cfg.bc_A.dir, 2.649010286988306),
            ('B', problem.sB, cfg.bc_B.dir, 4.198913430360186)):
        order = ((1, 0, 2), (0, 1, 2), (0, 2, 1))[direction // 2]
        for name, actual, scale in (('K_m2', solver.K_arr, 1.),
                                    ('cF_per_m', solver.cF_arr, factor)):
            expected = case.design_fields[name].transpose(order)
            if direction % 2:
                expected = expected[:, ::-1, :]
            np.testing.assert_array_equal(actual, expected * scale)
            if not constant:
                assert np.ptp(actual) > 0  # Full gradient survives the correction.
        info = solver._df_metadata
        assert info['scale_F'] == factor
        assert info['geometry_application'] == 'continuous-field-extrapolation'
        assert info['reference_geometry_mm'] == {'L': 7., 't': .6}


def test_2d_explicitly_rejects_three_dimensional_continuous_controls():
    cfg = _config(volume=True)
    cfg.solver.Nz = 1
    with pytest.raises(ValueError, match='2D continuous fields cannot supply n_ctrl_z'):
        prepare_case(cfg, case_id='unsupported-2d-continuous')


@pytest.mark.parametrize('volume', [False, True])
def test_execution_preserves_declared_continuous_dimension(volume):
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    case = prepare_case(_config(volume), case_id='declared-continuous-dimension')
    metadata = mutable_data(case.metadata)
    metadata['design_mode'] = 'continuous_xy_extruded' if volume else 'continuous_xyz'
    message = 'must be an xy extrusion' if volume else 'requires recorded 3D control inputs'
    with pytest.raises(ValueError, match=message):
        build_execution_inputs(replace(case, metadata=metadata))
