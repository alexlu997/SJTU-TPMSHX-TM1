# -*- coding: utf-8 -*-
"""703 sCO2 PCHE — METHOD B: 2D field-solver Δp confirmation at the METHOD-A geometry.

Method A (size_sco2_703.py) sizes each 703 core with a 1D enthalpy-segmented
ε-NTU + 1D Forchheimer Δp. This script drives the actual 2D SIMPLE/LTNE field
solver on the SAME sized geometry (frontal area + length) and the SAME closures
(nu_sco2_topo, cF×SCO2_CF_SCALE) to confirm the hot-side Δp and the duty
INDEPENDENTLY of the 1D estimate.

  * hot stream = sCO2, LIVE (incompressible SIMPLE, low-Mach var-property);
    properties refreshed PER CELL every outer iteration from CoolProp — this is
    the Phase C path, so it also carries the precooler's ×50 pseudocritical
    cp spike (far-from-critical devices just converge faster);
  * cold stream = PRESCRIBED counterflow (linear T from the spec/derated in/out)
    — the duty is governed by the A-side field heat transfer (same caveat as the
    Shanghai paper baseline);
  * Δp via extract_dP_mass_flux_from_simple (the mass-flux inlet convention).

Verdict per device: field hot-side Δp% vs the Method-A 1D Δp% (agreement ⇒ the
sizing's binding-side Δp is trustworthy). The precooler water side stays on the
1D estimate (water is the prescribed side here; its cF is the Shanghai-gated
gamma_df fit).

Run:  python -u projects/703-sCO2-D76/validate_sco2_703_field.py
"""
from __future__ import annotations

# ⚠ 2026-07-15: solver sCO2 closures switched to the SMOOTH-WALL unit-cell
# CFD campaign (nu_correlations.SCO2_NU_COEFFS now c·Re^a·Pr^⅓·(Dh/L)^d, both
# topologies; cF via df_surrogate.sco2_df, SCO2_CF_SCALE retired). This script
# validates against the D-7-6 EXPERIMENT (rough SLM part) — with smooth-wall
# closures its errors are EXPECTED to grow (~1.7× on Nu, ~3.4× on dP) until an
# experimental roughness anchor (gamma) lands. Historical experimental fit for
# reference: Nu = 0.28·Re^0.75·Pr^(1/3) (D76_EXP_NU), cF scale 3.39.
D76_EXP_NU = {'c': 0.28, 'a': 0.75}

import sys
import warnings
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sjtu_tpmshx.models import sco2_props as S                            # noqa: E402
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver                 # noqa: E402
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain              # noqa: E402
from sjtu_tpmshx.solvers.df_projection import extract_dP_mass_flux_from_simple  # noqa: E402
from sjtu_tpmshx.models.nu_correlations import nu_sco2_topo, nu_water_topo  # noqa: E402
# Historical D-7-6 experimental effective-cF multiplier (retired from
# production 2026-07-15 — solver now uses the smooth-wall sCO2 CFD cF).
# Kept LOCALLY here: this script validates the ROUGH D-7-6 experiment.
SCO2_CF_SCALE = 3.39
from size_sco2_703 import (DEVICES, design_device,  # noqa: E402
                                       EPS, EPS_A, D_H, A0, K_S, K0, CF0,
                                       _h as _enth, _props as _propsA)


def _grid_streamwise(L_dom, n_x, cluster_outlet=False, n_ref=10):
    dx = np.full(n_x, L_dom / n_x)
    if cluster_outlet and n_x > 2 * n_ref:
        first = 0.25 * (L_dom / n_x)
        cl = np.array([first * 1.6 ** k for k in range(n_ref)])[::-1]
        dx[-n_ref:] = cl
        dx *= L_dom / dx.sum()
    return dx


