"""Qt overlays drawn over a 3D viewport: colorbar, port chips, and lattice cards."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import matplotlib as mpl
from matplotlib.ticker import MaxNLocator
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextDocument,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from .colormap_popover import CURATED_COLORMAPS
from .symbols import MINUS, SYM
from .theme import get_theme

COLORBAR_WIDTH = 112
COLORBAR_HEIGHT = 460


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


def _dot_pixmap(color_hex: str, diameter: float) -> QPixmap:
    side = int(diameter) + 3
    pixmap = QPixmap(side * 3, side * 3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color_hex))
    painter.drawEllipse(QPointF(side / 2.0, side / 2.0), diameter / 2.0, diameter / 2.0)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return pixmap


def _format_unit(unit: str) -> str:
    clean = unit.strip()
    if not clean:
        return ""
    if clean.startswith("[") and clean.endswith("]"):
        return clean
    return f"[{clean}]"


def _auto_tick_formats(span: float) -> tuple[str, str]:
    abs_span = abs(span)
    if abs_span >= 50.0:
        return ("{:.1f}", "{:g}")
    if abs_span >= 5.0:
        return ("{:.2f}", "{:.1f}")
    if abs_span >= 0.05:
        return ("{:.3f}", "{:.2f}")
    return ("{:.4g}", "{:.3g}")


def _fmt_iso(val: float, spec: str) -> str:
    text = spec.format(val)
    if text in ("-0", "-0.0", "-0.00", "-0.000"):
        text = text[1:]
    return text.replace("-", MINUS)


def _format_triangles(count: int) -> str:
    if count >= 100_000:
        return f"{count / 1e6:.2f} M 三角面"
    if count >= 1_000:
        return f"{count / 1e3:.1f} k 三角面"
    return f"{count} 三角面"


def _segment_intersects_rect(
    p0: tuple[float, float],
    p1: tuple[float, float],
    rect: QRect,
    pad: int = 0,
) -> bool:
    """Return True if line segment ``[p0, p1]`` intersects ``rect`` expanded by ``pad``."""
    x_min = float(rect.left() - pad)
    x_max = float(rect.right() + pad)
    y_min = float(rect.top() - pad)
    y_max = float(rect.bottom() + pad)

    x0, y0 = p0
    dx = p1[0] - x0
    dy = p1[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, x0 - x_min),
        (dx, x_max - x0),
        (-dy, y0 - y_min),
        (dy, y_max - y0),
    ):
        if abs(p) < 1e-12:
            if q < 0.0:
                return False
        else:
            r = q / p
            if p < 0.0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return t0 <= t1


def _overlap_area(a: QRect, b: QRect) -> int:
    inter = a.intersected(b)
    if inter.isEmpty():
        return 0
    return inter.width() * inter.height()


class _VerticalHairline(QWidget):
    """Single-device-pixel vertical divider inside overlay chips."""

    def __init__(self, color_hex: str, height: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self.setFixedSize(1, height)

    def set_color(self, color_hex: str) -> None:
        self._color = QColor(color_hex)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.25, 0.0), QPointF(0.25, float(self.height())))
        painter.end()


class _ThinProgressBar(QWidget):
    """Compact 6 px progress bar used inside ``LatticeProgressCard``."""

    def __init__(
        self,
        progress: float,
        tokens: Mapping[str, Any],
        width: int = 104,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._progress = max(0.0, min(1.0, float(progress)))
        self._tokens = dict(tokens)
        self.setFixedSize(width, 6)

    def set_progress(self, fraction: float) -> None:
        self._progress = max(0.0, min(1.0, float(fraction)))
        self.update()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        self._tokens.update(tokens)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._tokens["sunken"]))
        painter.drawRoundedRect(QRectF(0.0, 1.0, float(self.width()), 4.0), 2.0, 2.0)
        fill_w = float(self.width()) * self._progress
        if fill_w > 0.0:
            painter.setBrush(QColor(self._tokens["accent"]))
            painter.drawRoundedRect(QRectF(0.0, 1.0, fill_w, 4.0), 2.0, 2.0)
        painter.end()


class StudioColorbarCard(QFrame):
    """Floating Style P2 vertical colorbar card for 3D fields.

    Accepts an ISO 80000-1 rich-text symbol, physical unit, ``(vmin, vmax)`` range,
    and one of the four curated colormap names in ``CURATED_COLORMAPS``.
    """

    def __init__(
        self,
        symbol_html: str = SYM["T_fA"],
        unit: str = "K",
        vmin: float = 300.0,
        vmax: float = 400.0,
        colormap: str = "coolwarm",
        *,
        end_fmt: str | None = None,
        mid_fmt: str | None = None,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._validate_colormap(colormap)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)

        self._symbol_html = symbol_html
        self._unit = _format_unit(unit)
        self._vmin = float(vmin)
        self._vmax = float(vmax)
        self._colormap = colormap
        self._end_fmt = end_fmt
        self._mid_fmt = mid_fmt

        self.setObjectName("studioColorbarCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(COLORBAR_WIDTH, COLORBAR_HEIGHT)

    def colormap(self) -> str:
        """Return the active colormap name."""
        return self._colormap

    def value_range(self) -> tuple[float, float]:
        """Return the displayed ``(vmin, vmax)`` range."""
        return (self._vmin, self._vmax)

    def set_spec(
        self,
        symbol_html: str,
        unit: str,
        vmin: float,
        vmax: float,
        colormap: str | None = None,
        *,
        end_fmt: str | None = None,
        mid_fmt: str | None = None,
    ) -> None:
        """Update symbol, unit, numeric range, and optionally the colormap."""
        if colormap is not None:
            self._validate_colormap(colormap)
            self._colormap = colormap
        self._symbol_html = symbol_html
        self._unit = _format_unit(unit)
        self._vmin = float(vmin)
        self._vmax = float(vmax)
        self._end_fmt = end_fmt
        self._mid_fmt = mid_fmt
        self.update()

    def set_range(self, vmin: float, vmax: float) -> None:
        """Update the displayed numeric range ``(vmin, vmax)``."""
        self._vmin = float(vmin)
        self._vmax = float(vmax)
        self.update()

    def set_colormap(self, name: str) -> None:
        """Select one of the four curated colormaps by name."""
        self._validate_colormap(name)
        self._colormap = name
        self.update()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the colorbar card."""
        self._tokens.update(tokens)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        t = self._tokens

        # Card surface and 1-device-pixel border
        card_rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        painter.setBrush(QColor(t["popover"]))
        painter.setPen(QPen(QColor(t["border"]), 0.5))
        painter.drawRoundedRect(card_rect, 11.0, 11.0)

        # Top-left ISO 80000-1 quantity symbol
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        sym_font = QFont("Helvetica Neue")
        sym_font.setPixelSize(14)
        sym_font.setWeight(QFont.Weight.DemiBold)
        doc.setDefaultFont(sym_font)
        doc.setHtml(
            f'<div style="color:{t["fg"]}; font-size:14px; font-weight:600; '
            f'white-space:nowrap;">{self._symbol_html}</div>'
        )
        painter.save()
        sym_h = doc.size().height()
        painter.translate(15.0, 11.0 + max(0.0, (22.0 - sym_h) / 2.0))
        doc.drawContents(painter)
        painter.restore()

        # Top-right upright unit
        if self._unit:
            f_unit = QFont("Helvetica Neue")
            f_unit.setPixelSize(11.5)
            painter.setFont(f_unit)
            painter.setPen(QColor(t["tert"]))
            painter.drawText(
                QRectF(15.0, 12.0, w - 30.0, 19.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._unit,
            )

        # Header divider
        painter.setPen(QPen(QColor(t["border"]), 0.5))
        painter.drawLine(QPointF(15.0, 41.0), QPointF(w - 15.0, 41.0))

        # Vertical gradient bar
        bx, by, bw = 16.0, 56.0, 16.0
        bh = max(40.0, h - 76.0)
        cmap = mpl.colormaps[self._colormap]
        grad = QLinearGradient(bx, by, bx, by + bh)
        steps = 32
        for idx in range(steps + 1):
            frac = idx / steps
            r, g, b, _ = cmap(1.0 - frac)
            grad.setColorAt(frac, QColor.fromRgbF(r, g, b))
        bar_path = QPainterPath()
        bar_path.addRoundedRect(QRectF(bx, by, bw, bh), 4.5, 4.5)
        painter.fillPath(bar_path, QBrush(grad))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(t["border_strong"]), 0.5))
        painter.drawPath(bar_path)

        # Endpoint and interior ticks
        lo, hi = self._vmin, self._vmax
        span = hi - lo
        auto_end, auto_mid = _auto_tick_formats(span if span > 0 else 1.0)
        end_fmt = self._end_fmt or auto_end
        mid_fmt = self._mid_fmt or auto_mid

        if span > 0.0 and math.isfinite(span):
            raw_inner = MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10]).tick_values(lo, hi)
            inner = [
                tick for tick in raw_inner if lo + 0.09 * span < tick < hi - 0.09 * span
            ]
            ticks = (
                [(hi, _fmt_iso(hi, end_fmt), True)]
                + [(tick, _fmt_iso(tick, mid_fmt), False) for tick in reversed(inner)]
                + [(lo, _fmt_iso(lo, end_fmt), True)]
            )
        else:
            ticks = [
                (hi, _fmt_iso(hi, end_fmt), True),
                (lo, _fmt_iso(lo, end_fmt), True),
            ]

        f_end = QFont("Helvetica Neue")
        f_end.setPixelSize(13)
        f_end.setWeight(QFont.Weight.DemiBold)
        f_end.setFeature(QFont.Tag("tnum"), 1)

        f_mid = QFont("Helvetica Neue")
        f_mid.setPixelSize(12)
        f_mid.setFeature(QFont.Tag("tnum"), 1)

        tx0 = bx + bw + 6.0
        for idx, (val, txt, is_end) in enumerate(ticks):
            if span > 0.0 and math.isfinite(span):
                frac_y = (hi - val) / span
            else:
                frac_y = 0.0 if idx == 0 else 1.0
            yy = by + frac_y * bh
            painter.setPen(
                QPen(
                    QColor(t["fg"] if is_end else t["border_strong"]),
                    0.85 if is_end else 0.55,
                )
            )
            painter.drawLine(QPointF(tx0, yy), QPointF(tx0 + (5.5 if is_end else 3.5), yy))
            painter.setFont(f_end if is_end else f_mid)
            painter.setPen(QColor(t["fg"] if is_end else t["tert"]))
            painter.drawText(
                QRectF(tx0 + 8.0, yy - 9.0, w - tx0 - 20.0, 18.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                txt,
            )

        painter.end()

    @staticmethod
    def _validate_colormap(name: str) -> None:
        if name not in CURATED_COLORMAPS:
            raise ValueError(
                f"Unsupported colormap {name!r}; expected one of {CURATED_COLORMAPS}"
            )


@dataclass(frozen=True)
class PortAnchor:
    """Screen-space anchor for one 3D port label chip."""

    key: str
    label: str
    side: str
    outer: tuple[float, float]
    inner: tuple[float, float] | None = None
    visible: bool = True


class PortChip(QFrame):
    """Floating pill chip showing a fluid-side color dot and port label."""

    def __init__(
        self,
        label: str,
        side: str = "A",
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._side = side

        self.setObjectName("portChip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 9, 3)
        layout.setSpacing(6)

        self._dot = QLabel()
        self._dot.setStyleSheet("background: transparent;")
        layout.addWidget(self._dot)

        self._label = QLabel(label)
        _enable_tnum(self._label)
        layout.addWidget(self._label)

        self.apply_theme(self._tokens)

    def set_label(self, text: str) -> None:
        """Update the chip text and resize to fit."""
        self._label.setText(text)
        self.adjustSize()

    def set_side(self, side: str) -> None:
        """Set the fluid side (``'A'`` or ``'B'``) that selects the dot color."""
        self._side = side
        self._refresh_dot()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the port chip."""
        self._tokens.update(tokens)
        self._label.setStyleSheet(
            f"color: {self._tokens['fg']}; font-size: 12px; font-weight: 600; "
            "background: transparent;"
        )
        self._refresh_dot()
        self.adjustSize()
        self.update()

    def _refresh_dot(self) -> None:
        color_key = "inlet_a" if self._side == "A" else "inlet_b"
        pm = _dot_pixmap(self._tokens[color_key], 6.5)
        self._dot.setPixmap(pm)
        self._dot.setFixedSize(int(pm.width() / pm.devicePixelRatio()), int(pm.height() / pm.devicePixelRatio()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["popover"]))
        painter.setPen(QPen(QColor(self._tokens["border_strong"]), 0.5))
        painter.drawRoundedRect(rect, 7.0, 7.0)
        painter.end()


def place_port_chip(
    outer: tuple[float, float],
    chip_size: QSize | tuple[int, int],
    viewport_size: QSize | tuple[int, int],
    *,
    inner: tuple[float, float] | None = None,
    obstacles: Sequence[QRect] = (),
    margins: tuple[int, int, int, int] = (16, 68, 16, 68),
    gap: int = 12,
    arrow_clearance: int = 4,
) -> QRect:
    """Compute a screen rectangle for a port chip that never covers its arrow.

    Places the chip past ``outer`` along the outward direction ``outer - inner``
    (or away from viewport center when ``inner`` is omitted). When the primary
    placement leaves the safe viewport box or overlaps an obstacle, tests
    perpendicular offsets around ``outer`` while rejecting placements that
    intersect the arrow segment ``[inner, outer]``.
    """
    tw, th = (
        (chip_size.width(), chip_size.height())
        if isinstance(chip_size, QSize)
        else (int(chip_size[0]), int(chip_size[1]))
    )
    vw, vh = (
        (viewport_size.width(), viewport_size.height())
        if isinstance(viewport_size, QSize)
        else (int(viewport_size[0]), int(viewport_size[1]))
    )
    ox, oy = float(outer[0]), float(outer[1])
    ml, mt, mr, mb = margins
    safe = QRect(ml, mt, max(tw, vw - ml - mr), max(th, vh - mt - mb))

    ref = inner if inner is not None else (vw * 0.5, vh * 0.5)
    dx = ox - float(ref[0])
    dy = oy - float(ref[1])

    # Build ordered candidate placements: primary outward side first, then perpendicular sides.
    left_rect = QRect(int(round(ox - tw - gap)), int(round(oy - th / 2.0)), tw, th)
    right_rect = QRect(int(round(ox + gap)), int(round(oy - th / 2.0)), tw, th)
    above_rect = QRect(int(round(ox - tw / 2.0)), int(round(oy - th - gap)), tw, th)
    below_rect = QRect(int(round(ox - tw / 2.0)), int(round(oy + gap)), tw, th)

    if abs(dx) >= abs(dy):
        primary = left_rect if dx < 0.0 else right_rect
        perp = (above_rect, below_rect) if dy <= 0.0 else (below_rect, above_rect)
        # Right-aligned or left-aligned perpendicular placements keep chips clear
        # of a right-edge colorbar or left-edge toolbar without touching the arrow.
        edge_x = int(round(ox - tw)) if dx >= 0.0 else int(round(ox))
        aligned_above = QRect(edge_x, int(round(oy - th - gap)), tw, th)
        aligned_below = QRect(edge_x, int(round(oy + gap)), tw, th)
        candidates: list[QRect] = [primary, perp[0], perp[1], aligned_above, aligned_below]
    else:
        primary = above_rect if dy < 0.0 else below_rect
        perp = (right_rect, left_rect) if dx >= 0.0 else (left_rect, right_rect)
        candidates = [primary, perp[0], perp[1]]

    # Add obstacle-cleared nudges beside any obstacle blocking the primary/perpendicular slots.
    for obs in obstacles:
        for base in (above_rect, below_rect):
            if _overlap_area(base, obs) > 0:
                candidates.append(QRect(obs.left() - tw - 8, base.top(), tw, th))
                candidates.append(QRect(obs.right() + 9, base.top(), tw, th))

    def _clamped(rect: QRect) -> QRect:
        x = max(safe.left(), min(safe.right() - tw + 1, rect.left()))
        y = max(safe.top(), min(safe.bottom() - th + 1, rect.top()))
        return QRect(x, y, tw, th)

    def _hits_arrow(rect: QRect) -> bool:
        if inner is None:
            return rect.adjusted(-arrow_clearance, -arrow_clearance, arrow_clearance, arrow_clearance).contains(
                int(round(ox)), int(round(oy))
            )
        return _segment_intersects_rect(inner, outer, rect, pad=arrow_clearance)

    best_rect = _clamped(candidates[0])
    best_score: tuple[int, int, int, int] | None = None

    for rank, raw in enumerate(candidates):
        for shifted_flag, cand in ((0, raw), (1, _clamped(raw))):
            arrow_hit = 1 if _hits_arrow(cand) else 0
            obs_area = sum(_overlap_area(cand, obs) for obs in obstacles)
            out_x = max(0, safe.left() - cand.left()) + max(0, cand.right() - safe.right())
            out_y = max(0, safe.top() - cand.top()) + max(0, cand.bottom() - safe.bottom())
            out_pen = out_x + out_y
            score = (arrow_hit, obs_area, out_pen, rank * 2 + shifted_flag)
            if best_score is None or score < best_score:
                best_score = score
                best_rect = cand
            if score[:3] == (0, 0, 0):
                return cand

    return best_rect


class PortChipOverlay(QWidget):
    """Transparent overlay widget that anchors and lays out 3D port chips."""

    def __init__(
        self,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._anchors: list[PortAnchor] = []
        self._chips: dict[str, PortChip] = {}
        self._obstacles: list[QRect] = []
        self._margins: tuple[int, int, int, int] = (16, 68, 16, 68)

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_anchors(self, anchors: Sequence[PortAnchor]) -> None:
        """Replace port anchors and reposition every chip."""
        self._anchors = list(anchors)
        active_keys = {a.key for a in self._anchors}
        for key in list(self._chips):
            if key not in active_keys:
                self._chips.pop(key).deleteLater()
        for anchor in self._anchors:
            chip = self._chips.get(anchor.key)
            if chip is None:
                chip = PortChip(anchor.label, anchor.side, tokens=self._tokens, parent=self)
                self._chips[anchor.key] = chip
            else:
                chip.set_label(anchor.label)
                chip.set_side(anchor.side)
            chip.setVisible(anchor.visible)
        self._relayout()

    def set_obstacles(self, rects: Sequence[QRect]) -> None:
        """Set screen rectangles (such as colorbar or toolbars) that chips avoid."""
        self._obstacles = [QRect(r) for r in rects]
        self._relayout()

    def set_safe_margins(self, left: int, top: int, right: int, bottom: int) -> None:
        """Set the viewport edge margins used during chip placement."""
        self._margins = (int(left), int(top), int(right), int(bottom))
        self._relayout()

    def chip_geometries(self) -> dict[str, QRect]:
        """Return the current geometry of each visible port chip by key."""
        return {
            key: chip.geometry()
            for key, chip in self._chips.items()
            if not chip.isHidden()
        }

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to every port chip."""
        self._tokens.update(tokens)
        for chip in self._chips.values():
            chip.apply_theme(self._tokens)
        self._relayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        placed: list[QRect] = list(self._obstacles)
        vp = self.size()
        for anchor in self._anchors:
            chip = self._chips.get(anchor.key)
            if chip is None or not anchor.visible:
                continue
            chip.adjustSize()
            rect = place_port_chip(
                anchor.outer,
                chip.size(),
                vp,
                inner=anchor.inner,
                obstacles=placed,
                margins=self._margins,
            )
            chip.setGeometry(rect)
            placed.append(rect.adjusted(-4, -4, 4, 4))


class LatticeProgressCard(QFrame):
    """Non-blocking lattice build progress card with cancel action (screen F20)."""

    cancel_requested = Signal()

    def __init__(
        self,
        *,
        title: str = "构建晶格",
        detail: str = "",
        progress: float = 0.0,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._progress = max(0.0, min(1.0, float(progress)))

        self.setObjectName("latticeProgressCard")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 5, 8, 5)
        layout.setSpacing(9)

        self._dot = QLabel()
        self._dot.setStyleSheet("background: transparent;")
        layout.addWidget(self._dot)

        self._title_label = QLabel(title)
        layout.addWidget(self._title_label)

        self._detail_label = QLabel(detail)
        _enable_tnum(self._detail_label)
        self._detail_label.setVisible(bool(detail))
        layout.addWidget(self._detail_label)

        self._bar = _ThinProgressBar(self._progress, self._tokens, width=104)
        layout.addWidget(self._bar)

        self._sep = _VerticalHairline(self._tokens["border"], height=16)
        layout.addWidget(self._sep)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setObjectName("latticeCancelButton")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self._cancel_btn)

        self.apply_theme(self._tokens)

    def progress(self) -> float:
        """Return the current completion fraction in ``[0.0, 1.0]``."""
        return self._progress

    def detail(self) -> str:
        """Return the current build stage detail string."""
        return self._detail_label.text()

    def set_progress(
        self,
        fraction: float,
        detail: str | None = None,
        *,
        title: str | None = None,
    ) -> None:
        """Update progress fraction and optional title or stage text."""
        self._progress = max(0.0, min(1.0, float(fraction)))
        self._bar.set_progress(self._progress)
        if title is not None:
            self._title_label.setText(title)
        if detail is not None:
            self._detail_label.setText(detail)
            self._detail_label.setVisible(bool(detail))
        self.adjustSize()

    def set_stage(
        self,
        domain_label: str,
        stage_label: str,
        step: int,
        total: int,
        fraction: float | None = None,
    ) -> None:
        """Format a multi-stage lattice build status line and update progress."""
        detail = f"{domain_label} · {stage_label} {step}/{total}"
        frac = (step / total) if (fraction is None and total > 0) else (fraction or 0.0)
        self.set_progress(frac, detail=detail)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the progress card."""
        self._tokens.update(tokens)
        t = self._tokens
        pm = _dot_pixmap(t["accent_fg"], 6.5)
        self._dot.setPixmap(pm)
        self._dot.setFixedSize(
            int(pm.width() / pm.devicePixelRatio()),
            int(pm.height() / pm.devicePixelRatio()),
        )
        self._title_label.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; font-weight: 600; background: transparent;"
        )
        self._detail_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 12px; font-weight: 500; background: transparent;"
        )
        self._bar.apply_theme(t)
        self._sep.set_color(t["border"])
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {t['sub']}; "
            f"min-height: 24px; max-height: 24px; padding: 0 8px; font-size: 12px; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {t['sunken']}; color: {t['fg']}; }}"
        )
        self.adjustSize()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["popover"]))
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawRoundedRect(rect, 9.0, 9.0)
        painter.end()


class LatticeDomainCard(QFrame):
    """Floating ready-state lattice domain and cache badge (screens F06 and F07)."""

    def __init__(
        self,
        domain_name: str = "",
        rule_html: str = "",
        triangles: int = 0,
        *,
        cached: bool = True,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._cached = cached

        self.setObjectName("latticeDomainCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 11, 5)
        layout.setSpacing(8)

        self._domain_label = QLabel(domain_name)
        layout.addWidget(self._domain_label)

        self._rule_label = QLabel(rule_html)
        if "<" in rule_html:
            self._rule_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._rule_label)

        self._sep1 = QLabel("·")
        layout.addWidget(self._sep1)

        self._tri_label = QLabel(_format_triangles(triangles))
        _enable_tnum(self._tri_label)
        layout.addWidget(self._tri_label)

        self._sep2 = QLabel("·")
        layout.addWidget(self._sep2)

        self._cache_box = QWidget()
        self._cache_box.setStyleSheet("background: transparent;")
        c_lay = QHBoxLayout(self._cache_box)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(5)
        self._cache_dot = QLabel()
        self._cache_dot.setStyleSheet("background: transparent;")
        self._cache_label = QLabel("已缓存")
        c_lay.addWidget(self._cache_dot)
        c_lay.addWidget(self._cache_label)
        layout.addWidget(self._cache_box)

        self._sync_cache_visibility()
        self.apply_theme(self._tokens)

    def set_domain_info(
        self,
        domain_name: str,
        rule_html: str,
        triangles: int,
        *,
        cached: bool = True,
    ) -> None:
        """Update the displayed lattice domain summary."""
        self._domain_label.setText(domain_name)
        self._rule_label.setTextFormat(
            Qt.TextFormat.RichText if "<" in rule_html else Qt.TextFormat.PlainText
        )
        self._rule_label.setText(rule_html)
        self._tri_label.setText(_format_triangles(triangles))
        self._cached = cached
        self._sync_cache_visibility()
        self.adjustSize()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the lattice domain card."""
        self._tokens.update(tokens)
        t = self._tokens
        self._domain_label.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; font-weight: 600; background: transparent;"
        )
        sub_qss = (
            f"color: {t['sub']}; font-size: 12.5px; font-weight: 500; background: transparent;"
        )
        self._rule_label.setStyleSheet(sub_qss)
        self._tri_label.setStyleSheet(sub_qss)
        self._cache_label.setStyleSheet(sub_qss)
        sep_qss = (
            f"color: {t['tert']}; font-size: 12.5px; font-weight: 500; background: transparent;"
        )
        self._sep1.setStyleSheet(sep_qss)
        self._sep2.setStyleSheet(sep_qss)
        pm = _dot_pixmap(t["ok"], 6.0)
        self._cache_dot.setPixmap(pm)
        self._cache_dot.setFixedSize(
            int(pm.width() / pm.devicePixelRatio()),
            int(pm.height() / pm.devicePixelRatio()),
        )
        self.adjustSize()
        self.update()

    def _sync_cache_visibility(self) -> None:
        self._sep2.setVisible(self._cached)
        self._cache_box.setVisible(self._cached)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["popover"]))
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawRoundedRect(rect, 9.0, 9.0)
        painter.end()
