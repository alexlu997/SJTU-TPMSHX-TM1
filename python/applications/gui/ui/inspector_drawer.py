"""Push inspector drawer with segmented tab strip and collapsible bands in Style P2."""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.applications.gui.ui.theme import get_theme

DRAWER_WIDTH = 376
DRAWER_WIDTH_COMPACT = 340

_ICON_PATHS: dict[str, str] = {
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "chevd": '<path d="m6 9 6 6 6-6"/>',
    "chevr": '<path d="m9 18 6-6-6-6"/>',
}


def _render_icon(name: str, color: str, size: int = 14, stroke: float = 1.65) -> QIcon:
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


class _Hairline(QWidget):
    """Single-device-pixel horizontal separator."""

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


class _TagChip(QFrame):
    """Neutral or accent pill tag placed inside a band header."""

    def __init__(self, text: str, tokens: Mapping[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = dict(tokens)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 6, 1)
        layout.setSpacing(0)
        self._label = QLabel(text)
        layout.addWidget(self._label)
        self.apply_theme(tokens)

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        self._tokens.update(tokens)
        self._label.setStyleSheet(
            f"color: {self._tokens['accent_fg']}; font-size: 10.5px; "
            "font-weight: 600; background: transparent;"
        )
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["accent_soft"]))
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        painter.end()


class DrawerTabStrip(QFrame):
    """Segmented tab selector for the inspector drawer header."""

    current_changed = Signal(int)

    def __init__(
        self,
        labels: Sequence[str] = (),
        current_index: int = 0,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._labels: list[str] = []
        self._badges: dict[int, int] = {}
        self._buttons: list[QPushButton] = []
        self._current_index = 0

        self.setObjectName("drawerTabStrip")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(2)

        self.set_tabs(labels, current_index=current_index)

    def set_tabs(self, labels: Sequence[str], current_index: int = 0) -> None:
        """Replace the tab labels and set the active index."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._labels = list(labels)
        self._buttons = []
        for idx, text in enumerate(self._labels):
            btn = QPushButton(text)
            btn.setFixedHeight(24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=idx: self._on_tab_clicked(i))
            self._buttons.append(btn)
            self._layout.addWidget(btn)
        if self._labels:
            self._current_index = max(0, min(current_index, len(self._labels) - 1))
        else:
            self._current_index = -1
        self._refresh()

    def current_index(self) -> int:
        """Return the active tab index, or -1 if no tabs exist."""
        return self._current_index

    def set_current_index(self, index: int) -> None:
        """Select a tab by index without emitting ``current_changed``."""
        if not self._buttons:
            return
        clamped = max(0, min(index, len(self._buttons) - 1))
        if clamped != self._current_index:
            self._current_index = clamped
            self._refresh()

    def set_tab_badge(self, index: int, count: int) -> None:
        """Display or clear a warning count suffix on one tab."""
        if index < 0 or index >= len(self._buttons):
            return
        self._badges[index] = max(0, int(count))
        base = self._labels[index]
        n = self._badges[index]
        self._buttons[index].setText(f"{base} ⚠{n}" if n > 0 else base)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the tab strip."""
        self._tokens.update(tokens)
        self._refresh()

    def _on_tab_clicked(self, index: int) -> None:
        if index == self._current_index:
            return
        self._current_index = index
        self._refresh()
        self.current_changed.emit(index)

    def _refresh(self) -> None:
        t = self._tokens
        self.setStyleSheet(
            f"QFrame#drawerTabStrip {{ background: {t['sunken']}; border: none; "
            "border-radius: 7px; }"
        )
        for idx, btn in enumerate(self._buttons):
            if idx == self._current_index:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {t['seg_on']}; color: {t['fg']}; "
                    f"border: 1px solid {t['border']}; border-radius: 5px; "
                    "padding: 0 9px; font-size: 12px; font-weight: 600; }"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {t['sub']}; "
                    "border: none; border-radius: 5px; padding: 0 9px; "
                    "font-size: 12px; font-weight: 400; }"
                    f"QPushButton:hover {{ color: {t['fg']}; }}"
                )


