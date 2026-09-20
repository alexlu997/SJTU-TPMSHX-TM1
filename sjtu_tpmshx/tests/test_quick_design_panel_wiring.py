from __future__ import annotations
import types
import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QLineEdit, QComboBox, QCheckBox, QLabel

from sjtu_tpmshx.ui.quick_design_panel import (
    _gather_inputs, _make_worker_class, run_quick_design,
)

def _le(t): le=QLineEdit(); le.setText(t); return le
def _combo(items,i=0): c=QComboBox(); c.addItems(items); c.setCurrentIndex(i); return c

def _make_window(mode="auto"):
    w = types.SimpleNamespace()
    w.le_qd_file = _le("spec.xlsx")
    w.combo_qd_mode = _combo(["auto","fixed"], 0 if mode=="auto" else 1)
    w.combo_qd_arr = _combo(["counter","cross"], 0)
    w.le_qd_rho = _le("7900")
    w.le_qd_topo = _le("Diamond,Gyroid")
    w.le_qd_l = _le("5,6,7,8")
    w.le_qd_t = _le("0.4,0.5")
    w.chk_qd_refine = QCheckBox(); w.chk_qd_refine.setChecked(False)
    w.combo_qd_cell_topo = _combo(["Diamond","Gyroid"], 0)
    w.le_qd_cell_l = _le("7")
    w.le_qd_cell_t = _le("0.5")
    return w

def test_gather_inputs_auto():
    p = _gather_inputs(_make_window("auto"))
    assert p["file"] == "spec.xlsx"
    assert p["mode"] == "auto" and p["arrangement"] == "counter"
    assert p["rho_s"] == 7900.0
    assert p["nodes"] == {"topo":["Diamond","Gyroid"],"l":[5.0,6.0,7.0,8.0],"t":[0.4,0.5]}
    assert p["refine"] is False

def test_gather_inputs_fixed():
    p = _gather_inputs(_make_window("fixed"))
    assert p["mode"] == "fixed"
    assert p["cell"] == ("Diamond", 7.0, 0.5)

