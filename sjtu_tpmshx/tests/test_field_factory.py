"""Unit tests for ui.field_factory.FieldFactory.

Phase 5 of 2026-05-06 main.py refactor (audit fix #4). Tests are Qt-aware
(they instantiate widgets) but use the offscreen platform; no live
window or theme switch.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLineEdit, QLabel, QVBoxLayout, QWidget,
    QComboBox,
)

from sjtu_tpmshx.ui.theme_manager import ThemeManager
from sjtu_tpmshx.ui.field_factory import (
    FieldFactory, default_factory, set_default_factory,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def factory():
    _app()
    return FieldFactory(ThemeManager())


@pytest.fixture(autouse=True)
def _reset_default_factory():
    """Each test starts with no installed default factory."""
    set_default_factory(None)
    yield
    set_default_factory(None)


# ---------------------------------------------------------------- atoms


@pytest.mark.parametrize('theme_name', ['light', 'dark'])
@pytest.mark.parametrize('editable', [False, True])
def test_combo_hover_and_focus_preserve_text_and_arrow_positions(theme_name, editable):
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox
    from sjtu_tpmshx.ui.theme import _build_styles

    app = _app()
    combo = QComboBox()
    combo.addItems(['Gyroid', 'Diamond'])
    combo.setEditable(editable)
    if editable:
        combo.lineEdit().setReadOnly(True)
    combo.setStyleSheet(_build_styles(theme_name)['COMBO'])
    combo.resize(160, 32)
    combo.show()
    app.processEvents()
    regions = []
    for state in (QStyle.StateFlag.State_None, QStyle.StateFlag.State_MouseOver,
                  QStyle.StateFlag.State_HasFocus):
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        option.state = QStyle.StateFlag.State_Enabled | state
        regions.append(tuple(combo.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, control, combo)
            for control in (QStyle.SubControl.SC_ComboBoxEditField,
                            QStyle.SubControl.SC_ComboBoxArrow)))
    combo.close()
    combo.deleteLater()
    assert regions[0] == regions[1] == regions[2]


@pytest.mark.parametrize('theme_name', ['light', 'dark'])
@pytest.mark.parametrize('enabled', [True, False])
def test_combo_arrow_has_visible_pixels_in_both_themes(theme_name, enabled):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox
    from sjtu_tpmshx.ui.theme import _build_styles

    combo = QComboBox()
    combo.addItem('')  # Isolate the arrow from the text and control outline.
    combo.setStyleSheet(_build_styles(theme_name)['COMBO'])
    combo.setEnabled(enabled)
    combo.resize(160, 34)
    combo.show()
    QApplication.processEvents()
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    arrow = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option,
        QStyle.SubControl.SC_ComboBoxArrow, combo)
    target = QRect(0, 0, 12, 12)
    target.moveCenter(arrow.center())
    pixmap = combo.grab()
    image = pixmap.toImage()
    scale = pixmap.devicePixelRatio()
    background = image.pixelColor(round(arrow.center().x() * scale), round((arrow.top() + 3) * scale))
    visible = []
    for y in range(round(target.top() * scale), round((target.bottom() + 1) * scale)):
        for x in range(round(target.left() * scale), round((target.right() + 1) * scale)):
            pixel = image.pixelColor(x, y)
            if max(abs(pixel.red() - background.red()),
                   abs(pixel.green() - background.green()),
                   abs(pixel.blue() - background.blue())) > 35:
                visible.append((x, y))
    combo.close()
    combo.deleteLater()
    assert len(visible) >= 4, 'The styled combo lost its dropdown chevron'


@pytest.mark.parametrize('theme_name', ['light', 'dark'])
def test_scrollbar_theme_has_no_native_arrow_boxes_or_white_outline(theme_name):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QScrollArea, QStyle, QStyleOptionSlider
    from sjtu_tpmshx.ui.theme import _build_styles, _THEMES

    area = QScrollArea()
    area.setStyleSheet(_build_styles(theme_name)['SCROLLBAR'])
    content = QWidget()
    content.setFixedSize(80, 600)
    area.setWidget(content)
    area.resize(180, 180)
    area.show()
    QApplication.processEvents()
    bar = area.verticalScrollBar()
    assert bar.isVisible()
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    for control in (QStyle.SubControl.SC_ScrollBarAddLine, QStyle.SubControl.SC_ScrollBarSubLine):
        assert bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option, control, bar).isEmpty()
    image = bar.grab().toImage()
    background = QColor(_THEMES[theme_name]['scroll_bg'])
    for x in (0, image.width() - 1):
        for y in (0, image.height() // 2, image.height() - 1):
            assert image.pixelColor(x, y) == background
    area.close()
    area.deleteLater()


def test_label_returns_qlabel_with_text(factory):
    lbl = factory.label('hello')
    assert isinstance(lbl, QLabel)
    assert lbl.text() == 'hello'
    assert lbl.textFormat() == Qt.TextFormat.RichText


def test_label_plain_mode():
    _app()
    f = FieldFactory(ThemeManager())
    lbl = f.label('<b>raw</b>', rich=False)
    assert lbl.textFormat() != Qt.TextFormat.RichText


def test_line_edit_default_text(factory):
    le = factory.line_edit('0.080')
    assert isinstance(le, QLineEdit)
    assert le.text() == '0.080'


def test_line_edit_tooltip_and_placeholder(factory):
    le = factory.line_edit('', tooltip='hint', placeholder='ph')
    assert le.toolTip() == 'hint'
    assert le.placeholderText() == 'ph'


def test_result_label_starts_empty(factory):
    val = factory.result_label(unit_hint='K', quantity_name='T_in')
    assert val.text() == '—'
    assert val.property('valState') == 'empty'


def test_result_label_set_text_flips_to_filled(factory):
    val = factory.result_label(unit_hint='K')
    val.setText('298.15')
    assert val.property('valState') == 'filled'


# ---------------------------------------------------------------- rows


def test_row_adds_two_cells(factory):
    host = QWidget()
    g = QGridLayout(host)
    le = factory.row(g, 0, 'L [m]', '0.080')
    assert isinstance(le, QLineEdit)
    assert le.text() == '0.080'
    assert g.itemAtPosition(0, 0) is not None
    assert g.itemAtPosition(0, 1) is not None
    # Label cell holds a QLabel
    assert isinstance(g.itemAtPosition(0, 0).widget(), QLabel)


def test_res_row_parses_unit_hint(factory):
    host = QWidget()
    g = QGridLayout(host)
    val = factory.res_row(g, 0, 'T<sub>in</sub> [K]')
    assert val.property('valState') == 'empty'
    # _ResultLabel records the unit hint
    assert val._unit_hint == 'K'


def test_add_row_returns_passed_widget(factory):
    host = QWidget()
    g = QGridLayout(host)
    combo = QComboBox()
    out = factory.add_row(g, 0, 'TPMS', combo)
    assert out is combo
    assert g.itemAtPosition(0, 1).widget() is combo


# ---------------------------------------------------------------- section


def test_section_returns_grid_and_container(factory):
    host = QWidget()
    parent_lay = QVBoxLayout(host)
    g, container = factory.section(parent_lay, 'Geometry',
                                     'color:white;', 'background:#222;')
    assert isinstance(g, QGridLayout)
    assert isinstance(container, QWidget)
    # Section title margins/spacing match legacy contract
    m = g.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (12, 10, 12, 10)
    assert g.verticalSpacing() == 8
    assert g.horizontalSpacing() == 10


# ---------------------------------------------------------------- singleton


def test_default_factory_lazy_creates():
    _app()
    set_default_factory(None)
    f = default_factory()
    assert isinstance(f, FieldFactory)
    # Same instance returned next call
    assert default_factory() is f


def test_set_default_factory_overrides():
    _app()
    custom = FieldFactory(ThemeManager())
    set_default_factory(custom)
    assert default_factory() is custom


# ---------------------------------------------------------------- repr


def test_repr_safe(factory):
    s = repr(factory)
    assert 'FieldFactory' in s