class BandHeader(QWidget):
    """Neutral section band header without colored side strips or underlines."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        *,
        first: bool = False,
        collapsible: bool = False,
        expanded: bool = True,
        count: int | None = None,
        tag: str | None = None,
        right_widget: QWidget | None = None,
        actions: Sequence[tuple[str, Callable[[], None]]] = (),
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._collapsible = collapsible
        self._expanded = expanded
        self._badge_count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._top_line: _Hairline | None = None
        if not first:
            self._top_line = _Hairline(self._tokens)
            outer.addWidget(self._top_line)

        self._bar = QFrame()
        self._bar.setObjectName("bandHeaderBar")
        self._bar.setFixedHeight(31)
        if collapsible:
            self._bar.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        row = QHBoxLayout(self._bar)
        row.setContentsMargins(14 if collapsible else 16, 0, 12, 0)
        row.setSpacing(6)

        self._chevron: QLabel | None = None
        if collapsible:
            self._chevron = QLabel()
            self._chevron.setFixedSize(12, 12)
            self._chevron.setStyleSheet("background: transparent;")
            row.addWidget(self._chevron)

        self._title_label = QLabel(title)
        if "<" in title:
            self._title_label.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self._title_label)

        self._count_label = QLabel()
        _enable_tnum(self._count_label)
        self._count_label.setVisible(count is not None)
        if count is not None:
            self._count_label.setText(str(count))
        row.addWidget(self._count_label)

        self._badge_label = QLabel()
        _enable_tnum(self._badge_label)
        self._badge_label.hide()
        row.addWidget(self._badge_label)

        self._tag_chip: _TagChip | None = None
        if tag:
            self._tag_chip = _TagChip(tag, self._tokens)
            row.addWidget(self._tag_chip)

        row.addStretch(1)

        self._right_slot = QHBoxLayout()
        self._right_slot.setContentsMargins(0, 0, 0, 0)
        self._right_slot.setSpacing(6)
        row.addLayout(self._right_slot)
        self._right_widget: QWidget | None = None
        if right_widget is not None:
            self.set_right_widget(right_widget)

        self._action_buttons: list[QPushButton] = []
        for label_text, callback in actions:
            btn = QPushButton(label_text)
            btn.setFixedHeight(20)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(callback)
            self._action_buttons.append(btn)
            row.addWidget(btn)

        outer.addWidget(self._bar)

        self._bottom_line = _Hairline(self._tokens)
        outer.addWidget(self._bottom_line)

        self._refresh()

    def mousePressEvent(self, event) -> None:
        if self._collapsible and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._collapsible and event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_expanded(self, expanded: bool) -> None:
        """Update the chevron direction for expanded or collapsed state."""
        self._expanded = expanded
        self._refresh()

    def set_count(self, count: int | None) -> None:
        """Update or hide the trailing count text."""
        if count is None:
            self._count_label.hide()
        else:
            self._count_label.setText(str(count))
            self._count_label.show()

    def set_badge_count(self, count: int) -> None:
        """Show or hide a validation warning badge (⚠ N) on the band header."""
        self._badge_count = max(0, int(count))
        if self._badge_count > 0:
            self._badge_label.setText(f"⚠ {self._badge_count}")
            self._badge_label.show()
        else:
            self._badge_label.hide()

    def set_right_widget(self, widget: QWidget | None) -> None:
        """Replace the optional right-side summary widget."""
        if self._right_widget is not None:
            self._right_slot.removeWidget(self._right_widget)
            self._right_widget.setParent(None)
        self._right_widget = widget
        if widget is not None:
            self._right_slot.addWidget(widget)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the band header."""
        self._tokens.update(tokens)
        self._refresh()

    def _refresh(self) -> None:
        t = self._tokens
        if self._top_line is not None:
            self._top_line.set_color(t["border"])
        self._bottom_line.set_color(t["border"])
        self._bar.setStyleSheet(
            f"QFrame#bandHeaderBar {{ background: {t['sunken']}; border: none; }}"
        )
        self._title_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        self._count_label.setStyleSheet(
            f"color: {t['tert']}; font-size: 12px; font-weight: 500; background: transparent;"
        )
        self._badge_label.setStyleSheet(
            f"color: {t['warn']}; background: {t['warn_soft']}; border-radius: 5px; "
            "padding: 1px 6px; font-size: 11px; font-weight: 600;"
        )
        if self._chevron is not None:
            icon_key = "chevd" if self._expanded else "chevr"
            self._chevron.setPixmap(_render_icon(icon_key, t["tert"], 12).pixmap(QSize(12, 12)))
        if self._tag_chip is not None:
            self._tag_chip.apply_theme(t)
        action_qss = (
            f"QPushButton {{ background: transparent; border: none; color: {t['accent_fg']}; "
            "padding: 0 2px 0 4px; font-size: 12px; font-weight: 500; border-radius: 5px; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
        )
        for btn in self._action_buttons:
            btn.setStyleSheet(action_qss)


