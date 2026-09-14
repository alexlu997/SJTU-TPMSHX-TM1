"""R1/R4 tests — openspec change solver-efficiency-r1-r4.

R1: 2D A+B early-exit (port of the 3D low-Re/plateau exit).
R4: opt-in 3D momentum SOU (flag off => bit-identical default path).
"""
from __future__ import annotations
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


def _make_solver(**kw):
    kwargs = dict(W=0.042, H=0.06, Nx=12, Ny=24,
                  tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.6,
                  r_h=1e-3, rho=1.2, mu=1.8e-5, T_in=322.0,
                  inlet_lo=0.0, inlet_hi=0.042, v_inlet=8.0,
                  wall_refine=False)
    kwargs.update(kw)
    return SIMPLESolver(**kwargs)


# ────────────────────────────────────────────────────────────────────
# R1 — 2D early-exit
# ────────────────────────────────────────────────────────────────────

def test_early_exit_fires_on_unreachable_tol():
    """tol=0 is unreachable for the absolute residual; the velocity-stability
    exit must still return converged well before max_iter."""
    s = _make_solver()
    conv, it = s.solve(max_iter=2000, tol=1e-30, verbose=False)
    assert conv and it < 500


def test_early_exit_off_restores_legacy_burnout():
    """lowre_early_exit=False → only the strict residual test remains, so an
    unreachable tol burns all max_iter (legacy behaviour)."""
    s = _make_solver()
    s.lowre_early_exit = False
    conv, it = s.solve(max_iter=100, tol=1e-30, verbose=False)
    assert (not conv) and it == 100


def test_early_exit_state_matches_deep_run():
    """The early-exit iterate must equal the flag-off deep-run iterate to
    engineering tolerance — evidence the exit only fires on a settled field."""
    sA = _make_solver()
    convA, itA = sA.solve(max_iter=2000, tol=1e-30, verbose=False)
    sB = _make_solver()
    sB.lowre_early_exit = False
    sB.solve(max_iter=2000, tol=1e-30, verbose=False)
    assert convA
    dP_A = float(sA.P[:, 0].mean() - sA.P[:, -1].mean())
    dP_B = float(sB.P[:, 0].mean() - sB.P[:, -1].mean())
    assert abs(dP_A - dP_B) / abs(dP_B) <= 5e-3
    vscale = float(np.linalg.norm(sB.v))
    assert float(np.linalg.norm(sA.v - sB.v)) / vscale <= 5e-3
    assert float(np.linalg.norm(sA.u - sB.u)) / vscale <= 5e-3


# ────────────────────────────────────────────────────────────────────
# R4 — 3D momentum SOU flag (default off == bit-identical)
# ────────────────────────────────────────────────────────────────────

def _make_solver_3d(**kw):
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
    Ny, Nz = 12, 4
    kwargs = dict(Lx=0.04, Ly=0.06, Lz=0.02, Nx=8, Ny=Ny, Nz=Nz,
                  rho=1.2, mu=1.8e-5, T_in=322.0, v_inlet=5.0, eps=0.6,
                  K_arr=np.full((Ny, Nz), 1e-7),
                  cF_arr=np.full((Ny, Nz), 0.1))
    kwargs.update(kw)
    return SIMPLESolver3D(**kwargs)


def test_sou_flag_off_bit_identical_3d():
    sA = _make_solver_3d()
    sA.solve(max_iter=40, tol=1e-30, verbose=False)
    sB = _make_solver_3d()
    sB.use_sou_momentum = False   # explicit off == unset default
    sB.solve(max_iter=40, tol=1e-30, verbose=False)
    assert np.array_equal(sA.u, sB.u)
    assert np.array_equal(sA.v, sB.v)
    assert np.array_equal(sA.w, sB.w)
    assert np.array_equal(sA.P, sB.P)


def test_sou_axis_matches_2d_kernels():
    """_sou_axis (3D shared helper) reproduces the 2D reference kernels
    exactly on random 1D profiles — cross-check of the flag conventions."""
    from sjtu_tpmshx.solvers.simple_solver import _sou_corr_u_x, _sou_corr_v_y
    from sjtu_tpmshx.solvers.simple_solver_3d import _sou_axis
    rng = np.random.default_rng(3)
    Nx, Ny = 9, 9
    u = rng.standard_normal((Nx + 1, Ny))
    v = rng.standard_normal((Nx, Ny + 1))
    Fe, Fw = 1.7, 1.3
    for j in (0, 4):
        for i in range(1, Nx):
            got = _sou_axis(u[max(i - 2, 0), j], u[max(i - 1, 0), j], u[i, j],
                            u[min(i + 1, Nx), j], u[min(i + 2, Nx), j],
                            i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1,
                            Fw, Fe)
            ref = _sou_corr_u_x(u, i, j, Nx, Fe, Fw)
            assert got == pytest.approx(ref, abs=1e-15), ('u-x', i, j)
    Fn, Fs = -0.9, 2.1
    for i in (0, 4):
        for j in range(1, Ny):
            got = _sou_axis(v[i, max(j - 2, 0)], v[i, max(j - 1, 0)], v[i, j],
                            v[i, min(j + 1, Ny)], v[i, min(j + 2, Ny)],
                            j > 2, j > 1, j + 2 <= Ny, j > 1,
                            Fs, Fn)
            ref = _sou_corr_v_y(v, i, j, Ny, Fn, Fs)
            assert got == pytest.approx(ref, abs=1e-15), ('v-y', i, j)


def test_sou_flag_on_runs_and_differs_3d():
    """SOU on: solver runs, stays finite, and actually changes the interior
    solution (deferred correction is live, not dead code)."""
    sA = _make_solver_3d()
    sA.solve(max_iter=60, tol=1e-30, verbose=False)
    sB = _make_solver_3d()
    sB.use_sou_momentum = True
    convB, _ = sB.solve(max_iter=60, tol=1e-30, verbose=False)
    assert np.all(np.isfinite(sB.v))
    assert not np.array_equal(sA.v, sB.v)
    # same physics to leading order: fields stay close
    vs = float(np.linalg.norm(sA.v))
    assert float(np.linalg.norm(sB.v - sA.v)) / vs <= 0.1
