"""Q_enth_B mass-weighted outlet T must exclude stagnant warm cells.

Symptom (Shanghai case 1 pre-fix): Q_enth_B = 18 kW vs Q_solid_B = 1.3 kW (14x).
Cause: outlet face naive average includes warm stagnant corners where rho*|v| ~ 0
but T_b ~ T_inlet via LTNE source heating.
"""
import numpy as np
import pytest
from types import SimpleNamespace

from sjtu_tpmshx.solvers.backends.python.three_d.flux import _mass_weighted_T_out


def _mock_solver(NX=12, NY=6, NZ=12, eps=0.5, rho=1000.0):
    """Minimal solver-shaped object exposing only what _face_flux_weights uses."""
    v = np.zeros((NX, NY + 1, NZ))
    # outflow at the solver outlet face (j=-1) only in the left-third stripe.
    # approach-(a): _face_flux_weights reads the REAL outlet at solver j=-1
    # with outlet_frac for ALL dirs (the reverse-dir spatial flip lives in the
    # velocity transforms, not the accounting). Was j=0 under approach-(b).
    v[:4, -1, :] = -0.05
    rho_field = np.full((NX, NY, NZ), rho)
    eps_field = np.full((NX, NY, NZ), eps)
    dx = np.full(NX, 0.04 / NX)
    dz = np.full(NZ, 0.04 / NZ)
    outlet_frac = np.zeros((NX, NZ))
    outlet_frac[:4, :] = 1.0
    return SimpleNamespace(
        v=v, rho_field=rho_field, eps_field=eps_field,
        dx=dx, dz=dz, inlet_frac=None, outlet_frac=outlet_frac,
    )


def test_q_enth_b_excludes_stagnant_corners():
    """Mass-flux weighted T_b ~ T_active even when face has stagnant warm cells."""
    NX, NZ = 12, 12
    T_face = np.full((NX, NZ), 360.0)
    T_face[:4, :] = 350.0   # cold active stripe
    sol = _mock_solver(NX=NX, NZ=NZ)

    # dir_code=3 (-y): approach-(a) real_outlet -> solver j=-1 + outlet_frac.
    T_bulk = _mass_weighted_T_out(T_face, sol, dir_code=3, eps_f_scalar=0.5)

    assert abs(T_bulk - 350.0) < 0.1, f"bulk T_b leaked stagnant: {T_bulk:.2f}"

    # sanity: naive average is contaminated
    T_naive = float(np.mean(T_face))
    assert T_naive > 354.0, f"sanity check: naive avg {T_naive:.2f} should be >354"


def test_q_enth_b_no_active_flow_falls_back():
    """If outlet_frac=0 everywhere -> fall back to naive mean, no crash."""
    NX, NZ = 8, 8
    T_face = np.full((NX, NZ), 355.0)
    sol = _mock_solver(NX=NX, NZ=NZ)
    sol.outlet_frac = np.zeros((NX, NZ))   # no active outlet
    sol.v[:] = 0.0                          # no flow anywhere
    T_bulk = _mass_weighted_T_out(T_face, sol, dir_code=3, eps_f_scalar=0.5)
    assert T_bulk == pytest.approx(355.0, abs=1e-6)
