"""Search recovery keeps proposal identity, used budget and original evidence."""
import json
from dataclasses import asdict, replace
from threading import Event

import numpy as np
import pytest

from tm1.run_control.module_ports import RunControl
from tm1.data_types.compute_config import ZoneInputConfig
from tm1.run_control.paused_run import PausedRun
from tm1.applications.optimization import multi_condition_optimizer as search
from tests.python.optimization_support import _conditions, _fake_batches, _manifest


@pytest.mark.parametrize('changed', [False, True])
def test_old_disabled_grid_flag_does_not_change_search_identity(tmp_path, monkeypatch, changed):
    _fake_batches(monkeypatch)
    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(_conditions(), output_dir=source,
            method='sobol', n_init=2, n_iter=0, workers=1, pause_check=lambda: True)
    for name in ('optimization.json', 'optimization-input.json'):
        path = source / name
        record = json.loads(path.read_text())
        for row in record['conditions']:
            row['config']['flags']['wall_refine_3d'] = False
        if changed and name == 'optimization.json':
            record['conditions'][0]['config']['flags']['variable_rho_cp'] = False
        path.write_text(json.dumps(record))
    before = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    target = tmp_path / 'resumed'
    if changed:
        with pytest.raises(ValueError, match='saved search conditions differ'):
            search.resume_multi_condition_optimization(source / 'optimization.json', output_dir=target, workers=1)
        assert not target.exists()
    else:
        result = search.resume_multi_condition_optimization(source / 'optimization.json', output_dir=target, workers=1)
        assert result['status'] == 'completed' and result['n_usable'] == 2
    assert {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()} == before


@pytest.mark.parametrize('shared', ['config', 'fluid'])
def test_resume_keeps_each_flow_when_conditions_share_input_objects(tmp_path, monkeypatch, shared):
    _fake_batches(monkeypatch)
    config = _conditions()[0][1]
    second = config if shared == 'config' else replace(config,
        fluid_A=replace(config.fluid_A, T_in_K=config.fluid_A.T_in_K+10.))
    conditions = [('first', config, .01, .02), ('second', second, .02, .04)]
    before = [asdict(row[1]) for row in conditions]
    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(conditions, output_dir=source,
            method='sobol', n_init=2, n_iter=0, workers=1, pause_check=lambda: True)
    frozen = json.loads((source / 'optimization-input.json').read_text())
    assert [[row['config']['fluid_'+side]['mass_flow_kg_s'] for side in 'AB']
            for row in frozen['conditions']] == [[.01, .02], [.02, .04]]
    result = search.resume_multi_condition_optimization(source / 'optimization.json',
        output_dir=tmp_path / 'resumed', workers=1)
    assert result['status'] == 'completed' and result['n_usable'] == 2
    assert [asdict(row[1]) for row in conditions] == before


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('cut', ['baseline', 'initial'])
def test_resume_normalizes_existing_continuous_field_before_freezing_input(
        tmp_path, monkeypatch, enabled, cut):
    _fake_batches(monkeypatch)
    conditions = _conditions()[:1]
    config = conditions[0][1]
    config.zones = ZoneInputConfig(enabled=enabled, axis='continuous', config=dict(
        n_ctrl_x=2, n_ctrl_y=2, symmetric_y=False, spline_order=1,
        L_bounds=[4., 8.], t_bounds=[.3, .6], x_decision=[6.]*4+[.4]*4))
    config.validate()
    before = asdict(config)
    pause = Event()
    source = tmp_path / 'source'
    def update(state):
        if state['report']['stage'] == cut:
            pause.set()
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(conditions, output_dir=source,
            method='sobol', n_init=2, n_iter=0, workers=1,
            pause_check=pause.is_set, on_update=update)
    frozen = json.loads((source / 'optimization-input.json').read_text())
    assert frozen['conditions'][0]['config']['zones'] == asdict(ZoneInputConfig())
    result = search.resume_multi_condition_optimization(source / 'optimization.json',
        output_dir=tmp_path / 'resumed', workers=1)
    assert result['status'] == 'completed' and result['n_usable'] == 2
    assert asdict(config) == before


