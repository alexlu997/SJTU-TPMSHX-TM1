"""Desktop task lifetime and background imports for the 3D views."""
from __future__ import annotations

from importlib import import_module

from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot

from sjtu_tpmshx.applications.gui.controllers import main_thread_gc


class ViewImports(QThread):
    prepared = Signal()
    settled = Signal()

    def __init__(self, workbench):
        super().__init__(workbench.window)
        self.workbench = workbench
        self.error = None
        self.finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def start(self, priority=QThread.Priority.InheritPriority):
        main_thread_gc.acquire()
        super().start(priority)

    def run(self):
        try:
            import_module('sjtu_tpmshx.applications.gui.ui.panel_vis_3d')
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'

    @Slot()
    def _deliver(self):
        if not self.wait(0):
            QTimer.singleShot(10, self, self._deliver)
            return
        workbench = self.workbench
        workbench.imports_ready = True
        if self.error is not None:
            workbench.import_error = self.error
        try:
            self.prepared.emit()
        finally:
            workbench.import_worker = None
            main_thread_gc.release()
            self.settled.emit()
            self.deleteLater()


def has_active_tasks(window) -> bool:
    return not all(owner.is_idle() for owner in (
        window.single_run, window.optimization, window.quick_design, window.workbench))
