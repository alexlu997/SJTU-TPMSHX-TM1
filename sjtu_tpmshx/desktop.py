"""Desktop launcher shared by installed scripts and standalone bundles."""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import sys


def configure_cache():
    """Keep writable JIT and plotting caches outside the application bundle."""
    from PySide6.QtCore import QStandardPaths
    root = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericCacheLocation)) / 'SJTU-TPMSHX-TM1'
    for name, directory in (('NUMBA_CACHE_DIR', 'numba'),
                            ('MPLCONFIGDIR', 'matplotlib'),
                            ('XDG_CACHE_HOME', 'libraries')):
        path = Path(os.environ.setdefault(name, str(root / directory)))
        path.mkdir(parents=True, exist_ok=True)


def main(argv=None):
    # PyInstaller's override handles spawned workers before importing Qt/Numba.
    multiprocessing.freeze_support()
    configure_cache()
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ['--cli']:
        from sjtu_tpmshx.cli import main as run_cli
        return run_cli(args[1:])
    from sjtu_tpmshx.main import main as run_gui
    return run_gui()


if __name__ == '__main__':
    raise SystemExit(main())
