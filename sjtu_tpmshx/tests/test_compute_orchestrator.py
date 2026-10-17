"""Unit tests for controllers.compute_orchestrator.

Validates the solver-lifecycle controller using a *mock* worker that does
not run any real CFD. Covers:

  - happy path: start → progress → finished
  - error path: worker raises → error signal
  - cancel path: cancel_token observed → cancelled signal
  - re-entrancy: second start() while running returns False

Phase 1 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os
import threading
import time

import pytest

# Headless Qt for CI / non-GUI test environments.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEventLoop

from sjtu_tpmshx.controllers.compute_orchestrator import ComputeOrchestrator, CancelToken
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.paused_run import PausedRun


# ----------------------------------------------------------- helpers


def _make_app():
    """Idempotent QCoreApplication for headless tests."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def _wait_for(predicate, timeout_s: float = 5.0, tick_ms: int = 20):
    """Spin Qt event loop until predicate() is true or timeout. Returns bool."""
    app = _make_app()
    deadline = time.time() + timeout_s
    while not predicate() and time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, tick_ms)
    return predicate()


# ----------------------------------------------------------- happy path


def test_happy_path_emits_started_progress_finished():
    _make_app()
    orch = ComputeOrchestrator()

    events = []
    orch.started.connect(lambda mode: events.append(('started', mode)))
    orch.progress.connect(lambda p: events.append(('progress', p)))
    orch.finished.connect(lambda r: events.append(('finished', r)))

    def worker(cfg, cancel, progress_cb):
        progress_cb(25)
        progress_cb(75)
        return {'Q': 1234.5, 'cfg_echo': cfg}

    ok = orch.start('2d', worker, {'param': 'v'})
    assert ok, "start should accept first call"

    assert _wait_for(lambda: any(e[0] == 'finished' for e in events))

    assert ('started', '2d') in events
    progress_values = [p for tag, p in events if tag == 'progress']
    assert 25 in progress_values
    assert 75 in progress_values
    finished_payload = next(e[1] for e in events if e[0] == 'finished')
    assert finished_payload['Q'] == 1234.5
    assert finished_payload['cfg_echo'] == {'param': 'v'}
    assert not orch.is_running()
    assert orch.last_result()['Q'] == 1234.5


# ----------------------------------------------------------- error path


def test_worker_exception_emits_error_signal():
    _make_app()
    orch = ComputeOrchestrator()

    errors = []
    orch.error.connect(lambda msg, log: errors.append((msg, log)))

    def worker(cfg, cancel, progress_cb):
        raise RuntimeError("solver diverged: |R| = nan")

    orch.start('2d', worker, {})
    assert _wait_for(lambda: len(errors) > 0)

    msg, log = errors[0]
    assert "solver diverged" in msg
    assert "RuntimeError" in log  # traceback was captured
    assert not orch.is_running()


@pytest.mark.parametrize('outcome', ['finished', 'error', 'cancelled', 'paused'])
def test_large_log_keeps_recent_diagnostics_in_every_terminal_state(monkeypatch, outcome):
    import io
    import sys

    _make_app()
    orch = ComputeOrchestrator()
    monkeypatch.setattr(sys, '__stdout__', io.StringIO())
    monkeypatch.setattr(sys, '__stderr__', io.StringIO())

    def worker(cfg, cancel, progress_cb):
        print('old-start-marker')
        print('x' * 500_100)
        print('最后一条诊断', file=sys.stderr)
        if outcome == 'error':
            raise ValueError('last-error-marker')
        if outcome == 'cancelled':
            raise orch.CancelledError()
        if outcome == 'paused':
            raise PausedRun('checkpoint.h5')
        return {'ok': True}

    assert orch.start('2d', worker, {})
    assert _wait_for(orch.is_idle)
    log = orch.last_log()
    assert len(log) <= 500_000
    assert '最后一条诊断' in log
    assert 'old-start-marker' not in log
    if outcome == 'error':
        assert 'ValueError: last-error-marker' in log


