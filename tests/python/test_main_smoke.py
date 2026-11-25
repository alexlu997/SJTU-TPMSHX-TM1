"""Tests for controls on the main window."""
import os
import sys
from unittest.mock import Mock

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


def test_sweep_button_clears_prior_heatmap_for_unknown_fluid(win, monkeypatch):
    from sjtu_tpmshx.applications.gui.ui.sensitivity import SensitivityDialog

    win.combo_fluidA.setCurrentText('Air')
    dialog = SensitivityDialog(win)
    dialog._le_steps.setText('3')
    dialog._btn_run.click()
    assert dialog._grid_params is not None
    prior_axes = dialog._grid_axes

    win.combo_fluidA.addItem('Helium')
    win.combo_fluidA.setCurrentText('Helium')
    unhandled = Mock()
    monkeypatch.setattr(sys, 'excepthook', unhandled)
    dialog._btn_run.click()
    unhandled.assert_not_called()
    assert 'Helium' in dialog._hint.text()
    assert dialog._grid_params is None
    assert prior_axes not in dialog._canvas.fig.axes


@pytest.mark.parametrize('co2_side', ['A', 'B'])
@pytest.mark.parametrize('preview', ['geometry', 'auto_fill'])
def test_previews_reject_unknown_fluid_on_either_side(win, monkeypatch, co2_side, preview):
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.applications.gui.ui.mixins import fluid_input

    win.combo_dim.setCurrentIndex(0)
    for side in 'AB':
        combo = getattr(win, 'combo_fluid' + side)
        if side == co2_side:
            combo.setCurrentText('CO₂')
        else:
            combo.addItem('Helium')
            combo.setCurrentText('Helium')
    error = Mock()
    monkeypatch.setattr(QMessageBox, 'critical', error)
    if preview == 'geometry':
        fields = [win._v_eps, win._v_A0, win._v_Dh, win._v_Kss]
        before = [field.text() for field in fields]
        assert not win.compute_tpms()
    else:
        fields = [getattr(win, '_v_' + key + co2_side) for key in ('rho', 'Re', 'Nu', 'dPL')]
        before = [field.text() for field in fields]
        monkeypatch.setattr(win, 'compute_tpms', lambda: True)
        compute = Mock(wraps=fluid_input.tpms_compute)
        monkeypatch.setattr(fluid_input, 'tpms_compute', compute)
        win._auto_fill_fluid(co2_side)
        compute.assert_not_called()
    error.assert_called_once()
    assert 'Helium' in error.call_args.args[2]
    assert [field.text() for field in fields] == before
