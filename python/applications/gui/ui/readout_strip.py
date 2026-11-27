"""Two-tier instrument readout strip pinned at the bottom of a page sheet."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from sjtu_tpmshx.applications.gui.ui.theme import get_theme

STRIP_HEIGHT = 52

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


def _status_pixmap(kind: str, tokens: Mapping[str, Any], size: float = 6.5) -> tuple[QPixmap, int]:
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
    return pixmap, side


def _set_status_mark(lab: QLabel, kind: str, tokens: Mapping[str, Any], size: float = 6.5) -> None:
    pixmap, side = _status_pixmap(kind, tokens, size=size)
    lab.setPixmap(pixmap)
    lab.setFixedSize(side, side)


class _VerticalHairline(QWidget):
    """Single-device-pixel vertical divider between readout cells."""

    def __init__(self, color_hex: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self.setFixedWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def set_color(self, color_hex: str) -> None:
        color = QColor(color_hex)
        if color != self._color:
            self._color = color
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.25, 0.0), QPointF(0.25, float(self.height())))
        painter.end()


def _update_label(
    lab: QLabel,
    text: str,
    size_px: float,
    color_hex: str,
    weight: int = 400,
) -> None:
    fmt = Qt.TextFormat.RichText if "<" in text else Qt.TextFormat.PlainText
    if lab.textFormat() != fmt:
        lab.setTextFormat(fmt)
    if lab.text() != text:
        lab.setText(text)
    qss = (
        f"color: {color_hex}; font-size: {int(round(size_px))}px; font-weight: {weight}; "
        "background: transparent;"
    )
    if lab.styleSheet() != qss:
        lab.setStyleSheet(qss)


def _make_label(
    text: str,
    size_px: float,
    color_hex: str,
    weight: int = 400,
) -> QLabel:
    lab = QLabel()
    _enable_tnum(lab)
    _update_label(lab, text, size_px, color_hex, weight=weight)
    return lab


class _ReadoutCell:
    """Reusable metric cell widgets and leading vertical divider."""

    def __init__(self, tokens: Mapping[str, Any]) -> None:
        self.sep = _VerticalHairline(tokens["border"])
        self.cell = QWidget()
        self.cell.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self.cell)
        self._layout.setSpacing(1)

        self.name_label = _make_label("", 11.0, tokens["sub"], weight=500)
        self._layout.addWidget(self.name_label)

        val_row = QHBoxLayout()
        val_row.setContentsMargins(0, 0, 0, 0)
        val_row.setSpacing(4)
        self.value_label = _make_label("", 14.0, tokens["fg"], weight=600)
        self.unit_label = _make_label("", 11.0, tokens["tert"], weight=400)
        val_row.addWidget(self.value_label)
        val_row.addWidget(self.unit_label)
        val_row.addStretch(1)
        self._layout.addLayout(val_row)

    def update_state(
        self,
        item: ReadoutItem,
        tokens: Mapping[str, Any],
        *,
        first_without_stale: bool,
        show_sep: bool,
        compact: bool,
    ) -> None:
        self.sep.set_color(tokens["border"])
        self.sep.setVisible(show_sep)

        if first_without_stale:
            pad_l = 14 if compact else 18
        else:
            pad_l = 12 if compact else 16
        pad_r = 12 if compact else 18
        self._layout.setContentsMargins(pad_l, 6, pad_r, 6)

        val_size = 13.5 if compact else 14.0
        tone_hex = tokens[item.tone] if item.tone in tokens else tokens["fg"]
        _update_label(self.name_label, item.name, 11.0, tokens["sub"], weight=500)
        _update_label(self.value_label, item.value, val_size, tone_hex, weight=600)
        if item.unit:
            _update_label(self.unit_label, item.unit, 11.0, tokens["tert"], weight=400)
            self.unit_label.show()
        else:
            self.unit_label.hide()
        self.cell.show()

    def hide(self) -> None:
        self.sep.hide()
        self.cell.hide()


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
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._items: list[ReadoutItem] = list(items)
        self._notice: ReadoutNotice | None = notice
        self._stale = stale
        self._stale_text = stale_text
        self._compact = compact
        self._stale_dot_key: tuple[str, str] | None = None
        self._notice_dot_key: tuple[str, str] | None = None

        self.setObjectName("readoutStrip")
        self.setFixedHeight(STRIP_HEIGHT)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 1, 0, 0)
        self._layout.setSpacing(0)

        self._build_static_structure()
        self._sync_ui()

    def _build_static_structure(self) -> None:
        t = self._tokens

        self._stale_box = QWidget()
        self._stale_box.setStyleSheet("background: transparent;")
        self._stale_layout = QHBoxLayout(self._stale_box)
        self._stale_layout.setSpacing(6)
        self._stale_dot = QLabel()
        self._stale_dot.setStyleSheet("background: transparent;")
        self._stale_label = _make_label("", 12.0, t["warn"], weight=600)
        self._stale_layout.addWidget(self._stale_dot)
        self._stale_layout.addWidget(self._stale_label)
        self._stale_sep = _VerticalHairline(t["border"])
        self._layout.addWidget(self._stale_box)
        self._layout.addWidget(self._stale_sep)

        self._cells_host = QWidget()
        self._cells_host.setStyleSheet("background: transparent;")
        self._cells_layout = QHBoxLayout(self._cells_host)
        self._cells_layout.setContentsMargins(0, 0, 0, 0)
        self._cells_layout.setSpacing(0)
        self._cells: list[_ReadoutCell] = []
        self._layout.addWidget(self._cells_host)

        self._layout.addStretch(1)

        self._notice_sep = _VerticalHairline(t["border"])
        self._notice_box = QWidget()
        self._notice_box.setStyleSheet("background: transparent;")
        self._notice_layout = QVBoxLayout(self._notice_box)
        self._notice_layout.setSpacing(1)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(5)
        self._notice_dot = QLabel()
        self._notice_dot.setStyleSheet("background: transparent;")
        self._notice_title = _make_label("", 11.0, t["warn"], weight=600)
        head.addWidget(self._notice_dot)
        head.addWidget(self._notice_title)
        head.addStretch(1)
        self._notice_layout.addLayout(head)
        self._notice_detail = _make_label("", 11.5, t["sub"], weight=500)
        self._notice_layout.addWidget(self._notice_detail)
        self._layout.addWidget(self._notice_sep)
        self._layout.addWidget(self._notice_box)

    def items(self) -> list[ReadoutItem]:
        """Return a copy of the current readout items."""
        return list(self._items)

    def notice(self) -> ReadoutNotice | None:
        """Return the current right-end status notice, if any."""
        return self._notice

    def is_stale(self) -> bool:
        """Return True when the leading stale-input indicator is active."""
        return self._stale

    def set_items(self, items: Sequence[ReadoutItem]) -> None:
        """Replace the readout cells with a new sequence of metrics."""
        updated = list(items)
        if updated == self._items:
            return
        self._items = updated
        self._sync_ui()

    def set_notice(self, notice: ReadoutNotice | None) -> None:
        """Set or clear the right-end status notice."""
        if notice == self._notice:
            return
        self._notice = notice
        self._sync_ui()

    def set_stale(self, stale: bool, text: str = "输入已修改") -> None:
        """Show or hide the leading stale-input indicator."""
        stale = bool(stale)
        if stale == self._stale and text == self._stale_text:
            return
        self._stale = stale
        self._stale_text = text
        self._sync_ui()

    def set_compact(self, compact: bool) -> None:
        """Adjust horizontal padding and value size for narrow viewports."""
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self._sync_ui()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the readout strip."""
        updated = dict(self._tokens)
        updated.update(tokens)
        if updated == self._tokens:
            return
        self._tokens = updated
        self._sync_ui()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()

    def _sync_ui(self) -> None:
        t = self._tokens
        frame_qss = (
            f"QFrame#readoutStrip {{ background: {t['sunken']}; border: none; "
            "border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; }"
        )
        if self.styleSheet() != frame_qss:
            self.setStyleSheet(frame_qss)

        if self._stale:
            pad_h = 12 if self._compact else 16
            self._stale_layout.setContentsMargins(pad_h, 0, pad_h, 0)
            stale_key = ("warn", t[_STATUS_COLOR_KEY["warn"]])
            if self._stale_dot_key != stale_key:
                _set_status_mark(self._stale_dot, "warn", t, size=6.5)
                self._stale_dot_key = stale_key
            _update_label(self._stale_label, self._stale_text, 12.0, t["warn"], weight=600)
            self._stale_sep.set_color(t["border"])
            self._stale_box.show()
            self._stale_sep.show()
        else:
            self._stale_box.hide()
            self._stale_sep.hide()

        while len(self._cells) < len(self._items):
            cell = _ReadoutCell(t)
            self._cells.append(cell)
            self._cells_layout.addWidget(cell.sep)
            self._cells_layout.addWidget(cell.cell)
        for idx, cell in enumerate(self._cells):
            if idx < len(self._items):
                cell.update_state(
                    self._items[idx],
                    t,
                    first_without_stale=(idx == 0 and not self._stale),
                    show_sep=(idx > 0),
                    compact=self._compact,
                )
            else:
                cell.hide()

        if self._notice is not None:
            self._notice_sep.set_color(t["border"])
            self._notice_layout.setContentsMargins(
                14 if self._compact else 16,
                6,
                16 if self._compact else 18,
                6,
            )
            notice_color = t[_STATUS_COLOR_KEY[self._notice.kind]]
            notice_key = (self._notice.kind, notice_color)
            if self._notice_dot_key != notice_key:
                _set_status_mark(self._notice_dot, self._notice.kind, t, size=6.0)
                self._notice_dot_key = notice_key
            _update_label(self._notice_title, self._notice.title, 11.0, notice_color, weight=600)
            _update_label(self._notice_detail, self._notice.detail, 11.5, t["sub"], weight=500)
            self._notice_sep.show()
            self._notice_box.show()
        else:
            self._notice_sep.hide()
            self._notice_box.hide()

        self.update()
