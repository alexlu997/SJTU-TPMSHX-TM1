from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sjtu_tpmshx.applications.gui.ui.quick_design_job import QuickDesignJob
from sjtu_tpmshx.run_control.module_ports import RunControl
from tests.python.gui_workbench_support import win as win
from tests.python.gui_worker_support import _wait_for
from tests.python.test_quick_design_dialog import make_page as make_page


_CASE = SimpleNamespace(case=3, dPlim_h=.04, dPlim_c=.09)


def test_page_reads_launch_control_and_keeps_results_between_visits(win, monkeypatch):
    from sjtu_tpmshx.applications.design.sizing import Design

    limits = []
    def size(*args, control, **kwargs):
        limits.append(control.cpu_threads)
        return Design(True, topo='Diamond', l=7., t=.5, V=.001)

    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda path: [_CASE])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.sizing.size_fixed_cell', size)
    page = win.quick_design
    assert not page._qd_export_btn.isEnabled()
    page.le_qd_file.setText('study.csv')
    page.mode_selector.set_value('fixed')
    for threads in (1, 0):
        win.btn_quick_design.click()
        assert win.page_stack.currentWidget() is page
        win.spin_cpu_cores.setValue(threads)
        page._qd_run_btn.click()
        _wait_for(page.is_idle)
        result = page.last_result
        assert result['feasible'] == [result['best']]
        assert page._qd_export_btn.isEnabled()
        win.btn_tab_layout.click()
        assert win.page_stack.currentWidget() is not page
        win.btn_quick_design.click()
        assert page.last_result is result and page._qd_table.rowCount() == 1
    assert limits == [1, None]

    # Style P2 Quick Design: drawer closed by default, peek card visible on chart view when closed.
    from PySide6.QtWidgets import QApplication, QPushButton
    win.btn_quick_design.click()
    QApplication.processEvents()
    assert not win.appearance.is_drawer_open('qd')
    assert not win.inspector_drawer.isVisibleTo(win)
    page.select_view_tab(1)
    QApplication.processEvents()
    assert page.peek_card.isVisibleTo(page)
    detail_btn = next(b for b in page.peek_card.findChildren(QPushButton) if '详情' in b.text())
    detail_btn.click()
    QApplication.processEvents()
    assert win.appearance.is_drawer_open('qd')
    assert win.inspector_drawer.strip_index() == 1
    assert not page.peek_card.isVisibleTo(page)

    # Invalid input error is surfaced visibly via toast and readout strip, not only a hidden label.
    page.mode_selector.set_value('auto')
    old_l = page.le_qd_l.text()
    page.le_qd_l.setText('4,oops')
    page.submit()
    QApplication.processEvents()
    assert '胞元尺寸 L' in win.dialogs.last_notice
    assert win.readout_strip.isVisibleTo(win)
    page.le_qd_l.setText(old_l)
    win.appearance.set_drawer_open(False, page_key='qd')
    page.select_view_tab(0)


@pytest.mark.parametrize('frozen', [False, True])
def test_worker_auto_calls_backend_and_emits(make_page, monkeypatch, frozen):
    monkeypatch.setattr('sys.frozen', frozen, raising=False)
    w = make_page("auto"); p = w._gather_inputs()
    worker = QuickDesignJob(p, control=RunControl())
    captured = {}
    class _D:
        feasible=True; topo="Diamond"; l=5.0; t=0.5; s=0.133; Lx=0.011
        V=2.02e-4; weight=0.6; dP_hot_max=0.005; dP_cold_max=0.031
        T_out_hot_max=560.0; arrangement="counter"; reason=""
    def _fake_load(path): captured["path"]=path; return [_CASE]
    def _fake_enum(cases, arrangement, nodes, rho_s, n_jobs=1, k_s=16.0,
                   prop_model="const", height=None, control=None, *, completed=None):
        captured.update(arr=arrangement, nodes=nodes, rho=rho_s, jobs=n_jobs,
                        ks=k_s, pm=prop_model, height=height)
        d=_D(); return [d], d
    received=[]
    worker.finished_with_result.connect(lambda r: received.append(r))
    with patch("sjtu_tpmshx.applications.design.cases.load_cases", _fake_load), \
         patch("sjtu_tpmshx.applications.design.select.enumerate_select", _fake_enum):
        worker.run()
    assert captured["path"]=="spec.xlsx"
    assert captured["arr"]=="cross" and captured["rho"]==7900.0
    assert captured["jobs"] == (1 if frozen else -1)
    assert captured["ks"]==16.0   # 默认 304SS 热导率传入后端
    assert captured["pm"]=="mean" # UI 默认物性模型 = 均温
    assert captured["height"] is None   # 默认方形 (未勾固定高度迎风)
    assert len(received)==1
    feas, best = received[0]["feasible"], received[0]["best"]
    assert best.topo=="Diamond" and len(feas)==1


