from __future__ import annotations
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from unittest.mock import patch

from sjtu_tpmshx.applications.gui.ui.quick_design_panel import (
    _gather_inputs, _make_worker_class, build_quick_design_dialog, run_quick_design,
)

@pytest.fixture
def make_window():
    dialogs = []

    def make(mode="auto"):
        dialog = build_quick_design_dialog()
        dialogs.append(dialog)
        dialog.le_qd_file.setText("spec.xlsx")
        dialog.combo_qd_mode.setCurrentIndex(dialog.combo_qd_mode.findData(mode))
        dialog.le_qd_l.setText("5,6,7,8")
        dialog.le_qd_t.setText("0.4,0.5")
        return dialog

    yield make

    for dialog in dialogs:
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('frozen', [False, True])
def test_worker_auto_calls_backend_and_emits(make_window, monkeypatch, frozen):
    monkeypatch.setattr('sys.frozen', frozen, raising=False)
    w = make_window("auto"); p = _gather_inputs(w)
    Worker = _make_worker_class()
    worker = Worker(p)
    captured = {}
    class _D:
        feasible=True; topo="Diamond"; l=5.0; t=0.5; s=0.133; Lx=0.011
        V=2.02e-4; weight=0.6; dP_hot_max=0.005; dP_cold_max=0.031
        T_out_hot_max=560.0; arrangement="counter"; reason=""
    def _fake_load(path): captured["path"]=path; return ["case1"]
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
    assert captured["arr"]=="counter" and captured["rho"]==7900.0
    assert captured["jobs"] == (1 if frozen else -1)
    assert captured["ks"]==16.0   # 默认 304SS 热导率传入后端
    assert captured["pm"]=="mean" # UI 默认物性模型 = 均温
    assert captured["height"] is None   # 默认方形 (未勾固定高度迎风)
    assert len(received)==1
    feas, best = received[0]["feasible"], received[0]["best"]
    assert best.topo=="Diamond" and len(feas)==1


@pytest.mark.parametrize('stage', ['enumeration', 'refinement'])
def test_cancel_retains_completed_candidates_from_current_stage(make_window, monkeypatch, stage):
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
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda p: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.select.enumerate_select', enumeration)
    monkeypatch.setattr('sjtu_tpmshx.applications.design.optimize.warm_start_joint', refinement)
    params = _gather_inputs(make_window())
    params['refine'] = True
    worker = _make_worker_class()(params)
    received = []
    worker.finished_with_result.connect(received.append)
    worker.run()
    result, = received
    assert result['all'] == result['feasible'] == [d]
    assert result['best'] is d
    assert result['partial'] and result['termination_reason'] == 'cancelled'


def test_new_run_clears_stale_results_then_publishes_partial_current_result(make_window, monkeypatch):
    import threading
    from sjtu_tpmshx.applications.design.sizing import Design
    from sjtu_tpmshx.applications.design.select import SelectionCancelled
    from tests.python.gui_worker_support import _wait_for
    from sjtu_tpmshx.applications.gui.ui import quick_design_panel as panel
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
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda p: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.select.enumerate_select', enumeration)
    w = make_window()
    w._qd_last = {'old': True}
    w._qd_table.setRowCount(1)
    w._qd_energy_table.setRowCount(1)
    panel.run_quick_design(w)
    try:
        assert w._qd_last is None and w._qd_table.rowCount() == 0
        assert w._qd_energy_table.rowCount() == 0
        assert '单进程串行' in w._qd_status.text()
    finally:
        release.set()
    _wait_for(lambda: w._qd_worker is None)
    assert w._qd_last['all'] == [d] and w._qd_last['partial']
    assert '已取消' in w._qd_status.text() and '不代表完整搜索最优' in w._qd_status.text()
    assert w._qd_table.rowCount() == 1
    assert w._qd_table.item(0, 12).text().startswith('已完成候选内')
    assert w._qd_energy_table.rowCount() == 1
    assert w._qd_energy_table.item(0, 1).text() == '3'

def test_gather_inputs_rect_height(make_window):
    w = make_window("auto")
    w.chk_qd_rect.setChecked(True)
    w.le_qd_height.setText("750")
    p = _gather_inputs(w)
    assert abs(p["height"] - 0.750) < 1e-12   # mm→m
    assert _gather_inputs(make_window("auto"))["height"] is None

