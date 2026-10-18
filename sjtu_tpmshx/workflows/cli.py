"""Independent prepare/solve/postprocess file stages and their composition."""
import argparse
from pathlib import Path
import signal
import threading

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.io.cli_options import add_run_control_arguments, run_control_from_args


def _check_input_outputs(parser, args):
    inputs, outputs = [args.input], [args.output]
    if args.stage == 'prepare' and args.output.suffix in ('.yaml', '.yml'):
        outputs.append(args.output.with_suffix('.h5'))
    elif args.stage == 'solve' and args.input.suffix != '.h5':
        from sjtu_tpmshx.io.case_io import _read_case_manifest
        inputs.append(args.input.parent / _read_case_manifest(args.input)['hdf5'])
    elif args.stage in ('run', 'resume'):
        outputs = [args.output / name for name in
                   ('case.h5', 'case.yaml', 'results.h5', 'metrics.json', 'checkpoint.h5', 'run.json')]
        if args.stage == 'resume':
            inputs += [args.input.parent / name for name in ('case.h5', 'run.json')]
    source_paths = {path.resolve() for path in inputs}
    for output in outputs:
        if output.resolve() in source_paths:
            parser.error(f'output overlaps input: {output}')
    for directory in {path.parent.resolve() for path in outputs}:
        if any((directory / name).exists() or (directory / name).is_symlink()
               for name in ('run.json', 'checkpoint.h5')):
            parser.error(f'output belongs to a saved run; use a new directory: {directory}')


def _recoverable_run(args, control):
    from sjtu_tpmshx.io.yaml_config import load_config
    from .recovery import compute_run, resume_run
    pause = threading.Event()

    def request_pause(signum, frame):
        pause.set()
        print('Pause requested; waiting for a saved solver boundary.', flush=True)

    previous = signal.signal(signal.SIGINT, request_pause)
    try:
        kwargs = dict(checkpoint_interval_s=args.checkpoint_interval,
                      control=control, pause_check=pause.is_set)
        if args.stage == 'resume':
            return resume_run(args.input, args.output, **kwargs)
        return compute_run(load_config(args.input), args.output, case_id=args.case_id, **kwargs)
    finally:
        signal.signal(signal.SIGINT, previous)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m sjtu_tpmshx.workflows.cli')
    commands = parser.add_subparsers(dest='stage', required=True)
    for stage in ('prepare', 'solve', 'postprocess', 'run', 'resume'):
        command = commands.add_parser(stage)
        command.add_argument('input', type=Path)
        command.add_argument('output', type=Path)
        if stage in ('prepare', 'run'):
            command.add_argument('--case-id', required=True)
        if stage in ('solve', 'run', 'resume'):
            add_run_control_arguments(command)
        if stage in ('run', 'resume'):
            command.add_argument('--checkpoint-interval', type=float, required=stage == 'resume',
                metavar='SECONDS', help='save native solver state at safe boundaries; Ctrl+C pauses the run')
        if stage == 'resume':
            command.set_defaults(backend='cpp')
    args = parser.parse_args(argv)
    _check_input_outputs(parser, args)
    control = run_control_from_args(args) if args.stage in ('solve', 'run', 'resume') else None
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
            result = run_case(load_case(args.input), control=control)
            save_result(result, args.output)
            return 0 if result.run_status['converged'] else 2
        if args.stage == 'postprocess':
            from sjtu_tpmshx.io.result_io import load_result
            from sjtu_tpmshx.io.metrics_io import save_metrics
            from sjtu_tpmshx.postprocess.api import evaluate
            result = load_result(args.input)
            performance = evaluate(result)
            save_metrics(performance, args.output)
            print('design = ' + performance.qualification.get('design', {}).get('status', 'unverified'))
            required = ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')
            return 0 if all(performance.metrics[key].status == 'available' for key in required) else 2
        from sjtu_tpmshx.io.yaml_config import load_config
        from sjtu_tpmshx.io.case_io import save_case
        from sjtu_tpmshx.io.result_io import save_result
        from sjtu_tpmshx.io.metrics_io import save_metrics
        from sjtu_tpmshx.io.file_set import staged_files
        from .compute import compute
        if args.stage == 'resume' or args.checkpoint_interval is not None:
            case, result, performance = _recoverable_run(args, control)
        else:
            args.output.mkdir(parents=True, exist_ok=True)
            case, result, performance = compute(load_config(args.input), case_id=args.case_id,
                                                control=control)
            names = ('case.h5', 'case.yaml', 'results.h5', 'metrics.json')
            with staged_files([args.output / name for name in names]) as stage:
                save_case(case, stage / 'case.yaml')
                save_result(result, stage / 'results.h5')
                save_metrics(performance, stage / 'metrics.json')
        print('design = ' + performance.qualification.get('design', {}).get('status', 'unverified'))
        required = ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')
        return 0 if result.run_status['converged'] and all(
            performance.metrics[key].status == 'available' for key in required) else 2
    except PausedRun as paused:
        print(f'paused = {paused.checkpoint_file}')
        return 3
    except CancelledError:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
