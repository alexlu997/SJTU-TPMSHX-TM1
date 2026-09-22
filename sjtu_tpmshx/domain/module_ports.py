"""Non-persistent controls shared by numerical execution entry points."""
from __future__ import annotations

from dataclasses import dataclass
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

    def check_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise CancelledError("Solver cancelled by user")

    def report_progress(self, percent: int) -> None:
        if self.progress is not None:
            self.progress(percent)