@pytest.mark.parametrize('cut', ['baseline', 'initial', 'model_fit', 'proposal', 'evaluation', 'saving'])
def test_pause_move_resume_keeps_budget_proposals_and_completed_observations(tmp_path, monkeypatch, cut):
    calls = _fake_batches(monkeypatch, fail_indices=(1,))
    monkeypatch.setattr(search, '_bo_versions', lambda: {})
    proposals = []
    def propose(X, Y, lower, upper, reference, **kwargs):
        kwargs['on_stage']('model_fit')
        kwargs['on_stage']('proposal')
        proposals.append(kwargs['seed'])
        return np.vstack((lower+.2*(upper-lower), lower+.8*(upper-lower)))
    monkeypatch.setattr(search, '_propose_bo', propose)
    pause = Event()
    source = tmp_path / 'source'
    def update(state):
        report = state['report']
        if (cut == report['stage'] and
                (cut != 'proposal' or proposals == [])):
            pause.set()
        if cut == 'saving' and report['history'] and report['history'][0]['status'] == 'completed':
            pause.set()
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(_conditions(), output_dir=source, method='qlognehvi',
            n_init=3, n_iter=2, q_batch=2, seed=17, workers=1,
            pause_check=pause.is_set, on_update=update)
    saved = _manifest(source)
    assert saved['status'] == 'paused'
    complete = [row['index'] for row in saved['history'] if row['status'] == 'completed']
    moved = source.rename(tmp_path / 'moved')
    before = {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()}
    earlier = list(calls)
    progress = []
    result = search.resume_multi_condition_optimization(moved / 'optimization.json',
        output_dir=tmp_path / 'resumed', workers=1, control=RunControl(progress=progress.append))
    assert result['status'] == 'completed'
    assert result['n_evaluated'] == result['design_budget'] == 7
    assert result['n_usable'] == 6 and result['history'][1]['status'] == 'failed'
    assert proposals == [18, 19]
    assert result['proposals'][:len(saved['proposals'])] == saved['proposals']
    assert progress == sorted(progress) and progress[-1] == 100
    assert not {f'design_{index:04d}' for index in complete}.intersection(
        row[2].name for row in calls[len(earlier):])
    assert {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()} == before
    assert result == _manifest(tmp_path / 'resumed')


def test_second_pause_keeps_all_retained_evidence_in_the_new_directory(tmp_path, monkeypatch):
    calls = _fake_batches(monkeypatch)
    original = tmp_path / 'original'
    expected = search.run_multi_condition_optimization(_conditions(), output_dir=original,
        method='sobol', n_init=2, n_iter=1, workers=1)
    copied = tmp_path / 'copied'
    with pytest.raises(PausedRun):
        search.resume_multi_condition_optimization(original / 'optimization.json',
            output_dir=copied, workers=1, pause_check=lambda: True)
    original.rename(tmp_path / 'unavailable')
    result = search.resume_multi_condition_optimization(copied / 'optimization.json',
        output_dir=tmp_path / 'finished', workers=1)
    assert len(calls) == 4
    assert result['n_usable'] == expected['n_usable'] == 3
    assert [row['model_y'] for row in result['history']] == [row['model_y'] for row in expected['history']]


@pytest.mark.parametrize('change', ['method', 'seed', 'n_iter', 'field_spec', 'conditions', 'decision',
                                   'proposal', 'reference', 'observation'])
