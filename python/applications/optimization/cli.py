"""Command-line route for a continuous-field search: ``python main.py optimize``.

The input is a file of a saved search. ``optimization.json`` continues that search.
``optimization-input.json`` (format ``optimization_v1``) starts a new search with
the same fixed input. Torch loads only when a BO method makes a proposal.

Exit codes are 0 for a completed search, 2 for a failed search, 3 for a saved
pause, and 130 for cancellation. Parsing and file errors exit nonzero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import threading

from tm1.applications.cli.cli_options import add_run_control_arguments, run_control_from_args
from tm1.run_control.cancellation import CancelledError
from tm1.run_control.paused_run import PausedRun

FIXED_SETTINGS = ('method', 'n_init', 'n_iter', 'q_batch', 'seed', 'field_spec')


def _search(args, control, pause_check):
    from .multi_condition import saved_condition_config
    from .multi_condition_optimizer import (
        resume_multi_condition_optimization, run_multi_condition_optimization,
    )
    options = dict(output_dir=args.output, control=control, workers=args.workers,
                   pause_check=pause_check)
    if args.input.name == 'optimization.json':
        return resume_multi_condition_optimization(args.input, **options)
    frozen = json.loads(args.input.read_text(encoding='utf-8'))
    if frozen.get('format') != 'optimization_v1':
        raise ValueError('saved search does not have a supported fixed input')
    conditions = [(row['condition_id'], saved_condition_config(row),
                   row['mass_flow_A_kg_s'], row['mass_flow_B_kg_s']) for row in frozen['conditions']]
    return run_multi_condition_optimization(
        conditions, mass_requirements=frozen.get('mass_requirements'),
        **{key: frozen[key] for key in FIXED_SETTINGS}, **options)


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
    pause = threading.Event()

    def request_pause(signum, frame):
        pause.set()
        print('Pause requested; waiting for a saved search boundary.', flush=True)

    previous = signal.signal(signal.SIGINT, request_pause)
    try:
        record = _search(args, control, pause.is_set)
    except PausedRun as paused:
        print(f'paused = {paused.checkpoint_file}')
        return 3
    except CancelledError:
        return 130
    finally:
        signal.signal(signal.SIGINT, previous)
    print(f"status = {record['status']}")
    if record['status'] != 'completed':
        print(f"reason = {record['reason']}")
        return 2
    return 0
