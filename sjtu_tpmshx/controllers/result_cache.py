"""Current 2D/3D results and rendered-tab state for the GUI.

Window consumers use this store directly. RunHistoryMixin owns recent-run
snapshots and their menu.
"""
from __future__ import annotations

from typing import Any, Optional

from sjtu_tpmshx.domain.compute_result import ComputeResult

from PySide6.QtCore import QObject


class ResultCache(QObject):
    """Per-mode results; replacing a result invalidates rendered tabs."""

    MODES = ('2d', '3d')


    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._results: dict[str, dict[str, Any] | ComputeResult | None] = {
            m: None for m in self.MODES
        }
        # Which tabs have been drawn for the current result snapshot.
        # Cleared when a new payload arrives so the canvas repaints.
        self._drawn_tabs: set = set()

    # ------------------------------------------------------------------ result

    def _check_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(
                f"unknown mode: {mode!r} (expected one of {self.MODES})")

    def set_result(self, mode: str, payload: dict[str, Any] | ComputeResult | None) -> None:
        """Store a fresh result for `mode`. Pass None to clear.

        A non-None payload clears the drawn-tabs set for repainting.
        """
        self._check_mode(mode)
        self._results[mode] = payload
        if payload is not None:
            # New result invalidates all prior tab renders.
            self._drawn_tabs.clear()

    def get_result(self, mode: str) -> dict[str, Any] | ComputeResult | None:
        self._check_mode(mode)
        return self._results[mode]

    def clear(self, mode: Optional[str] = None) -> None:
        """Clear one result, or all results and rendered-tab flags."""
        if mode is None:
            for m in self.MODES:
                self._results[m] = None
            self._drawn_tabs.clear()
        else:
            self.set_result(mode, None)

    def has_results(self, mode: Optional[str] = None) -> bool:
        """True if `mode` (or any mode if None) has a non-None result."""
        if mode is None:
            return any(r is not None for r in self._results.values())
        self._check_mode(mode)
        return self._results[mode] is not None

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

    def clear_drawn(self) -> None:
        self._drawn_tabs.clear()

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        flags = ' '.join(
            f'{m}={"+" if self._results[m] is not None else "-"}'
            for m in self.MODES
        )
        return f'<ResultCache {flags} drawn={sorted(self._drawn_tabs)!r}>'
