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
    from sjtu_tpmshx.solvers.backends.python.three_d import result_capture
    from sjtu_tpmshx.io.result_io import load_result, save_result
    capture = result_capture.capture_result
    def checked_capture(case, problem, outer, raw, diagnostics):
        assert not {'_capture_native', '_native_evidence', '_cancel_check',
                    '_progress_cb', '_iter_cb'}.intersection(problem.cfg)
        result = capture(case, problem, outer, raw, diagnostics)
        for name, source in (('P_fA_display', 'P_Pa'), ('P_fB_display', 'P_Pa_B'),
                             ('ucA', 'uc_real'), ('vcA', 'vc_real'), ('wcA', 'wc_real'),
                             ('ucB', 'uc_real_B'), ('vcB', 'vc_real_B'), ('wcB', 'wc_real_B')):
            np.testing.assert_array_equal(result.fields[name], raw[source])
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
def test_three_d_callback_failure_stops_before_thermal(monkeypatch, callback):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    failure = RuntimeError('callback failure')
    def fail(*args):
        raise failure
    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    monkeypatch.setattr(runtime, 'solve_full_domain_3d',
                        lambda *a, **k: pytest.fail('thermal solve after callback failure'))
    with pytest.raises(RuntimeError) as caught:
        run_case(prepare_case(_small_air_cfg(), case_id='callback-failure'),
                 RunControl(**{callback: fail}))
    assert caught.value is failure
