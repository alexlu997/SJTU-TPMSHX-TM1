"""Spawned condition workers keep callbacks, archives and failures separate."""
from dataclasses import replace
import json
import os
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.optimization import multi_condition as batch
from sjtu_tpmshx.tests.test_multi_condition_batch import _baseline, _conditions, _native


def _analytic_worker(index, case_file, directory, library, threads, checkpoint_file=None):
    from sjtu_tpmshx.workflows import recovery

    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        label = case.case_id.rsplit(':', 1)[-1]
        step = 0 if resume_state is None else int(resume_state['step'][0])
        if checkpoint_due():
            checkpoint({'build': 'analytic-worker', 'state.phase': np.array([6], dtype=np.uint64),
                        'step': np.array([step+1], dtype=np.uint64)})
        started = Path(directory).parent / f'started-{index}'
        started.write_text(str(os.getpid()))
        if index < 2 and resume_state is None:
            deadline = monotonic()+15.
            while len(list(started.parent.glob('started-*'))) < 2:
                control.check_cancelled()
                if monotonic() > deadline:
                    raise TimeoutError('The second test worker did not start.')
                sleep(.01)
        control.iteration(label)
        control.outer_iteration(1, 2)
        control.residual('A', 1, .01)
        control.report_progress(40)
        if label == 'bad':
            error = ValueError('injected worker solve failure')
            error.add_note('retained worker diagnostic detail')
            raise error
        if label == 'crash':
            os._exit(17)
        inputs = json.loads((Path(directory).parent / 'batch-input.json').read_text())
        waits_for_cancel = label == 'stop' or (label == 'mid' and inputs[0]['condition_id'] in ('stop', 'crash'))
        if waits_for_cancel and resume_state is None:
            deadline = monotonic()+10.
            while monotonic() < deadline:
                control.check_cancelled()
                sleep(.01)
            raise TimeoutError('The parent did not cancel the test worker.')
        if index == 0:
            sleep(.2)
        control.check_cancelled()
        control.report_progress(100)
        field = _native(case)
        return replace(field, metadata={**field.metadata,
            'test_worker_pid': os.getpid(), 'test_cpu_threads': control.cpu_threads,
            'test_resumed_step': step})

    recovery.run_case = solve
    return batch._run_native_condition(index, case_file, directory, library, threads, checkpoint_file)


def _control(tmp_path, **kwargs):
    library = tmp_path / 'analytic-library.dylib'
    library.write_bytes(b'non-executable test data')
    return RunControl(backend='cpp', native_library=str(library), cpu_threads=4, **kwargs)


@pytest.mark.parametrize('available_cpus', [2, 3, 8])
@pytest.mark.parametrize('failed_member', [False, True])
def test_process_batch_keeps_order_resources_and_parent_callbacks(
        tmp_path, monkeypatch, failed_member, available_cpus):
    monkeypatch.setattr(os, 'cpu_count', lambda: available_cpus)
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    if failed_member:
        conditions[1] = ('bad', *conditions[1][1:])
    baseline = _baseline(conditions)
    callbacks, progress = [], []
    def observe(*args):
        callbacks.append((os.getpid(), args))
    control = _control(tmp_path, progress=progress.append, iteration=observe,
                       outer_iteration=observe, residual=observe)
    root = tmp_path / 'parallel'
    result = batch.evaluate_condition_batch(conditions, output_dir=root,
        baseline=baseline, control=control, workers=2)
    assert result['status'] == ('failed' if failed_member else 'completed')
    budget = min(4, available_cpus)
    threads = budget // 2
    assert result['workers'] == 2 and result['native_cpu_budget'] == budget
    assert [row['condition_id'] for row in result['conditions']] == [row[0] for row in conditions]
    expected = ['low', 'high'] if failed_member else ['low', 'mid', 'high']
    assert [row[0] for row in result['results']] == expected
    assert progress == sorted(progress) and progress[-1] == 100
    assert callbacks and all(pid == os.getpid() for pid, _ in callbacks)
    assert len({row['worker_pid'] for row in result['conditions']}) == 2
    for row in result['conditions']:
        assert row['cpu_threads'] == threads and row['worker_pid'] != os.getpid()
        assert (root / row['checkpoint_file']).is_file()
        if row['status'] == 'completed':
            field = load_result(root / row['result_file'])
            assert field.metadata['test_worker_pid'] == row['worker_pid']
            assert field.metadata['test_cpu_threads'] == threads
    if failed_member:
        assert result['objectives'] is None
        assert 'injected worker solve failure' in result['conditions'][1]['reason']
        assert 'retained worker diagnostic detail' in result['conditions'][1]['reason']
    else:
        assert result['objectives'] == pytest.approx(dict(heat_gain_percent=0., pressure_ratio=1.))


