"""Search recovery keeps proposal identity, used budget and original evidence."""
import json
from dataclasses import asdict, replace
from threading import Event

import numpy as np
import pytest

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.compute_config import ZoneInputConfig
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.optimization import multi_condition_optimizer as search
from sjtu_tpmshx.tests.test_multi_condition_optimizer import _conditions, _fake_batches, _manifest


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
    from sjtu_tpmshx.tests.test_optimization_checkpoint_errors import _checkpoint_fault
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
