"""Qt worker for one optimization study."""
from copy import deepcopy
from dataclasses import replace
from threading import Event
from time import monotonic
from traceback import format_exception_only

from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot

from sjtu_tpmshx.applications.gui.controllers import main_thread_gc


class OptimizationJob(QThread):
    progress = Signal(int)
    updated = Signal(object)
    settled = Signal()
    _terminal = Signal(object, str)

    def __init__(self, inputs, output_dir, control, on_terminal, parent=None):
        super().__init__(parent)
        self.inputs = deepcopy(inputs)
        self.output_dir = output_dir
        self._control = control
        self._on_terminal = on_terminal
        self._pause = Event()
        self._delivered = False
        self._terminal.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self.finished.connect(self._release, Qt.ConnectionType.QueuedConnection)

    def start(self, priority=QThread.Priority.InheritPriority):
        main_thread_gc.acquire()
        super().start(priority)

    def request_pause(self):
        self._pause.set()

    def run(self):
        last_percent, last_emit = -1, -float('inf')

        def progress(percent):
            nonlocal last_percent, last_emit
            now = monotonic()
            if percent != last_percent and (now - last_emit >= 0.1 or percent == 100):
                self.progress.emit(percent)
                last_percent, last_emit = percent, now
            self._control.report_progress(percent)

        def cancelled():
            return self.isInterruptionRequested() or (
                self._control.cancel_check is not None and self._control.cancel_check())

        control = replace(self._control, progress=progress, cancel_check=cancelled)
        try:
            report = self.inputs.run(self.output_dir, control, self.updated.emit, self._pause.is_set)
        except Exception as exc:
            self._terminal.emit(None, ''.join(format_exception_only(exc)).strip())
        else:
            self._terminal.emit(report, '')

    @Slot(object, str)
    def _deliver(self, report, error):
        try:
            self._on_terminal(report, error)
        finally:
            self._delivered = True

    @Slot()
    def _release(self):
        # The terminal event and the thread's actual exit can arrive in either order.
        if not self._delivered or not self.wait(0):
            QTimer.singleShot(10, self, self._release)
            return
        main_thread_gc.release()
        self.settled.emit()
        self.deleteLater()
