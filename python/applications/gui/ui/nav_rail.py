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


def _icon_label(name: str, color: str, size: int = 15, stroke: float = 1.55) -> QLabel:
    lab = QLabel()
    lab.setPixmap(_render_icon(name, color, size, stroke).pixmap(QSize(size, size)))
    lab.setFixedSize(size, size)
    lab.setStyleSheet("background: transparent;")
    return lab


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
    """Clickable row inside the expanded rail with icon, label, and optional trailing items."""

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if active:
            self.setStyleSheet(
                f"QPushButton {{ background: {tokens['accent_soft']}; border: none; "
                f"border-radius: 7px; text-align: left; }}"
            )
            icon_color = tokens["accent_fg"]
            text_color = tokens["accent_fg"]
            weight = 600
        else:
            self.setStyleSheet(
                "QPushButton { background: transparent; border: none; "
                "border-radius: 7px; text-align: left; }"
                f"QPushButton:hover {{ background: {tokens['row_hover']}; }}"
            )
            icon_color = tokens["accent_fg"] if icon_accent else tokens["sub"]
            text_color = tokens["fg"]
            weight = 500 if checked else 400

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10 if height >= 34 else 8)

        layout.addWidget(_icon_label(icon_name, icon_color, icon_size))

        text_label = QLabel(text)
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if "<" in text:
            text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setStyleSheet(
            f"color: {text_color}; font-size: {int(round(font_size))}px; "
            f"font-weight: {weight}; background: transparent;"
        )
        _enable_tnum(text_label)
        layout.addWidget(text_label)
        layout.addStretch(1)

        if dot and dot in _STATUS_COLOR_KEY:
            pm = _status_pixmap(dot, tokens, size=6.5)
            side = int(round(pm.width() / pm.devicePixelRatio()))
            dot_lab = QLabel()
            dot_lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            dot_lab.setPixmap(pm)
            dot_lab.setFixedSize(side, side)
            dot_lab.setStyleSheet("background: transparent;")
            layout.addWidget(dot_lab)

        if meta:
            meta_lab = QLabel(meta)
            meta_lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            if "<" in meta:
                meta_lab.setTextFormat(Qt.TextFormat.RichText)
            meta_lab.setStyleSheet(
                f"color: {tokens['tert']}; font-size: 11px; font-weight: 400; "
                "background: transparent;"
            )
            _enable_tnum(meta_lab)
            layout.addWidget(meta_lab)

        if checked:
            layout.addWidget(_icon_label("check", tokens["accent_fg"], 14, stroke=1.9))

        if shortcut:
            kbd = QLabel(shortcut)
            kbd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            kbd.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            kbd.setStyleSheet(
                f"color: {tokens['tert']}; font-size: 11px; "
                f"background: {tokens['sunken']}; border: 1px solid {tokens['border']}; "
                "border-radius: 4px; padding: 1px 5px;"
            )
            layout.addWidget(kbd, 0, Qt.AlignmentFlag.AlignVCenter)


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

        self.setObjectName("expandedNavRail")
        self.setFixedWidth(EXPANDED_RAIL_WIDTH)

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(12, 12, 12, 12)
        self._root_layout.setSpacing(2)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(32)
        self._shadow.setOffset(4, 0)
        self.setGraphicsEffect(self._shadow)

        self._rebuild()

    def set_active_page(self, key: str) -> None:
        """Select the active page row."""
        self._active_page = key
        self._rebuild()

    def set_page_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable a navigation page row."""
        self._page_enabled[key] = enabled
        self._rebuild()

    def set_page_meta(self, page_meta: Mapping[str, tuple[str | None, str]]) -> None:
        """Set status mark and short metadata text for each page key."""
        self._page_meta = dict(page_meta)
        self._rebuild()

    def set_workspaces(self, workspaces: Sequence[str], active_workspace: str) -> None:
        """Set the workspace names and active workspace."""
        self._workspaces = list(workspaces)
        self._active_workspace = active_workspace
        self._rebuild()

    def set_recent_runs(self, items: Sequence[RecentRunItem]) -> None:
        """Set the recent run entries displayed in the rail."""
        self._recent_runs = list(items)
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the expanded rail."""
        self._tokens.update(tokens)
        self._rebuild()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.25, 0.25, self.width() - 0.5, self.height() - 0.5)
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.end()

    def _clear_layout(self) -> None:
        while self._root_layout.count():
            item = self._root_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                sub = item.layout()
                while sub.count():
                    child = sub.takeAt(0)
                    cw = child.widget()
                    if cw is not None:
                        cw.hide()
                        cw.setParent(None)
                        cw.deleteLater()

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
        self._rebuild()
        self.page_selected.emit(key)

    def _on_workspace_clicked(self, name: str) -> None:
        self._active_workspace = name
        self._rebuild()
        self.workspace_selected.emit(name)

    def _on_action_clicked(self, key: str) -> None:
        if key == "expand":
            self.collapse_requested.emit()
        self.action_triggered.emit(key)

    def _rebuild(self) -> None:
        self._clear_layout()
        t = self._tokens
        self.setStyleSheet(f"QFrame#expandedNavRail {{ background: {t['panel']}; border: none; }}")
        self._shadow.setColor(QColor(*t["shadow_drawer_ambient"]))

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        logo = QLabel("TM1")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"QLabel {{ background: {t['popover']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: 9px; "
            f"font-family: {_FONT_DISP}; font-size: 12px; font-weight: 700; }}"
        )
        brand = QLabel("SJTU-TPMSHX")
        brand.setStyleSheet(
            f"color: {t['fg']}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        top.addWidget(logo)
        top.addSpacing(8)
        top.addWidget(brand)
        top.addStretch(1)
        self._root_layout.addLayout(top)
        self._root_layout.addSpacing(12)

        for key, _, full_label in NAV_PAGES:
            kind, meta = self._page_meta.get(key, (None, ""))
            enabled = self._page_enabled.get(key, True)
            row = _ExpandedRowButton(
                key,
                full_label,
                t,
                active=(key == self._active_page),
                dot=kind,
                meta=meta,
            )
            row.setEnabled(enabled)
            if not enabled:
                row.setCursor(Qt.CursorShape.ArrowCursor)
            row.clicked.connect(lambda _=False, k=key: self._on_page_clicked(k))
            self._root_layout.addWidget(row)

        self._root_layout.addSpacing(10)
        self._root_layout.addWidget(_Hairline(t))
        self._root_layout.addSpacing(8)

        if self._workspaces:
            self._root_layout.addWidget(self._section_label("工作区"))
            for ws in self._workspaces:
                is_current = ws == self._active_workspace
                row = _ExpandedRowButton(
                    "ws",
                    f"工作区 {ws}",
                    t,
                    height=30,
                    icon_size=15,
                    font_size=12.5,
                    checked=is_current,
                    icon_accent=is_current,
                )
                row.clicked.connect(lambda _=False, name=ws: self._on_workspace_clicked(name))
                self._root_layout.addWidget(row)

        if self._recent_runs:
            self._root_layout.addSpacing(8)
            self._root_layout.addWidget(self._section_label("最近运行"))
            for item in self._recent_runs:
                row = _ExpandedRowButton(
                    "clock",
                    item.label,
                    t,
                    height=30,
                    icon_size=15,
                    font_size=11.5,
                    meta=item.summary_html,
                )
                row.clicked.connect(
                    lambda _=False, rid=item.run_id: self.recent_run_selected.emit(rid)
                )
                self._root_layout.addWidget(row)

        self._root_layout.addStretch(1)
        self._root_layout.addWidget(_Hairline(t))
        self._root_layout.addSpacing(6)

        for key, _, full_label, shortcut in RAIL_ACTIONS:
            icon_key = "railClose" if key == "expand" else key
            row = _ExpandedRowButton(
                icon_key,
                full_label,
                t,
                shortcut=shortcut,
            )
            row.clicked.connect(lambda _=False, k=key: self._on_action_clicked(k))
            self._root_layout.addWidget(row)
