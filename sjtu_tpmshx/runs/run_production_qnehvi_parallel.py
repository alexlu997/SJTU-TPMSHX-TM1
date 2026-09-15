"""run_production_qnehvi_parallel.py — Production v3 multi-seed BO.

12-core / 32 GB workstation configuration:
    M = 3 outer seeds × q_batch = 4 inner = 12 concurrent SIMPLE solves.
    OMP/MKL thread caps = 1 to prevent BLAS oversubscription.

Total evals: 3 × (32 init + 24 iter × 4 q_batch) = 3 × 128 = 384 evals.
Runtime depends on F2 convergence and the selected worker budget.

Usage:
    python -m sjtu_tpmshx.runs.run_production_qnehvi_parallel
    python -m sjtu_tpmshx.runs.run_production_qnehvi_parallel --seeds 4 --n_iter 30

Outputs (under opt_runs/production_v3_<timestamp>/):
    seed_NNN/                — per-seed BO checkpoint dirs (one per seed)
    pareto_merged.csv        — merged non-dominated front across seeds
    history_merged.csv       — concatenation of all evaluations
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional


def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--seeds',    type=int, default=3)
    p.add_argument('--n_init',   type=int, default=32)
    p.add_argument('--n_iter',   type=int, default=24)
    p.add_argument('--q_batch',  type=int, default=4)
    p.add_argument('--n_jobs',   type=int, default=4)
    p.add_argument('--save_dir', type=str, default=None)
    p.add_argument('--tol',      type=float, default=1e-2,
                   help='Retained compatibility value; does not set F2 tolerances')
    p.add_argument('--rho_loops', type=int, default=2,
                   help='Compressible Picard outer iterations')
    p.add_argument('--quiet',    action='store_true')
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)

    # Config for evaluator (per-design SIMPLE settings)
    config = {
        'tol_simple':       args.tol,
        'n_rho_loops':      args.rho_loops,
        'penalty_enabled':  True,
        # Operating point: leave defaults for Shanghai-like (DEFAULT_CONFIG)
    }

    save_dir = args.save_dir
    if save_dir is None:
        import time
        ts = time.strftime('%Y%m%d_%H%M%S')
        save_dir = str(Path('opt_runs') / f'production_v3_{ts}')

    # Spawn the orchestrator
    from sjtu_tpmshx.optimization.parallel_runner import run_qnehvi_multiseed

    out = run_qnehvi_multiseed(
        config=config,
        n_seeds=args.seeds,
        n_init=args.n_init,
        n_iter=args.n_iter,
        q_batch=args.q_batch,
        n_jobs_inner=args.n_jobs,
        save_dir_base=save_dir,
        hv_tol=0.01,
        hv_window=3,
        verbose=not args.quiet,
    )

    print("\n=== Production v3 SUMMARY ===")
    print(f"  save_dir:    {out['save_dir']}")
    print(f"  seeds_used:  {out['seeds_used']}")
    print(f"  n_evals:     {out['n_evals']}")
    print(f"  Pareto pts:  {len(out['X'])}")
    print(f"  wall_time:   {out['wall_time_s']:.0f} s "
          f"({out['wall_time_s']/60.0:.1f} min)")
    if len(out['X']) > 0:
        Q = -out['F'][:, 0]; dP = out['F'][:, 1]
        print(f"  Q range  [{Q.min():.0f}, {Q.max():.0f}] W/m")
        print(f"  dP range [{dP.min():.0f}, {dP.max():.0f}] Pa")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
