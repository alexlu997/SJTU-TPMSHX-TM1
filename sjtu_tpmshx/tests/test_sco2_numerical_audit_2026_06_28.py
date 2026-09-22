"""Historical sCO2 duty contrast and current local-property regressions.

The 2026-06-28 audit identified these historical defects:

  D1  2D coupled duty used ṁ·cp(T_in)·ΔT instead of the true enthalpy
      ṁ·(⟨h_in⟩ − ⟨h_out⟩); −40 %…+224 % off near the pseudocritical line.
      The scalar-pressure correction below is a test-only historical reference;
      current 2D/3D true-h duty uses recorded face mass flow and enthalpy.
  D2  3D duty evaluated h(⟨T⟩_out) instead of the mass-weighted mean
      enthalpy ⟨h(T)⟩_out — a Jensen error largest exactly at the cp spike.
  D3  3D volumetric h_v froze k/μ/ρ/Pr at the scalar inlet T while the
      neighbouring K_ff/ρcp already used the local Ta field — inconsistent,
      h_v biased many-fold for sCO2 wherever local T departs from inlet.

See vault reports/engineering/audit/2026-06-28-* (D1/D2/D3 detail).
"""
import numpy as np
import pytest

from sjtu_tpmshx.models import sco2_props, fluid_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")

_P = 8.0e6  # Pa — CO2 pseudocritical T ≈ 307.7 K at this pressure


# ── D1 : 2D true-enthalpy coupled duty ──────────────────────────────────────
def test_d1_historical_scalar_pressure_duty_differs_from_inlet_cp():
    """The retained historical h(T) reference differs materially from inlet cp."""
    from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _enthalpy_balance_2d
    from sjtu_tpmshx.tests.enthalpy_2d_reference import scalar_pressure_duty
    m = fluid_props.get('sco2')

    Nx, Ny = 4, 3
    T_in, T_out = 360.0, 310.0          # cooling, straddles the spike
    Ta = np.empty((Nx, Ny))
    Ta[0, :] = T_in                     # dir_code 0 → inlet plane i=0
    Ta[1:-1, :] = 0.5 * (T_in + T_out)
    Ta[-1, :] = T_out                   # outlet plane i=-1
    uc = np.full((Nx, Ny), 2.0)
    vc = np.zeros((Nx, Ny))
    dx = np.ones(Nx)
    dy = np.ones(Ny)
    rho_cp_in = sco2_props.sco2_prop('D', T_in, _P) * sco2_props.sco2_prop('C', T_in, _P)
    rho_cp = np.full((Nx, Ny), rho_cp_in)

    # Temperature-formulation approximation, not the current sCO2 duty route.
    Q_cp = _enthalpy_balance_2d(Ta, uc, vc, rho_cp, 0, dx, dy)
    # Historical scalar-pressure reference.
    Q_h = scalar_pressure_duty(
        Ta, uc, vc, 0, dx, dy,
        enthalpy_fn=m.enthalpy, rho_fn=m.rho, P_ref=_P)

    # reference ṁ·Δh (uniform inlet/outlet faces → ⟨h⟩ = h(T_face))
    m_dot = sco2_props.sco2_prop('D', T_in, _P) * 2.0 * dy.sum()
    Q_ref = m_dot * (sco2_props.sco2_prop('H', T_in, _P)
                     - sco2_props.sco2_prop('H', T_out, _P))
    assert Q_h == pytest.approx(Q_ref, rel=1e-9)
    # the inlet-cp approximation is wrong by tens of percent
    assert abs(Q_cp - Q_h) / abs(Q_h) > 0.30


def test_d1_temperature_duty_retains_capacity_weighting():
    """Temperature-formulation duty retains its independent capacity weighting."""
    from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _enthalpy_balance_2d
    rng = np.random.default_rng(0)
    Ta = 300.0 + rng.random((5, 4)) * 50.0
    uc = rng.random((5, 4)) + 0.1
    vc = np.zeros((5, 4))
    rho_cp = np.full((5, 4), 1.2 * 1005.0)
    dx = np.ones(5)
    dy = np.ones(4)
    Q = _enthalpy_balance_2d(Ta, uc, vc, rho_cp, 0, dx, dy)
    # hand-rolled legacy form
    w_in = rho_cp[0, :] * np.abs(uc[0, :]) * dy
    w_out = rho_cp[-1, :] * np.abs(uc[-1, :]) * dy
    Ti = float(np.sum(w_in * Ta[0, :]) / np.sum(w_in))
    To = float(np.sum(w_out * Ta[-1, :]) / np.sum(w_out))
    assert Q == pytest.approx(float(np.sum(w_in)) * (Ti - To), rel=1e-12)


