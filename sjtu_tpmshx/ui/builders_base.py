"""Shared widget-row factories for the page builders.

Split out of ui_builders.py (Batch-2, 2026-06-10): the pure helpers that
every ``build_page_*`` module uses — section/row/res_row/add_row (thin
Phase-5 delegators to FieldFactory), the COMPUTED divider, and the
``_ResultLabel`` value widget with its unit-parsing helper.

All functions keep the legacy ``window`` first argument for call-site
compatibility even where it is unused.
"""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame, QToolButton, QSizePolicy

from .theme import get_theme, RADIUS_INPUT
from .icons import icon


class MenuToolButton(QToolButton):
    """Native menu button with a small, theme-colored SVG chevron on the right."""

    def __init__(self, style, parent=None):
        super().__init__(parent)
        self._menu_chevron = icon('chevron-down', get_theme()['sub_fg'])
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setFixedHeight(36)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            style.replace('QPushButton', 'QToolButton')
            + 'QToolButton{padding:3px 26px 3px 10px;}'
            'QToolButton:focus{padding:2px 25px 2px 9px;}'
            'QToolButton::menu-indicator{image:none; width:0; height:0;}')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        self._menu_chevron.paint(
            painter, QRect(self.width() - 22, (self.height() - 12) // 2, 12, 12),
            Qt.AlignmentFlag.AlignCenter,
            QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled)
        painter.end()


def right_align_combo(combo):
    """Right-align a QComboBox's displayed text so combo rows read like the
    numeric inputs beside them (ui-plan3a follow-up, user request).

    Qt can't right-align a NON-editable combo via QSS, so: make it editable
    with a read-only line edit (alignment lives there), and re-open the
    popup on click since a read-only line edit swallows the press. Dropdown
    items get TextAlignmentRole for the same reading direction.
    """
    from PySide6.QtCore import QObject, QEvent
    combo.setEditable(True)
    le = combo.lineEdit()
    le.setReadOnly(True)
    le.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    t = get_theme()
    # The embedded QLineEdit doesn't inherit the combo QSS — keep it
    # invisible chrome (transparent, borderless) in the combo's text color.
    le.setStyleSheet(f"background:transparent; border:none;"
                     f" padding:0; color:{t['inp_fg']}; font-weight:400;")
    # The editable label needs room for QLineEdit's internal text/cursor
    # margins in addition to the combo's arrow and stylesheet padding.
    combo.ensurePolished()
    combo.setMinimumWidth(combo.sizeHint().width() + 8)

    class _PopupOnClick(QObject):
        def eventFilter(self, _obj, ev):
            if ev.type() == QEvent.Type.MouseButtonPress:
                combo.showPopup()
                return True
            return False

    filt = _PopupOnClick(combo)
    le.installEventFilter(filt)
    combo._right_align_filter = filt      # keep the filter alive
    align = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    for i in range(combo.count()):
        combo.setItemData(i, align, Qt.ItemDataRole.TextAlignmentRole)
    return combo


def section(window, parent_lay, title, title_style, frame_style):
    """Ex-Main_Menu._section. Phase 5: delegates to FieldFactory.

    The ``window`` argument is unused — kept for backward compatibility
    with every existing call site in ``build_page_*``. Returns
    ``(grid_layout, container_widget)``.
    """
    from .field_factory import default_factory
    return default_factory().section(parent_lay, title,
                                       title_style, frame_style)


def collapsible_section(window, parent_lay, title, title_style, frame_style,
                        expanded=False, on_toggle=None):
    """Collapsible variant of :func:`section`.

    Same ``(grid, container)`` return and the same visual card, but the
    title becomes a keyboard-accessible button that shows / hides the body.
    A shared chevron indicates its state. Mirrors the top-level
    accordion in ``ui_builders.build_param_tabs`` but scoped to one in-page
    sub-section, so rarely-touched "advanced" controls collapse out of the
    way by default.

    ``on_toggle(is_open)`` — optional callback fired after state changes
    (not the initial state), allowing mode-dependent visibility to refresh.
    ``window`` is unused — kept
    for call-site symmetry with :func:`section`.
    """
    from .field_factory import default_factory
    grid, container = default_factory().section(parent_lay, title,
                                                 title_style, frame_style)
    clay = container.layout()            # QVBoxLayout: [title, frame]
    title_lbl = clay.takeAt(0).widget()
    title_lbl.deleteLater()
    frame = clay.itemAt(0).widget()
    header = QToolButton(container)
    header.setText((title or "").strip())
    header.setCheckable(True)
    header.setChecked(expanded)
    header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    header.setIconSize(QSize(14, 14))
    header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    _ht = get_theme()
    header.setStyleSheet(
        f"QToolButton{{color:{_ht['sub_fg']}; font-size:10pt; font-weight:600;"
        f" background:{_ht.get('surface_elevated', _ht['card_bg'])};"
        f" border:1px solid {_ht['card_border']}; border-radius:{RADIUS_INPUT}px; padding:5px 8px;}}"
        f"QToolButton:hover{{color:{_ht['fg']}; border-color:{_ht['inp_focus']};}}"
        f"QToolButton:focus{{border:2px solid {_ht['inp_focus']}; padding:4px 7px;}}")
    clay.insertWidget(0, header)

    def _apply(exp):
        frame.setVisible(exp)
        header.setIcon(icon('chevron-down' if exp else 'chevron-right', _ht['sub_fg']))

    def _toggle(exp):
        _apply(exp)
        if on_toggle is not None:
            on_toggle(exp)

    _apply(expanded)
    header.toggled.connect(_toggle)
    # Programmatic expand/collapse hook (ui-ia-batch1): lets callers open a
    # collapsed section when its content becomes relevant (e.g. fluid
    # auto-fill opens the property details).
    container._set_expanded = header.setChecked
    return grid, container


def row(window, g, row_idx, text, default):
    """Ex-Main_Menu._row -> QLineEdit. Phase 5: delegates to FieldFactory.

    Note: parameter `row` renamed to `row_idx` to avoid shadowing the
    function name. ``window`` retained for call-site compatibility.
    """
    from .field_factory import default_factory
    return default_factory().row(g, row_idx, text, default)


def res_row(window, g, row_idx, text, col=0):
    """Label + computed-value row. Phase 5: delegates to FieldFactory."""
    from .field_factory import default_factory
    return default_factory().res_row(g, row_idx, text, col=col)


def add_row(window, g, row_idx, text, widget):
    """Ex-Main_Menu._add_row. Phase 5: delegates to FieldFactory."""
    from .field_factory import default_factory
    return default_factory().add_row(g, row_idx, text, widget)


def _computed_divider(g, row_idx, cols=2):
    """Insert a left-aligned `COMPUTED` caption + thin horizontal rule into
    grid `g` at the given row, spanning `cols` columns.

    Replaces the older `── computed ──` text separator. Visual weight is
    deliberately low — this is a layout hint, not a header.
    """
    t = get_theme()
    sub_fg = t.get('sub_fg', t['fg'])
    card_border = t.get('card_border', '#334155')

    holder = QWidget()
    holder.setStyleSheet("background:transparent;")
    h = QHBoxLayout(holder)
    h.setContentsMargins(0, 6, 0, 2)
    h.setSpacing(8)

    cap = QLabel("COMPUTED")
    cap.setStyleSheet(
        f"color:{sub_fg}; font-size:8pt; font-weight:600; letter-spacing:1.2px;"
        "background:transparent; border:none; padding:0;")
    cap.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    h.addWidget(cap, 0)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(
        f"background:{card_border}; border:none; color:{card_border};")
    h.addWidget(line, 1)

    g.addWidget(holder, row_idx, 0, 1, cols)


class _ResultLabel(QLabel):
    """QLabel that flips its dynamic `valState` property between `empty`
    ("—", muted italic) and `filled` (bold accent) as its text changes.

    A single `_VAL` stylesheet hosts both `QLabel[valState="empty"]` and
    `QLabel[valState="filled"]` selectors; Qt repolishes after each property
    change so call-sites that do `label.setText(...)` see the right look
    without touching styles themselves.

    Right-click pops a small menu with "Copy value" / "Copy with units";
    the unit string is parsed once from the row label at creation time.
    """
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
    """Extract the unit string inside the last bracket pair of a row label.
    Accepts HTML; strips tags and common entities first. Returns ("K", "T_out")
    for "<i>T</i><sub>out</sub> [K]" etc. Empty unit_hint → no unit token.
    """
    import re as _re_u
    plain = _re_u.sub(r"<[^>]+>", "", text or "")
    for ent, ch in _ENTITY_MAP.items():
        plain = plain.replace(ent, ch)
    plain = plain.strip()
    m = _re_u.search(r"\[([^\[\]]+)\]\s*$", plain)
    unit = m.group(1).strip() if m else ""
    name = (plain[:m.start()] if m else plain).strip().rstrip(",:")
    return unit, name
