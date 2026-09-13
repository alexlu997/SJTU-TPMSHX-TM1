"""Rejected evaluations stay traceable but cannot become selected designs."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.optimization import optimizer_qnehvi as bo
from sjtu_tpmshx.optimization.parallel_runner import _merge_paretos
from sjtu_tpmshx.optimization.export_ntop_csv import export_pareto_row


@pytest.mark.parametrize('all_failed', [False, True])
def test_worker_checkpoint_history_and_multiseed_keep_failure_status(tmp_path, all_failed):
    def failed(*args):
        raise RuntimeError('injected solve failure')
    evaluators = [failed, lambda *a: (-999., 120., 1.),
                  failed if all_failed else lambda *a: (-12., 20., 1.)]
    X = np.tile(np.r_[np.full(8, 6.), np.full(8, .4)], (3, 1))
    outcomes = [bo._eval_worker(x, {}, 100., evaluator)
                for x, evaluator in zip(X, evaluators)]
    errors = [row[2] for row in outcomes]
    Y = np.array([[Q, -np.log10(dp)] for Q, dp, _ in outcomes])
    tensor = lambda value: SimpleNamespace(numpy=lambda: value)
    bo._save_current_pareto(tensor(X), tensor(Y), str(tmp_path), 5, errors)
    assert errors[0] == "RuntimeError('injected solve failure')"
    assert errors[1] == 'dP exceeds dp_cap'
    expected_count = 0 if all_failed else 1
    for name in ('pareto_latest.csv', 'pareto_iter0005.csv'):
        assert len((tmp_path / name).read_text().splitlines()) == expected_count + 1
    history = np.loadtxt(tmp_path / 'history.csv', delimiter=',', skiprows=1)
    assert history.shape == (3, 18)
    statuses = json.loads((tmp_path / 'history_status.json').read_text())
    assert [row['evaluation'] for row in statuses] == [1, 2, 3]
    assert statuses[0]['reason'] == errors[0] and statuses[1]['status'] == 'failed'
    assert statuses[2]['status'] == ('failed' if all_failed else 'valid')
    mask = bo._pareto_mask_max(Y, valid=np.array([error is None for error in errors]))
    assert mask.tolist() == [False, False, not all_failed]
    F = np.column_stack([-Y[:, 0], 10. ** -Y[:, 1]])
    seed = dict(X=X[mask], F=F[mask], history_X=X, history_F=F,
                history_errors=errors, n_evals=3)
    merged = _merge_paretos([seed, seed])
    assert merged[0].shape == (2 * expected_count, 16)
    assert merged[2].shape == (6, 16) and merged[3].shape == (6, 2)
    assert merged[4] == 6
    # Explicitly exporting a failed historical geometry carries its verdict.
    exported = export_pareto_row(str(tmp_path / 'history.csv'), 0,
                                 str(tmp_path / 'geometry'), config=bo.EVAL_DEFAULT_CONFIG,
                                 Nx_export=4, Ny_export=4)
    assert exported['source']['evaluation_status'] == statuses[0]


@pytest.mark.parametrize('objective', [(np.nan, 10., 1.), (-3., np.inf, 1.), (-1e-6, 100., 1.)])
def test_worker_marks_nonfinite_and_evaluator_penalties(objective):
    Q, dp, error = bo._eval_worker(None, {}, 100., lambda *a: objective)
    assert np.isfinite(Q) and np.isfinite(dp) and error is not None


def test_full_bo_initial_batch_publishes_no_front_on_failure(tmp_path):
    pytest.importorskip('botorch', reason='BO execution requires the optional server lock')
    def failed(*args):
        raise RuntimeError('all initial evaluations failed')
    result = bo.run_qnehvi(n_init=2, n_iter=0, evaluator_fn=failed,
                           save_dir=str(tmp_path), verbose=True)
    assert result['X'].shape == (0, 16) and result['F'].shape == (0, 2)
    assert result['history_X'].shape == (2, 16)
    assert len(result['history_errors']) == 2 and all(result['history_errors'])
    assert bo.progress['best_Q'] == -float('inf')
    assert len((tmp_path / 'pareto_final.csv').read_text().splitlines()) == 1
    assert len(json.loads((tmp_path / 'history_status.json').read_text())) == 2
