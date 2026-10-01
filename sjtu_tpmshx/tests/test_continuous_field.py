"""
test_continuous_field.py — Unit tests for models.continuous_field.

Covers:
  * decision-vector dim, bounds, decode/encode round-trips (symmetric + not)
  * spline field evaluation (uniform, linear gradient, defensive clamping)
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from sjtu_tpmshx.models.continuous_field import (
    ContinuousFieldConfig,
    decision_dim,
    decision_bounds,
    decode_decision_vector,
    encode_decision_vector,
    from_decision_vector,
    uniform_field,
    DEFAULT_L_BOUNDS,
    DEFAULT_T_BOUNDS,
)


# ─── Decision-vector layout ─────────────────────────────────────────


def test_decision_dim_4x4_symmetric_is_16():
    assert decision_dim(4, 4, symmetric_y=True) == 16


def test_decision_dim_4x4_asymmetric_is_32():
    assert decision_dim(4, 4, symmetric_y=False) == 32


def test_decision_dim_3x3_symmetric_is_12():
    # ⌈3/2⌉ = 2 unique rows × 3 cols × 2 fields = 12
    assert decision_dim(3, 3, symmetric_y=True) == 12


def test_decision_bounds_shape_and_range():
    lb, ub = decision_bounds(4, 4, symmetric_y=True,
                              L_bounds=(3.0, 10.0), t_bounds=(0.2, 0.8))
    assert lb.size == 16 and ub.size == 16
    assert np.all(lb[:8] == 3.0) and np.all(ub[:8] == 10.0)
    assert np.all(lb[8:] == 0.2) and np.all(ub[8:] == 0.8)


# ─── Decode / encode round-trip ─────────────────────────────────────


def test_decode_encode_roundtrip_symmetric_4x4():
    L = np.array([[5.0, 6.0, 6.0, 5.0],
                  [5.5, 6.5, 6.5, 5.5],
                  [6.0, 7.0, 7.0, 6.0],
                  [5.5, 6.5, 6.5, 5.5]], dtype=np.float64)
    t = np.full((4, 4), 0.4)
    x = encode_decision_vector(L, t, symmetric_y=True)
    L2, t2 = decode_decision_vector(x, 4, 4, symmetric_y=True)
    assert np.allclose(L, L2)
    assert np.allclose(t, t2)


def test_decode_encode_roundtrip_asymmetric_3x4():
    rng = np.random.default_rng(0)
    L = rng.uniform(3.0, 10.0, size=(3, 4))
    t = rng.uniform(0.2, 0.8, size=(3, 4))
    x = encode_decision_vector(L, t, symmetric_y=False)
    L2, t2 = decode_decision_vector(x, 3, 4, symmetric_y=False)
    assert np.allclose(L, L2)
    assert np.allclose(t, t2)


def test_decode_encode_roundtrip_symmetric_odd_my():
    # 4×3 + symmetric_y: ⌈3/2⌉ = 2 unique rows; full reconstructed
    # must mirror seam-skip.
    L = np.array([[5.0, 6.0, 5.0],
                  [5.5, 6.5, 5.5],
                  [6.0, 7.0, 6.0],
                  [5.5, 6.5, 5.5]], dtype=np.float64)
    t = np.full((4, 3), 0.4)
    x = encode_decision_vector(L, t, symmetric_y=True)
    L2, t2 = decode_decision_vector(x, 4, 3, symmetric_y=True)
    assert np.allclose(L, L2)
    assert np.allclose(t, t2)


def test_decode_dimension_mismatch_raises():
    bad_x = np.zeros(15)   # 16 expected
    with pytest.raises(ValueError):
        decode_decision_vector(bad_x, 4, 4, symmetric_y=True)


# ─── Field evaluation ───────────────────────────────────────────────


def test_uniform_field_eval_returns_uniform():
    fc = uniform_field(6.0, 0.4, 'Diamond', 15.0, 0.1, 0.1)
    L_field, t_field = fc.evaluate_grid(20, 20)
    assert L_field.shape == (20, 20)
    assert np.allclose(L_field, 6.0, atol=1e-9)
    assert np.allclose(t_field, 0.4, atol=1e-9)


def test_linear_gradient_in_y_is_monotonic():
    """Ramping L from 4 → 8 along y should produce a monotonic field."""
    L_ctrl = np.tile(np.array([4.0, 5.5, 6.5, 8.0]), (4, 1))   # ramp in y
    t_ctrl = np.full((4, 4), 0.4)
    fc = ContinuousFieldConfig(
        ctrl_x=np.linspace(0, 0.1, 4),
        ctrl_y=np.linspace(0, 0.1, 4),
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type='Diamond', k_s=15.0,
        L_domain=0.1, H_domain=0.1,
    )
    L_field, _ = fc.evaluate_grid(20, 20)
    # Cell-row at y=0 < y=mid < y=H along centre slice
    assert L_field[10, 0] < L_field[10, 10] < L_field[10, -1]
    assert abs(L_field[10, 0] - 4.0) < 0.5
    assert abs(L_field[10, -1] - 8.0) < 0.5


def test_bounds_clamping_after_spline_overshoot():
    """Extreme corner control values: spline can overshoot — output must
    still respect L_bounds / t_bounds.
    """
    L_ctrl = np.array([[10.0, 10.0,  3.0,  3.0],
                       [10.0,  3.0, 10.0,  3.0],
                       [ 3.0, 10.0,  3.0, 10.0],
                       [ 3.0,  3.0, 10.0, 10.0]], dtype=np.float64)
    t_ctrl = np.full((4, 4), 0.4)
    fc = ContinuousFieldConfig(
        ctrl_x=np.linspace(0, 0.1, 4),
        ctrl_y=np.linspace(0, 0.1, 4),
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type='Diamond', k_s=15.0,
        L_domain=0.1, H_domain=0.1,
        L_bounds=DEFAULT_L_BOUNDS, t_bounds=DEFAULT_T_BOUNDS,
    )
    L_field, t_field = fc.evaluate_grid(40, 40)
    assert L_field.min() >= DEFAULT_L_BOUNDS[0] - 1e-12
    assert L_field.max() <= DEFAULT_L_BOUNDS[1] + 1e-12
    assert t_field.min() >= DEFAULT_T_BOUNDS[0] - 1e-12
    assert t_field.max() <= DEFAULT_T_BOUNDS[1] + 1e-12


def test_evaluate_grid_with_nonuniform_dx_dy():
    """Non-uniform cell widths still produce correctly-shaped fields and
    reasonable values (no NaNs / out-of-bounds)."""
    fc = uniform_field(6.0, 0.4, 'Diamond', 15.0, 0.1, 0.1)
    Nx, Ny = 12, 16
    # mildly non-uniform: stretch toward each axis end
    dx = np.linspace(0.5, 1.5, Nx)
    dx = dx / dx.sum() * 0.1
    dy = np.linspace(1.5, 0.5, Ny)
    dy = dy / dy.sum() * 0.1
    L_field, t_field = fc.evaluate_grid(Nx, Ny, dx_arr=dx, dy_arr=dy)
    assert L_field.shape == (Nx, Ny)
    assert np.all(np.isfinite(L_field)) and np.all(np.isfinite(t_field))
    assert np.allclose(L_field, 6.0, atol=1e-9)


# ─── from_decision_vector convenience ───────────────────────────────


def test_from_decision_vector_round_trip():
    """from_decision_vector + encode round-trips through ContinuousFieldConfig."""
    L = np.array([[5.0, 6.0, 6.0, 5.0],
                  [5.5, 6.5, 6.5, 5.5],
                  [6.0, 7.0, 7.0, 6.0],
                  [5.5, 6.5, 6.5, 5.5]], dtype=np.float64)
    t = np.full((4, 4), 0.4)
    x = encode_decision_vector(L, t, symmetric_y=True)

    fc = from_decision_vector(
        x, tpms_type='Diamond', k_s=15.0,
        L_domain=0.1, H_domain=0.1,
        n_ctrl_x=4, n_ctrl_y=4, symmetric_y=True,
    )
    assert np.allclose(fc.L_ctrl, L)
    assert np.allclose(fc.t_ctrl, t)
    assert fc.tpms_type == 'Diamond'


def test_original_config_and_csv_replay_preserve_asymmetric_quadratic_field(tmp_path):
    from sjtu_tpmshx.optimization.pareto_io import read_pareto_csv

    cfg = {'tpms_type': 'Gyroid', 'k_s': 17., 'L_domain': 0.182,
           'H_domain': 0.042, 'n_ctrl_x': 3, 'n_ctrl_y': 3,
           'symmetric_y': False, 'spline_order': 2,
           'L_bounds': DEFAULT_L_BOUNDS, 't_bounds': DEFAULT_T_BOUNDS}
    rng = np.random.default_rng(42)
    x = encode_decision_vector(rng.uniform(5.0, 7.0, (3, 3)),
                               rng.uniform(0.38, 0.48, (3, 3)), symmetric_y=False)
    original = from_decision_vector(x, **cfg)
    (tmp_path / 'config.json').write_text(json.dumps(cfg, allow_nan=False))
    path = tmp_path / 'pareto_final.csv'
    np.savetxt(path, np.r_[x, 100., 20.][None, :], delimiter=',', fmt='%.17g',
               header=','.join([*(f'x{i}' for i in range(x.size)), 'Q_W_per_m', 'dP_Pa']),
               comments='')
    saved_x = read_pareto_csv(path, decision_dim_expected=18)[0, :-2]
    np.testing.assert_array_equal(saved_x, x)
    restored = from_decision_vector(saved_x, **json.loads((tmp_path / 'config.json').read_text()))
    dx = np.diff([0.0, 0.011, 0.047, 0.095, 0.182])
    dy = np.diff([0.0, 0.004, 0.013, 0.028, 0.042])
    for subdivisions in (1, 3):
        grid_x = np.repeat(dx / subdivisions, subdivisions)
        grid_y = np.repeat(dy / subdivisions, subdivisions)
        before = original.evaluate_grid(len(grid_x), len(grid_y), grid_x, grid_y)
        after = restored.evaluate_grid(len(grid_x), len(grid_y), grid_x, grid_y)
        for expected, actual in zip(before, after):
            np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('quadratic', [False, True])
def test_asymmetric_field_matches_analytic_values_on_physical_grids(quadratic):
    cfg = {'tpms_type': 'Gyroid', 'k_s': 17., 'L_domain': 0.182,
           'H_domain': 0.042, 'n_ctrl_x': 3, 'n_ctrl_y': 3,
           'symmetric_y': False, 'spline_order': 2,
           'L_bounds': DEFAULT_L_BOUNDS, 't_bounds': DEFAULT_T_BOUNDS}

    def analytic(x_m, y_m):
        # Coordinates are metres, returned geometry parameters are millimetres.
        cell = 5.0 + 4.0 * x_m + 10.0 * y_m
        wall = 0.34 + 0.2 * x_m + 0.8 * y_m
        if quadratic:
            cell = cell + 20.0 * x_m**2 + 20.0 * x_m * y_m
            wall = wall + 1.5 * x_m**2 + 2.0 * x_m * y_m + 2.0 * y_m**2
        return cell, wall

    control_values = analytic(np.linspace(0.0, cfg['L_domain'], 3)[:, None],
                              np.linspace(0.0, cfg['H_domain'], 3)[None, :])
    field = from_decision_vector(encode_decision_vector(*control_values, symmetric_y=False), **cfg)
    x_edges = np.array([0.0, 0.011, 0.047, 0.095, 0.182])
    y_edges = np.array([0.0, 0.004, 0.013, 0.028, 0.042])
    for subdivisions in (1, 3):
        dx = np.repeat(np.diff(x_edges) / subdivisions, subdivisions)
        dy = np.repeat(np.diff(y_edges) / subdivisions, subdivisions)
        xc, yc = np.cumsum(dx) - dx / 2.0, np.cumsum(dy) - dy / 2.0
        expected = analytic(xc[:, None], yc[None, :])
        actual = field.evaluate_grid(len(dx), len(dy), dx, dy)
        for values, reference, bounds in zip(actual, expected, (cfg['L_bounds'], cfg['t_bounds'])):
            assert bounds[0] < reference.min() < reference.max() < bounds[1]
            np.testing.assert_allclose(values, reference, rtol=0.0, atol=1e-13)
