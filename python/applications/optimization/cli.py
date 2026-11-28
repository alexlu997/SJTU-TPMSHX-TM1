"""Command-line route for a continuous-field search: ``python main.py optimize``.

The input is a file of a saved search. ``optimization.json`` continues that search.
``optimization-input.json`` (format ``optimization_v1``) starts a new search with
the same fixed input. The output must be a new directory outside the saved search.
Torch loads only when the search uses a BO method (not Sobol).

Ctrl+C asks for a pause. The condition processes ignore the signal; this process
pauses them at a safe boundary. Exit codes are 0 for a completed search, 2 for a
failed search, 3 for a saved pause, and 130 for cancellation. Parsing and file
errors exit nonzero.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import signal
import threading

from tm1.applications.cli.cli_options import add_run_control_arguments, run_control_from_args
from tm1.run_control.cancellation import CancelledError
from tm1.run_control.paused_run import PausedRun


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='main.py optimize',
        description='Continue a saved continuous-field search, or start a new search '
                    'with the fixed input of a saved search.')
    parser.add_argument('input', type=Path,
                        help='optimization.json (continue) or optimization-input.json (new search)')
    parser.add_argument('output', type=Path, help='new search directory')
    parser.add_argument('--workers', type=int,
                        help='condition processes for each design; default: one for each two CPU threads, at most 4')
    add_run_control_arguments(parser)
    args = parser.parse_args(argv)
    if args.input.name not in ('optimization.json', 'optimization-input.json'):
        parser.error('select optimization.json or optimization-input.json')
    control = run_control_from_args(args)
    from .multi_condition_optimizer import (
        repeat_multi_condition_optimization, resume_multi_condition_optimization,
    )
    from .optimization_job import stopped_search
    search = (resume_multi_condition_optimization if args.input.name == 'optimization.json'
              else repeat_multi_condition_optimization)
    pause = threading.Event()

    def request_pause(signum, frame):
        pause.set()
        print('Pause requested; waiting for a saved search boundary.', flush=True)

    previous = signal.signal(signal.SIGINT, request_pause)
    try:
        record = search(args.input, output_dir=args.output, control=control,
                        workers=args.workers, pause_check=pause.is_set)
    except (CancelledError, PausedRun) as stop:
        report = stopped_search(args.output, stop)
        if report is None or report['status'] == 'cancelled':
            return 130
        print(f"paused = {args.output.resolve() / 'optimization.json'}")
        return 3
    finally:
        signal.signal(signal.SIGINT, previous)
    print(f"status = {record['status']}")
    if record['status'] != 'completed':
        print(f"reason = {record['reason']}")
        return 2
    return 0
