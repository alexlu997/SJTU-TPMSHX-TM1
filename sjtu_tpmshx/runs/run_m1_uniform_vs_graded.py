"""runs/run_m1_uniform_vs_graded.py — M1: 均匀 vs 梯度(连续场) Pareto 对照.

ZONED-OPTIMIZATION-PLAN-CN.md §六 M1 (Park 2026 IJHMT 269:129145 Fig.8 的
本项目复现): 同一工况、同量级评估预算下, 比较

  * UNIFORM  — 全域单一 (L, t) 的最优均匀设计前沿。2 维空间用确定性网格
               扫掠 (9×5 = 45 评估, 覆盖训练凸包) 取非支配集 — 比 BO 在
               2 维更干净, 无采样噪声。
  * GRADED   — 现有 16 维连续场 qNEHVI (32 Sobol + 24×2 BO = 80 评估)。

判据 (计划 §七): 两条前沿几乎重合 (HV 增益 < 5%) → 伴随线降级回想法池;
支配间隙显著 → 伴随线立项论证成立。附带产出 Tier-0 需要的输入: 梯度
Pareto 解中实际出现的最陡 L / ε 梯度。

Run (repo root):
  PYTHONHASHSEED=0 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
      PYTHONPATH=sjtu_tpmshx python -u \
      sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py [--fast]

Outputs in reports/m1_uniform_vs_graded/:
  uniform_all.csv / uniform_pareto.csv    扫掠全点 / 非支配集
  qnehvi_m1/                              run_qnehvi 的标准输出目录
  m1_metrics.json                         HV、支配率、最陡梯度
  m1_pareto_compare.png                   对照图 (dpi=300)
"""

from __future__ import annotations

import argparse
import json
import os
import time
import warnings

import numpy as np

from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG, evaluate_design, _resolve_grid
from sjtu_tpmshx.optimization.optimizer_qnehvi import run_qnehvi, _pareto_mask_max
from sjtu_tpmshx.models.continuous_field import (
    encode_decision_vector,
    from_decision_vector,
    decision_dim,
)
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L, TRAIN_T


# ─── Config (operating point mirrors runs/run_3d_qnehvi_fast.py) ────

CFG_M1: dict = {
    **DEFAULT_CONFIG,
    'tpms_type':  'Gyroid',
    'L_domain':   0.182,     # m (fluid A streamwise, Shanghai HX)
    'H_domain':   0.042,     # m (fluid B streamwise)
    'k_s':        16.0,      # 304 SS
    'rho_s':      7900.0,
    'u_A':        10.0,
    'u_B':        5.0,
    'T_inA':      400.0,
    'T_inB':      300.0,
    'P_inA':      101325.0,
    'P_inB':      101325.0,
    'n_rho_loops': 3,        # compressible baseline (hard invariant)
    # BC: ports_A/ports_B unset → DEFAULT_CONFIG None → FULL-FACE inlet/outlet
    # on both streams. The M1/M3 verdicts (graded +3~5 %, 36-D no gain) are
    # scoped to this full-face counterflow condition; the port-BC re-test
    # lives in run_port_dim_retest.py (ledger IDEA-PORT-DIM).
}

OUT_DIR = os.path.join('reports', 'm1_uniform_vs_graded')


# ─── Uniform sweep ──────────────────────────────────────────────────


def _uniform_x(L_mm: float, t_mm: float, cfg: dict) -> np.ndarray:
    """Decision vector of a uniform (L, t) field in the cfg's control grid."""
    ncx, ncy = int(cfg['n_ctrl_x']), int(cfg['n_ctrl_y'])
    return encode_decision_vector(
        np.full((ncx, ncy), L_mm, dtype=np.float64),
        np.full((ncx, ncy), t_mm, dtype=np.float64),
        bool(cfg['symmetric_y']),
    )


