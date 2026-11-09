"""Custom Qt item delegates for table editing."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStyledItemDelegate


class SelectAllDelegate(QStyledItemDelegate):
    """When editing starts on a QTableWidget cell, auto-select all text so
    the user can type to replace rather than appending to the existing
    value.
    """

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if hasattr(editor, 'selectAll'):
            # 2026-05-20 UI sweep: the editor widget can be destroyed
            # between this createEditor call and the next event loop
            # tick (rapid focus changes during rebuild), in which case
            # the bound `editor.selectAll` would dereference a deleted
            # C++ object and crash. Guard with a try/except inside a
            # closure rather than passing the bound method directly.
            def _select_all_safe(_e=editor):
                try:
                    _e.selectAll()
                except (RuntimeError, AttributeError):
                    pass
            QTimer.singleShot(0, _select_all_safe)
        return editor
