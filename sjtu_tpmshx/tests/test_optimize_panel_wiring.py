"""End-to-end UI wiring smoke for the Optimize tab.

Verifies the path:
  user clicks Optimize button
    → window._run_optimize(self)
    → ui.optimize_panel.run_optimize(window)
    → _gather_cfg(window) reads UI line-edits
    → _make_worker_class()(cfg, n_init, n_iter, q_batch, seed, save_dir)
    → worker.run() invokes run_qnehvi(..., n_jobs=q_batch)

We don't launch a real Qt window; we build a minimal duck-typed `window`
with the line-edits + combos that _gather_cfg reads. The actual BO is
NOT executed — we instead patch run_qnehvi to capture its kwargs and
return a synthetic Pareto, so the test runs in <1 s.
"""
from __future__ import annotations

import types
from unittest.mock import patch

import numpy as np
import pytest

from PySide6.QtWidgets import QLineEdit, QComboBox

from sjtu_tpmshx.ui.optimize_panel import _gather_cfg, _make_worker_class


# ─── Fake window builder ───────────────────────────────────────────


def _le(text: str) -> QLineEdit:
    le = QLineEdit()
    le.setText(text)
    return le


def _combo(items, default_idx=0) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setCurrentIndex(default_idx)
    return c


def _make_window():
    """Minimal duck-typed window mirroring the keys _gather_cfg expects."""
    w = types.SimpleNamespace()
    # Geometry (Shanghai HX)
    w.le_L     = _le('0.182')
    w.le_H     = _le('0.042')
    w.le_Lz    = _le('0.042')
    # TPMS seed values (not directly used as cfg keys; informational)
    w.le_Lcell = _le('6.0')
    w.le_t     = _le('0.4')
    w.le_ks    = _le('16.0')
    w.le_uA    = _le('5.0')
    w.le_uB    = _le('5.0')
    w.le_PinA  = _le('192362.0')
    w.le_PinB  = _le('101325.0')
    w.le_TinA  = _le('422.0')
    w.le_TinB  = _le('322.0')
    w.le_rho_s = _le('7900.0')
    w.combo_tpms = _combo(['Diamond', 'Gyroid'], default_idx=0)
    # Fluid combos read by _gather_cfg
    w.combo_fluidA = _combo(['Air', 'Water'], default_idx=0)
    w.combo_fluidB = _combo(['Air', 'Water'], default_idx=1)
    # Optional checkbox + temp converter (skip — _gather_cfg has guards)
    return w


# ─── Tests ─────────────────────────────────────────────────────────


def test_gather_cfg_reads_geometry_from_UI():
    """_gather_cfg must read le_L/le_H/le_Lz into L_domain/H_domain/Lz."""
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['L_domain'] == pytest.approx(0.182)
    assert cfg['H_domain'] == pytest.approx(0.042)
    assert cfg['Lz']       == pytest.approx(0.042)


def test_gather_cfg_reads_velocities_and_pressures():
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['u_A']  == pytest.approx(5.0)
    assert cfg['u_B']  == pytest.approx(5.0)
    assert cfg['P_inA'] == pytest.approx(192362.0)
    assert cfg['P_inB'] == pytest.approx(101325.0)


def test_gather_cfg_reads_solid_density_not_default():
    """Regression for the v1 bug where rho_s was silently dropped and
    optimizer used 2700 (Al) regardless of UI input."""
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['rho_s'] == pytest.approx(7900.0)


def test_gather_cfg_reads_tpms_type():
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['tpms_type'] == 'Diamond'


