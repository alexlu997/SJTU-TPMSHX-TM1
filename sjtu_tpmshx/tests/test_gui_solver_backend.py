"""Backend selection preserves case/results and reaches every desktop worker."""
from dataclasses import asdict, replace
import threading

import pytest
from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.tests.gui_workbench_support import win as win, _result
from sjtu_tpmshx.tests.gui_worker_support import _wait_for
from sjtu_tpmshx.tests.test_main_smoke import solver_threads as solver_threads
from sjtu_tpmshx.ui.window_config import config_from_window


def test_selection_updates_consumers_without_changing_case_or_result(win, tmp_path, solver_threads):
    library = tmp_path / 'solver-library'
    library.touch()  # Selection checks presence; native ABI is checked by the solver.
    win.run_control = replace(win.run_control, native_library=str(library),
                              native_table_directory=str(tmp_path / 'tables'))
    win._open_quick_design()
    win.write_result(_result('2d'))
    accepted = win.cache.get_result('2d')
    config = asdict(config_from_window(win))
    mask = solver_threads.get_solver_threads()
    win._select_param_page(2)
    assert win.combo_solver_backend.isVisibleTo(win)
    assert win.combo_solver_backend.currentData() == 'python'

    for backend in ('cpp', 'python', 'cpp', 'python'):
        win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData(backend))
        assert win.run_control.backend == win.compute.backend == backend
        assert win.run_control.native_library == str(library)
        assert win.run_control.native_table_directory == str(tmp_path / 'tables')
        assert win._qd_dialog.run_control is win.run_control
        assert win.cache.get_result('2d') is accepted
        assert asdict(config_from_window(win)) == config
        assert win.spin_cpu_cores.isEnabled() == (backend == 'python')
        if backend == 'cpp':
            assert win.spin_cpu_cores.text() == '自动'
        else:
            assert win.spin_cpu_cores.value() == mask
            assert win.spin_cpu_cores.maximum() == solver_threads.max_threads()
    target = 1 if mask > 1 else solver_threads.max_threads()
    win.spin_cpu_cores.setValue(target)
    assert solver_threads.get_solver_threads() == target


def test_missing_explicit_library_keeps_previous_selection(win, tmp_path, monkeypatch):
    win.run_control = replace(win.run_control, native_library=str(tmp_path / 'missing-library'))
    previous = win.run_control
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[2]))
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData('cpp'))
    assert win.run_control is previous
    assert win.combo_solver_backend.currentData() == win.compute.backend == 'python'
    assert win.combo_solver_backend.isEnabled() and win.spin_cpu_cores.isEnabled()
    assert len(messages) == 1 and previous.native_library in messages[0]


def test_python_start_resolves_local_macos_delivery(win, tmp_path, monkeypatch):
    from sjtu_tpmshx.ui import solver_backend
    library = tmp_path / 'native/lib/macos-arm64/libtpmshx_solver_shared.dylib'
    library.parent.mkdir(parents=True)
    library.touch()
    monkeypatch.setattr(solver_backend, 'SOURCE_ROOT', tmp_path)
    monkeypatch.setattr(solver_backend.sys, 'platform', 'darwin')
    monkeypatch.setattr(solver_backend.sys, 'frozen', False, raising=False)
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData('cpp'))
    assert win.run_control.backend == 'cpp'
    assert win.run_control.native_library == str(library)
    assert win.run_control.native_table_directory == str(tmp_path / '.cache/native-deps/tables')


@pytest.mark.parametrize('kind', ['compute', 'optimize', 'quick_design'])
def test_selected_backend_reaches_worker_and_stays_locked_through_cancel(
        win, tmp_path, monkeypatch, kind):
    from sjtu_tpmshx.ui import optimize_panel, quick_design_panel
    from sjtu_tpmshx.ui.background_tasks import has_active_tasks
    from sjtu_tpmshx.ui.mixins import run_controller

    library = tmp_path / 'solver-library'
    library.touch()
    win.run_control = replace(win.run_control, native_library=str(library))
    win._open_quick_design()  # An already-open dialog must follow the new choice.
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData('cpp'))
    entered, release = threading.Event(), threading.Event()
    controls = []

    def held(*args, control, **kwargs):
        controls.append(control)
        entered.set()
        assert release.wait(10)
        raise CancelledError('test cancelled')

    if kind == 'compute':
        monkeypatch.setattr(win, '_preflight_grid', lambda: True)
        monkeypatch.setattr(run_controller, '_run_pipeline', held)
        win.run_calculation()
        cancel = win.compute.cancel
    elif kind == 'optimize':
        monkeypatch.setattr(
            'sjtu_tpmshx.optimization.multi_condition_optimizer.run_multi_condition_optimization', held)
        monkeypatch.setattr(optimize_panel, 'optimization_output_dir', lambda: tmp_path)
        win.combo_dim.setCurrentIndex(0)
        win._opt_conditions = [dict(condition_id='selector', T_in_A_K=400., P_in_A_Pa=130000.,
            mass_flow_A_kg_s=.003, T_in_B_K=295., P_in_B_Pa=120000., mass_flow_B_kg_s=.015)]
        optimize_panel.run_optimize(win)
        cancel = lambda: optimize_panel.cancel_optimize(win)
    else:
        monkeypatch.setattr('sjtu_tpmshx.design.cases.load_cases', lambda _: ['case'])
        monkeypatch.setattr('sjtu_tpmshx.design.sizing.size_fixed_cell', held)
        dialog = win._qd_dialog
        dialog.le_qd_file.setText('not-read.xlsx')
        dialog.combo_qd_mode.setCurrentIndex(dialog.combo_qd_mode.findData('fixed'))
        quick_design_panel.run_quick_design(dialog)
        cancel = lambda: quick_design_panel.cancel_quick_design(dialog)
    try:
        assert entered.wait(5)
        assert controls[0].backend == 'cpp' and controls[0].native_library == str(library)
        assert has_active_tasks(win) and not win.combo_solver_backend.isEnabled()
        cancel()
        win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData('python'))
        assert win.combo_solver_backend.currentData() == win.compute.backend == 'cpp'
        assert win.run_control.backend == win._qd_dialog.run_control.backend == 'cpp'
        assert not win.combo_solver_backend.isEnabled()
    finally:
        release.set()
        _wait_for(lambda: not has_active_tasks(win))
    _wait_for(win.combo_solver_backend.isEnabled)
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData('python'))
    assert win.run_control.backend == win.compute.backend == 'python'
