"""Real backend observations cross the public non-persistent control port."""
import pytest
import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg


@pytest.mark.slow
def test_public_three_d_iteration_and_cancellation(monkeypatch, tmp_path):
    from sjtu_tpmshx.solvers.backends.cpp import full_3d_capture as result_capture
    from sjtu_tpmshx.io.result_io import load_result, save_result
    capture = result_capture.capture_result
    def checked_capture(case, cfg, prepared, raw, abi):
        assert not {'_capture_native', '_native_evidence', '_cancel_check',
                    '_progress_cb', '_iter_cb'}.intersection(cfg)
        result = capture(case, cfg, prepared, raw, abi)
        for side, flow in zip('AB', raw['flow']):
            np.testing.assert_array_equal(result.fields['P_f'+side+'_display'], flow['pressure_real'])
            for axis, value in zip(('uc', 'vc', 'wc'), flow['velocity_real']):
                np.testing.assert_array_equal(result.fields[axis+side], value)
        return result
    monkeypatch.setattr(result_capture, 'capture_result', checked_capture)
    config = _small_air_cfg()
    case = prepare_case(config, case_id='B30-controls')
    with pytest.raises(CancelledError):
        run_case(case, RunControl(cancel_check=lambda: True))
    iterations, progress, outer_iterations = [], [], []
    def report_outer(current, total):
        assert iterations[-1] == f'outer {current}/{total}'
        outer_iterations.append((current, total))
    result = run_case(case, RunControl(iteration=iterations.append, progress=progress.append,
                                      outer_iteration=report_outer))
    assert result.run_status['converged'] is True
    total = result.metadata['diagnostics']['_max_outer']
    assert iterations == [f'outer {index + 1}/{total}'
                          for index in range(result.run_status['outer_index'] + 1)]
    assert outer_iterations == [(index + 1, total) for index in range(len(iterations))]
    assert progress[-1] == 100
    assert 'iteration' not in case.parameters
    save_result(result, tmp_path / 'results.h5')
    loaded = load_result(tmp_path / 'results.h5')
    for name in result.fields:
        np.testing.assert_array_equal(loaded.fields[name], result.fields[name])


@pytest.mark.parametrize('callback', ['iteration', 'outer_iteration', 'progress'])
def test_three_d_callback_failure_stops_before_result_capture(monkeypatch, callback):
    from sjtu_tpmshx.solvers.backends.cpp import full_3d_capture
    failure = RuntimeError('callback failure')
    def fail(*args):
        raise failure
    monkeypatch.setattr(full_3d_capture, 'capture_result',
                        lambda *a, **k: pytest.fail('result capture after callback failure'))
    with pytest.raises(RuntimeError) as caught:
        run_case(prepare_case(_small_air_cfg(), case_id='callback-failure'),
                 RunControl(**{callback: fail}))
    assert caught.value is failure


@pytest.mark.parametrize('error', [RuntimeError, CancelledError])
def test_two_d_residual_failure_preserves_original_exception(monkeypatch, error):
    """The full public solve propagates failures from the real SIMPLE callback."""
    from dataclasses import replace
    from sjtu_tpmshx.solvers.backends.cpp import full_2d_capture
    from sjtu_tpmshx.tests.test_pipeline_2d_smoke import _shanghai_like_cfg

    def forbidden(*args, **kwargs):
        pytest.fail('result capture after residual callback failure')

    monkeypatch.setattr(full_2d_capture, 'capture_result', forbidden)
    config = _shanghai_like_cfg()
    config = replace(config, solver=replace(config.solver, Nx=4, Ny=4,
                                            max_iter_simple=1))
    case = prepare_case(config, case_id='residual-failure')
    failure = error('residual callback failure')
    calls = []

    def fail(*args):
        calls.append(args)
        raise failure

    with pytest.raises(error) as caught:
        run_case(case, RunControl(residual=fail))
    assert caught.value is failure
    assert calls and all(side in ('A', 'B') and index == 1
                         for side, index, residual in calls)
