"""Quick Design floating peek card and Optimization selected-design drawer content."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.applications.gui.ui.symbols import SYM, val_unit
from sjtu_tpmshx.applications.gui.ui.theme import get_theme

_FIELD_WIDTH_DESKTOP = 168
_FIELD_WIDTH_COMPACT = 150

_STATUS_COLOR_KEY: dict[str, str] = {
    "ok": "ok",
    "warn": "warn",
    "err": "err",
    "run": "accent_fg",
    "idle": "tert",
}

_TAG_LABELS: dict[str, str] = {
    "min-V": "最小体积",
    "min-wt": "最轻",
    "min-dP": "最小压损",
}

_ICON_PATHS: dict[str, str] = {
    "upload": (
        '<path d="M12 3v12"/><path d="m17 8-5-5-5 5"/>'
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    ),
    "download": (
        '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<path d="m7 10 5 5 5-5"/>'
    ),
    "chevr": '<path d="m9 18 6-6-6-6"/>',
}


@dataclass(frozen=True)
class PeekDesignData:
    """Plain-value Quick Design summary shown in ``DesignPeekCard``."""

    index: int
    topo: str
    l_mm: float
    t_mm: float
    V_m3: float
    weight_kg: float
    dP_hot_max: float
    dP_cold_max: float
    Re_hot_max: float
    Re_cold_max: float
    tags: Sequence[str] = ()
    validity_kind: str = "ok"
    validity_text: str = "域内"


@dataclass(frozen=True)
class ObjectiveCell:
    """Single objective readout cell inside ``SelectedDesignPanel``."""

    label: str
    value: str
    tone: str = "fg"


@dataclass(frozen=True)
class SpecRow:
    """Key-value specification row inside ``SelectedDesignPanel``."""

    label: str
    value: str
    status_kind: str | None = None
    tone: str = "fg"


@dataclass(frozen=True)
class FrontListItem:
    """Single clickable row in the dot-track Pareto or candidate front list."""

    index: int
    primary_value: float
    primary_text: str
    secondary_text: str
    secondary_tone: str = "sub"


@dataclass(frozen=True)
class ConditionCell:
    """Single operating condition entry in the condition grid."""

    condition_id: str
    mass_flow_a_kg_s: float | None = None
    mass_flow_b_kg_s: float | None = None
    detail_text: str = ""


@dataclass(frozen=True)
class SelectedQuickDesignData:
    """Plain-value Quick Design snapshot shown in the ``所选设计`` drawer tab."""

    title_html: str
    tags: Sequence[str] = ()
    objectives: tuple[ObjectiveCell, ObjectiveCell] = (
        ObjectiveCell("芯体体积", "—"),
        ObjectiveCell("重量", "—"),
    )
    spec_rows: Sequence[SpecRow] = ()
    case_rows: Sequence[tuple[str, str]] = ()


@dataclass(frozen=True)
class SelectedDesignData:
    """Plain-value snapshot rendered by ``SelectedDesignPanel``."""

    index: int
    objectives: tuple[ObjectiveCell, ObjectiveCell]
    spec_rows: Sequence[SpecRow] = ()
    front_items: Sequence[FrontListItem] = ()
    conditions: Sequence[ConditionCell] = ()
    tag: str = "Pareto 前沿"
    front_title: str = "前沿方案"
    front_sort_label: str = "压降比 ↑"
    objective_mode: str = "mean"
    can_load: bool = True
    can_export: bool = True


def format_objective_summary(n_conditions: int, objective_mode: str = "mean") -> str:
    """Format the locked objective wording for optimization drawers."""
    if objective_mode in ("mass", "mass_requirements"):
        return "逐项达标"
    if n_conditions <= 1:
        return "当前工况"
    return f"{n_conditions} 工况均值"


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


def _make_label(
    text: str,
    size_px: float,
    color_hex: str,
    weight: int = 400,
    align: Qt.AlignmentFlag | None = None,
) -> QLabel:
    lab = QLabel(text)
    if "<" in text:
        lab.setTextFormat(Qt.TextFormat.RichText)
    if align is not None:
        lab.setAlignment(align)
    lab.setStyleSheet(
        f"color: {color_hex}; font-size: {size_px}px; font-weight: {weight}; "
        "background: transparent;"
    )
    _enable_tnum(lab)
    return lab


def _status_mark(kind: str, tokens: Mapping[str, Any], size: float = 6.5) -> QLabel:
    color = QColor(tokens[_STATUS_COLOR_KEY.get(kind, "tert")])
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
    """Single-device-pixel horizontal or vertical divider."""

    def __init__(
        self,
        color_hex: str,
        *,
        vertical: bool = False,
        length: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self._vertical = vertical
        if vertical:
            if length is not None:
                self.setFixedSize(1, length)
            else:
                self.setFixedWidth(1)
                self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        if self._vertical:
            painter.drawLine(QPointF(0.25, 0.0), QPointF(0.25, float(self.height())))
        else:
            painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()


def _inset_hairline(color_hex: str, left: int = 16, right: int = 0) -> QWidget:
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(left, 0, right, 0)
    lay.setSpacing(0)
    lay.addWidget(_Hairline(color_hex))
    return wrap


class _CrispFrame(QFrame):
    """Rounded frame with a crisp 1-device-pixel border."""

    def __init__(
        self,
        *,
        radius: float,
        bg_hex: str,
        border_hex: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._radius = radius
        self._bg = QColor(bg_hex)
        self._border = QColor(border_hex)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(self._bg)
        painter.setPen(QPen(self._border, 0.5))
        painter.drawRoundedRect(rect, self._radius, self._radius)
        painter.end()


def _tag_chip(text: str, tokens: Mapping[str, Any], *, accent: bool = False) -> QFrame:
    bg = tokens["accent_soft"] if accent else tokens["sunken"]
    fg = tokens["accent_fg"] if accent else tokens["sub"]
    weight = 600 if accent else 500
    chip = _CrispFrame(radius=5.0, bg_hex=bg, border_hex=tokens["border"])
    chip.setFixedHeight(20)
    chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    lay = QHBoxLayout(chip)
    lay.setContentsMargins(6, 1, 6, 1)
    lay.setSpacing(0)
    lay.addWidget(_make_label(text, 10.5, fg, weight=weight))
    return chip


class MinimalDotTrack(QWidget):
    """Compact horizontal position track with a single dot marker."""

    def __init__(
        self,
        fraction: float,
        *,
        active: bool = False,
        width: int = 60,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self._active = active
        self.setFixedSize(width, 16)

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Update track and dot colors from Style P2 theme tokens."""
        self._tokens.update(tokens)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        cy = h / 2.0
        painter.setPen(QPen(QColor(self._tokens["border_strong"]), 0.75))
        painter.drawLine(QPointF(4.0, cy), QPointF(w - 4.0, cy))
        painter.setPen(Qt.PenStyle.NoPen)
        color = self._tokens["accent"] if self._active else self._tokens["tert"]
        painter.setBrush(QColor(color))
        cx = 4.0 + self._fraction * (w - 8.0)
        radius = 3.0 if self._active else 2.1
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.end()