def test_resume_rejects_changed_search_contract_before_creating_output(tmp_path, monkeypatch, change):
    _fake_batches(monkeypatch)
    root = tmp_path / 'source'
    result = search.run_multi_condition_optimization(_conditions(), output_dir=root,
        method='sobol', n_init=2, n_iter=1, workers=1)
    if change == 'method':
        result['method'] = 'qlognehvi'
    elif change == 'seed':
        result['seed'] += 1
    elif change == 'n_iter':
        result['n_iter'] += 1
    elif change == 'field_spec':
        result['field_spec']['n_ctrl_x'] += 1
    elif change == 'conditions':
        result['conditions'][0]['config']['fluid_A']['T_in_K'] += 1
    elif change == 'decision':
        result['history'][0]['x_decision'][0] += .01
    elif change == 'proposal':
        result['proposals'][0]['x_decisions'][0][0] += .01
    elif change == 'reference':
        result['ref_point'][0] += 1
    else:
        result['history'][0]['model_y'][0] += 1
    (root / 'optimization.json').write_text(json.dumps(result))
    with pytest.raises(ValueError):
        search.resume_multi_condition_optimization(root / 'optimization.json',
            output_dir=tmp_path / 'invalid', workers=1)
    assert not (tmp_path / 'invalid').exists()


def test_pause_save_failure_keeps_primary_error_and_does_not_claim_saved_pause(tmp_path, monkeypatch):
    from tests.python.optimization_support import _checkpoint_fault
    _fake_batches(monkeypatch)
    _checkpoint_fault(monkeypatch, search, 'optimization.json',
        lambda record, _: record['status'] == 'paused', persistent=True)
    output = tmp_path / 'search'
    with pytest.raises(PausedRun) as caught:
        search.run_multi_condition_optimization(_conditions(), output_dir=output,
            method='sobol', n_init=1, n_iter=0, workers=1, pause_check=lambda: True)
    assert 'checkpoint write failed' in '\n'.join(caught.value.__notes__)
    assert _manifest(output)['status'] == 'running'


@pytest.mark.parametrize('alias', ['none', 'symlink', 'case'])
@pytest.mark.parametrize('nested', [False, True])
def test_resume_rejects_destination_inside_the_source(tmp_path, monkeypatch, alias, nested):
    _fake_batches(monkeypatch)
    source = tmp_path / 'source'
    search.run_multi_condition_optimization(_conditions(), output_dir=source,
        method='sobol', n_init=1, n_iter=0, workers=1)
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    target = source
    if alias == 'symlink':
        target = tmp_path / 'source-alias'
        target.symlink_to(source, target_is_directory=True)
    elif alias == 'case':
        target = source.with_name('SOURCE')
        if not target.exists():
            pytest.skip('requires a case-insensitive filesystem')
    if nested:
        target /= 'continued'
    monkeypatch.setattr(search.shutil, 'copytree',
        lambda *args, **kwargs: pytest.fail('recovery must reject the source before copying'))
    with pytest.raises(ValueError, match='outside'):
        search.resume_multi_condition_optimization(source / 'optimization.json',
            output_dir=target, workers=1)
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()} == before
    if nested:
        assert not target.exists()


def test_search_with_real_batches_resumes_moved_archive_like_uninterrupted_search(tmp_path, monkeypatch):
    from tests.python.optimization_tm1.test_multi_condition_batch import _conditions as batch_conditions, _native, _patch_solve

    solved = []

    def solve(case, control):
        solved.append(case.case_id)
        return _native(case)

    _patch_solve(monkeypatch, solve)
    library = tmp_path / 'analytic-library'
    library.write_bytes(b'non-executable test data')
    control = RunControl(native_library=str(library), cpu_threads=1)
    conditions = batch_conditions(2)
    options = dict(method='sobol', n_init=2, n_iter=1, workers=1)
    expected = search.run_multi_condition_optimization(conditions, output_dir=tmp_path / 'expected',
                                                       control=control, **options)
    assert expected['status'] == 'completed'
    budget = len(solved)
    assert budget == 2 * (expected['design_budget'] + expected['baseline_batches'])
    del solved[:]
    stop = []

    def update(state):
        # Pause inside the second design batch after its first member is published.
        if len(state['report']['history']) == 2 and any(
                row['status'] == 'completed' for row in state['conditions']):
            stop.append(True)

    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(conditions, output_dir=source, control=control,
            on_update=update, pause_check=lambda: bool(stop), **options)
    saved = _manifest(source)
    assert [row['status'] for row in saved['history']] == ['completed', 'paused']
    batch_record = json.loads((source / 'design_0001/batch.json').read_text())
    assert [row['status'] for row in batch_record['conditions']] == ['completed', 'not_run']
    moved = source.rename(tmp_path / 'moved')
    before = {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()}
    target = tmp_path / 'resumed'
    result = search.resume_multi_condition_optimization(moved / 'optimization.json',
                                                        output_dir=target, control=control, workers=1)
    assert len(solved) == budget
    assert result['status'] == 'completed'
    for key in ('design_budget', 'n_evaluated', 'n_usable', 'pareto_indices', 'initial_designs'):
        assert result[key] == expected[key]
    assert [row['x_decisions'] for row in result['proposals']] == [
        row['x_decisions'] for row in expected['proposals']]
    assert [(row['status'], row['x_decision'], row['objectives'], row['model_y']) for row in result['history']] == [
        (row['status'], row['x_decision'], row['objectives'], row['model_y']) for row in expected['history']]
    continued = json.loads((target / 'design_0001/batch.json').read_text())
    assert continued['resumed_from'] == str(target.resolve() / 'design_0001')
    assert [row['recovery_mode'] for row in continued['conditions']] == ['completed_copy', 'new']
    assert {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()} == before


