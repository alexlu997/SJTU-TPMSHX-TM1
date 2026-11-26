"""Two-tier instrument readout strip pinned at the bottom of a page sheet."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

STRIP_HEIGHT = 52

_DEFAULT_TOKENS: dict[str, Any] = {
    "sunken": "#EFEEEA",
    "border": "#D9D8D4",
    "fg": "#181715",
    "sub": "#474643",
    "tert": "#686663",
    "accent_fg": "#0B5161",
    "ok": "#176B3E",
    "warn": "#96530C",
    "err": "#B43025",
}

_STATUS_COLOR_KEY: dict[str, str] = {
    "ok": "ok",
    "warn": "warn",
    "err": "err",
    "run": "accent_fg",
    "idle": "tert",
}


@dataclass(frozen=True)
class ReadoutItem:
    """Single two-tier metric cell with label above value and optional unit."""

    name: str
    value: str
    unit: str = ""
    tone: str = "fg"


@dataclass(frozen=True)
class ReadoutNotice:
    """Right-aligned status or extrapolation notice shown on the readout strip."""

    title: str
    detail: str
    kind: str = "warn"


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


def _status_mark(kind: str, tokens: Mapping[str, Any], size: float = 6.5) -> QLabel:
    color = QColor(tokens[_STATUS_COLOR_KEY[kind]])
    side = int(size) + 2
    pixmap = QPixmap(side * 3, side * 3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    if kind == "warn":
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(side / 2, 1.0),
                    QPointF(side - 1.0, side - 1.4),
                    QPointF(1.0, side - 1.4),
                ]
            )
        )
    else:
        painter.drawEllipse(QPointF(side / 2, side / 2), size / 2, size / 2)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    lab = QLabel()
    lab.setPixmap(pixmap)
    lab.setFixedSize(side, side)
    lab.setStyleSheet("background: transparent;")
    return lab


class _VerticalHairline(QWidget):
    """Single-device-pixel vertical divider between readout cells."""

    def __init__(self, color_hex: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self.setFixedWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.25, 0.0), QPointF(0.25, float(self.height())))
        painter.end()


def _make_label(
    text: str,
    size_px: float,
    color_hex: str,
    weight: int = 400,
) -> QLabel:
    lab = QLabel(text)
    if "<" in text:
        lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setStyleSheet(
        f"color: {color_hex}; font-size: {size_px}px; font-weight: {weight}; "
        "background: transparent;"
    )
    _enable_tnum(lab)
    return lab


class ReadoutStrip(QFrame):
    """Two-tier instrument deck showing metric names above tabular values and units."""

    def __init__(
        self,
        items: Sequence[ReadoutItem] = (),
        *,
        notice: ReadoutNotice | None = None,
        stale: bool = False,
        stale_text: str = "输入已修改",
        compact: bool = False,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(_DEFAULT_TOKENS)
        if tokens is not None:
            self._tokens.update(tokens)
        self._items: list[ReadoutItem] = list(items)
        self._notice: ReadoutNotice | None = notice
        self._stale = stale
        self._stale_text = stale_text
        self._compact = compact

        self.setObjectName("readoutStrip")
        self.setFixedHeight(STRIP_HEIGHT)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 1, 0, 0)
        self._layout.setSpacing(0)

        self._rebuild()

    def set_items(self, items: Sequence[ReadoutItem]) -> None:
        """Replace the readout cells with a new sequence of metrics."""
        self._items = list(items)
        self._rebuild()

    def set_notice(self, notice: ReadoutNotice | None) -> None:
        """Set or clear the right-end status notice."""
        self._notice = notice
        self._rebuild()

    def set_stale(self, stale: bool, text: str = "输入已修改") -> None:
        """Show or hide the leading stale-input indicator."""
        self._stale = stale
        self._stale_text = text
        self._rebuild()

    def set_compact(self, compact: bool) -> None:
        """Adjust horizontal padding and value size for narrow viewports."""
        self._compact = compact
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the readout strip."""
        self._tokens.update(tokens)
        self._rebuild()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_layout()
        t = self._tokens
        self.setStyleSheet(
            f"QFrame#readoutStrip {{ background: {t['sunken']}; border: none; "
            "border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; }"
        )

        if self._stale:
            stale_box = QWidget()
            stale_box.setStyleSheet("background: transparent;")
            stl = QHBoxLayout(stale_box)
            pad_h = 12 if self._compact else 16
            stl.setContentsMargins(pad_h, 0, pad_h, 0)
            stl.setSpacing(6)
            stl.addWidget(_status_mark("warn", t, size=6.5))
            stl.addWidget(_make_label(self._stale_text, 12.0, t["warn"], weight=600))
            self._layout.addWidget(stale_box)
            self._layout.addWidget(_VerticalHairline(t["border"]))

        val_size = 13.5 if self._compact else 14.0
        for idx, item in enumerate(self._items):
            if idx:
                self._layout.addWidget(_VerticalHairline(t["border"]))
            cell = QWidget()
            cell.setStyleSheet("background: transparent;")
            cl = QVBoxLayout(cell)
            if idx == 0 and not self._stale:
                pad_l = 14 if self._compact else 18
            else:
                pad_l = 12 if self._compact else 16
            pad_r = 12 if self._compact else 18
            cl.setContentsMargins(pad_l, 6, pad_r, 6)
            cl.setSpacing(1)

            cl.addWidget(_make_label(item.name, 11.0, t["sub"], weight=500))

            val_row = QHBoxLayout()
            val_row.setContentsMargins(0, 0, 0, 0)
            val_row.setSpacing(4)
            tone_hex = t[item.tone] if item.tone in t else t["fg"]
            val_row.addWidget(_make_label(item.value, val_size, tone_hex, weight=600))
            if item.unit:
                val_row.addWidget(_make_label(item.unit, 11.0, t["tert"], weight=400))
            val_row.addStretch(1)
            cl.addLayout(val_row)

            self._layout.addWidget(cell)

        self._layout.addStretch(1)

        if self._notice is not None:
            self._layout.addWidget(_VerticalHairline(t["border"]))
            notice_box = QWidget()
            notice_box.setStyleSheet("background: transparent;")
            nl = QVBoxLayout(notice_box)
            nl.setContentsMargins(
                14 if self._compact else 16,
                6,
                16 if self._compact else 18,
                6,
            )
            nl.setSpacing(1)

            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(5)
            head.addWidget(_status_mark(self._notice.kind, t, size=6.0))
            title_color = t[_STATUS_COLOR_KEY[self._notice.kind]]
            head.addWidget(_make_label(self._notice.title, 11.0, title_color, weight=600))
            head.addStretch(1)
            nl.addLayout(head)

            nl.addWidget(_make_label(self._notice.detail, 11.5, t["sub"], weight=500))
            self._layout.addWidget(notice_box)

        self.update()