@pytest.mark.parametrize('stage', ['enumeration', 'refinement'])
def test_cancel_retains_completed_candidates_from_current_stage(make_page, monkeypatch, stage):
    from sjtu_tpmshx.applications.design.sizing import Design
    from sjtu_tpmshx.applications.design.select import SelectionCancelled
    from sjtu_tpmshx.run_control.cancellation import CancelledError
    d = Design(True, topo='Diamond', l=5., t=.4, V=.01)
    def enumeration(*args, **kwargs):
        if stage == 'enumeration':
            raise SelectionCancelled([d])
        return [d], d
    def refinement(*args, **kwargs):
        raise CancelledError('cancelled during refinement')
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda p: [_CASE])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.select.enumerate_select', enumeration)
    monkeypatch.setattr('sjtu_tpmshx.applications.design.optimize.warm_start_joint', refinement)
    params = make_page()._gather_inputs()
    params['refine'] = True
    worker = QuickDesignJob(params, control=RunControl())
    received = []
    worker.finished_with_result.connect(received.append)
    worker.run()
    result, = received
    assert result['all'] == result['feasible'] == [d]
    assert result['best'] is d
    assert result['partial'] and result['termination_reason'] == 'cancelled'


def test_new_run_clears_stale_results_then_publishes_partial_current_result(make_page, monkeypatch):
    import threading
    from sjtu_tpmshx.applications.design.sizing import Design
    from sjtu_tpmshx.applications.design.select import SelectionCancelled
    monkeypatch.setattr('sys.frozen', True, raising=False)
    release = threading.Event()
    d = Design(True, topo='Gyroid', l=5., t=.4, V=.01,
               percase=[dict(case=3, Q_W=12., Q_cold_W=10.,
                             energy_imbalance_rel=1 / 6,
                             energy_imbalance_status='available',
                             energy_imbalance_reason='')])
    def enumeration(*args, **kwargs):
        assert kwargs['n_jobs'] == 1
        assert release.wait(10)
        raise SelectionCancelled([d])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda p: [_CASE])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.select.enumerate_select', enumeration)
    w = make_page()
    w.last_result = {'old': True}
    w._qd_table.setRowCount(1)
    w._qd_energy_table.setRowCount(1)
    w.submit()
    try:
        assert w.last_result is None and w._qd_table.rowCount() == 0
        assert w._qd_energy_table.rowCount() == 0
        assert '单进程串行' in w._qd_status.text()
    finally:
        release.set()
    _wait_for(w.is_idle)
    assert w.last_result['all'] == [d] and w.last_result['partial']
    assert '已取消' in w._qd_status.text() and '不代表完整搜索最优' in w._qd_status.text()
    cancel_notice = w.readout_spec()[1]
    assert cancel_notice is not None and '已取消' in cancel_notice.title and '不代表完整搜索最优' in cancel_notice.detail
    assert w._qd_table.rowCount() == 1
    assert w._qd_table.item(0, 12).text().startswith('已完成候选内')
    assert w._qd_energy_table.rowCount() == 1
    assert w._qd_energy_table.item(0, 1).text() == '3'

