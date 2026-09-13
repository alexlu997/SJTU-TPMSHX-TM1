"""Unit tests for controllers.compute_orchestrator.

Validates the solver-lifecycle controller using a *mock* worker that does
not run any real CFD. Covers:

  - happy path: start → progress → finished
  - error path: worker raises → error signal
  - cancel path: cancel_token observed → cancelled signal
  - re-entrancy: second start() while running returns False
  - ETA history: median over per-mode rings

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
    assert orch.last_error() == msg


# ----------------------------------------------------------- cancel path


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
    assert orch.last_result() is None and orch.last_error() is None
    assert not seen
    assert _wait_for(orch.is_idle)
    assert seen == [(gui_thread, True, False)]
    assert orch.current_mode() == '2d'
    if outcome == 'finished':
        assert orch.last_result() is result


# ----------------------------------------------------------- ETA history


def test_eta_history_reports_median():
    _make_app()
    orch = ComputeOrchestrator()

    # Empty history → None
    assert orch.eta_seconds('2d') is None

    # Run 3 quick computes, ETA should populate
    def quick_worker(cfg, cancel, progress_cb):
        time.sleep(0.05)
        return {}

    for _ in range(3):
        orch.start('2d', quick_worker, {})
        assert _wait_for(lambda: not orch.is_running(), timeout_s=2.0)

    eta = orch.eta_seconds('2d')
    assert eta is not None
    assert 0.04 <= eta <= 0.5  # broad bound — sleep + Qt overhead

    # 3D mode should still be empty (per-mode isolation)
    assert orch.eta_seconds('3d') is None


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
    tok.reset()
    assert not tok.is_set()
