"""Responsive groups obey the active Qt platform's minimum-size hints."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
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
