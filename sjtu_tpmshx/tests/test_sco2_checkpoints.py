"""Keep the full denominator and completed evidence across interrupted Q runs."""
import copy
import json
import os
import subprocess

import pandas as pd
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner
from sjtu_tpmshx.validation.cases import _sco2_checkpoints as checkpoints
from sjtu_tpmshx.validation.cases._sco2_checkpoints import runtime_identity


@pytest.fixture
def batch(monkeypatch):
    frame = pd.DataFrame([
        dict(case=case, side=side, ok_done=True, ok_hb=True, ok_heat_flow=True,
             Tin_C=100., Tout_C=90., Pin_MPa=9., Pout_MPa=8.9,
             Pin_abs_Pa=9101325., Pout_abs_Pa=9001325., mdot=.05)
        for case in (1, 2, 3) for side in ('hot', 'cold')])
    frame.attrs['reference'] = {'version': 'synthetic'}
    identity = dict(commit='test-clean-commit', dirty=False, packages={'numpy': ['2.0']})
    monkeypatch.setattr(checkpoints, 'runtime_identity', lambda root, **kw: copy.deepcopy(identity))
    monkeypatch.setattr(runner, 'load_exp', lambda topology: frame.copy())
    monkeypatch.setattr(runner, '_print_geometry', lambda *args: None)
    monkeypatch.setattr(runner, '_print_summary', lambda *args: None)
    calls = []

    def solve(topology, case, dimension, _frame):
        calls.append((topology, case, dimension))
        return dict(topology=topology, case=case, dimension=dimension,
                    converged=True, numerical_ok=True, reference_ok=True,
                    Q_solver_W=100., Q_ref_W=100., Q_error_rel=0.,
                    Q_hot_exp_W=100., Q_cold_exp_W=100., flow_err_hot_rel=0.,
                    flow_err_cold_rel=0., enthalpy_imbalance_rel=0., df_mode='cfd_smooth')

    monkeypatch.setattr(runner, '_run_case', solve)
    return frame, identity, calls, solve


def run(root=None, **kwargs):
    return runner.run(['Diamond'], ['2d'], case=None, all_valid=True,
                      checkpoint_dir=root, **kwargs)


@pytest.mark.parametrize('error_type,status', [(RuntimeError, 'failed'),
                                              (CancelledError, 'cancelled'),
                                              (KeyboardInterrupt, 'cancelled')])
def test_resume_keeps_failed_attempt_and_skips_only_completed(batch, tmp_path, monkeypatch,
                                                            error_type, status):
    _, _, calls, solve = batch
    error = error_type('second member stopped')

    def interrupt(topology, case, dimension, frame):
        if case == 2:
            raise error
        return solve(topology, case, dimension, frame)

    monkeypatch.setattr(runner, '_run_case', interrupt)
    with pytest.raises(error_type) as caught:
        run(tmp_path)
    assert caught.value is error
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['snapshot']['expected_cases'] == {'Diamond': [1, 2, 3]}
    assert [member['status'] for member in state['members'].values()] == ['completed', status, 'pending']
    assert state['status'] == status
    assert pd.read_csv(tmp_path / 'partial.csv')['case'].tolist() == [1]
    monkeypatch.setattr(runner, '_run_case', solve)
    resumed = run(tmp_path, resume=True)
    assert [case for _, case, _ in calls] == [1, 2, 3]
    state = json.loads((tmp_path / 'state.json').read_text())
    assert [attempt['status'] for attempt in state['members']['Diamond/2d/2']['attempts']] == [status, 'completed']
    assert runner._accept_q(resumed, resumed.attrs['expected_cases'], ['2d'])
    pd.testing.assert_frame_equal(resumed, run(), check_dtype=False)


def test_all_topologies_are_selected_before_first_solve(batch, tmp_path, monkeypatch):
    frame, _, _, _ = batch
    def missing(topology):
        if topology == 'Gyroid':
            raise ValueError('missing reference')
        return frame
    monkeypatch.setattr(runner, 'load_exp', missing)
    monkeypatch.setattr(runner, '_run_case', lambda *a: pytest.fail('solver started before selection'))
    with pytest.raises(ValueError, match='missing reference'):
        runner.run(['Diamond', 'Gyroid'], ['2d'], case=None, all_valid=True,
                   checkpoint_dir=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('change', ['commit', 'dirty', 'packages', 'reference', 'row', 'grid'])
def test_resume_rejects_changed_inputs_before_solving(batch, tmp_path, monkeypatch, change):
    frame, identity, _, _ = batch
    run(tmp_path)
    if change == 'commit': identity['commit'] = 'another-commit'
    elif change == 'dirty': identity['dirty'] = True
    elif change == 'packages': identity['packages']['numpy'] = ['3.0']
    elif change == 'reference': frame.attrs['reference']['version'] = 'changed'
    elif change == 'row': frame.loc[0, 'mdot'] += .000001
    else: monkeypatch.setattr(runner, 'N_STREAM', runner.N_STREAM + 1)
    monkeypatch.setattr(runner, '_run_case', lambda *a: pytest.fail('mismatched checkpoint reused'))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='checkpoint|clean code'):
        run(tmp_path, resume=True)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'value', 'unexpected'])