def test_tail_log_storage_is_bounded_before_completion():
    from sjtu_tpmshx.controllers.compute_orchestrator import _TailLog

    log = _TailLog(limit=16)
    expected = ''
    for chunk in ('开头', '1234567890', '末尾', 'x' * 50, '终', ''):
        assert log.write(chunk) == len(chunk)
        expected = (expected + chunk)[-16:]
        assert log.getvalue() == expected
        assert sum(map(len, log._chunks)) <= 16


def test_gui_output_does_not_enter_the_active_solver_log(monkeypatch):
    import io
    import sys

    _make_app()
    orch = ComputeOrchestrator()
    ready, release = threading.Event(), threading.Event()
    stdout, stderr = sys.stdout, sys.stderr
    monkeypatch.setattr(sys, '__stdout__', io.StringIO())

    def worker(cfg, cancel, progress_cb):
        print('solver-start-marker')
        ready.set()
        assert release.wait(2)
        print('solver-end-marker')
        return {}

    assert orch.start('2d', worker, {})
    try:
        assert ready.wait(2)
        print('unrelated-gui-marker')
    finally:
        release.set()
        assert _wait_for(orch.is_idle)
    assert 'solver-start-marker' in orch.last_log()
    assert 'solver-end-marker' in orch.last_log()
    assert 'unrelated-gui-marker' not in orch.last_log()
    assert sys.stdout is stdout and sys.stderr is stderr


# ----------------------------------------------------------- cancel path


def test_cancellation_alias_is_shared_with_domain():
    assert ComputeOrchestrator.CancelledError is CancelledError


def test_saved_pause_has_its_own_signal_and_keeps_publication_busy():
    _make_app()
    orch = ComputeOrchestrator()
    events = []
    ready, release = threading.Event(), threading.Event()
    orch.finished.connect(lambda result: events.append(('finished', result)))
    orch.cancelled.connect(lambda log: events.append(('cancelled', log)))
    orch.error.connect(lambda message, log: events.append(('error', message)))
    orch.paused.connect(lambda path, log: events.append(('paused', path, log, orch.is_running())))

    def worker(cfg, cancel, progress_cb):
        ready.set()
        assert release.wait(2)
        assert cancel.pause_requested()
        assert not cancel.cancelled and not cancel.is_set()
        print('saved numerical state')
        raise PausedRun('run/checkpoint.h5')

    assert orch.start('2d', worker, {})
    try:
        assert ready.wait(2)
        orch.pause()
        assert orch.is_running()
    finally:
        release.set()
        assert _wait_for(orch.is_idle)
    assert len(events) == 1
    assert events[0][:2] == ('paused', 'run/checkpoint.h5')
    assert 'saved numerical state' in events[0][2]
    assert events[0][3] is True
    assert orch.last_result() is None
    assert orch.last_elapsed() > 0


@pytest.mark.parametrize('error_type', [CancelledError, InterruptedError, ValueError])
@pytest.mark.parametrize('requested', [False, True])
def test_only_shared_cancellation_exception_emits_cancelled(error_type, requested):
    _make_app()
    orch = ComputeOrchestrator()
    events = []
    orch.finished.connect(lambda result: events.append(('finished', result)))
    orch.cancelled.connect(lambda log: events.append(('cancelled', log)))
    orch.error.connect(lambda message, log: events.append(('error', message, log)))
    failure = error_type('worker checkpoint')

    def worker(cfg, cancel, progress_cb):
        if requested:
            cancel.cancel()
        raise failure

    assert orch.start('2d', worker, {})
    assert _wait_for(orch.is_idle)
    expected = 'cancelled' if error_type is CancelledError else 'error'
    assert [event[0] for event in events] == [expected]
    assert orch.last_result() is None
    if expected == 'error':
        assert events[0][1] == str(failure)
        assert error_type.__name__ in events[0][2]


