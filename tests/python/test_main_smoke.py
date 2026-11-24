"""Tests for controls on the main window."""
import os

import pytest

from tests.python.gui_workbench_support import win as win


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


def test_compute_and_sensitivity_read_the_selected_topology(win):
    from sjtu_tpmshx.applications.gui.ui.sensitivity import SensitivityDialog
    from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window

    combo = win.combo_tpms
    assert [combo.itemText(i) for i in range(combo.count())] == ['Diamond', 'Gyroid']
    combo.insertItem(0, 'Test topology')
    dialog = SensitivityDialog(win)
    for name in ('Diamond', 'Gyroid'):
        combo.setCurrentText(name)
        assert config_from_window(win).geometry.tpms == name
        assert dialog._collect_fixed_params(('L_cell', 't'))['tpms'] == name

    combo.setCurrentText('Test topology')
    with pytest.raises(ValueError, match='Test topology') as error:
        config_from_window(win)
    dialog._run_sweep()
    assert str(error.value) in dialog._hint.text()
    assert dialog._grid_params is None
