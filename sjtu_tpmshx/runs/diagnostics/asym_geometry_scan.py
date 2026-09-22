"""
Phase 0 驱动：扫偏移 δ，量 ε_A/ε_B/A0/D_h/t/连通性，出 CSV + 闸门判定。

纯几何，无 CFD。用法：python -m sjtu_tpmshx.runs.diagnostics.asym_geometry_scan
计划：vault/reports/engineering/2026-06-05-asym-porosity-phase0-PLAN-CN.md
"""
import csv
from pathlib import Path

import numpy as np

from sjtu_tpmshx.models.tpms_geometry import _phi_grid, _C_from_tL, compute_geometry
from sjtu_tpmshx.models.asym_geometry import (
    eps_sides, a0_sides, dh_sides, wall_thickness, percolates_z, find_delta_max,
)

N = 128
CASES = [
    ('Diamond', 5.0, 0.4),
    ('Gyroid', 5.0, 0.4),
]
OUT_CSV = (Path(__file__).resolve().parents[2] / "runs" / "_out"
           / "asym_geom_scan_2026-06-05.csv")


def scan_one(tpms, L_mm, t_mm):
    phi = _phi_grid(tpms, N)
    L_m = L_mm / 1000.0
    C = _C_from_tL(tpms, t_mm / L_mm)
    phimax = float(np.max(np.abs(phi)))
    dmax = find_delta_max(phi, C)   # 壁=2C 常数 → δ_max 纯连通极限
    deltas = np.linspace(0.0, min(dmax * 1.15, phimax), 41)
    rows = []
    for d in deltas:
        eps_A, eps_B, eps = eps_sides(phi, C, d)
        A0_A, A0_B = a0_sides(phi, C, d, L_m, N)
        Dh_A, Dh_B = dh_sides(phi, C, d, L_m, N)
        t = wall_thickness(phi, C, d, L_m, N)
        pA = percolates_z(phi < (d - C))
        pB = percolates_z(phi > (d + C))
        r = eps_A / eps_B if eps_B > 1e-9 else float('inf')
        rows.append(dict(tpms=tpms, L_mm=L_mm, t_mm=t_mm, delta=float(d), C=C,
                         eps_A=eps_A, eps_B=eps_B, eps=eps, r=r,
                         A0_A=A0_A, A0_B=A0_B, Dh_A=Dh_A, Dh_B=Dh_B,
                         t_phys_mm=t * 1000.0, perc_A=pA, perc_B=pB,
                         feasible=bool(pA and pB)))   # 壁=2C 常数, 只看连通
    return rows, dmax


def main():
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    all_rows = []
    summary = []
    for tpms, L, t in CASES:
        rows, dmax = scan_one(tpms, L, t)
        all_rows += rows
        feas = [x for x in rows if x['feasible']]
        r_max = max((x['r'] for x in feas), default=0.0)
        e0 = rows[0]['eps']
        last = feas[-1] if feas else rows[0]
        eps_drift = abs(last['eps'] - e0) / e0 * 100
        # r_usable = 可用 r（小通道 ε_B 不塌过半：>= δ=0 时的 50%），避开 pinch 虚高
        epsB0 = rows[0]['eps_B']
        usable = [x for x in feas if x['eps_B'] >= 0.5 * epsB0]
        r_usable = max((x['r'] for x in usable), default=0.0)
        ref = compute_geometry(tpms, L, t, N)
        anchor_ok = abs(rows[0]['A0_A'] - ref['A_0']) / ref['A_0'] < 0.03
        summary.append(dict(tpms=tpms, dmax=dmax, r_max=r_max, r_usable=r_usable,
                            eps_drift_pct=eps_drift, anchor_ok=anchor_ok))
    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    print(f"[CSV] {OUT_CSV}  ({len(all_rows)} rows)")
    print("\n=== Phase 0 GATE (壁=2C 常数; r_usable = r @ eps_B >= 50% of eps_B0) ===")
    for s in summary:
        verdict = "PASS" if (s['r_usable'] >= 2.0 and s['anchor_ok']) else "HOLD"
        print(f"  {s['tpms']:8s} delta_max={s['dmax']:.3f}(连通)  "
              f"r_usable={s['r_usable']:.2f}  r_max={s['r_max']:.2f}(pinch)  "
              f"eps_drift={s['eps_drift_pct']:.1f}%  "
              f"anchor={'OK' if s['anchor_ok'] else 'FAIL'}  -> {verdict}")
    return all_rows, summary


if __name__ == "__main__":
    main()