def test_worker_class_constructible_with_cfg():
    """Worker must instantiate without exception given the gathered cfg."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=4, n_iter=1, q_batch=2,
                    seed=42, save_dir='opt_runs/_test_worker_smoke')
    assert worker.cfg is cfg
    assert worker.n_init == 4
    assert worker.n_iter == 1
    assert worker.q_batch == 2


def test_worker_passes_n_jobs_to_run_qnehvi():
    """Phase 1 wiring fix — worker.run() must pass n_jobs to enable inner
    joblib parallelism (was missing pre-2026-05-09; UI ran sequentially)."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=4,
                    seed=0, save_dir='opt_runs/_test_n_jobs_smoke')

    captured: dict = {}

    def _fake_run_qnehvi(**kwargs):
        captured.update(kwargs)
        # Synthetic 1-pt Pareto so finished_with_result has something
        return {
            'X':         np.zeros((1, 16)),
            'F':         np.array([[-8000.0, 12000.0]]),
            'history_X': np.zeros((1, 16)),
            'history_F': np.array([[-8000.0, 12000.0]]),
            'n_evals':   2,
            'save_dir':  worker.save_dir,
        }

    with patch('sjtu_tpmshx.optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert 'n_jobs' in captured, \
        "Worker did not pass n_jobs to run_qnehvi — UI inner parallel disabled"
    assert captured['n_jobs'] >= 1
    assert captured['n_jobs'] <= captured['q_batch']
    assert captured['q_batch'] == 4


def test_worker_n_jobs_capped_at_q_batch():
    """If cfg sets n_jobs > q_batch, the worker must clamp down (joblib
    can't usefully parallelize more than the batch size)."""
    w = _make_window()
    cfg = _gather_cfg(w)
    cfg['n_jobs'] = 32  # absurdly high
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_n_jobs_cap')

    captured: dict = {}

    def _fake_run_qnehvi(**kwargs):
        captured.update(kwargs)
        return {
            'X': np.zeros((0, 16)), 'F': np.zeros((0, 2)),
            'history_X': np.zeros((0, 16)), 'history_F': np.zeros((0, 2)),
            'n_evals': 0, 'save_dir': worker.save_dir,
        }

    with patch('sjtu_tpmshx.optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert captured['n_jobs'] == 2  # capped to q_batch


def test_worker_emits_finished_signal_on_success():
    """Run() must emit finished_with_result on the synthetic Pareto."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_finish_smoke')

    received: list = []
    worker.finished_with_result.connect(lambda res: received.append(res))

    def _fake_run_qnehvi(**_kw):
        return {
            'X':         np.array([[6.0]*16]),
            'F':         np.array([[-7500.0, 11000.0]]),
            'history_X': np.array([[6.0]*16]),
            'history_F': np.array([[-7500.0, 11000.0]]),
            'n_evals':   2,
            'save_dir':  worker.save_dir,
        }

    with patch('sjtu_tpmshx.optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert len(received) == 1
    assert received[0]['n_evals'] == 2
    assert len(received[0]['X']) == 1


def test_worker_emits_error_signal_on_exception():
    """run_qnehvi raising must NOT crash the worker — must emit error_signal."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_error_smoke')

    errors: list = []
    worker.error_signal.connect(lambda msg: errors.append(msg))

    def _fake_raise(**_kw):
        raise RuntimeError("synthetic BO crash")

    with patch('sjtu_tpmshx.optimization.optimizer_qnehvi.run_qnehvi', _fake_raise):
        worker.run()

    assert len(errors) == 1
    assert "RuntimeError" in errors[0]
    assert "synthetic BO crash" in errors[0]


@pytest.mark.parametrize('reason,label,count', [
    ('completed', '完成', 4), ('cancelled', '已取消', 1),
    ('plateau', '平台期提前结束', 2), ('error', 'ERROR', 0),
])
def test_terminal_state_and_progress_survive_until_thread_exit(monkeypatch, tmp_path,
                                                              reason, label, count):
    import threading
    from PySide6.QtWidgets import QLabel, QPushButton, QProgressBar
    from sjtu_tpmshx.ui import optimize_panel as panel
    from sjtu_tpmshx.tests.test_worker_result_handoff import _wait_for
    w = _make_window()
    w.combo_fluidB.setCurrentIndex(0)  # Current screening supports air/air.
    w._opt_status, w._opt_kpi_gen = QLabel(), QLabel()
    w._opt_btn, w._opt_cancel_btn = QPushButton(), QPushButton()
    w._opt_progress = QProgressBar()
    release = threading.Event()
    Worker = _make_worker_class()
    original_run = Worker.run
    def held_run(worker):
        original_run(worker)
        assert release.wait(10)
    monkeypatch.setattr(Worker, 'run', held_run)
    monkeypatch.setattr(panel, '_make_worker_class', lambda: Worker)
    monkeypatch.setattr(panel, '_show_qnehvi_param_dialog', lambda *a: dict(
        n_init=4, n_iter=0, q_batch=2, seed=1, n_rho_loops=3))
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    def result(**kwargs):
        if reason == 'error':
            raise RuntimeError('test failure')
        return dict(X=np.zeros((0, 16)), F=np.zeros((0, 2)), n_evals=count,
                    save_dir=str(tmp_path), termination_reason=reason)
    monkeypatch.setattr('sjtu_tpmshx.optimization.optimizer_qnehvi.run_qnehvi', result)
    panel.run_optimize(w)
    worker = w._opt_worker
    try:
        _wait_for(lambda: label in w._opt_status.text())
        assert label in w._opt_kpi_gen.text()
        assert w._opt_progress.value() == count * 25
        assert w._opt_worker is worker and worker.isRunning()
        assert not w._opt_btn.isEnabled()
    finally:
        release.set()
    _wait_for(lambda: w._opt_worker is None)
    assert w._opt_btn.isEnabled() and not w._opt_cancel_btn.isEnabled()


# ─── M0 (2026-07-09): search space, optimizer-budget hook, 3D routing ─


def _add_space_widgets(w, L_min=4.0, L_max=8.0, t_min=0.3, t_max=0.5,
                       grid=(4, 4), sym=True):
    """Attach the 搜索空间 card's widget dict as _gather_cfg reads it."""
    from PySide6.QtWidgets import QDoubleSpinBox, QCheckBox

    def _ds(lo, hi, val):
        d = QDoubleSpinBox()
        d.setRange(lo, hi); d.setDecimals(2); d.setValue(val)
        return d

    cb = QComboBox()
    cb.addItem("4 × 4（16 维）", (4, 4))
    cb.addItem("6 × 6（36 维）", (6, 6))
    cb.setCurrentIndex(0 if grid == (4, 4) else 1)
    chk = QCheckBox(); chk.setChecked(sym)
    w._opt_space_params = {
        'L_min': _ds(0.0, 100.0, L_min), 'L_max': _ds(0.0, 100.0, L_max),
        't_min': _ds(0.0, 100.0, t_min), 't_max': _ds(0.0, 100.0, t_max),
        'ctrl_grid': cb, 'symmetric_y': chk,
    }
    return w


def test_gather_cfg_reads_search_space_widgets():
    w = _add_space_widgets(_make_window(), L_min=5.0, L_max=7.0,
                           t_min=0.35, t_max=0.45, grid=(6, 6), sym=False)
    cfg = _gather_cfg(w)
    assert cfg['L_bounds'] == pytest.approx((5.0, 7.0))
    assert cfg['t_bounds'] == pytest.approx((0.35, 0.45))
    assert (cfg['n_ctrl_x'], cfg['n_ctrl_y']) == (6, 6)
    assert cfg['symmetric_y'] is False


def test_gather_cfg_clamps_bounds_to_training_hull():
    """User-entered bounds outside the DF/Nu hull must be clamped — out-of-
    hull rankings are extrapolation."""
    from sjtu_tpmshx.df_surrogate._domain import TRAIN_L, TRAIN_T
    w = _add_space_widgets(_make_window(), L_min=1.0, L_max=50.0,
                           t_min=0.01, t_max=5.0)
    cfg = _gather_cfg(w)
    assert cfg['L_bounds'] == pytest.approx(tuple(TRAIN_L))
    assert cfg['t_bounds'] == pytest.approx(tuple(TRAIN_T))


def test_gather_cfg_degenerate_range_is_rejected():
    w = _add_space_widgets(_make_window(), L_min=6.0, L_max=6.0)
    with pytest.raises(ValueError, match='lower < upper'):
        _gather_cfg(w)


def test_gather_cfg_optimizer_config_hook():
    """R3 wiring: a typed OptimizerConfig on window._optimizer_cfg must reach
    the evaluator dict; absent → dimension defaults unchanged."""
    from sjtu_tpmshx.domain.compute_config import OptimizerConfig
    from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG as EVAL_DEFAULT

    w = _make_window()
    cfg_plain = _gather_cfg(w)
    assert cfg_plain['max_iter_simple'] == EVAL_DEFAULT['max_iter_simple']
    assert cfg_plain['tol_simple'] == EVAL_DEFAULT['tol_simple']

    w._optimizer_cfg = OptimizerConfig(max_iter_simple=1234, tol_simple=5e-3,
                                       outer_tol_K=0.25, max_outer_ltne=6,
                                       alpha_T=0.5)
    cfg = _gather_cfg(w)
    assert cfg['max_iter_simple'] == 1234
    assert cfg['tol_simple'] == pytest.approx(5e-3)
    assert cfg['tol_energy'] == pytest.approx(0.25)
    assert cfg['max_outer_3d'] == 6
    assert cfg['alpha_outer'] == pytest.approx(0.5)


def test_gather_cfg_3d_base_keeps_fast_mode_budget():
    """3D launch passes DEFAULT_CONFIG_3D as base — the 3D fast-mode budget
    (max_iter_simple 300 / tol 1e-2) must survive, not be stomped by the 2D
    defaults (5000 / 1e-3)."""
    from sjtu_tpmshx.optimization.evaluator_3d import DEFAULT_CONFIG_3D
    w = _make_window()
    cfg = _gather_cfg(w, base=DEFAULT_CONFIG_3D)
    assert cfg['max_iter_simple'] == DEFAULT_CONFIG_3D['max_iter_simple']
    assert cfg['tol_simple'] == pytest.approx(DEFAULT_CONFIG_3D['tol_simple'])
    assert 'Nx_3d' in cfg and 'Lz' in cfg
    # widget reads still win: geometry came from the line-edits
    assert cfg['L_domain'] == pytest.approx(0.182)


def test_is_3d_mode_follows_combo_dim():
    from sjtu_tpmshx.ui.optimize_panel import _is_3d_mode
    w = _make_window()
    assert _is_3d_mode(w) is False            # no combo at all
    w.combo_dim = _combo(['2D', '3D'], default_idx=0)
    assert _is_3d_mode(w) is False
    w.combo_dim.setCurrentIndex(1)
    assert _is_3d_mode(w) is True


def test_worker_passes_evaluator_fn_to_run_qnehvi():
    """3D routing: the worker must forward evaluator_fn so run_qnehvi drives
    evaluate_design_3d instead of the 2D default."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    _sentinel = object()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_evalfn_smoke',
                    evaluator_fn=_sentinel)

    captured: dict = {}

    def _fake_run_qnehvi(**kwargs):
        captured.update(kwargs)
        return {
            'X': np.zeros((0, 16)), 'F': np.zeros((0, 2)),
            'history_X': np.zeros((0, 16)), 'history_F': np.zeros((0, 2)),
            'n_evals': 0, 'save_dir': worker.save_dir,
        }

    with patch('sjtu_tpmshx.optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert captured.get('evaluator_fn') is _sentinel
