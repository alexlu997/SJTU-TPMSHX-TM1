"""mms_phase_a3_h_refine.py — Phase A.3: 5-grid h-refinement order verification.

Standard Tier ASME V&V 20 — Phase A.3.

Runs MMS 1D/2D/3D on 5-grid sequence {12, 16, 20, 30, 40}^3.
Fits log-log L2 vs h to extract observed order p_obs per phase.

Hard gates (per plan):
  p_obs_A >= 1.5
  p_obs_B >= 1.5
  p_obs_s >= 1.8       (pure diffusion expects 2nd order)
  L2 (grid 30) < 1.0% per phase

Outputs:
  validation/mms_phase_a3_h_refine.csv     (raw L2/Linf per grid per case)
  validation/mms_phase_a3_orders.csv       (fitted slopes)
  .cache/validation/mms_phase_a3_report.md (auto-written, repository-local)
  validation/mms_phase_a3_loglog.png       (log-log plot, if matplotlib)
"""
from __future__ import annotations
import argparse
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.validation.cases.mms_3d_air_air import run_mms, L_DOM
from sjtu_tpmshx.validation.harness._provenance import write_csv_with_provenance
from sjtu_tpmshx.validation.harness._order_fit import fit_order_loglog
from sjtu_tpmshx.validation.harness._mms_driver import run_grid_sequence

