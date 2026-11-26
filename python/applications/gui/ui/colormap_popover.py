"""Floating colormap and scale popover (色阶) in Style P2."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import matplotlib as mpl
from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

POPOVER_WIDTH = 298
CURATED_COLORMAPS: tuple[str, ...] = ("coolwarm", "turbo", "viridis", "cividis")

_DEFAULT_TOKENS: dict[str, Any] = {
    "popover": "#FFFFFF",
    "row_hover": "#E3E2DD",
    "border": "#D9D8D4",
    "border_strong": "#C1BFBA",
    "inp_border": "#807F79",
    "fg": "#181715",
    "sub": "#474643",
    "tert": "#686663",
    "accent": "#0E6275",
    "accent_fg": "#0B5161",
}

_ICON_PATHS: dict[str, str] = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "scale": '<path d="M3 17h18M6 17V7M12 17V4M18 17v-7"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
}


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


def _cmap_swatch_pixmap(name: str, width: int = 92, height: int = 12) -> QPixmap:
    cmap = mpl.colormaps[name]
    pixmap = QPixmap(width * 3, height * 3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0.0, 0.0, float(width * 3), 0.0)
    steps = 32
    for idx in range(steps + 1):
        frac = idx / steps
        r, g, b, _ = cmap(frac)
        grad.setColorAt(frac, QColor.fromRgbF(r, g, b))
    painter.setBrush(QBrush(grad))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, width * 3, height * 3, 9, 9)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return pixmap


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


class ToggleSwitch(QAbstractButton):
    """Compact 34x20 pill toggle switch styled with Style P2 tokens."""

    def __init__(
        self,
        checked: bool = False,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(_DEFAULT_TOKENS)
        if tokens is not None:
            self._tokens.update(tokens)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(34, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Update track colors from Style P2 theme tokens."""
        self._tokens.update(tokens)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(34, 20)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = self._tokens["accent"] if self.isChecked() else self._tokens["inp_border"]
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(QRectF(0.0, 0.0, 34.0, 20.0), 10.0, 10.0)
        painter.setBrush(QColor("#FFFFFF"))
        cx = 24.0 if self.isChecked() else 10.0
        painter.drawEllipse(QPointF(cx, 10.0), 8.0, 8.0)
        painter.end()


