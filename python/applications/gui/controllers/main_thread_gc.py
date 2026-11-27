"""Keep cyclic garbage collection on the Qt main thread for the GUI process.

Workaround for a PySide6/Shiboken6 6.12.0 defect: worker-thread cyclic GC can
finalize main-thread wrappers and queue BindingManager::deleteInMainThread
entries that cause a use-after-free in mainThreadDeletionHandler. Remove this
guard when an upstream PySide6/Shiboken6 fix is available.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QCoreApplication, QTimer

_TICK_MS = 1000
_FULL_EVERY = 30
_timer: QTimer | None = None
_ticks = 0


def _collect() -> None:
    global _ticks
    _ticks += 1
    if _ticks % _FULL_EVERY == 0:
        gc.collect()
    else:
        gc.collect(1)


def install(app: QCoreApplication) -> None:
    """Disable automatic cyclic GC and schedule periodic main-thread collection."""
    global _timer
    if _timer is not None:
        return
    gc.disable()
    timer = QTimer(app)
    timer.setInterval(_TICK_MS)
    timer.timeout.connect(_collect)
    timer.start()
    _timer = timer
