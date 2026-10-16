"""Non-persistent controls shared by numerical execution entry points."""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

from sjtu_tpmshx.domain.cancellation import CancelledError

@dataclass(frozen=True)
class RunControl:
    """Non-persistent execution controls; never part of CaseData."""

    backend: str = "python"
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
