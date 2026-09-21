"""Actual screening rejection/cancellation remain explicit across result files."""
from dataclasses import replace
import importlib
import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_quick_design, prepare_screening_2d, prepare_screening_3d
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.io.result_io import save_result, load_result
from sjtu_tpmshx.io.case_io import save_case, load_case


def test_rejected_screen_and_native_low_budget(tmp_path):
    x = np.r_[np.full(8, 6.), np.full(8, .4)]
    cfg = dict(Nx=4, Ny=4, max_iter_simple=1, max_iter_energy=1, n_rho_loops=1)
    case = prepare_screening_2d(x, {**cfg, 'u_A': 1.e6}, case_id='choked')
    assert case.parameters['rejection']
    with pytest.raises(ValueError, match='unsupported screening design field'):
        run_case(replace(case, design_fields={**case.design_fields, 'unknown': np.ones((4, 4))}))
    result = run_case(case)
    assert result.run_status['execution'] == 'rejected'
    assert result.run_status['converged'] is False and 'Ta' not in result.fields
    path = tmp_path / 'rejected.h5'
    save_result(result, path)
    restored = load_result(path)
    metrics = evaluate(restored).metrics
    assert metrics['Q'].status == 'invalid' and metrics['Q'].value is None
    assert metrics['mass'].status == 'available' and metrics['mass'].value > 0.
    with pytest.raises(ValueError, match='reason'):
        save_result(replace(result, run_status={'execution': 'rejected', 'converged': False}), path)
    with pytest.raises(CancelledError):
        run_case(case, RunControl(cancel_check=lambda: True))
    finite = run_case(prepare_screening_2d(x, cfg, case_id='low-budget'))
    assert finite.run_status['execution'] == 'completed'
    assert finite.run_status['converged'] is False
    assert evaluate(finite).metrics['Q'].status == 'available'


@pytest.mark.parametrize('mode', ['quick_design', 'screening_2d', 'screening_3d'])
@pytest.mark.parametrize('kernel', ['numba', 'cpp_sweeps_v1'])
def test_approximation_mode_freezes_kernel_before_handoff(monkeypatch, tmp_path, mode, kernel):
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', kernel)
    monkeypatch.setenv('TPMSHX_THERMAL_LIBRARY', '/prepared/thermal.so')
    if mode == 'quick_design':
        from sjtu_tpmshx.tests.design.test_forward import _case
        case = prepare_quick_design(_case(), 'Diamond', 7., .5, .084, .05, case_id='frozen-kernel')
        backend = 'quick_design.execution'
    else:
        x = np.r_[np.full(8, 6.), np.full(8, .4)]
        if mode == 'screening_2d':
            case = prepare_screening_2d(x, dict(Nx=4, Ny=4), case_id='frozen-kernel')
            backend = 'screening.two_d'
        else:
            case = prepare_screening_3d(x, {}, case_id='frozen-kernel', Nx=4, Ny=4, Nz=2,
                roughness_mode='baseline', roughness_eps_um=100., verbose=False)
            backend = 'screening.three_d'
    save_case(case, tmp_path / 'case.h5')
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'cpp_sweeps_v1' if kernel == 'numba' else 'numba')
    monkeypatch.setenv('TPMSHX_THERMAL_LIBRARY', '/receiver/thermal.so')
    restored = load_case(tmp_path / 'case.h5')
    assert restored.parameters['_environment']['TPMSHX_TRUE_H_KERNEL'] == kernel
    assert restored.parameters['_environment']['TPMSHX_THERMAL_LIBRARY'] == '/prepared/thermal.so'
    reached = []

    def dispatch(*args, **kwargs):
        reached.append(True)
        raise RuntimeError('dispatch sentinel; no numerical solve')

    module = importlib.import_module('sjtu_tpmshx.solvers.backends.python.' + backend)
    monkeypatch.setattr(module, 'run_case', dispatch)
    if kernel == 'numba':
        with pytest.raises(RuntimeError, match='dispatch sentinel'):
            run_case(restored)
        assert reached == [True]
    else:
        with pytest.raises(ValueError, match='full two-fluid true-h'):
            run_case(restored)
        assert reached == []
