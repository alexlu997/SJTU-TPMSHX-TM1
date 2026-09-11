"""Tests for SIMPLESolver wall BC — verifies no-slip at side walls and
inlet / outlet semantics for a simple full-width configuration.
"""
import warnings

warnings.filterwarnings('ignore')

import numpy as np

from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry, P_atm
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


def _build_solver(Nx=24, Ny=80, wall_refine=False, v_in=4.0, T_in=450.0,
                  TPMS='Gyroid', L=7.0, t=0.4, k_s=16.0):
    g = tpms_geometry(TPMS, L, t, k_s)
    eps, D_h = g['epsilon'], g['D_h']
    W, H = 0.04, 0.2
    rho, mu = 1.0, 2.0e-5
    return SIMPLESolver(
        W, H, Nx, Ny, TPMS, L, t, eps, D_h / 2, rho, mu, T_in,
        0.0, W, v_in,                     # inlet full-width
        outlet_lo=0.0, outlet_hi=W,       # outlet full-width
        P_ref_abs=P_atm,
        wall_refine=wall_refine)


def test_no_slip_at_side_walls():
    """u-velocity at x=0 and x=W must be exactly 0 (wall BC enforced)."""
    s = _build_solver(wall_refine=False)
    s.solve(max_iter=300, tol=1e-4, verbose=False)
    u_left = s.u[0, :]
    u_right = s.u[s.Nx, :]
    assert np.allclose(u_left, 0.0), \
        f"u at left wall non-zero: max |u|={np.abs(u_left).max():.3e}"
    assert np.allclose(u_right, 0.0), \
        f"u at right wall non-zero: max |u|={np.abs(u_right).max():.3e}"
    print("test_no_slip_at_side_walls PASS")


def test_outlet_pinning_uniform_pressure():
    """Full-width outlet: all cells at j=Ny-1 must have equal P (pinned to 0)."""
    s = _build_solver()
    s.solve(max_iter=300, tol=1e-4, verbose=False)
    p_out = s.P[:, s.Ny - 1]
    assert p_out.std() < 1e-6, \
        f"outlet P std = {p_out.std():.3e} (expected ~0 for pinned cells)"
    assert np.allclose(p_out, 0.0, atol=1e-6), \
        f"outlet P not pinned to 0: mean={p_out.mean():.3e}"
    print("test_outlet_pinning_uniform_pressure PASS")


def test_dP_positive_and_monotone():
    """dP = P_inlet - P_outlet > 0; pressure decreases along stream (v-direction)."""
    s = _build_solver()
    s.solve(max_iter=300, tol=1e-4, verbose=False)
    p_profile = s.P.mean(axis=0)  # (Ny,), along stream
    dP = p_profile[0] - p_profile[-1]
    assert dP > 0, f"dP not positive: {dP:.3e}"
    # Monotone decrease: each step not increasing
    diffs = np.diff(p_profile)
    assert (diffs <= 1e-6).all(), \
        f"P not monotone along stream: max positive diff = {diffs.max():.3e}"
    print(f"test_dP_positive_and_monotone PASS (dP={dP:.1f} Pa)")


if __name__ == '__main__':
    test_no_slip_at_side_walls()
    test_outlet_pinning_uniform_pressure()
    test_dP_positive_and_monotone()
    print("\nAll SIMPLE wall BC tests PASS")
