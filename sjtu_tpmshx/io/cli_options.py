"""Translate host CLI execution options into the portable module contract."""
from pathlib import Path

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.module_ports import resolve_control


def add_run_control_arguments(parser):
    """Add host execution options without changing the saved case/config."""
    parser.add_argument('--backend', choices=('cpp',), default='cpp')
    parser.add_argument('--cpu-threads', type=int,
                        help='CPU thread limit for this run; native default: at most 8')
    parser.add_argument('--native-library', type=Path,
                        help='native solver library on this host (cpp backend)')
    parser.add_argument('--native-table-directory', type=Path,
                        help='native property-table directory on this host')


def run_control_from_args(args):
    """Resolve CLI paths for this invocation; keep them outside portable data."""
    return resolve_control(RunControl(
        backend=args.backend, cpu_threads=getattr(args, 'cpu_threads', None),
        native_library=args.native_library,
        native_table_directory=args.native_table_directory))
