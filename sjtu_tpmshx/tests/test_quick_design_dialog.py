"""Construction tests for build_quick_design_dialog.

Verifies:
  - All contract attributes exist on the returned QDialog instance.
  - The run button calls run_quick_design.
  - Switching combo_qd_mode between "auto" and "fixed" toggles group visibility.

Run from repo root:
    python -m pytest sjtu_tpmshx/tests/test_quick_design_dialog.py -v
"""
from unittest.mock import patch
import pytest
from sjtu_tpmshx.ui.quick_design_panel import build_quick_design_dialog

CONTRACT = [
    "le_qd_file", "combo_qd_mode", "combo_qd_arr", "le_qd_rho",
    "le_qd_topo", "le_qd_l", "le_qd_t", "chk_qd_refine",
    "combo_qd_cell_topo", "le_qd_cell_l", "le_qd_cell_t",
    "_qd_table", "_qd_status",
]


def test_dialog_builds_with_contract_attrs():
    dlg = build_quick_design_dialog()
    for a in CONTRACT:
        assert hasattr(dlg, a), f"missing contract attr {a}"
    assert dlg.combo_qd_mode.currentData() in ("auto", "fixed")
    assert dlg.combo_qd_arr.currentData() in ("counter", "cross")
    dlg.deleteLater()


def test_run_button_invokes_run_quick_design():
    dlg = build_quick_design_dialog()
    with patch("sjtu_tpmshx.ui.quick_design_panel.run_quick_design") as m:
        dlg._qd_run_btn.click()   # expose the run button as dlg._qd_run_btn
        assert m.called
    dlg.deleteLater()


def test_mode_toggle_switches_groups():
    dlg = build_quick_design_dialog()
    dlg.combo_qd_mode.setCurrentIndex(dlg.combo_qd_mode.findData("fixed"))
    assert dlg._qd_fixed_group.isVisibleTo(dlg) or not dlg._qd_auto_group.isVisibleTo(dlg)
    dlg.combo_qd_mode.setCurrentIndex(dlg.combo_qd_mode.findData("auto"))
    assert dlg._qd_auto_group.isVisibleTo(dlg) or not dlg._qd_fixed_group.isVisibleTo(dlg)
    dlg.deleteLater()


@pytest.mark.parametrize('mode', ['auto', 'fixed'])
@pytest.mark.parametrize('arrangement', ['counter', 'cross'])
def test_display_labels_do_not_change_backend_values(mode, arrangement):
    from sjtu_tpmshx.ui.quick_design_panel import _gather_inputs

    dlg = build_quick_design_dialog()
    dlg.combo_qd_mode.setCurrentIndex(dlg.combo_qd_mode.findData(mode))
    dlg.combo_qd_arr.setCurrentIndex(dlg.combo_qd_arr.findData(arrangement))
    dlg.combo_qd_prop.setCurrentIndex(dlg.combo_qd_prop.findData('const'))
    for combo in (dlg.combo_qd_mode, dlg.combo_qd_arr, dlg.combo_qd_prop):
        combo.setItemText(combo.currentIndex(), '修改后的显示名称')
    params = _gather_inputs(dlg)
    assert (params['mode'], params['arrangement'], params['prop_model']) == (
        mode, arrangement, 'const')
    assert dlg._qd_auto_group.isHidden() == (mode != 'auto')
    assert dlg._qd_fixed_group.isHidden() == (mode != 'fixed')
    dlg.deleteLater()
