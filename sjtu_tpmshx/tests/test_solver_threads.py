"""Numba thread-count control helper (`solvers/threads.py`)."""
import numba
import pytest
import sjtu_tpmshx.solvers.threads as th


def test_clamp_to_max_and_min():
    mx = th.max_threads()
    assert mx >= 1
    assert th.set_solver_threads(10 ** 9) == mx      # over-cap clamps to max
    assert th.get_solver_threads() == mx
    assert th.set_solver_threads(0) == 1             # under clamps to 1
    assert th.set_solver_threads(-5) == 1
    th.set_solver_threads(mx)                         # restore


def test_set_exact_value_within_range():
    mx = th.max_threads()
    target = max(1, mx // 2)
    assert th.set_solver_threads(target) == target
    assert th.get_solver_threads() == target
    assert numba.get_num_threads() == target
    th.set_solver_threads(mx)


def test_init_from_env_honors_project_var(monkeypatch):
    mx = th.max_threads()
    monkeypatch.setenv("TPMSHX_NUM_THREADS", "1")
    assert th.init_from_env() == 1
    # invalid → no change (stays at last value, here 1)
    monkeypatch.setenv("TPMSHX_NUM_THREADS", "garbage")
    assert th.init_from_env() == 1
    monkeypatch.delenv("TPMSHX_NUM_THREADS", raising=False)
    th.set_solver_threads(mx)


# ── P3.2: recommendation + one-shot advisory ─────────────────────────────────

def test_recommend_within_bounds():
    rec = th.recommend_solver_threads()
    assert isinstance(rec, int)
    assert 1 <= rec <= min(64, th.max_threads())


def _fake_big_box(monkeypatch, active=128, cap=128, rec=32):
    """Simulate an unpinned many-core machine without touching numba."""
    monkeypatch.setattr(th, "get_solver_threads", lambda: active)
    monkeypatch.setattr(th, "max_threads", lambda: cap)
    monkeypatch.setattr(th, "recommend_solver_threads", lambda: rec)
    monkeypatch.setattr(th, "_advised_default_pool", False)
    monkeypatch.delenv("TPMSHX_NUM_THREADS", raising=False)


class _Capture:
    """logutil's package root sets propagate=False (deliberate), so pytest's
    caplog (root-logger handler) never sees these records — attach a handler
    directly to the module logger instead."""

    def __init__(self):
        import logging
        self.records = []
        # logutil namespaces under the `tpmshx.` root (get_logger docstring)
        self._lg = logging.getLogger('tpmshx.solvers.threads')
        self._h = logging.Handler()
        self._h.emit = self.records.append

    def __enter__(self):
        self._lg.addHandler(self._h)
        return self

    def __exit__(self, *exc):
        self._lg.removeHandler(self._h)


def test_advisory_fires_once_on_unpinned_default(monkeypatch):
    _fake_big_box(monkeypatch)
    with _Capture() as cap:
        assert th.warn_if_default_pool(1_000_000) == 32
        assert th.warn_if_default_pool(1_000_000) == 32   # second call silent
    hits = [r for r in cap.records if "TPMSHX_NUM_THREADS" in r.getMessage()]
    assert len(hits) == 1
    assert "Advisory only" in hits[0].getMessage()


def test_advisory_silent_when_pinned_or_small(monkeypatch):
    # user pinned the env → silent
    _fake_big_box(monkeypatch)
    monkeypatch.setenv("TPMSHX_NUM_THREADS", "32")
    with _Capture() as cap:
        th.warn_if_default_pool(1_000_000)
    assert not cap.records
    # active lowered below cap (GUI spinbox) → silent
    _fake_big_box(monkeypatch, active=16, cap=128, rec=32)
    with _Capture() as cap:
        th.warn_if_default_pool(1_000_000)
    assert not cap.records
    # small machine: cap == rec → silent
    _fake_big_box(monkeypatch, active=8, cap=8, rec=8)
    with _Capture() as cap:
        th.warn_if_default_pool(1_000_000)
    assert not cap.records


@pytest.mark.parametrize('limit', [None, 1])
@pytest.mark.parametrize('fail', [False, True])
def test_public_python_run_restores_the_calling_thread_mask(monkeypatch, limit, fail):
    from sjtu_tpmshx.domain.field_result import FieldResult
    from sjtu_tpmshx.domain.module_ports import RunControl
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.solvers.backends.python.two_d import execution
    from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case

    case = sample_case()
    previous = th.get_solver_threads()
    initial = th.set_solver_threads(min(2, th.max_threads()))
    seen = []
    def solve(*args):
        seen.append(th.get_solver_threads())
        if fail:
            raise RuntimeError('controlled solver failure')
        return FieldResult('thread-test', case.case_id, 'python', grid=case.grid,
                           run_status={'execution': 'completed', 'converged': False})
    monkeypatch.setattr(execution, 'run_case', solve)
    monkeypatch.setattr('sjtu_tpmshx.solvers.execution_record.full_execution_record', lambda *args: {})
    monkeypatch.setattr('sjtu_tpmshx.solvers.applicability_evidence.capture_applicability', lambda *args: {})
    try:
        if fail:
            with pytest.raises(RuntimeError, match='controlled solver failure'):
                run_case(case, RunControl(cpu_threads=limit))
        else:
            run_case(case, RunControl(cpu_threads=limit))
        assert seen == [initial if limit is None else 1]
        assert th.get_solver_threads() == initial
    finally:
        th.set_solver_threads(previous)