def test_gather_inputs_rect_height(make_page):
    w = make_page("auto")
    w.chk_qd_rect.setChecked(True)
    w.le_qd_height.setText("750")
    p = w._gather_inputs()
    assert abs(p["height"] - 0.750) < 1e-12   # mm→m
    assert make_page("auto")._gather_inputs()["height"] is None


@pytest.mark.parametrize('bad_height', ['0', '-10', 'nan', 'inf', '-inf', 'abc', '1e-322'])
def test_gather_inputs_rejects_invalid_rect_height(make_page, bad_height):
    w = make_page("auto")
    w.chk_qd_rect.setChecked(True)
    w.le_qd_height.setText(bad_height)
    with pytest.raises(ValueError):
        w._gather_inputs()

def test_worker_emits_error_on_exception(make_page):
    w=make_page("auto"); worker=QuickDesignJob(w._gather_inputs(), control=RunControl())
    errs=[]; worker.error_signal.connect(lambda m: errs.append(m))
    def _boom(path): raise RuntimeError("bad file")
    with patch("sjtu_tpmshx.applications.design.cases.load_cases", _boom):
        worker.run()
    assert len(errs)==1 and "RuntimeError" in errs[0]


def test_run_quick_design_malformed_node_list_gives_feedback_not_crash(make_page):
    """U3 (audit 2026-06-28): a non-numeric node list (le_qd_l) must NOT let
    ValueError escape the Run slot — Qt swallows it to stderr, leaving a dead
    '运行设计' button with no _qd_status. The handler must catch the parse error
    and surface it, and must not launch a worker."""
    w = make_page("auto")
    w.le_qd_l.setText("4,5,oops,7")     # malformed token in the node list
    w.submit()               # must NOT raise
    assert ("解析" in w._qd_status.text() or "失败" in w._qd_status.text()), \
        f"no parse-failure feedback; status was {w._qd_status.text()!r}"
    notice = w.readout_spec()[1]
    assert notice is not None and ("解析" in notice.detail or "失败" in notice.detail)
    assert w.is_idle(), "worker launched on bad input"


def test_run_quick_design_malformed_fixed_cell_gives_feedback(make_page):
    """Bad active fixed-cell input is reported before launching a worker."""
    w = make_page("fixed")
    w.le_qd_cell_l.setText("7mm")        # malformed fixed-cell length
    w.submit()               # must NOT raise
    assert ("解析" in w._qd_status.text() or "失败" in w._qd_status.text())
    notice = w.readout_spec()[1]
    assert notice is not None and ("解析" in notice.detail or "失败" in notice.detail)


def test_thread_result_warnings_reach_table(make_page, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.applications.design.sizing import Design
    d = Design(True, topo='Diamond', l=5., t=.5, s=.1, Lx=.1,
               percase=[dict(case=2, warnings=['final-source'])])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda path: [_CASE])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.sizing.size_fixed_cell', lambda *a, **kw: d)
    worker = QuickDesignJob(make_page('fixed')._gather_inputs(), control=RunControl())
    received = []
    worker.finished_with_result.connect(received.append)
    worker.start()
    assert worker.wait(5000)
    QApplication.processEvents()
    assert received[0]['best'] is d
    assert received[0]['all'][0].percase == d.percase
    w = make_page("fixed")
    w._fill_table(received[0]['feasible'])
    cell = w._qd_table.item(0, 11)
    assert cell.text() == '有警告'
    assert cell.toolTip() == '[算例 2] final-source'
    from sjtu_tpmshx.applications.gui.ui.theme import get_theme
    assert cell.foreground().color().name() == get_theme()['warn'].lower()


