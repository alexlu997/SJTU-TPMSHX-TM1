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


@pytest.mark.parametrize('mode', ['full', 'screening'])
@pytest.mark.parametrize('error', [RuntimeError, CancelledError])
def test_two_d_residual_failure_preserves_original_exception(monkeypatch, mode, error):
    """Both public consumers propagate failures from the real SIMPLE callback."""
    from dataclasses import replace
    from sjtu_tpmshx.preprocess.api import prepare_screening_2d
    from sjtu_tpmshx.solvers.backends.python.two_d import coupling
    from sjtu_tpmshx.solvers.backends.python.screening import two_d as screening
    from sjtu_tpmshx.tests.test_pipeline_2d_smoke import _shanghai_like_cfg

    def forbidden(*args, **kwargs):
        pytest.fail('thermal solve reached after residual callback failure')

    monkeypatch.setattr(coupling, 'solve_full_domain', forbidden)
    monkeypatch.setattr(screening, 'solve_full_domain', forbidden)
    if mode == 'full':
        config = _shanghai_like_cfg()
        config = replace(config, solver=replace(config.solver, Nx=4, Ny=4,
                                                max_iter_simple=1))
        case = prepare_case(config, case_id='residual-failure')
    else:
        x = np.r_[np.full(8, 6.), np.full(8, .4)]
        case = prepare_screening_2d(x, dict(Nx=4, Ny=4, max_iter_simple=1),
                                   case_id='residual-failure')
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
