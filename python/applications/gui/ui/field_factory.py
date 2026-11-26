"""Themed widget builders and Alignment Rule A input fields for the GUI."""
from __future__ import annotations

import re
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "FieldFactory",
    "UnitLineEdit",
    "default_factory",
    "set_default_factory",
]

_FACTORY: Optional["FieldFactory"] = None


def set_default_factory(factory: Optional["FieldFactory"]) -> None:
    """Install the process-wide widget factory backed by the live ThemeManager."""
    global _FACTORY
    _FACTORY = factory


def default_factory() -> "FieldFactory":
    """Return the installed factory or build one backed by a fresh ThemeManager."""
    global _FACTORY
    if _FACTORY is None:
        from sjtu_tpmshx.applications.gui.ui.theme_manager import ThemeManager

        _FACTORY = FieldFactory(ThemeManager())
    return _FACTORY


class UnitLineEdit(QLineEdit):
    """Line edit with an Alignment Rule A muted unit suffix painted inside the field.

    The underlying ``text()`` stays exact in SI storage units for parsing,
    serialization, and undo. Unfocused display formats numbers to 6 significant
    digits in ``display_unit``; focus switches the suffix to ``raw_unit`` so the
    displayed unit always matches the editable numeric value.
    """

    def __init__(
        self,
        text: str = "",
        unit: str = "",
        *,
        display_unit: str = "",
        display_scale: float = 1.0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        font = self.font()
        font.setFeature(QFont.Tag("tnum"), 1)
        self.setFont(font)
        self._unit_label = QLabel(self)
        self._unit_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._unit_label.setObjectName("fieldUnitSuffix")
        self._raw_unit = (unit or "").strip()
        self._display_unit = (display_unit or self._raw_unit).strip()
        self._display_scale = float(display_scale)
        self._unit = ""
        self._apply_suffix(self._display_unit)

    def unit(self) -> str:
        """Return the active muted unit suffix text."""
        return self._unit

    def set_display_unit(self, display_unit: str, display_scale: float = 1.0) -> None:
        """Configure scaled unfocused display (e.g. Pa -> kPa, m -> mm)."""
        self._display_unit = (display_unit or self._raw_unit).strip()
        self._display_scale = float(display_scale)
        self._apply_suffix(self._raw_unit if self.hasFocus() else self._display_unit)
        self.update()

    def set_unit(self, unit: str) -> None:
        """Update the raw unit suffix (and display unit when unscaled)."""
        clean = (unit or "").strip()
        self._raw_unit = clean
        if self._display_scale == 1.0:
            self._display_unit = clean
        self._apply_suffix(self._raw_unit if self.hasFocus() else self._display_unit)

    def _apply_suffix(self, text: str) -> None:
        from sjtu_tpmshx.applications.gui.ui.theme import get_theme

        self._unit = (text or "").strip()
        if self._unit:
            t = get_theme()
            self._unit_label.setText(self._unit)
            self._unit_label.setStyleSheet(
                f"color:{t['tert']}; font-size:12px; font-weight:400; "
                "background:transparent; border:none;"
            )
            self._unit_label.adjustSize()
            self._unit_label.show()
            self.setTextMargins(0, 0, self._unit_label.width() + 7, 0)
            self._position_unit()
        else:
            self._unit_label.hide()
            self.setTextMargins(0, 0, 0, 0)

    def _position_unit(self) -> None:
        if not self._unit:
            return
        self._unit_label.adjustSize()
        x = self.width() - self._unit_label.width() - 8
        y = (self.height() - self._unit_label.height()) // 2
        self._unit_label.move(max(0, x), max(0, y))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_unit()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self._raw_unit != self._unit:
            self._apply_suffix(self._raw_unit)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self._display_unit != self._unit:
            self._apply_suffix(self._display_unit)
        self.update()

    def formatted_display_text(self) -> str:
        """Return the 6-significant-digit unfocused display text without mutating ``text()``."""
        raw = self.text().strip()
        if not raw:
            return raw
        from sjtu_tpmshx.applications.gui.ui.fmt import display_number

        return display_number(raw, scale=self._display_scale)

    def paintEvent(self, event) -> None:
        raw = self.text()
        if self.hasFocus() or not raw.strip():
            super().paintEvent(event)
            return
        shown = self.formatted_display_text()
        if shown == raw and self._display_scale == 1.0:
            super().paintEvent(event)
            return
        from PySide6.QtGui import QPainter
        from PySide6.QtWidgets import QStyle, QStyleOptionFrame

        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_PanelLineEdit, opt, painter, self)
        rect = self.style().subElementRect(QStyle.SubElement.SE_LineEditContents, opt, self)
        margins = self.textMargins()
        rect.adjust(margins.left() + 2, margins.top(), -margins.right(), -margins.bottom())
        role = QPalette.ColorRole.Text if self.isEnabled() else QPalette.ColorRole.PlaceholderText
        painter.setPen(self.palette().color(role))
        painter.setFont(self.font())
        painter.drawText(rect, int(self.alignment()), shown)
        painter.end()