class _FrontRow(QFrame):
    """Clickable Pareto front row with dot track and hover highlight."""

    clicked = Signal(int)

    def __init__(
        self,
        item: FrontListItem,
        *,
        fraction: float,
        selected: bool,
        track_width: int,
        tokens: Mapping[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = item.index
        self._selected = selected
        self._tokens = tokens
        self.setObjectName("frontRowSel" if selected else "frontRow")
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if selected:
            self.setStyleSheet(
                f"QFrame#frontRowSel {{ background: {tokens['accent_soft']}; "
                "border: none; border-radius: 7px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#frontRow { background: transparent; border: none; border-radius: 7px; }"
                f"QFrame#frontRow:hover {{ background: {tokens['row_hover']}; }}"
            )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        id_lab = _make_label(
            f"#{item.index}",
            12.5,
            tokens["accent_fg"] if selected else tokens["fg"],
            weight=600 if selected else 400,
        )
        id_lab.setFixedWidth(28)
        lay.addWidget(id_lab)

        lay.addWidget(
            MinimalDotTrack(fraction, active=selected, width=track_width, tokens=tokens)
        )
        lay.addStretch(1)

        primary_lab = _make_label(
            item.primary_text,
            12.5,
            tokens["fg"],
            weight=600 if selected else 400,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        primary_lab.setFixedWidth(60)
        lay.addWidget(primary_lab)

        sec_color = tokens.get(item.secondary_tone, tokens["sub"])
        secondary_lab = _make_label(
            item.secondary_text,
            12.5,
            sec_color,
            weight=600 if selected else 400,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        secondary_lab.setFixedWidth(72)
        lay.addWidget(secondary_lab)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)
            event.accept()
            return
        super().mousePressEvent(event)


def _band_header(
    title: str,
    tokens: Mapping[str, Any],
    *,
    first: bool = False,
    count: int | None = None,
    tag: str | None = None,
    right_text: str | None = None,
    actions: Sequence[tuple[str, str, bool, Callable[[], None]]] = (),
) -> QWidget:
    """Neutral section band header without colored side strips or underlines."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    vl = QVBoxLayout(wrap)
    vl.setContentsMargins(0, 0, 0, 0)
    vl.setSpacing(0)

    if not first:
        vl.addWidget(_Hairline(tokens["border"]))

    bar = QFrame()
    bar.setObjectName("designBandBar")
    bar.setFixedHeight(31)
    bar.setStyleSheet(f"QFrame#designBandBar {{ background: {tokens['sunken']}; border: none; }}")
    hl = QHBoxLayout(bar)
    hl.setContentsMargins(16, 0, 12, 0)
    hl.setSpacing(6)

    hl.addWidget(_make_label(title, 11.5, tokens["sub"], weight=600))
    if count is not None:
        hl.addWidget(_make_label(str(count), 11.5, tokens["tert"], weight=500))
    if tag:
        hl.addWidget(_tag_chip(tag, tokens, accent=True))
    hl.addStretch(1)

    if right_text:
        hl.addWidget(_make_label(right_text, 11.0, tokens["tert"], weight=500))

    for text, icon_name, enabled, callback in actions:
        btn = QPushButton(text)
        btn.setFixedHeight(20)
        btn.setEnabled(enabled)
        btn.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        icon_color = tokens["accent_fg"] if enabled else tokens["tert"]
        btn.setIcon(_render_icon(icon_name, icon_color, size=13, stroke=1.75))
        btn.setIconSize(QSize(13, 13))
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {icon_color}; "
            "padding: 0 2px 0 4px; font-size: 12px; font-weight: 500; border-radius: 5px; }"
            f"QPushButton:hover {{ background: {tokens['hover']}; }}"
        )
        btn.clicked.connect(callback)
        hl.addWidget(btn)

    vl.addWidget(bar)
    vl.addWidget(_Hairline(tokens["border"]))
    return wrap


class DesignPeekCard(QWidget):
    """Floating bottom-left peek card for a selected Quick Design candidate."""

    details_requested = Signal(int)

    def __init__(
        self,
        data: PeekDesignData | None = None,
        *,
        shadow: bool = True,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._data: PeekDesignData | None = data
        self._shadow = shadow

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._outer = QVBoxLayout(self)
        pad = 14 if shadow else 0
        self._outer.setContentsMargins(pad, pad, pad, pad)
        self._outer.setSpacing(0)

        self._rebuild()

    def set_design(self, data: PeekDesignData | None) -> None:
        """Update the displayed design summary, or hide when None."""
        self._data = data
        self.setVisible(data is not None)
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens and rebuild the peek card."""
        self._tokens.update(tokens)
        self._rebuild()

    def _clear_outer(self) -> None:
        while self._outer.count():
            item = self._outer.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_outer()
        d = self._data
        if d is None:
            return
        t = self._tokens

        card = _CrispFrame(radius=10.0, bg_hex=t["popover"], border_hex=t["border"])
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        l_mm = val_unit(f"{d.l_mm:g}", "mm")
        t_mm = val_unit(f"{d.t_mm:g}", "mm")
        title_html = f"{d.topo} · {SYM['L']} {l_mm} · {SYM['t']} {t_mm}"
        title_col.addWidget(_make_label(title_html, 13.0, t["fg"], weight=600))

        if d.tags:
            tags_row = QHBoxLayout()
            tags_row.setContentsMargins(0, 0, 0, 0)
            tags_row.setSpacing(5)
            for tag in d.tags:
                tags_row.addWidget(_tag_chip(_TAG_LABELS.get(tag, tag), t, accent=False))
            tags_row.addStretch(1)
            title_col.addLayout(tags_row)
        lay.addLayout(title_col)

        lay.addWidget(_Hairline(t["border"], vertical=True, length=34))

        metrics = (
            (f"体积 {SYM['V']}", val_unit(f"{d.V_m3 * 1e3:.3f}", "L")),
            ("重量", val_unit(f"{d.weight_kg:.3f}", "kg")),
            (
                f"热 / 冷压损 {SYM['dP_rel']}",
                val_unit(f"{d.dP_hot_max * 100:.2f} / {d.dP_cold_max * 100:.2f}", "%"),
            ),
            (f"{SYM['Re']} 热 / 冷", f"{d.Re_hot_max:.0f} / {d.Re_cold_max:.0f}"),
        )
        for name, val in metrics:
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            col.addWidget(_make_label(name, 11.0, t["tert"], weight=400))
            col.addWidget(_make_label(val, 13.0, t["fg"], weight=500))
            lay.addLayout(col)

        lay.addWidget(_Hairline(t["border"], vertical=True, length=34))

        validity_row = QHBoxLayout()
        validity_row.setContentsMargins(0, 0, 0, 0)
        validity_row.setSpacing(6)
        validity_row.addWidget(_status_mark(d.validity_kind, t, size=6.5))
        validity_row.addWidget(_make_label(d.validity_text, 12.0, t["fg"], weight=500))
        lay.addLayout(validity_row)

        detail_btn = QPushButton("详情")
        detail_btn.setFixedHeight(26)
        detail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        detail_btn.setIcon(_render_icon("chevr", t["sub"], size=14, stroke=1.65))
        detail_btn.setIconSize(QSize(14, 14))
        detail_btn.setStyleSheet(
            f"QPushButton {{ background: {t['panel']}; border: 1px solid {t['border_strong']}; "
            f"border-radius: 6px; padding: 0 10px; font-size: 12px; color: {t['fg']}; }}"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
        )
        detail_btn.clicked.connect(lambda _=False, idx=d.index: self.details_requested.emit(idx))
        lay.addWidget(detail_btn)

        if self._shadow:
            key_fx = QGraphicsDropShadowEffect(card)
            key_fx.setBlurRadius(7)
            key_fx.setOffset(0, 2)
            key_fx.setColor(QColor(*t["shadow_key"]))
            card.setGraphicsEffect(key_fx)

            amb_fx = QGraphicsDropShadowEffect(self)
            amb_fx.setBlurRadius(24)
            amb_fx.setOffset(0, 5)
            amb_fx.setColor(QColor(*t["shadow_ambient"]))
            self.setGraphicsEffect(amb_fx)

        self._outer.addWidget(card)
        self.adjustSize()


class SelectedDesignPanel(QWidget):
    """Selected-design drawer content for Optimization in Style P2.

    Displays two objective cells, key-value specification rows, a clickable
    dot-track front list, and the operating-condition grid. Contains no mini
    Pareto chart, no grey captions, and no colored side strips.
    """

    load_requested = Signal(int)
    export_requested = Signal(int)
    front_item_selected = Signal(int)

    def __init__(
        self,
        data: SelectedDesignData | None = None,
        *,
        compact: bool = False,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._compact = compact
        self._data: SelectedDesignData | None = data

        self.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._rebuild()

    def set_data(self, data: SelectedDesignData | None) -> None:
        """Replace the selected design snapshot and rebuild the drawer body."""
        self._data = data
        self._rebuild()

    def set_compact(self, compact: bool) -> None:
        """Switch column and dot-track widths for narrow viewports."""
        if self._compact == compact:
            return
        self._compact = compact
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens and rebuild."""
        self._tokens.update(tokens)
        self._rebuild()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_layout()
        d = self._data
        t = self._tokens

        if d is None:
            empty = QWidget()
            empty.setStyleSheet("background: transparent;")
            el = QVBoxLayout(empty)
            el.setContentsMargins(16, 28, 16, 28)
            el.addWidget(
                _make_label(
                    "尚未选择方案",
                    12.5,
                    t["sub"],
                    align=Qt.AlignmentFlag.AlignCenter,
                )
            )
            self._layout.addWidget(empty)
            return

        # 1. Header band with Load and Export actions.
        self._layout.addWidget(
            _band_header(
                f"方案 #{d.index}",
                t,
                first=True,
                tag=d.tag or None,
                actions=(
                    (
                        "载入",
                        "upload",
                        d.can_load,
                        lambda _=False, idx=d.index: self.load_requested.emit(idx),
                    ),
                    (
                        "导出坐标",
                        "download",
                        d.can_export,
                        lambda _=False, idx=d.index: self.export_requested.emit(idx),
                    ),
                ),
            )
        )

        # 2. Two objective cells side by side.
        obj_bar = QWidget()
        obj_bar.setStyleSheet("background: transparent;")
        obj_bar.setFixedHeight(52)
        ol = QHBoxLayout(obj_bar)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)
        for pos, cell in enumerate(d.objectives):
            if pos:
                ol.addWidget(_Hairline(t["border"], vertical=True))
            col = QWidget()
            col.setStyleSheet("background: transparent;")
            cl = QVBoxLayout(col)
            cl.setContentsMargins(16, 6, 12, 6)
            cl.setSpacing(1)
            cl.addWidget(_make_label(cell.label, 11.0, t["sub"], weight=400))
            val_color = t.get(cell.tone, t["fg"])
            cl.addWidget(_make_label(cell.value, 15.0, val_color, weight=600))
            ol.addWidget(col, 1)
        self._layout.addWidget(obj_bar)
        self._layout.addWidget(_Hairline(t["border"]))

        # 3. Specification rows under Alignment Rule A.
        field_w = _FIELD_WIDTH_COMPACT if self._compact else _FIELD_WIDTH_DESKTOP
        if d.spec_rows:
            spec_block = QWidget()
            spec_block.setStyleSheet("background: transparent;")
            sv = QVBoxLayout(spec_block)
            sv.setContentsMargins(0, 0, 0, 0)
            sv.setSpacing(0)
            for idx, row in enumerate(d.spec_rows):
                if idx:
                    sv.addWidget(_inset_hairline(t["border"], left=16, right=0))
                rw = QWidget()
                rw.setStyleSheet("background: transparent;")
                rw.setFixedHeight(28)
                rl = QHBoxLayout(rw)
                rl.setContentsMargins(16, 0, 16, 0)
                rl.setSpacing(8)
                rl.addWidget(_make_label(row.label, 12.5, t["sub"], weight=400), 1)

                holder = QWidget()
                holder.setStyleSheet("background: transparent;")
                holder.setFixedWidth(field_w)
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(8, 0, 0, 0)
                hl.setSpacing(6)
                if row.status_kind is not None:
                    hl.addWidget(_status_mark(row.status_kind, t, size=6.5))
                val_color = t.get(row.tone, t["fg"])
                weight = 500 if row.status_kind is not None else 400
                hl.addWidget(_make_label(row.value, 12.5, val_color, weight=weight))
                hl.addStretch(1)
                rl.addWidget(holder)
                sv.addWidget(rw)
            self._layout.addWidget(spec_block)

        # 4. Dot-track front list.
        if d.front_items:
            self._layout.addWidget(
                _band_header(
                    d.front_title,
                    t,
                    count=len(d.front_items),
                    right_text=d.front_sort_label,
                )
            )
            values = [item.primary_value for item in d.front_items]
            v_lo, v_hi = min(values), max(values)
            span = max(1e-9, v_hi - v_lo)
            track_w = 42 if self._compact else 60

            fwrap = QWidget()
            fwrap.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fwrap)
            fl.setContentsMargins(8, 6, 8, 8)
            fl.setSpacing(0)
            items = list(d.front_items)
            for pos, item in enumerate(items):
                selected = item.index == d.index
                frac = 0.5 if v_hi == v_lo else (item.primary_value - v_lo) / span
                row_widget = _FrontRow(
                    item,
                    fraction=frac,
                    selected=selected,
                    track_width=track_w,
                    tokens=t,
                )
                row_widget.clicked.connect(self.front_item_selected.emit)
                fl.addWidget(row_widget)
                if (
                    pos < len(items) - 1
                    and not selected
                    and items[pos + 1].index != d.index
                ):
                    fl.addWidget(_inset_hairline(t["border"], left=8, right=8))
            self._layout.addWidget(fwrap)

        # 5. Condition grid with locked mass-flow header and objective wording.
        if d.conditions:
            n_cond = len(d.conditions)
            obj_text = format_objective_summary(n_cond, d.objective_mode)
            self._layout.addWidget(
                _band_header(
                    "工况",
                    t,
                    count=n_cond,
                    right_text=f"目标：{obj_text}",
                )
            )
            cwrap = QWidget()
            cwrap.setStyleSheet("background: transparent;")
            cw = QVBoxLayout(cwrap)
            cw.setContentsMargins(16, 8, 16, 12)
            cw.setSpacing(0)

            cgrid = _CrispFrame(radius=8.0, bg_hex=t["canvas"], border_hex=t["border"])
            cgv = QVBoxLayout(cgrid)
            cgv.setContentsMargins(1, 1, 1, 1)
            cgv.setSpacing(0)

            gh = QFrame()
            gh.setStyleSheet(
                f"background: {t['sunken']}; border: none; "
                "border-top-left-radius: 7px; border-top-right-radius: 7px;"
            )
            gh.setFixedHeight(25)
            ghl = QHBoxLayout(gh)
            ghl.setContentsMargins(10, 0, 10, 0)
            ghl.addWidget(
                _make_label(
                    f"质量流量 {SYM['m_A']} / {SYM['m_B']} [kg/s]",
                    11.0,
                    t["sub"],
                    weight=500,
                )
            )
            ghl.addStretch(1)
            if d.objective_mode in ("mass", "mass_requirements"):
                share_text = "逐项约束"
            elif n_cond > 1:
                share_text = f"各占 1/{n_cond}"
            else:
                share_text = ""
            if share_text:
                ghl.addWidget(_make_label(share_text, 11.0, t["tert"], weight=500))
            cgv.addWidget(gh)

            conds = list(d.conditions)
            cols = 1 if n_cond == 1 else 2
            for start in range(0, n_cond, cols):
                cgv.addWidget(_Hairline(t["border"]))
                rw = QWidget()
                rw.setStyleSheet("background: transparent;")
                rw.setFixedHeight(42)
                rl = QHBoxLayout(rw)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(0)
                for col_i in range(cols):
                    if col_i:
                        rl.addWidget(_Hairline(t["border"], vertical=True))
                    idx = start + col_i
                    cell = QWidget()
                    cell.setStyleSheet("background: transparent;")
                    cl = QVBoxLayout(cell)
                    cl.setContentsMargins(10, 4, 10, 4)
                    cl.setSpacing(1)
                    if idx < n_cond:
                        c = conds[idx]
                        cl.addWidget(_make_label(c.condition_id, 12.0, t["fg"], weight=600))
                        detail = c.detail_text
                        if not detail:
                            ma = "—" if c.mass_flow_a_kg_s is None else f"{c.mass_flow_a_kg_s:.4f}"
                            mb = "—" if c.mass_flow_b_kg_s is None else f"{c.mass_flow_b_kg_s:.4f}"
                            detail = f"A {ma} · B {mb}"
                        cl.addWidget(_make_label(detail, 11.0, t["tert"], weight=400))
                    rl.addWidget(cell, 1)
                cgv.addWidget(rw)

            cw.addWidget(cgrid)
            self._layout.addWidget(cwrap)


class SelectedQuickDesignPanel(QWidget):
    """Selected-design drawer content for Quick Design in Style P2."""

    def __init__(
        self,
        data: SelectedQuickDesignData | None = None,
        *,
        compact: bool = False,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._compact = compact
        self._data: SelectedQuickDesignData | None = data

        self.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rebuild()

    def set_data(self, data: SelectedQuickDesignData | None) -> None:
        """Replace the selected Quick Design snapshot and rebuild."""
        self._data = data
        self._rebuild()

    def set_compact(self, compact: bool) -> None:
        """Adjust value column width for compact viewports."""
        if self._compact == compact:
            return
        self._compact = compact
        self._rebuild()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens and rebuild."""
        self._tokens.update(tokens)
        self._rebuild()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_layout()
        d = self._data
        t = self._tokens

        if d is None:
            empty = QWidget()
            empty.setStyleSheet("background: transparent;")
            el = QVBoxLayout(empty)
            el.setContentsMargins(16, 28, 16, 28)
            el.addWidget(
                _make_label(
                    "尚未选择可行设计",
                    12.5,
                    t["sub"],
                    align=Qt.AlignmentFlag.AlignCenter,
                )
            )
            self._layout.addWidget(empty)
            return

        first_tag = _TAG_LABELS.get(d.tags[0], d.tags[0]) if d.tags else None
        self._layout.addWidget(_band_header(d.title_html, t, first=True, tag=first_tag))

        obj_bar = QWidget()
        obj_bar.setStyleSheet("background: transparent;")
        obj_bar.setFixedHeight(52)
        ol = QHBoxLayout(obj_bar)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)
        for pos, cell in enumerate(d.objectives):
            if pos:
                ol.addWidget(_Hairline(t["border"], vertical=True))
            col = QWidget()
            col.setStyleSheet("background: transparent;")
            cl = QVBoxLayout(col)
            cl.setContentsMargins(16, 6, 12, 6)
            cl.setSpacing(1)
            cl.addWidget(_make_label(cell.label, 11.0, t["sub"], weight=400))
            val_color = t.get(cell.tone, t["fg"])
            cl.addWidget(_make_label(cell.value, 15.0, val_color, weight=600))
            ol.addWidget(col, 1)
        self._layout.addWidget(obj_bar)
        self._layout.addWidget(_Hairline(t["border"]))

        field_w = _FIELD_WIDTH_COMPACT if self._compact else _FIELD_WIDTH_DESKTOP
        if d.spec_rows:
            spec_block = QWidget()
            spec_block.setStyleSheet("background: transparent;")
            sv = QVBoxLayout(spec_block)
            sv.setContentsMargins(0, 0, 0, 0)
            sv.setSpacing(0)
            for idx, row in enumerate(d.spec_rows):
                if idx:
                    sv.addWidget(_inset_hairline(t["border"], left=16, right=0))
                rw = QWidget()
                rw.setStyleSheet("background: transparent;")
                rw.setFixedHeight(28)
                rl = QHBoxLayout(rw)
                rl.setContentsMargins(16, 0, 16, 0)
                rl.setSpacing(8)
                rl.addWidget(_make_label(row.label, 12.5, t["sub"], weight=400), 1)

                holder = QWidget()
                holder.setStyleSheet("background: transparent;")
                holder.setFixedWidth(field_w)
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(8, 0, 0, 0)
                hl.setSpacing(6)
                if row.status_kind is not None:
                    hl.addWidget(_status_mark(row.status_kind, t, size=6.5))
                val_color = t.get(row.tone, t["fg"])
                weight = 500 if row.status_kind is not None else 400
                hl.addWidget(_make_label(row.value, 12.5, val_color, weight=weight))
                hl.addStretch(1)
                rl.addWidget(holder)
                sv.addWidget(rw)
            self._layout.addWidget(spec_block)

        if d.case_rows:
            self._layout.addWidget(_band_header("逐工况记录", t, count=len(d.case_rows)))
            cblock = QWidget()
            cblock.setStyleSheet("background: transparent;")
            cv = QVBoxLayout(cblock)
            cv.setContentsMargins(0, 0, 0, 8)
            cv.setSpacing(0)
            for idx, (cid, summary) in enumerate(d.case_rows):
                if idx:
                    cv.addWidget(_inset_hairline(t["border"], left=16, right=0))
                rw = QWidget()
                rw.setStyleSheet("background: transparent;")
                rl = QVBoxLayout(rw)
                rl.setContentsMargins(16, 6, 16, 6)
                rl.setSpacing(2)
                rl.addWidget(_make_label(cid, 12.0, t["fg"], weight=600))
                rl.addWidget(_make_label(summary, 11.0, t["sub"], weight=400))
                cv.addWidget(rw)
            self._layout.addWidget(cblock)


__all__ = [
    "ConditionCell",
    "DesignPeekCard",
    "FrontListItem",
    "MinimalDotTrack",
    "ObjectiveCell",
    "PeekDesignData",
    "SelectedDesignData",
    "SelectedDesignPanel",
    "SelectedQuickDesignData",
    "SelectedQuickDesignPanel",
    "SpecRow",
    "format_objective_summary",
]
