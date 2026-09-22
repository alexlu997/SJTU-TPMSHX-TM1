"""
runs/run_production_qnehvi.py — Production-grade Pareto run.

Settings vs the smoke (`python -m sjtu_tpmshx.optimization.optimizer_qnehvi`):
  * n_init   16 → 32  (≈ 2 × decision_dim, escapes Sobol-init basin)
  * n_iter    8 → 24  (BO has room to converge before HV plateau early-stop)
  * n_rho_loops uses the new DEFAULT (3) → compressible ρ(T) coupling on
  * screening uses the shared F2 convergence gates

Historical timing estimates predate F2 screening; measure this workload
again before assigning a current runtime budget.

Outputs in opt_runs/production_v1/:
  pareto_final.csv     Pareto-only decisions + (Q, dP)
  history.csv          every evaluated point
  pareto_iterNNNN.csv  per-5-iter checkpoints
  config.json          serialized cfg
"""

from __future__ import annotations

import os
import warnings

from sjtu_tpmshx.optimization.optimizer_qnehvi import run_qnehvi


def main() -> None:
    warnings.filterwarnings('ignore')

    out = run_qnehvi(
        config={
            'fast_mode':           False,
            # Solver knobs
            'max_iter_simple':     800,
            'max_iter_energy':     1500,
            'tol_energy':          0.5,
            # Compressibility (D feature) — 3 outer iterations + 1 % Δρ tol
            'n_rho_loops':         3,
            'drho_tol':            0.01,
            'rho_relax':           0.7,
            # Production hardening
            'dp_cap_pa':           1.0e6,
            'reject_unconverged':  False,
            'penalty_enabled':     True,
        },
        n_init=32, n_iter=24, q_batch=2, seed=42,
        verbose=True,
        save_dir=os.path.join('opt_runs', 'production_v1'),
        hv_tol=0.01, hv_window=3,
    )
    print(f"\nProduction run complete: {len(out['X'])} Pareto points / "
          f"{out['n_evals']} total evaluations")
    print(f"  save_dir = {out['save_dir']}")


if __name__ == '__main__':
    main()