@pytest.mark.parametrize('frozen', [False, True])
def test_worker_auto_calls_backend_and_emits(monkeypatch, frozen):
    monkeypatch.setattr('sys.frozen', frozen, raising=False)
    w = _make_window("auto"); p = _gather_inputs(w)
    Worker = _make_worker_class()
    worker = Worker(p)
    captured = {}
    class _D:
        feasible=True; topo="Diamond"; l=5.0; t=0.5; s=0.133; Lx=0.011
        V=2.02e-4; weight=0.6; dP_hot_max=0.005; dP_cold_max=0.031
        T_out_hot_max=560.0; arrangement="counter"; reason=""
    def _fake_load(path): captured["path"]=path; return ["case1"]
    def _fake_enum(cases, arrangement, nodes, rho_s, n_jobs=1, k_s=16.0,
                   prop_model="const", height=None, control=None):
        captured.update(arr=arrangement, nodes=nodes, rho=rho_s, jobs=n_jobs,
                        ks=k_s, pm=prop_model, height=height)
        d=_D(); return [d], d
    received=[]
    worker.finished_with_result.connect(lambda r: received.append(r))
    with patch("sjtu_tpmshx.design.cases.load_cases", _fake_load), \
         patch("sjtu_tpmshx.design.select.enumerate_select", _fake_enum):
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
def test_cancel_retains_completed_candidates_from_current_stage(monkeypatch, stage):
    from sjtu_tpmshx.design.sizing import Design
    from sjtu_tpmshx.design.select import SelectionCancelled
    from sjtu_tpmshx.domain.cancellation import CancelledError
    d = Design(True, topo='Diamond', l=5., t=.4, V=.01)
    def enumeration(*args, **kwargs):
        if stage == 'enumeration':
            raise SelectionCancelled([d])
        return [d], d
    def refinement(*args, **kwargs):
        raise CancelledError('cancelled during refinement')
    monkeypatch.setattr('sjtu_tpmshx.design.cases.load_cases', lambda p: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.design.select.enumerate_select', enumeration)
    monkeypatch.setattr('sjtu_tpmshx.design.optimize.warm_start_joint', refinement)
    params = _gather_inputs(_make_window())
    params['refine'] = True
    worker = _make_worker_class()(params)
    received = []
    worker.finished_with_result.connect(received.append)
    worker.run()
    result, = received
    assert result['all'] == result['feasible'] == [d]
    assert result['best'] is d
    assert result['partial'] and result['termination_reason'] == 'cancelled'


def test_new_run_clears_stale_results_then_publishes_partial_current_result(monkeypatch):
    import threading
    from PySide6.QtWidgets import QTableWidget
    from sjtu_tpmshx.design.sizing import Design
    from sjtu_tpmshx.design.select import SelectionCancelled
    from sjtu_tpmshx.tests.test_worker_result_handoff import _wait_for
    from sjtu_tpmshx.ui import quick_design_panel as panel
    monkeypatch.setattr('sys.frozen', True, raising=False)
    release = threading.Event()
    d = Design(True, topo='Gyroid', l=5., t=.4, V=.01)
    def enumeration(*args, **kwargs):
        assert kwargs['n_jobs'] == 1
        assert release.wait(10)
        raise SelectionCancelled([d])
    monkeypatch.setattr('sjtu_tpmshx.design.cases.load_cases', lambda p: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.design.select.enumerate_select', enumeration)
    w = _make_window()
    w._qd_last = {'old': True}
    w._qd_table = QTableWidget(1, 1)
    w._qd_status = QLabel()
    panel.run_quick_design(w)
    try:
        assert w._qd_last is None and w._qd_table.rowCount() == 0
        assert '单进程串行' in w._qd_status.text()
    finally:
        release.set()
    _wait_for(lambda: w._qd_worker is None)
    assert w._qd_last['all'] == [d] and w._qd_last['partial']
    assert '已取消' in w._qd_status.text() and '不代表完整搜索最优' in w._qd_status.text()
    assert w._qd_table.rowCount() == 1
    assert w._qd_table.item(0, 12).text().startswith('已完成候选内')

def test_gather_inputs_rect_height():
    w = _make_window("auto")
    w.chk_qd_rect = QCheckBox(); w.chk_qd_rect.setChecked(True)
    w.le_qd_height = _le("750")
    p = _gather_inputs(w)
    assert abs(p["height"] - 0.750) < 1e-12   # mm→m
    # 默认 (无 chk_qd_rect 控件) → 方形
    assert _gather_inputs(_make_window("auto"))["height"] is None

def test_worker_emits_error_on_exception():
    w=_make_window("auto"); worker=_make_worker_class()(_gather_inputs(w))
    errs=[]; worker.error_signal.connect(lambda m: errs.append(m))
    def _boom(path): raise RuntimeError("bad file")
    with patch("sjtu_tpmshx.design.cases.load_cases", _boom):
        worker.run()
    assert len(errs)==1 and "RuntimeError" in errs[0]


def test_run_quick_design_malformed_node_list_gives_feedback_not_crash():
    """U3 (audit 2026-06-28): a non-numeric node list (le_qd_l) must NOT let
    ValueError escape the Run slot — Qt swallows it to stderr, leaving a dead
    '运行设计' button with no _qd_status. The handler must catch the parse error
    and surface it, and must not launch a worker."""
    w = _make_window("auto")
    w.le_qd_l = _le("4,5,oops,7")     # malformed token in the node list
    w._qd_status = QLabel()
    w._qd_worker = None
    run_quick_design(w)               # must NOT raise
    assert ("解析" in w._qd_status.text() or "失败" in w._qd_status.text()), \
        f"no parse-failure feedback; status was {w._qd_status.text()!r}"
    assert getattr(w, "_qd_worker", None) is None, "worker launched on bad input"


def test_run_quick_design_malformed_fixed_cell_gives_feedback():
    """U3: the fixed-cell tuple is parsed unconditionally (even in auto mode),
    so bad le_qd_cell_l text must also be caught, not crash the slot."""
    w = _make_window("auto")
    w.le_qd_cell_l = _le("7mm")        # malformed fixed-cell length
    w._qd_status = QLabel()
    w._qd_worker = None
    run_quick_design(w)               # must NOT raise
    assert ("解析" in w._qd_status.text() or "失败" in w._qd_status.text())


def test_thread_result_warnings_reach_table_and_fallback(monkeypatch):
    from PySide6.QtWidgets import QApplication, QTableWidget
    from sjtu_tpmshx.design.sizing import Design
    from sjtu_tpmshx.ui import quick_design_panel as panel
    d = Design(True, topo='Diamond', l=5., t=.5, s=.1, Lx=.1,
               percase=[dict(case=2, warnings=['final-source'])])
    monkeypatch.setattr('sjtu_tpmshx.design.cases.load_cases', lambda path: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.design.sizing.size_fixed_cell', lambda *a, **kw: d)
    worker = _make_worker_class()(_gather_inputs(_make_window('fixed')))
    received = []
    worker.finished_with_result.connect(received.append)
    worker.start()
    assert worker.wait(5000)
    QApplication.processEvents()
    assert received[0]['best'] is d
    assert received[0]['all'][0].percase == d.percase
    w = types.SimpleNamespace(_qd_table=QTableWidget())
    panel._fill_table(w, received[0]['feasible'], received[0]['best'])
    cell = w._qd_table.item(0, 11)
    assert cell.text() == '有警告'
    assert cell.toolTip() == '[工况 2] final-source'
    from sjtu_tpmshx.ui.theme import get_theme
    assert cell.foreground().color().name() == get_theme()['warn'].lower()
    logs = []
    monkeypatch.setattr(panel._log, 'info', logs.append)
    panel._fill_table(types.SimpleNamespace(), [d], d)
    assert '[工况 2] final-source' in logs
