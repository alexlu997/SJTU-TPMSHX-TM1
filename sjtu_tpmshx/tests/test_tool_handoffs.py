"""File handoffs and process outcomes, without launching BO or CFD."""
import csv
import json
from concurrent.futures import Future

import numpy as np
import pytest

from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
from sjtu_tpmshx.optimization import parallel_runner as parallel
from sjtu_tpmshx.optimization import export_ntop_csv as ntop
from sjtu_tpmshx.validation.cases import verify_pareto_3d as verify


@pytest.mark.parametrize('dimension', [16, 36])
def test_export_and_verifier_restore_the_same_named_decisions(tmp_path, monkeypatch, dimension):
    values = {f'x{i}': float(i + 1) for i in range(dimension)}
    values.update(Q_W_per_m=1234., dP_Pa=567.)
    path = tmp_path / 'pareto.csv'
    with path.open('w', newline='') as target:
        writer = csv.DictWriter(target, list(reversed(values)))
        writer.writeheader()
        writer.writerow(values)
    captured = []
    monkeypatch.setattr(ntop, 'export_decision_vector',
                        lambda x, *a, **kw: captured.append(x))
    ntop.export_pareto_row(str(path), 0, str(tmp_path / 'out'), config=DEFAULT_CONFIG)
    expected, q, dp = verify._load_pareto_row(str(path), 0, dimension)
    np.testing.assert_array_equal(captured[0], expected)
    assert (q, dp) == (1234., 567.)


def test_verification_requires_original_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, 'evaluate_3d', lambda *a, **kw: pytest.fail('solver launched'))
    with pytest.raises(ValueError, match='original config.json'):
        verify.main(['--pareto', str(tmp_path / 'pareto.csv')])


@pytest.mark.parametrize('failed_seeds', [{43}, {42, 43}, set()])
def test_multiseed_config_actual_members_and_failed_members(tmp_path, monkeypatch, failed_seeds):
    class Executor:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, seed, cfg, *args):
            future = Future()
            if seed in failed_seeds:
                future.set_exception(RuntimeError(f'failed seed {seed}'))
            else:
                x, f = np.ones((1, 16)), np.array([[-100., 20.]])
                future.set_result(dict(seed=seed, config=cfg, X=x, F=f,
                                       history_X=x, history_F=f, history_errors=[None],
                                       n_evals=1, termination_reason='completed'))
            return future

    monkeypatch.setattr(parallel, 'ProcessPoolExecutor', Executor)
    result = parallel.run_qnehvi_multiseed(seeds=[42, 43], config={'u_A': 7.},
                                          save_dir_base=str(tmp_path), verbose=False)
    assert set(result['seeds_used']) == {42, 43} - failed_seeds
    assert set(result['failed_seeds']) == failed_seeds
    assert result['complete'] is (not failed_seeds)
    assert result['seeds_requested'] == [42, 43]
    assert json.loads((tmp_path / 'config.json').read_text())['u_A'] == 7.
    status = json.loads((tmp_path / 'multiseed_status.json').read_text())
    assert set(map(int, status['failed_seeds'])) == failed_seeds
    assert verify._load_run_cfg(str(tmp_path / 'pareto_merged.csv'))['u_A'] == 7.
    assert result['X'].shape[1] == 16
    assert len(next(csv.reader((tmp_path / 'pareto_merged.csv').open()))) == 18


@pytest.mark.parametrize('seeds', [[], [42, 42]])
def test_invalid_seed_membership_rejected(seeds, tmp_path):
    with pytest.raises(ValueError, match='seed'):
        parallel.run_qnehvi_multiseed(seeds=seeds, save_dir_base=str(tmp_path))


@pytest.mark.parametrize('complete', [False, True])
def test_both_multiseed_cli_exits_reflect_partial_failure(monkeypatch, complete):
    from sjtu_tpmshx.runs import run_production_qnehvi_parallel as production
    result = dict(X=np.empty((0, 16)), F=np.empty((0, 2)), n_evals=0,
                  wall_time_s=0., save_dir='unused', seeds_used=[], complete=complete)
    monkeypatch.setattr(parallel, 'run_qnehvi_multiseed', lambda **kw: result)
    assert parallel.main(['--quiet']) == (0 if complete else 1)
    assert production.main(['--quiet']) == (0 if complete else 1)
