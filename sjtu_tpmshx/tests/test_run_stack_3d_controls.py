"""The retained dictionary entry uses the same explicit controls as the backend."""

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem, _run_3d_stack
from sjtu_tpmshx.tests.test_convergence_truth_table import _cheap_3d


@pytest.mark.parametrize('entry', [_build_3d_problem, _run_3d_stack])
def test_cancelled_dictionary_entry_stops_before_preparation(entry):
    with pytest.raises(CancelledError):
        entry({}, control=RunControl(cancel_check=lambda: True))


@pytest.mark.parametrize('entry', [_build_3d_problem, _run_3d_stack])
def test_dictionary_entry_rejects_unsupported_backend(entry):
    with pytest.raises(ValueError, match='unsupported backend: unknown'):
        entry({}, control=RunControl(backend='unknown'))


@pytest.mark.parametrize('entry', [_build_3d_problem, _run_3d_stack])
@pytest.mark.parametrize('key, port', [
    ('_cancel_check', 'cancel_check'),
    ('_progress_cb', 'progress'),
    ('_iter_cb', 'outer_iteration'),
])
def test_retired_dictionary_controls_explain_migration(entry, key, port):
    with pytest.raises(ValueError, match=rf'{key}.*RunControl\({port}='):
        entry({key: lambda *args: None})


def test_dictionary_cancellation_reaches_initial_simple():
    checks = []

    def cancel_after_entry():
        checks.append(True)
        return len(checks) > 1

    with pytest.raises(CancelledError):
        _build_3d_problem(_cheap_3d(), control=RunControl(cancel_check=cancel_after_entry))
    assert len(checks) > 1


def test_dictionary_callbacks_preserve_results_and_order():
    cfg = _cheap_3d(max_outer_ltne=2)
    baseline = _run_3d_stack(cfg)
    events = []
    result = _run_3d_stack(cfg, control=RunControl(
        iteration=lambda message: events.append(('iteration', message)),
        outer_iteration=lambda current, total: events.append(('outer', (current, total))),
        progress=lambda percent: events.append(('progress', percent)),
    ))
    count = result['convergence_detail']['outer_iters']
    assert count > 0
    assert len(events) == 3 * count
    for index in range(count):
        assert events[3 * index] == ('iteration', f'outer {index + 1}/2')
        assert events[3 * index + 1] == ('outer', (index + 1, 2))
        assert events[3 * index + 2][0] == 'progress'
        assert 0 <= events[3 * index + 2][1] <= 100
    for name in ('Ta', 'Tb', 'Ts', 'P_Pa', 'P_Pa_B'):
        np.testing.assert_array_equal(result[name], baseline[name])
    assert result['solver_converged'] == baseline['solver_converged']
    assert count == baseline['convergence_detail']['outer_iters']


def test_dictionary_cancellation_reaches_outer_thermal_solve():
    progress = []
    with pytest.raises(CancelledError):
        _run_3d_stack(_cheap_3d(), control=RunControl(
            progress=progress.append, cancel_check=lambda: bool(progress)))
    assert len(progress) == 1


@pytest.mark.parametrize('callback', ['iteration', 'outer_iteration', 'progress'])
def test_dictionary_callback_exception_propagates(callback):
    failure = RuntimeError('dictionary callback failure')

    def fail(*args):
        raise failure

    with pytest.raises(RuntimeError) as caught:
        _run_3d_stack(_cheap_3d(), control=RunControl(**{callback: fail}))
    assert caught.value is failure


@pytest.mark.parametrize('cap,last_raw,last_pipeline', [(4, 70, 69), (12, 83, 78), (24, 86, 80)])
def test_outer_progress_uses_effective_budget_through_pipeline(monkeypatch, cap, last_raw, last_pipeline):
    """Exercise real callbacks and pipeline mapping; stop before thermal work."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, GeometryConfig, SolverConfig
    from sjtu_tpmshx.solvers import api
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime

    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(_cheap_3d(max_outer_ltne=cap))
    hv = runtime._build_hv_machinery(prob)
    raw, mapped, counts = [], [], []

    class BeforeThermal(Exception):
        pass

    class FinishedProbe(Exception):
        pass

    def outer_loop(*, max_iter, step, **kwargs):
        assert max_iter == cap
        for index in range(max_iter):
            with pytest.raises(BeforeThermal):
                step(index)
        raise FinishedProbe

    def run_case(case, control):
        def progress(percent):
            raw.append(percent)
            control.report_progress(percent)
            raise BeforeThermal

        with pytest.raises(FinishedProbe):
            runtime._run_outer_coupling_3d(prob, hv, control=RunControl(
                progress=progress,
                outer_iteration=lambda current, total: counts.append((current, total))))

    monkeypatch.setattr(runtime, 'run_outer_coupling', outer_loop)
    monkeypatch.setattr(api, 'run_case', run_case)
    cfg = ComputeConfig(geometry=GeometryConfig(Lz_m=.02), solver=SolverConfig(Nz=3))
    Pipeline3D(cfg, progress_cb=mapped.append).run_solvers(None)
    assert counts == [(index + 1, cap) for index in range(cap)]
    assert raw[0] == 10 and raw[-1] == last_raw
    assert all(0 <= p < 90 for p in raw)
    assert raw == sorted(raw)
    assert mapped[0] == 27 and mapped[-1] == last_pipeline
    assert all(20 <= p < 90 for p in mapped)


def test_initial_single_fluid_profile_reports_effective_simple_cap(monkeypatch):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime

    calls, messages = [], []

    def solve(self, **kwargs):
        calls.append(kwargs['max_iter'])
        return True, 0

    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', solve)
    monkeypatch.setenv('TPMSHX_PROFILE_3D', '1')
    monkeypatch.setattr(runtime._log, 'info', lambda message, *a, **k: messages.append(message))
    cfg = _cheap_3d(max_iter_simple=37)
    cfg['fluid_B_cfg'] = None
    _build_3d_problem(cfg)
    assert calls == [37]
    initial = next(message for message in messages if 'initial SIMPLE_A (serial, no-B)' in message)
    assert '(cap=37)' in initial
