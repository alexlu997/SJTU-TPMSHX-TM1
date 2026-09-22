"""Validate the 16 Shanghai water-air cases through the current Pipeline3D.

Both fluids are solved using confirmed staggered water ports and measured
mass-flow inputs. With no explicit grid, the port/wall mesh is used; output
counts come from the prepared result. Full membership, finite errors,
convergence, final pressure validity and the existing 12%/6% RMSRE gates
remain separate requirements.

The frozen-water kernel and its D76 pressure-validation consumer are retired.
Their source, scores and original thresholds remain at Git a32b975638aaa7df0ab154e438b40130c4df4906 and in
historical references. New outputs never overwrite the tracked CSV oracle.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.harness._harness import load_cases_df
from sjtu_tpmshx.validation.harness._case_sets import (
    shanghai_spec, SHANGHAI_XLSX, SHANGHAI_N_CASES,
)
from sjtu_tpmshx.validation.harness._provenance import (
    output_directory, output_path, write_csv_with_provenance,
)

MAX_OUTER = 12

def _pipeline_config(ci, df, Nx_u, Ny_u, Nz_u, max_outer=None, wall_refine=False,
                     port_wall_refine=False):
    from sjtu_tpmshx.domain.compute_config import SolverConfig
    from sjtu_tpmshx.validation.harness._case_sets import shanghai_pipeline_config
    return shanghai_pipeline_config(ci, df,
        SolverConfig(Nx=Nx_u, Ny=Ny_u, Nz=Nz_u,
                     max_outer_ltne=None if max_outer is None else int(max_outer)),
        wall_refine=wall_refine, port_wall_refine=port_wall_refine)


def _run_one_case_pipeline(ci, df, Nx_u, Ny_u, Nz_u,
                           max_outer=None, wall_refine=False, port_wall_refine=False):
    """Solve both fluids through the same production pipeline as the GUI."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
    cc = _pipeline_config(ci, df, Nx_u, Ny_u, Nz_u, max_outer, wall_refine,
                          port_wall_refine)
    case = ci + 1
    u_A, u_B = cc.fluid_A.u_mps, cc.fluid_B.u_mps
    dP_A_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])
    Q_exp = float(df.iloc[ci, 33])
    result = Pipeline3D(cc).run()
    dP_sim = result.dP_A_Pa
    Q_sim = result.Q_W
    err_dP = ((dP_sim - dP_A_exp) / dP_A_exp * 100
              if dP_A_exp != 0 else float('nan'))
    err_Q = (Q_sim - Q_exp) / Q_exp * 100 if Q_exp != 0 else float('nan')
    # Final envelope validity and lifetime clipping count have different
    # meanings: an intermediate clip does not itself fail a recovered result.
    _diag = result.diagnostics or {}
    _env_valid = bool(_diag.get('envelope_valid', True))
    _clip_hits = int(_diag.get('p_clip_hits', 0))
    # Report actual iterations, not the configured cap.
    _cdet = _diag.get('convergence_detail') or {}
    _outer_done = int(_cdet.get('outer_iters', 0)) or -1
    _outer_conv = bool(_cdet.get('outer_converged', False))
    if result.warnings:
        print(f"  [case {case}] pipeline warnings: "
              f"{'; '.join(str(w) for w in result.warnings)}")
    return {
        'case': case, 'u_air': u_A, 'u_water': u_B,
        'dP_exp': dP_A_exp, 'dP_sim': dP_sim, 'err_dP%': err_dP,
        'Q_exp': Q_exp, 'Q_sim': Q_sim, 'err_Q%': err_Q,
        'Q_native': float(result.Q_W), 'Q_native_unit': 'W',
        **{'grid_n' + axis: len(result.fields['d' + axis]) for axis in 'xyz'},
        'outer_iters': _outer_done,
        'outer_converged': _outer_conv,
        'converged': bool(result.converged),
        'pressure_clip_hits': _clip_hits,
        'pressure_state_valid': int(_env_valid),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--wall-refine', action='store_true', help='Enable 6-wall refinement')
    ap.add_argument('--port-wall-refine', action='store_true',
                    help='Use port/wall grading; counts include all refinement cells')
    ap.add_argument('--nx', type=int)
    ap.add_argument('--ny', type=int)
    ap.add_argument('--nz', type=int)
    ap.add_argument('--cases', type=int, default=SHANGHAI_N_CASES,
                    help='Run first N cases (default 16)')
    ap.add_argument('--suffix', default='', help='CSV output suffix')
    ap.add_argument('--out-dir', help='New result directory (default: separate .cache/validation run)')
    ap.add_argument('--max-outer', type=int, default=MAX_OUTER,
                    help=f'Outer SIMPLE<->LTNE coupling budget (default {MAX_OUTER})')
    # Existing thresholds are retained; they do not certify a new physical
    # model or turn the historical 4.88%/2.12% scores into a current oracle.
    ap.add_argument('--gate-dp', type=float, default=12.0,
                    help='FAIL (exit 1) if RMSRE_dP exceeds this %% (default 12)')
    ap.add_argument('--gate-q', type=float, default=6.0,
                    help='FAIL (exit 1) if RMSRE_Q exceeds this %% (default 6)')
    ap.add_argument('--no-gate', action='store_true', help='Report only; no acceptance verdict')
    args = ap.parse_args(argv)
    if args.cases < 1:
        ap.error('--cases must be positive')
    if any(not np.isfinite(gate) or gate < 0 for gate in (args.gate_dp, args.gate_q)):
        ap.error('RMSRE gates must be finite and nonnegative')
    if Path(args.suffix).name != args.suffix and args.suffix:
        ap.error('--suffix must be a filename suffix, not a path')
    if args.port_wall_refine and args.wall_refine:
        ap.error('--port-wall-refine cannot combine with --wall-refine')
    try:
        out_dir = output_directory('shanghai_3d', args.out_dir)
        out_path = output_path(out_dir / f'shanghai_3d_baseline{args.suffix}.csv')
    except ValueError as exc:
        ap.error(str(exc))
    explicit_grid = any(n is not None for n in (args.nx, args.ny, args.nz))
    port_refine = args.port_wall_refine or (not explicit_grid and not args.wall_refine)
    from sjtu_tpmshx.models.grid import SHANGHAI_GRID_3D
    defaults = SHANGHAI_GRID_3D if port_refine else (20, 10, 3)
    Nx_u, Ny_u, Nz_u = (default if value is None else value
                        for value, default in zip((args.nx, args.ny, args.nz), defaults))
    df = load_cases_df(SHANGHAI_XLSX)
    if args.cases > len(df):
        ap.error(f'--cases requests {args.cases} rows but the source has {len(df)}')

    spec = shanghai_spec()
    print(f'Shanghai 3D validation ({spec.tpms} L={spec.L_cell_mm} '
          f't={spec.t_wall_mm} eps={spec.eps:.4f})')
    print(f'Domain: {spec.L_dom_m*1000:.0f}x{spec.H_dom_m*1000:.0f}x{spec.Lz_m*1000:.0f} mm')
    print(f'Requested grid: {Nx_u} x {Ny_u} x {Nz_u}; '
          f'wall_refine={args.wall_refine}, port_wall_refine={port_refine}')
    print(f'Requested outer budget: max_outer={args.max_outer}')
    print('Runner: production Pipeline3D, both fluids solved\n')
    results = []
    for ci in range(args.cases):
        try:
            r = _run_one_case_pipeline(ci, df, Nx_u, Ny_u, Nz_u,
                                      max_outer=args.max_outer, wall_refine=args.wall_refine,
                                      port_wall_refine=port_refine)
            print(f"Actual prepared grid: {r['grid_nx']} x {r['grid_ny']} x {r['grid_nz']}")
        except Exception as exc:
            results.append(dict(case=ci + 1, error=f'{type(exc).__name__}: {exc}',
                                pressure_state_valid=0, converged=False,
                                **{'err_dP%': float('nan'), 'err_Q%': float('nan')}))
            print(f'Case {ci + 1}: FAILED ({type(exc).__name__}: {exc})')
            continue
        results.append(r)
        marker = '' if r['outer_converged'] else '!'
        print(f"Case {r['case']:2d}: dP {r['dP_exp']:.0f}/{r['dP_sim']:.0f} "
              f"({r['err_dP%']:+.1f}%)  Q {r['Q_exp']:.0f}/{r['Q_sim']:.0f} "
              f"({r['err_Q%']:+.1f}%)  outer={r['outer_iters']}{marker}")

    # Every requested member remains in the RMSRE denominator. A failed
    # pressure/convergence verdict cannot turn into a dropped sample.
    invalid_cases = [r['case'] for r in results if not r['pressure_state_valid']]
    n_total, n_invalid = len(results), len(invalid_cases)
    err_dP = np.array([r['err_dP%'] for r in results])
    err_Q = np.array([r['err_Q%'] for r in results])
    rmsre_dP = float(np.sqrt(np.mean(err_dP ** 2)))
    rmsre_Q = float(np.sqrt(np.mean(err_Q ** 2)))
    print(f'\nCases: {n_total} total, {n_total-n_invalid} pressure-valid, {n_invalid} pressure-invalid')
    if invalid_cases:
        print(f'Invalid cases: {invalid_cases} (gate fails; rows retained)')
    print(f'RMSRE_dP: {rmsre_dP:.2f}%; max|err_dP|: {np.max(np.abs(err_dP)):.2f}%')
    print(f'RMSRE_Q: {rmsre_Q:.2f}%; max|err_Q|: {np.max(np.abs(err_Q)):.2f}%')
    print(f'Errors cover all {n_total} requested cases.')
    write_csv_with_provenance(pd.DataFrame(results), out_path, __file__)
    print(f'Saved: {out_path}')
    if args.no_gate:
        print('Report only: no accuracy or convergence acceptance claimed.')
        return 0
    incomplete = any(not r['converged'] for r in results)
    gate_fail = (n_total != args.cases or n_invalid > 0 or incomplete or
                 not np.all(np.isfinite(err_dP)) or not np.all(np.isfinite(err_Q)) or
                 rmsre_dP > args.gate_dp or rmsre_Q > args.gate_q)
    verdict = 'FAIL' if gate_fail else 'PASS'
    print(f'GATE {verdict}: RMSRE_dP {rmsre_dP:.2f}% (limit {args.gate_dp:.1f}%), '
          f'RMSRE_Q {rmsre_Q:.2f}% (limit {args.gate_q:.1f}%)')
    if incomplete:
        print('At least one production case did not converge.')
    return int(gate_fail)


if __name__ == '__main__':
    raise SystemExit(main())
