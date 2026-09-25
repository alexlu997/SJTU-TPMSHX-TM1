"""Cancellation remains authoritative through the last workflow stage."""
from threading import Event

import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.workflows.compute import compute


@pytest.mark.parametrize('outcome', ['completed', 'cancelled', 'failed'])
def test_postprocess_outcome(outcome):
    cancelled = Event()
    case, result, performance = object(), object(), object()
    error = ValueError('invalid result evidence')

    def evaluate(field_result):
        assert field_result is result
        if outcome != 'completed':
            cancelled.set()
        if outcome == 'failed':
            raise error
        return performance

    def run():
        return compute(
            {}, case_id='cancel-after-postprocess',
            control=RunControl(cancel_check=cancelled.is_set),
            prepare=lambda config, case_id: case,
            solve=lambda prepared, control: result,
            evaluate=evaluate,
        )

    if outcome == 'completed':
        assert run() == (case, result, performance)
    elif outcome == 'cancelled':
        with pytest.raises(CancelledError):
            run()
    else:
        with pytest.raises(ValueError) as caught:
            run()
        assert caught.value is error
