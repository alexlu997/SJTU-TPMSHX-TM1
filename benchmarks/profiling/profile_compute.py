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
  * tol_simple = 1e-3, n_rho_loops = 3 (compressible)
  * Uniform L=6 mm, t=0.4 mm (fixed historical workload)
  * One warm-up, then one profiled call
"""

from __future__ import annotations

from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG
from benchmarks.profiling.profile_evaluator import profile_workload


def _build_cfg() -> dict:
    return {**DEFAULT_CONFIG, 'L_domain': .182, 'H_domain': .042,
            'tol_simple': 1e-3, 'n_rho_loops': 3, 'penalty_enabled': True}


def main() -> None:
    profile_workload(_build_cfg(), 'compute', repeats=1, wall_repeats=0, callees=8)


if __name__ == '__main__':
    main()
