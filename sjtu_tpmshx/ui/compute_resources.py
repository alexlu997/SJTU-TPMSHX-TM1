"""Window-local CPU limits shared by compute and design launches."""
from dataclasses import replace
import os

from PySide6.QtCore import QSignalBlocker, QTimer

from sjtu_tpmshx.ui.background_tasks import has_active_tasks


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


def bind_resource_controls(window):
    spin = window.spin_cpu_cores
    with QSignalBlocker(spin):
        spin.setRange(0, os.cpu_count() or 1)
        spin.setSpecialValueText('自动')
        spin.setValue(window.run_control.cpu_threads or 0)
    tip = '设置下一次计算的总线程上限；自动最多用 8 个可用 CPU。多工况优化会在此预算内分配工作进程。'
    spin.setToolTip(tip)
    window._cpu_card.setToolTip(tip)
    window._resource_refresh_timer = QTimer(window)
    window._resource_refresh_timer.setInterval(100)
    window._resource_refresh_timer.setSingleShot(True)
    window._resource_refresh_timer.timeout.connect(lambda: refresh_resource_availability(window))
    window.compute.started.connect(lambda _: refresh_resource_availability(window))

    def set_threads(count):
        window.run_control = replace(window.run_control, cpu_threads=count or None)
        dialog = getattr(window, '_qd_dialog', None)
        if dialog is not None:
            dialog.run_control = window.run_control

    spin.valueChanged.connect(set_threads)
    refresh_resource_availability(window)
