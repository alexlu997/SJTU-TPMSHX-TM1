"""Zone graph editor — draggable boundary handles on the Layout canvas.

MVP scope: 1-D y-axis zoning (the most common mode). Users can grab a
handle on any interior zone boundary and drag it; the zone_table cells
for that row's end% and the next row's start% update live, and on
release the layout redraws with the new bounds. Grid-mode + x-axis
mode fall back to table-only editing (skipped here to keep scope small).
"""
from __future__ import annotations

from .theme import get_theme


class ZoneHandleManager:
    """Wire once per window; redraw handles after every layout render."""

    def __init__(self, window):
        self._w = window
        self._drag_row = None
        self._handles = []  # list[(row_idx, scatter_artist, baseline_y)]
        self._connected = False
        self._Lmm = 1.0
        self._Hmm = 1.0

    def wire(self):
        if self._connected:
            return
        c = getattr(self._w, 'canvas_layout', None)
        if c is None:
            return
        c.mpl_connect('button_press_event', self._on_press)
        c.mpl_connect('motion_notify_event', self._on_motion)
        c.mpl_connect('button_release_event', self._on_release)
        self._connected = True

    def draw_handles(self, ax, Lmm, Hmm):
        """Must be called after draw_layout_rect finishes populating `ax`."""
        self._handles = []
        w = self._w
        if not getattr(w, 'chk_zones', None) or not w.chk_zones.isChecked():
            return
        try:
            z_ax = w._zone_axis()
        except Exception:
            z_ax = 'y'
        if z_ax != 'y':
            return  # MVP: y-axis only
        n = w.zone_table.rowCount()
        t = get_theme()
        bar_color = t.get('accent_primary', '#3B82F6')
        for r in range(n - 1):
            end_item = w.zone_table.item(r, 1)
            if end_item is None or not end_item.text().strip():
                continue
            try:
                f = float(end_item.text()) / 100.0
            except ValueError:
                continue
            y = f * Hmm
            art = ax.scatter([Lmm * 0.5], [y], s=110,
                              facecolors=t.get('card_bg', '#ffffff'),
                              edgecolors=bar_color, linewidths=2.4,
                              zorder=12, marker='o')
            # Thick guide line across the domain for this handle.
            line = ax.plot([0, Lmm], [y, y],
                            color=bar_color, lw=1.2, alpha=0.55,
                            zorder=11, linestyle='-')[0]
            self._handles.append((r, art, line, y))

    # ── Matplotlib event callbacks ──────────────────────────────────
    def _pick_row(self, event):
        """Return the nearest handle row within a tolerance, else None."""
        if event.inaxes is None or event.ydata is None:
            return None
        tol_mm = max(3.0, self._Hmm * 0.04)
        best = None; best_d = tol_mm
        for r, art, _line, y in self._handles:
            d = abs(event.ydata - y)
            if d < best_d:
                best_d = d; best = r
        return best

    def _on_press(self, event):
        self._drag_row = self._pick_row(event)

    def _on_motion(self, event):
        if self._drag_row is None or event.ydata is None:
            return
        new_f = max(0.02, min(0.98, event.ydata / max(1e-6, self._Hmm)))
        pct = new_f * 100.0
        w = self._w
        r = self._drag_row
        end_item = w.zone_table.item(r, 1)
        next_start = w.zone_table.item(r + 1, 0) if (r + 1 <
                        w.zone_table.rowCount()) else None
        prev_start_val = 0.0
        prev_start = w.zone_table.item(r, 0)
        if prev_start is not None:
            try:
                prev_start_val = float(prev_start.text())
            except Exception:
                pass
        # Enforce monotonic ordering with BOTH neighbours. FIX (2026-06-24 audit):
        # this boundary is written to row r's END *and* row r+1's START, so it must
        # also stay below row r+1's END — otherwise dragging past the next zone's
        # end inverts that zone (start>end). The old clamp only bounded the lower
        # side (own start) and an absolute 99.
        next_end_val = 99.0
        if (r + 1) < w.zone_table.rowCount():
            _ne = w.zone_table.item(r + 1, 1)
            if _ne is not None:
                try:
                    next_end_val = float(_ne.text())
                except Exception:
                    pass
        pct = max(prev_start_val + 1.0, min(99.0, next_end_val - 1.0, pct))
        # 2026-05-20 UI sweep (Tier 19): writing the table cells on every
        # mouse-motion event triggered the table's `cellChanged` signal
        # chain (validation re-runs, stylesheet recompute, table model
        # repaint) on each pixel of drag — visibly stutters on smaller
        # GPUs. Defer the table writes to `_on_release` and stash the
        # pending value here; only the handle artist + guide line move
        # live during drag.
        self._drag_pending_pct = pct
        self._drag_pending_end_item = end_item
        self._drag_pending_next_start = next_start
        # Live preview: just move the handle + guide line, skip full redraw
        # so dragging stays smooth.
        y_new = new_f * self._Hmm
        for (rr, art, line, _y0) in self._handles:
            if rr == r:
                art.set_offsets([[self._Lmm * 0.5, y_new]])
                line.set_ydata([y_new, y_new])
                break
        w.canvas_layout.draw_idle()

    def _on_release(self, event):
        if self._drag_row is None:
            return
        # Tier 19: flush deferred table writes here so the cellChanged
        # validator runs exactly once per drag, not once per pixel.
        # Block signals on the table object while we apply both cells,
        # then re-emit once via a final cellChanged on the end row.
        _pct = getattr(self, '_drag_pending_pct', None)
        _end_item = getattr(self, '_drag_pending_end_item', None)
        _next_start = getattr(self, '_drag_pending_next_start', None)
        if _pct is not None and (_end_item is not None or _next_start is not None):
            _table = getattr(self._w, 'zone_table', None)
            _blocker = _table.blockSignals(True) if _table is not None else False
            try:
                if _end_item is not None:
                    _end_item.setText(f"{_pct:.1f}")
                if _next_start is not None:
                    _next_start.setText(f"{_pct:.1f}")
            finally:
                if _table is not None:
                    _table.blockSignals(_blocker)
            # Re-emit cellChanged once at release so the validator runs.
            if _table is not None and _end_item is not None:
                try:
                    _table.cellChanged.emit(_end_item.row(), _end_item.column())
                except Exception:
                    pass
        self._drag_pending_pct = None
        self._drag_pending_end_item = None
        self._drag_pending_next_start = None
        self._drag_row = None
        # Final redraw picks up the fully-styled zone rectangles + labels.
        try:
            self._w._draw_layout()
        except Exception:
            pass
