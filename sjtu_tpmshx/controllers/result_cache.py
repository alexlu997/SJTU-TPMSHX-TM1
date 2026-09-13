"""ResultCache — centralized per-mode result + dirty + recent-runs storage.

Phase 2 of 2026-05-06 main.py refactor (audit fix #4). Aggregates state
that was previously scattered across Main_Menu instance attributes:

    Main_Menu attribute            ResultCache method
    ──────────────────────────     ──────────────────────────────
    self._compute_results          cache.get_result('2d') / set_result
    self._result_3d                cache.get_result('3d') / set_result
    self._has_results_2d           cache.has_results('2d')
    self._has_results_3d           cache.has_results('3d')
    self._has_results              cache.has_any_results()
    self._recent_runs              cache.get_recent() / push_recent
    self._drawn_tabs               cache.is_drawn(tab) / mark_drawn / clear_drawn

Backwards-compat: Main_Menu still exposes the old attribute names via
@property bridges in ui/mixins/result_bridge.py. Result presentation in
ui/mixins/run_results.py and panel modules continue to
read/write the legacy attributes — they transparently delegate to
ResultCache. New code should use the ResultCache API directly.

Signals
-------
results_changed(str mode)
    Emitted when set_result / clear is called. mode in {'2d', '3d', 'poly'}.
recent_pushed(dict meta)
    Emitted when push_recent appends to the ring.

Phase 2 of 2026-05-06 plan #4 refactor.
See vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


class ResultCache(QObject):
    """Centralized result store with per-mode tracking + recent-runs ring.

    Modes are 2d / 3d / poly. Each mode owns a payload dict (whatever the
    solver writes) and a dirty bit (whether canvases need redraw).
    """

    MODES = ('2d', '3d', 'poly')

    # Signals (auto-marshal to GUI thread when emitted from worker)
    results_changed = Signal(str)
    recent_pushed = Signal(dict)

    def __init__(self, parent: Optional[QObject] = None,
                 max_recent: int = 5):
        super().__init__(parent)
        self._results: Dict[str, Optional[Dict[str, Any]]] = {
            m: None for m in self.MODES
        }
        # `_dirty[mode]` is True when result was set but canvas hasn't redrawn.
        self._dirty: Dict[str, bool] = {m: False for m in self.MODES}
        # Ring of headline metadata for the "Recent ▾" menu (max_recent entries).
        self._recent: deque = deque(maxlen=max_recent)
        # Which tabs have been drawn for the current result snapshot.
        # Cleared on each set_result so canvas knows to repaint.
        self._drawn_tabs: set = set()
        self._max_recent = max_recent

    # ------------------------------------------------------------------ result

    def _check_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(
                f"unknown mode: {mode!r} (expected one of {self.MODES})")

    def set_result(self, mode: str, payload: Optional[Dict[str, Any]]) -> None:
        """Store a fresh result for `mode`. Pass None to clear.

        Marks the mode as dirty (canvas needs redraw) and clears the
        drawn-tabs set so each tab repaints when shown.
        """
        self._check_mode(mode)
        self._results[mode] = payload
        if payload is None:
            self._dirty[mode] = False
        else:
            self._dirty[mode] = True
            # New result invalidates all prior tab renders.
            self._drawn_tabs.clear()
        self.results_changed.emit(mode)

    def get_result(self, mode: str) -> Optional[Dict[str, Any]]:
        self._check_mode(mode)
        return self._results[mode]

    def clear(self, mode: Optional[str] = None) -> None:
        """Clear one mode or all modes. Clears drawn_tabs."""
        if mode is None:
            for m in self.MODES:
                self._results[m] = None
                self._dirty[m] = False
            self._drawn_tabs.clear()
            for m in self.MODES:
                self.results_changed.emit(m)
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

    def is_dirty(self, mode: str) -> bool:
        self._check_mode(mode)
        return self._dirty[mode]

    def mark_clean(self, mode: str) -> None:
        """Mark mode as clean (canvas has been redrawn for current result)."""
        self._check_mode(mode)
        self._dirty[mode] = False

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
        """Replace the drawn-tabs set wholesale (legacy `_drawn_tabs = ...`)."""
        self._drawn_tabs = set(tabs)

    def clear_drawn(self) -> None:
        self._drawn_tabs.clear()

    # ------------------------------------------------------------------ recent

    def push_recent(self, meta: Dict[str, Any]) -> None:
        """Append a headline-metadata dict to the recent-runs ring.

        meta typically contains: timestamp, mode, Q, dP, preset_name, fluid_A,
        fluid_B, geom params. Schema-free — ResultCache stores whatever the
        caller passes.
        """
        self._recent.append(dict(meta))   # shallow copy to avoid alias
        self.recent_pushed.emit(dict(meta))

    def get_recent(self) -> List[Dict[str, Any]]:
        """Return recent runs as a list (newest first if push order ascending)."""
        return list(self._recent)

    def replace_recent(self, runs: List[Dict[str, Any]]) -> None:
        """Replace the entire ring (e.g. when restoring from session)."""
        self._recent = deque((dict(r) for r in runs), maxlen=self._max_recent)

    def clear_recent(self) -> None:
        self._recent.clear()

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        flags = ' '.join(
            f'{m}={"+" if self._results[m] is not None else "-"}'
            f'{"d" if self._dirty[m] else ""}'
            for m in self.MODES
        )
        return (f'<ResultCache {flags} '
                f'recent={len(self._recent)}/{self._max_recent} '
                f'drawn={sorted(self._drawn_tabs)!r}>')
