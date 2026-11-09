"""SIMPLE callback lifetime, optional hooks and isolated failures."""
from concurrent.futures import ThreadPoolExecutor
import gc
from threading import Barrier

import pytest

from sjtu_tpmshx.solvers.backends.cpp._simple_abi import make_callbacks


@pytest.mark.parametrize('with_cancel', [False, True])
@pytest.mark.parametrize('with_progress', [False, True])
def test_callback_lifetime_and_optional_hooks(with_cancel, with_progress):
    events = []
    callbacks, errors = make_callbacks(
        (lambda: True) if with_cancel else None,
        (lambda *values: events.append(values)) if with_progress else None)
    gc.collect()
    assert bool(callbacks.cancel) == (with_cancel or with_progress)
    assert bool(callbacks.progress) == with_progress
    assert callbacks.context is None
    if callbacks.cancel:
        assert callbacks.cancel(None) == int(with_cancel)
    if callbacks.progress:
        callbacks.progress(None, 3, .125)
        assert events == [(3, .125)]
        assert type(events[0][0]) is int and type(events[0][1]) is float
    assert errors == []


@pytest.mark.parametrize('stage', ['cancel', 'progress'])
def test_first_callback_failure_stops_host_hooks(stage):
    marker = BaseException('SIMPLE callback sentinel')
    events = []

    def fail(*_):
        events.append(stage)
        raise marker

    callbacks, errors = make_callbacks(fail, fail)
    if stage == 'cancel':
        assert callbacks.cancel(None) == 1
    else:
        callbacks.progress(None, 1, .5)
    assert callbacks.cancel(None) == 1
    callbacks.progress(None, 2, .25)
    assert events == [stage]
    assert len(errors) == 1 and errors[0] is marker


def test_concurrent_callback_failures_are_isolated():
    barrier = Barrier(2)
    marker = BaseException('one call failed')

    def run(fail):
        def progress(*_):
            barrier.wait(timeout=10)
            if fail:
                raise marker

        callbacks, errors = make_callbacks(None, progress)
        callbacks.progress(None, 1, .5)
        return callbacks.cancel(None), errors

    with ThreadPoolExecutor(2) as pool:
        failed, successful = list(pool.map(run, (True, False)))
    assert failed[0] == 1 and len(failed[1]) == 1 and failed[1][0] is marker
    assert successful == (0, [])
