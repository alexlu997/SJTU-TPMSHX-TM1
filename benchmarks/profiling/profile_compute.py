"""
Profile the historical tighter-tolerance 2D screening workload.

Run::

    python -m benchmarks.profiling.profile_compute

Outputs (benchmarks/profiling/):
  - compute_baseline.prof
  - compute_baseline_top30.txt
  - compute_baseline_tottime.txt
  - compute_baseline_callees.txt

Uses optimization.evaluator.evaluate_design through the public screening mode.
The historical filename does not imply a GUI/full-model profile. Workload:
  * Shanghai geometry: L=0.182, H=0.042 m
  * Fluid pair and remaining settings from evaluator.DEFAULT_CONFIG
  * tol_simple = 1e-3 (production), n_rho_loops = 3 (compressible)
  * Uniform L=6 mm, t=0.4 mm (centre of bounds)
  * One warm-up, then one profiled call
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


def _build_nominal_x() -> np.ndarray:
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
    # Shanghai geometry
    cfg['L_domain'] = 0.182
    cfg['H_domain'] = 0.042
    # Production tol (UI default)
    cfg['tol_simple']  = 1e-3
    cfg['n_rho_loops'] = 3
    cfg['penalty_enabled'] = True
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

    print("[profile-compute] warm-up ...", flush=True)
    t0 = time.perf_counter()
    Q_neg, dP, mass = evaluate_design(x_nom, cfg, fc)
    print(f"  warm-up: Q={-Q_neg:.1f}, dP={dP:.1f}, t={time.perf_counter()-t0:.2f}s",
          flush=True)

    print("[profile-compute] profiling ...", flush=True)
    pr = cProfile.Profile()
    pr.enable()
    Q_neg, dP, mass = evaluate_design(x_nom, cfg, fc)
    pr.disable()
    print(f"  result: Q={-Q_neg:.1f}, dP={dP:.1f}", flush=True)

    prof_path = OUT_DIR / "compute_baseline.prof"
    pr.dump_stats(str(prof_path))

    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats('cumulative').print_stats(30)
    (OUT_DIR / "compute_baseline_top30.txt").write_text(
        buf.getvalue(), encoding='utf-8')

    buf2 = io.StringIO()
    pstats.Stats(pr, stream=buf2).sort_stats('tottime').print_stats(20)
    tottime = buf2.getvalue()
    (OUT_DIR / "compute_baseline_tottime.txt").write_text(
        tottime, encoding='utf-8')

    buf3 = io.StringIO()
    ps = pstats.Stats(pr, stream=buf3).sort_stats('cumulative')
    ps.print_stats(5)
    ps.print_callees(8)
    (OUT_DIR / "compute_baseline_callees.txt").write_text(
        buf3.getvalue(), encoding='utf-8')

    print("\n[profile-compute] === TOP 20 BY SELF TIME ===")
    print(tottime)


if __name__ == "__main__":
    main()
