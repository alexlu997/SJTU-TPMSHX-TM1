"""fit_cf_aniso.py — 方向分辨单胞 CFD 结果 → cf_aniso 系数（见同目录 README）.

用法:
    python -m sjtu_tpmshx.validation.cf_aniso.fit_cf_aniso results.csv

输入 CSV 列 (与 results_template.csv 相同):
    case_id, tpms, L_mm, t_mm, theta_deg, u_sup_mps,
    dpdl_Pa_per_m, rho_kg_m3, mu_Pa_s

输出:
    每 (tpms, L, t, θ): K(θ), cF(θ) — 二次拟合 dP/L = (μ/K)u + ρ·cF·u²
    K 各向同性核验: K(θ)/K(0) 偏差 (>5 % 报警 → 升级台账 B3 全张量)
    cf_aniso: cF(θ)/cF(0) − 1 = a·ξ4(θ) 最小二乘, 每 (L,t) 一个 a + 汇总
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd


def _fit_darcy_forchheimer(u, dpdl, rho, mu):
    """dP/L = (mu/K)·u + rho·cF·u² → (K, cF). Linear LSQ in (u, u²)."""
    A = np.column_stack([u, u * u])
    coef, *_ = np.linalg.lstsq(A, dpdl, rcond=None)
    a_lin, b_quad = float(coef[0]), float(coef[1])
    if a_lin <= 0 or b_quad <= 0:
        raise ValueError(f"non-physical fit: linear={a_lin:.3e} quad={b_quad:.3e}")
    return float(mu) / a_lin, b_quad / float(rho)


def main(path: str) -> None:
    df = pd.read_csv(path)
    need = {'tpms', 'L_mm', 't_mm', 'theta_deg', 'u_sup_mps',
            'dpdl_Pa_per_m', 'rho_kg_m3', 'mu_Pa_s'}
    missing = need - set(df.columns)
    if missing:
        sys.exit(f"missing columns: {sorted(missing)}")
    df = df.dropna(subset=['dpdl_Pa_per_m'])
    if df.empty:
        sys.exit("no filled rows — run the CFD worklist first")

    rows = []
    for (tpms, L, t, th), g in df.groupby(['tpms', 'L_mm', 't_mm', 'theta_deg']):
        K, cF = _fit_darcy_forchheimer(
            g['u_sup_mps'].to_numpy(float),
            g['dpdl_Pa_per_m'].to_numpy(float),
            g['rho_kg_m3'].astype(float).mean(),
            g['mu_Pa_s'].astype(float).mean())
        th_rad = np.deg2rad(th)
        xi4 = float(4.0 * (np.sin(th_rad) * np.cos(th_rad)) ** 2)
        rows.append(dict(tpms=tpms, L_mm=L, t_mm=t, theta_deg=th,
                         xi4=xi4, K=K, cF=cF, n_pts=len(g)))
    res = pd.DataFrame(rows).sort_values(['tpms', 'L_mm', 't_mm', 'theta_deg'])
    print("\n== per-case K / cF ==")
    print(res.to_string(index=False))

    print("\n== K isotropy check (theory: flat for cubic symmetry) ==")
    a_list = []
    for (tpms, L, t), g in res.groupby(['tpms', 'L_mm', 't_mm']):
        g = g.sort_values('theta_deg')
        base = g[g['theta_deg'] == 0.0]
        if base.empty:
            print(f"  {tpms} L={L} t={t}: no θ=0 row — skipped")
            continue
        K0 = float(base['K'].iloc[0]); cF0 = float(base['cF'].iloc[0])
        K_dev = float((g['K'] / K0 - 1.0).abs().max())
        flag = "  ⚠ >5% — escalate ledger B3 (full tensor)" if K_dev > 0.05 else ""
        print(f"  {tpms} L={L} t={t}: max|K(θ)/K(0)−1| = {K_dev:.1%}{flag}")
        # cf_aniso per (L,t): LSQ through origin on (ξ4, cF/cF0 − 1)
        xi = g['xi4'].to_numpy(float)
        y = (g['cF'] / cF0 - 1.0).to_numpy(float)
        denom = float(np.dot(xi, xi))
        if denom > 0:
            a = float(np.dot(xi, y) / denom)
            a_list.append((tpms, L, t, a))

    print("\n== cf_aniso per (L, t) ==")
    for tpms, L, t, a in a_list:
        print(f"  {tpms} L={L} t={t}: cf_aniso = {a:+.4f}")
    if a_list:
        vals = np.array([a for *_, a in a_list])
        print(f"\n  POOLED cf_aniso = {vals.mean():+.4f} ± {vals.std(ddof=0):.4f}"
              f"  (spread > 0.05 → make it (L,t)-dependent; the per-cell cF"
              f" plumbing already supports that)")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
