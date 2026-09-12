"""
Profile a single evaluate_design call (BO inner-loop hot path).

Run::

    python -m benchmarks.profiling.profile_evaluator

Outputs:
  - benchmarks/profiling/eval_baseline.prof (pstats binary)
  - benchmarks/profiling/eval_baseline_top30.txt (text top-30 cumulative)
  - benchmarks/profiling/eval_baseline_callees.txt (callee tree top-20)

Methodology:
  * Single 16-D decision vector at the fixed historical nominal geometry → "nominal design"
  * Uniform L = 6 mm, t = 0.4 mm (fixed historical workload)
  * Air/air screening domain 0.10 × 0.05 m, adaptive grid
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
from sjtu_tpmshx.models.screening import build_field

OUT_DIR = Path(__file__).parent
N_REPEAT = 3


def _build_nominal_x() -> np.ndarray:
    """Preserve the historical 16-D L=6 mm, t=0.4 mm workload."""
    return np.r_[np.full(8, 6.), np.full(8, .4)]


def _build_cfg() -> dict:
    return {**DEFAULT_CONFIG, 'tol_simple': 1e-2, 'n_rho_loops': 2,
            'penalty_enabled': False}


def profile_workload(cfg, prefix, *, repeats, wall_repeats, callees):
    """Shared execution/reporting; each entry retains its own workload."""
    x_nom = _build_nominal_x()
    fc = build_field(x_nom, cfg)
    print(f"[profile-{prefix}] warm-up ...", flush=True)
    started = time.perf_counter()
    Q_neg, dP, _ = evaluate_design(x_nom, cfg, fc)
    print(f"  warm-up: Q={-Q_neg:.1f}, dP={dP:.1f}, t={time.perf_counter()-started:.2f}s", flush=True)
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(repeats):
        Q_neg, dP, _ = evaluate_design(x_nom, cfg, fc)
    profiler.disable()
    print(f"  result: Q={-Q_neg:.1f}, dP={dP:.1f}", flush=True)
    if wall_repeats:
        started = time.perf_counter()
        for _ in range(wall_repeats):
            evaluate_design(x_nom, cfg, fc)
        print(f"  avg wall per call: {(time.perf_counter()-started)/wall_repeats:.2f}s", flush=True)
    stem = OUT_DIR / f'{prefix}_baseline'
    profiler.dump_stats(str(stem) + '.prof')
    for suffix, sort, count in [('top30', 'cumulative', 30),
                                 ('tottime', 'tottime', 20),
                                 ('callees', 'cumulative', 5)]:
        buffer = io.StringIO()
        stats = pstats.Stats(profiler, stream=buffer).sort_stats(sort)
        stats.print_stats(count)
        if suffix == 'callees':
            stats.print_callees(callees)
        Path(f'{stem}_{suffix}.txt').write_text(buffer.getvalue(), encoding='utf-8')
        if suffix == 'tottime':
            print(buffer.getvalue())


def main() -> None:
    profile_workload(_build_cfg(), 'eval', repeats=N_REPEAT,
                     wall_repeats=N_REPEAT, callees=5)


if __name__ == '__main__':
    main()
