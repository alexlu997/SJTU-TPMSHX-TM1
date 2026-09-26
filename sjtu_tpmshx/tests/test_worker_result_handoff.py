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
    monkeypatch.setenv('TPMSHX_DISABLE_3D_PANEL', '1')
    window = Main_Menu()
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
        assert float(win._sb_labels['tout'].text().split(' / ')[0]) == 341.25
        assert float(win._sb_labels['tout'].text().split(' / ')[1]) == 312.75
    win._toggle_temp_unit()
    assert '[°C]' in win._lbl_sidebar_tout_unit.text()
    assert win._sb_labels['tout'].text() == '68.10 / 39.60'
    win._update_tout(0)
    assert float(win._sb_labels['tout'].text().split(' / ')[0]) == pytest.approx(68.10)
    assert float(win._sb_labels['tout'].text().split(' / ')[1]) == pytest.approx(39.60)
    win._toggle_temp_unit()
    assert '[K]' in win._lbl_sidebar_tout_unit.text()
    assert win._sb_labels['tout'].text() == '341.25 / 312.75'
    assert float(win._sb_labels['tout'].text().split(' / ')[0]) == 341.25
    assert float(win._sb_labels['tout'].text().split(' / ')[1]) == 312.75
    assert win.cache.get_result('2d').Q_W == result.Q_W == 123.


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
    # These deliberately tiny velocities probe Nu warnings, outside the
    # experiment-effective D-F application's velocity window.
    win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData('cfd_smooth'))
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
        cache_writes.append((threading.get_ident(), args[0], args[1] is None))
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
        assert not writes and not cache_writes
        win.le_Nz.setText('99')  # UI edits cannot change the in-flight config.
    finally:
        release.set()
    _wait_for(win.compute.is_idle)

    assert worker_seen[0][0] != gui_thread
    assert worker_seen[0][1] is cfg
    assert worker_seen[0][2] == (2 if mode == '3d' else 1)
    assert writes == [(gui_thread, result, True)]
    assert cache_writes == [
        (gui_thread, '3d' if mode == '2d' else '2d', True),
        (gui_thread, mode, False),
    ]
    assert payloads == [result] and payloads[0] is result
    assert win.compute.last_result() is result
    assert (gui_thread, 37) in progress
    assert iterations[0][0] == gui_thread
    assert rendered == [(False, True, False)]
    assert win.compute.current_mode() == mode
    if mode == '3d':
        assert win.cache.get_result(mode) is result
    else:
        assert win.cache.get_result('2d').fields['Ta'] is result.fields['Ta']
        assert win.cache.get_result('2d').Q_W == result.Q_W
    assert not win._compute_running
    assert win.btn_compute.isEnabled()
    assert win._compute_btn_handler == win.run_calculation


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_display_timing_reaches_result_and_export_cache(win, monkeypatch, mode):
    _configure(win, monkeypatch, mode)
    clock = [0.0]
    monkeypatch.setattr('sjtu_tpmshx.ui.mixins.run_controller.perf_counter',
                        lambda: clock[0])
    result = ComputeResult(
        Q_W=123.5, diagnostics={'mode': mode}, warnings=['retained warning'],
        metadata={'timings_s': {'prepare': 1.0, 'solve': 2.0, 'postprocess': 3.0}})
    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run',
                        lambda _pipe: result)
    original_write = win.write_result
    original_end = win._end_compute_ui
    original_finish = win._run_status_card.finish
    card_elapsed, provenance_elapsed = [], []
    # Worker time includes overhead beyond the 1+2+3-second phase timings.
    monkeypatch.setattr(win.compute, 'last_elapsed', lambda: 20.0)

    def write(payload):
        original_write(payload)
        clock[0] += 2.0

    def render():
        clock[0] += 3.0
        return True

    def end(*, success):
        clock[0] += 100.0
        win._compute_t0 -= 3600.0  # time spent waiting/reading is not compute work
        original_end(success=success)

    def finish(state, elapsed, **kwargs):
        card_elapsed.append(elapsed)
        original_finish(state, elapsed, **kwargs)

    monkeypatch.setattr(win, 'write_result', write)
    monkeypatch.setattr(win, '_render_compute_result', render)
    monkeypatch.setattr(win, '_end_compute_ui', end)
    monkeypatch.setattr(win._run_status_card, 'finish', finish)
    monkeypatch.setattr(win, '_stamp_result_provenance', provenance_elapsed.append)
    win.run_calculation()
    _wait_for(win.compute.is_idle)

    expected = {'prepare': 1.0, 'solve': 2.0, 'postprocess': 3.0, 'display': 5.0}
    assert result.metadata['timings_s'] == expected
    cached = win.cache.get_result(mode)
    assert cached.metadata['timings_s'] == expected
    assert win._diag_summary['timings_s'] == expected
    assert card_elapsed == provenance_elapsed == [25.0]
    assert win._last_elapsed_s == 25.0
    assert win._diag_summary['warnings'] == ['retained warning']
    assert result.Q_W == 123.5


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
    assert not win.progress.isVisible()
    if mode == '3d':
        assert not win._compute_3d_watchdog.isActive()
    if outcome == 'render_error':
        assert win.cache.has_results(mode), 'render failure destroyed valid data'
    assert bool(win._test_error_dialogs) == (outcome == 'error')


