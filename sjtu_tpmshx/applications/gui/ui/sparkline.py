"""Theme-aware inline chart for optimization progress and recent run values.

Each caller owns the history's meaning and clears it before changing quantity.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath
from PySide6.QtWidgets import QWidget

from .theme import get_theme


class Sparkline(QWidget):
    def __init__(self, parent=None, height=44):
        super().__init__(parent)
        self._data: list[float] = []
        self.setMinimumHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def push(self, value):
        """Append one sample and trigger a repaint.

        2026-05-20 UI sweep (Tier 24): harden the public API at the
        entry point. Previously `float(value)` was unguarded, so a
        `None`, empty string, or other non-numeric push raised
        TypeError/ValueError into the caller's slot. The paint-time
        filter (added Tier 21) caught non-finite values once stored,
        but could not protect callers from an exception here. Reject
        non-numeric / non-finite samples silently instead.
        """
        import math
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(v):
            return
        self._data.append(v)
        if len(self._data) > 500:  # cap memory
            self._data = self._data[-500:]
        self.update()

    def clear_data(self):
        self._data = []
        self.update()

    def paintEvent(self, event):
        t = get_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 4

        # Empty-state baseline — dashed rule at bottom suggests "live chart
        # will fill here" without the noise of an empty box.
        if len(self._data) < 2:
            pen = QPen(QColor(t.get('border_subtle', '#888')))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.drawLine(pad, h - pad - 1, w - pad, h - pad - 1)
            p.end()
            return

        # 2026-05-20 UI sweep (Tier 21): drop non-finite samples before
        # min/max. A single NaN/inf pushed onto the sparkline (e.g. an
        # ETA or HV value that went non-finite on a degenerate run)
        # would otherwise poison vmin/vmax and produce NaN painter
        # coordinates — silent on most platforms, a hard paint error on
        # some. Fall back to the empty-state rule if nothing finite is
        # left.
        import math as _math_sl
        vals = [v for v in self._data if _math_sl.isfinite(v)]
        if len(vals) < 2:
            pen = QPen(QColor(t.get('border_subtle', '#888')))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.drawLine(pad, h - pad - 1, w - pad, h - pad - 1)
            p.end()
            return
        vmin = min(vals); vmax = max(vals)
        rng = (vmax - vmin) or max(1.0, abs(vmax))

        xs = [(pad + (i / (len(vals) - 1)) * (w - 2 * pad))
              for i in range(len(vals))]
        ys = [(h - pad - ((v - vmin) / rng) * (h - 2 * pad)) for v in vals]

        col = QColor(t.get('accent_primary', '#3B82F6'))

        # Gradient-like fill under curve (single alpha fill is enough at
        # this size; QLinearGradient would be over-engineered here).
        path_fill = QPainterPath()
        path_fill.moveTo(xs[0], h - pad)
        for xx, yy in zip(xs, ys):
            path_fill.lineTo(xx, yy)
        path_fill.lineTo(xs[-1], h - pad)
        path_fill.closeSubpath()
        col_fill = QColor(col); col_fill.setAlpha(55)
        p.fillPath(path_fill, col_fill)

        # Line stroke
        pen = QPen(col)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(xs[0], ys[0])
        for xx, yy in zip(xs[1:], ys[1:]):
            path.lineTo(xx, yy)
        p.drawPath(path)

        # Current value marker — filled dot at the tail
        p.setBrush(col)
        p.setPen(Qt.PenStyle.NoPen)
        dot_r = 3
        p.drawEllipse(int(xs[-1]) - dot_r, int(ys[-1]) - dot_r,
                       dot_r * 2, dot_r * 2)
        # Outer ring for emphasis
        ring = QColor(col); ring.setAlpha(70)
        p.setBrush(ring)
        p.drawEllipse(int(xs[-1]) - dot_r - 3, int(ys[-1]) - dot_r - 3,
                       (dot_r + 3) * 2, (dot_r + 3) * 2)

        p.end()
