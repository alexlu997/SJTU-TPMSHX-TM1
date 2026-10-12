"""Current 2D/3D results and rendered-tab state for the GUI.

Window consumers use this store directly. RunHistoryMixin owns recent-run
snapshots and their menu.
"""
from __future__ import annotations

from typing import Optional

from sjtu_tpmshx.domain.compute_result import ComputeResult

from PySide6.QtCore import QObject


class ResultCache(QObject):
    """One published result; a replacement invalidates rendered tabs."""

    MODES = ('2d', '3d')


    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._result: ComputeResult | None = None
        self._mode: str | None = None
        # Which tabs have been drawn for the current result snapshot.
        # Cleared when a new payload arrives so the canvas repaints.
        self._drawn_tabs: set = set()

    # ------------------------------------------------------------------ result

    def _check_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(
                f"unknown mode: {mode!r} (expected one of {self.MODES})")

    def set_result(self, mode: str, payload: ComputeResult | None) -> None:
        """Store a fresh result for `mode`. Pass None to clear.

        A non-None payload clears the drawn-tabs set for repainting.
        """
        self._check_mode(mode)
        if payload is not None or mode == self._mode:
            self._result = payload
            self._mode = mode if payload is not None else None
            self._drawn_tabs.clear()

    def get_result(self, mode: str | None = None) -> ComputeResult | None:
        if mode is not None:
            self._check_mode(mode)
        return self._result if mode is None or mode == self._mode else None

    def clear(self, mode: Optional[str] = None) -> None:
        """Clear one result, or all results and rendered-tab flags."""
        if mode is None:
            self._result = None
            self._mode = None
            self._drawn_tabs.clear()
        else:
            self.set_result(mode, None)

    def has_results(self, mode: Optional[str] = None) -> bool:
        """True if `mode` (or any mode if None) has a non-None result."""
        return self.get_result(mode) is not None

    def has_any_results(self) -> bool:
        return self.has_results(None)

    # ------------------------------------------------------------------ tabs

    def mark_drawn(self, tab: str) -> None:
        """Mark `tab` as having been drawn for the current result snapshot."""
        self._drawn_tabs.add(tab)

    def is_drawn(self, tab: str) -> bool:
        return tab in self._drawn_tabs

    def get_drawn_tabs(self) -> set:
        """Return a copy of the drawn-tabs set."""
        return set(self._drawn_tabs)

    def replace_drawn_tabs(self, tabs: set) -> None:
        """Replace the set after invalidating or rebuilding selected views."""
        self._drawn_tabs = set(tabs)

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        flags = ' '.join(
            f'{m}={"+" if self.get_result(m) is not None else "-"}'
            for m in self.MODES
        )
        return f'<ResultCache {flags} drawn={sorted(self._drawn_tabs)!r}>'
