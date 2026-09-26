"""Checkpoint failures preserve active errors without claiming stale data is saved."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.io import text_file
from sjtu_tpmshx.optimization import multi_condition as batch
from sjtu_tpmshx.optimization import multi_condition_optimizer as search
from sjtu_tpmshx.solvers import api as execution
from sjtu_tpmshx.tests.test_multi_condition_batch import _conditions, _native
from sjtu_tpmshx.tests.test_multi_condition_optimizer import _conditions as search_conditions


def _checkpoint_fault(monkeypatch, module, filename, when, *, persistent=False):
    original = text_file.write_text
    error = OSError('checkpoint write failed')
    attempts = []

    def write(path, text):
        if Path(path).name != filename:
            return original(path, text)
        record = json.loads(text)
        fail = when(record, len(attempts))
        if attempts and any(failed for _, failed in attempts):
            fail = persistent
        attempts.append((record, fail))
        if fail:
            raise error
        return original(path, text)

    monkeypatch.setattr(module, 'write_text', write)
    return error, attempts


def _search_batches(monkeypatch, primary=None, stage=None):
    calls = []

    def evaluate(conditions, *, baseline=None, **kwargs):
        label = 'baseline' if baseline is None else 'candidate'
        calls.append(label)
        if label == stage:
            raise primary
        return dict(status='completed', reason=None, results=[],
                    objectives=None if baseline is None else
                    dict(heat_gain_percent=float(len(calls)), pressure_ratio=.9))

    monkeypatch.setattr(search, 'evaluate_condition_batch', evaluate)
    return calls


@pytest.mark.parametrize('stage,error_type,persistent', [
    ('candidate', RuntimeError, False), ('candidate', CancelledError, False),
    ('candidate', RuntimeError, True), ('baseline', RuntimeError, False),
    ('baseline', CancelledError, False), ('proposal', RuntimeError, False),
])
def test_search_checkpoint_failure_keeps_primary_exception(
        tmp_path, monkeypatch, stage, error_type, persistent):
    primary = error_type('original failure')
    calls = _search_batches(monkeypatch, primary, stage)
    if stage == 'proposal':
        monkeypatch.setattr(search, '_bo_versions', lambda: {})
        def proposal(*args, **kwargs):
            raise primary
        monkeypatch.setattr(search, '_propose_bo', proposal)
    def when(record, index):
        if stage == 'candidate':
            return any(row['status'] in ('failed', 'cancelled') for row in record['history'])
        return record['status'] in ('failed', 'cancelled')
    _, attempts = _checkpoint_fault(monkeypatch, search, 'optimization.json', when,
                                     persistent=persistent)
    output = tmp_path / 'search'
    with pytest.raises(error_type) as caught:
        search.run_multi_condition_optimization(search_conditions()[:1], output_dir=output,
            method='qlognehvi' if stage == 'proposal' else 'sobol',
            n_init=2 if stage == 'proposal' else 1, n_iter=int(stage == 'proposal'))
    assert caught.value is primary
    assert any('checkpoint write failed' in note for note in primary.__notes__)
    saved = json.loads((output/'optimization.json').read_text())
    assert saved == [record for record, failed in attempts if not failed][-1]
    terminal = attempts[-1][0]
    assert terminal['status'] == ('cancelled' if error_type is CancelledError else 'failed')
    assert 'original failure' in terminal['reason']
    if stage == 'candidate':
        assert calls == ['baseline', 'candidate']
        assert 'original failure' in terminal['history'][0]['reason']
        assert saved['status'] == ('running' if persistent else terminal['status'])
    else:
        assert saved['status'] == 'running'


@pytest.fixture(scope='module')
def prepared_native_case():
    _, config, flow_a, flow_b = _conditions(1)[0]
    return batch.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=flow_a,
        mass_flow_B_kg_s=flow_b, case_id='checkpoint-test-reference')


def _batch_solver(monkeypatch, prepared, primary=None):
    calls = []
    def prepare(config, *, case_id, **kwargs):
        calls.append('prepare')
        return replace(prepared, case_id=case_id)
    def solve(case, control):
        calls.append('solve')
        if primary is not None:
            raise primary
        return _native(case)
    monkeypatch.setattr(batch, 'prepare_fixed_mass_flow_case', prepare)
    monkeypatch.setattr(execution, 'run_case', solve)
    return calls


@pytest.mark.parametrize('error_type,save_stage', [
    (RuntimeError, 'condition'), (CancelledError, 'condition'), (CancelledError, 'batch'),
])
def test_batch_checkpoint_failure_keeps_primary_exception(
        tmp_path, monkeypatch, prepared_native_case, error_type, save_stage):
    primary = error_type('original failure')
    calls = _batch_solver(monkeypatch, prepared_native_case, primary)
    def when(record, index):
        return (record['conditions'][0]['status'] in ('failed', 'cancelled')
                if save_stage == 'condition' else record['status'] == 'cancelled')
    _, attempts = _checkpoint_fault(monkeypatch, text_file, 'batch.json', when)
    output = tmp_path / 'batch'
    with pytest.raises(error_type) as caught:
        batch.evaluate_condition_batch(_conditions(2), output_dir=output)
    assert caught.value is primary
    assert any('checkpoint write failed' in note for note in primary.__notes__)
    assert calls == ['prepare', 'solve']
    saved = json.loads((output/'batch.json').read_text())
    assert saved == [record for record, failed in attempts if not failed][-1]
    row = attempts[-1][0]['conditions'][0]
    assert 'original failure' in row['reason']
    assert (output/row['case_file']).exists()
    assert row['result_file'] is row['metrics_file'] is None
    assert attempts[-1][0]['conditions'][1]['status'] == 'not_run'


@pytest.mark.parametrize('kind', ['search', 'batch'])
@pytest.mark.parametrize('save_stage', ['first', 'middle', 'final'])
def test_checkpoint_io_without_active_error_is_not_suppressed(
        tmp_path, monkeypatch, prepared_native_case, kind, save_stage):
    calls = (_search_batches(monkeypatch) if kind == 'search'
             else _batch_solver(monkeypatch, prepared_native_case))
    filename = 'optimization.json' if kind == 'search' else 'batch.json'
    def when(record, index):
        rows = record.get('history', record.get('conditions', []))
        if save_stage == 'first':
            return index == 0
        if save_stage == 'final':
            return record['status'] == 'completed'
        return bool(rows) and rows[0]['status'] == 'running' and (
            kind == 'search' or rows[0]['stage'] == 'save_case')
    error, attempts = _checkpoint_fault(monkeypatch, search if kind == 'search' else text_file,
                                         filename, when)
    output = tmp_path / kind
    def run():
        if kind == 'search':
            return search.run_multi_condition_optimization(search_conditions()[:1],
                output_dir=output, method='sobol', n_init=1, n_iter=0)
        return batch.evaluate_condition_batch(_conditions(1), output_dir=output)
    if kind == 'batch' and save_stage == 'middle':
        # A handled condition failure with a successful error checkpoint still
        # follows the existing batch contract rather than becoming fail-fast.
        result = run()
        assert result['status'] == 'failed'
        assert 'checkpoint write failed' in result['conditions'][0]['reason']
    else:
        with pytest.raises(OSError) as caught:
            run()
        assert caught.value is error
    if save_stage == 'first':
        assert calls == [] and not (output/filename).exists()
    else:
        saved = json.loads((output/filename).read_text())
        assert saved == [record for record, failed in attempts if not failed][-1]
        if save_stage == 'final':
            assert saved['status'] == 'running'


def test_final_io_does_not_resurrect_an_already_handled_condition_error(
        tmp_path, monkeypatch, prepared_native_case):
    primary = RuntimeError('handled condition failure')
    _batch_solver(monkeypatch, prepared_native_case, primary)
    error, attempts = _checkpoint_fault(monkeypatch, text_file, 'batch.json',
                                         lambda record, index: record['status'] == 'failed')
    with pytest.raises(OSError) as caught:
        batch.evaluate_condition_batch(_conditions(1), output_dir=tmp_path/'batch')
    assert caught.value is error
    assert attempts[-2][0]['conditions'][0]['reason'] == 'RuntimeError: handled condition failure'