@pytest.mark.parametrize('failure', ['false', 'exception'])
@pytest.mark.parametrize('discard', [False, True])
def test_close_requires_choice_when_session_save_fails(win, monkeypatch, failure, discard):
    dialogs, disconnected = [], []

    def save():
        if failure == 'exception':
            raise OSError('disk full')
        return False

    def warning(*args):
        dialogs.append(args)
        return (QMessageBox.StandardButton.Discard if discard
                else QMessageBox.StandardButton.Cancel)

    with monkeypatch.context() as patch:
        patch.setattr(win, '_save_session', save)
        patch.setattr(QMessageBox, 'warning', warning)
        patch.setattr(win.signals, 'disconnect_all', lambda: disconnected.append(True))
        win.le_Lcell.setText('6.5')
        assert win.close() is discard
        assert len(dialogs) == 1
        assert dialogs[0][-1] == QMessageBox.StandardButton.Cancel
        assert dialogs[0][-2] == (QMessageBox.StandardButton.Cancel
                                  | QMessageBox.StandardButton.Discard)
        assert bool(disconnected) is discard
        if not discard:
            assert win.isEnabled()
            assert not getattr(win, '_close_pending', False)
            assert win.le_Lcell.text() == '6.5'
    if not discard:
        assert win.close(), 'saving successfully must allow a later close'
        assert win.sm.load_session() is not None


def test_cancel_close_on_save_failure_keeps_live_compute(win, monkeypatch):
    release, entered = threading.Event(), threading.Event()

    def worker(cfg, cancel, progress_cb):
        entered.set()
        assert release.wait(10)
        assert not cancel.is_set(), 'cancelled closing must not cancel the computation'
        return ComputeResult(Q_W=123)

    monkeypatch.setattr(win, '_render_compute_result', lambda: True)
    try:
        win.compute.start('2d', worker, ComputeConfig())
        _wait_for(entered.is_set)
        with monkeypatch.context() as patch:
            patch.setattr(win, '_save_session', lambda: False)
            patch.setattr(QMessageBox, 'warning',
                          lambda *args: QMessageBox.StandardButton.Cancel)
            assert not win.close()
            assert win.isEnabled() and not getattr(win, '_close_pending', False)
            assert win.compute.is_running()
    finally:
        release.set()
    _wait_for(win.compute.is_idle)
    assert win.cache.get_result('2d').Q_W == 123
    assert win.btn_compute.isEnabled() and not win._compute_running
    assert win.close()


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
@pytest.mark.parametrize('save_ok', [True, False])
def test_close_waits_for_terminal_delivery_and_runnable_exit(win, monkeypatch, outcome, save_ok):
    from sjtu_tpmshx.controllers.compute_orchestrator import _ComputeRunnable

    release, terminal_sent = threading.Event(), threading.Event()
    tail_errors, writes = [], []
    saves, dialogs = [], []
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
    monkeypatch.setattr(win, '_save_session', lambda: saves.append(True) or save_ok)
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *args: dialogs.append(args) or QMessageBox.StandardButton.Discard)
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
    assert len(saves) == 1 and len(dialogs) == (0 if save_ok else 1)


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