def test_completed_energy_diagnostics_include_all_cases_without_changing_feasibility(make_page, monkeypatch):
    from sjtu_tpmshx.applications.design.sizing import Design

    feasible = Design(True, topo='Diamond', l=5., t=.5, V=.002, percase=[
        dict(case='hot', Q_W=100., Q_cold_W=75., energy_imbalance_rel=.25,
             energy_imbalance_status='available', energy_imbalance_reason='',
             run_status={'converged': True}, acceptance_reasons=[]),
        dict(case='zero', Q_W=0., Q_cold_W=0., energy_imbalance_rel=None,
             energy_imbalance_status='insufficient_data',
             energy_imbalance_reason='missing source diagnostic',
             run_status={'converged': True}, acceptance_reasons=[]),
    ])
    infeasible = Design(False, topo='Gyroid', l=6., t=.4, V=.001,
                        percase=[dict(case='legacy', Q_W=7.,
                                      run_status={'converged': False},
                                      acceptance_reasons=['not-converged@final'])])
    early = Design(False, topo='Diamond', l=4., t=.3, reason='no final case')
    results = [feasible, infeasible, early]
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda path: [_CASE])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.select.enumerate_select',
                        lambda *a, **kw: (results, feasible))
    window = make_page()
    window.submit()
    _wait_for(window.is_idle)

    assert window.last_result['all'] == results
    assert window.last_result['feasible'] == [feasible] and window.last_result['best'] is feasible
    assert window._qd_table.rowCount() == 1
    assert window._qd_table.columnCount() == 13
    table = window._qd_energy_table
    rows = [[table.item(i, j).text() for j in range(table.columnCount())]
            for i in range(table.rowCount())]
    assert rows == [
        ['Diamond_l5_t0.5', 'hot', '100', '75', '25', '可用', '', '是', '是', ''],
        ['Diamond_l5_t0.5', 'zero', '0', '0', '—', '数据不足',
         'missing source diagnostic', '是', '是', ''],
        ['Gyroid_l6_t0.4', 'legacy', '7', '—', '—', '—',
         '未提供能量不平衡诊断', '否', '否', 'not-converged@final'],
    ]
    assert feasible.percase[0]['energy_imbalance_rel'] == .25


@pytest.mark.parametrize('mode,hidden,active', [
    ('auto', 'le_qd_cell_l', 'le_qd_l'),
    ('fixed', 'le_qd_l', 'le_qd_cell_l'),
])
def test_only_active_design_parameters_are_parsed(make_page, mode, hidden, active):
    w = make_page(mode)
    w.le_qd_l.setText('5,6,7,8')
    getattr(w, hidden).setText('invalid')
    params = w._gather_inputs()
    if mode == 'auto':
        assert params['nodes']['l'] == [5., 6., 7., 8.]
        assert 'cell' not in params
    else:
        assert params['cell'] == ('Diamond', 7., .5)
        assert 'nodes' not in params
    getattr(w, active).setText('invalid')
    with pytest.raises(ValueError):
        w._gather_inputs()


