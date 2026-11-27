"""Native resource controls preserve inputs and reach each desktop worker."""
from dataclasses import asdict, replace
import threading
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.run_control.cancellation import CancelledError
from tests.python.gui_workbench_support import win as win, _result
from tests.python.gui_worker_support import _wait_for
from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window


def test_cpu_budget_updates_consumers_without_changing_case_or_result(win, tmp_path):
    library = tmp_path / 'solver-library'
    win.run_control = replace(win.run_control, native_library=str(library),
                              native_table_directory=str(tmp_path / 'tables'))
    win.workbench.show_quick_design()
    win.results.publish(_result('2d'))
    accepted = win.cache.get_result('2d')
    config = asdict(config_from_window(win))
    for count in (1, 0, 1):
        win.spin_cpu_cores.setValue(count)
        assert win.run_control.backend == 'cpp'
        assert win.run_control.cpu_threads == (count or None)
        assert win.run_control.native_library == str(library)
        assert win.cache.get_result('2d') is accepted
        assert asdict(config_from_window(win)) == config


@pytest.mark.parametrize('kind', ['compute', 'optimize', 'quick_design'])
def test_native_control_reaches_workers_and_stays_locked_through_cancel(
        win, tmp_path, monkeypatch, kind):
    from sjtu_tpmshx.applications.gui.ui import optimize_panel, single_run
    from sjtu_tpmshx.applications.gui.ui.background_tasks import has_active_tasks

    library = tmp_path / 'solver-library'
    library.touch()
    win.run_control = replace(win.run_control, native_library=str(library))
    win.workbench.show_quick_design()
    win.spin_cpu_cores.setValue(1)
    entered, release = threading.Event(), threading.Event()
    controls = []

    def held(*args, control, **kwargs):
        controls.append(control)
        entered.set()
        assert release.wait(10)
        raise CancelledError('test cancelled')

    if kind == 'compute':
        monkeypatch.setattr(win.single_run, 'preflight_grid', lambda config: True)
        monkeypatch.setattr(single_run, '_run_compute', held)
        win.single_run.submit()
        cancel = win.single_run.compute.cancel
    elif kind == 'optimize':
        monkeypatch.setattr(
            'sjtu_tpmshx.applications.optimization.multi_condition_optimizer.run_multi_condition_optimization', held)
        monkeypatch.setattr(optimize_panel, 'optimization_output_dir', lambda: tmp_path)
        win.combo_dim.setCurrentIndex(0)
        win.optimization.conditions = [dict(condition_id='selector', T_in_A_K=400., P_in_A_Pa=130000.,
            mass_flow_A_kg_s=.003, T_in_B_K=295., P_in_B_Pa=120000., mass_flow_B_kg_s=.015)]
        win.optimization.start()
        cancel = win.optimization.cancel
    else:
        monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda _: [SimpleNamespace(case='A', dPlim_h=.05, dPlim_c=.06)])
        monkeypatch.setattr('sjtu_tpmshx.applications.design.sizing.size_fixed_cell', held)
        page = win.quick_design
        page.le_qd_file.setText('not-read.xlsx')
        page.mode_selector.set_value('fixed')
        page.submit()
        cancel = page.cancel
    try:
        assert entered.wait(5)
        assert controls[0].backend == 'cpp' and controls[0].native_library == str(library)
        assert controls[0].cpu_threads == win.run_control.cpu_threads == 1
        assert not win.spin_cpu_cores.isEnabled()
        assert has_active_tasks(win)
        win.spin_cpu_cores.setValue(0)
        assert win.run_control.cpu_threads == win.spin_cpu_cores.value() == 1
        cancel()
        assert win.run_control.backend == 'cpp'
        assert not win.spin_cpu_cores.isEnabled()
    finally:
        release.set()
        _wait_for(lambda: not has_active_tasks(win))
    _wait_for(win.spin_cpu_cores.isEnabled)
    assert controls[0].cpu_threads == 1
