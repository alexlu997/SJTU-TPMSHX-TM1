"""True XYZ control fields and their portable two-/three-dimensional contract."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.models.continuous_field import (
    decision_bounds, decision_dim, decode_decision_vector, encode_decision_vector,
    from_decision_vector,
)


def _field(L, t, order=2):
    return from_decision_vector(
        encode_decision_vector(L, t, False), 'Gyroid', 16., .182, .042,
        n_ctrl_x=L.shape[0], n_ctrl_y=L.shape[1], symmetric_y=False,
        spline_order=order, n_ctrl_z=L.shape[2], Lz_domain=.042)


@pytest.mark.parametrize('order', [1, 2, 3])
def test_tensor_field_reproduces_physical_polynomial_on_nonuniform_and_finer_grid(order):
    lengths = (.182, .042, .042)

    def analytic(x, y, z):
        # Physical coordinates in metres; every axis, including z, varies.
        L = 5. + 2*x + 3*y + 4*z
        t = .38 + .1*x + .2*y + .3*z
        if order >= 2:
            L = L + 5*x*x + 10*y*z + 8*z*z
            t = t + .3*x*y + .8*z*z
        if order == 3:
            L = L + 4*x*x*z
            t = t + .5*x*y*z
        return L, t

    controls = np.meshgrid(*(np.linspace(0, length, order+1) for length in lengths), indexing='ij')
    field = _field(*analytic(*controls), order=order)
    coarse = (np.array([.021, .048, .013, .100]),
              np.array([.005, .022, .015]), np.array([.012, .003, .018, .009]))
    for widths in (coarse, tuple(np.repeat(axis/2, 2) for axis in coarse)):
        centres = tuple(np.cumsum(axis) - .5*axis for axis in widths)
        expected = analytic(*np.meshgrid(*centres, indexing='ij'))
        actual = field.evaluate_volume(*(len(axis) for axis in widths), *widths)
        for sampled, exact in zip(actual, expected):
            assert sampled.shape == tuple(len(axis) for axis in widths)
            assert sampled.flags.c_contiguous
            np.testing.assert_allclose(sampled, exact, rtol=3e-14, atol=3e-14)
            assert np.all(np.ptp(sampled, axis=2) > 0.)


@pytest.mark.parametrize('order', [1, 2, 3])
def test_constant_xyz_field_is_exact_and_stays_within_bounds(order):
    shape = (order+1,)*3
    field = _field(np.full(shape, 7.), np.full(shape, .6), order)
    L, t = field.evaluate_volume(5, 7, 3)
    np.testing.assert_array_equal(L, np.full((5, 7, 3), 7.))
    np.testing.assert_array_equal(t, np.full((5, 7, 3), .6))
    alternating = np.indices(shape).sum(axis=0) % 2
    field = _field(4. + 4.*alternating, .3 + .3*alternating, order)
    L, t = field.evaluate_volume(13, 11, 9)
    assert np.all((L >= 4.) & (L <= 8.))
    assert np.all((t >= .3) & (t <= .6))


@pytest.mark.parametrize('ny,symmetric', [(3, False), (3, True), (4, True)])
def test_xyz_decision_layout_keeps_z_values_and_only_mirrors_y(ny, symmetric):
    count = 3*((ny+1)//2 if symmetric else ny)*3
    x = np.r_[np.linspace(4.123456789012345, 7.812345678901234, count),
              np.linspace(.312345678901234, .581234567890123, count)]
    assert decision_dim(3, ny, symmetric, n_ctrl_z=3) == 2*count
    lower, upper = decision_bounds(3, ny, symmetric, n_ctrl_z=3)
    np.testing.assert_array_equal(lower, [4.]*count + [.3]*count)
    np.testing.assert_array_equal(upper, [8.]*count + [.6]*count)
    L, t = decode_decision_vector(x, 3, ny, symmetric, n_ctrl_z=3)
    assert L.shape == t.shape == (3, ny, 3)
    np.testing.assert_array_equal(encode_decision_vector(L, t, symmetric, n_ctrl_z=3), x)
    if symmetric:
        np.testing.assert_array_equal(L, L[:, ::-1, :])
    assert np.all(np.ptp(L, axis=2) > 0.)


def _config(nz=3, n_ctrl_z=3):
    count = 9*(1 if n_ctrl_z is None else n_ctrl_z)
    spec = dict(x_decision=np.r_[np.linspace(4.123456789012345, 7.812345678901234, count),
                                np.linspace(.312345678901234, .581234567890123, count)].tolist(),
                n_ctrl_x=3, n_ctrl_y=3, symmetric_y=False, spline_order=2,
                L_bounds=[4., 8.], t_bounds=[.3, .6])
    if n_ctrl_z is not None:
        spec['n_ctrl_z'] = n_ctrl_z
    return ComputeConfig(
        geometry=GeometryConfig(L_cell_mm=7., t_wall_mm=.6, Lz_m=.042),
        fluid_A=FluidConfig(type='air', u_mps=10., T_in_K=400.),
        fluid_B=FluidConfig(type='water', u_mps=.1, T_in_K=300.),
        solver=SolverConfig(Nz=nz), zones=ZoneInputConfig(enabled=True, axis='continuous', config=spec),
        df_mode='experimental')


@pytest.mark.parametrize('nz,n_ctrl_z', [(1, None), (3, None), (3, 3)])
def test_json_replay_preserves_complete_xy_or_xyz_field(tmp_path, nz, n_ctrl_z):
    original = _config(nz, n_ctrl_z).validate()
    path = tmp_path / 'config.json'
    original.to_json(path)
    restored = ComputeConfig.from_json(path)
    assert restored.zones.config == original.zones.config
    sampled = []
    for cfg in (original, restored):
        spec = deepcopy(cfg.zones.config)
        decision = spec.pop('x_decision')
        field = from_decision_vector(decision, cfg.geometry.tpms, cfg.geometry.k_s_W_mK,
            cfg.geometry.L_dom_m, cfg.geometry.H_dom_m,
            **({'Lz_domain': cfg.geometry.Lz_m} if n_ctrl_z is not None else {}), **spec)
        sampled.append(field.evaluate_grid(7, 5) if n_ctrl_z is None else field.evaluate_volume(7, 5, 4))
    for original_values, replayed in zip(*sampled):
        np.testing.assert_array_equal(original_values, replayed)


@pytest.mark.parametrize('damage,match', [
    ('2d_z', '2D continuous'), ('few_z', 'more controls'), ('float_z', 'integer'),
    ('short_vector', 'values'), ('nan', 'finite'), ('bounds', 'increasing'),
    ('outside', 'within'), ('sco2', 'does not support zones'),
    ('anchor', 'uniform L/t'), ('domain', 'campaign domain'),
])
def test_continuous_contract_rejects_wrong_dimension_geometry_and_values(damage, match):
    cfg = _config()
    spec = cfg.zones.config
    if damage == '2d_z':
        cfg.solver.Nz = 1
    elif damage == 'few_z':
        spec['n_ctrl_z'] = 2
    elif damage == 'float_z':
        spec['n_ctrl_z'] = 3.
    elif damage == 'short_vector':
        spec['x_decision'].pop()
    elif damage == 'nan':
        spec['x_decision'][0] = float('nan')
    elif damage == 'bounds':
        spec['L_bounds'] = [8., 4.]
    elif damage == 'outside':
        spec['x_decision'][0] = 8.1
    elif damage == 'sco2':
        cfg.fluid_A = replace(cfg.fluid_A, type='sco2', P_in_Pa=8e6)
    elif damage == 'anchor':
        cfg.geometry.L_cell_mm = 6.
    elif damage == 'domain':
        cfg.geometry.L_dom_m = .2
    with pytest.raises(ValueError, match=match):
        cfg.validate()


@pytest.mark.parametrize('widths', [np.array([.021, .021]), np.array([0., .01, .032]),
                                  np.array([.01, np.nan, .02]), np.array([.01, .01, .01])])
def test_volume_rejects_cell_widths_that_do_not_describe_its_domain(widths):
    field = _field(np.full((3, 3, 3), 7.), np.full((3, 3, 3), .6))
    with pytest.raises(ValueError, match='cell widths'):
        field.evaluate_volume(4, 4, 3, dz_arr=widths)


def test_volume_requires_full_valid_xyz_controls():
    field = _field(np.full((3, 3, 3), 7.), np.full((3, 3, 3), .6))
    with pytest.raises(ValueError, match='evaluate_volume'):
        field.evaluate_grid(4, 4)
    with pytest.raises(ValueError, match='more controls'):
        _field(np.full((3, 3, 2), 7.), np.full((3, 3, 2), .6))
    with pytest.raises(ValueError, match='finite'):
        _field(np.full((3, 3, 3), np.inf), np.full((3, 3, 3), .6))
    with pytest.raises(ValueError, match='increase'):
        replace(field, ctrl_z=np.array([0., .05, .042]))
    with pytest.raises(ValueError, match='bounds'):
        replace(field, t_bounds=(.3, np.nan))
