"""validate_shanghai_lumped_dual_nu.py — Shanghai 16-case dual-Nu ε-NTU.

Forward prediction of Q from inlet conditions only — no T_Aout / T_Bout
leak. Uses both air-side (Nu v4.1 + ×1.28) and water-side
(`nu_water_topo` per-topology fit) correlations to build a two-sided UA,
then standard ε-NTU.

Pipeline
--------
1. Inlet props per side — ρ, μ, k, cp, Pr at T_in (then iterate with T_avg).
2. Re_A = ρ_A·u_A·D_h/μ_A;  Re_B = ρ_B·u_B·D_h/μ_B  (single-stream).
3. Nu_A = nu_from_Re(Gyroid, Re_A, ε_A, L, D_h_mm)        [v4.1 ×1.28].
   Nu_B = nu_water_topo('Gyroid', Re_B, Pr_B) = c·Re^a·Pr^(1/3), using current WATER_NU_COEFFS.
4. h_A = Nu_A·k_A/D_h;   h_B = Nu_B·k_B/D_h.
5. UA = 1 / [1/(A_tot·h_A) + t_wall/(k_steel·A_tot) + 1/(A_tot·h_B)].
6. C_A = m_air·cp_A;  C_B = m_water·cp_B;  C_min, C_max, Cr = C_min/C_max.
7. NTU = UA / C_min.
8. Cross-flow both unmixed (primary, Shanghai air⊥water):
       ε = 1 - exp((1/Cr)·NTU^0.22·(exp(-Cr·NTU^0.78) - 1))
   Counter-flow (sensitivity check) ε-NTU:
       Cr<0.999: ε = [1 - exp(-NTU(1-Cr))] / [1 - Cr·exp(-NTU(1-Cr))]
       Cr≈1   : ε = NTU/(1+NTU)
9. Q_pred = ε · C_min · (T_Ain - T_Bin).
10. T_Aout_pred / T_Bout_pred from energy balance (post-hoc).

Inputs used: m_air, m_water, T_Ain, T_Bin, P_Ain, geometry — only.
NOT used: T_Aout_exp, T_Bout_exp.

Reference Q
-----------
Compare Q_pred against three exp references:
- Q_air_exp   = m_air·cp_A·(T_Ain - T_Aout_exp)
- Q_water_exp = m_water·cp_B·(T_Bout - T_Bin)_exp
- Q_avg_exp   = 0.5·(Q_air_exp + Q_water_exp)

Outputs:
- shanghai_lumped_dual_nu.csv + provenance in a new .cache/validation/ directory
  (or the explicit --out-dir)
- console table per case + summary RMSRE / bias / max|err|
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.harness._provenance import (
    output_directory, write_csv_with_provenance,
)
from sjtu_tpmshx.models.tpms_calc import (
    geometry as tpms_geometry, nu_from_Re, nu_water_topo,
    air_density, air_viscosity, air_conductivity, air_cp,
    water_density, water_viscosity, water_conductivity, water_cp,
    P_atm,
)

# ─── Geometry (Shanghai cross-flow HX) ───────────────────────────
# Canonical params from configs/shanghai_baseline.json (Item 3 / AR8, 2026-05-28).
# Air flows along x (full-width inlet on yz face), water flows along y
# (cross-flow, narrow 42×42 port). Internal interstitial flow areas
# differ between streams since flow direction differs.
from sjtu_tpmshx.configs import load_shanghai_baseline
from sjtu_tpmshx.domain.compute_config import ComputeConfig
# Audit C3 (2026-05-28): sourced through ComputeConfig.
_SH = load_shanghai_baseline()
_SH_CC = ComputeConfig.from_dict(_SH)
TPMS = _SH_CC.geometry.tpms
L_CELL = _SH_CC.geometry.L_cell_mm                 # mm
T_WALL = _SH_CC.geometry.t_wall_mm                 # mm
K_STEEL = _SH_CC.geometry.k_s_W_mK                 # W/(m·K), 304 SS
L_AIR   = _SH_CC.geometry.L_dom_m                  # m, x  (air flow length)
L_WATER = _SH_CC.geometry.H_dom_m                  # m, y  (water flow length)
L_Z     = _SH_CC.geometry.Lz_m                     # m, z  (spanwise)


def epsilon_counterflow(NTU: float, Cr: float) -> float:
    """Counter-flow ε-NTU formula. Cr = C_min/C_max ∈ [0,1]."""
    if Cr < 0.999:
        e = np.exp(-NTU * (1.0 - Cr))
        return (1.0 - e) / (1.0 - Cr * e)
    return NTU / (1.0 + NTU)


def epsilon_crossflow_unmixed(NTU: float, Cr: float) -> float:
    """Cross-flow both unmixed (Kays & London, approximate)."""
    if NTU <= 0.0:
        return 0.0
    if Cr < 1e-6:
        return 1.0 - np.exp(-NTU)
    return 1.0 - np.exp((1.0 / Cr) * NTU**0.22
                        * (np.exp(-Cr * NTU**0.78) - 1.0))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir')
    args = parser.parse_args(argv)
    try:
        out_dir = output_directory('shanghai-lumped-dual-nu', args.out_dir)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_STEEL)
    EPS = float(g['epsilon'])
    EPS_A = float(g['epsilon_A'])
    EPS_B = float(g['epsilon_B'])
    D_H = float(g['D_h'])
    A_0 = float(g['A_0'])
    V_HX_TOTAL = L_AIR * L_WATER * L_Z
    A_TOT_GEOM = A_0 * V_HX_TOTAL  # full-volume heat transfer surface

    # ── Re convention (lumped, Yan [6] / engineering standard) ──
    # Lumped Re uses INLET-face interstitial cross-section. Internal flow
    # geometry is 3D and ambiguous (water diffuses from 42×42 manifold to
    # full 182×42 xz inside HX, then contracts back at outlet). Yan [6]
    # was fitted with inlet Re as the single-value Re label, with the
    # resulting Nu absorbing all spatial variation. Use the same convention
    # here for consistency.
    #
    #   air inlet face   (yz plane, perp to x) = L_water · L_z = 42×42 mm²
    #     A_flow_air     = ε_A · 42×42 = 650 mm² (interstitial through gyroid
    #                                              at HX entry)
    #   water inlet face (narrow 42×42 manifold port, perp to y direction)
    #     A_flow_water   = ε_B · 42×42 = 650 mm² (interstitial through gyroid
    #                                              at the manifold-HX boundary)
    A_FLOW_AIR   = EPS_A * L_WATER * L_Z
    A_FLOW_WATER = EPS_B * L_WATER * L_Z

    # ── Heat transfer surface (sheet HX topology) ──
    # Inside HX, every gyroid wall has air on one side and water on the
    # other, throughout the full 182×42×42 mm³ volume. So the full gyroid
    # surface area participates in heat transfer, regardless of the inlet
    # manifold shape.
    A_TOT = A_TOT_GEOM   # = A_0 · V_HX_total

    print("Shanghai lumped dual-Nu ε-NTU (cross-flow geometry)")
    print(f"  Geom: {TPMS} L_cell={L_CELL}mm t={T_WALL}mm  ε={EPS:.4f}  "
          f"ε_A={EPS_A:.4f}  ε_B={EPS_B:.4f}  D_h={D_H*1000:.3f}mm")
    print(f"  HX dims: L_air={L_AIR*1000:.0f}×L_water={L_WATER*1000:.0f}"
          f"×L_z={L_Z*1000:.0f} mm")
    print("  Re convention: inlet 42×42 manifold")
    print(f"  A_flow_air  ={A_FLOW_AIR*1e6:7.2f} mm² (yz · ε_A)")
    print(f"  A_flow_water={A_FLOW_WATER*1e6:7.2f} mm² (xz inlet · ε_B)")
    print(f"  A_0={A_0:.1f} 1/m  V_HX_total={V_HX_TOTAL*1e6:.1f}cm³  "
          f"A_tot={A_TOT:.4f}m² (full sheet HX gyroid wall)")
    print("  Air Nu: nu_from_Re (Gyroid v4.1 ×1.28 roughness)")
    from sjtu_tpmshx.models.nu_correlations import WATER_NU_COEFFS
    water_fit = WATER_NU_COEFFS[TPMS]
    print(f"  Water Nu: nu_water_topo({TPMS})  "
          f"Nu = {water_fit['c']}·Re^{water_fit['a']}·Pr^(1/3)\n")

    from sjtu_tpmshx.validation.harness._harness import load_cases_df
    from sjtu_tpmshx.validation.harness._case_sets import SHANGHAI_XLSX
    df = load_cases_df(SHANGHAI_XLSX)

    rows = []
    print(f"{'C':>2} {'Re_A':>5} {'Re_B':>5} {'Nu_A':>5} {'Nu_B':>5} "
          f"{'h_A':>5} {'h_B':>6} {'UA':>5} {'NTU':>5} {'Cr':>5} "
          f"{'ε_cf':>5} {'Q_p':>6} {'Qair':>6} {'Qwat':>6} "
          f"{'eA%':>6} {'eW%':>6}")
    print('─' * 110)

    for ci in range(16):
        m_air = float(df.iloc[ci, 5])
        T_Ain  = float(df.iloc[ci, 28]) + 273.15
        T_Aout_exp = float(df.iloc[ci, 29]) + 273.15
        P_Ain  = P_atm + float(df.iloc[ci, 30])
        T_Bin  = float(df.iloc[ci, 24]) + 273.15
        T_Bout_exp = float(df.iloc[ci, 25]) + 273.15
        m_water = float(df.iloc[ci, 7])

        # ── Air-side props at T_Ain (inlet only — no leak, no iter) ──
        rho_A = air_density(T_Ain, P_Ain)
        mu_A  = air_viscosity(T_Ain)
        k_A   = air_conductivity(T_Ain)
        cp_A  = air_cp(T_Ain)
        u_A   = m_air / (rho_A * A_FLOW_AIR)
        Re_A  = rho_A * u_A * D_H / mu_A
        Nu_A  = nu_from_Re(TPMS, Re_A, EPS_A, L_CELL, D_H * 1000.0)
        h_A   = Nu_A * k_A / D_H

        # ── Water-side iterates on T_avg_B ──
        T_Bout_pred = T_Bin   # init
        n_iter = 0
        for n_iter in range(1, 51):
            T_avg_B = 0.5 * (T_Bin + T_Bout_pred)
            rho_B = water_density(T_avg_B)
            mu_B  = water_viscosity(T_avg_B)
            k_B   = water_conductivity(T_avg_B)
            cp_B  = water_cp(T_avg_B)
            Pr_B  = mu_B * cp_B / k_B
            u_B   = m_water / (rho_B * A_FLOW_WATER)
            Re_B  = rho_B * u_B * D_H / mu_B
            Nu_B  = float(nu_water_topo('Gyroid', max(Re_B, 1.0), Pr_B))
            h_B   = Nu_B * k_B / D_H

            R_A = 1.0 / (h_A * A_TOT)
            R_B = 1.0 / (h_B * A_TOT)
            R_wall = (T_WALL * 1e-3) / (K_STEEL * A_TOT)
            UA = 1.0 / (R_A + R_wall + R_B)

            C_A = m_air   * cp_A
            C_B = m_water * cp_B
            C_min = min(C_A, C_B)
            C_max = max(C_A, C_B)
            Cr = C_min / C_max
            NTU = UA / C_min
            # Cross-flow primary (Shanghai geometry: air ⊥ water)
            eps_xf = epsilon_crossflow_unmixed(NTU, Cr)
            Q_pred_xf = eps_xf * C_min * (T_Ain - T_Bin)

            T_Bout_new = T_Bin + Q_pred_xf / (m_water * cp_B)
            if abs(T_Bout_new - T_Bout_pred) < 0.01:
                T_Bout_pred = T_Bout_new
                break
            T_Bout_pred = T_Bout_new

        # ── Counter-flow ε from converged NTU/Cr (sensitivity check) ──
        eps_cf = epsilon_counterflow(NTU, Cr)
        Q_pred_cf = eps_cf * C_min * (T_Ain - T_Bin)

        # ── Reference Q from experiment (independent enthalpy) ──
        Q_air_exp   = m_air   * cp_A * (T_Ain - T_Aout_exp)
        Q_water_exp = m_water * cp_B * (T_Bout_exp - T_Bin)
        Q_avg_exp   = 0.5 * (Q_air_exp + Q_water_exp)

        err_air_cf   = (Q_pred_cf - Q_air_exp)   / Q_air_exp   * 100.0
        err_water_cf = (Q_pred_cf - Q_water_exp) / Q_water_exp * 100.0
        err_avg_cf   = (Q_pred_cf - Q_avg_exp)   / Q_avg_exp   * 100.0
        err_air_xf   = (Q_pred_xf - Q_air_exp)   / Q_air_exp   * 100.0
        err_water_xf = (Q_pred_xf - Q_water_exp) / Q_water_exp * 100.0
        err_avg_xf   = (Q_pred_xf - Q_avg_exp)   / Q_avg_exp   * 100.0

        rows.append(dict(
            case=ci + 1,
            m_air=m_air, m_water=m_water,
            T_Ain=T_Ain, T_Bin=T_Bin,
            T_Bout_pred=T_Bout_pred, T_Bout_exp=T_Bout_exp,
            n_iter_water=n_iter,
            Re_A=Re_A, Nu_A=Nu_A, h_A=h_A,
            Re_B=Re_B, Pr_B=Pr_B, Nu_B=Nu_B, h_B=h_B,
            UA=UA, NTU=NTU, Cr=Cr,
            eps_cf=eps_cf, eps_xf=eps_xf,
            Q_pred_cf=Q_pred_cf, Q_pred_xf=Q_pred_xf,
            Q_air_exp=Q_air_exp, Q_water_exp=Q_water_exp, Q_avg_exp=Q_avg_exp,
            err_air_cf=err_air_cf, err_water_cf=err_water_cf,
            err_avg_cf=err_avg_cf,
            err_air_xf=err_air_xf, err_water_xf=err_water_xf,
            err_avg_xf=err_avg_xf,
        ))
        print(f"{ci+1:2d} {Re_A:5.0f} {Re_B:5.0f} {Nu_A:5.1f} {Nu_B:5.1f} "
              f"{h_A:5.0f} {h_B:6.0f} {UA:5.1f} {NTU:5.2f} {Cr:5.2f} "
              f"{eps_xf:5.3f} {Q_pred_xf:6.0f} {Q_air_exp:6.0f} {Q_water_exp:6.0f} "
              f"{err_air_xf:+6.2f} {err_water_xf:+6.2f} it={n_iter}")

    out = pd.DataFrame(rows)
    csv_path = out_dir / 'shanghai_lumped_dual_nu.csv'
    write_csv_with_provenance(out, csv_path, __file__)

    # err_stats_pct: shared helper (validation/_metrics.py, L5 fix 2026-05-28)
    from sjtu_tpmshx.validation.harness._metrics import err_stats_pct as stats

    print('\n' + '═' * 70)
    print(f"{'Reference':>16}  {'RMSRE':>8}  {'bias':>8}  {'max|err|':>8}")
    print('─' * 70)
    for label, key in [
        ('cross-flow (primary, Shanghai air⊥water)',  'xf'),
        ('counter-flow (sensitivity check)',          'cf'),
    ]:
        print(f"  [{label}]")
        for ref in ['air', 'water', 'avg']:
            r, b, m = stats(out[f'err_{ref}_{key}'].to_numpy())
            print(f"    vs Q_{ref:<6}    {r:7.2f}%  {b:+7.2f}%  {m:7.2f}%")

    print(f"\nSaved: {csv_path}")


if __name__ == '__main__':
    main()
