"""Floating run-information popover opened from the header status badge."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tm1.applications.gui.ui.theme import get_theme

POPOVER_WIDTH = 344

_STATUS_COLOR_KEY: dict[str, str] = {
    "ok": "ok",
    "warn": "warn",
    "err": "err",
    "run": "accent_fg",
    "idle": "tert",
}

_ICON_PATHS: dict[str, str] = {
    "log": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8M16 17H8M10 9H8"/>'
    ),
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "folder": (
        '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 '
        '2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>'
    ),
}


@dataclass(frozen=True)
class RunInfoRow:
    """Single key-value metadata row inside ``RunInfoPopover``."""

    label: str
    value: str
    tone: str = "fg"
    weight: int = 500


@dataclass(frozen=True)
class RunInfoData:
    """Plain-value snapshot rendered by ``RunInfoPopover``."""

    info_rows: Sequence[RunInfoRow] = ()
    status_kind: str = "idle"
    status_text: str = ""
    status_rows: Sequence[RunInfoRow] = ()
    can_show_log: bool = True
    can_show_diagnostics: bool = True
    can_open_folder: bool = True


def _render_icon(name: str, color: str, size: int = 15, stroke: float = 1.55) -> QIcon:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICON_PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(size * 3, size * 3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return QIcon(pixmap)


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


def _status_mark(kind: str, tokens: Mapping[str, Any], size: float = 6.0) -> QLabel:
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


class _Hairline(QWidget):
    """Single-device-pixel horizontal divider inside a popover."""

    def __init__(self, color_hex: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()


def _make_label(text: str, size_px: float, color_hex: str, weight: int = 400) -> QLabel:
    lab = QLabel(text)
    if "<" in text:
        lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setStyleSheet(
        f"color: {color_hex}; font-size: {int(round(size_px))}px; font-weight: {weight}; "
        "background: transparent;"
    )
    _enable_tnum(lab)
    return lab


class RunInfoPopover(QFrame):
    """Floating popover that displays run metadata, solve status, and run actions."""

    log_requested = Signal()
    diagnostics_requested = Signal()
    open_folder_requested = Signal()

    def __init__(
        self,
        data: RunInfoData | None = None,
        *,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._data: RunInfoData = data or RunInfoData()

        self.setObjectName("runInfoPopover")
        self.setFixedWidth(POPOVER_WIDTH)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(1)

        self._rebuild()

    def set_data(self, data: RunInfoData) -> None:
        """Replace the displayed run metadata and action states."""
        self._data = data
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the popover."""
        self._tokens.update(tokens)
        self._rebuild()

    def popup_below(self, anchor: QWidget, offset_y: int = 6) -> None:
        """Open the popover below an anchor widget as a dismissible popup."""
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + offset_y))
        self.move(pos)
        self.show()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["popover"]))
        painter.setPen(QPen(QColor(self._tokens["border_strong"]), 0.5))
        painter.drawRoundedRect(rect, 11.0, 11.0)
        painter.end()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_group(self, title: str) -> None:
        lab = QLabel(title)
        lab.setContentsMargins(10, 7, 10, 3)
        lab.setStyleSheet(
            f"color: {self._tokens['tert']}; font-size: 11px; font-weight: 600; "
            "background: transparent;"
        )
        self._layout.addWidget(lab)

    def _add_separator(self) -> None:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.addWidget(_Hairline(self._tokens["border"]))
        self._layout.addWidget(wrap)

    def _add_kv_row(self, key_text: str, value_widget: QWidget) -> None:
        row = QFrame()
        row.setFixedHeight(27)
        row.setStyleSheet("background: transparent; border: none;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(10)
        hl.addWidget(_make_label(key_text, 12.0, self._tokens["sub"], weight=400))
        hl.addStretch(1)
        hl.addWidget(value_widget)
        self._layout.addWidget(row)

    def _add_action(self, icon_name: str, text: str, enabled: bool, callback) -> None:
        t = self._tokens
        btn = QPushButton()
        btn.setFixedHeight(32)
        btn.setEnabled(enabled)
        btn.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 7px; "
            "text-align: left; }"
            f"QPushButton:hover {{ background: {t['row_hover']}; }}"
        )
        hl = QHBoxLayout(btn)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(9)

        icon_color = t["sub"] if enabled else t["tert"]
        ic = QLabel()
        ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        ic.setPixmap(_render_icon(icon_name, icon_color, 15).pixmap(QSize(15, 15)))
        ic.setFixedSize(15, 15)
        ic.setStyleSheet("background: transparent;")
        hl.addWidget(ic)

        text_color = t["fg"] if enabled else t["tert"]
        lbl = _make_label(text, 12.5, text_color, weight=400)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl.addWidget(lbl)
        hl.addStretch(1)

        btn.clicked.connect(lambda _=False, cb=callback: self._trigger(cb))
        self._layout.addWidget(btn)

    def _trigger(self, callback) -> None:
        if self.windowFlags() & Qt.WindowType.Popup:
            self.hide()
        callback()

    def _rebuild(self) -> None:
        self._clear_layout()
        t = self._tokens
        d = self._data

        self._add_group("运行信息")
        for row in d.info_rows:
            color = t[row.tone] if row.tone in t else t["fg"]
            self._add_kv_row(row.label, _make_label(row.value, 12.0, color, weight=row.weight))

        if d.status_text or d.status_rows:
            self._add_separator()
            self._add_group("求解状态")
            if d.status_text:
                status_box = QWidget()
                status_box.setStyleSheet("background: transparent;")
                sl = QHBoxLayout(status_box)
                sl.setContentsMargins(0, 0, 0, 0)
                sl.setSpacing(6)
                sl.addWidget(_status_mark(d.status_kind, t, size=6.0))
                st_color = t[_STATUS_COLOR_KEY[d.status_kind]]
                sl.addWidget(_make_label(d.status_text, 12.0, st_color, weight=600))
                self._add_kv_row("状态", status_box)
            for row in d.status_rows:
                color = t[row.tone] if row.tone in t else t["fg"]
                self._add_kv_row(
                    row.label, _make_label(row.value, 12.0, color, weight=row.weight)
                )

        self._add_separator()
        self._add_action("log", "计算日志…", d.can_show_log, self.log_requested.emit)
        self._add_action(
            "activity", "诊断详情…", d.can_show_diagnostics, self.diagnostics_requested.emit
        )
        self._add_action(
            "folder", "打开运行目录", d.can_open_folder, self.open_folder_requested.emit
        )

        self.adjustSize()
        self.update()
