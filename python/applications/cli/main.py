"""Qt-free summary route: ``python main.py summary CONFIG [--dry-run] [--json]``.

The root ``main.py`` routes ``prepare``, ``solve``, ``postprocess``, ``run`` and
``resume`` to the public file-based workflow in ``stages.py``. This module solves one
ComputeConfig JSON file and prints a summary. GUI presets use a separate
format and must be restored through the GUI.

Exit codes are 0 for a passed summary or a dry run, and 2 for failed convergence,
envelope or required-metric checks. Parsing and file errors exit nonzero.
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
    ap = argparse.ArgumentParser(
        prog='main.py summary',
        description='Headless SJTU-TPMSHX solve: ComputeConfig JSON in, '
                    'a direct summary out. Qt is never imported.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='For the public file workflow, use main.py prepare, solve, postprocess,\n'
               'run or resume (COMMAND --help gives the arguments).\n'
               'GUI saved sessions are not CLI configuration files.')
    ap.add_argument('config', help='ComputeConfig JSON file '
                                   '(canonical or legacy baseline shape)')
    ap.add_argument('--dry-run', action='store_true',
                    help='parse, validate and report the dimension without a solve')
    ap.add_argument('--json', action='store_true', dest='as_json',
                    help='machine-readable one-line JSON summary')
    from tm1.applications.cli.cli_options import add_run_control_arguments, run_control_from_args
    add_run_control_arguments(ap)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    control = run_control_from_args(args)

    from tm1.data_types.compute_config import ComputeConfig
    from tm1.applications.result_adapter import compute_result

    with redirect_stdout(sys.stderr) if args.as_json else nullcontext():
        cc = ComputeConfig.from_json(args.config)
        result = None if args.dry_run else compute_result(cc, control=control)
    if args.dry_run:
        # Keep the public mode identifiers in the direct-summary interface.
        info = {'pipeline': 'Pipeline3D' if cc.is_3d else 'Pipeline2D',
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
        'qualification': result.metadata.get('qualification', {}),
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
        print("design = " + summary['qualification'].get('design', {}).get('status', 'unverified'))
        print(f"models = {json.dumps(summary['metadata'], ensure_ascii=False)}")
        for w in warnings_list:
            print(f"warning: {w}")
        for reason in result.extrap_reasons:
            print(f"extrap_reason: {reason}")
    return 0 if ok else 2
