# -*- coding: utf-8 -*-
"""703 precooler — METHOD ii : near-critical / low-Re Nu sensitivity + literature cross-check.

The precooler's heat-transfer closure is the weakest link (see report caveat 2):
  * nu_sco2_topo = 0.28·Re^0.75·Pr^(1/3) is the FAR-from-critical D-7-6 fit;
  * the precooler crosses the pseudocritical line (cp×56 at Tpc≈306 K);
  * the duty-closed geometry (A≈2.0 m²) drops sCO2 Re to ~6-7 k, BELOW the D-7-6
    window (8-40 k) → low-Re extrapolation on top.

There is NO TPMS near-critical experiment, so this CANNOT validate — it can only
(1) cross-check the topo extrapolation against published near-critical sCO2
COOLING correlations and (2) bracket the sizing impact. Literature points:
  * Gnielinski (bulk properties) — the canonical turbulent-tube baseline;
  * Pitla et al. (2002, IJR) — Nu = ½(Nu_wall+Nu_bulk)·(k_wall/k_bulk), each
    Gnielinski at wall/bulk props; the standard sCO2-cooling property treatment.
Both are TUBE correlations → a TPMS geometry factor is unknown; they bound the
*property-variation* effect, not the absolute TPMS Nu.

Run:  python -u projects/703-sCO2-D76/precooler_nu_sensitivity.py
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

from CoolProp.CoolProp import PropsSI as P                     # noqa: E402
from sjtu_tpmshx.models.tpms_calc import geometry as _geom               # noqa: E402
from sjtu_tpmshx.models.nu_correlations import nu_sco2_topo               # noqa: E402

G_ = _geom("Diamond", 7.0, 0.6, 16.0)
EPS_A, D_H = G_["epsilon_A"], G_["D_h"]
PH = 7.7e6                       # near-critical pressure (hot outlet end)
A_FRONT = 2.0                    # duty-closed geometry
MH = 37.6
G_MASS = MH / (EPS_A * A_FRONT)  # sCO2 mass flux [kg/m²s]


def _props(T, p=PH):
    rho = P("D", "T", T, "P", p, "CO2")
    mu = P("V", "T", T, "P", p, "CO2")
    k = P("L", "T", T, "P", p, "CO2")
    cp = P("C", "T", T, "P", p, "CO2")
    return rho, mu, k, cp


def gnielinski(Re, Pr):
    if Re < 2300:
        return 4.36                       # laminar const-q floor
    f = (0.790 * np.log(Re) - 1.64) ** -2
    return (f / 8) * (Re - 1000) * Pr / (1 + 12.7 * (f / 8) ** 0.5 * (Pr ** (2 / 3) - 1))


def pitla(T_b, T_w, p=PH):
    """Pitla 2002: Nu = ½(Nu_w+Nu_b)·(k_w/k_b), Gnielinski at wall & bulk."""
    rb, mub, kb, cpb = _props(T_b, p)
    rw, muw, kw, cpw = _props(T_w, p)
    Reb = G_MASS * D_H / mub
    Rew = G_MASS * D_H / muw
    Prb = mub * cpb / kb
    Prw = muw * cpw / kw
    Nub = gnielinski(Reb, Prb)
    Nuw = gnielinski(Rew, Prw)
    return 0.5 * (Nub + Nuw) * (kw / kb), Reb, Prb


def main():
    print(f"703 precooler Nu cross-check — Diamond 7/0.6, P={PH/1e6:.2f}MPa, "
          f"A_front={A_FRONT} m² (G={G_MASS:.1f} kg/m²s)")
    print("  Tpc(7.7MPa)≈306 K.  Wall T (cooling) estimated as bulk − 0.5·(bulk − T_water_local).\n")
    # representative bulk states from hot-inlet (371) down through the spike (308)
    # local water T rises 297→307 counterflow; approximate T_water at each bulk
    states = [(371.0, 306.0), (340.0, 304.0), (320.0, 301.0),
              (312.0, 299.5), (308.0, 298.5)]
    print(f"{'T_b K':>6} {'T_w K':>6} {'Re':>7} {'Pr':>7} {'cp kJ':>6} "
          f"{'Nu_topo':>8} {'Nu_Gniel':>9} {'Nu_Pitla':>9} {'topo/Pitla':>10}")
    for T_b, T_water in states:
        rb, mub, kb, cpb = _props(T_b)
        Reb = G_MASS * D_H / mub
        Prb = mub * cpb / kb
        T_w = T_b - 0.5 * (T_b - T_water)         # wall midway (cooling)
        Nu_topo = float(nu_sco2_topo("Diamond", max(Reb, 1.0), Prb,
                                     7.0, D_H * 1e3))
        Nu_gn = gnielinski(Reb, Prb)
        Nu_pit, _, _ = pitla(T_b, T_w)
        print(f"{T_b:>6.0f} {T_w:>6.1f} {Reb:>7.0f} {Prb:>7.2f} {cpb/1e3:>6.1f} "
              f"{Nu_topo:>8.1f} {Nu_gn:>9.1f} {Nu_pit:>9.1f} {Nu_topo/Nu_pit:>10.2f}")
    print("\n  ⚠ READ CAREFULLY — the absolute topo-vs-tube ratio (5-8×) is GEOMETRY-")
    print("  CONFOUNDED: nu_sco2_topo is TPMS (high A_0, tortuous mixing) and tube")
    print("  Gnielinski/Pitla are a different geometry, so the tube correlations CANNOT")
    print("  serve as an absolute baseline for topo. Two real signals remain:")
    print("   (1) Pitla peaks near Tpc (T_b≈312K, Nu_Pitla→90) — a near-critical Nu")
    print("       ENHANCEMENT that topo's monotone Pr^(1/3) under-resolves in FORM;")
    print("   (2) topo's absolute level is independently suspect (D-7-6 construction-")
    print("       wall-temp reduction artifact, Nu∝1/ΔT) → it may run OPTIMISTIC.")
    print("  Net: the precooler Nu is uncertain in BOTH form and level; no TPMS near-")
    print("  critical data resolves it. Sizing bracket: required core volume scales")
    print("  ~1/Nu, so if topo is optimistic the precooler grows beyond the 2× already")
    print("  found; water-side dP (the binding constraint) only IMPROVES with more")
    print("  frontal → FEASIBILITY is robust, SIZE is the uncertain quantity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