def _split_trailing_unit(label_text: str) -> tuple[str, str]:
    """Split a trailing ``[unit]`` bracket off a row caption for Rule A suffixes."""
    match = re.search(r"\s*\[([^\[\]]+)\]\s*$", label_text or "")
    if not match:
        return label_text, ""
    return label_text[: match.start()].rstrip(), match.group(1).strip()


class FieldFactory:
    """Build Style P2 themed labels, Rule A inputs, result rows, and sections."""

    def __init__(self, theme_manager) -> None:
        self._tm = theme_manager

    @property
    def theme(self):
        return self._tm

    def label(
        self,
        text: str,
        *,
        style_key: str = "LBL",
        rich: bool = True,
        word_wrap: bool = True,
    ) -> QLabel:
        """Build a themed QLabel."""
        lbl = QLabel(text)
        if rich:
            lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setStyleSheet(self._tm.style(style_key))
        lbl.setWordWrap(word_wrap)
        return lbl

    def line_edit(
        self,
        default: str = "",
        *,
        style_key: str = "INP",
        unit: str = "",
        placeholder: Optional[str] = None,
        tooltip: Optional[str] = None,
    ) -> UnitLineEdit:
        """Build a themed Rule A line edit with an optional muted unit suffix."""
        le = UnitLineEdit(default, unit=unit)
        le.setStyleSheet(self._tm.style(style_key))
        le.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if placeholder is not None:
            le.setPlaceholderText(placeholder)
        if tooltip is not None:
            le.setToolTip(tooltip)
        return le

    def result_label(
        self,
        *,
        unit_hint: str = "",
        quantity_name: str = "",
    ) -> "_ResultLabel":
        """Build a result label that switches empty and filled states."""
        val = _ResultLabel("—", unit_hint=unit_hint, quantity_name=quantity_name)
        val.setProperty("valState", "empty")
        val.setStyleSheet(self._tm.style("VAL"))
        font = val.font()
        font.setFeature(QFont.Tag("tnum"), 1)
        val.setFont(font)
        return val

    def row(
        self,
        g: QGridLayout,
        row_idx: int,
        text: str,
        default: str,
        *,
        unit: Optional[str] = None,
        tooltip: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> UnitLineEdit:
        """Add ``(label, UnitLineEdit)`` on ``row_idx`` with Rule A unit suffix."""
        if unit is None:
            caption, suffix = _split_trailing_unit(text)
        else:
            caption, suffix = text, unit
        lbl = self.label(caption)
        le = self.line_edit(
            default,
            unit=suffix,
            tooltip=tooltip,
            placeholder=placeholder,
        )
        g.addWidget(lbl, row_idx, 0)
        g.addWidget(le, row_idx, 1)
        return le

    def res_row(
        self,
        g: QGridLayout,
        row_idx: int,
        text: str,
        col: int = 0,
    ) -> "_ResultLabel":
        """Add ``(label, _ResultLabel)`` on ``row_idx``."""
        lbl = self.label(text)
        unit_hint, qty_name = _parse_unit_from_label(text)
        val = self.result_label(unit_hint=unit_hint, quantity_name=qty_name)
        g.addWidget(lbl, row_idx, col)
        g.addWidget(val, row_idx, col + 1)
        return val

    def add_row(
        self,
        g: QGridLayout,
        row_idx: int,
        text: str,
        widget: QWidget,
    ) -> QWidget:
        """Add ``(label, widget)`` on ``row_idx``."""
        lbl = self.label(text)
        g.addWidget(lbl, row_idx, 0)
        g.addWidget(widget, row_idx, 1)
        return widget

    def section(
        self,
        parent_lay,
        title: str,
        title_style: str,
        frame_style: str,
    ) -> Tuple[QGridLayout, QWidget]:
        """Build a neutral Style P2 band section with a Rule A two-column grid."""
        from .theme import get_theme

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        clay = QVBoxLayout(container)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setSpacing(0)

        t = QLabel((title or "").strip())
        t.setObjectName("secTitle")
        t.setStyleSheet(title_style)
        t.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        fg_color = QColor(get_theme()["sub"])
        pal = t.palette()
        pal.setColor(QPalette.ColorRole.WindowText, fg_color)
        pal.setColor(QPalette.ColorRole.Text, fg_color)
        t.setPalette(pal)
        clay.addWidget(t)

        frame = QFrame()
        frame.setStyleSheet(frame_style)
        g = QGridLayout(frame)
        g.setContentsMargins(16, 10, 16, 12)
        g.setVerticalSpacing(7)
        g.setHorizontalSpacing(10)
        g.setColumnStretch(0, 1)
        g.setColumnMinimumWidth(1, 150)
        clay.addWidget(frame)

        parent_lay.addWidget(container)
        return g, container

    def __repr__(self) -> str:
        return f"<FieldFactory theme={self._tm!r}>"


class _ResultLabel(QLabel):
    """Show empty or filled value styles and provide unit-aware copy actions."""

    _EMPTY_TOKENS = ("—", "-", "", None)

    def __init__(self, *args, unit_hint="", quantity_name="", **kw) -> None:
        super().__init__(*args, **kw)
        self._unit_hint = unit_hint
        self._quantity_name = quantity_name
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)

    def setText(self, txt) -> None:  # type: ignore[override]
        super().setText(txt if txt is not None else "—")
        state = "empty" if (txt in self._EMPTY_TOKENS) else "filled"
        if self.property("valState") != state:
            self.setProperty("valState", state)
            self.style().unpolish(self)
            self.style().polish(self)

    def _show_ctx_menu(self, pos) -> None:
        from PySide6.QtWidgets import QApplication, QMenu

        txt = self.text()
        is_empty = txt in self._EMPTY_TOKENS
        menu = QMenu(self)
        act_val = menu.addAction("复制数值")
        act_val.setEnabled(not is_empty)
        unit_suffix = f"  [{self._unit_hint}]" if self._unit_hint else ""
        act_unit = menu.addAction(f"复制数值与单位{unit_suffix}")
        act_unit.setEnabled(not is_empty and bool(self._unit_hint))
        menu.addSeparator()
        act_qty = menu.addAction(f"复制为赋值式（{self._quantity_name or 'value'} = …）")
        act_qty.setEnabled(not is_empty)
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        cb = QApplication.clipboard()
        if chosen is act_val:
            cb.setText(txt)
        elif chosen is act_unit and self._unit_hint:
            cb.setText(f"{txt} {self._unit_hint}")
        elif chosen is act_qty:
            q = self._quantity_name or "value"
            cb.setText(f"{q} = {txt}" + (f" [{self._unit_hint}]" if self._unit_hint else ""))


_ENTITY_MAP = {
    "&nbsp;": " ",
    "&epsilon;": "ε",
    "&mu;": "μ",
    "&rho;": "ρ",
    "&sigma;": "σ",
    "&phi;": "φ",
    "&psi;": "ψ",
    "&theta;": "θ",
    "&lambda;": "λ",
    "&alpha;": "α",
    "&beta;": "β",
    "&gamma;": "γ",
    "&delta;": "δ",
    "&Delta;": "Δ",
    "&eta;": "η",
    "&kappa;": "κ",
    "&pi;": "π",
    "&tau;": "τ",
    "&omega;": "ω",
    "&middot;": "·",
    "&plusmn;": "±",
    "&deg;": "°",
}


def _parse_unit_from_label(text: str) -> tuple[str, str]:
    """Read the trailing unit and quantity name after removing HTML markup."""
    plain = re.sub(r"<[^>]+>", "", text or "")
    for ent, ch in _ENTITY_MAP.items():
        plain = plain.replace(ent, ch)
    plain = plain.strip()
    m = re.search(r"\[([^\[\]]+)\]\s*$", plain)
    unit = m.group(1).strip() if m else ""
    name = (plain[: m.start()] if m else plain).strip().rstrip(",:")
    return unit, name