def test_worker_emits_error_on_exception(make_window):
    w=make_window("auto"); worker=_make_worker_class()(_gather_inputs(w))
    errs=[]; worker.error_signal.connect(lambda m: errs.append(m))
    def _boom(path): raise RuntimeError("bad file")
    with patch("sjtu_tpmshx.applications.design.cases.load_cases", _boom):
        worker.run()
    assert len(errs)==1 and "RuntimeError" in errs[0]


def test_run_quick_design_malformed_node_list_gives_feedback_not_crash(make_window):
    """U3 (audit 2026-06-28): a non-numeric node list (le_qd_l) must NOT let
    ValueError escape the Run slot — Qt swallows it to stderr, leaving a dead
    '运行设计' button with no _qd_status. The handler must catch the parse error
    and surface it, and must not launch a worker."""
    w = make_window("auto")
    w.le_qd_l.setText("4,5,oops,7")     # malformed token in the node list
    w._qd_worker = None
    run_quick_design(w)               # must NOT raise
    assert ("解析" in w._qd_status.text() or "失败" in w._qd_status.text()), \
        f"no parse-failure feedback; status was {w._qd_status.text()!r}"
    assert getattr(w, "_qd_worker", None) is None, "worker launched on bad input"


def test_run_quick_design_malformed_fixed_cell_gives_feedback(make_window):
    """Bad active fixed-cell input is reported before launching a worker."""
    w = make_window("fixed")
    w.le_qd_cell_l.setText("7mm")        # malformed fixed-cell length
    w._qd_worker = None
    run_quick_design(w)               # must NOT raise
    assert ("解析" in w._qd_status.text() or "失败" in w._qd_status.text())


