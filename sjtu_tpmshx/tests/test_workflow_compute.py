"""Common stage order, cancellation, progress and immutable run evidence."""
from threading import Event

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import current_warnings, record_warning
from sjtu_tpmshx.workflows.compute import compute


@pytest.fixture
def native_result():
    return FieldResult('result', 'case', 'test', fields={'Ta': np.arange(6.)},
                       metadata={'diagnostics': {'warnings_list': ['solver notice']},
                                 'units': {'Q': 'W'}})


@pytest.mark.parametrize('progress_enabled', [True, False])
def test_stage_order_progress_timing_and_shared_storage(monkeypatch, native_result, progress_enabled):
    clock, calls, overall, raw = [0.], [], [], []
    case, performance = object(), object()
    monkeypatch.setattr('sjtu_tpmshx.workflows.compute.perf_counter', lambda: clock[0])

    def prepare(config, *, case_id):
        assert case_id == native_result.case_id
        calls.append('prepare')
        clock[0] += 1.
        assert record_warning('prepare', 'prepare notice')
        return case

    def solve(prepared, control):
        assert prepared is case
        assert control.backend == 'cpp' and control.native_library == '/host/library'
        calls.append('solve')
        clock[0] += 2.
        control.report_progress(50)
        assert record_warning('solve', 'solver notice')
        return native_result

    def evaluate(result):
        assert result is native_result
        calls.append('postprocess')
        clock[0] += 3.
        assert record_warning('postprocess', 'postprocess notice')
        return performance

    def progress(percent):
        overall.append(percent)
        # Stage callbacks are outside timing; in-solver callbacks are inside.
        if percent in (20, 90, 100):
            clock[0] += 100.

    actual_case, result, actual_performance = compute(ComputeConfig(), case_id='case',
        control=RunControl(backend='cpp', native_library='/host/library', progress=raw.append),
        progress_cb=progress if progress_enabled else None,
        prepare=prepare, solve=solve, evaluate=evaluate)
    assert actual_case is case and actual_performance is performance
    assert calls == ['prepare', 'solve', 'postprocess']
    assert overall == ([20, 55, 90, 100] if progress_enabled else [])
    assert raw == [50]
    assert result.metadata['timings_s'] == {'prepare': 1., 'solve': 2., 'postprocess': 3.}
    assert result.metadata['units'] == {'Q': 'W'}
    assert result.metadata['diagnostics']['warnings_list'] == (
        'solver notice', 'prepare notice', 'postprocess notice')
    assert result.result_id == native_result.result_id
    assert result.case_id == native_result.case_id
    assert np.shares_memory(result.fields['Ta'], native_result.fields['Ta'])
    with pytest.raises(ValueError):
        result.fields['Ta'].setflags(write=True)
    assert 'timings_s' not in native_result.metadata
    assert current_warnings() is None


@pytest.mark.parametrize('stage', ['before', 'prepare', 'solve', 'postprocess', 'complete'])
def test_cancelled_work_never_returns_result(native_result, stage):
    cancelled, calls, progress = Event(), [], []
    if stage == 'before':
        cancelled.set()

    def run_stage(name, result):
        calls.append(name)
        if stage == name:
            cancelled.set()
        return result

    def report(percent):
        progress.append(percent)
        if stage == 'complete' and percent == 100:
            cancelled.set()

    with pytest.raises(CancelledError):
        compute(ComputeConfig(), control=RunControl(cancel_check=cancelled.is_set),
                progress_cb=report,
                prepare=lambda config, case_id: run_stage('prepare', object()),
                solve=lambda case, control: run_stage('solve', native_result),
                evaluate=lambda result: run_stage('postprocess', object()))
    expected = ['prepare', 'solve', 'postprocess']
    count = {'before': 0, 'prepare': 1, 'solve': 2, 'postprocess': 3, 'complete': 3}[stage]
    assert calls == expected[:count]
    assert (100 in progress) == (stage == 'complete')
    assert current_warnings() is None


@pytest.mark.parametrize('outcome', ['completed', 'cancelled', 'failed'])
def test_postprocess_outcome(native_result, outcome):
    cancelled = Event()
    case, performance = object(), object()
    error = ValueError('invalid result evidence')

    def evaluate(field_result):
        assert field_result is native_result
        if outcome != 'completed':
            cancelled.set()
        if outcome == 'failed':
            raise error
        return performance

    def run():
        return compute(ComputeConfig(), case_id='cancel-after-postprocess',
            control=RunControl(cancel_check=cancelled.is_set),
            prepare=lambda config, case_id: case,
            solve=lambda prepared, control: native_result, evaluate=evaluate)

    if outcome == 'completed':
        actual_case, result, actual_performance = run()
        assert actual_case is case and actual_performance is performance
        assert result.result_id == native_result.result_id
    elif outcome == 'cancelled':
        with pytest.raises(CancelledError):
            run()
    else:
        with pytest.raises(ValueError) as caught:
            run()
        assert caught.value is error


def test_invalid_config_never_reaches_preparation():
    config = ComputeConfig()
    config.solver.Nx = 0
    with pytest.raises(ValueError):
        compute(config, prepare=lambda *a, **k: pytest.fail('invalid config prepared'))


@pytest.mark.parametrize('outcome', ['completed', 'cancelled', 'failed'])
def test_application_mapping_keeps_cancellation_and_real_errors(monkeypatch, outcome):
    from sjtu_tpmshx.controllers import module_adapter
    cancelled = Event()
    native, performance, display = object(), object(), object()
    error = ValueError('invalid application evidence')
    monkeypatch.setattr('sjtu_tpmshx.workflows.compute.compute',
                        lambda *a, **k: (object(), native, performance))

    def map_result(result, metrics):
        assert result is native and metrics is performance
        if outcome != 'completed':
            cancelled.set()
        if outcome == 'failed':
            raise error
        return display

    monkeypatch.setattr(module_adapter, 'to_compute_result', map_result)
    control = RunControl(cancel_check=cancelled.is_set)
    if outcome == 'completed':
        assert module_adapter.compute_result(ComputeConfig(), control=control) is display
    else:
        with pytest.raises(CancelledError if outcome == 'cancelled' else ValueError) as caught:
            module_adapter.compute_result(ComputeConfig(), control=control)
        if outcome == 'failed':
            assert caught.value is error
