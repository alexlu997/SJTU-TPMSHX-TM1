"""Check visible Quick Design controls and workbook export."""
import pytest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget

from sjtu_tpmshx.applications.gui.ui.quick_design_panel import QuickDesignPage
from sjtu_tpmshx.run_control.module_ports import RunControl
from tests.python.gui_worker_support import _wait_for


@pytest.fixture
def make_page():
    window = QWidget()
    window.run_control = RunControl()
    window._close_pending = False
    pages = []

    def make(mode='auto'):
        page = QuickDesignPage(window)
        page.le_qd_file.setText('spec.xlsx')
        page.mode_selector.set_value(mode)
        pages.append(page)
        return page

    yield make

    for page in pages:
        if not page.is_idle():
            page.cancel()
            _wait_for(page.is_idle)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('mode,arrangement,properties', [
    ('auto', 'counter', 'mean'), ('fixed', 'cross', 'const'),
])
def test_display_labels_do_not_change_backend_values(make_page, mode, arrangement, properties, monkeypatch):
    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.quick_design_panel.TRAIN_T_NODES', (.3000004, .6))
    page = make_page()
    page.mode_selector.set_value(mode)
    page.arrangement_selector.set_value(arrangement)
    page.prop_model_selector.set_value(properties)
    for selector in (page.mode_selector, page.arrangement_selector, page.prop_model_selector):
        selector.set_label(selector.current_index(), '修改后的显示名称')
    params = page._gather_inputs()
    assert (params['mode'], params['arrangement'], params['prop_model']) == (
        mode, arrangement, properties)
    if mode == 'auto':
        assert params['nodes']['t'] == [.3000004, .6]
    assert page.le_qd_l.isVisibleTo(page._input_drawer_body) == (mode == 'auto')
    assert page.le_qd_cell_l.isVisibleTo(page._input_drawer_body) == (mode == 'fixed')


@pytest.mark.parametrize('alias', [False, True])
def test_export_preserves_accepted_input_after_file_draft_changes(make_page, tmp_path, monkeypatch, alias):
    from openpyxl import load_workbook
    from PySide6.QtWidgets import QFileDialog, QPushButton
    from sjtu_tpmshx.applications.design.cases import load_cases
    from sjtu_tpmshx.applications.design.sizing import Design
    from tests.python.design.test_cases import _make_xlsx

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
    page = make_page()
    assert not page._qd_export_btn.isEnabled()
    page.le_qd_file.setText(str(source))
    page.mode_selector.set_value('fixed')
    page._qd_run_btn.click()
    _wait_for(page.is_idle)
    assert page._qd_export_btn.isEnabled()
    assert calls == [2]
    assert page.last_result['params']['file'] == str(source)
    page.le_qd_file.setText(str(tmp_path / 'next-input.xlsx'))
    assert page.last_result['case_limits'] == [
        dict(case=1, dPlim_h=.075, dPlim_c=.05), dict(case=2, dPlim_h=.07, dPlim_c=.05)]
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
    export = next(b for b in page.findChildren(QPushButton) if b.text() == '导出 xlsx')
    export.click()
    assert page._qd_status.text() == '导出失败: 导出文件不能覆盖输入算例文件'
    assert page._action_notice is not None and '输入算例文件' in page._action_notice.detail
    assert source.read_bytes() == previous
    assert len(load_cases(str(source))) == 2
    if alias:
        assert target.is_symlink()
    target = tmp_path / 'report.xlsx'
    export.click()
    assert '已导出' in page._qd_status.text()
    workbook = load_workbook(target, read_only=True)
    try:
        assert workbook.sheetnames == ['构型汇总', '工况明细']
        cells = list(workbook['构型汇总'].values)
        row = dict(zip(cells[0], cells[1]))
        assert row['拓扑'] == 'Diamond' and row['l_mm'] == 7.
    finally:
        workbook.close()
    assert source.read_bytes() == previous
