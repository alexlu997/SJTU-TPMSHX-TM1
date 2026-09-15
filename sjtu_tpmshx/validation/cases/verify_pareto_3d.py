"""
validation/verify_pareto_3d.py — Independent 3D verification of a 2D Pareto pick.

The continuous-field optimizer runs a 2D SIMPLE × 2 + LTNE pipeline that
returns Q_2D per unit HX depth (W/m) and dP_2D in Pa. This script takes one Pareto
solution, extrudes its L(x, y) and t(x, y) fields uniformly along z to fill
a 3D voxel grid, runs the full 3D solver stack
(SIMPLESolver3D + solve_full_domain_3d with outer ρ(T) coupling), and
reports::

    Q_3D vs Q_2D · Lz       — total heat transfer (W)
    dP_A_3D, dP_B_3D vs dP_2D
    Δ relative                — quantifies the 3D physics correction

Usage::

    python -m sjtu_tpmshx.validation.cases.verify_pareto_3d \\
        --pareto opt_runs/production_v1/pareto_final.csv \\
        --row    2 \\
        --Nx 40 --Ny 16 --Nz 16 \\
        --Lz 0.042

Defaults reuse the run's config.json so the 3D run sees the same
(tpms_type, L_domain, H_domain, fluid operating point) as the 2D
optimization. ``Lz`` defaults to 0.042 m (Shanghai depth), but is the only
parameter the 2D run cannot supply since the optimizer has no z dimension.

Solver path & fidelity (ledger C10, 2026-07-12)
-----------------------------------------------
This tool REPORTS numbers, so it must not run the BO screening profile.
Graded continuous-field designs cannot go through the production
``run_stack_3d`` (its zoned path is piecewise-constant ``zone_grid_cells``
— a different geometry parametrization that would silently change the
design being verified), so this script uses ``core.evaluators.evaluate_3d``
but at VERIFICATION grade:

  * ``convergence_mode='f2'`` — the honest three-gate criterion (ledger C7),
    same as the production pipeline default, instead of the screening
    'legacy' mode whose numbers the evaluator itself forbids quoting.
  * LTNE convective ρcp from SIMPLE's local ρ(P_local, T) (ledger C10 fix),
    matching the production ``variable_rho_cp`` physics.

Remaining, KNOWN gaps vs the production pipeline (ledger O2): fluid B is
solved once cold (frozen velocities, no var-ρ re-solve) and there is no
post-solve Mach/positive-pressure gate. The printout labels the path so
these numbers are never mistaken for production-pipeline output.

Exit codes
----------
0 — converged AND certified (full truth table PASS); numbers are reportable.
2 — INVALID operating point (choked, no steady solution; ledger C10).
3 — NOT CONVERGED (any of simple_A/B, LTNE-inner, outer, finite failed;
    codex review P0, 2026-07-13) — numbers printed but uncertified.
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings('ignore')

from sjtu_tpmshx.core.evaluators import (
    evaluate_3d,
)

def _load_pareto_row(pareto_csv: str, row_index: int,
                      decision_dim_expected: int = 16) -> tuple:
    data = np.loadtxt(pareto_csv, delimiter=',', skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if row_index < 0 or row_index >= data.shape[0]:
        raise IndexError(f"row {row_index} out of range [0, {data.shape[0]})")
    row = data[row_index]
    return (row[:decision_dim_expected],
            float(row[decision_dim_expected]),     # Q_2D [W/m]
            float(row[decision_dim_expected + 1])) # dP_2D [Pa]


def _load_run_cfg(pareto_csv: str) -> dict:
    cfg_path = Path(pareto_csv).parent / 'config.json'
    if cfg_path.exists():
        with open(cfg_path) as f:
            return json.load(f)
    return {}


# ─── CLI ────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='verify_pareto_3d',
        description='3D verification of a 2D Pareto pick.')
    p.add_argument('--pareto', required=True, help='pareto_final.csv path')
    p.add_argument('--row', type=int, default=0, help='Pareto row index')
    p.add_argument('--Nx', type=int, default=40)
    p.add_argument('--Ny', type=int, default=16)
    p.add_argument('--Nz', type=int, default=16)
    p.add_argument('--Lz', type=float, default=0.042,
                   help='HX depth in m (default Shanghai 42 mm)')
    p.add_argument('--cfg-override', default=None,
                   help='optional JSON dict to merge over cfg.json (e.g. '
                        '\'{"u_A": 5.0}\')')
    return p


def main(argv=None) -> int:
    args = _build_argparser().parse_args(argv)

    x_decision, Q_2D_W_per_m, dP_2D_Pa = _load_pareto_row(args.pareto, args.row)
    cfg = _load_run_cfg(args.pareto)
    if args.cfg_override:
        cfg.update(json.loads(args.cfg_override))

    print(f"=== 3D verification of Pareto row {args.row} ===")
    print(f"  source: {args.pareto}")
    print(f"  cfg   : tpms={cfg.get('tpms_type')}  L_dom={cfg.get('L_domain')}  "
          f"H_dom={cfg.get('H_domain')}  Lz={args.Lz}  "
          f"u_A={cfg.get('u_A')}  u_B={cfg.get('u_B')}")
    print(f"  2D    : Q = {Q_2D_W_per_m:.0f} W/m   dP = {dP_2D_Pa:.0f} Pa")
    print(f"  3D run: grid {args.Nx}×{args.Ny}×{args.Nz}\n")

    t0 = time.perf_counter()
    # f2 = verification grade (ledger C7/C10) — NOT the BO screening profile.
    # See the module docstring for why this evaluator (and not run_stack_3d)
    # and what gaps remain. max_outer=12 matches the production pipeline's
    # _MAX_OUTER — the screening default (3) is too tight for a tool that
    # GATES on outer convergence (codex review P0, 2026-07-13).
    out = evaluate_3d(x_decision, cfg,
                      Nx=args.Nx, Ny=args.Ny, Nz=args.Nz,
                      Lz=args.Lz,
                      max_outer=12,
                      convergence_mode='f2')
    dt = time.perf_counter() - t0
    if out.get('invalid'):
        # Strict-validation contract (core/evaluators.py): choked / infeasible
        # operating point → NaN + reason. A verification tool must surface
        # this, not print NaNs that look like numbers.
        print(f"\n=== INVALID operating point (3D wall {dt:.0f}s) ===")
        print(f"  {out.get('invalid_reason', '(no reason recorded)')}")
        return 2
    # Convergence truth table (codex review P0, 2026-07-13): an unconverged
    # run used to print here indistinguishably from a converged one and exit
    # 0. A verification tool must not report numbers it cannot certify.
    _gates = ('simple_A_converged', 'simple_B_converged',
              'ltne_inner_converged', 'outer_converged', 'finite')
    if not out.get('converged', False):
        print(f"\n=== NOT CONVERGED (3D wall {dt:.0f}s) — "
              "numbers below are NOT certified ===")
        for g in _gates:
            print(f"  {g:22s}: {'PASS' if out.get(g) else 'FAIL'}")
        print(f"  Q_3D_W={out['Q_3D_W']:.1f}  dP_A={out['dP_A_Pa']:.0f}  "
              f"dP_B={out['dP_B_Pa']:.0f}  (uncertified)")
        return 3
    print(f"\n=== Results (3D wall {dt:.0f}s) ===")
    print("  [conv] " + "  ".join(f"{g}=PASS" for g in _gates))
    print("  [path] core.evaluators.evaluate_3d @ convergence_mode='f2', "
          "local-ρ LTNE ρcp (ledger C10);")
    print("  [path] NOT the production run_stack_3d pipeline — fluid B frozen "
          "(cold single solve), no post-solve Mach gate (ledger O2).")
    Q_2D_W_total = Q_2D_W_per_m * args.Lz
    Q_3D = out['Q_3D_W']; dP_3D = out['dP_total_Pa']
    print(f"  Q_2D × Lz   = {Q_2D_W_total:8.1f} W   ({Q_2D_W_per_m:.0f} W/m × {args.Lz} m)")
    print(f"  Q_3D        = {Q_3D:8.1f} W")
    print(f"  ΔQ rel      = {(Q_3D - Q_2D_W_total)/Q_2D_W_total*100:+6.2f} %")
    print()
    print(f"  dP_2D       = {dP_2D_Pa:8.0f} Pa  (sum of A + B in 2D evaluator)")
    print(f"  dP_A_3D     = {out['dP_A_Pa']:8.0f} Pa")
    print(f"  dP_B_3D     = {out['dP_B_Pa']:8.0f} Pa")
    print(f"  dP_total_3D = {dP_3D:8.0f} Pa")
    print(f"  ΔdP rel     = {(dP_3D - dP_2D_Pa)/max(dP_2D_Pa,1)*100:+6.2f} %")
    print()
    print(f"  mass        = {out['mass_kg']:8.4f} kg")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
