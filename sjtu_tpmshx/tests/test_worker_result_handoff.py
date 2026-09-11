"""Real Qt pool/window regressions; only expensive numerical work is stubbed."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from sjtu_tpmshx.controllers.compute_orchestrator import ComputeOrchestrator
from sjtu_tpmshx.controllers.compute_pipeline import (
    CancelledError, Pipeline2D, Pipeline3D,
)
from sjtu_tpmshx.domain.compute_config import ComputeConfig, SolverConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult


def _wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.001)
    assert predicate(), 'Qt worker/lifecycle did not finish'


@pytest.fixture
def win(tmp_path, monkeypatch):
    from sjtu_tpmshx.controllers.session_manager import SessionManager
    from sjtu_tpmshx.main import Main_Menu

    original_init = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
                        lambda self, parent=None: original_init(
                            self, base_dir=tmp_path, parent=parent))
    monkeypatch.setenv('SJTU_TPMSHX_DISABLE_3D_PANEL', '1')
    window = Main_Menu()
    window._K_ffA = window._K_ffB = 1e-8
    monkeypatch.setattr(window, '_validate_inputs_preflight', lambda: True)
    monkeypatch.setattr(window, '_preflight_grid', lambda: True)
    monkeypatch.setattr(window, '_preflight_3d', lambda: (True, 8, '2×2×2'))
    monkeypatch.setattr(window, '_finalize_plots', lambda: None)
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                        lambda _window: False)
    window._test_error_dialogs = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *args: window._test_error_dialogs.append(args))
    yield window
    if isValid(window):
        window.compute.cancel()
        _wait_for(window.compute.is_idle)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _configure(win, monkeypatch, mode):
    cfg = ComputeConfig(solver=SolverConfig(Nz=2 if mode == '3d' else 1))
    win.combo_shape.setCurrentIndex(0)
    win.combo_dim.setCurrentIndex(1 if mode == '3d' else 0)
    monkeypatch.setattr('sjtu_tpmshx.ui.window_config.config_from_window',
                        lambda *args, **kwargs: cfg)
    return cfg


def test_2d_tout_displays_result_scalars_across_units_and_direction_drafts(win):
    win._temp_unit = 'K'
    result = ComputeResult(Q_W=123., T_out_A_K=341.25, T_out_B_K=312.75,
        fields={'Ta': np.arange(6.).reshape(2, 3) + 400.,
                'Tb': np.arange(6.).reshape(2, 3) + 300.},
        diagnostics={'mode': '2d'})
    win.write_result(result)
    assert win._tout_K_cache == (341.25, 312.75)
    for direction in range(4):
        win.combo_dirA.setCurrentIndex(direction)
        win.combo_dirB.setCurrentIndex(3-direction)
        win._update_tout(-1)
        assert float(win._r_ToutA.text()) == 341.25
        assert float(win._r_ToutB.text()) == 312.75
    win._toggle_temp_unit()
    win._update_tout(0)
    assert float(win._r_ToutA.text()) == pytest.approx(68.10)
    assert float(win._r_ToutB.text()) == pytest.approx(39.60)
    win._toggle_temp_unit()
    assert float(win._r_ToutA.text()) == 341.25
    assert float(win._r_ToutB.text()) == 312.75
    assert win._compute_results['Q_total'] == result.Q_W == 123.


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('df_extrap', [False, True])
def test_real_source_warnings_do_not_set_df_ui_flag(win, monkeypatch, mode, df_extrap):
    from sjtu_tpmshx.df_surrogate.surrogate_domain import check_surrogate_domain_at_point
    from sjtu_tpmshx.models.nu_correlations import nu_water_topo
    from sjtu_tpmshx.models.tpms_props import air_cp
    from sjtu_tpmshx.tests.test_compute_pipeline import _RecordingPipeline

    # Exercise the existing geometry reason carrier, not an out-of-domain solve.
    df_reasons = check_surrogate_domain_at_point(
        'Gyroid', 9 if df_extrap else 7, 0.4, 16, 5, 350, allow_extrap=True)
    pipe = _RecordingPipeline(ComputeConfig())
    original_build, original_finalize = pipe.build_fields, pipe.finalize

    def build():
        nu_water_topo('Gyroid', 1, 3)
        air_cp(1100)
        return original_build()

    def finalize(*args):
        result = original_finalize(*args)
        result.extrap_reasons = list(df_reasons)
        result.diagnostics['mode'] = mode
        return result

    monkeypatch.setattr(pipe, 'build_fields', build)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    result = pipe.run()
    assert any('[water Nu extrap]' in text for text in result.warnings)
    assert any('air_cp:' in text for text in result.warnings)
    assert result.extrap_reasons == df_reasons
    win.write_result(result)
    assert win._diag_summary['warnings'] == result.warnings
    assert win._extrap_reasons == df_reasons
    assert win._has_extrap is df_extrap


def test_autofill_cache_and_draft_warnings_are_isolated_from_worker(win, monkeypatch):
    """Use real Auto-Fill/compute/Nu; stub only numerical phases of the worker."""
    from sjtu_tpmshx.models.tpms_calc import compute
    from sjtu_tpmshx.domain.run_warnings import current_warnings

    _configure(win, monkeypatch, '2d')
    win.combo_tpms.setCurrentText('Gyroid')
    win.le_Lcell.setText('7')
    win.le_t.setText('0.6')
    win.le_ks.setText('16')
    win.le_uA.setText('0.001')
    win.le_PinA.setText('101325')
    # Read the GUI's existing temperature unit conversion, not a guessed unit.
    temperature = win._temp_to_K(win.le_TinA)
    win.auto_fill_fluid_a()  # same params warm the public compute cache first
    assert not win._test_error_dialogs
    ready, release = threading.Event(), threading.Event()

    def build(pipe):
        assert current_warnings() is not None
        ready.set()
        assert release.wait(10)
        compute('Gyroid', 7, 0.6, 0.001, temperature, 101325, 16, 'air')
        return {}

    monkeypatch.setattr(Pipeline2D, 'build_fields', build)
    monkeypatch.setattr(Pipeline2D, 'run_solvers', lambda *a: {})
    monkeypatch.setattr(Pipeline2D, 'finalize',
                        lambda *a: ComputeResult(diagnostics={'mode': '2d'}))
    monkeypatch.setattr(win, '_render_compute_result', lambda: True)
    try:
        win.run_calculation()
        _wait_for(ready.is_set)
        assert current_warnings() is None
        win.combo_fluidB.setCurrentIndex(1)  # water, distinct from run's air Nu
        win.le_uB.setText('0.000001')
        win.auto_fill_fluid_b()
        assert not win._test_error_dialogs
    finally:
        release.set()
    _wait_for(win.compute.is_idle)
    result = win.compute.last_result()
    assert any('[Nu extrap]' in text for text in result.warnings)
    assert not any('[water Nu extrap]' in text for text in result.warnings)
    assert result.extrap_reasons == []
    # The same warmed inputs in a second worker still own their notices.
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert win.compute.last_result().warnings == result.warnings


@pytest.mark.parametrize('dimensions', [(0,), (1, 0, 1)])
def test_real_window_config_preserves_explicit_pipeline_mode(win, monkeypatch, dimensions):
    """A hidden Nz survives switching to 2D; it must not select Pipeline3D."""
    win.combo_shape.setCurrentIndex(0)
    win.le_Nz.setText('5')
    win.auto_fill_fluid_a()
    win.auto_fill_fluid_b()
    assert isValid(win.combo_df_mode)
    assert win.isAncestorOf(win.combo_df_mode)
    calls = []

    def run(pipe):
        mode = '3d' if isinstance(pipe, Pipeline3D) else '2d'
        calls.append((mode, pipe.cfg.solver.Nz))
        return ComputeResult(Q_W=123, diagnostics={'mode': mode})

    monkeypatch.setattr(Pipeline2D, 'run', run)
    monkeypatch.setattr(Pipeline3D, 'run', run)
    monkeypatch.setattr(win, '_render_compute_result', lambda: True)
    for dim in dimensions:
        win.combo_dim.setCurrentIndex(dim)
        win.run_calculation()
        _wait_for(win.compute.is_idle)
        mode = '3d' if dim else '2d'
        assert win.compute.current_mode() == mode
        assert win.compute.last_result().diagnostics['mode'] == mode
    assert calls == [('3d' if dim else '2d', 5 if dim else 1) for dim in dimensions]
    assert win.le_Nz.text() == '5'


def test_default_window_dimension_and_port_validation(win):
    from sjtu_tpmshx.ui.window_config import config_from_window

    # Startup applies the Shanghai 3D preset; select 2D with those defaults.
    win.combo_dim.setCurrentIndex(0)
    assert int(win.le_Nz.text()) >= 2
    cfg = config_from_window(win, strict=True)
    assert not cfg.is_3d
    cfg.bc_A.dir = 4
    with pytest.raises(ValueError, match='bc_A'):
        cfg.validate()
    win.combo_dim.setCurrentIndex(1)
    cfg = config_from_window(win, strict=True)
    assert cfg.is_3d
    cfg.bc_A.dir = 4
    cfg.bc_A.in_w = cfg.bc_A.out_w = 0
    cfg.validate()


@pytest.mark.parametrize('axis', [0, 2])
def test_real_window_zone_snapshot_is_independent(win, axis):
    from sjtu_tpmshx.ui.window_config import config_from_window

    win.combo_dim.setCurrentIndex(0)
    win.chk_zones.setChecked(True)
    win.combo_zone_axis.setCurrentIndex(axis)
    win._pareto_x_decision = np.array([0.1, 0.2, 0.3])
    cfg = config_from_window(win)
    win._pareto_x_decision[:] = 9
    win.zone_table.item(0, win.zone_table.columnCount() - 2).setText('8')
    assert cfg.zones.pareto_x_decision == pytest.approx([0.1, 0.2, 0.3])
    if axis == 2:
        win._zone_grid['cells'][0]['L'] = 8
        assert cfg.zones.grid['cells'][0]['L'] == 6
    else:
        cfg.zones.config.compute_properties(5, 3, 400, 300)
        assert cfg.zones.config.zones[0].L_mm == 6
        fresh = config_from_window(win)
        assert fresh.zones.config.zones[0].L_mm == 8
        assert not fresh.zones.config.zones[0].props_A


@pytest.mark.parametrize('axis,invalid', [
    (axis, invalid) for axis in (0, 2) for invalid in ('missing', 'empty', 'text')
] + [(0, 'gap')])
def test_real_window_rejects_invalid_zone_input(win, monkeypatch, axis, invalid):
    win.chk_zones.setChecked(True)
    win.combo_zone_axis.setCurrentIndex(axis)
    if invalid == 'missing':
        win.zone_table.takeItem(0, 0)
    elif invalid == 'empty':
        win.zone_table.setRowCount(0)
    else:
        win.zone_table.item(0, 0).setText('bad' if invalid == 'text' else '10')
    warnings, starts = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    win.compute.started.connect(starts.append)
    win.run_calculation()
    assert warnings and warnings[0][1] == 'Invalid Input'
    assert not starts and win.compute.is_idle()


@pytest.mark.parametrize('dim', [0, 1])
def test_real_zoned_pipeline_error_never_publishes(win, monkeypatch, dim):
    win.combo_dim.setCurrentIndex(dim)
    win.chk_zones.setChecked(True)
    win.combo_zone_axis.setCurrentIndex(0)
    win.chk_allow_extrap.setChecked(True)
    # 2D water zones and 3D 1D zones are existing unsupported paths.
    win.combo_fluidB.setCurrentText('Water')
    published, errors, writes = [], [], []
    win.compute.finished.connect(published.append)
    win.compute.error.connect(lambda *args: errors.append(args))
    monkeypatch.setattr(win, 'write_result', writes.append)
    pipeline = Pipeline3D if dim else Pipeline2D
    monkeypatch.setattr(pipeline, 'run_solvers', lambda *args: {})
    monkeypatch.setattr(pipeline, 'finalize', lambda *args: ComputeResult(Q_W=1))
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert errors and not published and not writes
    assert win.compute.last_result() is None


@pytest.mark.parametrize('column,value', [(2, '100'), (3, '0'), (0, '-10'),
                                         (1, '110'), (2, 'nan'), (3, 'inf')])
def test_real_window_rejects_invalid_grid_rectangle(win, monkeypatch, column, value):
    from PySide6.QtWidgets import QTableWidgetItem

    win.chk_zones.setChecked(True)
    win.combo_zone_axis.setCurrentIndex(2)
    win.zone_table.setRowCount(1)
    for col, text in enumerate(('0', '100', '0', '100', '6', '0.3')):
        win.zone_table.setItem(0, col, QTableWidgetItem(text))
    win.zone_table.item(0, column).setText(value)
    warnings, starts = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    win.compute.started.connect(starts.append)
    win.run_calculation()
    assert warnings and 'cell 1' in warnings[0][2]
    assert not starts and win.compute.is_idle()


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_worker_publishes_payload_on_gui_thread_without_reentry(win, monkeypatch, mode):
    cfg = _configure(win, monkeypatch, mode)
    gui_thread = threading.get_ident()
    release = threading.Event()
    result = ComputeResult(
        Q_W=123.5, dP_A_Pa=42.0, dP_B_Pa=7.0, T_out_A_K=310.0,
        T_out_B_K=300.0, fields={'Ta': np.ones((2, 2))},
        diagnostics={'mode': mode}, metadata={'run': 'complete payload'})
    worker_seen, writes, cache_writes, rendered, payloads = [], [], [], [], []
    progress, iterations = [], []
    win.compute.finished.connect(payloads.append)
    win.progress.valueChanged.connect(
        lambda p: progress.append((threading.get_ident(), p)))
    win.compute.iteration.connect(lambda s: iterations.append((threading.get_ident(), s)))

    def run(pipe):
        pipe.progress_cb(37)
        if mode == '2d':
            pipe.ui_hooks['live_residuals']['A'].append((1, 1e-3))
            pipe.ui_hooks['iter_label_cb']('iter 1/2')
        else:
            pipe.ui_hooks['iter_cb'](1, 2)
        assert release.wait(10)
        worker_seen.append((threading.get_ident(), pipe.cfg, pipe.cfg.solver.Nz))
        return result

    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run', run)
    original_write = win.write_result
    original_cache = win.cache.set_result

    def write(payload):
        writes.append((threading.get_ident(), payload, win.compute.is_running()))
        original_write(payload)

    def cache_write(*args):
        cache_writes.append(threading.get_ident())
        original_cache(*args)

    def render():
        # Recreate nested event processing during an expensive render.
        def restart():
            rendered.append((win.compute.start('2d', lambda *a, **k: None, {}),
                             win._compute_running, win.btn_compute.isEnabled()))
        QTimer.singleShot(0, restart)
        QApplication.processEvents()
        return True

    monkeypatch.setattr(win, 'write_result', write)
    monkeypatch.setattr(win.cache, 'set_result', cache_write)
    monkeypatch.setattr(win, '_render_compute_result', render)
    try:
        win.run_calculation()
        _wait_for(lambda: bool(iterations))
        assert win._compute_progress == 37
        assert win._iter_label_now == ('iter 1/2' if mode == '2d' else 'outer 1/2')
        if mode == '2d':
            assert win._live_residuals['A'] == [(1, 1e-3)]
        assert not writes and not cache_writes
        win.le_Nz.setText('99')  # UI edits cannot change the in-flight config.
    finally:
        release.set()
    _wait_for(win.compute.is_idle)

    assert worker_seen[0][0] != gui_thread
    assert worker_seen[0][1] is cfg
    assert worker_seen[0][2] == (2 if mode == '3d' else 1)
    assert writes == [(gui_thread, result, True)]
    assert cache_writes == [gui_thread]
    assert payloads == [result] and payloads[0] is result
    assert win.compute.last_result() is result
    assert (gui_thread, 37) in progress
    assert iterations[0][0] == gui_thread
    assert rendered == [(False, True, False)]
    assert win.compute.current_mode() == mode
    if mode == '3d':
        assert win.cache.get_result(mode) is result
    else:
        assert win._compute_results['Ta'] is result.fields['Ta']
        assert win._compute_results['Q_total'] == result.Q_W
    assert not win._compute_running
    assert win.btn_compute.isEnabled()
    assert win._compute_btn_handler == win.run_calculation


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('outcome', ['error', 'cancel', 'render_error'])
def test_terminal_paths_restore_ui(win, monkeypatch, mode, outcome):
    _configure(win, monkeypatch, mode)
    observed = []
    win.compute.error.connect(lambda *args: observed.append('error'))
    win.compute.cancelled.connect(lambda *args: observed.append('cancel'))
    win.compute.finished.connect(lambda *args: observed.append('finished'))

    def run(pipe):
        if outcome == 'error':
            raise RuntimeError('solver failed')
        if outcome == 'cancel':
            assert pipe.cancel.is_set()
            raise CancelledError('cancel checkpoint')
        return ComputeResult(Q_W=123, diagnostics={'mode': mode})

    def bad_render():
        raise RuntimeError('render failed')

    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run', run)
    if outcome == 'cancel':
        win.compute.started.connect(lambda _mode: win._on_cancel_compute())
    if outcome == 'render_error':
        monkeypatch.setattr(win, '_render_compute_result', bad_render)
    win.run_calculation()
    _wait_for(win.compute.is_idle)

    assert observed == ['finished' if outcome == 'render_error' else outcome]
    assert not win._compute_running
    assert win.btn_compute.isEnabled()
    assert win._compute_btn_handler == win.run_calculation
    assert not win._btn_ticker_timer.isActive()
    assert not win._live_resid_timer.isActive()
    assert not win.progress.isVisible()
    if mode == '3d':
        assert not win._compute_3d_watchdog.isActive()
    if outcome == 'render_error':
        assert win.cache.has_results(mode), 'render failure destroyed valid data'
    assert bool(win._test_error_dialogs) == (outcome == 'error')


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_close_waits_for_terminal_delivery_and_runnable_exit(win, monkeypatch, outcome):
    from sjtu_tpmshx.controllers.compute_orchestrator import _ComputeRunnable

    release, terminal_sent = threading.Event(), threading.Event()
    tail_errors, writes = [], []
    original_run = _ComputeRunnable.run

    def held_run(runnable):
        original_run(runnable)
        terminal_sent.set()
        try:
            assert release.wait(10)
            # The pool still owns this active runnable after terminal delivery.
            runnable._orch.progress.emit(95)
        except Exception as exc:
            tail_errors.append(exc)

    def worker(cfg, cancel, progress_cb):
        if outcome == 'error':
            raise RuntimeError('failure while closing')
        if outcome == 'cancel':
            raise ComputeOrchestrator.CancelledError()
        return ComputeResult(Q_W=123)

    monkeypatch.setattr(_ComputeRunnable, 'run', held_run)
    monkeypatch.setattr(win, 'write_result', writes.append)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    orch, cache = win.compute, win.cache
    try:
        orch.start('2d', worker, ComputeConfig())
        assert terminal_sent.wait(5)  # Deliberately do not drain Qt yet.
        t0 = time.monotonic()
        assert not win.close()
        assert time.monotonic() - t0 < 0.5, 'close blocked the GUI thread'
        assert isValid(win) and isValid(orch) and isValid(cache)
        assert win._close_pending and not win.isEnabled()
        _wait_for(lambda: not orch.is_running())
        assert not orch.is_idle(), 'terminal signal is not runnable completion'
        assert not win.close()
        assert isValid(win) and not writes
        assert not win._test_error_dialogs
    finally:
        release.set()
    _wait_for(lambda: not isValid(win))
    assert not isValid(orch) and not isValid(cache)
    assert not tail_errors, 'worker accessed a deleted QObject'


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_close_cancels_live_pipeline_without_destroying_its_callbacks(win, monkeypatch, mode):
    _configure(win, monkeypatch, mode)
    release, entered = threading.Event(), threading.Event()
    cancellation_seen = []

    def run(pipe):
        entered.set()
        assert release.wait(10)
        cancellation_seen.append(pipe.cancel.cancelled)
        pipe.progress_cb(90)
        if mode == '2d':
            pipe.ui_hooks['iter_label_cb']('last checkpoint')
        else:
            pipe.ui_hooks['iter_cb'](2, 2)
        pipe._check_cancel()

    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run', run)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    try:
        win.run_calculation()
        assert entered.wait(5)
        assert not win.close()
        assert isValid(win.compute) and win.compute.is_running()
        assert win._close_pending
    finally:
        release.set()
    _wait_for(lambda: not isValid(win))
    assert cancellation_seen == [True]
