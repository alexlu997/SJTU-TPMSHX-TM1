"""The opt-in SIMPLE rejection follows every flow solve in both screeners."""
from collections import Counter
import importlib

import numpy as np
import pytest

from sjtu_tpmshx.preprocess.api import prepare_screening_2d, prepare_screening_3d
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.io.case_io import save_case, load_case
from sjtu_tpmshx.optimization.evaluator import evaluate_design
from sjtu_tpmshx.optimization.evaluator_3d import evaluate_design_3d
from sjtu_tpmshx.optimization.optimizer_qnehvi import _eval_worker


@pytest.mark.parametrize('dimension,failed_solve', [(2, 1), (2, 2), (2, 3), (2, 4),
                                                    (3, 1), (3, 2), (3, 3)])
@pytest.mark.parametrize('reject', [False, True])
def test_explicit_rejection_survives_prepare_replay_and_outer_flow(
        tmp_path, monkeypatch, dimension, failed_solve, reject):
    backend = importlib.import_module('sjtu_tpmshx.solvers.backends.python.screening.'
                                      + ('two_d' if dimension == 2 else 'three_d'))
    counts = Counter()
    def flow(s, **kwargs):
        counts['flow'] += 1
        s.v.fill(1.)
        profile = np.linspace(1000., 0., s.Ny)[None, :]
        s.P[:] = profile if dimension == 2 else profile[:, :, None]
        return counts['flow'] != failed_solve, 1
    def thermal(*args, **kwargs):
        counts['thermal'] += 1
        shape = tuple(args[2:4] if dimension == 2 else args[3:6])
        return (*(np.full(shape, t) for t in (350., 325., 337.5)), {'converged': True})
    solver = backend.SIMPLESolver if dimension == 2 else backend.SIMPLESolver3D
    monkeypatch.setattr(solver, 'solve', flow)
    monkeypatch.setattr(backend, 'solve_full_domain' if dimension == 2 else 'solve_full_domain_3d', thermal)
    x = np.r_[np.full(8, 6.), np.full(8, .4)]
    cfg = dict(u_A=1., u_B=1., T_inA=400., T_inB=300., reject_unconverged=reject,
               Nx=4, Ny=4, n_rho_loops=2, penalty_enabled=False,
               Nx_3d=4, Ny_3d=4, Nz_3d=2, max_outer_3d=2,
               roughness_mode='baseline', roughness_eps_um=0.)
    if dimension == 2:
        case = prepare_screening_2d(x, cfg, case_id='flow-verdict')
        evaluator = evaluate_design
    else:
        case = prepare_screening_3d(x, cfg, case_id='flow-verdict', Nx=4, Ny=4, Nz=2,
            max_outer=2, roughness_mode='baseline', roughness_eps_um=0., verbose=False)
        evaluator = evaluate_design_3d
    save_case(case, tmp_path / 'case.h5')
    result = run_case(load_case(tmp_path / 'case.h5'))
    metrics = evaluate(result).metrics
    assert result.run_status['execution'] == ('rejected' if reject else 'completed')
    if reject:
        assert result.run_status['converged'] is False
        assert result.run_status['rejection_stage'] == ('initial_flow' if failed_solve <= 2 else 'outer_flow')
        assert metrics['Q'].value is None and metrics['Q'].status == 'invalid'
        assert counts['thermal'] == (0 if failed_solve <= 2 else 1)
    else:
        assert counts['thermal'] == 2  # Preserve default finite-unconverged screening.
        assert metrics['Q'].value is not None
    assert metrics['mass'].status == 'available' and metrics['mass'].value > 0
    counts.clear()
    Q, pressure, error = _eval_worker(x, cfg, 1e6, evaluator)
    if reject:
        assert (Q, pressure) == (1e-6, 1e6)
        assert error == 'evaluator rejected design (bounded penalty)'
    else:
        assert np.isfinite(Q) and np.isfinite(pressure) and error is None