def test_cancel_token_triggers_cancelled_signal():
    _make_app()
    orch = ComputeOrchestrator()

    cancelled_logs = []
    orch.cancelled.connect(lambda log: cancelled_logs.append(log))

    def worker(cfg, cancel, progress_cb):
        for i in range(100):
            if cancel.is_set():
                raise ComputeOrchestrator.CancelledError()
            time.sleep(0.01)
            progress_cb(i)
        return {'completed': True}

    orch.start('2d', worker, {})
    # Let it tick a few iterations, then cancel
    time.sleep(0.05)
    orch.cancel()

    assert _wait_for(lambda: len(cancelled_logs) > 0, timeout_s=2.0)
    assert not orch.is_running()
    # Verify the result is NOT the "completed" payload (loop didn't finish)
    assert orch.last_result() is None


# ----------------------------------------------------------- re-entrancy


def test_second_start_while_running_returns_false():
    _make_app()
    orch = ComputeOrchestrator()

    def slow_worker(cfg, cancel, progress_cb):
        time.sleep(0.2)
        return {'ok': True}

    ok1 = orch.start('2d', slow_worker, {})
    assert ok1, "first start accepted"

    # Immediately try a second one — must reject
    ok2 = orch.start('2d', slow_worker, {})
    assert not ok2, "second start while running must return False"

    # Wait for the first to complete, then verify a third is accepted
    assert _wait_for(lambda: not orch.is_running(), timeout_s=2.0)
    ok3 = orch.start('2d', slow_worker, {})
    assert ok3, "start after completion must succeed"
    assert _wait_for(lambda: not orch.is_running(), timeout_s=2.0)


@pytest.mark.parametrize('outcome', ['finished', 'error', 'cancelled'])
def test_terminal_state_is_queued_and_locked_through_publication(outcome):
    from sjtu_tpmshx.domain.compute_result import ComputeResult

    app = _make_app()
    orch = ComputeOrchestrator()
    gui_thread = threading.get_ident()
    result = ComputeResult(Q_W=12.5, metadata={'payload': 'complete'})
    seen = []

    def worker(cfg, cancel, progress_cb):
        if outcome == 'error':
            raise ValueError('failed')
        if outcome == 'cancelled':
            raise orch.CancelledError()
        return result

    def terminal(*args):
        app.processEvents()
        seen.append((threading.get_ident(), orch.is_running(),
                     orch.start('3d', worker, {})))

    getattr(orch, outcome).connect(terminal)
    assert orch.start('2d', worker, {})
    assert orch._pool.waitForDone(3000)
    # Worker exit alone must not write state or unlock a pending publication.
    assert orch.is_running() and not orch.is_idle()
    assert orch.last_result() is None
    assert not seen
    assert _wait_for(orch.is_idle)
    assert seen == [(gui_thread, True, False)]
    assert orch.current_mode() == '2d'
    if outcome == 'finished':
        assert orch.last_result() is result




# ----------------------------------------------------------- mode validation


@pytest.mark.parametrize('mode', ['quantum', 'poly'])
def test_invalid_mode_raises(mode):
    orch = ComputeOrchestrator()

    def noop(cfg, cancel, progress_cb):
        pytest.fail('invalid mode dispatched a worker')

    with pytest.raises(ValueError):
        orch.start(mode, noop, {})
    assert not orch.is_running()


# ----------------------------------------------------------- cancel idempotent


def test_cancel_before_start_is_noop():
    """cancel() called when no worker is active should not crash."""
    orch = ComputeOrchestrator()
    orch.cancel()  # no exception expected
    assert not orch.is_running()


def test_cancel_token_class_basic():
    """Sanity on the CancelToken primitive itself."""
    tok = CancelToken()
    assert not tok.is_set()
    tok.cancel()
    assert tok.is_set()
