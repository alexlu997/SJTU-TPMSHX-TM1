"""Window-local CPU limits shared by compute and design launches."""
from dataclasses import replace
import os

from PySide6.QtCore import QSignalBlocker

from sjtu_tpmshx.applications.gui.ui.background_tasks import has_active_tasks


def refresh_resource_availability(window):
    window._cpu_card.setEnabled(not has_active_tasks(window))


def bind_resource_controls(window):
    spin = window.spin_cpu_cores
    with QSignalBlocker(spin):
        spin.setRange(0, os.cpu_count() or 1)
        spin.setSpecialValueText('自动')
        spin.setValue(window.run_control.cpu_threads or 0)
    tip = '设置下一次计算的总线程上限；自动最多用 8 个可用 CPU。多工况优化会在此预算内分配工作进程。'
    spin.setToolTip(tip)
    window._cpu_card.setToolTip(tip)
    for page in (window.single_run, window.optimization, window.quick_design):
        page.activity_changed.connect(lambda: refresh_resource_availability(window))

    def set_threads(count):
        if has_active_tasks(window):
            with QSignalBlocker(spin):
                spin.setValue(window.run_control.cpu_threads or 0)
            return
        window.run_control = replace(window.run_control, cpu_threads=count or None)

    spin.valueChanged.connect(set_threads)
    refresh_resource_availability(window)
