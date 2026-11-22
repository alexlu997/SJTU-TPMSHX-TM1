"""Check visible Quick Design controls and workbook export."""
import pytest

from sjtu_tpmshx.applications.gui.ui.quick_design_panel import build_quick_design_dialog


@pytest.mark.parametrize('mode,arrangement,properties', [
    ('auto', 'counter', 'mean'), ('fixed', 'cross', 'const'),
])
def test_display_labels_do_not_change_backend_values(mode, arrangement, properties, monkeypatch):
    from sjtu_tpmshx.applications.gui.ui.quick_design_panel import _gather_inputs

    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.quick_design_panel.TRAIN_T_NODES', (.3000004, .6))
    dlg = build_quick_design_dialog()
    dlg.combo_qd_mode.setCurrentIndex(dlg.combo_qd_mode.findData(mode))
    dlg.combo_qd_arr.setCurrentIndex(dlg.combo_qd_arr.findData(arrangement))
    dlg.combo_qd_prop.setCurrentIndex(dlg.combo_qd_prop.findData(properties))
    for combo in (dlg.combo_qd_mode, dlg.combo_qd_arr, dlg.combo_qd_prop):
        combo.setItemText(combo.currentIndex(), '修改后的显示名称')
    params = _gather_inputs(dlg)
    assert (params['mode'], params['arrangement'], params['prop_model']) == (
        mode, arrangement, properties)
    if mode == 'auto':
        assert params['nodes']['t'] == [.3000004, .6]
    assert dlg.le_qd_l.isVisibleTo(dlg) == (mode == 'auto')
    assert dlg.le_qd_cell_l.isVisibleTo(dlg) == (mode == 'fixed')
    dlg.deleteLater()


@pytest.mark.parametrize('alias', [False, True])
def test_export_preserves_accepted_input_after_file_draft_changes(tmp_path, monkeypatch, alias):
    from openpyxl import load_workbook
    from PySide6.QtWidgets import QFileDialog, QPushButton
    from sjtu_tpmshx.applications.design.cases import load_cases
    from sjtu_tpmshx.applications.design.sizing import Design
    from tests.python.design.test_cases import _make_xlsx
    from tests.python.gui_worker_support import _wait_for

    source = tmp_path / 'input.xlsx'
    _make_xlsx(source)
    previous = source.read_bytes()
    target = source
    if alias:
        target = tmp_path / 'input-alias.xlsx'
        try:
            target.symlink_to(source)
        except OSError:
            pytest.skip('symlinks unavailable')
    calls = []

    def candidate(cases, *args, **kwargs):
        calls.append(len(cases))
        return Design(True, topo='Diamond', l=7., t=.5, V=.001)

    monkeypatch.setattr('sjtu_tpmshx.applications.design.sizing.size_fixed_cell', candidate)
    # Actual buttons, QThread, input loader and XLSX writer; only numerical
    # sizing and the headless file chooser's selected path are substituted.
    dialog = build_quick_design_dialog()
    try:
        dialog.le_qd_file.setText(str(source))
        dialog.combo_qd_mode.setCurrentIndex(dialog.combo_qd_mode.findData('fixed'))
        dialog._qd_run_btn.click()
        _wait_for(lambda: dialog._qd_worker is None)
        assert calls == [2]
        assert dialog._qd_last['params']['file'] == str(source)
        dialog.le_qd_file.setText(str(tmp_path / 'next-input.xlsx'))
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
        export = next(b for b in dialog.findChildren(QPushButton) if b.text() == '导出 xlsx')
        export.click()
        assert dialog._qd_status.text() == '导出失败: 导出文件不能覆盖输入工况文件'
        assert source.read_bytes() == previous
        assert len(load_cases(str(source))) == 2
        if alias:
            assert target.is_symlink()
        target = tmp_path / 'report.xlsx'
        export.click()
        assert '已导出' in dialog._qd_status.text()
        workbook = load_workbook(target, read_only=True)
        try:
            assert workbook.sheetnames == ['构型汇总', '工况明细']
            cells = list(workbook['构型汇总'].values)
            row = dict(zip(cells[0], cells[1]))
            assert row['拓扑'] == 'Diamond' and row['l_mm'] == 7.
        finally:
            workbook.close()
        assert source.read_bytes() == previous
    finally:
        if getattr(dialog, '_qd_worker', None) is not None:
            dialog._qd_worker.requestInterruption()
            _wait_for(lambda: dialog._qd_worker is None)
        dialog.close()