def test_resume_rejects_incomplete_or_mixed_csv(batch, tmp_path, monkeypatch, damage):
    run(tmp_path)
    path = tmp_path / 'partial.csv'
    frame = pd.read_csv(path)
    if damage == 'missing': frame = frame.iloc[1:]
    elif damage == 'duplicate': frame = pd.concat([frame, frame.iloc[:1]])
    elif damage == 'value': frame.loc[0, 'Q_solver_W'] = 120.
    else: frame.loc[0, 'case'] = 99
    frame.to_csv(path, index=False)
    monkeypatch.setattr(runner, '_run_case', lambda *a: pytest.fail('invalid evidence reused'))
    with pytest.raises(ValueError, match='checkpoint'):
        run(tmp_path, resume=True)


def test_numerically_failed_member_is_preserved_then_retried(batch, tmp_path, monkeypatch):
    _, _, calls, solve = batch
    def failed(*args):
        row = solve(*args)
        if row['case'] == 2:
            row.update(numerical_ok=False, converged=False)
        return row
    monkeypatch.setattr(runner, '_run_case', failed)
    first = run(tmp_path)
    assert len(first) == 3 and not runner._accept_q(first, first.attrs['expected_cases'], ['2d'])
    calls.clear()
    monkeypatch.setattr(runner, '_run_case', solve)
    resumed = run(tmp_path, resume=True)
    assert calls == [('Diamond', 2, '2d')]
    state = json.loads((tmp_path / 'state.json').read_text())
    assert len(state['members']['Diamond/2d/2']['attempts']) == 2
    assert len(resumed) == 3


def test_failed_pair_publication_preserves_previous_checkpoint(batch, tmp_path, monkeypatch):
    from sjtu_tpmshx.io import file_set
    result = run(tmp_path)
    state = json.loads((tmp_path / 'state.json').read_text())
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    replace = file_set.os.replace
    def fail_state(source, target):
        if source.parent.name.startswith('.tm1-publish-') and target == tmp_path / 'state.json':
            raise OSError('state publication failed')
        return replace(source, target)
    monkeypatch.setattr(file_set.os, 'replace', fail_state)
    state['status'] = 'failed'
    with pytest.raises(OSError, match='state publication failed'):
        checkpoints.publish(tmp_path, state,
                            {checkpoints.member_key(row): row for row in result.to_dict('records')})
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_programmatic_run_has_no_implicit_file_output(batch, monkeypatch):
    monkeypatch.setattr(checkpoints, 'publish', lambda *a: pytest.fail('unexpected write'))
    assert len(run()) == 3


def test_cli_cancel_has_nonzero_native_exit(batch, tmp_path, monkeypatch):
    def cancel(*a, **kw): raise CancelledError('cancelled')
    monkeypatch.setattr(runner, '_run_case', cancel)
    monkeypatch.setattr('sys.argv', ['runner', '--topology', 'Diamond', '--dimension', '2d',
                                   '--all-valid', '--out-dir', str(tmp_path)])
    assert runner.main() == 130
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['status'] == 'cancelled'
    assert len(state['members']) == 3


def test_cli_checkpoint_and_final_output_cannot_overlap(batch, tmp_path, monkeypatch):
    monkeypatch.setattr('sys.argv', ['runner', '--out-dir', str(tmp_path),
                                   '--csv', str(tmp_path / 'partial.csv')])
    monkeypatch.setattr(runner, 'run', lambda *a, **kw: pytest.fail('path collision launched'))
    with pytest.raises(SystemExit) as caught:
        runner.main()
    assert caught.value.code == 2


