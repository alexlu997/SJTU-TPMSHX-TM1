"""Real startup controls and the native CPU budget."""
import os

from sjtu_tpmshx.tests.gui_workbench_support import win as win


def test_cpu_cores_spinbox_sets_native_budget(win):
    for name in ('combo_tpms', 'le_L', 'le_H', 'canvas_temp', 'progress'):
        assert hasattr(win, name), f'{name} missing after startup'
    assert win.run_control.backend == 'cpp'
    assert win.spin_cpu_cores.maximum() == (os.cpu_count() or 1)
    assert win.spin_cpu_cores.value() == 0
    assert win.spin_cpu_cores.text() == '自动'
    win.spin_cpu_cores.setValue(1)
    assert win.run_control.cpu_threads == 1
    win.spin_cpu_cores.setValue(0)
    assert win.run_control.cpu_threads is None
