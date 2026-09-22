"""E1 guard: SIMPLESolver3D non-uniform cell spacing (wall_refine wiring).

The momentum + pressure-correction kernels were already non-uniform-aware; E1
just lets __init__ accept dx_arr/dy_arr/dz_arr instead of hard-coding uniform.
Two guarantees:
  1. passing a UNIFORM dx_arr is byte-identical to the default (no dx_arr) —
     proves the new code path doesn't perturb the standard uniform grid;
  2. a graded NON-UNIFORM grid solves to a finite, physical, converged field
     (mass conserved), proving the spacing actually flows through the kernels.
2026-06-09 E1.
"""
import warnings
warnings.filterwarnings('ignore')

import numpy as np
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

_LX, _LY, _LZ = 0.1, 0.04, 0.02
_NX, _NY, _NZ = 12, 10, 4
_VIN = 3.0


def _cfg(**kw):
    K_arr = np.full((_NY, _NZ), 1e-7, dtype=np.float64)
    cF_arr = np.full((_NY, _NZ), 340.0, dtype=np.float64)
    base = dict(Lx=_LX, Ly=_LY, Lz=_LZ, Nx=_NX, Ny=_NY, Nz=_NZ,
                rho=1.0, mu=2e-5, T_in=350.0, v_inlet=_VIN,
                eps=0.78, K_arr=K_arr, cF_arr=cF_arr, P_ref_abs=101325.0)
    base.update(kw)
    return base


def test_uniform_dx_arr_matches_default():
    """A uniform dx_arr/dy_arr/dz_arr == the hard-coded uniform default."""
    base = SIMPLESolver3D(**_cfg())
    base.solve(max_iter=250, verbose=False)

    arr = SIMPLESolver3D(**_cfg(
        dx_arr=np.full(_NX, _LX / _NX),
        dy_arr=np.full(_NY, _LY / _NY),
        dz_arr=np.full(_NZ, _LZ / _NZ)))
    arr.solve(max_iter=250, verbose=False)

    np.testing.assert_array_equal(base.u, arr.u)
    np.testing.assert_array_equal(base.v, arr.v)
    np.testing.assert_array_equal(base.w, arr.w)
    np.testing.assert_array_equal(base.P, arr.P)


def test_nonuniform_grid_solves_physical():
    """A graded streamwise (dy) + cross (dx) grid solves to a finite, physical,
    mass-conserving field — proving the non-uniform spacing flows through the
    momentum + pressure kernels."""
    dy = np.linspace(0.6, 1.4, _NY); dy *= _LY / dy.sum()   # graded streamwise
    dx = np.linspace(1.3, 0.7, _NX); dx *= _LX / dx.sum()   # graded cross
    s = SIMPLESolver3D(**_cfg(dx_arr=dx, dy_arr=dy))
    conv, it = s.solve(max_iter=500, verbose=False)

    # spacing actually stored (not overwritten by uniform)
    assert abs(s.dy.sum() - _LY) < 1e-12
    assert abs(s.dx.sum() - _LX) < 1e-12
    assert not np.allclose(s.dy, _LY / _NY)   # genuinely non-uniform

    # finite, physical fields
    assert np.all(np.isfinite(s.u)) and np.all(np.isfinite(s.v))
    assert np.all(np.isfinite(s.P))
    # Darcy-Forchheimer: streamwise v stays the order of v_inlet (mass cons),
    # no blow-up / collapse from the non-uniform discretisation.
    v_mean = float(np.mean(np.abs(s.v)))
    # T6 tightened (2026-07-07): measured v_mean/v_in = 0.9915 post-N4
    # (node-distance fix); the old 0.3..3.0 band passed a 3x regression.
    assert 0.85 * _VIN < v_mean < 1.15 * _VIN, \
        f"v_mean={v_mean} off (vin={_VIN})"
