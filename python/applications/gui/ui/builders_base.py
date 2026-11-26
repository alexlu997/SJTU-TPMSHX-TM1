"""Shared menu controls and collapsible sections for page builders."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QToolButton, QSizePolicy

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


def collapsible_section(parent_lay, title, title_style, frame_style,
                        expanded=False, on_toggle=None):
    """Collapsible variant of ``FieldFactory.section``.

    Same ``(grid, container)`` return and the same visual card, but the
    title becomes a keyboard-accessible button that shows / hides the body.
    A shared chevron indicates its state. Mirrors the top-level
    accordion in ``ui_builders.build_param_tabs`` but scoped to one in-page
    sub-section, so rarely-touched "advanced" controls collapse out of the
    way by default.

    ``on_toggle(is_open)`` — optional callback fired after state changes
    (not the initial state), allowing mode-dependent visibility to refresh.
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