def _eval_uniform_one(L_mm: float, t_mm: float, cfg: dict) -> tuple:
    """(L, t, Q, dP, mass, err) for one uniform design."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            Q_neg, dP, mass = evaluate_design(_uniform_x(L_mm, t_mm, cfg), cfg)
        return (L_mm, t_mm, float(-Q_neg), float(dP), float(mass), '')
    except Exception as e:                                  # noqa: BLE001
        return (L_mm, t_mm, np.nan, np.nan, np.nan, repr(e))


def run_uniform_sweep(cfg: dict, L_vals, t_vals, n_jobs: int) -> np.ndarray:
    """Sweep uniform (L, t) grid → array rows (L, t, Q, dP, mass)."""
    from joblib import Parallel, delayed
    combos = [(float(L), float(t)) for L in L_vals for t in t_vals]
    print(f"[M1] uniform sweep: {len(combos)} designs "
          f"(L {L_vals[0]:.1f}–{L_vals[-1]:.1f} × t {t_vals[0]:.2f}–{t_vals[-1]:.2f}), "
          f"n_jobs={n_jobs}", flush=True)
    t0 = time.time()
    rows = Parallel(n_jobs=n_jobs)(
        delayed(_eval_uniform_one)(L, t, cfg) for L, t in combos)
    ok = [r[:5] for r in rows if not r[5]]
    for r in rows:
        if r[5]:
            print(f"[M1]   uniform ({r[0]:.1f}, {r[1]:.2f}) FAILED: {r[5]}",
                  flush=True)
    print(f"[M1] uniform sweep done: {len(ok)}/{len(combos)} ok "
          f"in {time.time()-t0:.0f} s", flush=True)
    return np.asarray(ok, dtype=np.float64)


# ─── Metrics ────────────────────────────────────────────────────────


def hv_2d_max(front_QdP: np.ndarray, ref: tuple) -> float:
    """2-objective hypervolume under (maximize Q, minimize dP).

    ``front_QdP`` rows (Q, dP); ``ref`` = (Q_ref, dP_ref) with Q_ref below
    every Q and dP_ref above every dP. Rectangle-sum over the dP-sorted
    non-dominated set.
    """
    if front_QdP.size == 0:
        return 0.0
    Y = front_QdP[_pareto_mask_max(
        np.column_stack([front_QdP[:, 0], -front_QdP[:, 1]]))]
    Y = Y[np.argsort(Y[:, 1])]           # dP ascending → Q descending
    hv, dp_prev = 0.0, ref[1]
    for Q, dP in Y[::-1]:                # from worst dP down
        hv += max(0.0, Q - ref[0]) * max(0.0, dp_prev - dP)
        dp_prev = dP
    return float(hv)


def dominated_fraction(uni_front: np.ndarray, grad_front: np.ndarray) -> float:
    """Fraction of uniform-front points strictly dominated by ≥1 graded point
    (max-Q / min-dP semantics)."""
    if uni_front.size == 0 or grad_front.size == 0:
        return float('nan')
    n_dom = 0
    for Qu, dPu in uni_front:
        dom = np.any((grad_front[:, 0] >= Qu) & (grad_front[:, 1] <= dPu) &
                     ((grad_front[:, 0] > Qu) | (grad_front[:, 1] < dPu)))
        n_dom += bool(dom)
    return n_dom / len(uni_front)


def steepest_gradients(X_pareto: np.ndarray, cfg: dict) -> dict:
    """Max per-cell relative L step and per-cell ε step over Pareto designs.

    Feeds Tier-0 of the scale-separation spot check (plan §五 3b): the strip
    CFD's gradient level is taken from what the optimizer ACTUALLY produced,
    not an assumed value.
    """
    out = {'max_rel_dL_per_cell': 0.0, 'max_abs_deps_per_cell': 0.0,
           'argmax_design': -1}
    for i, x in enumerate(np.asarray(X_pareto, dtype=np.float64)):
        fc = from_decision_vector(
            x, tpms_type=cfg['tpms_type'], k_s=cfg['k_s'],
            L_domain=cfg['L_domain'], H_domain=cfg['H_domain'],
            n_ctrl_x=cfg['n_ctrl_x'], n_ctrl_y=cfg['n_ctrl_y'],
            symmetric_y=cfg['symmetric_y'], spline_order=cfg['spline_order'],
            L_bounds=cfg['L_bounds'], t_bounds=cfg['t_bounds'])
        Nx, Ny = _resolve_grid(cfg, fc)
        arrays = fc.build_grid_arrays(
            Nx, Ny, u_A=cfg['u_A'], u_B=cfg['u_B'],
            T_inA=cfg['T_inA'], T_inB=cfg['T_inB'], P_in=cfg['P_inA'])
        L_f, eps = arrays['L_field'], arrays['eps_arr']
        rel_dL = max(
            float(np.max(np.abs(np.diff(L_f, axis=0)) / L_f[:-1, :]))
            if L_f.shape[0] > 1 else 0.0,
            float(np.max(np.abs(np.diff(L_f, axis=1)) / L_f[:, :-1]))
            if L_f.shape[1] > 1 else 0.0)
        deps = max(
            float(np.max(np.abs(np.diff(eps, axis=0))))
            if eps.shape[0] > 1 else 0.0,
            float(np.max(np.abs(np.diff(eps, axis=1))))
            if eps.shape[1] > 1 else 0.0)
        if rel_dL > out['max_rel_dL_per_cell']:
            out['argmax_design'] = i
        out['max_rel_dL_per_cell'] = max(out['max_rel_dL_per_cell'], rel_dL)
        out['max_abs_deps_per_cell'] = max(out['max_abs_deps_per_cell'], deps)
    return out


# ─── Plot ───────────────────────────────────────────────────────────


def plot_compare(uni_all, uni_front, grad_hist, grad_front, metrics,
                 path_png: str) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    if grad_hist is not None and len(grad_hist):
        ax.scatter(grad_hist[:, 1], grad_hist[:, 0], s=12, c='0.82',
                   label=f'graded history (n={len(grad_hist)})', zorder=1)
    if len(uni_all):
        ax.scatter(uni_all[:, 3], uni_all[:, 2], s=18, c='#8FBC8F',
                   marker='s', label=f'uniform sweep (n={len(uni_all)})',
                   zorder=2)
    o = np.argsort(uni_front[:, 1])
    ax.plot(uni_front[o, 1], uni_front[o, 0], 's-', c='#2E7D32', ms=6,
            lw=1.6, label=f'uniform Pareto (n={len(uni_front)})', zorder=3)
    o = np.argsort(grad_front[:, 1])
    ax.plot(grad_front[o, 1], grad_front[o, 0], 'o-', c='#C1440E', ms=6,
            lw=1.6, label=f'graded Pareto (n={len(grad_front)})', zorder=4)
    ax.set_xlabel('dP  [Pa]  (A+B, incl. manufacturability penalty)')
    ax.set_ylabel('Q  [W/m depth]')
    ax.set_xscale('log')
    ax.grid(True, alpha=0.3, which='both')
    ax.legend(loc='lower right', fontsize=9)
    ax.set_title(
        f"M1 uniform vs graded — {CFG_M1['tpms_type']}, "
        f"{CFG_M1['L_domain']*1e3:.0f}×{CFG_M1['H_domain']*1e3:.0f} mm, "
        f"u=({CFG_M1['u_A']:.0f},{CFG_M1['u_B']:.0f}) m/s\n"
        f"HV gain {metrics['hv_gain_pct']:+.1f} %  ·  "
        f"uniform front dominated {metrics['uniform_dominated_frac']*100:.0f} %",
        fontsize=10)
    fig.tight_layout()
    fig.savefig(path_png, dpi=300)
    plt.close(fig)
    print(f"[M1] figure → {path_png}", flush=True)


# ─── Main ───────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true',
                    help='smoke: 3×2 uniform grid + 6 Sobol + 2 BO iters')
    ap.add_argument('--jobs', type=int, default=6,
                    help='joblib workers for the uniform sweep')
    ap.add_argument('--seed', type=int, default=42,
                    help='qNEHVI seed (robustness re-runs)')
    ap.add_argument('--no-early-stop', action='store_true',
                    help='disable the HV-plateau early stop (hv_tol=0)')
    ap.add_argument('--skip-uniform', action='store_true',
                    help='reuse existing uniform_all.csv (seed re-runs)')
    ap.add_argument('--ctrl', type=int, default=4, choices=(4, 6),
                    help='control grid per side (M3 gate-2: 6 → 36-D). '
                         'Budget auto-scales: n_init = 2×D, n_iter 32.')
    ap.add_argument('--saas', action='store_true',
                    help='fully-Bayesian SAAS GP (NUTS) — the d≥30 engine; '
                         'slow per iter but sample-efficient in high-D')
    a = ap.parse_args()

    global OUT_DIR
    if a.seed != 42 or a.no_early_stop or a.ctrl != 4 or a.saas:
        OUT_DIR = os.path.join(
            'reports', 'm1_uniform_vs_graded',
            f"{'ctrl%d_' % a.ctrl if a.ctrl != 4 else ''}"
            f"{'saas_' if a.saas else ''}seed{a.seed}"
            f"{'_full' if a.no_early_stop else ''}")
    os.makedirs(OUT_DIR, exist_ok=True)
    cfg = dict(CFG_M1)
    if a.ctrl != 4:
        cfg['n_ctrl_x'] = a.ctrl
        cfg['n_ctrl_y'] = a.ctrl
    if a.saas:
        cfg['gp_model'] = 'saas'
    t_start = time.time()

    D = decision_dim(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'])
    if a.fast:
        L_vals = np.linspace(TRAIN_L[0], TRAIN_L[1], 3)
        t_vals = np.linspace(TRAIN_T[0], TRAIN_T[1], 2)
        n_init, n_iter, q_batch = 6, 2, 2
    else:
        L_vals = np.linspace(TRAIN_L[0], TRAIN_L[1], 9)
        t_vals = np.linspace(TRAIN_T[0], TRAIN_T[1], 5)
        # n_init = 2×D rule of thumb; 36-D (M3 gate-2) gets more BO iters too.
        n_init = 2 * D
        n_iter, q_batch = (32 if D > 16 else 24), 2
    print(f"[M1] cfg: {cfg['tpms_type']} D={D} "
          f"budget uniform={len(L_vals)*len(t_vals)} "
          f"graded={n_init}+{n_iter}×{q_batch}", flush=True)

    # 1. uniform sweep (or reuse the seed-42 baseline for seed re-runs)
    if a.skip_uniform:
        _base_csv = os.path.join('reports', 'm1_uniform_vs_graded',
                                 'uniform_all.csv')
        uni = np.loadtxt(_base_csv, delimiter=',', skiprows=1)
        print(f"[M1] uniform sweep reused from {_base_csv} "
              f"({len(uni)} designs)", flush=True)
    else:
        uni = run_uniform_sweep(cfg, L_vals, t_vals, a.jobs)
    np.savetxt(os.path.join(OUT_DIR, 'uniform_all.csv'), uni,
               delimiter=',', header='L_mm,t_mm,Q_W_per_m,dP_Pa,mass_kg_per_m',
               comments='')
    uni_mask = _pareto_mask_max(np.column_stack([uni[:, 2], -uni[:, 3]]))
    uni_front_rows = uni[uni_mask]
    np.savetxt(os.path.join(OUT_DIR, 'uniform_pareto.csv'), uni_front_rows,
               delimiter=',', header='L_mm,t_mm,Q_W_per_m,dP_Pa,mass_kg_per_m',
               comments='')
    print(f"[M1] uniform Pareto: {len(uni_front_rows)} points", flush=True)

    # 2. graded qNEHVI
    res = run_qnehvi(config=cfg, n_init=n_init, n_iter=n_iter,
                     q_batch=q_batch, seed=a.seed, verbose=True,
                     save_dir=os.path.join(OUT_DIR, 'qnehvi_m1'),
                     n_jobs=min(q_batch, 2),
                     hv_tol=0.0 if a.no_early_stop else 0.01)
    grad_front = np.column_stack([-res['F'][:, 0], res['F'][:, 1]])   # (Q, dP)
    grad_hist = (np.column_stack([-res['history_F'][:, 0],
                                  res['history_F'][:, 1]])
                 if res.get('history_F') is not None else None)

    # 3. metrics — common ref point spans both fronts
    uni_front = uni_front_rows[:, 2:4]                                # (Q, dP)
    all_pts = np.vstack([uni_front, grad_front])
    ref = (0.0, float(all_pts[:, 1].max()) * 1.05)
    hv_uni = hv_2d_max(uni_front, ref)
    hv_grad = hv_2d_max(grad_front, ref)
    grads = steepest_gradients(res['X'], cfg)
    metrics = {
        'config': {k: cfg[k] for k in
                   ('tpms_type', 'L_domain', 'H_domain', 'u_A', 'u_B',
                    'T_inA', 'T_inB', 'P_inA', 'P_inB', 'n_rho_loops')},
        'budget': {'uniform': int(len(L_vals) * len(t_vals)),
                   'graded': int(res['n_evals'])},
        'ref_point_Q_dP': list(ref),
        'hv_uniform': hv_uni,
        'hv_graded': hv_grad,
        'hv_gain_pct': (hv_grad / hv_uni - 1.0) * 100.0 if hv_uni > 0 else float('nan'),
        'uniform_dominated_frac': dominated_fraction(uni_front, grad_front),
        'steepest_gradients_tier0': grads,
        'wall_seconds': time.time() - t_start,
    }
    with open(os.path.join(OUT_DIR, 'm1_metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"[M1] HV uniform={hv_uni:.4g}  graded={hv_grad:.4g}  "
          f"gain={metrics['hv_gain_pct']:+.2f} %", flush=True)
    print(f"[M1] uniform front dominated: "
          f"{metrics['uniform_dominated_frac']*100:.0f} %", flush=True)
    print(f"[M1] Tier-0 steepest gradients: {grads}", flush=True)

    # 4. figure
    plot_compare(uni, uni_front, grad_hist, grad_front, metrics,
                 os.path.join(OUT_DIR, 'm1_pareto_compare.png'))
    print(f"[M1] DONE in {metrics['wall_seconds']/60:.1f} min → {OUT_DIR}",
          flush=True)


if __name__ == '__main__':
    main()
