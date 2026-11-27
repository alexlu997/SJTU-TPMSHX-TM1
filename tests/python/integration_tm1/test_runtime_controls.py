"""Real backend observations cross the public non-persistent control port."""
import pytest
import numpy as np

from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from tests.python.cases_3d import small_air_config


@pytest.mark.slow
def test_public_three_d_iteration_and_cancellation(monkeypatch, tmp_path):
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    from sjtu_tpmshx.solvers import full_3d as result_capture
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    capture = result_capture.capture_result
    def checked_capture(case, cfg, prepared, raw, abi):
        assert not {'_capture_native', '_native_evidence', '_cancel_check',
                    '_progress_cb', '_iter_cb'}.intersection(cfg)
        return capture(case, cfg, prepared, raw, abi)
    config = small_air_config()
    case = prepare_case(config, case_id='B30-controls')
    with pytest.raises(CancelledError):
        run_case(case, RunControl(cancel_check=lambda: True))
    iterations, progress, outer_iterations = [], [], []
    def report_outer(current, total):
        assert iterations[-1] == f'outer {current}/{total}'
        outer_iterations.append((current, total))
    from tests.python.native.stage_interception import native_3d_arrays
    detach, raw = full_3d_stage._detach, []
    def copied(native, shape, *args, **kwargs):
        raw.append(native_3d_arrays(native, shape))
        return detach(native, shape, *args, **kwargs)
    with monkeypatch.context() as capture_hook:
        capture_hook.setattr(result_capture, 'capture_result', checked_capture)
        capture_hook.setattr(full_3d_stage, '_detach', copied)
        result = run_case(case, RunControl(iteration=iterations.append, progress=progress.append,
                                          outer_iteration=report_outer))
    # The published fields equal the raw native real-axis arrays of the same run.
    for side, flow in zip('AB', raw[0]['flow']):
        np.testing.assert_array_equal(result.fields['P_f' + side + '_display'], flow['pressure_real'])
        for axis, value in zip(('uc', 'vc', 'wc'), flow['velocity_real']):
            np.testing.assert_array_equal(result.fields[axis + side], value)
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
    from sjtu_tpmshx.solvers import full_3d
    failure = RuntimeError('callback failure')
    def fail(*args):
        raise failure
    monkeypatch.setattr(full_3d, 'capture_result',
                        lambda *a, **k: pytest.fail('result capture after callback failure'))
    with pytest.raises(RuntimeError) as caught:
        run_case(prepare_case(small_air_config(), case_id='callback-failure'),
                 RunControl(**{callback: fail}))
    assert caught.value is failure


@pytest.mark.parametrize('error', [RuntimeError, CancelledError])
def test_two_d_residual_failure_preserves_original_exception(monkeypatch, error):
    """The full public solve propagates failures from the real SIMPLE callback."""
    from dataclasses import replace
    from sjtu_tpmshx.solvers import full_2d
    from tests.python.execution_tm1.test_pipeline_2d_smoke import _shanghai_like_cfg

    def forbidden(*args, **kwargs):
        pytest.fail('result capture after residual callback failure')

    monkeypatch.setattr(full_2d, 'capture_result', forbidden)
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
