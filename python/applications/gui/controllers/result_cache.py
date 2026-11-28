"""Current 2D/3D results and rendered-tab state for the GUI.

Window consumers use this store directly. ``RunHistory`` owns recent-run
snapshots and their menu.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from tm1.applications.gui.controllers.result_field_loader import (
    load_all_saved_display_fields,
    read_saved_display_field,
)
from tm1.data_types.compute_result import ComputeResult

from PySide6.QtCore import QObject


class ResultCache(QObject):
    """One published result; a replacement invalidates rendered tabs."""

    MODES = ('2d', '3d')

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._result: ComputeResult | None = None
        self._mode: str | None = None
        self._result_file: Path | None = None
        self._source_result_id: str | None = None
        self._available_fields: frozenset[str] = frozenset()
        # Which tabs have been drawn for the current result snapshot.
        # Cleared when a new payload arrives so the canvas repaints.
        self._drawn_tabs: set = set()

    # ------------------------------------------------------------------ result

    def _check_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(
                f"unknown mode: {mode!r} (expected one of {self.MODES})")

    def set_result(
        self,
        mode: str,
        payload: ComputeResult | None,
        *,
        result_file: str | Path | None = None,
        source_result_id: str | None = None,
        available_fields: Iterable[str] = (),
    ) -> None:
        """Store a fresh result for `mode`. Pass None to clear.

        A non-None payload clears the drawn-tabs set for repainting.
        """
        self._check_mode(mode)
        if payload is not None or mode == self._mode:
            self._result = payload
            self._mode = mode if payload is not None else None
            if payload is not None and result_file is not None:
                self._result_file = Path(result_file)
                self._source_result_id = (
                    source_result_id
                    if source_result_id is not None
                    else payload.metadata.get('source_result_id')
                )
                self._available_fields = frozenset(available_fields)
            else:
                self._result_file = None
                self._source_result_id = None
                self._available_fields = frozenset()
            self._drawn_tabs.clear()

    def get_result(self, mode: str | None = None) -> ComputeResult | None:
        if mode is not None:
            self._check_mode(mode)
        return self._result if mode is None or mode == self._mode else None

    def result_file(self, mode: str | None = None) -> Path | None:
        """Return the saved HDF5 file backing the active result, if any."""
        if self.get_result(mode) is None:
            return None
        return self._result_file

    def source_result_id(self, mode: str | None = None) -> str | None:
        """Return the source result ID recorded for the backing HDF5 file, if any."""
        if self.get_result(mode) is None:
            return None
        return self._source_result_id

    def has_field(self, key: str, mode: str | None = None) -> bool:
        """Return True if `key` is present in memory or in the backing result file."""
        result = self.get_result(mode)
        if result is None:
            return False
        if result.fields.get(key) is not None:
            return True
        return self._result_file is not None and key in self._available_fields

    def available_fields(self, mode: str | None = None) -> frozenset[str]:
        """Return every display field key available in memory or in the backing file."""
        result = self.get_result(mode)
        if result is None:
            return frozenset()
        present = {key for key, value in result.fields.items() if value is not None}
        if self._result_file is not None:
            present.update(self._available_fields)
        return frozenset(present)

    def read_field(self, key: str, mode: str | None = None) -> Any:
        """Read one display field from memory or from the backing file on demand."""
        result = self.get_result(mode)
        if result is None:
            return None
        value = result.fields.get(key)
        if value is not None:
            return value
        if self._result_file is not None and self._mode is not None and key in self._available_fields:
            return read_saved_display_field(
                self._result_file,
                key,
                mode=self._mode,
                expected_result_id=self._source_result_id,
            )
        return None

    def load_all_fields(self, mode: str | None = None) -> dict[str, Any]:
        """Return the full display-field dictionary, using full load_result when file-backed."""
        result = self.get_result(mode)
        if result is None:
            return {}
        if self._result_file is None or self._mode is None:
            return dict(result.fields)
        merged = dict(result.fields)
        merged.update(
            load_all_saved_display_fields(
                self._result_file,
                mode=self._mode,
                expected_result_id=self._source_result_id,
            )
        )
        return merged

    def clear(self, mode: Optional[str] = None) -> None:
        """Clear one result, or all results and rendered-tab flags."""
        if mode is None:
            self._result = None
            self._mode = None
            self._result_file = None
            self._source_result_id = None
            self._available_fields = frozenset()
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
