"""Themed widget builders shared by the parameter pages.

``FieldFactory`` owns themed rows, sections and result-value widgets.
Page builders use the installed factory and its ThemeManager reference.
This module does not import page builders or ``main``.

    f = FieldFactory(theme_manager)
    le = f.row(grid, row_idx, "L [m]", "0.080")
    val = f.res_row(grid, row_idx, "ε [-]")
    f.section(parent_lay, title="Geometry", title_style=..., frame_style=...)

"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QLineEdit, QVBoxLayout,
    QWidget,
)


__all__ = ['FieldFactory', 'default_factory', 'set_default_factory']


# Created lazily or installed by Main_Menu with its active ThemeManager.
_FACTORY: Optional['FieldFactory'] = None


def set_default_factory(factory: Optional['FieldFactory']) -> None:
    """Install the process-wide factory. ``Main_Menu.__init__`` calls this
    after instantiating its ThemeManager so ``ui_builders`` helpers can
    pick up a coherent factory without each helper rebuilding one."""
    global _FACTORY
    _FACTORY = factory


def default_factory() -> 'FieldFactory':
    """Return the installed process factory, or a stand-alone fallback.

    The fallback constructs a fresh :class:`FieldFactory` with a brand-new
    :class:`ui.theme_manager.ThemeManager`. This keeps unit
    tests + headless validation runs working when no Main_Menu has been
    built; the styles will mirror whatever ``ui.theme`` reports.
    """
    global _FACTORY
    if _FACTORY is None:
        # Lazy import: theme_manager pulls Qt; importing it at module top
        # would force pytest collection to spin Qt for tests that don't
        # need styling.
        from sjtu_tpmshx.ui.theme_manager import ThemeManager
        _FACTORY = FieldFactory(ThemeManager())
    return _FACTORY


class FieldFactory:
    """Builds themed widgets and composite rows.

    All constructors return raw Qt widgets — no special wrapper. The
    style strings come from the bound :class:`ThemeManager` cache.
    Appearance changes are applied to the full workbench after restart.
    """

    def __init__(self, theme_manager):
        self._tm = theme_manager

    # ------------------------------------------------------------------ access

    @property
    def theme(self):
        return self._tm

    # ------------------------------------------------------------------ atoms

    def label(self, text: str, *, style_key: str = 'LBL',
              rich: bool = True, word_wrap: bool = True) -> QLabel:
        """Build a themed QLabel. Default style key = 'LBL' (row caption).

        Pass ``rich=False`` for plain text labels (no HTML interpretation —
        helpful when displaying user-supplied values that may contain
        ``<``).

        ``word_wrap`` defaults ON (ui-layout-fixes, 2026-07-03): unwrapped
        rich-text row captions set the grid's minimum width and pushed the
        param pages into a horizontal scrollbar + clipped inputs. Wrapping
        lets the label yield instead of widening the card.
        """
        lbl = QLabel(text)
        if rich:
            lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setStyleSheet(self._tm.style(style_key))
        lbl.setWordWrap(word_wrap)
        return lbl

    def line_edit(self, default: str = '',
                  *, style_key: str = 'INP',
                  placeholder: Optional[str] = None,
                  tooltip: Optional[str] = None) -> QLineEdit:
        """Build a themed QLineEdit. Style key default = 'INP'."""
        le = QLineEdit(default)
        le.setStyleSheet(self._tm.style(style_key))
        # Numeric inputs share the same right edge within each card.
        le.setAlignment(Qt.AlignmentFlag.AlignRight |
                        Qt.AlignmentFlag.AlignVCenter)
        if placeholder is not None:
            le.setPlaceholderText(placeholder)
        if tooltip is not None:
            le.setToolTip(tooltip)
        return le

    def result_label(self, *, unit_hint: str = '',
                     quantity_name: str = '') -> '_ResultLabel':
        """Build a result label that flips empty/filled style on text set."""
        val = _ResultLabel('—', unit_hint=unit_hint,
                            quantity_name=quantity_name)
        val.setProperty('valState', 'empty')
        val.setStyleSheet(self._tm.style('VAL'))
        return val

    # ------------------------------------------------------------------ rows

    def row(self, g: QGridLayout, row_idx: int, text: str,
            default: str, *, tooltip: Optional[str] = None,
            placeholder: Optional[str] = None) -> QLineEdit:
        """Add (label, line-edit) on row ``row_idx`` columns 0/1. Returns
        the QLineEdit for further wiring (validator / signal)."""
        lbl = self.label(text)
        le = self.line_edit(default, tooltip=tooltip,
                            placeholder=placeholder)
        g.addWidget(lbl, row_idx, 0)
        g.addWidget(le, row_idx, 1)
        return le

    def res_row(self, g: QGridLayout, row_idx: int, text: str,
                col: int = 0) -> '_ResultLabel':
        """Add (label, result-label) at cols ``col``/``col+1``. The unit
        hint is parsed from the trailing ``[unit]`` token in ``text``."""
        lbl = self.label(text)
        unit_hint, qty_name = _parse_unit_from_label(text)
        val = self.result_label(unit_hint=unit_hint, quantity_name=qty_name)
        g.addWidget(lbl, row_idx, col)
        g.addWidget(val, row_idx, col + 1)
        return val

    def add_row(self, g: QGridLayout, row_idx: int, text: str,
                widget: QWidget) -> QWidget:
        """Add (label, ``widget``) to row ``row_idx``. Returns ``widget``."""
        lbl = self.label(text)
        g.addWidget(lbl, row_idx, 0)
        g.addWidget(widget, row_idx, 1)
        return widget

    # ------------------------------------------------------------------ sections

    def section(self, parent_lay, title: str,
                title_style: str, frame_style: str
                ) -> Tuple[QGridLayout, QWidget]:
        """Build a titled card. Returns ``(grid, container)``.

        Shared title spacing keeps every parameter card visually separated.
        """
        container = QWidget()
        container.setStyleSheet('background:transparent;')
        clay = QVBoxLayout(container)
        clay.setContentsMargins(0, 8, 0, 0)
        clay.setSpacing(6)

        t = QLabel(title)
        t.setObjectName('secTitle')
        t.setStyleSheet(title_style)
        t.setAlignment(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter)

        # Belt-and-suspenders palette pinning (see ui_builders.section
        # for the QSS-vs-palette inheritance comment).
        from .theme import get_theme
        _tt_fg = QColor(get_theme()['title_fg'])
        _pal = t.palette()
        _pal.setColor(QPalette.ColorRole.WindowText, _tt_fg)
        _pal.setColor(QPalette.ColorRole.Text, _tt_fg)
        t.setPalette(_pal)
        clay.addWidget(t)

        frame = QFrame()
        frame.setStyleSheet(frame_style)
        g = QGridLayout(frame)
        g.setContentsMargins(12, 10, 12, 10)
        g.setVerticalSpacing(8)
        g.setHorizontalSpacing(10)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)
        clay.addWidget(frame)

        parent_lay.addWidget(container)
        return g, container

    def __repr__(self) -> str:
        return f'<FieldFactory theme={self._tm!r}>'


class _ResultLabel(QLabel):
    """Show empty or filled value styles and provide unit-aware copy actions."""
    _EMPTY_TOKENS = ('—', '-', '', None)

    def __init__(self, *args, unit_hint="", quantity_name="", **kw):
        super().__init__(*args, **kw)
        self._unit_hint = unit_hint
        self._quantity_name = quantity_name
        from PySide6.QtCore import Qt as _Qt
        self.setContextMenuPolicy(_Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)

    def setText(self, txt):  # type: ignore[override]
        super().setText(txt if txt is not None else '—')
        state = 'empty' if (txt in self._EMPTY_TOKENS) else 'filled'
        if self.property('valState') != state:
            self.setProperty('valState', state)
            self.style().unpolish(self)
            self.style().polish(self)

    def _show_ctx_menu(self, pos):
        from PySide6.QtWidgets import QMenu, QApplication
        txt = self.text()
        is_empty = txt in self._EMPTY_TOKENS
        menu = QMenu(self)
        act_val = menu.addAction("&Copy value")
        act_val.setEnabled(not is_empty)
        unit_suffix = f"  [{self._unit_hint}]" if self._unit_hint else ""
        act_unit = menu.addAction(f"Copy with &units{unit_suffix}")
        act_unit.setEnabled(not is_empty and bool(self._unit_hint))
        menu.addSeparator()
        act_qty = menu.addAction(
            f"Copy as &assignment ({self._quantity_name or 'value'} = …)")
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
            cb.setText(f"{q} = {txt}" + (
                f" [{self._unit_hint}]" if self._unit_hint else ""))


_ENTITY_MAP = {
    '&nbsp;': ' ',
    '&epsilon;': 'ε', '&mu;': 'μ', '&rho;': 'ρ', '&sigma;': 'σ',
    '&phi;': 'φ', '&psi;': 'ψ', '&theta;': 'θ', '&lambda;': 'λ',
    '&alpha;': 'α', '&beta;': 'β', '&gamma;': 'γ', '&delta;': 'δ',
    '&Delta;': 'Δ', '&eta;': 'η', '&kappa;': 'κ', '&pi;': 'π',
    '&tau;': 'τ', '&omega;': 'ω',
    '&middot;': '·', '&plusmn;': '±', '&deg;': '°',
}


def _parse_unit_from_label(text):
    """Read the trailing unit and quantity name after removing HTML markup."""
    import re as _re_u
    plain = _re_u.sub(r"<[^>]+>", "", text or "")
    for ent, ch in _ENTITY_MAP.items():
        plain = plain.replace(ent, ch)
    plain = plain.strip()
    m = _re_u.search(r"\[([^\[\]]+)\]\s*$", plain)
    unit = m.group(1).strip() if m else ""
    name = (plain[:m.start()] if m else plain).strip().rstrip(",:")
    return unit, name
