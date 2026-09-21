"""Qt-free command line entry: ``python -m sjtu_tpmshx.cli ...``.

``prepare``, ``solve``, ``postprocess`` and ``run`` dispatch to the public
file-based workflow. A direct ComputeConfig JSON argument retains the summary
interface, with ``--dry-run`` and ``--json`` options. GUI presets use a separate
format and must be restored through the GUI.

Calculation exit codes are 0 for a successful stage and 2 for failed
convergence/required-result checks; public workflow cancellation returns 130.
Parsing and file errors exit nonzero. See README for each stage's contract.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
import json
import math
import sys


def _json_values(value):
    """Represent unavailable numbers as null; accompanying statuses stay intact."""
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_values(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('prepare', 'solve', 'postprocess', 'run'):
        from sjtu_tpmshx.workflows.cli import main as module_main
        return module_main(argv)
    ap = argparse.ArgumentParser(
        prog='tpmshx-run',
        usage='%(prog)s {prepare,solve,postprocess,run} ...\n'
              '       %(prog)s config [--dry-run] [--json]',
        description='Headless SJTU-TPMSHX solve: ComputeConfig JSON in, '
                    'formal module files or a direct summary out. Qt is never imported.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Public file workflow (use COMMAND --help for arguments):\n'
               '  prepare       configuration -> case.yaml + case.h5\n'
               '  solve         case.yaml -> results.h5\n'
               '  postprocess   results.h5 -> metrics.json\n'
               '  run           configuration -> all four files\n\n'
               'From a source checkout:\n'
               '  python -m sjtu_tpmshx.cli run INPUT OUTPUT_DIR --case-id ID\n'
               'The direct config argument retains the summary interface;\n'
               'GUI saved sessions are not CLI configuration files.')
    ap.add_argument('config', help='ComputeConfig JSON file '
                                   '(canonical or legacy baseline shape)')
    ap.add_argument('--dry-run', action='store_true',
                    help='parse + validate + pipeline dispatch, no solve')
    ap.add_argument('--json', action='store_true', dest='as_json',
                    help='machine-readable one-line JSON summary')
    args = ap.parse_args(argv)

    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.controllers.compute_pipeline import pipeline_for

    with redirect_stdout(sys.stderr) if args.as_json else nullcontext():
        cc = ComputeConfig.from_json(args.config)
        pipe = pipeline_for(cc)
        result = None if args.dry_run else pipe.run()
    if args.dry_run:
        info = {'pipeline': type(pipe).__name__,
                'grid': [cc.solver.Nx, cc.solver.Ny, cc.solver.Nz]}
        print(json.dumps(info) if args.as_json
              else f"[dry-run] {info['pipeline']} grid={info['grid']}")
        return 0

    assert result is not None  # The dry-run branch has already returned.
    diag = result.diagnostics or {}
    ok = result.converged and bool(diag.get('envelope_valid', True)) and bool(
        (diag.get('convergence_detail') or {}).get('outer_converged', True))
    ok = ok and all(status == 'available' for status in result.metadata.get('metric_status', {}).values())
    warnings_list: list = list(getattr(result, 'warnings', []) or [])
    summary = {
        'Q_W': getattr(result, 'Q_W', None),
        'Q_unit': result.metadata.get('units', {}).get('Q', 'W' if cc.is_3d else 'W/m'),
        'converged': result.converged,
        'dP_A_Pa': getattr(result, 'dP_A_Pa', None),
        'dP_B_Pa': getattr(result, 'dP_B_Pa', None),
        'envelope_valid': diag.get('envelope_valid'),
        'outer_converged': (diag.get('convergence_detail') or {}
                            ).get('outer_converged'),
        'warnings': warnings_list,
        'extrap_reasons': list(result.extrap_reasons),
        'metadata': result.metadata,
    }
    if args.as_json:
        print(json.dumps(_json_values(summary), ensure_ascii=False,
                         allow_nan=False, default=str))
    else:
        print(f"Q = {summary['Q_W']} {summary['Q_unit']}")
        print(f"dP_A = {summary['dP_A_Pa']} Pa   dP_B = {summary['dP_B_Pa']} Pa")
        print(f"converged = {summary['converged']}   "
              f"envelope_valid = {summary['envelope_valid']}   "
              f"outer_converged = {summary['outer_converged']}")
        print(f"models = {json.dumps(summary['metadata'], ensure_ascii=False)}")
        for w in warnings_list:
            print(f"warning: {w}")
        for reason in result.extrap_reasons:
            print(f"extrap_reason: {reason}")
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
