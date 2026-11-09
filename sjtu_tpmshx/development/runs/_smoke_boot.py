"""Select the offscreen platform before importing Qt for GUI smoke tools.

Importing this helper neither creates an application nor patches dialogs.
Call get_app/patch_modals explicitly; smoke_ui_offscreen._smoke_window owns
the isolated user state and window lifetime. Run modules from the repo root.
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def get_app():
    """The shared offscreen QApplication (created on first call)."""
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def patch_modals():
    """Auto-accept pipeline smoke dialogs, including instance exec calls."""
    from PySide6.QtWidgets import QMessageBox

    def _auto(*a, **k):
        print('  [dialog auto-Yes]', flush=True)
        return QMessageBox.StandardButton.Yes
    QMessageBox.question = staticmethod(_auto)
    QMessageBox.warning = staticmethod(_auto)
    QMessageBox.information = staticmethod(_auto)
    QMessageBox.exec = lambda self: (print('  [instance modal auto-Yes]',
                                           flush=True)
                                     or QMessageBox.StandardButton.Yes)