class ColormapPopover(QFrame):
    """Floating popover for selecting a curated colormap and scale sharing options."""

    colormap_selected = Signal(str)
    sync_temp_scale_changed = Signal(bool)
    shared_pressure_scale_changed = Signal(bool)
    reset_requested = Signal()

    def __init__(
        self,
        quantity_label: str = "温度",
        current_colormap: str = "coolwarm",
        *,
        colormaps: Sequence[str] = CURATED_COLORMAPS,
        sync_temp_scale: bool = True,
        shared_pressure_scale: bool = True,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(_DEFAULT_TOKENS)
        if tokens is not None:
            self._tokens.update(tokens)
        self._quantity_label = quantity_label
        self._colormaps: tuple[str, ...] = tuple(colormaps)
        self._current_colormap = current_colormap
        self._sync_temp_scale = sync_temp_scale
        self._shared_pressure_scale = shared_pressure_scale

        self.setObjectName("colormapPopover")
        self.setFixedWidth(POPOVER_WIDTH)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(1)

        self._rebuild()

    def current_colormap(self) -> str:
        """Return the selected colormap name."""
        return self._current_colormap

    def set_colormap(self, name: str) -> None:
        """Set the active colormap name without emitting ``colormap_selected``."""
        self._current_colormap = name
        self._rebuild()

    def set_quantity_label(self, label: str) -> None:
        """Set the quantity name shown in the group title (for example, 温度)."""
        self._quantity_label = label
        self._rebuild()

    def sync_temp_scale(self) -> bool:
        """Return True when phases share one temperature color scale."""
        return self._sync_temp_scale

    def set_sync_temp_scale(self, enabled: bool) -> None:
        """Set the temperature scale sync switch state."""
        self._sync_temp_scale = enabled
        self._rebuild()

    def shared_pressure_scale(self) -> bool:
        """Return True when fluid pressures share one color scale."""
        return self._shared_pressure_scale

    def set_shared_pressure_scale(self, enabled: bool) -> None:
        """Set the shared pressure scale switch state."""
        self._shared_pressure_scale = enabled
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to the popover."""
        self._tokens.update(tokens)
        self._rebuild()

    def popup_below(self, anchor: QWidget, offset_y: int = 6) -> None:
        """Open the popover right-aligned below an anchor widget."""
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.adjustSize()
        pos = anchor.mapToGlobal(
            QPoint(anchor.width() - self.width(), anchor.height() + offset_y)
        )
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

    def _on_cmap_clicked(self, name: str) -> None:
        self._current_colormap = name
        self._rebuild()
        self.colormap_selected.emit(name)

    def _on_sync_temp_toggled(self, checked: bool) -> None:
        self._sync_temp_scale = checked
        self.sync_temp_scale_changed.emit(checked)

    def _on_shared_pressure_toggled(self, checked: bool) -> None:
        self._shared_pressure_scale = checked
        self.shared_pressure_scale_changed.emit(checked)

    def _on_reset_clicked(self) -> None:
        self.reset_requested.emit()

    def _add_toggle_row(self, text: str, checked: bool, slot) -> None:
        t = self._tokens
        row = QFrame()
        row.setFixedHeight(36)
        row.setStyleSheet("background: transparent; border: none;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(9)

        ic = QLabel()
        ic.setPixmap(_render_icon("scale", t["sub"], 15).pixmap(QSize(15, 15)))
        ic.setFixedSize(15, 15)
        ic.setStyleSheet("background: transparent;")
        hl.addWidget(ic)

        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; font-weight: 400; background: transparent;"
        )
        hl.addWidget(lbl)
        hl.addStretch(1)

        sw = ToggleSwitch(checked=checked, tokens=t)
        sw.toggled.connect(slot)
        hl.addWidget(sw)
        self._layout.addWidget(row)

    def _rebuild(self) -> None:
        self._clear_layout()
        t = self._tokens

        header = f"色阶 · {self._quantity_label}" if self._quantity_label else "色阶"
        self._add_group(header)

        for name in self._colormaps:
            selected = name == self._current_colormap
            btn = QPushButton()
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 7px; "
                "text-align: left; }"
                f"QPushButton:hover {{ background: {t['row_hover']}; }}"
            )
            hl = QHBoxLayout(btn)
            hl.setContentsMargins(10, 0, 10, 0)
            hl.setSpacing(12)

            swatch = QLabel()
            swatch.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            swatch.setPixmap(_cmap_swatch_pixmap(name))
            swatch.setFixedSize(92, 12)
            swatch.setStyleSheet("background: transparent;")
            hl.addWidget(swatch)

            lbl = QLabel(name)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lbl.setStyleSheet(
                f"color: {t['fg']}; font-size: 12.5px; "
                f"font-weight: {600 if selected else 400}; background: transparent;"
            )
            hl.addWidget(lbl)
            hl.addStretch(1)

            if selected:
                chk = QLabel()
                chk.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                chk.setPixmap(
                    _render_icon("check", t["accent_fg"], 14, stroke=1.9).pixmap(QSize(14, 14))
                )
                chk.setFixedSize(14, 14)
                chk.setStyleSheet("background: transparent;")
                hl.addWidget(chk)

            btn.clicked.connect(lambda _=False, cmap_name=name: self._on_cmap_clicked(cmap_name))
            self._layout.addWidget(btn)

        self._add_separator()
        self._add_group("范围")
        self._add_toggle_row(
            "各相使用相同温标", self._sync_temp_scale, self._on_sync_temp_toggled
        )
        self._add_toggle_row(
            "压力共用色阶", self._shared_pressure_scale, self._on_shared_pressure_toggled
        )

        self._add_separator()
        reset_btn = QPushButton()
        reset_btn.setFixedHeight(32)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 7px; "
            "text-align: left; }"
            f"QPushButton:hover {{ background: {t['row_hover']}; }}"
        )
        rhl = QHBoxLayout(reset_btn)
        rhl.setContentsMargins(10, 0, 10, 0)
        rhl.setSpacing(9)
        ric = QLabel()
        ric.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        ric.setPixmap(_render_icon("reset", t["sub"], 15).pixmap(QSize(15, 15)))
        ric.setFixedSize(15, 15)
        ric.setStyleSheet("background: transparent;")
        rhl.addWidget(ric)
        rlbl = QLabel("恢复默认色阶")
        rlbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        rlbl.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; font-weight: 400; background: transparent;"
        )
        rhl.addWidget(rlbl)
        rhl.addStretch(1)
        reset_btn.clicked.connect(self._on_reset_clicked)
        self._layout.addWidget(reset_btn)

        self.adjustSize()
        self.update()
