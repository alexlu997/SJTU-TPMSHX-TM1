"""Keep cyclic garbage collection on the Qt main thread during worker runs.

Workaround for a PySide6/Shiboken6 6.12.0 defect: worker-thread cyclic GC can
finalize main-thread wrappers and queue BindingManager::deleteInMainThread
entries that cause a use-after-free in mainThreadDeletionHandler. Remove this
guard when an upstream PySide6/Shiboken6 fix is available.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QCoreApplication, QTimer

_INTERVAL_MS = 5000
_active = 0
_timer: QTimer | None = None


def acquire() -> None:
    """Disable automatic cyclic GC on the first active worker and poll on the main thread."""
    global _active, _timer
    if _active == 0:
        gc.collect()
        gc.disable()
        timer = QTimer(QCoreApplication.instance())
        timer.setInterval(_INTERVAL_MS)
        timer.timeout.connect(gc.collect)
        timer.start()
        _timer = timer
    _active += 1


def release() -> None:
    """Stop the main-thread timer and re-enable automatic cyclic GC on the last worker."""
    global _active, _timer
    if _active == 0:
        raise RuntimeError('main_thread_gc.release() called without matching acquire()')
    _active -= 1
    if _active == 0:
        timer = _timer
        _timer = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        gc.collect()
        gc.enable()