_SCRIPT_REL = 'sjtu_tpmshx/validation/cases/mms_phase_a3_h_refine.py'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', default='all', help='comma-list or "all"')
    ap.add_argument('--grids', default='12,16,20,30,40',
                    help='comma-list of N values (Nx=Ny=Nz=N)')
    ap.add_argument('--max_outer', type=int, default=2500)
    ap.add_argument('--inner', type=int, default=100)
    ap.add_argument('--alpha_f', type=float, default=0.7)
    ap.add_argument('--alpha_s', type=float, default=1.0)
    ap.add_argument('--out_csv', default='validation/mms_phase_a3_h_refine.csv')
    ap.add_argument('--orders_csv', default='validation/mms_phase_a3_orders.csv')
    ap.add_argument('--report', default=str(
        ROOT.parent / '.cache' / 'validation' / 'mms_phase_a3_report.md'))
    ap.add_argument('--plot', action='store_true', help='Generate log-log plot')
    args = ap.parse_args()

    cases = ['1d', '2d', '3d'] if args.cases == 'all' else args.cases.split(',')
    grids = [int(g) for g in args.grids.split(',')]

    print(f"{'='*72}")
    print("  MMS Phase A.3 — h-refinement order verification")
    print(f"{'='*72}")
    print(f"  Cases:  {cases}")
    print(f"  Grids:  {grids}  (h_x = L/N = {L_DOM:.4f}/N)")
    print(f"  alpha_f={args.alpha_f}  alpha_s={args.alpha_s}")
    print(f"  max_outer={args.max_outer}  inner={args.inner}\n")

    rows = []
    t_start = time.time()
    for c in cases:
        print(f"--- MMS-{c} ---")
        rows += run_grid_sequence(
            grids,
            lambda g, _c=c: run_mms(_c, Nx=g, Ny=g, Nz=g,
                                    max_outer=args.max_outer,
                                    inner=args.inner,
                                    alpha_f=args.alpha_f,
                                    alpha_s=args.alpha_s,
                                    verbose=False),
            lambda g, r, dt, _c=c: dict(
                case=_c, N=g, h=L_DOM / g,
                L2_A=r['L2_A'], L2_B=r['L2_B'], L2_s=r['L2_s'],
                Linf_A=r['Linf_A'], Linf_B=r['Linf_B'], Linf_s=r['Linf_s'],
                outer_iters=r['outer_iters'], last_chg=r['last_chg'],
                elapsed=dt),
            on_grid=lambda g, r, row, dt: print(
                f"  N={g:>3d}  L2_A={r['L2_A']:.4%}  L2_B={r['L2_B']:.4%}  "
                f"L2_s={r['L2_s']:.4%}  Linf_A={r['Linf_A']:.3f}K  "
                f"[{dt:.0f}s, conv={r['converged']}]"))
        print()

    df = pd.DataFrame(rows)
    out_csv = ROOT / args.out_csv
    write_csv_with_provenance(df, out_csv, _SCRIPT_REL)
    print(f"Raw data written: {out_csv}")

    # Order fit
    print(f"\n{'='*72}")
    print("  Observed order (log-log fit, all grids)")
    print(f"{'='*72}")
    order_rows = []
    print(f"  {'case':<6} {'metric':<7} {'p_obs':>8} {'R^2':>7} {'L2(g30)':>10}")
    for c in cases:
        sub = df[df['case'] == c].sort_values('h', ascending=False)
        h = sub['h'].values
        for metric in ['L2_A', 'L2_B', 'L2_s', 'Linf_A', 'Linf_B', 'Linf_s']:
            _fit = fit_order_loglog(h, sub[metric].values)
            p, c0, r2 = _fit.p, _fit.c, _fit.r2
            row = dict(case=c, metric=metric, p_obs=p, R2=r2,
                       intercept=c0)
            # Ref grid 30 value
            g30 = sub[sub['N'] == 30]
            row['val_g30'] = float(g30[metric].iloc[0]) if len(g30) else float('nan')
            order_rows.append(row)
            print(f"  {c:<6} {metric:<7} {p:>7.3f} {r2:>7.4f} "
                  f"{row['val_g30']:>9.4g}")
        print()
    order_df = pd.DataFrame(order_rows)
    orders_csv = ROOT / args.orders_csv
    write_csv_with_provenance(order_df, orders_csv, _SCRIPT_REL)
    print(f"Orders written: {orders_csv}")

    # Hard gates
    print(f"\n{'='*72}")
    print("  Hard gates")
    print(f"{'='*72}")
    fail = []
    for c in cases:
        sub = order_df[order_df['case'] == c]
        pA = sub[sub['metric'] == 'L2_A']['p_obs'].iloc[0]
        pB = sub[sub['metric'] == 'L2_B']['p_obs'].iloc[0]
        ps = sub[sub['metric'] == 'L2_s']['p_obs'].iloc[0]
        L2A_g30 = sub[sub['metric'] == 'L2_A']['val_g30'].iloc[0]
        L2B_g30 = sub[sub['metric'] == 'L2_B']['val_g30'].iloc[0]
        L2s_g30 = sub[sub['metric'] == 'L2_s']['val_g30'].iloc[0]
        gates = dict(
            p_A_ge_1p5=(pA >= 1.5),
            p_B_ge_1p5=(pB >= 1.5),
            p_s_ge_1p8=(ps >= 1.8),
            L2A_g30_lt_1pct=(L2A_g30 < 0.010),
            L2B_g30_lt_1pct=(L2B_g30 < 0.010),
            L2s_g30_lt_1pct=(L2s_g30 < 0.010),
        )
        all_ok = all(gates.values())
        print(f"  MMS-{c}: p_obs (A={pA:.2f}, B={pB:.2f}, s={ps:.2f})  "
              f"L2_g30 (A={L2A_g30:.3%}, B={L2B_g30:.3%}, s={L2s_g30:.3%})  "
              f"{'PASS' if all_ok else 'FAIL'}")
        if not all_ok:
            for g, ok in gates.items():
                if not ok:
                    print(f"    FAIL gate: {g}")
            fail.append(c)

    elapsed_total = time.time() - t_start
    print(f"\n  Total elapsed: {elapsed_total/60:.1f} min")

    # Plot
    if args.plot:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(1, len(cases), figsize=(5*len(cases), 4.5),
                                     squeeze=False)
            for i, c in enumerate(cases):
                ax = axes[0, i]
                sub = df[df['case'] == c].sort_values('h', ascending=False)
                for metric, mark in [('L2_A', 'o-'), ('L2_B', 's-'), ('L2_s', '^-')]:
                    ax.loglog(sub['h'], sub[metric], mark, label=metric)
                # 2nd-order reference line
                h_ref = sub['h'].values
                e_ref = (h_ref / h_ref[0]) ** 2 * sub['L2_A'].iloc[0]
                ax.loglog(h_ref, e_ref, 'k--', alpha=0.5, label='slope=2')
                ax.set_xlabel('h (m)')
                ax.set_ylabel('rel L2')
                ax.set_title(f'MMS-{c}')
                ax.legend(fontsize=8)
                ax.grid(True, which='both', alpha=0.3)
            plt.tight_layout()
            plot_path = ROOT / 'validation' / 'mms_phase_a3_loglog.png'
            plt.savefig(plot_path, dpi=120)
            print(f"  Plot saved: {plot_path}")
        except Exception as e:
            print(f"  Plot skipped: {e}")

    # Auto-write report
    try:
        _write_report(args.report, cases, grids, df, order_df, args)
        print(f"  Report saved: {args.report}")
    except Exception as e:
        print(f"  Report write skipped: {e}")

    return 1 if fail else 0