@pytest.mark.parametrize('stage', ['enumeration', 'refinement'])
def test_failure_keeps_completed_candidates_error_and_export(make_page, monkeypatch, tmp_path, stage):
    from dataclasses import replace
    from openpyxl import load_workbook
    from sjtu_tpmshx.applications.gui.ui import quick_design_panel as panel
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog, QPushButton
    from sjtu_tpmshx.applications.design import optimize, select
    from sjtu_tpmshx.applications.design.sizing import Design
    inputs = tmp_path / 'cases.csv'
    inputs.write_text(
        'case,hot_fluid,T_in_h_K,P_in_h_kPa,mdot_h,cold_fluid,T_in_c_K,P_in_c_kPa,mdot_c,Q_kW,dPlim_h,dPlim_c\n'
        '1,air,500,200,0.1,water,300,200,0.1,10,0.1,0.1\n', encoding='utf-8')
    case_result = dict(case=1, hot_fluid='air', cold_fluid='water',
        T_air_out=400., T_cold_out=350., Q_W=10000., Q_cold_W=8000.,
        energy_imbalance_rel=.2, energy_imbalance_status='available',
        energy_imbalance_reason='',
        dP_hot_frac=.01, dP_hot_pa=2000., dP_cold_frac=.02, dP_cold_pa=4000.,
        Re_hot=1000., Re_cold=2000., warnings=['retained source warning'],
        run_status={'converged': True}, acceptance_reasons=[])
    feasible = Design(True, topo='Diamond', l=4., t=.4, s=.1, Lx=.1,
                      V=.001, weight=1., percase=[case_result])
    infeasible = replace(feasible, feasible=False, l=5., V=.0005,
                         reason='not-converged@final', percase=[dict(case_result,
                         run_status={'converged': False},
                         acceptance_reasons=['not-converged@final'])])
    completed = [feasible, infeasible]
    error = ValueError(f'injected {stage} failure')
    calls, events = [], []

    def candidate(cases, topo, length, wall, *args, **kwargs):
        calls.append(length)
        if length == 6.:
            raise error
        return completed[int(length) - 4]

    def refinement(*args, **kwargs):
        raise error

    # Enumeration, file loading, QThread.run, result/table delivery and Excel
    # remain real. Only individual candidate work/refinement is controlled.
    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    monkeypatch.setattr(optimize, 'warm_start_joint', refinement)

    def make_worker(params, *, control):
        worker = QuickDesignJob(params, control=control)
        worker.n_jobs = 1
        # Attach before start(), including when a controlled candidate is fast.
        worker.finished_with_result.connect(lambda value: events.append(('result', value)))
        worker.error_signal.connect(lambda value: events.append(('error', value)))
        worker.cancelled.connect(lambda: events.append(('cancelled', None)))
        return worker

    monkeypatch.setattr(panel, 'QuickDesignJob', make_worker)
    page = make_page()
    page.le_qd_file.setText(str(inputs))
    page.topo_checks['Diamond'].setChecked(True)
    page.topo_checks['Gyroid'].setChecked(False)
    page.le_qd_l.setText('4,5,6,7' if stage == 'enumeration' else '4,5')
    page.le_qd_t.setText('0.4')
    page.chk_qd_refine.setChecked(stage == 'refinement')
    page.last_result = {'old': True}
    page._qd_table.setRowCount(1)
    page._qd_energy_table.setRowCount(1)
    QTest.mouseClick(page._qd_run_btn, Qt.MouseButton.LeftButton)
    assert page.last_result is None and page._qd_table.rowCount() == 0
    assert page._qd_energy_table.rowCount() == 0
    _wait_for(page.is_idle)
    assert calls == ([4., 5., 6.] if stage == 'enumeration' else [4., 5.])
    assert [value for kind, value in events if kind == 'error'] == [
        f'ValueError: injected {stage} failure']
    assert [kind for kind, _ in events] == ['result', 'error'], events
    result = page.last_result
    assert result['all'] == completed and result['feasible'] == [feasible]
    assert result['best'] is feasible
    assert result['partial'] and result['termination_reason'] == 'failed'
    status = page._qd_status.text()
    assert str(error) in status and '保留 2' in status
    assert '不代表完整搜索最优' in status and '已取消' not in status
    notice = page.readout_spec()[1]
    assert notice is not None and str(error) in notice.detail and '不代表完整搜索最优' in notice.detail
    assert page._qd_table.rowCount() == 1
    assert page._qd_table.item(0, 12).text().startswith('已完成候选内')
    assert page._qd_energy_table.rowCount() == 2
    assert [page._qd_energy_table.item(i, 4).text() for i in range(2)] == ['20', '20']
    assert [page._qd_energy_table.item(i, 8).text() for i in range(2)] == ['是', '否']
    assert page._qd_run_btn.isEnabled() and not page._qd_cancel_btn.isEnabled()

    output = tmp_path / 'failed-partial.xlsx'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(output), ''))
    export = next(button for button in page.findChildren(QPushButton)
                  if button.text() == '导出 xlsx')
    QTest.mouseClick(export, Qt.MouseButton.LeftButton)
    assert output.exists(), page._qd_status.text()
    assert '失败' in page._qd_status.text() and '已取消' not in page._qd_status.text()
    workbook = load_workbook(output)
    try:
        rows = {}
        for sheet in workbook:
            cells = list(sheet.values)
            rows[sheet.title] = [dict(zip(cells[0], row)) for row in cells[1:]]
            assert len(rows[sheet.title]) == 2
            for row in rows[sheet.title]:
                state = row['任务状态']
                assert '失败' in state and '部分' in state and '不代表完整搜索最优' in state
                assert '取消' not in state
        summary = {row['l_mm']: row for row in rows['构型汇总']}
        assert summary[4]['可行'] == '是' and summary[5]['可行'] == '否'
        assert summary[4]['标记'].startswith('已完成候选内')
        assert summary[5]['备注'] == 'not-converged@final'
        for row in rows['算例明细']:
            assert row['热侧出口_K'] == 400. and row['换热量_kW'] == 10.
            assert row['警告'] == 'retained source warning'
        assert {row['数值收敛'] for row in rows['算例明细']} == {True, False}
    finally:
        workbook.close()


