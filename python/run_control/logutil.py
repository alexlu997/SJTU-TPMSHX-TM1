"""Central logging for the tm1 production packages (print→logging,
openspec change print-to-logging, 2026-07-03).

Usage::

    from tm1.run_control.logutil import get_logger
    _log = get_logger(__name__)
    _log.info("[3D grid] %s", summary)

Design constraints (do not "simplify" these away):

1. **Handler writes to sys.stdout, resolved PER RECORD.** The GUI solve-log
   viewer captures run-local solver output through ``capture_output`` in
   ``controllers/compute_orchestrator.py``. A plain
   ``StreamHandler(sys.stdout)`` binds the stream object at handler-creation
   time, so redirected runs would silently miss every log record. The
   ``_StdoutHandler`` below reads ``sys.stdout`` dynamically, keeping the
   capture path byte-identical with the old ``print()`` behaviour.

2. **Default format is the bare message.** Existing output carries its own
   tags (``[3D grid]``, ``[Coupling n]``, ``[qNEHVI]`` …) and scripts /
   humans eyeball it; the default render is therefore indistinguishable
   from the old prints. Set ``TPMSHX_LOG_TS=1`` for
   ``HH:MM:SS level name: message``.

3. **Level from env** ``TPMSHX_LOG_LEVEL`` (DEBUG/INFO/WARNING/ERROR,
   default INFO). Solver per-iteration traces keep their existing
   ``verbose`` gates — the env level filters on top, it does not replace
   them.

4. **StreamHandler flushes per record**, which retires the "python -u or
   stdout block-buffers and the run looks hung" trap for everything that
   goes through logging.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar

_ROOT_NAME = "tm1"
_configured = False
_output = ContextVar('solver_output', default=None)
_stream_lock = threading.Lock()
_stream_users = 0
_original_streams = None


def current_output():
    """The current run's sinks, explicitly handed to its SIMPLE workers."""
    return _output.get()


@contextmanager
def output_scope(streams):
    token = _output.set(streams)
    try:
        yield
    finally:
        _output.reset(token)


class _RoutedStream:
    def __init__(self, original, index):
        self.original = original
        self.index = index

    def _target(self):
        streams = current_output()
        return self.original if streams is None else streams[self.index]

    def write(self, text):
        target = self._target()
        return len(text) if target is None else target.write(text)

    def flush(self):
        target = self._target()
        if target is not None:
            target.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


@contextmanager
def capture_output(stdout, stderr):
    """Route only this run's writes; unrelated threads retain their own output.

    The lock protects installing/restoring streams, never solver execution.
    Reference counting also permits scopes to finish in either order.
    """
    global _stream_users, _original_streams
    with _stream_lock:
        if _stream_users == 0:
            _original_streams = sys.stdout, sys.stderr
            sys.stdout = _RoutedStream(sys.stdout, 0)
            sys.stderr = _RoutedStream(sys.stderr, 1)
        _stream_users += 1
    try:
        with output_scope((stdout, stderr)):
            yield
    finally:
        with _stream_lock:
            _stream_users -= 1
            if _stream_users == 0:
                sys.stdout, sys.stderr = _original_streams
                _original_streams = None


class _StdoutHandler(logging.StreamHandler):
    """StreamHandler whose stream is ALWAYS the current sys.stdout.

    Required so ``contextlib.redirect_stdout`` (GUI solve-log capture)
    sees log records; see module docstring #1.
    """

    def __init__(self):
        # Parent __init__ assigns self.stream; the property below ignores it.
        super().__init__(sys.stdout)

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value):  # noqa: D401 - deliberate no-op
        pass


def _configure_root():
    global _configured
    if _configured:
        return
    root = logging.getLogger(_ROOT_NAME)
    if not root.handlers:
        h = _StdoutHandler()
        if os.environ.get("TPMSHX_LOG_TS", "0") == "1":
            fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
            h.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        else:
            h.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(h)
    level_name = os.environ.get("TPMSHX_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.propagate = False   # never duplicate into the stdlib root logger
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``tm1`` root (configured on first use).

    ``name`` is usually ``__name__``. Strip a leading ``tm1.`` prefix so that
    both package-qualified and relative subsystem names resolve to
    ``tm1.<subsystem>...``.

    Historical failure record (2026-07-21):
    the taxonomy must not encode packaging history (P1.8b F2: modules now
    execute under package-qualified names; without this, every logger would
    have become ``tpmshx.sjtu_tpmshx.*`` and name-anchored consumers broke).
    """
    _configure_root()
    return logging.getLogger(f"{_ROOT_NAME}.{name.removeprefix('tm1.')}")


def log_zone_report(stats):
    log = get_logger('tm1.solvers.backends.capture_2d')
    log.info("\n[ZONE STATISTICS]")
    log.info(format_zone_report(stats))


def format_zone_report(stats):
    """Format zone statistics into a readable string."""
    lines = []
    for s in stats:
        if s['n_cells'] == 0:
            lines.append(f"  {s['name']}: (empty)")
            continue
        lines.append(f"  {s['name']} (L={s['L_mm']}mm, t={s['t_mm']}mm, "
                     f"{s['n_cells']} cells):")
        lines.append(f"    Ta: {s['Ta_mean']:.1f} +/- {s['Ta_std']:.1f} K "
                     f"[{s['Ta_min']:.1f}, {s['Ta_max']:.1f}]")
        lines.append(f"    Tb: {s['Tb_mean']:.1f} +/- {s['Tb_std']:.1f} K "
                     f"[{s['Tb_min']:.1f}, {s['Tb_max']:.1f}]")
        lines.append(f"    Ts: {s['Ts_mean']:.1f} +/- {s['Ts_std']:.1f} K")
        if 'umag_mean' in s:
            lines.append(f"    |U|: {s['umag_mean']:.3f} m/s "
                         f"(CV={s['umag_cv']:.1%})")
        if 'P_spread' in s:
            lines.append(f"    P spread: {s['P_spread']:.1f} Pa")
    return '\n'.join(lines)
