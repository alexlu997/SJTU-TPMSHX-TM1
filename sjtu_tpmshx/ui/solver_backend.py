"""Window-local backend selection, shared by compute and design launches."""
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
import sys

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.domain.provenance import SOURCE_ROOT
from sjtu_tpmshx.io.cli_options import run_control_from_args
from sjtu_tpmshx.ui.background_tasks import has_active_tasks


def _cpp_control(control):
    if control.native_library is None:
        defaults = run_control_from_args(Namespace(
            backend='cpp', native_library=None, native_table_directory=None))
        if defaults.native_library is None:
            if sys.platform != 'darwin':
                raise ValueError('尚未配置本机 C++ 求解器库，请使用带匹配原生库的启动入口。')
            defaults = replace(defaults,
                native_library=str(SOURCE_ROOT / 'native/lib/macos-arm64/libtpmshx_solver_shared.dylib'),
                native_table_directory=str(SOURCE_ROOT / '.cache/native-deps/tables'))
        control = replace(control, native_library=defaults.native_library,
            native_table_directory=control.native_table_directory or defaults.native_table_directory)
    if not Path(control.native_library).is_file():
        raise ValueError(f'未找到 C++ 求解器库：\n{control.native_library}\n请恢复匹配的库后重试。')
    return control


def _configure_threads(window):
    spin = window.spin_cpu_cores
    with QSignalBlocker(spin):
        if window.run_control.backend == 'cpp':
            spin.setRange(0, 0)
            spin.setSpecialValueText('自动')
            tip = 'C++ 求解器采用固定并行策略，此控件不适用。'
        else:
            from sjtu_tpmshx.solvers.threads import max_threads, get_solver_threads
            spin.setSpecialValueText('')
            spin.setRange(1, max_threads())
            spin.setValue(get_solver_threads())
            tip = (f'设置下一次普通计算使用的 Numba 并行核线程数（1–{max_threads()}），'
                   '小网格可能使用串行核。\n它不限制整个应用的 CPU 占用，也不控制优化任务数量。')
    spin.setToolTip(tip)
    window._cpu_card.setToolTip(tip)


def refresh_backend_availability(window):
    if getattr(window, 'combo_solver_backend', None) is None:
        return
    busy = has_active_tasks(window) or getattr(window, '_opt_launching', False)
    window.combo_solver_backend.setEnabled(not busy)
    window._cpu_card.setEnabled(not busy and window.run_control.backend == 'python')
    if busy:
        # Terminal publication can precede the worker's actual return.
        window._backend_refresh_timer.start()
    else:
        window._backend_refresh_timer.stop()


def _select_backend(window):
    combo = window.combo_solver_backend
    backend = combo.currentData()
    if backend == window.run_control.backend:
        return
    error = None
    busy = has_active_tasks(window) or getattr(window, '_opt_launching', False)
    if not busy:
        control = replace(window.run_control, backend=backend)
        try:
            if backend == 'cpp':
                control = _cpp_control(control)
        except ValueError as exc:
            error = str(exc)
        else:
            window.run_control = control
            window.compute.backend = backend
            dialog = getattr(window, '_qd_dialog', None)
            if dialog is not None:
                dialog.run_control = control
            _configure_threads(window)
    with QSignalBlocker(combo):
        combo.setCurrentIndex(combo.findData(window.run_control.backend))
    refresh_backend_availability(window)
    if error:
        QMessageBox.warning(window, '无法切换求解器', error)


def bind_backend_controls(window):
    window.combo_solver_backend.setCurrentIndex(
        window.combo_solver_backend.findData(window.run_control.backend))
    _configure_threads(window)
    window._backend_refresh_timer = QTimer(window)
    window._backend_refresh_timer.setInterval(100)
    window._backend_refresh_timer.setSingleShot(True)
    window._backend_refresh_timer.timeout.connect(lambda: refresh_backend_availability(window))
    window.compute.started.connect(lambda _: refresh_backend_availability(window))
    window.combo_solver_backend.currentIndexChanged.connect(lambda _: _select_backend(window))

    def set_threads(count):
        if window.run_control.backend == 'python':
            from sjtu_tpmshx.solvers.threads import set_solver_threads
            set_solver_threads(count)

    window.spin_cpu_cores.valueChanged.connect(set_threads)
    refresh_backend_availability(window)