class CollapsibleBand(QWidget):
    """Inspector drawer section with a clickable header band and collapsible body."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        first: bool = False,
        collapsible: bool = True,
        expanded: bool = True,
        count: int | None = None,
        tag: str | None = None,
        right_widget: QWidget | None = None,
        actions: Sequence[tuple[str, Callable[[], None]]] = (),
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = BandHeader(
            title,
            first=first,
            collapsible=collapsible,
            expanded=expanded,
            count=count,
            tag=tag,
            right_widget=right_widget,
            actions=actions,
            tokens=tokens,
        )
        if collapsible:
            self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)

        self._body = QWidget()
        self._body.setObjectName("bandBody")
        self._body.setStyleSheet("QWidget#bandBody { background: transparent; }")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._body.setVisible(expanded)
        layout.addWidget(self._body)

    def body_layout(self) -> QVBoxLayout:
        """Return the vertical layout that holds the section content."""
        return self._body_layout

    def set_body(self, widget: QWidget) -> None:
        """Replace the body content with a single widget."""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._body_layout.addWidget(widget)

    def is_expanded(self) -> bool:
        """Return True when the section body is visible."""
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        """Expand or collapse the section body."""
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._body.setVisible(expanded)
        self.header.set_expanded(expanded)
        self.toggled.emit(expanded)

    def toggle(self) -> None:
        """Toggle between expanded and collapsed states."""
        self.set_expanded(not self._expanded)

    def set_badge_count(self, count: int) -> None:
        """Forward a validation warning badge count to the band header."""
        self.header.set_badge_count(count)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the band header."""
        self.header.apply_theme(tokens)


