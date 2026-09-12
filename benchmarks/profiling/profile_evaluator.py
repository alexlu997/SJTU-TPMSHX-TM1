"""
Profile a single evaluate_design call (BO inner-loop hot path).

Run::

    python -m benchmarks.profiling.profile_evaluator

Outputs:
  - benchmarks/profiling/eval_baseline.prof (pstats binary)
  - benchmarks/profiling/eval_baseline_top30.txt (text top-30 cumulative)
  - benchmarks/profiling/eval_baseline_callees.txt (callee tree top-20)

Methodology:
  * Single 16-D decision vector at the centre of the bounds → "nominal design"
  * Uniform L = 6 mm, t = 0.4 mm (mid of training window)
  * Shanghai air-water-like grid resolution (Nx=Ny=adaptive)
  * tol_simple loose (1e-2) to mimic BO inner; n_rho_loops=2 (single Picard)
  * One warm-up, three profiled calls, then three wall-time calls
"""

from __future__ import annotations

import cProfile
import pstats
import io
import time
from pathlib import Path

import numpy as np

from sjtu_tpmshx.optimization.evaluator import evaluate_design, DEFAULT_CONFIG
from sjtu_tpmshx.models.continuous_field import (
    from_decision_vector,
    decision_bounds,
    DEFAULT_N_CTRL_X,
    DEFAULT_N_CTRL_Y,
    DEFAULT_SYMMETRIC_Y,
    DEFAULT_L_BOUNDS,
    DEFAULT_T_BOUNDS,
)


OUT_DIR = Path(__file__).parent
N_REPEAT = 3
SEED = 42


def _build_nominal_x() -> np.ndarray:
    """Decision vector at centre of bounds (uniform L=6 mm, t=0.4 mm)."""
    lb, ub = decision_bounds(
        n_ctrl_x=DEFAULT_N_CTRL_X,
        n_ctrl_y=DEFAULT_N_CTRL_Y,
        symmetric_y=DEFAULT_SYMMETRIC_Y,
        L_bounds=DEFAULT_L_BOUNDS,
        t_bounds=DEFAULT_T_BOUNDS,
    )
    return 0.5 * (lb + ub)


def _build_cfg() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    # BO inner loop preset
    cfg['tol_simple']  = 1e-2
    cfg['n_rho_loops'] = 2
    cfg['penalty_enabled'] = False
    return cfg


def main() -> None:
    cfg = _build_cfg()
    fc = from_decision_vector(
        x=_build_nominal_x(),
        tpms_type=cfg['tpms_type'],
        k_s=cfg['k_s'],
        L_domain=cfg['L_domain'],
        H_domain=cfg['H_domain'],
        n_ctrl_x=cfg['n_ctrl_x'],
        n_ctrl_y=cfg['n_ctrl_y'],
        symmetric_y=cfg['symmetric_y'],
        L_bounds=cfg['L_bounds'],
        t_bounds=cfg['t_bounds'],
    )
    x_nom = _build_nominal_x()

    # Warm-up (JIT, cache fills)
    print("[profile] warm-up call ...", flush=True)
    t0 = time.perf_counter()
    Q_neg, dP, mass = evaluate_design(x_nom, cfg, fc)
    t_warm = time.perf_counter() - t0
    print(f"  warm-up: Q={-Q_neg:.1f}, dP={dP:.1f}, t={t_warm:.2f}s",
          flush=True)

    pr = cProfile.Profile()
    pr.enable()
    for k in range(N_REPEAT):
        Q_neg, dP, mass = evaluate_design(x_nom, cfg, fc)
    pr.disable()

    # Per-call wall summary (separate from cProfile self timing)
    t1 = time.perf_counter()
    for k in range(N_REPEAT):
        evaluate_design(x_nom, cfg, fc)
    t_avg = (time.perf_counter() - t1) / N_REPEAT
    print(f"\n[profile] avg wall per call (post-warm): {t_avg:.2f}s",
          flush=True)

    prof_path = OUT_DIR / "eval_baseline.prof"
    pr.dump_stats(str(prof_path))

    # Top 30 cumulative
    buf = io.StringIO()
    ps = pstats.Stats(pr, stream=buf).sort_stats('cumulative')
    ps.print_stats(30)
    top30 = buf.getvalue()

    # Top callees on the worst 5 by cumulative time
    buf2 = io.StringIO()
    ps2 = pstats.Stats(pr, stream=buf2).sort_stats('cumulative')
    ps2.print_stats(5)
    ps2.print_callees(5)
    callees = buf2.getvalue()

    # Top 20 by tottime (self time, excludes children)
    buf3 = io.StringIO()
    ps3 = pstats.Stats(pr, stream=buf3).sort_stats('tottime')
    ps3.print_stats(20)
    tottime = buf3.getvalue()

    (OUT_DIR / "eval_baseline_top30.txt").write_text(top30, encoding='utf-8')
    (OUT_DIR / "eval_baseline_callees.txt").write_text(
        callees, encoding='utf-8')
    (OUT_DIR / "eval_baseline_tottime.txt").write_text(
        tottime, encoding='utf-8')

    print("\n[profile] wrote:")
    print(f"  {prof_path}")
    print(f"  {OUT_DIR/'eval_baseline_top30.txt'}")
    print(f"  {OUT_DIR/'eval_baseline_tottime.txt'}")
    print(f"  {OUT_DIR/'eval_baseline_callees.txt'}")
    print("\n[profile] === TOP 20 BY SELF TIME ===")
    print(tottime)


if __name__ == "__main__":
    main()
