"""runs/run_port_dim_retest.py — 端口 BC 下的维数收益复测 (IDEA-PORT-DIM).

背景: ADJOINT 门 2 判决 ("升维无收益, 伴随线关闭") 的全部实验用整面进出
退化分支, 判决范围限定于整面逆流 (见 M3-gate2 报告 §四 范围限定).
本实验把设计域换成 Park 2026 IJHMT 269:129145 Fig.4 的类比配置 —
方形芯体 + 每股流体单端口进出 + 流股在域内交叉 — 检验流路自由度
出现后, 高维 ε 场是否恢复收益.

与 Park Fig.4 的对应 / 偏离 (刻意, 均有记录):
  * 复现: 方形域 0.15×0.15 m、端口宽 0.015 m (10 % 面宽)、单端口进出、
    两股流对角交叉、双流体各自连续域 (TPMS 非混合双网络).
  * 偏离: 工质保持 air (评估器闭合为 air 标定; Park 用水), 速度保持
    M1 工况 u=(10,5) m/s (Forchheimer 主导区 — 我们的标定域; Park 是
    低速层流线性阻力区). 故本实验隔离的是"端口流路自由度"单变量,
    不是 Park 工况的完整复刻.

关键前提 (2026-07-10 同批实装, 缺一不可):
  * per_cell_K=True — 动量阻力逐胞 (lateral-K). 旧的逐行投影把横向
    阻力对比平均掉, "选路"杠杆在动量方程里根本不存在.
  * symmetric_y=False — 端口布置破坏 y 镜像对称, 决策维数翻倍:
    4×4 → 32 维, 6×6 → 72 维.
  * SAAS 引擎双臂统一 (32/72 维都 ≥30 维, vanilla ARD 在此已知退化,
    M3 实测) — 引擎恒定, 维数是唯一变量.
  * 无早停 (M1 seed42 假平台教训).

注意: partial-BC 绝对数字未经实验对标 (台账 IDEA-PORT-VALID) — 本实验
只做维数间相对比较, 不产出可引用的绝对 Q/dP.

Run (repo root):
  PYTHONHASHSEED=0 PYTHONPATH=sjtu_tpmshx python -u \
      sjtu_tpmshx/runs/run_port_dim_retest.py --ctrl 4 --seed 7 [--fast]

Outputs in reports/port_dim_retest/ctrl{4|6}_seed{N}/:
  uniform_all.csv / uniform_pareto.csv    端口配置下的均匀扫掠基线
  qnehvi_port/                            run_qnehvi 标准输出目录
  port_metrics.json                       HV、支配率、最陡梯度
  port_pareto_compare.png                 对照图
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG
from sjtu_tpmshx.optimization.optimizer_qnehvi import run_qnehvi, _pareto_mask_max
from sjtu_tpmshx.models.continuous_field import decision_dim
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L, TRAIN_T
from sjtu_tpmshx.runs.run_m1_uniform_vs_graded import (
    run_uniform_sweep, hv_2d_max, dominated_fraction, steepest_gradients,
)


# ─── Config — Park Fig.4 analog, M1 operating point ─────────────────

_SIDE = 0.15          # m — Park: Lx = Ly = 15 cm square body
_PORT = 0.015         # m — Park: 1.5 cm ports (10 % of the face)

CFG_PORT: dict = {
    **DEFAULT_CONFIG,
    'tpms_type':  'Gyroid',
    'L_domain':   _SIDE,     # fluid A streamwise (real x)
    'H_domain':   _SIDE,     # fluid B streamwise (real y)
    'k_s':        16.0,      # 304 SS
    'rho_s':      7900.0,
    'u_A':        10.0,      # M1 operating point (calibrated regime)
    'u_B':        5.0,
    'T_inA':      400.0,
    'T_inB':      300.0,
    'P_inA':      101325.0,
    'P_inB':      101325.0,
    'n_rho_loops': 3,        # compressible baseline (hard invariant)

    # Ports — crossing diagonals (Park Fig.4 analog):
    #   A (+x): in at TOP of the left face, out at BOTTOM of the right face ↘
    #   B (−y): in at RIGHT of the top face, out at LEFT of the bottom face ↙
    'ports_A': (_SIDE - _PORT, _SIDE, 0.0, _PORT),   # (in_lo, in_hi, out_lo, out_hi) real y
    'ports_B': (_SIDE - _PORT, _SIDE, 0.0, _PORT),   # real x

    # Routing prerequisites (see module docstring)
    'per_cell_K':  True,
    'symmetric_y': False,
}

OUT_ROOT = os.path.join('reports', 'port_dim_retest')


def plot_compare(uni_all, uni_front, grad_hist, grad_front, metrics, cfg,
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
    D = decision_dim(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'])
    ax.set_title(
        f"PORT dim-retest — {cfg['tpms_type']}, "
        f"{cfg['L_domain']*1e3:.0f}×{cfg['H_domain']*1e3:.0f} mm sq, "
        f"ports {_PORT*1e3:.0f} mm, D={D}\n"
        f"HV gain {metrics['hv_gain_pct']:+.1f} %  ·  "
        f"uniform front dominated {metrics['uniform_dominated_frac']*100:.0f} %",
        fontsize=10)
    fig.tight_layout()
    fig.savefig(path_png, dpi=300)
    plt.close(fig)
    print(f"[PORT] figure → {path_png}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true',
                    help='smoke: 3×2 uniform grid + 6 Sobol + 2 BO iters')
    ap.add_argument('--jobs', type=int, default=6)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--ctrl', type=int, default=4, choices=(4, 6),
                    help='control grid per side: 4 → 32-D, 6 → 72-D '
                         '(symmetric_y=False doubles vs the M1 mirror dims)')
    ap.add_argument('--no-saas', action='store_true',
                    help='vanilla GP (diagnostics only — both production '
                         'arms are ≥30-D, engine default is SAAS)')
    ap.add_argument('--skip-uniform', action='store_true',
                    help='reuse ctrl4_seed7/uniform_all.csv (arm re-runs; '
                         'the uniform baseline is ctrl-independent)')
    ap.add_argument('--grid', type=int, default=0,
                    help='override Nx=Ny (0 = adaptive_grid default)')
    ap.add_argument('--n-iter', type=int, default=32)
    ap.add_argument('--cf-aniso', type=float, default=0.0,
                    help='oblique-flow Forchheimer direction factor '
                         '(verdict-robustness sweeps only; the calibrated '
                         'value comes from validation/cf_aniso/)')
    a = ap.parse_args()

    out_dir = os.path.join(
        OUT_ROOT,
        f"ctrl{a.ctrl}_seed{a.seed}"
        + ('_vanilla' if a.no_saas else '')
        + (f"_aniso{a.cf_aniso:+.2f}" if a.cf_aniso != 0.0 else ''))
    os.makedirs(out_dir, exist_ok=True)
    cfg = dict(CFG_PORT)
    cfg['n_ctrl_x'] = a.ctrl
    cfg['n_ctrl_y'] = a.ctrl
    if not a.no_saas:
        cfg['gp_model'] = 'saas'
    if a.grid:
        cfg['Nx'] = a.grid
        cfg['Ny'] = a.grid
    if a.cf_aniso != 0.0:
        cfg['cf_aniso'] = a.cf_aniso
    t_start = time.time()

    D = decision_dim(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'])
    if a.fast:
        L_vals = np.linspace(TRAIN_L[0], TRAIN_L[1], 3)
        t_vals = np.linspace(TRAIN_T[0], TRAIN_T[1], 2)
        n_init, n_iter, q_batch = 6, 2, 2
    else:
        L_vals = np.linspace(TRAIN_L[0], TRAIN_L[1], 9)
        t_vals = np.linspace(TRAIN_T[0], TRAIN_T[1], 5)
        n_init, n_iter, q_batch = 2 * D, a.n_iter, 2
    print(f"[PORT] cfg: {cfg['tpms_type']} D={D} saas={not a.no_saas} "
          f"grid={cfg.get('Nx') or 'adaptive'} "
          f"budget uniform={len(L_vals)*len(t_vals)} "
          f"graded={n_init}+{n_iter}×{q_batch}", flush=True)

    # 1. uniform sweep on the SAME port config (baseline)
    if a.skip_uniform:
        _base_csv = os.path.join(OUT_ROOT, 'ctrl4_seed7', 'uniform_all.csv')
        uni = np.loadtxt(_base_csv, delimiter=',', skiprows=1)
        print(f"[PORT] uniform sweep reused from {_base_csv} "
              f"({len(uni)} designs)", flush=True)
    else:
        uni = run_uniform_sweep(cfg, L_vals, t_vals, a.jobs)
    np.savetxt(os.path.join(out_dir, 'uniform_all.csv'), uni,
               delimiter=',', header='L_mm,t_mm,Q_W_per_m,dP_Pa,mass_kg_per_m',
               comments='')
    uni_mask = _pareto_mask_max(np.column_stack([uni[:, 2], -uni[:, 3]]))
    uni_front_rows = uni[uni_mask]
    np.savetxt(os.path.join(out_dir, 'uniform_pareto.csv'), uni_front_rows,
               delimiter=',', header='L_mm,t_mm,Q_W_per_m,dP_Pa,mass_kg_per_m',
               comments='')
    print(f"[PORT] uniform Pareto: {len(uni_front_rows)} points", flush=True)

    # 2. graded qNEHVI — no early stop (M1 seed42 false-plateau lesson)
    res = run_qnehvi(config=cfg, n_init=n_init, n_iter=n_iter,
                     q_batch=q_batch, seed=a.seed, verbose=True,
                     save_dir=os.path.join(out_dir, 'qnehvi_port'),
                     n_jobs=min(q_batch, 2),
                     hv_tol=0.0)
    grad_front = np.column_stack([-res['F'][:, 0], res['F'][:, 1]])
    grad_hist = (np.column_stack([-res['history_F'][:, 0],
                                  res['history_F'][:, 1]])
                 if res.get('history_F') is not None else None)

    # 3. metrics
    uni_front = uni_front_rows[:, 2:4]
    all_pts = np.vstack([uni_front, grad_front])
    ref = (0.0, float(all_pts[:, 1].max()) * 1.05)
    hv_uni = hv_2d_max(uni_front, ref)
    hv_grad = hv_2d_max(grad_front, ref)
    grads = steepest_gradients(res['X'], cfg)
    metrics = {
        'config': {k: cfg[k] for k in
                   ('tpms_type', 'L_domain', 'H_domain', 'u_A', 'u_B',
                    'T_inA', 'T_inB', 'P_inA', 'P_inB', 'n_rho_loops',
                    'ports_A', 'ports_B', 'per_cell_K', 'symmetric_y',
                    'cf_aniso')},
        'decision_dim': int(D),
        'gp_model': cfg.get('gp_model', 'single_task'),
        'budget': {'uniform': int(len(L_vals) * len(t_vals)),
                   'graded': int(res['n_evals'])},
        'ref_point_Q_dP': list(ref),
        'hv_uniform': hv_uni,
        'hv_graded': hv_grad,
        'hv_gain_pct': (hv_grad / hv_uni - 1.0) * 100.0 if hv_uni > 0 else float('nan'),
        'uniform_dominated_frac': dominated_fraction(uni_front, grad_front),
        'steepest_gradients': grads,
        'wall_seconds': time.time() - t_start,
    }
    with open(os.path.join(out_dir, 'port_metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"[PORT] HV uniform={hv_uni:.4g}  graded={hv_grad:.4g}  "
          f"gain={metrics['hv_gain_pct']:+.2f} %", flush=True)
    print(f"[PORT] uniform front dominated: "
          f"{metrics['uniform_dominated_frac']*100:.0f} %", flush=True)

    # 4. figure
    plot_compare(uni, uni_front, grad_hist, grad_front, metrics, cfg,
                 os.path.join(out_dir, 'port_pareto_compare.png'))
    print(f"[PORT] DONE in {metrics['wall_seconds']/60:.1f} min → {out_dir}",
          flush=True)


if __name__ == '__main__':
    main()