class InspectorDrawer(QFrame):
    """Right-side push drawer with segmented tabs, close button, and scrolled body."""

    tab_changed = Signal(int)
    close_requested = Signal()
    open_changed = Signal(bool)

    def __init__(
        self,
        tabs: Sequence[tuple[str, QWidget]] = (),
        current_index: int = 0,
        *,
        opened: bool = True,
        compact: bool = False,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._opened = opened
        self._compact = compact
        self._tab_titles: list[str] = []

        self.setObjectName("inspectorDrawer")
        self.setFixedWidth(DRAWER_WIDTH_COMPACT if compact else DRAWER_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(16, 8, 10, 8)
        head.setSpacing(8)

        self.tab_strip = DrawerTabStrip(tokens=self._tokens)
        self.tab_strip.current_changed.connect(self._on_tab_changed)
        head.addWidget(self.tab_strip)
        head.addStretch(1)

        self.close_button = QToolButton()
        self.close_button.setFixedSize(26, 26)
        self.close_button.setIconSize(QSize(15, 15))
        self.close_button.setToolTip("收起检查器  Ctrl+]")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self._on_close_clicked)
        head.addWidget(self.close_button)

        layout.addLayout(head)

        self._head_line = _Hairline(self._tokens)
        layout.addWidget(self._head_line)

        self._stack = QStackedWidget()
        self._stack.setObjectName("inspectorStack")
        self._stack.setStyleSheet(
            "QStackedWidget#inspectorStack { background: transparent; border: none; }"
        )
        layout.addWidget(self._stack, 1)

        self.set_tabs(tabs, current_index=current_index)
        self.setVisible(opened)
        self._refresh()

    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("inspectorViewport")
        holder = QWidget()
        holder.setObjectName("inspectorBodyHolder")
        inner = QVBoxLayout(holder)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(content)
        inner.addStretch(1)
        scroll.setWidget(holder)
        return scroll

    def set_tabs(
        self,
        tabs: Sequence[tuple[str, QWidget]],
        current_index: int = 0,
    ) -> None:
        """Replace all drawer tabs with ``(title, content_widget)`` pairs."""
        self.clear_tabs()
        for title, widget in tabs:
            self._tab_titles.append(title)
            self._stack.addWidget(self._wrap_scroll(widget))
        self.tab_strip.set_tabs(self._tab_titles, current_index=current_index)
        if self._tab_titles:
            idx = max(0, min(current_index, len(self._tab_titles) - 1))
            self._stack.setCurrentIndex(idx)
        self._refresh_scrollbars()

    def add_tab(self, title: str, content: QWidget) -> int:
        """Append a tab to the drawer and return its index."""
        self._tab_titles.append(title)
        idx = self._stack.addWidget(self._wrap_scroll(content))
        current = self.tab_strip.current_index()
        self.tab_strip.set_tabs(self._tab_titles, current_index=max(0, current))
        self._refresh_scrollbars()
        return idx

    def clear_tabs(self) -> None:
        """Remove all tabs from the drawer."""
        self._tab_titles.clear()
        while self._stack.count():
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self.tab_strip.set_tabs(())

    def current_index(self) -> int:
        """Return the active tab index."""
        return self._stack.currentIndex()

    def set_current_index(self, index: int) -> None:
        """Select the active tab by index."""
        if not self._tab_titles:
            return
        clamped = max(0, min(index, len(self._tab_titles) - 1))
        self.tab_strip.set_current_index(clamped)
        self._stack.setCurrentIndex(clamped)

    def is_open(self) -> bool:
        """Return True when the drawer is open."""
        return self._opened

    def set_open(self, opened: bool) -> None:
        """Show or hide the push drawer and emit ``open_changed`` when state changes."""
        if self._opened == opened:
            return
        self._opened = opened
        self.setVisible(opened)
        self.open_changed.emit(opened)

    def set_compact(self, compact: bool) -> None:
        """Switch between 376 px desktop width and 340 px compact width."""
        self._compact = compact
        self.setFixedWidth(DRAWER_WIDTH_COMPACT if compact else DRAWER_WIDTH)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the drawer and any child bands."""
        self._tokens.update(tokens)
        self.tab_strip.apply_theme(self._tokens)
        for band in self.findChildren(CollapsibleBand):
            band.apply_theme(self._tokens)
        for header in self.findChildren(BandHeader):
            header.apply_theme(self._tokens)
        self._refresh()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["panel"]))
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawRoundedRect(rect, 12.0, 12.0)
        painter.end()

    def _on_tab_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.tab_changed.emit(index)

    def _on_close_clicked(self) -> None:
        self.close_requested.emit()

    def _refresh_scrollbars(self) -> None:
        t = self._tokens
        scroll_qss = (
            "QScrollArea#inspectorScroll, QWidget#inspectorViewport, QWidget#inspectorBodyHolder {"
            " background: transparent; border: none; }"
            "QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 1px; }"
            f"QScrollBar::handle:vertical {{ background: {t['border_strong']}; "
            "border-radius: 2px; min-height: 40px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        for idx in range(self._stack.count()):
            self._stack.widget(idx).setStyleSheet(scroll_qss)

    def _refresh(self) -> None:
        t = self._tokens
        self.setStyleSheet(
            "QFrame#inspectorDrawer { background: transparent; border: none; }"
        )
        self._head_line.set_color(t["border"])
        self.close_button.setIcon(_render_icon("x", t["tert"], 15))
        self.close_button.setStyleSheet(
            "QToolButton { background: transparent; border: none; border-radius: 6px; }"
            f"QToolButton:hover {{ background: {t['hover']}; }}"
        )
        self._refresh_scrollbars()
        self.update()