def test_thread_result_warnings_reach_table(make_window, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.applications.design.sizing import Design
    from sjtu_tpmshx.applications.gui.ui import quick_design_panel as panel
    d = Design(True, topo='Diamond', l=5., t=.5, s=.1, Lx=.1,
               percase=[dict(case=2, warnings=['final-source'])])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda path: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.sizing.size_fixed_cell', lambda *a, **kw: d)
    worker = _make_worker_class()(_gather_inputs(make_window('fixed')))
    received = []
    worker.finished_with_result.connect(received.append)
    worker.start()
    assert worker.wait(5000)
    QApplication.processEvents()
    assert received[0]['best'] is d
    assert received[0]['all'][0].percase == d.percase
    w = make_window("fixed")
    panel._fill_table(w, received[0]['feasible'])
    cell = w._qd_table.item(0, 11)
    assert cell.text() == '有警告'
    assert cell.toolTip() == '[工况 2] final-source'
    from sjtu_tpmshx.applications.gui.ui.theme import get_theme
    assert cell.foreground().color().name() == get_theme()['warn'].lower()


def test_completed_energy_diagnostics_include_all_cases_without_changing_feasibility(make_window, monkeypatch):
    from sjtu_tpmshx.applications.design.sizing import Design
    from tests.python.gui_worker_support import _wait_for
    from sjtu_tpmshx.applications.gui.ui import quick_design_panel as panel

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
    monkeypatch.setattr('sjtu_tpmshx.applications.design.cases.load_cases', lambda path: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.applications.design.select.enumerate_select',
                        lambda *a, **kw: (results, feasible))
    window = make_window()
    panel.run_quick_design(window)
    _wait_for(lambda: window._qd_worker is None)

    assert window._qd_last['all'] == results
    assert window._qd_last['feasible'] == [feasible] and window._qd_last['best'] is feasible
    assert window._qd_table.rowCount() == 1
    assert window._qd_table.columnCount() == 13
    table = window._qd_energy_table
    rows = [[table.item(i, j).text() for j in range(table.columnCount())]
            for i in range(table.rowCount())]
    assert rows == [
        ['Diamond_l5_t0.5', 'hot', '100', '75', '25', 'available', '', 'True', '是', ''],
        ['Diamond_l5_t0.5', 'zero', '0', '0', '—', 'insufficient_data',
         'missing source diagnostic', 'True', '是', ''],
        ['Gyroid_l6_t0.4', 'legacy', '7', '—', '—', '未提供',
         '未提供能量不平衡诊断', 'False', '否', 'not-converged@final'],
    ]
    assert feasible.percase[0]['energy_imbalance_rel'] == .25


@pytest.mark.parametrize('mode,hidden,active', [
    ('auto', 'le_qd_cell_l', 'le_qd_l'),
    ('fixed', 'le_qd_l', 'le_qd_cell_l'),
])
def test_only_active_design_parameters_are_parsed(make_window, mode, hidden, active):
    w = make_window(mode)
    getattr(w, hidden).setText('invalid')
    params = _gather_inputs(w)
    if mode == 'auto':
        assert params['nodes']['l'] == [5., 6., 7., 8.]
        assert 'cell' not in params
    else:
        assert params['cell'] == ('Diamond', 7., .5)
        assert 'nodes' not in params
    getattr(w, active).setText('invalid')
    with pytest.raises(ValueError):
        _gather_inputs(w)


@pytest.mark.parametrize('stage', ['enumeration', 'refinement'])
def test_failure_keeps_completed_candidates_error_and_export(monkeypatch, tmp_path, stage):
    from dataclasses import replace
    from openpyxl import load_workbook
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog, QPushButton
    from sjtu_tpmshx.applications.design import optimize, select
    from sjtu_tpmshx.applications.design.sizing import Design
    from tests.python.gui_worker_support import _wait_for
    from sjtu_tpmshx.applications.gui.ui import quick_design_panel as panel
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
    worker_class = panel._make_worker_class()

    def make_worker(params, *, control):
        worker = worker_class(params, control=control)
        worker.n_jobs = 1
        # Attach before start(), including when a controlled candidate is fast.
        worker.finished_with_result.connect(lambda value: events.append(('result', value)))
        worker.error_signal.connect(lambda value: events.append(('error', value)))
        worker.cancelled.connect(lambda: events.append(('cancelled', None)))
        return worker

    monkeypatch.setattr(panel, '_make_worker_class', lambda: make_worker)
    dialog = panel.build_quick_design_dialog()
    try:
        dialog.le_qd_file.setText(str(inputs))
        dialog.le_qd_topo.setText('Diamond')
        dialog.le_qd_l.setText('4,5,6,7' if stage == 'enumeration' else '4,5')
        dialog.le_qd_t.setText('0.4')
        dialog.chk_qd_refine.setChecked(stage == 'refinement')
        dialog._qd_last = {'old': True}
        dialog._qd_table.setRowCount(1)
        dialog._qd_energy_table.setRowCount(1)
        QTest.mouseClick(dialog._qd_run_btn, Qt.MouseButton.LeftButton)
        assert dialog._qd_last is None and dialog._qd_table.rowCount() == 0
        assert dialog._qd_energy_table.rowCount() == 0
        _wait_for(lambda: dialog._qd_worker is None)
        assert calls == ([4., 5., 6.] if stage == 'enumeration' else [4., 5.])
        assert [value for kind, value in events if kind == 'error'] == [
            f'ValueError: injected {stage} failure']
        assert [kind for kind, _ in events] == ['result', 'error'], events
        result = dialog._qd_last
        assert result['all'] == completed and result['feasible'] == [feasible]
        assert result['best'] is feasible
        assert result['partial'] and result['termination_reason'] == 'failed'
        status = dialog._qd_status.text()
        assert str(error) in status and '保留 2' in status
        assert '不代表完整搜索最优' in status and '已取消' not in status
        assert dialog._qd_table.rowCount() == 1
        assert dialog._qd_table.item(0, 12).text().startswith('已完成候选内')
        assert dialog._qd_energy_table.rowCount() == 2
        assert [dialog._qd_energy_table.item(i, 4).text() for i in range(2)] == ['20', '20']
        assert [dialog._qd_energy_table.item(i, 8).text() for i in range(2)] == ['是', '否']
        assert dialog._qd_run_btn.isEnabled() and not dialog._qd_cancel_btn.isEnabled()

        output = tmp_path / 'failed-partial.xlsx'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(output), ''))
        export = next(button for button in dialog.findChildren(QPushButton)
                      if button.text() == '导出 xlsx')
        QTest.mouseClick(export, Qt.MouseButton.LeftButton)
        assert output.exists(), dialog._qd_status.text()
        assert '失败' in dialog._qd_status.text() and '已取消' not in dialog._qd_status.text()
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
            for row in rows['工况明细']:
                assert row['热侧出口_K'] == 400. and row['换热量_kW'] == 10.
                assert row['警告'] == 'retained source warning'
            assert {row['数值收敛'] for row in rows['工况明细']} == {True, False}
        finally:
            workbook.close()
    finally:
        if getattr(dialog, '_qd_worker', None) is not None:
            dialog._qd_worker.requestInterruption()
            _wait_for(lambda: dialog._qd_worker is None)
        dialog.close()
