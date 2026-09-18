"""logutil locks (openspec print-to-logging).

The load-bearing property: the handler resolves sys.stdout PER RECORD, so
the GUI solve-log viewer's ``contextlib.redirect_stdout`` capture sees log
records exactly as it saw the old ``print()`` output. A plain
``StreamHandler(sys.stdout)`` would bind the original stream and silently
bypass the capture — that regression is what these tests pin.
"""
from __future__ import annotations

import contextlib
import io
import logging

from sjtu_tpmshx.logutil import get_logger  # noqa: E402


def test_logger_output_visible_under_redirect_stdout():
    log = get_logger('tests.capture')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        log.info("[capture-check] hello %d", 42)
    assert "[capture-check] hello 42" in buf.getvalue()


def test_default_format_is_bare_message():
    log = get_logger('tests.fmt')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        log.info("[fmt-check] plain")
    # Bare message + newline — no level/name/timestamp prefix by default.
    lines = [l for l in buf.getvalue().splitlines() if 'fmt-check' in l]
    assert lines == ["[fmt-check] plain"]


def test_level_filter_suppresses_info():
    log = get_logger('tests.level')
    root = logging.getLogger('tpmshx')
    old = root.level
    try:
        root.setLevel(logging.ERROR)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log.info("[level-check] should not appear")
            log.error("[level-check] should appear")
        out = buf.getvalue()
        assert "should not appear" not in out
        assert "should appear" in out
    finally:
        root.setLevel(old)


def test_no_duplicate_into_stdlib_root(capfd=None):
    """tpmshx root has propagate=False — records must not reach the stdlib
    root logger (which could double-print once an app configures it)."""
    root = logging.getLogger('tpmshx')
    get_logger('tests.prop')          # ensure configured
    assert root.propagate is False
    assert any(type(h).__name__ == '_StdoutHandler' for h in root.handlers)


def test_ts_env_adds_timestamp_prefix(monkeypatch):
    """TPMSHX_LOG_TS=1 → 'HH:MM:SS LEVEL name: message' render.

    _configure_root is once-per-process, so build the handler/formatter
    pair the same way the module does and verify the format directly."""
    import io as _io
    import sjtu_tpmshx.logutil as lu
    monkeypatch.setenv('TPMSHX_LOG_TS', '1')
    # Reset the module singleton in an isolated logger namespace.
    monkeypatch.setattr(lu, '_configured', False)
    saved_handlers = list(logging.getLogger('tpmshx').handlers)
    logging.getLogger('tpmshx').handlers.clear()
    try:
        log = lu.get_logger('tests.ts')
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            log.info("[ts-check] stamped")
        line = [l for l in buf.getvalue().splitlines() if 'ts-check' in l][0]
        # "HH:MM:SS INFO tpmshx.tests.ts: [ts-check] stamped"
        assert 'INFO' in line and 'tpmshx.tests.ts' in line
        assert line.split(' ')[0].count(':') == 2
    finally:
        logging.getLogger('tpmshx').handlers.clear()
        logging.getLogger('tpmshx').handlers.extend(saved_handlers)
        monkeypatch.setattr(lu, '_configured', True)


def test_invalid_level_env_falls_back_to_info(monkeypatch):
    """Garbage TPMSHX_LOG_LEVEL must resolve to INFO, not crash."""
    import sjtu_tpmshx.logutil as lu
    monkeypatch.setenv('TPMSHX_LOG_LEVEL', 'NOT_A_LEVEL')
    monkeypatch.setattr(lu, '_configured', False)
    try:
        lu.get_logger('tests.badlevel')
        assert logging.getLogger('tpmshx').level == logging.INFO
    finally:
        monkeypatch.setattr(lu, '_configured', True)
        logging.getLogger('tpmshx').setLevel(logging.INFO)


def test_parallel_simple_workers_keep_their_parent_output_scope():
    import sys
    from sjtu_tpmshx.logutil import capture_output
    from sjtu_tpmshx.solvers.backends.python.three_d.runtime import _run_two_simple

    original = sys.stdout, sys.stderr
    out, err = io.StringIO(), io.StringIO()

    class Solver:
        Nx = Ny = Nz = 2

        def __init__(self, side):
            self.side = side

        def solve(self, **kwargs):
            print(f'worker-{self.side}')
            print(f'diagnostic-{self.side}', file=sys.stderr)
            get_logger('tests.parallel').info(f'logged-{self.side}')
            return True, 1

    with capture_output(out, err):
        assert _run_two_simple(Solver('A'), Solver('B')) == [(True, 1), (True, 1)]
    for side in ('A', 'B'):
        assert f'worker-{side}' in out.getvalue()
        assert f'logged-{side}' in out.getvalue()
        assert f'diagnostic-{side}' in err.getvalue()
    assert (sys.stdout, sys.stderr) == original


def test_overlapping_capture_scopes_restore_streams_after_out_of_order_exit():
    import sys
    import threading
    from sjtu_tpmshx.logutil import capture_output

    original = sys.stdout, sys.stderr
    ready, release = threading.Event(), threading.Event()
    first, second = io.StringIO(), io.StringIO()

    def worker():
        with capture_output(second, second):
            ready.set()
            assert release.wait(2)
            print('second-run')

    with capture_output(first, first):
        thread = threading.Thread(target=worker)
        thread.start()
        assert ready.wait(2)
        print('first-run')
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert first.getvalue() == 'first-run\n'
    assert second.getvalue() == 'second-run\n'
    assert (sys.stdout, sys.stderr) == original
