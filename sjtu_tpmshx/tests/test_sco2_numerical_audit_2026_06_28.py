"""Shared temperature-duty and local-property regressions from the sCO2 audit."""
import numpy as np
import pytest

from sjtu_tpmshx.models import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")

_P = 8.0e6  # Pa — CO2 pseudocritical T ≈ 307.7 K at this pressure


# ── D1 : 2D true-enthalpy coupled duty ──────────────────────────────────────


def test_d1_temperature_duty_retains_capacity_weighting():
    """Temperature-formulation duty retains its independent capacity weighting."""
    from sjtu_tpmshx.result_math import _enthalpy_balance_2d
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




# ── D3 : 3D h_v with LOCAL-temperature transport props (sCO2) ────────────────
def test_d3_sco2_hv_uses_local_temperature_props():
    # No effective parameter selection: both paths use the smooth CFD base.
    from sjtu_tpmshx.models.local_heat_transfer import real_fluid_hv_local_field
    from sjtu_tpmshx.models.tpms_calc import nu_sco2_topo

    A_0, D_h_m = 500.0, 1.0e-3
    u_abs = np.full((2, 2, 2), 1.5)
    T_in = 320.0
    T_field = np.full((2, 2, 2), T_in)
    T_field[1, 1, 1] = 450.0               # a cell far from the inlet state

    hv = real_fluid_hv_local_field(T_field, _P, u_abs, A_0, D_h_m, 'Diamond', 7.0)

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