def test_cli_and_gui_share_unified_defaults_and_density(make_page, monkeypatch, tmp_path):
    from sjtu_tpmshx.applications.design import cli, sizing

    monkeypatch.setattr(sizing, 'RHO_S', 2700.)
    monkeypatch.setattr(sizing, 'K_STEEL', 150.)
    seen = []
    design = sizing.Design(True, topo='Diamond', l=7., t=.5, V=.002)

    def fixed(cases, topo, l, t, arrangement, **kwargs):
        seen.append(dict(arrangement=arrangement, rho_s=kwargs['rho_s'],
                         k_s=kwargs['k_s'], prop_model=kwargs['prop_model'],
                         height=kwargs['height']))
        return design

    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda p: [_CASE])
    monkeypatch.setattr(cli, 'load_cases', lambda p: [_CASE])
    monkeypatch.setattr(sizing, 'size_fixed_cell', fixed)

    page = make_page()
    assert page.le_qd_rho.text() == '2700'
    assert page.le_qd_ks.text() == '150'
    page.le_qd_file.setText('spec.xlsx')
    page.mode_selector.set_value('fixed')
    params = page._gather_inputs()
    assert params['rho_s'] == 2700. and params['k_s'] == 150.
    assert params['arrangement'] == 'cross' and params['prop_model'] == 'mean'
    assert params['height'] is None

    # Previous GUI counterflow and CLI const selections stay reachable.
    page.arrangement_selector.set_value('counter')
    page.prop_model_selector.set_value('const')
    legacy = page._gather_inputs()
    assert legacy['arrangement'] == 'counter' and legacy['prop_model'] == 'const'

    worker = QuickDesignJob(params, control=RunControl())
    received = []
    worker.finished_with_result.connect(received.append)
    worker.run()
    assert received[0]['best'] is design

    assert cli.run(['--xlsx', str(tmp_path / 'spec.xlsx'), '--mode', 'fixed',
                    '--cell', 'Diamond,7,0.5', '--out', str(tmp_path / 'out.xlsx')]) == 0
    expected = dict(arrangement='cross', rho_s=2700., k_s=150., prop_model='mean', height=None)
    assert seen == [expected, expected]


