# -*- coding: utf-8 -*-
"""Gate A++ — sCO2 Nu closure in the 2D SIMPLE/LTNE FIELD solver vs D-7-6.

Stronger than the lumped ε-NTU gate (validate_sco2_d76.py): drives the actual
2D compressible-SIMPLE momentum + LTNE energy field solver with the sCO2
closure, on the D-7-6 GOLD cases, and compares the field-integrated (enthalpy)
duty Q to experiment. Architecture mirrors validate_shanghai_aligned.py but:

  * both streams are sCO2 (CoolProp Span-Wagner properties, P-dependent);
  * hot stream A is LIVE (incompressible SIMPLE — D-7-6 ΔP/P<2%, Phase A);
  * cold stream B is prescribed (linear Tb from measured T_in/T_out),
    arranged COUNTERFLOW (B anti-parallel to A along the streamwise axis);
  * Nu both sides = nu_sco2_topo (SCO2_NU_COEFFS, Diamond, far-from-critical).

Carries the prescribed-B caveat (same as the Shanghai paper baseline): the
cold side is frozen, so this validates the A-side field heat transfer with
the sCO2 closure, not a fully two-side-live coupled solve.

Run:  python projects/703-sCO2-D76/validate_sco2_d76_2d.py
Gate: max per-case |Q error| < 15 %.
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
import openpyxl
from openpyxl.utils import column_index_from_string as ci

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from CoolProp.CoolProp import PropsSI                         # noqa: E402
from sjtu_tpmshx.models.tpms_calc import (compute as tpms_compute, adaptive_grid,
                               nu_sco2_topo)
from sjtu_tpmshx.models import sco2_props as S                           # noqa: E402
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver                # noqa: E402
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain             # noqa: E402
from sjtu_tpmshx.solvers.df_projection import (build_master_refined_grid,  # noqa: E402
                                   extract_dP_mass_flux_from_simple)
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF  # noqa: E402
# Historical D-7-6 experimental effective-cF multiplier (retired from
# production 2026-07-15 — solver now uses the smooth-wall sCO2 CFD cF).
# Kept LOCALLY here: this script validates the ROUGH D-7-6 experiment.
SCO2_CF_SCALE = 3.39
# Module moved to validation/harness/ (c3635cd-era reorg); old path broke
# this script — the calibration driver for the production SCO2_CF_SCALE.
from sjtu_tpmshx.validation.harness._case_sets import d76_spec             # noqa: E402

XLSX = (_ROOT / "data" / "raw_data" / "D-7-6-sCO2"
        / "D-7-6实验数据-V1.xlsx")
GOLD = [15, 20, 21, 32, 37, 38]
GATE_PCT = 15.0
_MAX_COUPLING, _COUP_TOL, _DT_TOL, _ALPHA = 10, 0.01, 1.0, 0.7

SP = d76_spec()
TPMS, L_CELL, T_WALL, K_S = SP.tpms, SP.L_cell_mm, SP.t_wall_mm, SP.k_s_W_mK
EPS, EPS_A, D_H, A0 = SP.eps, SP.eps_A, SP.D_h, SP.A_0
R_H = D_H / 2
L_DOM, H_DOM, A_FLOW = SP.L_dom_m, SP.H_dom_m, SP.a_flow_m2
NXU, NYU = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)
DX, DY, N_X, N_Y = build_master_refined_grid(L_DOM, H_DOM, NXU, NYU,
                                             n_refine=8, first_cell=0.02e-3,
                                             growth=1.8)
K0, cF0 = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)


def _vprop(key, T, P):
    """Vectorised CoolProp property over a T-field at (near-constant) P."""
    return PropsSI(key, 'T', np.ascontiguousarray(T, float).ravel(),
                   'P', float(P), 'CO2').reshape(np.shape(T))


def _col(ws, L):
    return np.array([ws.cell(r, ci(L)).value for r in range(3, 54)], float)


def _run_case(m_h, Th, Ph, m_c, Tc_in, Tc_out, Pc, Qexp, dP_exp=None):
    rho_A0, mu_A0 = S.sco2_density(Th, Ph), S.sco2_viscosity(Th, Ph)
    cp_A0, k_A0 = S.sco2_cp(Th, Ph), S.sco2_conductivity(Th, Ph)
    u_A = m_h / (rho_A0 * A_FLOW)
    rA = tpms_compute(TPMS, L_CELL, T_WALL, u_A, Th, Ph, K_S, fluid_type='sco2')
    h_vA = A0 * rA['H_sf']
    K_ffA = EPS_A * k_A0

    # cold side B (prescribed), sCO2 props at its inlet
    rho_B0, mu_B0 = S.sco2_density(Tc_in, Pc), S.sco2_viscosity(Tc_in, Pc)
    cp_B0, k_B = S.sco2_cp(Tc_in, Pc), S.sco2_conductivity(Tc_in, Pc)
    u_B = m_c / (rho_B0 * A_FLOW)
    Re_B = rho_B0 * abs(u_B) * D_H / mu_B0
    Pr_B = mu_B0 * cp_B0 / k_B
    Nu_B = float(nu_sco2_topo(TPMS, max(Re_B, 1.0), Pr_B, L_CELL,
                              D_H * 1e3))
    h_vB = A0 * Nu_B * k_B / D_H
    K_ffB = EPS_A * k_B
    K_ss = (1.0 - EPS) * K_S

    # COUNTERFLOW: A flows +x (streamwise axis 0, inlet i=0, outlet i=-1);
    # B (cold) anti-parallel — inlet at A's outlet (i=-1), outlet at i=0.
    x_edges = np.concatenate([[0.0], np.cumsum(DX)])
    x_cen = 0.5 * (x_edges[:-1] + x_edges[1:])
    Tb_1d = Tc_out + (Tc_in - Tc_out) * (x_cen / L_DOM)      # warm at i=0
    Tb_pre = np.broadcast_to(Tb_1d[:, None], (N_X, N_Y)).copy()

    G_A = m_h / A_FLOW
    C_est = mu_A0 * G_A / K0 + cF0 * G_A ** 2
    P_seed = float(np.sqrt(max(Ph ** 2 - 2.0 * 188.92 * Th * C_est * L_DOM,
                               1.0e4)))   # R_CO2≈188.9 for the 1D seed

    rho_f = np.full((N_X, N_Y), rho_A0)
    mu_f = np.full((N_X, N_Y), mu_A0)
    rho_cp = rho_A0 * cp_A0
    Ta = Tb = Ts = None
    Ta_prev = None
    conv = False
    iters = 0
    for it in range(_MAX_COUPLING):
        iters = it + 1
        rho_s = np.ascontiguousarray(rho_f.T)
        mu_s = np.ascontiguousarray(mu_f.T)
        T_s = np.ascontiguousarray(Ta.T) if Ta is not None else None
        s = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                         EPS, R_H, rho_s, mu_s, Th, 0.0, H_DOM, u_A,
                         outlet_lo=0.0, outlet_hi=H_DOM, P_ref_abs=P_seed,
                         rho_inlet_ref=rho_A0, wall_refine=False,
                         cf_scale=SCO2_CF_SCALE)   # D-7-6 sCO2 effective cF
        s.fluid_type = 'incompressible'      # Phase A: sCO2 incompressible
        s.dx_arr, s.dy_arr = DY.copy(), DX.copy()
        if T_s is not None:
            s.update_T_field(np.ascontiguousarray(T_s, float))
        s.solve(max_iter=3000, tol=1e-4, verbose=False)
        v_cell = 0.5 * (s.v[:, :-1] + s.v[:, 1:])
        ucA = np.ascontiguousarray(v_cell.T)
        vcA = np.zeros((N_X, N_Y))

        Ta, Tb, Ts, _ = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y, Th, Tc_in,
            K_ffA, K_ffB, K_ss, h_vA, h_vB,
            rho_cp, rho_B0 * cp_B0, EPS,
            ucA, vcA, np.zeros((N_X, N_Y)), np.zeros((N_X, N_Y)),
            dir_A=0, dir_B=1, Tb_prescribed=Tb_pre,
            tol=0.5, max_iter=5000, return_info=True,
            dx_arr=DX, dy_arr=DY, Ta_init=Ta, Tb_init=Tb, Ts_init=Ts)

        rho_new = _vprop('D', Ta, Ph)
        mu_new = _vprop('V', Ta, Ph)
        rho_cp_new = rho_new * _vprop('C', Ta, Ph)
        dT = float(np.max(np.abs(Ta - Ta_prev))) if Ta_prev is not None else 1e9
        if dT < _DT_TOL:
            conv = True
            break
        Ta_prev = Ta.copy()
        rho_f = _ALPHA * rho_new + (1 - _ALPHA) * rho_f
        mu_f = _ALPHA * mu_new + (1 - _ALPHA) * mu_f
        rho_cp = (rho_cp_new if np.ndim(rho_cp) == 0
                  else _ALPHA * rho_cp_new + (1 - _ALPHA) * rho_cp)

    # enthalpy-based duty on the hot stream (mass-flux-weighted outlet T)
    w = np.abs(ucA[-1, :]) + 1e-12
    T_A_out = float((Ta[-1, :] * w).sum() / w.sum())
    Q_sim = m_h * (S.sco2_enthalpy(Th, Ph) - S.sco2_enthalpy(T_A_out, Ph)) / 1e3
    err = (Q_sim - Qexp) / Qexp * 100.0
    # field Δp on the hot stream (cf_scale=SCO2_CF_SCALE already applied)
    dP_sim = extract_dP_mass_flux_from_simple(s)          # Pa
    err_dP = ((dP_sim - dP_exp) / dP_exp * 100.0
              if dP_exp not in (None, 0.0) else float('nan'))
    return dict(Re_h=rA['Re'], T_out=T_A_out, Q_sim=Q_sim, Qexp=Qexp,
                err=err, iters=iters, conv=conv,
                dP_sim=dP_sim, dP_exp=dP_exp, err_dP=err_dP)


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb.active
    case = _col(ws, 'B')
    mh, ThI, PhI = _col(ws, 'G'), _col(ws, 'H'), _col(ws, 'I')
    mc, McI = _col(ws, 'L'), _col(ws, 'M')
    TcO, Pc = _col(ws, 'O'), _col(ws, 'P')
    Qexp = _col(ws, 'S')
    dPhot = _col(ws, 'T')                                  # hot Δp [MPa] (in-out)
    print(f"sCO2 D-7-6 Gate A++ (2D SIMPLE/LTNE field) — Diamond {L_CELL}/{T_WALL}, "
          f"L={L_DOM*1000:.0f}mm grid {N_X}x{N_Y}  (cf_scale={SCO2_CF_SCALE})")
    print(f"{'case':>4} {'Re_h':>7} {'T_out':>7} {'Q_exp':>7} {'Q_sim':>7} "
          f"{'errQ%':>6} {'dPexp':>6} {'dPsim':>6} {'edP%':>6} {'it':>3} conv")
    errs = []
    edPs = []
    for cidx in GOLD:
        i = int(np.where(case == cidx)[0][0])
        r = _run_case(mh[i], ThI[i] + 273.15, PhI[i] * 1e6,
                      mc[i], McI[i] + 273.15, TcO[i] + 273.15, Pc[i] * 1e6,
                      Qexp[i], dP_exp=dPhot[i] * 1e6)
        errs.append(r['err'])
        edPs.append(r['err_dP'])
        print(f"{cidx:>4} {r['Re_h']:>7.0f} {r['T_out']-273.15:>7.1f} "
              f"{r['Qexp']:>7.2f} {r['Q_sim']:>7.2f} {r['err']:>+6.1f} "
              f"{r['dP_exp']/1e3:>5.1f}k {r['dP_sim']/1e3:>5.1f}k {r['err_dP']:>+6.1f} "
              f"{r['iters']:>3} {r['conv']}")
    errs = np.array(errs)
    edPs = np.array(edPs)
    rmsre = float(np.sqrt(np.mean(errs ** 2)))
    mx = float(np.max(np.abs(errs)))
    rmsre_dP = float(np.sqrt(np.mean(edPs ** 2)))
    mx_dP = float(np.max(np.abs(edPs)))
    print(f"\nQ : RMSRE = {rmsre:.1f}%  max|err| = {mx:.1f}%  bias = {np.mean(errs):+.1f}%")
    print(f"Δp: RMSRE = {rmsre_dP:.1f}%  max|err| = {mx_dP:.1f}%  bias = {np.mean(edPs):+.1f}%"
          f"   (cf_scale={SCO2_CF_SCALE} = D-7-6 sCO2 effective)")
    ok = mx < GATE_PCT and mx_dP < GATE_PCT
    print(f"GATE A++ ({GATE_PCT:.0f}% max, Q & Δp): {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
