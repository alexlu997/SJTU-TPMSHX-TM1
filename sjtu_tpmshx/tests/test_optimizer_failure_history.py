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
    output = tmp_path / 'run'
    result = bo.run_qnehvi(n_init=2, n_iter=0, evaluator_fn=failed,
                           save_dir=str(output), verbose=True)
    assert result['X'].shape == (0, 16) and result['F'].shape == (0, 2)
    assert result['history_X'].shape == (2, 16)
    assert len(result['history_errors']) == 2 and all(result['history_errors'])
    assert bo.progress['best_Q'] == -float('inf')
    assert len((output / 'pareto_final.csv').read_text().splitlines()) == 1
    assert len(json.loads((output / 'history_status.json').read_text())) == 2


@pytest.mark.parametrize('cancel_before_start', [False, True])
def test_bo_cancel_during_initial_sampling_retains_only_evaluated_rows(tmp_path, cancel_before_start):
    pytest.importorskip('botorch', reason='BO execution requires the optional server lock')
    cancelled = cancel_before_start
    def evaluate(*args):
        nonlocal cancelled
        cancelled = True
        return -10., 10., 1.
    output = tmp_path / 'run'
    result = bo.run_qnehvi(n_init=4, n_iter=3, evaluator_fn=evaluate,
                           cancel_check=lambda: cancelled, save_dir=str(output),
                           verbose=False)
    count = 0 if cancel_before_start else 1
    assert result['termination_reason'] == bo.progress['phase'] == 'cancelled'
    assert result['n_evals'] == count
    assert result['history_X'].shape == (count, 16)
    assert result['history_F'].shape == (count, 2)
    status = json.loads((output / 'run_status.json').read_text())
    assert status['termination_reason'] == 'cancelled' and status['n_evals'] == count


@pytest.mark.parametrize('default_name', [False, True])
def test_existing_run_archive_rejected_before_evaluation(tmp_path, monkeypatch, default_name):
    pytest.importorskip('botorch', reason='BO execution requires the optional server lock')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bo.time, 'strftime', lambda *a: 'fixed-time')
    output = tmp_path / ('opt_qnehvi_fixed-time' if default_name else 'existing')
    output.mkdir()
    original = {'config.json': b'{"original": true}', 'history.csv': b'previous observations\n'}
    for name, content in original.items():
        (output / name).write_bytes(content)
    calls = []

    def evaluate(*args):
        calls.append(args)
        return -10., 20., 1.

    with pytest.raises(FileExistsError):
        bo.run_qnehvi(n_init=1, n_iter=0, evaluator_fn=evaluate,
                       save_dir=None if default_name else str(output), verbose=False)
    assert not calls
    assert {path.name: path.read_bytes() for path in output.iterdir()} == original


def _fault_at_bo_boundary(monkeypatch, error, stage, fail_at=1):
    pytest.importorskip('botorch', reason='BO execution requires the optional server lock')
    import torch
    import botorch.fit
    import botorch.optim.optimize
    import botorch.acquisition.multi_objective.monte_carlo

    calls = dict(evaluations=[], fit=0, acquisition=0, proposal=0, cancel=False)

    def evaluate(x, cfg):
        calls['evaluations'].append(x.copy())
        count = len(calls['evaluations'])
        return -float(100 + count), float(20 + count), 1.

    def fit(*args, **kwargs):
        calls['fit'] += 1
        if stage == 'fit':
            raise error

    def acquisition(*args, **kwargs):
        calls['acquisition'] += 1
        if stage == 'fit':
            raise AssertionError('acquisition reached after failed fit')
        if stage == 'acquisition':
            raise error
        return object()

    def propose(*args, **kwargs):
        calls['proposal'] += 1
        if stage == 'proposal' and calls['proposal'] == fail_at:
            # A concurrent cancellation cannot overwrite a real failure.
            calls['cancel'] = fail_at > 1
            raise error
        bounds = kwargs['bounds']
        fraction = .1 + .05 * calls['proposal']
        return (bounds[0] + fraction * (bounds[1] - bounds[0])).unsqueeze(0), torch.tensor(0.)

    monkeypatch.setattr(botorch.fit, 'fit_gpytorch_mll', fit)
    monkeypatch.setattr(botorch.fit, 'fit_fully_bayesian_model_nuts', fit)
    monkeypatch.setattr(botorch.acquisition.multi_objective.monte_carlo,
                        'qNoisyExpectedHypervolumeImprovement', acquisition)
    monkeypatch.setattr(botorch.optim.optimize, 'optimize_acqf', propose)
    return evaluate, calls


