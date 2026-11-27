"""Select the offscreen platform before importing Qt for GUI smoke tools.

Importing this helper does not create an application. Call get_app explicitly;
smoke_ui_offscreen._smoke_window owns the isolated user state and window
lifetime. Run modules from the repo root.
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def get_app():
    """The shared offscreen QApplication (created on first call)."""
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.applications.gui.controllers import main_thread_gc
    app = QApplication.instance() or QApplication(sys.argv)
    main_thread_gc.install(app)
    return app