@pytest.mark.parametrize('scenario', [
    'fixed_feasible',
    'fixed_infeasible',
    'fixed_rect_height',
    'auto',
    'auto_rect_height',
    'auto_refine_improved',
    'auto_refine_fallback',
    'failed_refinement',
    'cancel_enumeration',
    'cancel_refinement',
])
def test_cli_and_gui_match_on_shared_inputs(make_page, monkeypatch, tmp_path, capsys, scenario):
    from openpyxl import load_workbook
    from sjtu_tpmshx.applications.design import cli, optimize, report, select, sizing
    from sjtu_tpmshx.run_control.cancellation import CancelledError

    source = tmp_path / 'spec.csv'
    source.write_text(
        'case,hot_fluid,T_in_h_K,P_in_h_kPa,mdot_h,cold_fluid,T_in_c_K,P_in_c_kPa,'
        'mdot_c,Q_kW,dPlim_h,dPlim_c\n'
        '1,air,500,200,0.1,water,300,200,0.1,10,0.1,0.1\n', encoding='utf-8')

    use_rect = scenario.endswith('_rect_height')
    expected_height = .75 if use_rect else None

    def make_design(feasible, l, t, volume, *, reason=''):
        detail = dict(
            case=1, hot_fluid='air', cold_fluid='water',
            T_air_out=400., T_cold_out=350., Q_W=10000., Q_cold_W=9900.,
            energy_imbalance_rel=.01, energy_imbalance_status='available',
            energy_imbalance_reason='', dP_hot_frac=.01, dP_hot_pa=2000.,
            dP_cold_frac=.02, dP_cold_pa=4000., Re_hot=1000., Re_cold=2000.,
            warnings=[], run_status={'converged': feasible},
            acceptance_reasons=([reason] if reason else []),
        )
        return sizing.Design(
            feasible, topo='Diamond', l=l, t=t, s=.1, Lx=.1, arrangement='cross',
            V=volume, weight=volume * 2000., dP_hot_max=.01, dP_cold_max=.02,
            T_out_hot_max=400., reason=reason, percase=[detail],
            height=(expected_height or 0.0),
        )

    designs = {
        5.: make_design(False, 5., .4, .0008, reason='dP>lim@final'),
        6.: make_design(True, 6., .4, .0030),
        7.: make_design(True, 7., .4, .0020),
    }
    refined_better = make_design(True, 6.8, .42, .0015)
    failure = RuntimeError('injected refinement failure')

    def run_pair():
        state = {'cancel': False}

        def candidate(cases, topo, l, t, arrangement, **kwargs):
            assert arrangement == 'cross' and kwargs['prop_model'] == 'mean'
            assert kwargs['rho_s'] == sizing.RHO_S and kwargs['k_s'] == sizing.K_STEEL
            assert kwargs['height'] == expected_height
            if scenario == 'fixed_infeasible':
                return designs[5.]
            if scenario == 'cancel_enumeration' and l == 6.:
                state['cancel'] = True
            return designs[l]

        def refine(cases, baseline, arrangement, **kwargs):
            assert kwargs['height'] == expected_height
            if scenario == 'failed_refinement':
                raise failure
            if scenario == 'cancel_refinement':
                raise CancelledError('cancelled during refinement')
            if scenario == 'auto_refine_improved':
                return refined_better
            return baseline

        monkeypatch.setattr(sizing, 'size_fixed_cell', candidate)
        monkeypatch.setattr(select, 'size_fixed_cell', candidate)
        monkeypatch.setattr(optimize, 'warm_start_joint', refine)
        return state

    mode = 'fixed' if scenario.startswith('fixed') else 'auto'
    use_refine = scenario in (
        'auto_refine_improved', 'auto_refine_fallback',
        'failed_refinement', 'cancel_refinement',
    )
    cli_out = tmp_path / f'{scenario}.xlsx'
    cli_args = [
        '--xlsx', str(source), '--mode', mode, '--jobs', '1', '--out', str(cli_out),
    ]
    if mode == 'fixed':
        cli_args += ['--cell', 'Diamond,7,0.4']
    else:
        cli_args += ['--nodes', 'Diamond:5,6,7:0.4']
    if use_rect:
        cli_args += ['--height', '750']
    if use_refine:
        cli_args.append('--refine')

    # Run CLI.
    cli_state = run_pair()
    cli_control = RunControl(cancel_check=lambda: cli_state['cancel'])
    monkeypatch.setattr(cli, 'run_control_from_args', lambda a: cli_control)
    cli_cancelled = None
    cli_failed = None
    if scenario == 'failed_refinement':
        with pytest.raises(RuntimeError) as caught:
            cli.run(cli_args)
        cli_failed = caught.value
    elif scenario.startswith('cancel_'):
        with pytest.raises(select.SelectionCancelled) as caught:
            cli.run(cli_args)
        cli_cancelled = caught.value
    else:
        assert cli.run(cli_args) == 0
    cli_stdout = capsys.readouterr().out

    # Run GUI worker with matching inputs gathered from the page.
    gui_state = run_pair()
    gui_control = RunControl(cancel_check=lambda: gui_state['cancel'])
    page = make_page()
    page.le_qd_file.setText(str(source))
    page.mode_selector.set_value(mode)
    page.chk_qd_rect.setChecked(use_rect)
    if use_rect:
        page.le_qd_height.setText('750')
    if mode == 'fixed':
        page.combo_qd_cell_topo.setCurrentText('Diamond')
        page.le_qd_cell_l.setText('7')
        page.le_qd_cell_t.setText('0.4')
    else:
        page.topo_checks['Diamond'].setChecked(True)
        page.topo_checks['Gyroid'].setChecked(False)
        page.le_qd_l.setText('5,6,7')
        page.le_qd_t.setText('0.4')
        page.chk_qd_refine.setChecked(use_refine)
    gui_params = page._gather_inputs()
    clock = iter((12., 18.75))
    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.quick_design_job.perf_counter', lambda: next(clock))
    worker = QuickDesignJob(gui_params, control=gui_control)
    worker.n_jobs = 1
    gui_results, gui_errors, gui_cancelled = [], [], []
    worker.finished_with_result.connect(gui_results.append)
    worker.error_signal.connect(gui_errors.append)
    worker.cancelled.connect(lambda: gui_cancelled.append(True))
    worker.run()

    assert len(gui_results) == 1
    gui = gui_results[0]
    assert gui['case_limits'] == [dict(case=1, dPlim_h=.1, dPlim_c=.1)]
    assert gui['elapsed_s'] == 6.75
    gui_order = [report.cid(d) for d in gui['all']]
    gui_best_id = report.cid(gui['best']) if gui['best'] is not None else None

    if scenario.startswith('cancel_'):
        assert gui_cancelled == [True] and not gui_errors
        assert gui['partial'] and gui['termination_reason'] == 'cancelled'
        cli_order = [report.cid(d) for d in cli_cancelled.results]
        cli_feas = [d for d in cli_cancelled.results if d.feasible]
        cli_best = min(cli_feas, key=lambda d: d.V) if cli_feas else None
        cli_best_id = report.cid(cli_best) if cli_best is not None else None
        assert cli_order == gui_order
        assert cli_best_id == gui_best_id
        expected = ['Diamond_l5_t0.4', 'Diamond_l6_t0.4'] if scenario == 'cancel_enumeration' else [
            'Diamond_l5_t0.4', 'Diamond_l6_t0.4', 'Diamond_l7_t0.4']
        assert cli_order == expected
        return

    workbook = load_workbook(cli_out, read_only=True, data_only=True)
    try:
        detail_rows = list(workbook['算例明细'].values)
        detail_header = detail_rows[0]
        cli_order = [row[detail_header.index('构型')] for row in detail_rows[1:]]
        summary_rows = list(workbook['构型汇总'].values)
        summary_header = summary_rows[0]
        min_v_rows = [
            row[summary_header.index('构型')]
            for row in summary_rows[1:]
            if 'min-V' in (row[summary_header.index('标记')] or '')
        ]
        if use_rect:
            heights = {row[summary_header.index('H_mm')] for row in summary_rows[1:]}
            assert heights == {750.0}
    finally:
        workbook.close()

    assert cli_order == gui_order
    cli_best_id = min_v_rows[0] if min_v_rows else None
    assert cli_best_id == gui_best_id
    if scenario == 'failed_refinement':
        assert cli_failed is failure
        assert gui_errors == ['RuntimeError: injected refinement failure']
        assert gui['partial'] and gui['termination_reason'] == 'failed'
        assert cli_order == ['Diamond_l5_t0.4', 'Diamond_l6_t0.4', 'Diamond_l7_t0.4']
    else:
        assert not gui_errors and not gui['partial']
        if gui_best_id is not None:
            assert f'best (min-V): {gui_best_id}' in cli_stdout
            if use_rect:
                assert '100.0×750.0×100.0mm' in cli_stdout
        else:
            assert 'best (min-V):' not in cli_stdout
