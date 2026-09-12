# -*- coding: utf-8 -*-
"""Phase C (near-critical sCO2) capability check — 703 precooler in the 2D field solver.

The 703 precooler cools sCO2 371 K -> 307.15 K at ~7.7-7.86 MPa, i.e. straight
THROUGH the pseudocritical line (Tpc(7.7 MPa) ~= 306 K): cp swings x17, rho x2.7
over the last ~5 K at the hot outlet. Phase A froze properties; Phase C refreshes
the per-cell rho*cp / mu / rho FIELDS from CoolProp every outer iteration so the
energy convection coefficient tracks the cp spike.

This driver is a CAPABILITY + CROSS-CHECK, not a validated gate:
  * there is NO TPMS near-critical experiment to validate against (D-7-6 sCO2 is
    far from critical, 199-229 C), so the field-solver duty is cross-checked
    against the segmented enthalpy eps-NTU sizing (same Nu/cF closure), not a
    measurement. Loud caveat carried.
  * hot side A = sCO2 LIVE (incompressible SIMPLE, low-Mach var-property);
  * cold side B = water, PRESCRIBED counterflow (linear Tb) — the duty is
    governed by the A-side field heat transfer, which is the Phase C question.
  * per-cell Nu (local Re/Pr through the spike), per-cell rho*cp, fine streamwise
    grid clustered at the hot-outlet (cp peak), strong under-relaxation, NaN guard.

Run:  python projects/703-sCO2-D76/validate_sco2_precooler_phasec.py
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

from CoolProp.CoolProp import PropsSI                          # noqa: E402
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry, nu_sco2_topo  # noqa: E402
from sjtu_tpmshx.models import sco2_props as S                            # noqa: E402
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver                 # noqa: E402
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain              # noqa: E402
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF  # noqa: E402
# Historical D-7-6 experimental effective-cF multiplier (retired from
# production 2026-07-15 — solver now uses the smooth-wall sCO2 CFD cF).
# Kept LOCALLY here: this script validates the ROUGH D-7-6 experiment.
SCO2_CF_SCALE = 3.39

# ── 703 precooler operating point ──────────────────────────────────────
MH = 37.6                  # hot sCO2 mass flow [kg/s]
TH_IN, TH_OUT = 371.0, 307.15
PH_IN, PH_OUT = 7.857e6, 7.7e6
PM = 0.5 * (PH_IN + PH_OUT)
MC = 129.5                 # cold water mass flow [kg/s]
TC_IN, TC_OUT = 297.15, 307.15
PC = 0.5e6

# ── geometry: Diamond 7/0.6 (validated sCO2 Nu + D-7-6 cF) ──────────────
GEOM = tpms_geometry("Diamond", 7.0, 0.6, 16.0)
EPS, EPS_A = GEOM["epsilon"], GEOM["epsilon_A"]
D_H, A0 = GEOM["D_h"], GEOM["A_0"]
K_S, T_WALL = 16.0, 0.6e-3
CF_SCO2 = predict_K_cF("Diamond", 7.0, 0.6, EPS_A)[1] * SCO2_CF_SCALE  # D-7-6 sCO2 effective

# sizing design point from the segmented enthalpy eps-NTU (hot dP<=2%)
A_FRONT = 0.40             # frontal area [m2]
L_DOM = 0.19               # core length [m]
A_FLOW = EPS_A * A_FRONT    # void frontal flow area (per stream) [m2]
H_DOM = 0.03               # nominal 2D-slice transverse height [m]


def _wprop(key, T, P):
    return PropsSI(key, "T", T, "P", P, "Water")


def _grid(n_x, n_y, n_refine=10):
    """Streamwise grid clustered toward the hot-outlet end (x=L, the cp spike).
    Geometric refinement near the LAST cells (outlet)."""
    # uniform base, then geometric clustering at the outlet (i = N-1)
    dx = np.full(n_x, L_DOM / n_x)
    # cluster: shrink the last n_refine cells, grow earlier ones to conserve length
    if n_refine > 0 and n_x > 2 * n_refine:
        first = 0.25 * (L_DOM / n_x)
        growth = 1.6
        cl = np.array([first * growth ** k for k in range(n_refine)])  # small->large
        cl = cl[::-1]                                                  # large->small toward outlet
        dx[-n_refine:] = cl
        # rescale all so sum == L_DOM
        dx *= L_DOM / dx.sum()
    dy = np.full(n_y, H_DOM / n_y)
    return dx, dy


def run(n_x=240, n_y=12, max_outer=40, alpha=0.30, verbose=False):
    DX, DY = _grid(n_x, n_y)
    N_X, N_Y = n_x, n_y
    x_edges = np.concatenate([[0.0], np.cumsum(DX)])
    x_cen = 0.5 * (x_edges[:-1] + x_edges[1:])

    # inlet (hot) reference props
    rho_A0 = S.sco2_density(TH_IN, PM)
    mu_A0 = S.sco2_viscosity(TH_IN, PM)
    cp_A0 = S.sco2_cp(TH_IN, PM)
    u_A = MH / (rho_A0 * A_FLOW)

    K_ss = (1.0 - EPS) * K_S

    # cold water B (prescribed counterflow): warm (307.15) at hot-inlet end i=0,
    # cold (297.15) at hot-outlet end i=L.
    Tb_1d = TC_OUT + (TC_IN - TC_OUT) * (x_cen / L_DOM)
    Tb_pre = np.broadcast_to(Tb_1d[:, None], (N_X, N_Y)).copy()
    rho_B = _wprop("D", 0.5 * (TC_IN + TC_OUT), PC)
    mu_B = _wprop("V", 0.5 * (TC_IN + TC_OUT), PC)
    cp_B = _wprop("C", 0.5 * (TC_IN + TC_OUT), PC)
    k_B = _wprop("L", 0.5 * (TC_IN + TC_OUT), PC)
    u_B = MC / (rho_B * A_FLOW)
    from sjtu_tpmshx.models.nu_correlations import nu_water_topo
    Re_B = rho_B * abs(u_B) * D_H / mu_B
    Pr_B = mu_B * cp_B / k_B
    Nu_B = float(nu_water_topo("Diamond", max(Re_B, 1.0), Pr_B))
    h_vB = np.full((N_X, N_Y), A0 * Nu_B * k_B / D_H)
    K_ffB = np.full((N_X, N_Y), EPS_A * k_B)
    rho_cp_B = rho_B * cp_B

    # 1D compressible seed for the inlet-pressure anchor (R_CO2 ~ 188.9)
    G_A = MH / A_FLOW
    C_est = mu_A0 * G_A / predict_K_cF("Diamond", 7.0, 0.6, EPS_A)[0] + CF_SCO2 * G_A ** 2
    P_seed = float(np.sqrt(max(PH_IN ** 2 - 2.0 * 188.9 * TH_IN * C_est * L_DOM, 1.0e4)))

    rho_f = np.full((N_X, N_Y), rho_A0)
    mu_f = np.full((N_X, N_Y), mu_A0)
    rho_cp_A = np.full((N_X, N_Y), rho_A0 * cp_A0)
    Ta = Tb = Ts = None
    Ta_prev = None
    conv = False
    iters = 0
    for it in range(max_outer):
        iters = it + 1
        rho_s = np.ascontiguousarray(rho_f.T)
        mu_s = np.ascontiguousarray(mu_f.T)
        T_s = np.ascontiguousarray(Ta.T) if Ta is not None else None
        s = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, "Diamond", 7.0, 0.6,
                         EPS, D_H / 2, rho_s, mu_s, TH_IN, 0.0, H_DOM, u_A,
                         outlet_lo=0.0, outlet_hi=H_DOM, P_ref_abs=P_seed,
                         rho_inlet_ref=rho_A0, wall_refine=False,
                         cf_scale=SCO2_CF_SCALE)
        s.fluid_type = "incompressible"
        s.dx_arr, s.dy_arr = DY.copy(), DX.copy()
        if T_s is not None:
            s.update_T_field(np.ascontiguousarray(T_s, float))
        s.solve(max_iter=3000, tol=1e-4, verbose=False)
        v_cell = 0.5 * (s.v[:, :-1] + s.v[:, 1:])
        ucA = np.ascontiguousarray(v_cell.T)
        vcA = np.zeros((N_X, N_Y))

        # per-cell Nu through the spike (local Re/Pr) -> per-cell h_vA
        if Ta is not None:
            kA = S.sco2_conductivity_field(Ta, PM)
            ReA = rho_f * np.abs(ucA) * D_H / np.maximum(mu_f, 1e-12)
            PrA = mu_f * (rho_cp_A / np.maximum(rho_f, 1e-9)) / np.maximum(kA, 1e-12)
            NuA = nu_sco2_topo("Diamond", np.maximum(ReA, 1.0),
                               np.maximum(PrA, 1e-3), 7.0, D_H * 1e3)
            h_vA = A0 * NuA * kA / D_H
            K_ffA_f = EPS_A * kA
        else:
            kA0 = S.sco2_conductivity(TH_IN, PM)
            ReA0 = rho_A0 * abs(u_A) * D_H / mu_A0
            PrA0 = mu_A0 * cp_A0 / kA0
            h_vA = np.full((N_X, N_Y), A0 * float(nu_sco2_topo(
                "Diamond", ReA0, PrA0, 7.0, D_H * 1e3)) * kA0 / D_H)
            K_ffA_f = np.full((N_X, N_Y), EPS_A * kA0)

        Ta, Tb, Ts, _ = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y, TH_IN, TC_IN,
            K_ffA_f, K_ffB, K_ss, h_vA, h_vB,
            rho_cp_A, rho_cp_B, EPS,
            ucA, vcA, np.zeros((N_X, N_Y)), np.zeros((N_X, N_Y)),
            dir_A=0, dir_B=1, Tb_prescribed=Tb_pre,
            tol=0.2, max_iter=8000, return_info=True,
            dx_arr=DX, dy_arr=DY, Ta_init=Ta, Tb_init=Tb, Ts_init=Ts)

        if not np.all(np.isfinite(Ta)):
            print("  [NaN guard] non-finite Ta — abort"); return None
        # clamp to the physical CoolProp range to keep the inversion safe
        Ta = np.clip(Ta, TH_OUT - 5.0, TH_IN + 5.0)

        rho_new = S.sco2_density_field(Ta, PM)
        mu_new = S.sco2_viscosity_field(Ta, PM)
        rho_cp_new = S.sco2_rho_cp_field(Ta, PM)
        dT = float(np.max(np.abs(Ta - Ta_prev))) if Ta_prev is not None else 1e9
        if verbose:
            w = np.abs(ucA[-1, :]) + 1e-12
            T_out = float((Ta[-1, :] * w).sum() / w.sum())
            print(f"  it{iters:2d} maxdT={dT:7.3f}  T_out={T_out-273.15:6.2f}C  "
                  f"cp_peak={rho_cp_new.max()/rho_new.min()/1e3:5.1f}")
        if dT < 0.05:
            conv = True
            break
        Ta_prev = Ta.copy()
        rho_f = alpha * rho_new + (1 - alpha) * rho_f
        mu_f = alpha * mu_new + (1 - alpha) * mu_f
        rho_cp_A = alpha * rho_cp_new + (1 - alpha) * rho_cp_A

    # enthalpy-based duty on the hot stream (mass-flux-weighted outlet T)
    w = np.abs(ucA[-1, :]) + 1e-12
    T_A_out = float((Ta[-1, :] * w).sum() / w.sum())
    Q_sim = MH * (S.sco2_enthalpy(TH_IN, PH_IN) - S.sco2_enthalpy(T_A_out, PH_OUT)) / 1e3
    return dict(N_X=N_X, N_Y=N_Y, iters=iters, conv=conv, T_out=T_A_out, Q_sim=Q_sim)


def main():
    Q_ref = MH * (S.sco2_enthalpy(TH_IN, PH_IN) - S.sco2_enthalpy(TH_OUT, PH_OUT)) / 1e3
    print(f"703 precooler Phase C field-solver check — Diamond 7/0.6, "
          f"A_front={A_FRONT} m2, L={L_DOM} m")
    print(f"  target: hot sCO2 {TH_IN:.1f}->{TH_OUT:.1f} K  Q_ref(enthalpy)={Q_ref:.0f} kW")
    print("  Tpc(7.7MPa)~306 K -> cp spike x17 at the hot outlet\n")
    print(f"{'grid':>10} {'it':>3} {'conv':>5} {'T_out C':>8} {'Q kW':>8} {'errQ%':>7}")
    last = None
    for (nx, ny) in [(160, 10), (240, 12), (360, 14)]:
        r = run(nx, ny)
        if r is None:
            print(f"{nx}x{ny:>4}  FAILED"); continue
        errQ = (r["Q_sim"] - Q_ref) / Q_ref * 100.0
        print(f"{nx:>4}x{ny:<4} {r['iters']:>3} {str(r['conv']):>5} "
              f"{r['T_out']-273.15:>8.2f} {r['Q_sim']:>8.0f} {errQ:>+7.1f}")
        last = r
    if last is not None:
        # grid convergence between the two finest
        print("\n  (cross-check vs segmented enthalpy eps-NTU sizing, NOT a measurement)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
