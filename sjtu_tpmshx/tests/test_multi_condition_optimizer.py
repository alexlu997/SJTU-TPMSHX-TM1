"""Search orchestration uses complete native batches; physics is not mocked as valid evidence."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig, GeometryConfig, SolverConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.optimization import multi_condition_optimizer as search


def _conditions(dimension=2):
    return [(f'flow-{i}', ComputeConfig(
        geometry=GeometryConfig(Lz_m=.042), solver=SolverConfig(Nz=3 if dimension == 3 else 1),
        fluid_A=FluidConfig(type='air', u_mps=10., T_in_K=380.+i),
        fluid_B=FluidConfig(type='water', u_mps=.1, T_in_K=300.)), .01+i*.005, .03+i*.01)
        for i in range(2)]


def _manifest(path):
    return json.loads((path / 'optimization.json').read_text())


def _fake_batches(monkeypatch, *, fail_indices=(), baseline_failure=False, cancel_index=None):
    calls, baseline_token = [], object()

    def evaluate(conditions, *, output_dir, baseline=None, control=RunControl()):
        directory = Path(output_dir)
        directory.mkdir()
        index = len(calls)-1  # First call is the extra uniform baseline.
        calls.append((conditions, baseline, directory))
        (directory / 'native-evidence.txt').write_text('test evaluator evidence; no physical solve')
        control.report_progress(0)
        if baseline is None:
            assert all(not cfg.zones.enabled for _, cfg, _, _ in conditions)
            result = dict(status='failed' if baseline_failure else 'completed',
                          reason='bad reference' if baseline_failure else None,
                          objectives=None, results=baseline_token)
        else:
            assert baseline is baseline_token
            if index == cancel_index:
                (directory / 'batch.json').write_text(json.dumps(dict(status='cancelled')))
                raise CancelledError('injected batch cancellation')
            failed = index in fail_indices
            # Deliberately retain negative gain and sub-unity pressure cost.
            result = dict(status='failed' if failed else 'completed',
                          reason='one condition failed' if failed else None,
                          objectives={'heat_gain_percent': -20.+index, 'pressure_ratio': .7+.02*index},
                          results=[])
        (directory / 'batch.json').write_text(json.dumps({k: v for k, v in result.items() if k != 'results'}))
        control.report_progress(100)
        return result

    monkeypatch.setattr(search, 'evaluate_condition_batch', evaluate)
    return calls


@pytest.mark.parametrize('dimension', [2, 3])
def test_equal_design_budgets_initial_data_and_full_field_handoff(tmp_path, monkeypatch, dimension):
    originals = _conditions(dimension)
    snapshots = [asdict(row[1]) for row in originals]
    reports = []
    for method in ('sobol', 'qlognehvi', 'qlognparego'):
        calls = _fake_batches(monkeypatch, fail_indices=(1,))
        proposals = []

        def propose(X, Y, lower, upper, reference, **kwargs):
            proposals.append((X.copy(), Y.copy(), reference.copy(), kwargs))
            return np.vstack((lower + .3*(upper-lower), lower + .7*(upper-lower)))

        monkeypatch.setattr(search, '_bo_versions', lambda: {'botorch': 'test double'})
        monkeypatch.setattr(search, '_propose_bo', propose)
        progress = []
        directory = tmp_path / method
        result = search.run_multi_condition_optimization(originals, output_dir=directory,
            method=method, n_init=3, n_iter=2, q_batch=2, seed=17,
            control=RunControl(progress=progress.append))
        assert result == _manifest(directory)
        assert result['status'] == 'completed'
        assert result['design_budget'] == result['n_evaluated'] == 7
        assert result['n_usable'] == 6 and len(calls) == 8
        assert len(result['history']) == 7 and len(result['proposals']) == 2
        assert result['baseline']['status'] == 'completed'
        assert result['history'][1]['status'] == 'failed'
        assert result['history'][1]['objectives'] is result['history'][1]['model_y'] is None
        assert 1 not in result['pareto_indices']
        assert result['history'][0]['objectives'] == {'heat_gain_percent': -20., 'pressure_ratio': .7}
        assert result['history'][0]['model_y'] == [-20., -.7]
        assert progress == sorted(progress) and progress[-1] == 100
        count = 9 if dimension == 2 else 27
        np.testing.assert_array_equal(result['initial_designs'][0], [7.]*count + [.6]*count)
        for row, (conditions, _, native_dir) in zip(result['history'], calls[1:]):
            assert (native_dir / 'native-evidence.txt').exists()
            assert directory / row['directory'] == native_dir
            for (name, cfg, a, b), original in zip(conditions, originals):
                assert (name, a, b) == (original[0], original[2], original[3])
                assert cfg.zones.config == {**result['field_spec'], 'x_decision': row['x_decision']}
                assert len(cfg.zones.config['x_decision']) == 2*count
                assert ('n_ctrl_z' in cfg.zones.config) == (dimension == 3)
        if proposals:
            assert [len(item[0]) for item in proposals] == [2, 4]
            np.testing.assert_array_equal(proposals[0][1], [[-20., -.7], [-18., -.74]])
            np.testing.assert_array_equal(proposals[0][2], proposals[1][2])
            assert all(item[3]['method'] == method for item in proposals)
        reports.append(result)
    assert [asdict(row[1]) for row in originals] == snapshots
    for result in reports[1:]:
        assert result['initial_designs'] == reports[0]['initial_designs']
        assert result['ref_point'] == reports[0]['ref_point']


def test_insufficient_valid_initial_data_stops_without_fallback(tmp_path, monkeypatch):
    calls = _fake_batches(monkeypatch, fail_indices=(1, 2))
    monkeypatch.setattr(search, '_bo_versions', lambda: {})
    monkeypatch.setattr(search, '_propose_bo', lambda *a, **k: pytest.fail('unfit BO reached'))
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'search',
        n_init=3, n_iter=2)
    assert result['status'] == 'failed' and 'two distinct usable' in result['reason']
    assert len(calls) == 4 and result['n_usable'] == 1 and not result['proposals']


@pytest.mark.parametrize('method', ['qlognehvi', 'qlognparego'])
def test_zero_iterations_accepts_one_usable_initial_design(tmp_path, monkeypatch, method):
    calls = _fake_batches(monkeypatch)
    monkeypatch.setattr(search, '_bo_versions', lambda: {})
    monkeypatch.setattr(search, '_propose_bo', lambda *a, **k: pytest.fail('zero-iteration BO reached'))
    directory = tmp_path / method
    result = search.run_multi_condition_optimization(_conditions(), output_dir=directory,
        method=method, n_init=1, n_iter=0)
    assert result == _manifest(directory)
    assert result['status'] == 'completed' and result['stage'] == 'finished'
    assert result['n_evaluated'] == result['n_usable'] == 1
    assert len(calls) == 2 and not result['proposals']
    assert result['pareto_indices'] == [0]


def test_failed_uniform_reference_stops_before_candidates(tmp_path, monkeypatch):
    calls = _fake_batches(monkeypatch, baseline_failure=True)
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'search',
        method='sobol', n_init=2, n_iter=1)
    assert len(calls) == 1 and result['status'] == 'failed'
    assert result['history'] == result['pareto_indices'] == []
    assert result['baseline']['reason'] == 'bad reference'


@pytest.mark.parametrize('pre_cancelled', [False, True])
def test_cancel_retains_finished_and_current_native_evidence(tmp_path, monkeypatch, pre_cancelled):
    calls = _fake_batches(monkeypatch, cancel_index=1)
    directory = tmp_path / 'search'
    with pytest.raises(CancelledError):
        search.run_multi_condition_optimization(_conditions(), output_dir=directory, method='sobol',
            n_init=3, n_iter=2, control=RunControl(cancel_check=lambda: pre_cancelled))
    result = _manifest(directory)
    assert result['status'] == 'cancelled'
    assert len(result['initial_designs']) == 3
    if pre_cancelled:
        assert not calls and result['baseline']['status'] == 'not_run' and not result['history']
    else:
        assert [row['status'] for row in result['history']] == ['completed', 'cancelled']
        for row in result['history']:
            assert (directory / row['directory'] / 'native-evidence.txt').exists()
        assert result['history'][1]['objectives'] is None


def test_proposal_failure_is_logged_and_reraised_without_random_fallback(tmp_path, monkeypatch):
    calls = _fake_batches(monkeypatch)
    monkeypatch.setattr(search, '_bo_versions', lambda: {})

    def fail(*args, **kwargs):
        raise RuntimeError('GP fit failed')

    monkeypatch.setattr(search, '_propose_bo', fail)
    directory = tmp_path / 'search'
    with pytest.raises(RuntimeError, match='GP fit failed'):
        search.run_multi_condition_optimization(_conditions(), output_dir=directory, n_init=2, n_iter=1)
    record = _manifest(directory)
    assert len(calls) == 3 and len(record['history']) == 2
    assert record['stage'] == 'proposal' and record['status'] == 'failed'
    assert 'GP fit failed' in record['reason']


def test_missing_bo_environment_does_not_spend_physical_evaluations(tmp_path, monkeypatch):
    calls = _fake_batches(monkeypatch)

    def absent():
        raise ModuleNotFoundError('No module named botorch')

    monkeypatch.setattr(search, '_bo_versions', absent)
    directory = tmp_path / 'search'
    with pytest.raises(ModuleNotFoundError, match='botorch'):
        search.run_multi_condition_optimization(_conditions(), output_dir=directory)
    assert not calls and not directory.exists()


def test_sobol_single_design_and_existing_directory_contract(tmp_path, monkeypatch):
    calls = _fake_batches(monkeypatch)
    directory = tmp_path / 'search'
    result = search.run_multi_condition_optimization(_conditions(), output_dir=directory,
        method='sobol', n_init=1, n_iter=0)
    before = (directory / 'optimization.json').read_text()
    assert result['n_evaluated'] == 1 and result['pareto_indices'] == [0]
    with pytest.raises(FileExistsError):
        search.run_multi_condition_optimization(_conditions(), output_dir=directory, method='sobol')
    assert (directory / 'optimization.json').read_text() == before and len(calls) == 2


def test_import_does_not_load_optional_bo_or_qt():
    subprocess.run([sys.executable, '-c', '''
import sys
import sjtu_tpmshx.optimization.multi_condition_optimizer
assert not any(name.split('.')[0] in ('torch', 'botorch', 'gpytorch', 'PySide6') for name in sys.modules)
'''], check=True)


@pytest.mark.parametrize('method', ['qlognehvi', 'qlognparego'])
def test_real_log_acquisition_selects_then_evaluates_complete_design(tmp_path, monkeypatch, method):
    pytest.importorskip('botorch', reason='requires the separately authorized locked BO environment')
    calls = _fake_batches(monkeypatch)
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / method,
        method=method, n_init=4, n_iter=1, q_batch=1, seed=4)
    assert result['status'] == 'completed' and result['n_evaluated'] == 5 and len(calls) == 6
    chosen = result['history'][-1]['x_decision']
    assert result['proposals'][0]['x_decisions'] == [chosen]
    assert calls[-1][0][0][1].zones.config['x_decision'] == chosen
    assert np.isfinite(result['history'][-1]['model_y']).all()
