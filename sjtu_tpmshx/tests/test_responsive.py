"""Responsive groups obey the active Qt platform's minimum-size hints."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QComboBox, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
)

from sjtu_tpmshx.ui.responsive import ResponsiveRow


def _settle_layout():
    for _ in range(3):
        QApplication.processEvents()


def _close(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('widget_groups', [False, True])
def test_native_group_minimums_allow_wide_to_narrow_resize(widget_groups):
    """Both layout and widget callers must wrap without enlarging the host."""
    host = QWidget()
    outer = QVBoxLayout(host)
    outer.setContentsMargins(7, 9, 11, 13)
    row = ResponsiveRow(threshold=1, spacing=7)
    row.layout().setContentsMargins(9, 3, 13, 5)
    outer.addWidget(row)
    controls = []
    for text in ('Load current configuration', 'Save current configuration'):
        group = QWidget() if widget_groups else None
        layout = QHBoxLayout(group) if group is not None else QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label, button = QLabel('File:'), QPushButton(text)
        layout.addWidget(label)
        layout.addWidget(button)
        if group is not None:
            row.addWidget(group)
        else:
            row.layout().addLayout(layout)
        controls.extend((label, button))
    host.ensurePolished()
    widths = [row.layout().itemAt(i).minimumSize().width() for i in range(2)]
    horizontal_margins = 7 + 11 + 9 + 13
    narrow = max(widths) + horizontal_margins
    wide = sum(widths) + row.layout().spacing() + horizontal_margins + 23
    try:
        host.resize(wide, 200)
        host.show()
        for width, direction in (
                (wide, QBoxLayout.Direction.LeftToRight),
                (narrow, QBoxLayout.Direction.TopToBottom),
                (wide, QBoxLayout.Direction.LeftToRight),
                (narrow, QBoxLayout.Direction.TopToBottom)):
            host.resize(width, 200)
            _settle_layout()
            assert host.width() == width
            assert row.direction == direction
            for control in controls:
                rect = control.rect().translated(control.mapTo(host, QPoint()))
                assert host.rect().contains(rect)
                assert control.width() >= control.minimumSizeHint().width()
    finally:
        _close(host)


def test_native_text_minimum_change_reflows_without_resizing_host():
    host = QWidget()
    outer = QVBoxLayout(host)
    outer.setContentsMargins(7, 9, 11, 13)
    row = ResponsiveRow(threshold=1, spacing=7)
    outer.addWidget(row)
    first, second = QPushButton('Load'), QPushButton('Save')
    row.addWidget(first)
    row.addWidget(second)
    long_text = 'Save current configuration and application settings'
    second.setText(long_text)
    host.ensurePolished()
    available = second.minimumSizeHint().width()
    second.setText('Save')
    assert available > (first.minimumSizeHint().width()
                        + second.minimumSizeHint().width() + row.layout().spacing())
    width = available + 7 + 11
    try:
        host.resize(width, 200)
        host.show()
        _settle_layout()
        assert row.direction == QBoxLayout.Direction.LeftToRight
        second.setText(long_text)
        _settle_layout()
        assert host.width() == width
        assert row.direction == QBoxLayout.Direction.TopToBottom
        assert second.width() >= second.minimumSizeHint().width()
        second.setText('Save')
        _settle_layout()
        assert host.width() == width
        assert row.direction == QBoxLayout.Direction.LeftToRight
    finally:
        _close(host)


@pytest.mark.parametrize('group_kind', ['layout', 'widget', 'responsive'])
def test_content_minimum_hint_survives_smaller_explicit_minimum(group_kind):
    """Qt's item minimum can be smaller than the native content minimum."""
    host = QWidget()
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    row = ResponsiveRow(threshold=1, spacing=7)
    outer.addWidget(row)
    combo = QComboBox()
    combo.addItem('Temperature A reference field at the selected slice')
    combo.setMinimumWidth(140)
    label = QLabel('Z coordinate range (0–182.0 mm), choose the slice position')
    label.setMinimumWidth(260)
    controls = (combo, label)
    for control in controls:
        group = QHBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.addWidget(control)
        if group_kind == 'layout':
            row.layout().addLayout(group)
        elif group_kind == 'widget':
            wrapper = QWidget()
            vertical = QVBoxLayout(wrapper)
            vertical.setContentsMargins(0, 0, 0, 0)
            vertical.addLayout(group)
            row.addWidget(wrapper)
        else:
            wrapper = ResponsiveRow(threshold=1)
            wrapper.layout().addLayout(group)
            row.addWidget(wrapper)
    host.ensurePolished()
    hints = [control.minimumSizeHint().width() for control in controls]
    assert hints[0] > 140 and hints[1] > 260
    # Fits either complete group but cannot fit both native content hints.
    width = max(hints) + min(hints) // 2
    assert width > 140 + 260 + row.layout().spacing()
    try:
        host.resize(width, 200)
        host.show()
        _settle_layout()
        assert host.width() == width
        assert row.direction == QBoxLayout.Direction.TopToBottom
        for control in controls:
            assert control.width() >= control.minimumSizeHint().width()
            rect = control.rect().translated(control.mapTo(host, QPoint()))
            assert host.rect().contains(rect)
    finally:
        _close(host)


def test_content_minimum_respects_hidden_ignored_fixed_and_spacer_items():
    row = ResponsiveRow(threshold=1, spacing=7)
    row.addWidget(QLabel('Field'))
    ignored = QLabel('The ignored label does not constrain horizontal layout')
    ignored.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    row.addWidget(ignored)
    hidden = QLabel('A hidden control must not require width for its content')
    row.addWidget(hidden)
    hidden.hide()
    fixed = QLabel('A fixed control still respects its explicit maximum width')
    fixed.setFixedWidth(31)
    row.addWidget(fixed)
    row.layout().addSpacerItem(QSpacerItem(
        2000, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
    try:
        row.resize(200, 100)
        row.show()
        _settle_layout()
        assert row.width() == 200
        assert row.direction == QBoxLayout.Direction.LeftToRight
        assert row.minimumSizeHint().width() <= 200
        assert hidden.isHidden()
        assert fixed.width() == 31
    finally:
        _close(row)
