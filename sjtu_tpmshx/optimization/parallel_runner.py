"""parallel_runner.py — Multi-seed qNEHVI orchestrator.

Runs M independent BO seeds concurrently, each using inner joblib q_batch
parallelism, and merges their Pareto fronts at the end.

Configuration (12-core / 32 GB workstation, user 2026-05-09 spec):
    M = 3 outer seeds × q_batch = 4 inner = 12 process total.
    OMP/MKL threads per process pinned to 1 to prevent BLAS oversubscription.

The outer parallelism uses concurrent.futures.ProcessPoolExecutor with
"spawn" start method so each subprocess gets a fresh interpreter (avoids
inheriting the parent's PyTorch / Numba state, which can deadlock on Windows).
The inner parallelism uses joblib loky inside `run_qnehvi` (see optimizer_qnehvi.py).

Public API:
    run_qnehvi_multiseed(...) -> dict   — same shape as run_qnehvi but with
                                          'seeds_used' and 'per_seed_results'

CLI:
    python -m sjtu_tpmshx.optimization.parallel_runner  # default 3-seed smoke
    python -m sjtu_tpmshx.optimization.parallel_runner --seeds 4 --n_init 32 --n_iter 24

Implementation note:
    Multi-seed BO is a "trivial parallel" pattern: each seed's BO loop is
    a self-contained sequence (Sobol → fit GP → acquire → eval → update),
    independent of every other seed's iterations. Merging at the end takes
    the union of all observed (X, F) and runs `_pareto_mask_max` once.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Optional

import numpy as np

from sjtu_tpmshx.logutil import get_logger
from sjtu_tpmshx.optimization._thread_caps import set_worker_thread_caps

_log = get_logger(__name__)


def _seed_subprocess_main(seed: int,
                          config: Optional[dict],
                          n_init: int,
                          n_iter: int,
                          q_batch: int,
                          n_jobs_inner: int,
                          save_dir_base: str,
                          hv_tol: float,
                          hv_window: int,
                          verbose: bool) -> dict:
    """Worker entry point for one BO seed.

    Runs in its own process (spawn start method). Sets thread caps before
    importing optimizer_qnehvi to keep MKL from launching N threads per
    process which would oversubscribe the 12-core budget.
    """
    set_worker_thread_caps()
    # Heavy import deferred until after thread caps are set
    from sjtu_tpmshx.optimization.optimizer_qnehvi import run_qnehvi

    save_dir = os.path.join(save_dir_base, f"seed_{seed:03d}")
    os.makedirs(save_dir, exist_ok=True)

    out = run_qnehvi(
        config=config,
        n_init=n_init,
        n_iter=n_iter,
        q_batch=q_batch,
        seed=seed,
        verbose=verbose,
        save_dir=save_dir,
        hv_tol=hv_tol,
        hv_window=hv_window,
        n_jobs=n_jobs_inner,
    )
    return {
        'seed':       int(seed),
        'X':          out['X'],
        'F':          out['F'],
        'history_X':  out['history_X'],
        'history_F':  out['history_F'],
        'history_errors': out['history_errors'],
        'n_evals':    int(out['n_evals']),
        'save_dir':   out['save_dir'],
        'config': out['config'],
        'termination_reason': out['termination_reason'],
    }


def _merge_paretos(seed_outputs: List[dict]) -> tuple:
    """Concatenate per-seed Pareto fronts and extract the global non-dominated
    front (in the (-Q, dP) min-form representation each seed already returns).

    Returns
    -------
    (X_merged, F_merged_min, X_history, F_history_min, n_evals_total)
    """
    from sjtu_tpmshx.optimization.optimizer_qnehvi import _pareto_mask_max

    X_paretos = [o['X'] for o in seed_outputs]
    F_paretos = [o['F'] for o in seed_outputs]
    X_hists   = [o['history_X'] for o in seed_outputs]
    F_hists   = [o['history_F'] for o in seed_outputs]
    n_evals_total = sum(int(o['n_evals']) for o in seed_outputs)

    if not X_paretos:
        return (np.zeros((0, 1)), np.zeros((0, 2)),
                np.zeros((0, 1)), np.zeros((0, 2)), n_evals_total)

    X_all = np.vstack(X_paretos)
    F_all = np.vstack(F_paretos)

    # Convert min-form (-Q, dP) → max-form (Q, -log10(dP)) for the mask, then
    # back. Using log10 keeps the same dominance ordering used inside qNEHVI.
    Q = -F_all[:, 0]
    log_dP = np.log10(np.maximum(F_all[:, 1], 1.0))
    Y_max = np.column_stack([Q, -log_dP])
    mask = _pareto_mask_max(Y_max)

    X_merged = X_all[mask]
    F_merged_min = F_all[mask]

    X_history = np.vstack(X_hists)
    F_history = np.vstack(F_hists)

    return X_merged, F_merged_min, X_history, F_history, n_evals_total


def run_qnehvi_multiseed(config: Optional[dict] = None,
                         n_seeds: int = 3,
                         seeds: Optional[List[int]] = None,
                         n_init: int = 32,
                         n_iter: int = 24,
                         q_batch: int = 4,
                         n_jobs_inner: int = 4,
                         save_dir_base: Optional[str] = None,
                         hv_tol: float = 0.01,
                         hv_window: int = 3,
                         verbose: bool = True) -> dict:
    """Run M independent BO seeds in parallel and merge Pareto fronts.

    Parameters
    ----------
    config         passed to each ``run_qnehvi`` call.
    n_seeds        number of outer-parallel BO seeds (M). Default 3 for the
                   12-core workstation budget (M=3 × q_batch=4).
    seeds          explicit seed list; defaults to [42, 43, ..., 42+n_seeds-1].
    n_init, n_iter, q_batch, hv_tol, hv_window  forwarded to run_qnehvi.
    n_jobs_inner   joblib workers inside each BO seed (default q_batch=4).
    save_dir_base  directory under which `seed_NNN/` per-seed checkpoint
                   directories are created. Auto-named if None.

    Returns
    -------
    dict
        'X', 'F', 'history_X', 'history_F', 'n_evals'  – merged across seeds
        'seeds_used'        – list of seeds actually run
        'per_seed_results'  – list of dicts, one per seed (bare results)
        'wall_time_s'       – total wall time for the orchestrated run
        'save_dir'          – save_dir_base
    """
    if seeds is None:
        seeds = [42 + i for i in range(n_seeds)]
    else:
        n_seeds = len(seeds)
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError('Specify at least one seed, with no duplicate seeds')

    from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
    from sjtu_tpmshx.models.continuous_field import decision_dim
    config = {**DEFAULT_CONFIG, **(config or {})}
    dimension = decision_dim(config['n_ctrl_x'], config['n_ctrl_y'], config['symmetric_y'])

    if save_dir_base is None:
        save_dir_base = f"opt_qnehvi_multiseed_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(save_dir_base, exist_ok=True)
    with open(os.path.join(save_dir_base, 'config.json'), 'w', encoding='utf-8') as target:
        json.dump(config, target, indent=2)

    if verbose:
        _log.info(f"[multiseed] {n_seeds} seeds × q_batch={q_batch} inner = "
                  f"{n_seeds * q_batch} concurrent SIMPLE solves")
        _log.info(f"[multiseed] save_dir_base = {save_dir_base}")
        _log.info(f"[multiseed] seeds = {seeds}")

    t0 = time.perf_counter()

    # Use spawn so each subprocess starts cold (no inherited PyTorch / Numba
    # state). Default fork on Linux works too but spawn is portable + safer
    # under nested loky workers.
    import multiprocessing as mp
    ctx = mp.get_context('spawn')

    per_seed_results: List[dict] = []
    failed_seeds = {}
    # initializer from the LIGHT module: unpickling it imports os only, so
    # the caps land BEFORE the child's numpy/numba load (candidate C fix —
    # see optimization/_thread_caps.py for the spawn-timing rationale).
    with ProcessPoolExecutor(max_workers=n_seeds, mp_context=ctx,
                             initializer=set_worker_thread_caps) as ex:
        futs = {
            ex.submit(_seed_subprocess_main,
                      seed, config, n_init, n_iter, q_batch,
                      n_jobs_inner, save_dir_base,
                      hv_tol, hv_window, verbose): seed
            for seed in seeds
        }
        for fut in as_completed(futs):
            try:
                result = fut.result()
                per_seed_results.append(result)
                if result['termination_reason'] not in ('completed', 'plateau') or not len(result['X']):
                    failed_seeds[futs[fut]] = (result['termination_reason'] if len(result['X'])
                                              else 'no valid Pareto solutions')
            except Exception as e:
                failed_seeds[futs[fut]] = repr(e)
                _log.warning(f"[multiseed] seed worker FAILED: {e!r}")

    wall = time.perf_counter() - t0

    X_m, F_m, X_h, F_h, n_evals_total = _merge_paretos(per_seed_results)
    if not per_seed_results:
        X_m = np.empty((0, dimension))
        X_h = np.empty((0, dimension))
    status = dict(seeds_requested=list(seeds),
                  seeds_used=[result['seed'] for result in per_seed_results],
                  failed_seeds=failed_seeds, complete=not failed_seeds)
    with open(os.path.join(save_dir_base, 'multiseed_status.json'), 'w', encoding='utf-8') as target:
        json.dump(status, target, indent=2)

    if verbose:
        _log.info(f"\n[multiseed] DONE in {wall:.0f}s")
        _log.info("  per-seed: " + " ".join(
            f"seed{r['seed']}={len(r['X'])}P/{r['n_evals']}E"
            for r in per_seed_results))
        _log.info(f"  merged Pareto: {len(X_m)} points across "
                  f"{n_evals_total} total evals")
        if len(X_m) > 0:
            Q = -F_m[:, 0]; dP = F_m[:, 1]
            _log.info(f"  Q range  [{Q.min():.0f}, {Q.max():.0f}] W/m")
            _log.info(f"  dP range [{dP.min():.0f}, {dP.max():.0f}] Pa")

    # Write merged Pareto + history at top level
    from sjtu_tpmshx.optimization.optimizer_qnehvi import _save_pareto_csv, _save_history
    history_errors = [error for output in per_seed_results for error in output['history_errors']]
    _save_pareto_csv(os.path.join(save_dir_base, 'pareto_merged.csv'), X_m, F_m)
    _save_history(save_dir_base, X_h, F_h, history_errors, stem='history_merged')

    return {
        'X':                 X_m,
        'F':                 F_m,
        'history_X':         X_h,
        'history_F':         F_h,
        'history_errors':    history_errors,
        'n_evals':           n_evals_total,
        **status,
        'config':           config,
        'per_seed_results':  per_seed_results,
        'wall_time_s':       wall,
        'save_dir':          save_dir_base,
    }


# ─── CLI ────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Multi-seed qNEHVI orchestrator (3 outer × 4 inner = 12 proc)")
    p.add_argument('--seeds',    type=int, default=3, help='Number of seeds')
    p.add_argument('--n_init',   type=int, default=32)
    p.add_argument('--n_iter',   type=int, default=24)
    p.add_argument('--q_batch',  type=int, default=4)
    p.add_argument('--n_jobs',   type=int, default=4,
                   help='joblib inner workers per seed')
    p.add_argument('--save_dir', type=str, default=None)
    p.add_argument('--hv_tol',   type=float, default=0.01)
    p.add_argument('--quiet',    action='store_true')
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    out = run_qnehvi_multiseed(
        n_seeds=args.seeds,
        n_init=args.n_init,
        n_iter=args.n_iter,
        q_batch=args.q_batch,
        n_jobs_inner=args.n_jobs,
        save_dir_base=args.save_dir,
        hv_tol=args.hv_tol,
        verbose=not args.quiet,
    )
    print(f"\nMerged: {len(out['X'])} Pareto points / {out['n_evals']} evals "
          f"in {out['wall_time_s']:.0f}s")
    return 0 if out['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
