# -*- coding: utf-8 -*-
"""B — sCO2 Δp INDEPENDENT-PREDICTION (hold-out) validation, D-7-6.

Gate A++ (validate_sco2_d76_2d.py) reports Δp bias ≈ 0 % — but ``SCO2_CF_SCALE``
(3.39) was CALIBRATED on those same 6 GOLD cases, so a centred bias is *forced*,
not *predicted*. That gate is a calibration self-consistency check, not evidence
of predictive power.

This script breaks the circularity. It runs the SAME 2D SIMPLE/LTNE field
driver (imported verbatim from the gate) on ALL 51 D-7-6 cases with
``cf_scale`` HELD FIXED at ``SCO2_CF_SCALE`` (no per-set re-tuning), then reports
the held-out (non-GOLD, 45 cases) Δp error SEPARATELY from the calibration
(GOLD, 6) set:

  * if held-out RMSRE ≈ GOLD RMSRE, the single multiplier GENERALISES across the
    measured Re ≈ 8–40 k envelope at this geometry → the Δp claim upgrades from
    "self-consistent" to "predictive within Diamond 7/0.6";
  * a Δp-error-vs-Re correlation near zero confirms the constant carries no
    residual Re trend (i.e. one scalar, not a hidden Re fit).

⚠ SCOPE: same geometry only (Diamond 7/0.6). Transfer of 3.39 to OTHER (L, t)
remains UNVERIFIED — there is no second sCO2 Δp dataset. This validates Re
transfer, not geometry transfer.

Run:  python -u projects/703-sCO2-D76/validate_sco2_d76_dP_holdout.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import openpyxl

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Reuse the gate's field driver + constants verbatim — no duplicated physics.
from validate_sco2_d76_2d import (_run_case, _col, GOLD, XLSX,  # noqa: E402
                                             N_X, N_Y, L_CELL, T_WALL, L_DOM)
# Historical D-7-6 experimental effective-cF multiplier (retired from
# production 2026-07-15 — solver now uses the smooth-wall sCO2 CFD cF).
# Kept LOCALLY here: this script validates the ROUGH D-7-6 experiment.
SCO2_CF_SCALE = 3.39


def _summary(tag, errs):
    errs = np.asarray(errs, float)
    rmsre = float(np.sqrt(np.mean(errs ** 2)))
    return dict(tag=tag, n=errs.size, rmsre=rmsre,
                mx=float(np.max(np.abs(errs))), bias=float(np.mean(errs)))


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb.active
    case = _col(ws, "B")
    mh, ThI, PhI = _col(ws, "G"), _col(ws, "H"), _col(ws, "I")
    mc, McI = _col(ws, "L"), _col(ws, "M")
    TcO, Pc = _col(ws, "O"), _col(ws, "P")
    Qexp = _col(ws, "S")
    dPhot = _col(ws, "T")                                   # hot Δp [MPa]

    print(f"sCO2 D-7-6 Δp HOLD-OUT — Diamond {L_CELL}/{T_WALL}, L={L_DOM*1000:.0f}mm "
          f"grid {N_X}x{N_Y}  (cf_scale={SCO2_CF_SCALE} FIXED, no re-tune)")
    print(f"  GOLD (calibration) = {sorted(GOLD)};  held-out = the other 45 cases\n")
    print(f"{'case':>4} {'set':>4} {'Re_h':>7} {'dPexp':>7} {'dPsim':>7} "
          f"{'errQ%':>6} {'edP%':>6} conv")

    rows = []
    for i in range(len(case)):
        cid = int(case[i])
        if not (np.isfinite(dPhot[i]) and dPhot[i] > 0 and np.isfinite(Qexp[i])):
            continue
        r = _run_case(mh[i], ThI[i] + 273.15, PhI[i] * 1e6,
                      mc[i], McI[i] + 273.15, TcO[i] + 273.15, Pc[i] * 1e6,
                      Qexp[i], dP_exp=dPhot[i] * 1e6)
        in_gold = cid in GOLD
        rows.append((cid, in_gold, r["Re_h"], r["err"], r["err_dP"], r["conv"]))
        print(f"{cid:>4} {'GOLD' if in_gold else 'HOLD':>4} {r['Re_h']:>7.0f} "
              f"{dPhot[i]*1e3:>6.1f}k {r['dP_sim']/1e3:>6.1f}k "
              f"{r['err']:>+6.1f} {r['err_dP']:>+6.1f} {r['conv']}")

    gold_dP = [r[4] for r in rows if r[1]]
    hold_dP = [r[4] for r in rows if not r[1]]
    all_dP = [r[4] for r in rows]
    re_all = np.array([r[2] for r in rows], float)
    edp_all = np.array([r[4] for r in rows], float)

    print("\n── Δp error summary ──")
    for s in (_summary("GOLD(calib)", gold_dP),
              _summary("HOLD-OUT", hold_dP),
              _summary("ALL-51", all_dP)):
        print(f"  {s['tag']:>12}  n={s['n']:>2}  RMSRE={s['rmsre']:>5.1f}%  "
              f"max={s['mx']:>5.1f}%  bias={s['bias']:>+5.1f}%")

    # Re-trend of the Δp error — near-zero slope/corr ⇒ no hidden Re fit.
    if re_all.size > 2 and np.ptp(re_all) > 0:
        corr = float(np.corrcoef(re_all, edp_all)[0, 1])
        slope = float(np.polyfit(re_all, edp_all, 1)[0])     # %-err per unit Re
        print(f"\n  Δp-err vs Re_h:  corr = {corr:+.3f}   slope = {slope*1e3:+.3f} %/kRe")
        print("  (|corr| small ⇒ the single 3.39 carries no residual Re trend)")

    # Verdict: held-out should track the calibration set, both well inside 15%.
    h = _summary("HOLD-OUT", hold_dP)
    g = _summary("GOLD", gold_dP)
    ok = h["rmsre"] < 15.0 and h["mx"] < 20.0
    drift = h["rmsre"] - g["rmsre"]
    print(f"\n  held-out RMSRE − GOLD RMSRE = {drift:+.1f} pts "
          f"({'tracks calibration' if abs(drift) < 5 else 'DIVERGES — investigate'})")
    print(f"HOLD-OUT PREDICTION: {'PASS' if ok else 'FAIL'} "
          f"(held-out RMSRE<15%, max<20%)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
