"""Desktop task lifetime, including queued results and 3D imports."""
from __future__ import annotations

from importlib import import_module

from PySide6.QtCore import QThread, Qt, Signal, Slot


class _ViewImports(QThread):
    prepared = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.error = None
        self.finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def run(self):
        try:
            import_module('sjtu_tpmshx.ui.panel_vis_3d')
            import_module('scipy.interpolate')
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'

    @Slot()
    def _deliver(self):
        window = self.parent()
        window._view_imports_ready = True
        if self.error is not None:
            window._vis3d_import_error = self.error
        try:
            self.prepared.emit()
        finally:
            window._view_import_worker = None
            self.deleteLater()


def prepare_3d(window, callback):
    """Prepare imports, then call back on the GUI thread."""
    if (getattr(window, '_vis3d_import_error', None)
            or getattr(window, '_view_imports_ready', False)):
        callback()
        return
    worker = getattr(window, '_view_import_worker', None)
    first = worker is None
    if first:
        worker = _ViewImports(window)
        window._view_import_worker = worker
    worker.prepared.connect(callback)
    if first:
        refresh_resource_availability(window)
        worker.start()


def has_active_tasks(window) -> bool:
    compute = getattr(window, 'compute', None)
    return bool(
        (compute is not None and not compute.is_idle())
        or getattr(window, '_view_import_worker', None) is not None
        or getattr(window, '_opt_worker', None) is not None
        or getattr(getattr(window, '_qd_dialog', None), '_qd_worker', None) is not None
    )


def refresh_resource_availability(window):
    if getattr(window, '_cpu_card', None) is None:
        return
    busy = has_active_tasks(window) or getattr(window, '_opt_launching', False)
    window._cpu_card.setEnabled(not busy)
    if busy:
        # Terminal publication can precede the worker's actual return.
        window._resource_refresh_timer.start()
    else:
        window._resource_refresh_timer.stop()
