"""Actual screening rejection/cancellation remain explicit across result files."""
from dataclasses import replace
import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_screening_2d
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.io.result_io import save_result, load_result


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