@pytest.mark.parametrize('stage,gp_model,fail_at,completed', [
    ('fit', 'single_task', 1, 0),
    ('fit', 'saas', 1, 0),
    ('acquisition', 'single_task', 1, 0),
    ('proposal', 'single_task', 1, 0),
    ('proposal', 'single_task', 7, 6),
])
def test_optimizer_failure_keeps_completed_history_and_original_error(
        tmp_path, monkeypatch, stage, gp_model, fail_at, completed):
    error = RuntimeError(f'injected {gp_model} {stage} failure')
    evaluate, calls = _fault_at_bo_boundary(monkeypatch, error, stage, fail_at)
    output = tmp_path / 'run'
    with pytest.raises(Exception) as caught:
        bo.run_qnehvi(config={'gp_model': gp_model}, n_init=2, n_iter=fail_at,
            q_batch=1, seed=42, hv_tol=0., evaluator_fn=evaluate,
            cancel_check=lambda: calls['cancel'], save_dir=str(output), verbose=False)
    assert caught.value is error
    count = 2 + completed
    assert len(calls['evaluations']) == bo.progress['count'] == count
    assert bo.progress['phase'] == 'failed'
    if stage == 'fit':
        assert (calls['fit'], calls['acquisition'], calls['proposal']) == (1, 0, 0)

    status = json.loads((output / 'run_status.json').read_text())
    assert status['termination_reason'] == 'failed'
    assert status['stage'] == ('fit' if stage == 'fit' else 'proposal')
    assert status['n_evals'] == count and status['planned_evals'] == 2 + fail_at
    assert type(error).__name__ in status['reason'] and str(error) in status['reason']
    history = np.loadtxt(output / 'history.csv', delimiter=',', skiprows=1, ndmin=2)
    assert history.shape == (count, 18)
    np.testing.assert_array_equal(history[:, :16], np.asarray(calls['evaluations']))
    np.testing.assert_array_equal(history[:, 16], 100 + np.arange(1, count + 1))
    np.testing.assert_allclose(history[:, 17], 20 + np.arange(1, count + 1), rtol=1e-12, atol=0.)
    statuses = json.loads((output / 'history_status.json').read_text())
    assert statuses == [dict(evaluation=i, status='valid', reason=None) for i in range(1, count + 1)]
    # Every controlled observation trades increasing Q against increasing dP.
    latest = np.loadtxt(output / 'pareto_latest.csv', delimiter=',', skiprows=1, ndmin=2)
    np.testing.assert_array_equal(latest, history)
    checkpoint = output / f'pareto_iter{completed:04d}.csv'
    np.testing.assert_array_equal(np.loadtxt(checkpoint, delimiter=',', skiprows=1, ndmin=2), latest)
    assert not (output / 'pareto_final.csv').exists()
    if completed == 6:
        assert (output / 'pareto_iter0005.csv').exists()
        assert len((output / 'pareto_iter0005.csv').read_text().splitlines()) == 8


def test_optimizer_checkpoint_failure_does_not_replace_original_error(tmp_path, monkeypatch, caplog):
    error = RuntimeError('injected proposal failure')
    evaluate, calls = _fault_at_bo_boundary(monkeypatch, error, 'proposal')
    saved = []

    def failed_save(train_X, train_Y, save_dir, step, errors):
        saved.append((len(train_X), len(train_Y), step, list(errors)))
        raise OSError('injected checkpoint failure')

    monkeypatch.setattr(bo, '_save_current_pareto', failed_save)
    output = tmp_path / 'run'
    with pytest.raises(Exception) as caught:
        bo.run_qnehvi(n_init=2, n_iter=1, q_batch=1, seed=42, hv_tol=0.,
            evaluator_fn=evaluate, save_dir=str(output), verbose=False)
    assert caught.value is error
    assert saved == [(2, 2, 0, [None, None])]
    assert len(calls['evaluations']) == bo.progress['count'] == 2
    assert bo.progress['phase'] == 'failed'
    diagnostic = '\n'.join(getattr(error, '__notes__', [])) + caplog.text
    assert 'injected checkpoint failure' in diagnostic
    assert not (output / 'pareto_final.csv').exists()
