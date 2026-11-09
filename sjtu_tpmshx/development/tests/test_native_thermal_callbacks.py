"""Thermal callback lifetime, failure propagation and per-call isolation."""
from concurrent.futures import ThreadPoolExecutor
import gc
from threading import Barrier

import pytest

from sjtu_tpmshx.solvers.backends.cpp._thermal_abi import make_callbacks


def test_callback_lifetime_and_optional_progress():
    events = []
    callbacks, errors = make_callbacks(lambda: False, lambda *values: events.append(values))
    gc.collect()
    assert callbacks.cancel(None) == 0
    callbacks.progress(None, 3, 7)
    assert events == [(3, 7)]
    assert all(type(value) is int for value in events[0])
    assert errors == []

    callbacks, errors = make_callbacks(None, None)
    assert callbacks.cancel(None) == 0
    assert not callbacks.progress
    assert errors == []


@pytest.mark.parametrize('stage', ['cancel', 'progress'])
def test_callback_failure_keeps_identity_and_stops_host_hooks(stage):
    marker = BaseException('thermal callback sentinel')
    events = []

    def fail(*_):
        events.append(stage)
        raise marker

    callbacks, errors = make_callbacks(fail, fail)
    if stage == 'cancel':
        assert callbacks.cancel(None) == 1
    else:
        callbacks.progress(None, 1, 3)
    assert callbacks.cancel(None) == 1
    callbacks.progress(None, 2, 3)
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
        callbacks.progress(None, 1, 3)
        return callbacks.cancel(None), errors

    with ThreadPoolExecutor(2) as pool:
        failed, successful = list(pool.map(run, (True, False)))
    assert failed[0] == 1 and len(failed[1]) == 1 and failed[1][0] is marker
    assert successful == (0, [])
