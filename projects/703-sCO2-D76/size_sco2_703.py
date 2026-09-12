# -*- coding: utf-8 -*-
"""703 sCO2 PCHE — METHOD A: enthalpy-segmented ε-NTU sizing at Diamond 7/0.6.

Sizes the THREE 703 heat exchangers (main heater / recuperator / precooler) as
TPMS Diamond 7/0.6 cores. Counterflow. Variable properties carried in ENTHALPY
(CoolProp Span-Wagner), so the recuperator's mild cp drift and the precooler's
×50 pseudocritical cp spike are both handled without an ill-conditioned cp·dT.

Naming: ``A_front`` = frontal area (= L×W, the inlet face ⟂ flow); the streamwise
length is ``L`` here = the report/xlsx "depth H" (convention: 迎风面 L×W, 深度 H).
The solver's streamwise axis is fed this length regardless of the letter.

For each device and a swept frontal area A_front:
  * interstitial u = ṁ/(ρ·ε_A·A_front), mass flux G = ṁ/(ε_A·A_front);
  * local Re = G·D_h/μ → Nu (nu_sco2_topo / nu_water_topo) → h = Nu·k/D_h →
    volumetric h_v = A_0·h  [W/(m³·K)];
  * overall 1/U_v = 1/h_vH + 1/h_vC + t_wall/(k_s·A_0)  (wall conduction);
  * segment volume dV = dq/(U_v·ΔT_local), summed over the duty → V_core;
  * L = V_core/A_front; 1D Forchheimer Δp per side = Σ (μ·G/K + cF·G²)/ρ · dL.

Friction closure (the validated one): sCO2 cF = geometric cF × SCO2_CF_SCALE
(=3.39, D-7-6 field-calibrated, hold-out RMSRE 5.9 % across Re 8-40 k — see
validate_sco2_d76_dP_holdout.py). Water cF = geometric cF (gamma_df already
embeds SLM roughness). The design point = smallest-V geometry whose BINDING-side
Δp ≤ the 2 % budget (sized to ≤1.7 % to leave margin for the ~6 % cF error).

Method B (validate_sco2_703_field.py) then drives the 2D field solver at these
sized geometries to confirm the Δp independently (Phase C for the precooler).

Run:  python -u projects/703-sCO2-D76/size_sco2_703.py
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
from scipy.optimize import brentq

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from CoolProp.CoolProp import PropsSI                          # noqa: E402
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry        # noqa: E402
from sjtu_tpmshx.models.nu_correlations import nu_sco2_topo, nu_water_topo  # noqa: E402
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF  # noqa: E402
# Historical D-7-6 experimental effective-cF multiplier (retired from
# production 2026-07-15 — solver now uses the smooth-wall sCO2 CFD cF).
# Kept LOCALLY here: this script validates the ROUGH D-7-6 experiment.
SCO2_CF_SCALE = 3.39

# ── geometry: Diamond 7/0.6 (the only sCO2-calibrated lattice) ──────────
K_S, T_WALL_MM = 16.0, 0.6
T_WALL = T_WALL_MM * 1e-3
GEOM = tpms_geometry("Diamond", 7.0, 0.6, K_S)
EPS, EPS_A = GEOM["epsilon"], GEOM["epsilon_A"]
D_H, A0 = GEOM["D_h"], GEOM["A_0"]
K0, CF0 = predict_K_cF("Diamond", 7.0, 0.6, EPS_A)   # geometric (air/water-anchored)
DP_BUDGET = 0.02          # 2 % of inlet absolute pressure
DP_TARGET = 0.017         # size to 1.7 % → margin for the ~6 % cF prediction error
DT_MIN = 5.0              # minimum counterflow approach ΔT [K] (pinch guard)
N_SEG = 200               # enthalpy segments


def _props(fluid, T, P):
    """(rho, mu, k, cp) at (T,P). fluid ∈ {'sco2','water'} → CoolProp."""
    name = "CO2" if fluid == "sco2" else "Water"
    rho = PropsSI("D", "T", T, "P", P, name)
    mu = PropsSI("V", "T", T, "P", P, name)
    k = PropsSI("L", "T", T, "P", P, name)
    cp = PropsSI("C", "T", T, "P", P, name)
    return rho, mu, k, cp


def _h(fluid, T, P):
    return PropsSI("H", "T", T, "P", P, "CO2" if fluid == "sco2" else "Water")


def _T_of_h(fluid, h, P):
    return PropsSI("T", "H", h, "P", P, "CO2" if fluid == "sco2" else "Water")


def _nu(fluid, Re, Pr):
    Re = max(Re, 1.0)
    if fluid == "sco2":
        return float(nu_sco2_topo("Diamond", Re, Pr, 7.0, D_H * 1e3))
    return float(nu_water_topo("Diamond", Re, Pr))


def _cf(fluid):
    return CF0 * SCO2_CF_SCALE if fluid == "sco2" else CF0


def _profiles(dev, Q):
    """Counterflow T profiles vs cumulative duty q∈[0,Q] (q=0 at hot inlet end).
    Returns (q[N+1], Th[N+1], Tc[N+1]). min(Th-Tc) is the pinch."""
    mh, mc = dev["mh"], dev["mc"]
    Ph, Pc = dev["Ph"], dev["Pc"]
    hh_in = _h(dev["hot"], dev["Th_in"], Ph)
    # cold OUTLET enthalpy (hot-inlet end): h_c_out = h_c_in + Q/mc
    hc_in = _h(dev["cold"], dev["Tc_in"], Pc)
    hc_out = hc_in + Q / mc
    q = np.linspace(0.0, Q, N_SEG + 1)
    Th = np.array([_T_of_h(dev["hot"], hh_in - qi / mh, Ph) for qi in q])
    Tc = np.array([_T_of_h(dev["cold"], hc_out - qi / mc, Pc) for qi in q])
    return q, Th, Tc


def _derate_Q(dev):
    """Max feasible duty so the counterflow approach ΔT ≥ DT_MIN everywhere.
    Returns (Q, Tc_out, pinch). Used for the main heater (823 K target is a
    temperature crossing — see thermodynamic check)."""
    mc, Pc = dev["mc"], dev["Pc"]
    Tc_in = dev["Tc_in"]
    hc_in = _h(dev["cold"], Tc_in, Pc)
    # target duty if cold reached its spec outlet
    Q_spec = mc * (_h(dev["cold"], dev["Tc_out"], Pc) - hc_in)

    def min_dT(Q):
        _, Th, Tc = _profiles(dev, Q)
        return float(np.min(Th - Tc))

    if min_dT(Q_spec) >= DT_MIN:
        return Q_spec, dev["Tc_out"], min_dT(Q_spec)
    # bisect down to where the pinch = DT_MIN
    Q = brentq(lambda q: min_dT(q) - DT_MIN, 0.05 * Q_spec, Q_spec, xtol=1e2)
    Tc_out = _T_of_h(dev["cold"], hc_in + Q / mc, Pc)
    return Q, Tc_out, min_dT(Q)


def size_at_Afront(dev, Q, A_front):
    """Segmented ε-NTU + Forchheimer at a given frontal area. Returns dict."""
    q, Th, Tc = _profiles(dev, Q)
    dT = Th - Tc
    if np.min(dT) <= 0:
        return None
    A_flow = EPS_A * A_front
    Gh = dev["mh"] / A_flow
    Gc = dev["mc"] / A_flow
    cfh, cfc = _cf(dev["hot"]), _cf(dev["cold"])
    R_wall = T_WALL / (K_S * A0)        # volumetric wall conduction resistance

    V = 0.0
    Re_h_acc = Re_c_acc = 0.0
    # segment midpoints
    for i in range(N_SEG):
        dq = q[i + 1] - q[i]
        Thm = 0.5 * (Th[i] + Th[i + 1])
        Tcm = 0.5 * (Tc[i] + Tc[i + 1])
        dTm = 0.5 * (dT[i] + dT[i + 1])
        rh, muh, kh, cph = _props(dev["hot"], Thm, dev["Ph"])
        rc, muc, kc, cpc = _props(dev["cold"], Tcm, dev["Pc"])
        Reh, Rec = Gh * D_H / muh, Gc * D_H / muc
        Prh, Prc = muh * cph / kh, muc * cpc / kc
        hvh = A0 * _nu(dev["hot"], Reh, Prh) * kh / D_H
        hvc = A0 * _nu(dev["cold"], Rec, Prc) * kc / D_H
        Uv = 1.0 / (1.0 / hvh + 1.0 / hvc + R_wall)
        dV = dq / (Uv * dTm)
        V += dV
        Re_h_acc = max(Re_h_acc, Reh)
        Re_c_acc = max(Re_c_acc, Rec)

    L = V / A_front
    # 1D Forchheimer Δp per side (local rho,mu; G constant along the channel).
    # Second pass: each segment's length share dL = dV/A_front, re-deriving the
    # local U_v exactly as the volume pass did.
    dPh = dPc = 0.0
    for i in range(N_SEG):
        dq = q[i + 1] - q[i]
        Thm = 0.5 * (Th[i] + Th[i + 1]); Tcm = 0.5 * (Tc[i] + Tc[i + 1])
        dTm = 0.5 * (dT[i] + dT[i + 1])
        rh, muh, kh, cph = _props(dev["hot"], Thm, dev["Ph"])
        rc, muc, kc, cpc = _props(dev["cold"], Tcm, dev["Pc"])
        Reh, Rec = Gh * D_H / muh, Gc * D_H / muc
        Prh, Prc = muh * cph / kh, muc * cpc / kc
        hvh = A0 * _nu(dev["hot"], Reh, Prh) * kh / D_H
        hvc = A0 * _nu(dev["cold"], Rec, Prc) * kc / D_H
        Uv = 1.0 / (1.0 / hvh + 1.0 / hvc + R_wall)
        dL = (dq / (Uv * dTm)) / A_front
        dPh += (muh * Gh / K0 + cfh * Gh ** 2) / rh * dL
        dPc += (muc * Gc / K0 + cfc * Gc ** 2) / rc * dL
    return dict(A_front=A_front, V=V, L=L,
                dPh=dPh, dPc=dPc,
                dPh_frac=dPh / dev["Ph"], dPc_frac=dPc / dev["Pc"],
                Re_h=Re_h_acc, Re_c=Re_c_acc, Q=Q)


def design_device(dev):
    # de-rate if the spec target crosses; else use spec duty
    if dev.get("derate"):
        Q, Tc_out, pinch = _derate_Q(dev)
    else:
        Q = dev["mc"] * (_h(dev["cold"], dev["Tc_out"], dev["Pc"])
                         - _h(dev["cold"], dev["Tc_in"], dev["Pc"]))
        Tc_out, pinch = dev["Tc_out"], None

    # sweep A_front; binding-side Δp falls as A_front grows. Find the smallest
    # A_front whose BOTH-side Δp ≤ DP_TARGET (→ smallest core that fits budget).
    grid = np.linspace(0.02, 1.2, 60)
    rows = [size_at_Afront(dev, Q, a) for a in grid]
    rows = [r for r in rows if r is not None]
    feasible = [r for r in rows
                if r["dPh_frac"] <= DP_TARGET and r["dPc_frac"] <= DP_TARGET]
    pick = min(feasible, key=lambda r: r["V"]) if feasible else None
    return dict(dev=dev, Q=Q, Tc_out=Tc_out, pinch=pinch, pick=pick, rows=rows)


DEVICES = [
    dict(name="主换热器 Heater", hot="sco2", cold="sco2",
         Th_in=873.15, mh=25.0, Ph=12.7e6,
         Tc_in=654.0, Tc_out=823.15, mc=37.6, Pc=18.11e6, derate=True),
    dict(name="回热器 Recuperator", hot="sco2", cold="sco2",
         Th_in=737.0, mh=37.6, Ph=8.017e6,
         Tc_in=361.0, Tc_out=655.0, mc=37.6, Pc=18.48e6, derate=False),
    dict(name="预冷器 Precooler", hot="sco2", cold="water",
         Th_in=371.0, mh=37.6, Ph=7.857e6,
         Tc_in=297.15, Tc_out=307.15, mc=129.5, Pc=0.5e6, derate=False),
]


def main():
    print("703 sCO2 PCHE — METHOD A (enthalpy-segmented ε-NTU), Diamond 7/0.6")
    print(f"  ε={EPS:.3f} ε_A={EPS_A:.3f} D_h={D_H*1e3:.3f}mm A_0={A0:.0f} m²/m³ "
          f"K={K0:.3e} cF_geom={CF0:.1f} cF_sCO2={CF0*SCO2_CF_SCALE:.1f} (×{SCO2_CF_SCALE})")
    print(f"  budget {DP_BUDGET*100:.0f}% (sized to {DP_TARGET*100:.1f}%), pinch≥{DT_MIN:.0f}K\n")
    print(f"{'device':>20} {'Q MW':>6} {'Tc_out':>7} {'pinch':>6} "
          f"{'A_fr m²':>8} {'L m':>6} {'V m³':>7} {'dPh%':>6} {'dPc%':>6} "
          f"{'Re_h':>7} {'Re_c':>7}")
    for dev in DEVICES:
        d = design_device(dev)
        p = d["pick"]
        Tco = d["Tc_out"]
        pinch = "" if d["pinch"] is None else f"{d['pinch']:.1f}"
        if p is None:
            print(f"{dev['name']:>20} {d['Q']/1e6:>6.2f} {Tco-273.15:>6.1f}C "
                  f"{pinch:>6} {'— infeasible at any A_front ≤1.2 m² —':>50}")
            continue
        print(f"{dev['name']:>20} {d['Q']/1e6:>6.2f} {Tco-273.15:>6.1f}C {pinch:>6} "
              f"{p['A_front']:>8.3f} {p['L']:>6.3f} {p['V']:>7.4f} "
              f"{p['dPh_frac']*100:>6.2f} {p['dPc_frac']*100:>6.2f} "
              f"{p['Re_h']:>7.0f} {p['Re_c']:>7.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
