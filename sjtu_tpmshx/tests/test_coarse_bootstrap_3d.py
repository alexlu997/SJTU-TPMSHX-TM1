"""Coarse-grid bootstrap (Phase C) regression tests."""
from __future__ import annotations
import warnings

import numpy as np

warnings.filterwarnings('ignore')

from sjtu_tpmshx.solvers.coarse_bootstrap_3d import (
    bootstrap_simple_3d, _block_average_2d, _block_average_3d,
    _trilinear_zoom)
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _build_solver():
    # All axes ≥ 8 so coarse 2× halving stays ≥ 4 (min_coarse_axis gate).
    Nx, Ny, Nz = 16, 12, 8
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=350.0, v_inlet=3.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)


def test_block_average_2d_shape_and_value():
    arr = np.ones((8, 6))
    out = _block_average_2d(arr, 2, 2)
    assert out.shape == (4, 3)
    np.testing.assert_allclose(out, 1.0)


def test_block_average_3d_shape():
    arr = np.arange(2 * 4 * 6, dtype=float).reshape(2, 4, 6)
    out = _block_average_3d(arr, 1, 2, 2)
    assert out.shape == (2, 2, 3)


def test_trilinear_zoom_preserves_constant():
    arr = np.full((6, 4, 3), 7.5)
    out = _trilinear_zoom(arr, (12, 8, 6))
    assert out.shape == (12, 8, 6)
    np.testing.assert_allclose(out, 7.5, atol=1e-9)


def test_bootstrap_skips_too_small_grid():
    """Coarse axis < 4 → bootstrap skipped, no exception."""
    Nx, Ny, Nz = 6, 6, 4   # Nz//2=2 < min_coarse_axis=4
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    s = SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=350.0, v_inlet=3.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)
    info = bootstrap_simple_3d(s)
    assert info['applied'] is False
    assert info['reason'] == 'coarse-too-small'


def test_bootstrap_seeds_fine_velocity_field():
    """After bootstrap, fine v[:, 0, :] equals inlet BC and field is
    not all-zero (cold-start would leave it zero outside the inlet)."""
    s = _build_solver()
    info = bootstrap_simple_3d(s, max_iter_coarse=50)
    assert info['applied'] is True
    assert info['coarse_shape'] == (8, 6, 4)
    # Fine v field should not be all zeros after prolongation.
    assert np.any(np.abs(s.v) > 1e-6)
    # Inlet BC re-imposed exactly.
    np.testing.assert_allclose(s.v[:, 0, :], s.v_inlet_field, atol=1e-12)


def test_bootstrap_solver_matches_baseline_converged_state():
    """Bootstrapped solver must reach the same converged state as the
    cold-start baseline (zero precision loss)."""
    s_cold = _build_solver()
    conv_c, it_c = s_cold.solve(max_iter=400, tol=1e-4)
    assert conv_c, "Cold-start baseline did not converge"

    s_warm = _build_solver()
    s_warm.use_coarse_bootstrap = True
    s_warm.coarse_bootstrap_max_iter = 80
    conv_w, it_w = s_warm.solve(max_iter=400, tol=1e-4)
    assert conv_w, "Bootstrap-warmed solver did not converge"

    # Coarse bootstrap should at minimum not slow cold-start; ideally faster.
    # Allow some slack since this is a small test grid.
    assert it_w <= it_c + 30, (
        f"Bootstrap slowed solver: warm {it_w} vs cold {it_c} iters")

    # Final fields must agree (Anderson rollback / Phase A both preserve
    # final attractor; bootstrap is only an init perturbation).
    np.testing.assert_allclose(s_cold.u, s_warm.u, rtol=2e-2, atol=1e-3)
    np.testing.assert_allclose(s_cold.v, s_warm.v, rtol=2e-2, atol=1e-3)


def test_bootstrap_rebuilds_rectangles_and_conserves_inlet_mass(monkeypatch):
    # Odd, nonuniform axes deliberately cut the opening in different fine and
    # coarse cells. Mock only solve: all real setup and transfer run normally.
    widths = [np.linspace(.3, 1.7, n) / n for n in (9, 9, 11)]
    fine = SIMPLESolver3D(1., 1., 1., 9, 9, 11, 2., .01, 300., 0.,
                         eps=.6, fluid_type='incompressible',
                         dx_arr=widths[0], dy_arr=widths[1], dz_arr=widths[2],
                         inlet_rect=(.61, .97, .13, .86),
                         outlet_rect=(.08, .42, .23, .93))
    fine.rho_field[:] = np.linspace(1., 3., 9)[:, None, None]
    fine.eps_field[:] = np.linspace(.4, .7, 11)[None, None, :]
    fine.v_inlet_field = fine.inlet_frac * np.linspace(.5, 1.5, 11)[None, :]
    fine._massflux_target = fine.rho_field[:, 0, :] * fine.v_inlet_field
    target = np.sum(fine._massflux_target * fine.eps_field[:, 0, :]
                    * fine.dx[:, None] * fine.dz[None, :])
    seen = []

    def solve(coarse, **kwargs):
        seen.append(coarse)
        assert kwargs['max_iter'] == 37 and coarse.convergence_mode == 'f2'
        assert coarse.inlet_rect == fine.inlet_rect
        assert coarse.outlet_rect == fine.outlet_rect
        area = coarse.dx[:, None] * coarse.dz[None, :]
        np.testing.assert_allclose(np.sum(coarse.rho_field[:, 0, :]
                                   * coarse.eps_field[:, 0, :] * coarse.v_inlet_field * area),
                                   target, rtol=2e-14)
        np.testing.assert_allclose(np.sum(coarse.inlet_frac * area), .36 * .73)
        assert np.all(coarse.v_inlet_field[coarse.inlet_frac == 0.] == 0.)
        assert coarse.outlet_u_frac.shape == (5, 5)
        assert coarse.outlet_w_frac.shape == (4, 6)
        coarse.v[:] = .3
        coarse.residuals = [.01]
        return False, 37

    monkeypatch.setattr(SIMPLESolver3D, 'solve', solve)
    info = bootstrap_simple_3d(fine, max_iter_coarse=37)
    assert len(seen) == 1 and info['applied'] and not info['coarse_converged']
    np.testing.assert_array_equal(fine.v[:, 0, :], fine.v_inlet_field)
    assert np.all(fine.v[:, -1, :][~fine.outlet_mask_ij] == 0.)
    np.testing.assert_allclose(np.sum(fine.rho_field[:, 0, :] * fine.eps_field[:, 0, :]
                               * fine.v[:, 0, :] * fine.dx[:, None] * fine.dz[None, :]), target)
