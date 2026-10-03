"""Translate host CLI execution options into the portable module contract."""
from pathlib import Path
import sys

from sjtu_tpmshx.domain.module_ports import RunControl


def add_run_control_arguments(parser):
    """Add host execution options without changing the saved case/config."""
    parser.add_argument('--backend', choices=('python', 'cpp'), default='python')
    parser.add_argument('--native-library', type=Path,
                        help='native solver library on this host (cpp backend)')
    parser.add_argument('--native-table-directory', type=Path,
                        help='native property-table directory on this host')


def run_control_from_args(args):
    """Resolve CLI paths for this invocation; keep them outside portable data."""
    if args.backend != 'cpp' and (args.native_library is not None or
                                  args.native_table_directory is not None):
        raise ValueError('--native-library and --native-table-directory require --backend cpp')
    library = args.native_library
    if args.backend == 'cpp' and library is None and getattr(sys, 'frozen', False):
        names = {'darwin': 'libtpmshx_solver_shared.dylib', 'win32': 'tpmshx_solver_shared.dll'}
        if sys.platform not in names:
            raise ValueError(f'unsupported bundled native platform: {sys.platform}')
        library = Path(sys._MEIPASS) / 'native' / names[sys.platform]
    return RunControl(
        backend=args.backend,
        native_library=str(library.expanduser().resolve()) if library is not None else None,
        native_table_directory=(str(args.native_table_directory.expanduser().resolve())
                                if args.native_table_directory is not None else None))