# ── D2 : 3D mass-weighted mean OUTLET enthalpy ⟨h(T)⟩, not h(⟨T⟩) ────────────
def _fake_outlet_solver(Nx, Nz):
    from types import SimpleNamespace
    v = np.zeros((Nx, 1, Nz))
    v[:, -1, :] = 1.0                       # uniform outlet-plane velocity
    rho = np.ones((Nx, 1, Nz))
    return SimpleNamespace(v=v, rho_field=rho, dx=np.ones(Nx), dz=np.ones(Nz))


def test_d2_mass_weighted_outlet_enthalpy_not_h_of_mean():
    from sjtu_tpmshx.solvers.backends.python.three_d.flux import _mass_weighted_h_out, _mass_weighted_T_out
    Nx, Nz = 2, 2
    T_face = np.array([[300.0, 315.0], [305.0, 312.0]])   # straddles the spike
    solver = _fake_outlet_solver(Nx, Nz)
    eps_f = 0.5

    h_avg = _mass_weighted_h_out(T_face, _P, lambda T, P: sco2_props.sco2_prop("H", T, P),
                                 solver, eps_f)
    T_avg = _mass_weighted_T_out(T_face, solver, eps_f)

    # equal weights → ⟨h(T)⟩ = mean of per-cell enthalpy
    h_mean_ref = float(np.mean(sco2_props.sco2_prop('H', T_face, _P)))
    assert h_avg == pytest.approx(h_mean_ref, rel=1e-9)

    # Jensen: ⟨h(T)⟩ ≠ h(⟨T⟩) — non-trivial relative to the face enthalpy span
    h_of_mean = float(sco2_props.sco2_prop('H', T_avg, _P))
    span = abs(sco2_props.sco2_prop('H', 300.0, _P)
               - sco2_props.sco2_prop('H', 315.0, _P))
    assert abs(h_avg - h_of_mean) / span > 0.02


# ── D3 : 3D h_v with LOCAL-temperature transport props (sCO2) ────────────────
def test_d3_sco2_hv_uses_local_temperature_props():
    # No effective parameter selection: both paths use the smooth CFD base.
    from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field
    from sjtu_tpmshx.models.tpms_calc import nu_sco2_topo

    A_0, D_h_m = 500.0, 1.0e-3
    u_abs = np.full((2, 2, 2), 1.5)
    T_in = 320.0
    T_field = np.full((2, 2, 2), T_in)
    T_field[1, 1, 1] = 450.0               # a cell far from the inlet state

    hv = _sco2_hv_local_field(T_field, _P, u_abs, A_0, D_h_m, 'Diamond', 7.0)

    # frozen-at-inlet h_v (what the buggy scalar path applies to EVERY cell)
    rho_i = sco2_props.sco2_prop('D', T_in, _P)
    mu_i = sco2_props.sco2_prop('V', T_in, _P)
    k_i = sco2_props.sco2_prop('L', T_in, _P)
    Pr_i = sco2_props.sco2_prop('C', T_in, _P) * mu_i / k_i
    Re_i = rho_i * 1.5 * D_h_m / mu_i
    Nu_i = nu_sco2_topo('Diamond', max(Re_i, 1.0), Pr_i, 7.0, D_h_m * 1000.0)
    hv_frozen = A_0 * Nu_i * k_i / D_h_m

    # cells at the inlet state match the frozen value (no spurious change)
    assert hv[0, 0, 0] == pytest.approx(hv_frozen, rel=1e-9)
    # the departed cell differs by a large factor (the frozen-prop bias)
    assert abs(hv[1, 1, 1] - hv_frozen) / hv_frozen > 0.20