def run_device(d, n_x=240, n_y=12, max_outer=40, alpha=0.30):
    """Field-solve the hot (sCO2) side at the Method-A sized geometry.
    Returns (Q_kW, dP_hot_Pa, dP_hot_frac, conv, iters)."""
    dev = d["dev"]
    pick = d["pick"]
    if pick is None:
        return None
    Q = d["Q"]
    A_front = pick["A_front"]
    L_DOM = pick["L"]
    near_crit = dev["name"].startswith("预冷")
    A_FLOW = EPS_A * A_front
    H_DOM = A_front / 1.0     # 2D slice: treat frontal as width (height folded into A_FLOW via EPS_A)
    # use a transverse height that keeps the 2D slice well-posed; A_FLOW already
    # encodes the real void area, so H_DOM only sets the SIMPLE transverse extent.
    H_DOM = 0.05

    Ph = dev["Ph"]
    PM = Ph if not near_crit else 0.5 * (dev["Ph"] + 7.7e6)
    Th_in = dev["Th_in"]
    # hot outlet target (from duty): h_out = h_in - Q/mh
    h_out = _enth("sco2", Th_in, Ph) - Q / dev["mh"]
    Th_out = float(S.sco2_temperature(h_out, Ph))

    rho0 = S.sco2_density(Th_in, PM)
    mu0 = S.sco2_viscosity(Th_in, PM)
    cp0 = S.sco2_cp(Th_in, PM)
    u_A = dev["mh"] / (rho0 * A_FLOW)

    DX = _grid_streamwise(L_DOM, n_x, cluster_outlet=near_crit)
    DY = np.full(n_y, H_DOM / n_y)
    N_X, N_Y = n_x, n_y
    x_cen = np.cumsum(DX) - 0.5 * DX

    # cold side prescribed counterflow: warm end at hot inlet (i=0)
    Tc_in, Tc_out = dev["Tc_in"], d["Tc_out"]
    Tb_1d = Tc_out + (Tc_in - Tc_out) * (x_cen / L_DOM)
    Tb_pre = np.broadcast_to(Tb_1d[:, None], (N_X, N_Y)).copy()
    # cold-side props + Nu
    cold = dev["cold"]
    Tc_m = 0.5 * (Tc_in + Tc_out)
    rcB, muB, kB, cpB = _propsA(cold, Tc_m, dev["Pc"])
    u_B = dev["mc"] / (rcB * A_FLOW)
    Re_B = rcB * abs(u_B) * D_H / muB
    Pr_B = muB * cpB / kB
    nuB = (nu_sco2_topo("Diamond", max(Re_B, 1.0), Pr_B, 7.0, D_H * 1e3)
           if cold == "sco2"
           else nu_water_topo("Diamond", max(Re_B, 1.0), Pr_B))
    h_vB = np.full((N_X, N_Y), A0 * float(nuB) * kB / D_H)
    K_ffB = np.full((N_X, N_Y), EPS_A * kB)
    rho_cp_B = rcB * cpB
    K_ss = (1.0 - EPS) * K_S

    cF_eff = CF0 * SCO2_CF_SCALE
    G_A = dev["mh"] / A_FLOW
    C_est = mu0 * G_A / K0 + cF_eff * G_A ** 2
    P_seed = float(np.sqrt(max(Ph ** 2 - 2.0 * 188.9 * Th_in * C_est * L_DOM, 1.0e4)))

    rho_f = np.full((N_X, N_Y), rho0)
    mu_f = np.full((N_X, N_Y), mu0)
    rho_cp_A = np.full((N_X, N_Y), rho0 * cp0)
    Ta = Tb = Ts = None
    Ta_prev = None
    conv = False
    iters = 0
    s = None
    for it in range(max_outer):
        iters = it + 1
        rho_s = np.ascontiguousarray(rho_f.T)
        mu_s = np.ascontiguousarray(mu_f.T)
        T_s = np.ascontiguousarray(Ta.T) if Ta is not None else None
        s = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, "Diamond", 7.0, 0.6,
                         EPS, D_H / 2, rho_s, mu_s, Th_in, 0.0, H_DOM, u_A,
                         outlet_lo=0.0, outlet_hi=H_DOM, P_ref_abs=P_seed,
                         rho_inlet_ref=rho0, wall_refine=False,
                         cf_scale=SCO2_CF_SCALE)
        s.fluid_type = "incompressible"
        s.dx_arr, s.dy_arr = DY.copy(), DX.copy()
        if T_s is not None:
            s.update_T_field(np.ascontiguousarray(T_s, float))
        s.solve(max_iter=3000, tol=1e-4, verbose=False)
        v_cell = 0.5 * (s.v[:, :-1] + s.v[:, 1:])
        ucA = np.ascontiguousarray(v_cell.T)
        vcA = np.zeros((N_X, N_Y))

        if Ta is not None:
            kA = S.sco2_conductivity_field(Ta, PM)
            ReA = rho_f * np.abs(ucA) * D_H / np.maximum(mu_f, 1e-12)
            PrA = mu_f * (rho_cp_A / np.maximum(rho_f, 1e-9)) / np.maximum(kA, 1e-12)
            NuA = nu_sco2_topo("Diamond", np.maximum(ReA, 1.0),
                               np.maximum(PrA, 1e-3), 7.0, D_H * 1e3)
            h_vA = A0 * NuA * kA / D_H
            K_ffA = EPS_A * kA
        else:
            kA0 = S.sco2_conductivity(Th_in, PM)
            ReA0 = rho0 * abs(u_A) * D_H / mu0
            PrA0 = mu0 * cp0 / kA0
            h_vA = np.full((N_X, N_Y), A0 * float(nu_sco2_topo(
                "Diamond", ReA0, PrA0, 7.0, D_H * 1e3)) * kA0 / D_H)
            K_ffA = np.full((N_X, N_Y), EPS_A * kA0)

        Ta, Tb, Ts, _ = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y, Th_in, Tc_in,
            K_ffA, K_ffB, K_ss, h_vA, h_vB,
            rho_cp_A, rho_cp_B, EPS,
            ucA, vcA, np.zeros((N_X, N_Y)), np.zeros((N_X, N_Y)),
            dir_A=0, dir_B=1, Tb_prescribed=Tb_pre,
            tol=0.2, max_iter=8000, return_info=True,
            dx_arr=DX, dy_arr=DY, Ta_init=Ta, Tb_init=Tb, Ts_init=Ts)

        if not np.all(np.isfinite(Ta)):
            print(f"    [NaN guard] {dev['name']} — abort"); return None
        Ta = np.clip(Ta, Th_out - 10.0, Th_in + 5.0)

        rho_new = S.sco2_density_field(Ta, PM)
        mu_new = S.sco2_viscosity_field(Ta, PM)
        rho_cp_new = S.sco2_rho_cp_field(Ta, PM)
        dT = float(np.max(np.abs(Ta - Ta_prev))) if Ta_prev is not None else 1e9
        if dT < 0.05:
            conv = True
            break
        Ta_prev = Ta.copy()
        rho_f = alpha * rho_new + (1 - alpha) * rho_f
        mu_f = alpha * mu_new + (1 - alpha) * mu_f
        rho_cp_A = alpha * rho_cp_new + (1 - alpha) * rho_cp_A

    w = np.abs(ucA[-1, :]) + 1e-12
    T_A_out = float((Ta[-1, :] * w).sum() / w.sum())
    Q_sim = dev["mh"] * (_enth("sco2", Th_in, Ph) - S.sco2_enthalpy(T_A_out, Ph)) / 1e3
    dP = extract_dP_mass_flux_from_simple(s)
    return dict(Q_kW=Q_sim, dP=dP, dP_frac=dP / Ph, conv=conv, iters=iters,
                T_out=T_A_out, Q_target_kW=Q / 1e3)


def main():
    print("703 sCO2 PCHE — METHOD B (2D field-solver Δp confirm @ Method-A geometry)\n")
    print(f"{'device':>20} {'A1d dPh%':>9} {'Bfield dPh%':>11} {'Δ pts':>6} "
          f"{'Q_A MW':>7} {'Q_field MW':>10} {'it':>3} conv")
    for dev in DEVICES:
        d = design_device(dev)
        if d["pick"] is None:
            print(f"{dev['name']:>20}  (Method-A infeasible — skip)")
            continue
        r = run_device(d)
        if r is None:
            print(f"{dev['name']:>20}  field FAILED")
            continue
        a_dph = d["pick"]["dPh_frac"] * 100
        print(f"{dev['name']:>20} {a_dph:>9.2f} {r['dP_frac']*100:>11.2f} "
              f"{r['dP_frac']*100 - a_dph:>+6.2f} {d['Q']/1e6:>7.2f} "
              f"{r['Q_kW']/1e3:>10.2f} {r['iters']:>3} {r['conv']}")
    print("\n  (hot sCO2 side field-confirmed; precooler water-side Δp stays on the 1D estimate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
