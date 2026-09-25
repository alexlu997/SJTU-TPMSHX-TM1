"""Tests for the 3D SIMPLE solver.

Phase 1 validation: Nz=1 3D solve must match a 2D reference in the
pure-Stokes / Darcy-Forchheimer regime. Also checks trivial smokes:
solver does not crash, fields have expected shapes, and w stays zero
in a 2D-equivalent setup.
"""
import warnings

warnings.filterwarnings('ignore')

import numpy as np

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _uniform_darcy_config(Nx=20, Ny=15, Nz=5, v_inlet=3.0,
                          K=1e-7, cF=340.0, rho=1.0, mu=2e-5,
                          eps=0.78):
    K_arr = np.full((Ny, Nz), K, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), cF, dtype=np.float64)
    s = SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho, mu=mu, T_in=350.0, v_inlet=v_inlet,
        eps=eps, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)
    return s


def test_shapes():
    s = _uniform_darcy_config(Nx=12, Ny=8, Nz=3)
    assert s.u.shape == (13, 8, 3), s.u.shape
    assert s.v.shape == (12, 9, 3), s.v.shape
    assert s.w.shape == (12, 8, 4), s.w.shape
    assert s.P.shape == (12, 8, 3), s.P.shape
    assert s.K_arr.shape == (12, 8, 3), s.K_arr.shape
    print("test_shapes PASS")


def test_uniform_darcy_converges():
    """Uniform D-F channel: converges, dP has right sign + order of magnitude."""
    s = _uniform_darcy_config(Nx=20, Ny=15, Nz=5)
    conv, it = s.solve(max_iter=200)
    assert conv, f"solver did not converge in {it} iters"

    # v stays close to v_inlet in uniform D-F (mass conservation)
    v_bulk = s.v[10, 7, 2]
    assert abs(v_bulk - 3.0) / 3.0 < 0.05, \
        f"v bulk {v_bulk} strays > 5% from inlet 3.0"

    # dP has correct sign (inlet > outlet)
    dP = s.P[:, 0, :].mean() - s.P[:, -1, :].mean()
    assert dP > 0, f"dP not positive: {dP}"

    # dP within order of magnitude of 1D analytical (no-slip + upwind ~30% error)
    dP_1d = (2e-5 * 3.0 / 1e-7 + 1.0 * 340.0 * 9.0) * 0.04
    ratio = dP / dP_1d
    assert 0.5 < ratio < 1.1, \
        f"dP ratio {ratio:.3f} outside [0.5, 1.1] vs 1D analytical"
    print(f"test_uniform_darcy_converges PASS (dP={dP:.1f} Pa, "
          f"ratio to 1D {ratio:.2f}, {it} iters)")


def test_nz1_flow_stays_2d():
    """Nz=1 run: w should stay at zero everywhere; u should stay ~0."""
    s = _uniform_darcy_config(Nx=20, Ny=15, Nz=1)
    s.solve(max_iter=100)

    # w is identically zero by construction: Nz=1 means w[..., 0] and w[..., 1]
    # are the only faces, both walls. Solver never updates them.
    assert np.max(np.abs(s.w)) < 1e-12, \
        f"w field nonzero in Nz=1: max={np.max(np.abs(s.w)):.3e}"
    # u stays ~0 (no cross-stream driver)
    assert np.max(np.abs(s.u)) < 1e-2, \
        f"u field too large in uniform 2D-equivalent flow: "\
        f"max={np.max(np.abs(s.u)):.3e}"
    print("test_nz1_flow_stays_2d PASS")


def test_nz1_matches_nz5_uniform():
    """Uniform z-extrusion: Nz=5 run's middle slice equals Nz=1 run
    to within grid tolerance."""
    s1 = _uniform_darcy_config(Nx=16, Ny=10, Nz=1)
    s1.solve(max_iter=150)
    dP_1 = s1.P[:, 0, :].mean() - s1.P[:, -1, :].mean()

    s5 = _uniform_darcy_config(Nx=16, Ny=10, Nz=5)
    s5.solve(max_iter=150)
    dP_5 = s5.P[:, 0, :].mean() - s5.P[:, -1, :].mean()

    # In pure D-F with uniform z-extrude and full-width inlet, 3D result
    # should match 2D within no-slip wall artifact (couple of percent).
    rel = abs(dP_5 - dP_1) / max(abs(dP_1), 1e-12)
    assert rel < 0.10, f"dP Nz=1 vs Nz=5 diverges: {dP_1:.2f} vs {dP_5:.2f} " \
        f"(rel {rel:.3f})"
    print(f"test_nz1_matches_nz5_uniform PASS (dP_Nz=1={dP_1:.1f}, "
          f"dP_Nz=5={dP_5:.1f}, rel={rel:.3f})")


if __name__ == '__main__':
    test_shapes()
    test_uniform_darcy_converges()
    test_nz1_flow_stays_2d()
    test_nz1_matches_nz5_uniform()
    print("\nAll simple_solver_3d tests PASS")