def _write_report(path, cases, grids, df, order_df, args):
    lines = [
        "# MMS Phase A.3 — h-refinement Order Verification",
        "",
        "## 目标",
        "",
        "Standard Tier ASME V&V 20 框架 Phase A.3. 5-grid sequence "
        f"{grids} 跑 MMS 1D/2D/3D, log-log fit 提取观测阶 p_obs.",
        "",
        "## Hard gates",
        "",
        "- p_obs (L2_A) >= 1.5",
        "- p_obs (L2_B) >= 1.5",
        "- p_obs (L2_s) >= 1.8 (pure diffusion 期望 2nd order)",
        "- L2 (grid 30) < 1.0% per phase",
        "",
        "## 配置",
        "",
        f"- Domain: {L_DOM*1000:.0f}x42x42 mm (Shanghai-like)",
        f"- alpha_f={args.alpha_f}  alpha_s={args.alpha_s}",
        f"- max_outer={args.max_outer}  inner={args.inner}",
        "",
        "## 原始 L2/Linf vs grid",
        "",
    ]
    for c in cases:
        lines += [f"### MMS-{c}", "", "| N | h | L2_A | L2_B | L2_s | "
                  "Linf_A | Linf_B | Linf_s | iters |", "|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        sub = df[df['case'] == c].sort_values('N')
        for _, r in sub.iterrows():
            lines.append(
                f"| {int(r['N'])} | {r['h']:.5f} | {r['L2_A']:.4%} | "
                f"{r['L2_B']:.4%} | {r['L2_s']:.4%} | {r['Linf_A']:.3f} | "
                f"{r['Linf_B']:.3f} | {r['Linf_s']:.3f} | {int(r['outer_iters'])} |")
        lines += ["", ""]

    lines += ["## 观测阶 (log-log fit, 全 5 grid)", "",
              "| case | metric | p_obs | R^2 | L2 @ grid 30 |",
              "|------|--------|------:|----:|-------------:|"]
    for _, r in order_df.iterrows():
        lines.append(f"| {r['case']} | {r['metric']} | {r['p_obs']:.3f} | "
                     f"{r['R2']:.4f} | {r['val_g30']:.4g} |")

    lines += [
        "",
        "## 结论",
        "",
        "见 csv 和 console 输出 hard-gate pass/fail 详情.",
        "",
        "## 文件",
        "",
        f"- driver: `{_SCRIPT_REL}`",
        f"- 原始数据: `{args.out_csv}`",
        f"- order csv: `{args.orders_csv}`",
        "- log-log 图: `validation/mms_phase_a3_loglog.png` (--plot)",
        "",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