def test_process_cancel_keeps_checkpoint_and_unrun_members(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('stop', *conditions[0][1:])
    cancelled = []
    def iteration(message):
        if message == 'stop':
            cancelled.append(True)
    root = tmp_path / 'cancelled'
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=root, workers=2,
            control=_control(tmp_path, iteration=iteration, cancel_check=lambda: bool(cancelled)))
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == 'cancelled' and record['objectives'] is None
    assert record['conditions'][0]['status'] == 'cancelled'
    assert (root / record['conditions'][0]['checkpoint_file']).is_file()
    assert record['conditions'][2]['status'] == 'not_run'
    assert all(row['status'] not in ('running', 'computed') for row in record['conditions'])


@pytest.mark.parametrize('workers', [0, -1, True, 1.5])
def test_invalid_worker_count_creates_no_archive(tmp_path, workers):
    root = tmp_path / 'invalid'
    with pytest.raises(ValueError, match='workers'):
        batch.evaluate_condition_batch(_conditions(1), output_dir=root, workers=workers)
    assert not root.exists()





def test_batch_resume_reuses_complete_members_and_actual_saved_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('stop', *conditions[0][1:])
    cancelled = []
    def iteration(message):
        if message == 'stop':
            cancelled.append(True)
    original = tmp_path / 'source'
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=original, workers=2,
            control=_control(tmp_path, iteration=iteration, cancel_check=lambda: bool(cancelled)))
    moved = original.rename(tmp_path / 'moved')
    previous = json.loads((moved / 'batch.json').read_text())
    before = {p.relative_to(moved): p.read_bytes() for p in moved.rglob('*') if p.is_file()}
    target = tmp_path / 'resumed'
    result = batch.resume_condition_batch(moved / 'batch.json', output_dir=target, workers=2,
                                          control=_control(tmp_path))
    assert result['status'] == 'completed' and len(result['results']) == 3
    assert [item[0] for item in result['results']] == ['stop', 'mid', 'high']
    assert result['results'][0][1].metadata['test_resumed_step'] == 1
    for old, row, (_, field, _) in zip(previous['conditions'], result['conditions'], result['results']):
        assert row['case_id'] == old['case_id'] == field.case_id
        if old['status'] == 'completed':
            assert row['reused_from'] == str(moved / old['directory'])
            assert field.result_id == load_result(moved / old['result_file']).result_id
    assert {p.relative_to(moved): p.read_bytes() for p in moved.rglob('*') if p.is_file()} == before
    assert result['resumed_from'] == str(moved)


def test_completed_batch_replay_retains_objectives_without_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions(2)
    source = tmp_path / 'complete'
    original = batch.evaluate_condition_batch(conditions, output_dir=source, workers=2,
        baseline=_baseline(conditions), control=_control(tmp_path))
    monkeypatch.setattr(batch, '_run_native_condition', lambda *a: pytest.fail('completed member recomputed'))
    result = batch.resume_condition_batch(source / 'batch.json', output_dir=tmp_path/'copied', workers=2, control=_control(tmp_path))
    assert result['status'] == 'completed' and result['objectives'] == original['objectives']
    assert [item[1].result_id for item in result['results']] == [item[1].result_id for item in original['results']]