def test_optimize_route_continues_or_repeats_a_saved_search(tmp_path, monkeypatch, capsys):
    from tm1.applications.optimization.cli import run
    _fake_batches(monkeypatch)
    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(_conditions(), output_dir=source,
            method='sobol', n_init=2, n_iter=0, workers=1, pause_check=lambda: True)
    frozen = json.loads((source / 'optimization-input.json').read_text())
    for name, target in (('optimization.json', 'resumed'), ('optimization-input.json', 'repeated')):
        assert run([str(source / name), str(tmp_path / target), '--workers', '1']) == 0
        result = _manifest(tmp_path / target)
        assert result['status'] == 'completed' and result['n_usable'] == 2
        assert json.loads((tmp_path / target / 'optimization-input.json').read_text()) == frozen
    statuses = [line for line in capsys.readouterr().out.splitlines() if line.startswith('status = ')]
    assert statuses == ['status = completed'] * 2
    with pytest.raises(ValueError, match='outside the saved search'):
        run([str(source / 'optimization-input.json'), str(source / 'baseline'), '--workers', '1'])
    assert not (source / 'baseline').exists()


@pytest.mark.parametrize('saved', [True, False])
def test_optimize_route_reports_the_search_pause_only_after_it_is_saved(tmp_path, monkeypatch, capsys, saved):
    import signal
    from tests.python.optimization_support import _checkpoint_fault
    from tm1.applications.optimization.cli import run
    _fake_batches(monkeypatch)
    batch = search.evaluate_compact_condition_batch

    def interrupted(*args, **kwargs):
        # The terminal Ctrl+C arrives while the baseline batch runs; the batch pauses at its boundary.
        signal.raise_signal(signal.SIGINT)
        return batch(*args, **kwargs)

    monkeypatch.setattr(search, 'evaluate_compact_condition_batch', interrupted)
    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        search.run_multi_condition_optimization(_conditions(), output_dir=source,
            method='sobol', n_init=1, n_iter=0, workers=1, pause_check=lambda: True)
    output = tmp_path / 'continued'
    if not saved:
        _checkpoint_fault(monkeypatch, search, 'optimization.json',
            lambda record, _: record['status'] == 'paused', persistent=True)
        with pytest.raises(PausedRun) as caught:
            run([str(source / 'optimization.json'), str(output), '--workers', '1'])
        assert 'checkpoint write failed' in '\n'.join(caught.value.__notes__)
        assert 'paused = ' not in capsys.readouterr().out
        return
    assert run([str(source / 'optimization.json'), str(output), '--workers', '1']) == 3
    assert f"paused = {output.resolve() / 'optimization.json'}" in capsys.readouterr().out.splitlines()
    assert _manifest(output)['status'] == 'paused'
