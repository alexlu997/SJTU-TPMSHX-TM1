"""Non-persistent controls shared by numerical execution entry points."""
from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys
from typing import Callable

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.provenance import SOURCE_ROOT

@dataclass(frozen=True)
class RunControl:
    """Non-persistent execution controls; never part of CaseData."""

    backend: str = "cpp"
    progress: Callable[[int], None] | None = None
    cancel_check: Callable[[], bool] | None = None
    iteration: Callable[[str], None] | None = None
    outer_iteration: Callable[[int, int], None] | None = None
    residual: Callable[[str, int, float], None] | None = None
    # Host-local library location; never persisted as part of CaseData.
    native_library: str | None = None
    native_table_directory: str | None = None
    cpu_threads: int | None = None

    def __post_init__(self) -> None:
        if self.backend != "cpp":
            raise ValueError(f"unsupported backend: {self.backend}; the Python numerical backend has been retired")
        if self.cpu_threads is not None and (type(self.cpu_threads) is not int or self.cpu_threads < 1):
            raise ValueError('cpu_threads must be a positive integer or None')

    def native_cpu_threads(self) -> int:
        """Resolve the native limit within the logical CPUs on this host."""
        return min(self.cpu_threads or 8, os.cpu_count() or 1)

    def check_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise CancelledError("Solver cancelled by user")

    def report_progress(self, percent: int) -> None:
        if self.progress is not None:
            self.progress(percent)


def resolve_control(control):
    """Resolve host paths outside the portable case and saved configuration."""
    library = control.native_library
    tables = control.native_table_directory
    if library is None:
        names = {'darwin': 'libtpmshx_solver_shared.dylib', 'win32': 'tpmshx_solver_shared.dll'}
        if sys.platform not in names:
            raise ValueError(f'no default native library for {sys.platform}; set native_library')
        if getattr(sys, 'frozen', False):
            library = Path(sys._MEIPASS) / 'native' / names[sys.platform]
        else:
            platform_dir = {'darwin': 'macos-arm64', 'win32': 'windows-x64'}[sys.platform]
            library = SOURCE_ROOT / 'native/lib' / platform_dir / names[sys.platform]
            if tables is None:
                tables = SOURCE_ROOT / '.cache/native-deps/tables'
    return replace(control, native_library=str(Path(library).expanduser().resolve()),
        native_table_directory=str(Path(tables).expanduser().resolve()) if tables is not None else None)
