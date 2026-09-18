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
