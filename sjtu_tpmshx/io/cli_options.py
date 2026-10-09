"""Translate host CLI execution options into the portable module contract."""
from pathlib import Path
import sys

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.provenance import SOURCE_ROOT


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
    tables = args.native_table_directory
    if args.backend == 'cpp' and library is None:
        names = {'darwin': 'libtpmshx_solver_shared.dylib', 'win32': 'tpmshx_solver_shared.dll'}
        if sys.platform not in names:
            raise ValueError(f'no default native library for {sys.platform}; use --native-library')
        if getattr(sys, 'frozen', False):
            library = Path(sys._MEIPASS) / 'native' / names[sys.platform]
        else:
            platform_dir = {'darwin': 'macos-arm64', 'win32': 'windows-x64'}[sys.platform]
            library = SOURCE_ROOT / 'native/lib' / platform_dir / names[sys.platform]
            if tables is None:
                tables = SOURCE_ROOT / '.cache/native-deps/tables'
    return RunControl(
        backend=args.backend,
        native_library=str(library.expanduser().resolve()) if library is not None else None,
        native_table_directory=str(tables.expanduser().resolve()) if tables is not None else None)