@pytest.mark.parametrize('kind', ['optimize', 'quick_design'])
@pytest.mark.parametrize('outcome', ['result', 'error'])
def test_auxiliary_task_close_keeps_thread_until_run_returns(win, monkeypatch, tmp_path,
                                                            kind, outcome):
    """A published result/error does not permit destruction of a running QThread."""
    from sjtu_tpmshx.ui import optimize_panel, quick_design_panel
    from sjtu_tpmshx.design.sizing import Design
    from sjtu_tpmshx.ui.background_tasks import has_active_tasks

    release, terminal_sent = threading.Event(), threading.Event()
    backend_called = threading.Event()
    panel = optimize_panel if kind == 'optimize' else quick_design_panel
    Worker = panel._make_worker_class()
    original_run = Worker.run

    def held_run(worker):
        original_run(worker)
        terminal_sent.set()
        assert release.wait(10)

    monkeypatch.setattr(Worker, 'run', held_run)
    monkeypatch.setattr(panel, '_make_worker_class', lambda: Worker)
    def fail_or_result(*args, **kwargs):
        if kind == 'optimize':
            assert isinstance(args[0][0][1], ComputeConfig)
        backend_called.set()
        if outcome == 'error':
            raise RuntimeError('terminal error before thread exit')
        if kind == 'quick_design':
            return Design(False)
        return dict(status='completed', reason=None, method=kwargs['method'],
                    history=[], pareto_indices=[], n_evaluated=0, n_usable=0)

    monkeypatch.setattr('sjtu_tpmshx.optimization.multi_condition_optimizer.run_multi_condition_optimization',
                        fail_or_result)
    monkeypatch.setattr(optimize_panel, 'optimization_output_dir', lambda: tmp_path)
    monkeypatch.setattr('sjtu_tpmshx.design.cases.load_cases', lambda p: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.design.sizing.size_fixed_cell', fail_or_result)
    if kind == 'optimize':
        owner, attr = win, '_opt_worker'
        win.combo_dim.setCurrentIndex(0)
        win._opt_conditions = [dict(condition_id='close-test',
            T_in_A_K=400., P_in_A_Pa=130000., mass_flow_A_kg_s=.003,
            T_in_B_K=295., P_in_B_Pa=120000., mass_flow_B_kg_s=.015)]
        optimize_panel.run_optimize(win)
    else:
        owner = quick_design_panel.build_quick_design_dialog(win)
        win._qd_dialog = owner
        owner.le_qd_file.setText('not-read.xlsx')
        owner.combo_qd_mode.setCurrentIndex(owner.combo_qd_mode.findData('fixed'))
        attr = '_qd_worker'
        quick_design_panel.run_quick_design(owner)
    worker = getattr(owner, attr)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    try:
        assert terminal_sent.wait(5)
        assert backend_called.is_set()
        assert not win.close()
        assert has_active_tasks(win)
        _wait_for(lambda: worker.isInterruptionRequested())
        QApplication.processEvents()
        assert getattr(owner, attr) is worker and worker.isRunning()
        assert isValid(win) and isValid(worker)
        assert not win.close()
    finally:
        release.set()
    _wait_for(lambda: not isValid(win))


def test_quick_design_escape_requests_cooperative_cancel(win, monkeypatch):
    from sjtu_tpmshx.ui import quick_design_panel as panel
    from sjtu_tpmshx.design.sizing import Design
    entered, release = threading.Event(), threading.Event()
    def candidate(*args, control, **kwargs):
        entered.set()
        assert release.wait(10)
        control.check_cancelled()
        return Design(False)
    monkeypatch.setattr('sjtu_tpmshx.design.cases.load_cases', lambda p: ['case'])
    monkeypatch.setattr('sjtu_tpmshx.design.sizing.size_fixed_cell', candidate)
    dlg = panel.build_quick_design_dialog(win)
    win._qd_dialog = dlg
    dlg.le_qd_file.setText('unused.xlsx')
    dlg.combo_qd_mode.setCurrentIndex(dlg.combo_qd_mode.findData('fixed'))
    dlg.show()
    panel.run_quick_design(dlg)
    worker = dlg._qd_worker
    try:
        assert entered.wait(5)
        dlg.reject()  # Escape follows QDialog.reject, as well as the titlebar close.
        assert dlg.isVisible() and not dlg.isEnabled()
        assert worker.isInterruptionRequested()
    finally:
        release.set()
    _wait_for(lambda: dlg._qd_worker is None)
    assert not dlg.isVisible() and dlg.isEnabled()
    assert '已取消' in dlg._qd_status.text()


@pytest.mark.parametrize('dimension,expected', [(0, (84, 24, 1)), (1, (92, 14, 10))])
def test_field_restore_uses_the_current_case_dimension_and_remains_undoable(win, dimension, expected):
    from sjtu_tpmshx.ui.field_menu import _revert_field_to_default
    win.combo_dim.setCurrentIndex(dimension)
    win._temp_unit = 'C'
    for attr in ('le_Nx', 'le_Ny', 'le_Nz', 'le_rho_s', 'le_pipeB_in_z_ctr', 'le_TinA'):
        getattr(win, attr).setText('100')
    win._resync_undo_baseline()
    win._undo_stack.clear()
    for axis in 'xyz':
        attr = 'le_N' + axis
        _revert_field_to_default(win, getattr(win, attr), attr)
    assert tuple(int(getattr(win, 'le_N' + axis).text()) for axis in 'xyz') == expected
    _revert_field_to_default(win, win.le_TinA, 'le_TinA')
    assert float(win.le_TinA.text()) == pytest.approx(148.85)
    win._undo_stack.undo()
    assert win.le_TinA.text() == '100'
    win._undo_stack.redo()
    assert float(win.le_TinA.text()) == pytest.approx(148.85)
    for attr, expected_value in [('le_rho_s', 7900.), ('le_pipeB_in_z_ctr', .021)]:
        _revert_field_to_default(win, getattr(win, attr), attr)
        assert float(getattr(win, attr).text()) == expected_value


@pytest.mark.parametrize('typed,expected', [('0.042 / 2', '0.021'), ('5 mm', '0.005')])
def test_normalized_field_edit_records_undo_and_final_validation(win, typed, expected):
    win.le_L.setText('0.1')
    win._resync_undo_baseline()
    win._undo_stack.clear()
    win.le_L.setText(typed)
    win.le_L.editingFinished.emit()
    assert win.le_L.text() == expected
    assert win.le_L.property('inpError') == 'false'
    assert win._field_history['le_L'][0] == expected
    assert win._undo_stack.count() == 1
    win._undo_stack.undo()
    assert win.le_L.text() == '0.1'
    win._undo_stack.redo()
    assert win.le_L.text() == expected
    assert win.le_L.property('inpError') == 'false'


@pytest.mark.parametrize('refined,expected', [(False, (36, 17, 17)), (True, (50, 17, 17))])
def test_geometry_grid_suggestion_uses_selected_scheme_and_preserves_edits(win, monkeypatch, refined, expected):
    import sjtu_tpmshx.main as main
    win.combo_dim.setCurrentIndex(1)
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(refined))
    monkeypatch.setattr(main, 'tpms_geometry', lambda *a: dict(
        epsilon=.7, A_0=100., D_h=.005, K_ss=3.))
    win._user_edited_grid = False
    assert win.compute_tpms()
    assert tuple(int(getattr(win, 'le_N' + axis).text()) for axis in 'xyz') == expected
    for axis, count in zip('xyz', (111, 30, 20)):
        getattr(win, 'le_N' + axis).setText(str(count))
    win._mark_grid_edited()
    assert win.compute_tpms()
    assert tuple(int(getattr(win, 'le_N' + axis).text()) for axis in 'xyz') == (111, 30, 20)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('index,fluid_type', [(0, 'air'), (1, 'water'), (2, 'sco2')])
def test_auto_fill_uses_same_fluid_type_as_config(win, monkeypatch, side, index, fluid_type):
    from sjtu_tpmshx.ui.window_config import config_from_window
    win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData('cfd_smooth'))
    getattr(win, f'combo_fluid{side}').setCurrentIndex(index)
    monkeypatch.setattr(win, 'compute_tpms', lambda: True)
    observed = []
    def compute(*args, **kwargs):
        observed.append(kwargs['fluid_type'])
        return dict(Re=1000., Nu=30., rho=10., dP_per_L=5.)
    monkeypatch.setattr('sjtu_tpmshx.ui.mixins.fluid_input.tpms_compute', compute)
    win._auto_fill_fluid(side)
    cfg = config_from_window(win)
    assert observed == [fluid_type]
    assert getattr(cfg, f'fluid_{side}').type == fluid_type
