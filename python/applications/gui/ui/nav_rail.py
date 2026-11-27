"""Collapsed 64 px navigation rail and 232 px expanded rail in Style P2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.applications.gui.ui.theme import RADIUS_BTN, get_theme

RAIL_WIDTH = 64
EXPANDED_RAIL_WIDTH = 232

NAV_PAGES: tuple[tuple[str, str, str], ...] = (
    ("run", "算例", "算例计算"),
    ("result", "结果", "计算结果"),
    ("opt", "优化", "优化设计"),
    ("qd", "快速", "快速设计"),
)

RAIL_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("search", "搜索", "搜索命令", "Ctrl+K"),
    ("open", "载入", "载入", ""),
    ("save", "保存", "保存", ""),
    ("more", "设置", "设置", ""),
    ("expand", "展开", "收起导航", "Ctrl+\\"),
)

_FONT_DISP = '"Helvetica Neue", "PingFang SC", "Microsoft YaHei UI", "Segoe UI"'

_STATUS_COLOR_KEY: dict[str, str] = {
    "ok": "ok",
    "warn": "warn",
    "err": "err",
    "run": "accent_fg",
    "idle": "tert",
}

_ICON_PATHS: dict[str, str] = {
    "run": (
        '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 '
        '1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>'
        '<path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>'
    ),
    "result": (
        '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 '
        '1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/>'
        '<path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>'
    ),
    "opt": (
        '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><circle cx="8" cy="15" r="1.4"/>'
        '<circle cx="11.5" cy="10.5" r="1.4"/><circle cx="17" cy="7" r="1.4"/>'
        '<circle cx="16" cy="14.5" r="1.4"/>'
    ),
    "qd": (
        '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/>'
        '<path d="M3 15h18"/><path d="M9 9v12"/>'
    ),
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "open": (
        '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 '
        '1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 '
        '1.67.9H18a2 2 0 0 1 2 2v2"/>'
    ),
    "save": (
        '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 '
        '0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
        '<path d="M7 3v4a1 1 0 0 0 1 1h7"/>'
    ),
    "more": (
        '<path d="M10 5H3"/><path d="M12 19H3"/><path d="M14 3v4"/><path d="M16 17v4"/>'
        '<path d="M21 12h-9"/><path d="M21 19h-5"/><path d="M21 5h-7"/><path d="M8 10v4"/>'
        '<path d="M8 12H3"/>'
    ),
    "railOpen": (
        '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>'
        '<path d="m14 9 3 3-3 3"/>'
    ),
    "railClose": (
        '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>'
        '<path d="m16 9-3 3 3 3"/>'
    ),
    "ws": (
        '<rect width="7" height="7" x="3" y="3" rx="1"/>'
        '<rect width="7" height="7" x="14" y="3" rx="1"/>'
        '<rect width="7" height="7" x="14" y="14" rx="1"/>'
        '<rect width="7" height="7" x="3" y="14" rx="1"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
}


@dataclass(frozen=True)
class RecentRunItem:
    """Single recent-run entry shown in the expanded navigation rail."""

    run_id: str
    label: str
    summary_html: str = ""


def _render_icon(name: str, color: str, size: int = 18, stroke: float = 1.55) -> QIcon:
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


def _status_pixmap(kind: str, tokens: Mapping[str, Any], size: float = 6.0, halo: str | None = None) -> QPixmap:
    color = QColor(tokens[_STATUS_COLOR_KEY[kind]])
    pad = 2 if halo else 0
    side = int(size) + 2 + 2 * pad
    pixmap = QPixmap(side * 3, side * 3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    painter.setPen(Qt.PenStyle.NoPen)
    if halo:
        painter.setBrush(QColor(halo))
        painter.drawEllipse(QPointF(side / 2, side / 2), side / 2, side / 2)
    c0 = pad + 1
    painter.setBrush(color)
    if kind == "warn":
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(side / 2, c0),
                    QPointF(side - c0, side - c0 - 0.4),
                    QPointF(c0, side - c0 - 0.4),
                ]
            )
        )
    else:
        painter.drawEllipse(QPointF(side / 2, side / 2), size / 2, size / 2)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return pixmap


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


class _Hairline(QWidget):
    """Single-device-pixel horizontal rule."""

    def __init__(self, tokens: Mapping[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(tokens["border"])
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()


class _RailCell(QWidget):
    """Icon button with a centered short label and an optional status mark."""

    clicked = Signal()

    def __init__(self, icon_name: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._active = False
        self._open = False
        self._dot: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.button = QToolButton()
        self.button.setFixedSize(40, 30)
        self.button.setIconSize(QSize(18, 18))
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.clicked.emit)

        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._dot_label = QLabel(self.button)
        self._dot_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._dot_label.hide()

        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.label)

    def set_state(
        self,
        tokens: Mapping[str, Any],
        *,
        active: bool = False,
        opened: bool = False,
        dot: str | None = None,
    ) -> None:
        self._active = active
        self._open = opened
        self._dot = dot

        if active:
            icon_color = tokens["accent_fg"]
            btn_qss = (
                f"QToolButton {{ background: {tokens['popover']}; "
                f"border: 1px solid {tokens['border']}; border-radius: {RADIUS_BTN}px; }}"
                "QToolButton::menu-indicator { image: none; width: 0px; }"
            )
            lbl_qss = (
                f"QLabel {{ font-size: 11px; font-weight: 600; "
                f"color: {tokens['fg']}; background: transparent; }}"
            )
        elif opened:
            icon_color = tokens["fg"]
            btn_qss = (
                f"QToolButton {{ background: {tokens['hover']}; border: none; "
                f"border-radius: {RADIUS_BTN}px; }}"
                "QToolButton::menu-indicator { image: none; width: 0px; }"
            )
            lbl_qss = (
                f"QLabel {{ font-size: 11px; font-weight: 600; "
                f"color: {tokens['fg']}; background: transparent; }}"
            )
        else:
            icon_color = tokens["tert"]
            btn_qss = (
                f"QToolButton {{ background: transparent; border: none; "
                f"border-radius: {RADIUS_BTN}px; }}"
                f"QToolButton:hover {{ background: {tokens['hover']}; }}"
                "QToolButton::menu-indicator { image: none; width: 0px; }"
            )
            lbl_qss = (
                f"QLabel {{ font-size: 11px; font-weight: 400; "
                f"color: {tokens['tert']}; background: transparent; }}"
            )

        enabled = self.button.isEnabled()
        if not enabled:
            icon_color = tokens["border_strong"]
            lbl_qss = (
                f"QLabel {{ font-size: 11px; font-weight: 400; "
                f"color: {tokens['border_strong']}; background: transparent; }}"
            )
            self.button.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.button.setStyleSheet(btn_qss)
        self.button.setIcon(_render_icon(self._icon_name, icon_color, 18))
        self.label.setStyleSheet(lbl_qss)

        if dot and dot in _STATUS_COLOR_KEY:
            halo = tokens["popover"] if active else tokens["window"]
            pm = _status_pixmap(dot, tokens, size=5.5, halo=halo)
            side = int(round(pm.width() / pm.devicePixelRatio()))
            self._dot_label.setPixmap(pm)
            self._dot_label.setFixedSize(side, side)
            self._dot_label.move(40 - side - 1, 1)
            self._dot_label.show()
        else:
            self._dot_label.hide()


class NavRail(QFrame):
    """Fixed 64 px left navigation rail for the four pages and five shell actions."""

    page_selected = Signal(str)
    page_split_requested = Signal(str)
    action_triggered = Signal(str)

    def __init__(
        self,
        active_page: str = "run",
        status_dots: Mapping[str, str | None] | None = None,
        open_action: str | None = None,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._active_page = active_page
        self._open_action = open_action
        self._dots: dict[str, str | None] = dict(status_dots or {})

        self.setObjectName("navRail")
        self.setFixedWidth(RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(9)

        self._logo = QLabel("TM1")
        self._logo.setFixedSize(36, 36)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(8)

        self._page_cells: dict[str, _RailCell] = {}
        for key, short_label, full_label in NAV_PAGES:
            cell = _RailCell(key, short_label)
            cell.button.setToolTip(full_label)
            cell.clicked.connect(lambda k=key: self._on_page_clicked(k))
            self._page_cells[key] = cell
            layout.addWidget(cell)

        layout.addStretch(1)

        self._action_cells: dict[str, _RailCell] = {}
        for key, short_label, full_label, shortcut in RAIL_ACTIONS:
            icon_key = "railOpen" if key == "expand" else key
            cell = _RailCell(icon_key, short_label)
            tip = f"{full_label}  {shortcut}" if shortcut else full_label
            cell.button.setToolTip(tip)
            cell.clicked.connect(lambda k=key: self.action_triggered.emit(k))
            self._action_cells[key] = cell
            layout.addWidget(cell)

        self._refresh()

    def _on_page_clicked(self, key: str) -> None:
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.page_split_requested.emit(key)
            return
        self.set_active_page(key)
        self.page_selected.emit(key)

    def active_page(self) -> str:
        """Return the active page key."""
        return self._active_page

    def set_active_page(self, key: str) -> None:
        """Highlight the selected page key."""
        if key not in self._page_cells:
            raise ValueError(f"Unknown page key {key!r}")
        self._active_page = key
        self._refresh()

    def set_page_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable a navigation page button."""
        if key not in self._page_cells:
            raise ValueError(f"Unknown page key {key!r}")
        self._page_cells[key].button.setEnabled(enabled)
        self._refresh()

    def page_button(self, key: str) -> QToolButton:
        """Return the QToolButton for a navigation page key."""
        return self._page_cells[key].button

    def action_button(self, key: str) -> QToolButton:
        """Return the QToolButton for a rail action key."""
        return self._action_cells[key].button

    def set_open_action(self, key: str | None) -> None:
        """Highlight the bottom action whose menu or palette is open."""
        self._open_action = key
        self._refresh()

    def set_status_dots(self, dots: Mapping[str, str | None]) -> None:
        """Update per-page status marks (ok, warn, err, run, idle, or None)."""
        self._dots = dict(dots)
        self._refresh()

    def action_anchor(self, key: str) -> QWidget:
        """Return the rail cell widget used to anchor popovers."""
        return self._action_cells[key]

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the collapsed rail."""
        self._tokens.update(tokens)
        self._refresh()

    def _refresh(self) -> None:
        t = self._tokens
        self.setStyleSheet(f"QFrame#navRail {{ background: {t['window']}; border: none; }}")
        self._logo.setStyleSheet(
            f"QLabel {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: 9px; "
            f"font-family: {_FONT_DISP}; font-size: 12px; font-weight: 700; }}"
        )
        for key, cell in self._page_cells.items():
            cell.set_state(t, active=(key == self._active_page), dot=self._dots.get(key))
        for key, cell in self._action_cells.items():
            cell.set_state(t, opened=(key == self._open_action))


class _ExpandedRowButton(QPushButton):
    """Clickable row inside the expanded rail with reusable icon, label, and trailing slots."""

    def __init__(
        self,
        icon_name: str,
        text: str,
        tokens: Mapping[str, Any],
        *,
        height: int = 34,
        icon_size: int = 17,
        font_size: float = 13.0,
        active: bool = False,
        dot: str | None = None,
        meta: str = "",
        shortcut: str = "",
        checked: bool = False,
        icon_accent: bool = False,
        enabled: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._height = height
        self._icon_size = icon_size
        self._font_size = font_size
        self._icon_cache_key: tuple[str, str, int] | None = None
        self._dot_cache_key: tuple[str, str] | None = None
        self._check_cache_key: str | None = None

        self.setFixedHeight(height)

        layout = QHBoxLayout(self)
        margin_h = 8 if height <= 30 else 10
        layout.setContentsMargins(margin_h, 0, margin_h, 0)
        layout.setSpacing(10 if height >= 34 else 6)

        self._icon_label = QLabel()
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._icon_label.setFixedSize(icon_size, icon_size)
        self._icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(self._icon_label)

        self._text_label = QLabel()
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _enable_tnum(self._text_label)
        layout.addWidget(self._text_label)
        layout.addStretch(1)

        self._dot_label = QLabel()
        self._dot_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._dot_label.setStyleSheet("background: transparent;")
        self._dot_label.hide()
        layout.addWidget(self._dot_label)

        self._meta_label = QLabel()
        self._meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _enable_tnum(self._meta_label)
        self._meta_label.hide()
        layout.addWidget(self._meta_label)

        self._check_label = QLabel()
        self._check_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._check_label.setFixedSize(14, 14)
        self._check_label.setStyleSheet("background: transparent;")
        self._check_label.hide()
        layout.addWidget(self._check_label)

        self._shortcut_label = QLabel()
        self._shortcut_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._shortcut_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._shortcut_label.hide()
        layout.addWidget(self._shortcut_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.update_state(
            tokens,
            text=text,
            active=active,
            dot=dot,
            meta=meta,
            shortcut=shortcut,
            checked=checked,
            icon_accent=icon_accent,
            enabled=enabled,
        )

    def update_state(
        self,
        tokens: Mapping[str, Any],
        *,
        text: str | None = None,
        active: bool = False,
        dot: str | None = None,
        meta: str = "",
        shortcut: str = "",
        checked: bool = False,
        icon_accent: bool = False,
        enabled: bool = True,
    ) -> None:
        """Update button visuals, text, status mark, and trailing badges in place."""
        self.setEnabled(enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

        if active:
            btn_qss = (
                f"QPushButton {{ background: {tokens['accent_soft']}; border: none; "
                f"border-radius: 7px; text-align: left; }}"
            )
            icon_color = tokens["accent_fg"]
            text_color = tokens["accent_fg"]
            weight = 600
        else:
            btn_qss = (
                "QPushButton { background: transparent; border: none; "
                "border-radius: 7px; text-align: left; }"
                f"QPushButton:hover {{ background: {tokens['row_hover']}; }}"
            )
            icon_color = tokens["accent_fg"] if icon_accent else tokens["sub"]
            text_color = tokens["fg"]
            weight = 500 if checked else 400
        if self.styleSheet() != btn_qss:
            self.setStyleSheet(btn_qss)

        icon_key = (self._icon_name, icon_color, self._icon_size)
        if self._icon_cache_key != icon_key:
            self._icon_label.setPixmap(
                _render_icon(self._icon_name, icon_color, self._icon_size).pixmap(
                    QSize(self._icon_size, self._icon_size)
                )
            )
            self._icon_cache_key = icon_key

        if text is not None:
            fmt = Qt.TextFormat.RichText if "<" in text else Qt.TextFormat.PlainText
            if self._text_label.textFormat() != fmt:
                self._text_label.setTextFormat(fmt)
            if self._text_label.text() != text:
                self._text_label.setText(text)
        text_qss = (
            f"color: {text_color}; font-size: {int(round(self._font_size))}px; "
            f"font-weight: {weight}; background: transparent;"
        )
        if self._text_label.styleSheet() != text_qss:
            self._text_label.setStyleSheet(text_qss)

        if dot and dot in _STATUS_COLOR_KEY:
            dot_key = (dot, tokens[_STATUS_COLOR_KEY[dot]])
            if self._dot_cache_key != dot_key:
                pm = _status_pixmap(dot, tokens, size=6.5)
                side = int(round(pm.width() / pm.devicePixelRatio()))
                self._dot_label.setPixmap(pm)
                self._dot_label.setFixedSize(side, side)
                self._dot_cache_key = dot_key
            self._dot_label.show()
        else:
            self._dot_label.hide()

        if meta:
            meta_fmt = Qt.TextFormat.RichText if "<" in meta else Qt.TextFormat.PlainText
            if self._meta_label.textFormat() != meta_fmt:
                self._meta_label.setTextFormat(meta_fmt)
            if self._meta_label.text() != meta:
                self._meta_label.setText(meta)
            meta_px = "10.5px" if self._height <= 30 else "11px"
            meta_qss = (
                f"color: {tokens['tert']}; font-size: {meta_px}; font-weight: 400; "
                "background: transparent;"
            )
            if self._meta_label.styleSheet() != meta_qss:
                self._meta_label.setStyleSheet(meta_qss)
            self._meta_label.show()
        else:
            self._meta_label.hide()

        if checked:
            check_color = tokens["accent_fg"]
            if self._check_cache_key != check_color:
                self._check_label.setPixmap(
                    _render_icon("check", check_color, 14, stroke=1.9).pixmap(QSize(14, 14))
                )
                self._check_cache_key = check_color
            self._check_label.show()
        else:
            self._check_label.hide()

        if shortcut:
            if self._shortcut_label.text() != shortcut:
                self._shortcut_label.setText(shortcut)
            kbd_qss = (
                f"color: {tokens['tert']}; font-size: 11px; "
                f"background: {tokens['sunken']}; border: 1px solid {tokens['border']}; "
                "border-radius: 4px; padding: 1px 5px;"
            )
            if self._shortcut_label.styleSheet() != kbd_qss:
                self._shortcut_label.setStyleSheet(kbd_qss)
            self._shortcut_label.show()
        else:
            self._shortcut_label.hide()


class ExpandedNavRail(QFrame):
    """232 px expanded navigation panel with page status, workspaces, and recent runs."""

    page_selected = Signal(str)
    action_triggered = Signal(str)
    workspace_selected = Signal(str)
    recent_run_selected = Signal(str)
    collapse_requested = Signal()

    def __init__(
        self,
        active_page: str = "run",
        page_meta: Mapping[str, tuple[str | None, str]] | None = None,
        workspaces: Sequence[str] = ("A", "B", "C"),
        active_workspace: str = "A",
        recent_runs: Sequence[RecentRunItem] = (),
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._active_page = active_page
        self._page_enabled: dict[str, bool] = {k: True for k, _, _ in NAV_PAGES}
        self._page_meta: dict[str, tuple[str | None, str]] = dict(page_meta or {})
        self._workspaces: list[str] = list(workspaces)
        self._active_workspace = active_workspace
        self._recent_runs: list[RecentRunItem] = list(recent_runs)
        self._dirty = False

        self.setObjectName("expandedNavRail")
        self.setFixedWidth(EXPANDED_RAIL_WIDTH)

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(12, 12, 12, 12)
        self._root_layout.setSpacing(2)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(32)
        self._shadow.setOffset(4, 0)
        self.setGraphicsEffect(self._shadow)

        self._build_static_structure()
        self._sync_ui()

    def _build_static_structure(self) -> None:
        t = self._tokens

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        self._logo = QLabel("TM1")
        self._logo.setFixedSize(36, 36)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._brand = QLabel("SJTU-TPMSHX")
        top.addWidget(self._logo)
        top.addSpacing(8)
        top.addWidget(self._brand)
        top.addStretch(1)
        self._root_layout.addLayout(top)
        self._root_layout.addSpacing(12)

        self._page_rows: dict[str, _ExpandedRowButton] = {}
        for key, _, full_label in NAV_PAGES:
            row = _ExpandedRowButton(key, full_label, t)
            row.clicked.connect(lambda _=False, k=key: self._on_page_clicked(k))
            self._page_rows[key] = row
            self._root_layout.addWidget(row)

        self._root_layout.addSpacing(10)
        self._top_hairline = _Hairline(t)
        self._root_layout.addWidget(self._top_hairline)
        self._root_layout.addSpacing(8)

        self._ws_box = QWidget()
        self._ws_box.setStyleSheet("background: transparent;")
        self._ws_layout = QVBoxLayout(self._ws_box)
        self._ws_layout.setContentsMargins(0, 0, 0, 0)
        self._ws_layout.setSpacing(2)
        self._ws_header = self._section_label("工作区")
        self._ws_layout.addWidget(self._ws_header)
        self._ws_rows: list[_ExpandedRowButton] = []
        self._root_layout.addWidget(self._ws_box)

        self._recent_box = QWidget()
        self._recent_box.setStyleSheet("background: transparent;")
        self._recent_layout = QVBoxLayout(self._recent_box)
        self._recent_layout.setContentsMargins(0, 8, 0, 0)
        self._recent_layout.setSpacing(2)
        self._recent_header = self._section_label("最近运行")
        self._recent_layout.addWidget(self._recent_header)
        self._recent_rows: list[_ExpandedRowButton] = []
        self._root_layout.addWidget(self._recent_box)

        self._root_layout.addStretch(1)
        self._bottom_hairline = _Hairline(t)
        self._root_layout.addWidget(self._bottom_hairline)
        self._root_layout.addSpacing(6)

        self._action_rows: dict[str, _ExpandedRowButton] = {}
        for key, _, full_label, shortcut in RAIL_ACTIONS:
            icon_key = "railClose" if key == "expand" else key
            row = _ExpandedRowButton(icon_key, full_label, t, shortcut=shortcut)
            row.clicked.connect(lambda _=False, k=key: self._on_action_clicked(k))
            self._action_rows[key] = row
            self._root_layout.addWidget(row)

    def _schedule_sync(self) -> None:
        if self.isVisible():
            self._sync_ui()
        else:
            self._dirty = True

    def showEvent(self, event) -> None:
        if self._dirty:
            self._sync_ui()
        super().showEvent(event)

    def set_active_page(self, key: str) -> None:
        """Select the active page row."""
        if key == self._active_page:
            return
        self._active_page = key
        self._schedule_sync()

    def set_page_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable a navigation page row."""
        enabled = bool(enabled)
        if self._page_enabled.get(key) is enabled:
            return
        self._page_enabled[key] = enabled
        self._schedule_sync()

    def set_page_meta(self, page_meta: Mapping[str, tuple[str | None, str]]) -> None:
        """Set status mark and short metadata text for each page key."""
        updated = dict(page_meta)
        if updated == self._page_meta:
            return
        self._page_meta = updated
        self._schedule_sync()

    def set_workspaces(self, workspaces: Sequence[str], active_workspace: str) -> None:
        """Set the workspace names and active workspace."""
        ws_list = list(workspaces)
        if ws_list == self._workspaces and active_workspace == self._active_workspace:
            return
        self._workspaces = ws_list
        self._active_workspace = active_workspace
        self._schedule_sync()

    def set_recent_runs(self, items: Sequence[RecentRunItem]) -> None:
        """Set the recent run entries displayed in the rail."""
        run_list = list(items)
        if run_list == self._recent_runs:
            return
        self._recent_runs = run_list
        self._schedule_sync()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the expanded rail."""
        updated = dict(self._tokens)
        updated.update(tokens)
        if updated == self._tokens:
            return
        self._tokens = updated
        self._schedule_sync()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.25, 0.25, self.width() - 0.5, self.height() - 0.5)
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.end()

    def _section_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setContentsMargins(10, 0, 0, 4)
        lab.setStyleSheet(
            f"color: {self._tokens['tert']}; font-size: 11px; font-weight: 600; "
            "background: transparent;"
        )
        return lab

    def _on_page_clicked(self, key: str) -> None:
        self._active_page = key
        self._sync_ui()
        self.page_selected.emit(key)

    def _on_workspace_row_clicked(self, index: int) -> None:
        if 0 <= index < len(self._workspaces):
            name = self._workspaces[index]
            self._active_workspace = name
            self._sync_ui()
            self.workspace_selected.emit(name)

    def _on_recent_row_clicked(self, index: int) -> None:
        if 0 <= index < len(self._recent_runs):
            self.recent_run_selected.emit(self._recent_runs[index].run_id)

    def _on_action_clicked(self, key: str) -> None:
        if key == "expand":
            self.collapse_requested.emit()
        self.action_triggered.emit(key)

    def _sync_ui(self) -> None:
        self._dirty = False
        t = self._tokens

        frame_qss = f"QFrame#expandedNavRail {{ background: {t['panel']}; border: none; }}"
        if self.styleSheet() != frame_qss:
            self.setStyleSheet(frame_qss)
        effect = self.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setColor(QColor(*t["shadow_drawer_ambient"]))

        logo_qss = (
            f"QLabel {{ background: {t['popover']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: 9px; "
            f"font-family: {_FONT_DISP}; font-size: 12px; font-weight: 700; }}"
        )
        if self._logo.styleSheet() != logo_qss:
            self._logo.setStyleSheet(logo_qss)
        brand_qss = (
            f"color: {t['fg']}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        if self._brand.styleSheet() != brand_qss:
            self._brand.setStyleSheet(brand_qss)

        for key, _, full_label in NAV_PAGES:
            kind, meta = self._page_meta.get(key, (None, ""))
            enabled = self._page_enabled.get(key, True)
            self._page_rows[key].update_state(
                t,
                text=full_label,
                active=(key == self._active_page),
                dot=kind,
                meta=meta,
                enabled=enabled,
            )

        self._top_hairline.set_color(t["border"])
        self._bottom_hairline.set_color(t["border"])
        section_qss = (
            f"color: {t['tert']}; font-size: 11px; font-weight: 600; background: transparent;"
        )
        if self._ws_header.styleSheet() != section_qss:
            self._ws_header.setStyleSheet(section_qss)
        if self._recent_header.styleSheet() != section_qss:
            self._recent_header.setStyleSheet(section_qss)

        self._ws_box.setVisible(bool(self._workspaces))
        while len(self._ws_rows) < len(self._workspaces):
            idx = len(self._ws_rows)
            row = _ExpandedRowButton(
                "ws",
                "",
                t,
                height=30,
                icon_size=15,
                font_size=12.5,
            )
            row.clicked.connect(lambda _=False, i=idx: self._on_workspace_row_clicked(i))
            self._ws_rows.append(row)
            self._ws_layout.addWidget(row)
        for idx, row in enumerate(self._ws_rows):
            if idx < len(self._workspaces):
                ws = self._workspaces[idx]
                is_current = ws == self._active_workspace
                row.update_state(
                    t,
                    text=f"工作区 {ws}",
                    checked=is_current,
                    icon_accent=is_current,
                )
                row.show()
            else:
                row.hide()

        self._recent_box.setVisible(bool(self._recent_runs))
        while len(self._recent_rows) < len(self._recent_runs):
            idx = len(self._recent_rows)
            row = _ExpandedRowButton(
                "clock",
                "",
                t,
                height=30,
                icon_size=15,
                font_size=11.5,
            )
            row.clicked.connect(lambda _=False, i=idx: self._on_recent_row_clicked(i))
            self._recent_rows.append(row)
            self._recent_layout.addWidget(row)
        for idx, row in enumerate(self._recent_rows):
            if idx < len(self._recent_runs):
                item = self._recent_runs[idx]
                row.update_state(
                    t,
                    text=item.label,
                    meta=item.summary_html,
                )
                row.show()
            else:
                row.hide()

        for key, _, full_label, shortcut in RAIL_ACTIONS:
            self._action_rows[key].update_state(
                t,
                text=full_label,
                shortcut=shortcut,
            )