def test_runtime_identity_excludes_only_known_untracked_outputs(tmp_path, monkeypatch):
    import subprocess
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    source = tmp_path / 'solver.py'
    source.write_text('value = 1\n')
    git('add', 'solver.py')
    git('-c', 'user.name=Checkpoint Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'fixture')
    monkeypatch.setattr(checkpoints, 'installed_versions', lambda: {})
    report = tmp_path / 'output' / 'partial.csv'
    report.parent.mkdir()
    identity = checkpoints.runtime_identity(tmp_path, generated=[report, source])
    assert not identity['dirty']
    report.write_text('case,Q\n1,100\n')
    assert checkpoints.runtime_identity(tmp_path, generated=[report]) == identity
    unknown = tmp_path / 'extra.py'
    unknown.write_text('other = 2\n')
    assert checkpoints.runtime_identity(tmp_path, generated=[report])['dirty']
    unknown.unlink()
    source.write_text('value = 3\n')
    assert checkpoints.runtime_identity(tmp_path, generated=[report, source])['dirty']


def _git(root, *args):
    return subprocess.check_output(
        ['git', '-C', str(root), '-c', 'user.name=Checkpoint Test',
         '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', *args],
        text=True, stderr=subprocess.DEVNULL).strip()


@pytest.mark.parametrize('metadata', ['absent', 'empty'])
def test_resume_rejects_unidentified_copy_inside_parent_repo(batch, tmp_path, monkeypatch,
                                                           metadata):
    repo = tmp_path / 'parent'
    repo.mkdir()
    _git(repo, 'init')
    (repo / '.gitignore').write_text('installed/\n')
    _git(repo, 'add', '.gitignore')
    _git(repo, 'commit', '-m', 'parent repository')
    installed = repo / 'installed'
    installed.mkdir()
    source = installed / 'solver.py'
    source.write_text('value = 1\n')
    if metadata == 'empty':
        (installed / '.git').mkdir()
    monkeypatch.setattr(checkpoints, 'runtime_identity', runtime_identity)
    monkeypatch.setattr(checkpoints, 'installed_versions', lambda: {})
    monkeypatch.setattr(runner, 'REPO_ROOT', installed)
    output = installed / 'checkpoint'
    run(output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    source.write_text('value = 2\n')
    monkeypatch.setattr(runner, '_run_case', lambda *a: pytest.fail('unidentified copy resumed'))
    with pytest.raises(ValueError, match='identified clean code checkout'):
        run(output, resume=True)
    identity = json.loads((output / 'state.json').read_text())['snapshot']['runtime']
    assert identity['commit'] == '' and identity['dirty'] is True
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


@pytest.mark.parametrize('linked', [False, True])
@pytest.mark.parametrize('override', [None, 'GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE'])
def test_resume_uses_own_checkout_despite_external_git_environment(
        batch, tmp_path, monkeypatch, linked, override):
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init')
    (repo / 'solver.py').write_text('value = 1\n')
    _git(repo, 'add', 'solver.py')
    _git(repo, 'commit', '-m', 'first source')
    worktree = tmp_path / 'worktree'
    _git(repo, 'worktree', 'add', '--detach', str(worktree), 'HEAD')
    (repo / 'solver.py').write_text('value = 2\n')
    _git(repo, 'commit', '-am', 'second source')
    root = worktree if linked else repo
    revision = _git(root, 'rev-parse', 'HEAD')
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    _git(foreign, 'init')
    (foreign / 'solver.py').write_text('foreign = True\n')
    _git(foreign, 'add', 'solver.py')
    _git(foreign, 'commit', '-m', 'foreign source')
    monkeypatch.setattr(checkpoints, 'runtime_identity', runtime_identity)
    monkeypatch.setattr(checkpoints, 'installed_versions', lambda: {})
    monkeypatch.setattr(runner, 'REPO_ROOT', root)
    output = root / 'checkpoint'
    expected = run(output)
    identity = json.loads((output / 'state.json').read_text())['snapshot']['runtime']
    assert identity['commit'] == revision and identity['dirty'] is False
    if override:
        target = {'GIT_DIR': foreign / '.git',
                  'GIT_COMMON_DIR': foreign / 'missing-metadata',
                  'GIT_WORK_TREE': foreign}[override]
        monkeypatch.setenv(override, str(target))
    inherited = os.environ.copy()
    monkeypatch.setattr(runner, '_run_case', lambda *a: pytest.fail('completed member reran'))
    pd.testing.assert_frame_equal(run(output, resume=True), expected, check_dtype=False)
    # Known untracked checkpoint outputs are excluded; modified tracked code never is.
    source = root / 'solver.py'
    source.write_text('value = 3\n')
    with pytest.raises(ValueError, match='identified clean code checkout'):
        run(output, resume=True, output_paths=(source,))
    assert os.environ == inherited
