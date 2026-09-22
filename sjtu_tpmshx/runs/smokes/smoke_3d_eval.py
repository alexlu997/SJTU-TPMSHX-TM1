"""Time one 3D design evaluation to estimate a serial BO budget.

Times evaluate_design_3d near the midpoint of the search bounds, with
Nx=40, Ny=16, Nz=10 and max_outer=3. The measured time includes this run's
compilation/cache state. The serial estimate excludes GP overhead and cannot
predict parallel speedup or certify convergence of the screening result.

Usage::
    python -u -m sjtu_tpmshx.runs.smokes.smoke_3d_eval
"""

from __future__ import annotations

import time
import warnings

import numpy as np

from sjtu_tpmshx.optimization.evaluator_3d import (
    DEFAULT_CONFIG_3D,
    evaluate_design_3d,
)
from sjtu_tpmshx.models.continuous_field import (
    decision_dim,
    decision_bounds,
)


def main() -> None:
    warnings.filterwarnings('ignore')

    cfg = {**DEFAULT_CONFIG_3D,
           'tpms_type': 'Gyroid',
           'u_A': 12.0, 'u_B': 8.0,
           'T_inA': 422.0, 'T_inB': 302.0,
           'P_inA': 101325.0, 'P_inB': 101325.0,
           'L_domain': 0.182, 'H_domain': 0.042,
           'Lz': 0.042,
           # Bounded 3D screening preset; not a full-compute qualification.
           'Nx_3d': 40, 'Ny_3d': 16, 'Nz_3d': 10,
           'max_outer_3d': 3,
           'max_iter_simple': 500, 'tol_simple': 1e-2,
           'max_iter_energy': 1500, 'tol_energy': 0.5,
           'n_rho_loops': 1,           # outer ρ done by 3D evaluator's max_outer
           }

    D = decision_dim(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'])
    lb, ub = decision_bounds(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'],
                              L_bounds=cfg['L_bounds'], t_bounds=cfg['t_bounds'])
    rng = np.random.default_rng(0)
    x_mid = lb + 0.5 * (ub - lb) + 0.05 * (ub - lb) * rng.standard_normal(D)
    x_mid = np.clip(x_mid, lb, ub)

    print(f"[smoke3D] D={D}  cfg.tpms={cfg['tpms_type']}  grid=({cfg['Nx_3d']},"
          f"{cfg['Ny_3d']},{cfg['Nz_3d']})  Lz={cfg['Lz']}  max_outer="
          f"{cfg['max_outer_3d']}", flush=True)
    print(f"[smoke3D] u_A={cfg['u_A']}  u_B={cfg['u_B']}  "
          f"T_inA={cfg['T_inA']}  T_inB={cfg['T_inB']}", flush=True)

    t0 = time.perf_counter()
    Q_neg, dP, mass = evaluate_design_3d(x_mid, cfg)
    wall = time.perf_counter() - t0

    print(f"\n[smoke3D] DONE in {wall:.1f}s "
          f"({wall/60:.2f} min)", flush=True)
    print(f"[smoke3D] Q_per_m  = {-Q_neg:.0f} W/m"
          f"   (Q_total = {-Q_neg * cfg['Lz']:.1f} W)", flush=True)
    print(f"[smoke3D] dP_total = {dP:.0f} Pa", flush=True)
    print(f"[smoke3D] mass     = {mass:.3f} kg/m", flush=True)

    n_init, n_iter, q = 24, 40, 2
    n_evals = n_init + n_iter * q
    est_serial = wall * n_evals / 3600.0
    print(f"\n[smoke3D] Serial compute estimate ({n_evals} evals at {wall:.0f}s/eval):"
          f" {est_serial:.1f} h; excludes GP overhead and parallel speedup.", flush=True)


if __name__ == '__main__':
    main()
