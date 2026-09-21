"""runs/run_3d_qnehvi_fast.py — qNEHVI Pareto run on the 3D evaluator.

Wires ``optimization.evaluator_3d.evaluate_design_3d`` into the existing
qNEHVI loop via the new ``evaluator_fn`` injection. Configuration matches
the Shanghai Nz=10 validation baseline so the Pareto sits in the same
operating regime as the published 3D real-data sweep.

Smoke-timed at 13 s / eval on the workstation (12-core, fast-mode SIMPLE
tolerances). At n_init=32 + n_iter=80 × q_batch=2 = 192 evals, expect
~ 25 min compute + GP overhead ≈ 50–70 min wall.

Outputs in opt_runs/qnehvi_3d_<ts>/:
  pareto_final.csv     Pareto-only decisions + (Q_per_m, dP)
  history.csv          all evals
  pareto_iterNNNN.csv  per-5-iter checkpoints
  config.json          serialized cfg
"""

from __future__ import annotations

import os
import time
import warnings

from sjtu_tpmshx.optimization.evaluator_3d import (
    DEFAULT_CONFIG_3D,
    evaluate_design_3d,
)
from sjtu_tpmshx.optimization.optimizer_qnehvi import run_qnehvi


def main() -> None:
    warnings.filterwarnings('ignore')

    cfg = {
        **DEFAULT_CONFIG_3D,

        # Geometry — Shanghai HX (validate_shanghai_3d_real defaults)
        'tpms_type':  'Gyroid',
        'L_domain':   0.182,    # m  (fluid A streamwise)
        'H_domain':   0.042,    # m  (fluid B streamwise)
        'Lz':         0.042,    # m  (HX depth)

        # Operating point — mid-Re Shanghai case (within validate range)
        'u_A':        10.0,
        'u_B':        5.0,
        'T_inA':      400.0,
        'T_inB':      300.0,
        'P_inA':      101325.0,
        'P_inB':      101325.0,

        # 3D production grid (matches Shanghai Nz=10 validation)
        'Nx_3d':      40,
        'Ny_3d':      16,
        'Nz_3d':      10,
        'max_outer_3d': 3,
        'outer_tol_K':  0.5,
        'alpha_outer':  0.6,

        # Solver tols (3D fast-mode within evaluator)
        'max_iter_simple': 500,
        'tol_simple':      1e-2,
        'max_iter_energy': 1500,
        'tol_energy':      0.5,
        # Outer ρ via 3D evaluator's max_outer_3d, not 2D n_rho_loops
        'n_rho_loops':     1,

        # BO hardening (same as 2D production)
        'dp_cap_pa':           1.0e6,
        'reject_unconverged':  False,
        'penalty_enabled':     True,

        # 2026-05-14 (revised): norris_1a is alias of baseline for friction.
        # ×1.28 Nu in tpms_calc is the only roughness compensation; c_F is
        # already SLM-fit, so any f-side multiplier double-counts. See
        # models/roughness.py docstring.
        'roughness_mode':      'norris_1a',
        'roughness_eps_um':    100.0,
    }

    save_dir = os.path.join('opt_runs',
                             f"qnehvi_3d_{time.strftime('%Y%m%d_%H%M%S')}")

    print(f"[run_3d_qnehvi_fast] save_dir = {save_dir}", flush=True)
    print(f"[run_3d_qnehvi_fast] grid=({cfg['Nx_3d']},{cfg['Ny_3d']},"
          f"{cfg['Nz_3d']})  Lz={cfg['Lz']}  max_outer={cfg['max_outer_3d']}",
          flush=True)

    out = run_qnehvi(
        config=cfg,
        n_init=32, n_iter=80, q_batch=2, seed=42,
        verbose=True,
        save_dir=save_dir,
        hv_tol=0.01, hv_window=3,
        n_jobs=2,
        evaluator_fn=evaluate_design_3d,
    )

    print(f"\n[run_3d_qnehvi_fast] DONE — {len(out['X'])} Pareto points / "
          f"{out['n_evals']} evals", flush=True)
    print(f"  save_dir = {out['save_dir']}", flush=True)


if __name__ == '__main__':
    main()