def test_worker_exit_keeps_last_complete_checkpoint(tmp_path, monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('crash', *conditions[0][1:])
    root = tmp_path / 'worker-exit'
    with pytest.raises(BrokenProcessPool):
        batch.evaluate_condition_batch(conditions, output_dir=root, workers=2, control=_control(tmp_path))
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == 'failed' and record['objectives'] is None
    assert record['conditions'][2]['status'] == 'not_run'
    assert all(row['status'] not in ('running', 'computed') for row in record['conditions'])
    assert (root / 'condition_001/run/checkpoint.h5').is_file()


def test_parent_callback_error_is_retained_after_workers_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    error = ValueError('parent callback failed')
    def iteration(message):
        raise error
    root = tmp_path / 'callback-error'
    with pytest.raises(ValueError) as caught:
        batch.evaluate_condition_batch(_conditions(), output_dir=root, workers=2,
                                       control=_control(tmp_path, iteration=iteration))
    assert caught.value is error
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == 'failed' and 'parent callback failed' in record['reason']
    assert record['conditions'][2]['status'] == 'not_run'
    assert all(row['status'] not in ('running', 'computed') for row in record['conditions'])


@pytest.mark.parametrize('damage,reason', [
    ('membership', 'membership differ'), ('case_id', 'identity differ'),
    ('flow', 'mass flow A differs'), ('config', 'configuration differs'),
    ('baseline', 'baseline must retain the original uniform design'),
])
def test_batch_resume_rejects_changed_saved_inputs(tmp_path, monkeypatch, damage, reason):
    from sjtu_tpmshx.io.result_io import save_result
    from sjtu_tpmshx.workflows import recovery

    monkeypatch.setattr(recovery, 'run_case', lambda case, control, **kw: _native(case))
    conditions = _conditions(1)
    source = tmp_path / 'complete'
    batch.evaluate_condition_batch(conditions, output_dir=source,
        baseline=_baseline(conditions), control=_control(tmp_path))
    record_path = source / 'batch.json'
    record = json.loads(record_path.read_text())
    input_path = source / 'batch-input.json'
    inputs = json.loads(input_path.read_text())
    if damage == 'membership':
        inputs[0]['condition_id'] = 'changed'
    elif damage == 'case_id':
        record['conditions'][0]['case_id'] = 'changed'
    elif damage == 'flow':
        inputs[0]['mass_flow_A_kg_s'] *= 1.1
    elif damage == 'config':
        inputs[0]['config']['fluid_A']['T_in_K'] += 1.
    else:
        file = source / record['baseline_files'][0]['result_file']
        field = load_result(file)
        save_result(replace(field, metadata={**field.metadata, 'design_mode': 'zones'}), file)
    record_path.write_text(json.dumps(record))
    input_path.write_text(json.dumps(inputs))
    monkeypatch.setattr(recovery, 'run_case', lambda *a, **kw: pytest.fail('invalid archive recomputed'))
    destination = tmp_path / 'rejected'
    with pytest.raises(ValueError, match=reason):
        batch.resume_condition_batch(record_path, output_dir=destination, control=_control(tmp_path))
    if (destination / 'batch.json').is_file():
        saved = json.loads((destination / 'batch.json').read_text())
        assert saved['status'] == 'failed' and saved['objectives'] is None


def test_process_batch_resolves_relative_output_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions(2)
    control = _control(tmp_path)
    monkeypatch.chdir(tmp_path)
    report = batch.evaluate_condition_batch(conditions, output_dir='relative-output',
                                           control=control, workers=2)
    assert report['status'] == 'completed'
    assert all((tmp_path / 'relative-output' / row['result_file']).is_file()
               for row in report['conditions'])



def test_pre_cancelled_batch_keeps_inputs_without_loading_missing_library(tmp_path, monkeypatch):
    from sjtu_tpmshx.workflows import recovery

    conditions = _conditions(1)
    source = tmp_path / 'pre-cancelled'
    control = RunControl(backend='cpp', native_library=str(tmp_path / 'missing-library'), cancel_check=lambda: True)
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=source, baseline=_baseline(conditions), control=control)
    record = json.loads((source / 'batch.json').read_text())
    assert record['status'] == 'cancelled' and record['conditions'][0]['status'] == 'not_run'
    assert (source / 'batch-input.json').is_file()
    assert record['baseline_files'] and 'native_file' not in record
    monkeypatch.setattr(recovery, 'run_case', lambda case, control, **kw: _native(case))
    resumed = batch.resume_condition_batch(source / 'batch.json', output_dir=tmp_path / 'resumed', control=_control(tmp_path))
    assert resumed['status'] == 'completed'
    assert resumed['objectives'] == pytest.approx(dict(heat_gain_percent=0., pressure_ratio=1.))


@pytest.mark.parametrize('backend,available,limit,members,workers,expected', [
    ('cpp', 8, None, 5, None, 4),
    ('cpp', 8, 4, 5, None, 2),
    ('cpp', 3, None, 5, None, 1),
    ('cpp', 1, None, 5, None, 1),
    ('cpp', 8, None, 1, None, 1),
    ('cpp', 8, 4, 5, 4, 4),
    ('cpp', 8, 1, 5, 4, 1),
    ('cpp', 8, 8, 5, 1, 1),
])
def test_default_worker_count_is_saved_before_cancellation(
        tmp_path, monkeypatch, backend, available, limit, members, workers, expected):
    monkeypatch.setattr(os, 'cpu_count', lambda: available)
    template = _conditions(1)[0]
    conditions = [(f'condition-{index}', *template[1:]) for index in range(members)]
    control = RunControl(backend=backend, cpu_threads=limit, cancel_check=lambda: True)
    root = tmp_path / 'cancelled'
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=root, control=control, workers=workers)
    record = json.loads((root / 'batch.json').read_text())
    assert record['workers'] == expected
    assert record['native_cpu_budget'] == min(limit or 8, available)
    assert record['status'] == 'cancelled'
    assert len(record['conditions']) == members
    assert all(row['status'] == 'not_run' for row in record['conditions'])


def test_default_process_batch_and_recovery_keep_complete_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'cpu_count', lambda: 8)
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions.append(('extra', *conditions[-1][1:]))
    control = replace(_control(tmp_path), cpu_threads=8)
    source = tmp_path / 'automatic'
    report = batch.evaluate_condition_batch(conditions, output_dir=source,
        baseline=_baseline(conditions), control=control)
    assert report['status'] == 'completed' and report['workers'] == 4
    assert report['native_cpu_budget'] == 8
    assert [name for name, _, _ in report['results']] == [row[0] for row in conditions]
    for row, (_, field, _) in zip(report['conditions'], report['results']):
        assert row['worker_pid'] != os.getpid() and row['cpu_threads'] == 2
        assert field.metadata['test_cpu_threads'] == 2
        assert (source / row['result_file']).is_file()
        assert (source / row['checkpoint_file']).is_file()
    resumed = batch.resume_condition_batch(source / 'batch.json',
        output_dir=tmp_path / 'recovered', control=replace(control, cpu_threads=4))
    assert resumed['status'] == 'completed' and resumed['workers'] == 2
    assert resumed['objectives'] == report['objectives']
    assert all(row['recovery_mode'] == 'completed_copy' for row in resumed['conditions'])
