"""Independent prepare/solve/postprocess file stages and their composition."""
import argparse
from pathlib import Path

from sjtu_tpmshx.domain.cancellation import CancelledError


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m sjtu_tpmshx.workflows.cli')
    commands = parser.add_subparsers(dest='stage', required=True)
    for stage in ('prepare', 'solve', 'postprocess', 'run'):
        command = commands.add_parser(stage)
        command.add_argument('input', type=Path)
        command.add_argument('output', type=Path)
        if stage in ('prepare', 'run'):
            command.add_argument('--case-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.stage == 'prepare':
            from sjtu_tpmshx.io.yaml_config import load_config
            from sjtu_tpmshx.io.case_io import save_case
            from sjtu_tpmshx.preprocess.api import prepare_case
            save_case(prepare_case(load_config(args.input), case_id=args.case_id), args.output)
            return 0
        if args.stage == 'solve':
            from sjtu_tpmshx.io.case_io import load_case
            from sjtu_tpmshx.io.result_io import save_result
            from sjtu_tpmshx.solvers.api import run_case
            result = run_case(load_case(args.input))
            save_result(result, args.output)
            return 0 if result.run_status['converged'] else 2
        if args.stage == 'postprocess':
            from sjtu_tpmshx.io.result_io import load_result
            from sjtu_tpmshx.io.metrics_io import save_metrics
            from sjtu_tpmshx.postprocess.api import evaluate
            result = load_result(args.input)
            performance = evaluate(result)
            save_metrics(performance, args.output)
            required = (('Q', 'dP_A', 'dP_B', 'mass')
                        if result.metadata.get('mode') in ('screening_2d', 'screening_3d')
                        else ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B'))
            return 0 if all(performance.metrics[key].status == 'available' for key in required) else 2
        from sjtu_tpmshx.io.yaml_config import load_config
        from sjtu_tpmshx.io.case_io import save_case
        from sjtu_tpmshx.io.result_io import save_result
        from sjtu_tpmshx.io.metrics_io import save_metrics
        from .compute import compute
        args.output.mkdir(parents=True, exist_ok=True)
        case, result, performance = compute(load_config(args.input), case_id=args.case_id)
        save_case(case, args.output / 'case.yaml')
        save_result(result, args.output / 'results.h5')
        save_metrics(performance, args.output / 'metrics.json')
        required = ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')
        return 0 if result.run_status['converged'] and all(
            performance.metrics[key].status == 'available' for key in required) else 2
    except CancelledError:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
