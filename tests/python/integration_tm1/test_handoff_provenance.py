"""Preparation and execution origins survive independent file handoff."""
import os
import subprocess

import pytest
from tm1.file_io.case_io import load_case, save_case
from tm1.file_io.result_io import load_result, save_result
from tm1.preprocess import _metadata
from tm1.preprocess import api as preparation
from tm1.solvers import api as execution
from tm1.run_control.provenance import repository_revision, source_context
from tests.python.integration_tm1.integration_support import baseline_config


@pytest.mark.slow
def test_provenance_survives_case_and_result(tmp_path, monkeypatch):
    prepared = {'code':{'revision':'preparation-revision'}, 'data':{'declared_revision':'input-revision'}}
    solved = {'code':{'revision':'solver-revision'}, 'data':{'declared_revision':'solver-data-revision'}}
    monkeypatch.setattr(_metadata, 'source_context', lambda: prepared)
    monkeypatch.setattr(execution, 'source_context', lambda: solved)
    case = preparation.prepare_case(baseline_config(), case_id='provenance')
    save_case(case,tmp_path/'case.yaml')
    result = execution.run_case(load_case(tmp_path/'case.yaml'))
    save_result(result,tmp_path/'result.h5')
    result = load_result(tmp_path/'result.h5')
    assert result.metadata['provenance']['preparation']==prepared
    assert result.metadata['provenance']['execution']==solved


def test_missing_repository_is_explicit(tmp_path):
    assert repository_revision(tmp_path)==dict(revision=None,tracked_changes=None,status='unavailable')
    context = source_context()
    assert context['code']['package_version']
    assert 'declared_revision' in context['data']
    assert 'repository' in context['data']


def test_repository_revision_worktree_and_git_env_overrides(tmp_path, monkeypatch):
    """Source provenance resolves linked worktrees and ignores foreign GIT_* variables."""
    def git(root, *args):
        return subprocess.check_output(
            ['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL,
        ).strip()

    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'first')
    worktree = tmp_path / 'worktree'
    git(repo, 'worktree', 'add', '--detach', str(worktree), 'HEAD')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'second')
    foreign = tmp_path / 'foreign'
    git(repo, 'clone', str(repo), str(foreign))
    git(foreign, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'foreign')

    assert (worktree / '.git').is_file()
    overrides = {
        None: None,
        'GIT_DIR': foreign / '.git',
        'GIT_COMMON_DIR': foreign / 'missing-metadata',
        'GIT_WORK_TREE': foreign,
    }
    for override, target in overrides.items():
        installed = repo / f'installed-{override or "none"}'
        revisions = []
        with monkeypatch.context() as env_patch:
            if override is not None:
                env_patch.setenv(override, str(target))
            inherited = os.environ.copy()
            env_patch.chdir(repo)
            for root, subject in ((worktree, 'first'), (repo, 'second')):
                context = repository_revision(root)
                assert context['status'] == 'recorded'
                assert context['tracked_changes'] is False
                revisions.append((context['revision'], subject))
            # An installed layout inside another checkout must not inherit its HEAD.
            assert repository_revision(installed)['revision'] is None
            (installed / '.git').mkdir(parents=True)
            assert repository_revision(installed)['revision'] is None
            assert os.environ == inherited
        for revision, subject in revisions:
            assert git(foreign, 'show', '-s', '--format=%s', revision) == subject


def test_repository_revision_tracks_changes_and_unavailable_metadata(tmp_path, monkeypatch):
    def git(root, *args):
        return subprocess.check_output(
            ['git', '-C', str(root), '-c', 'user.name=Test',
             '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false', *args],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()

    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init')
    assert repository_revision(repo)['status'] == 'unavailable'
    tracked = repo / '# tracked file.txt'
    tracked.write_text('first')
    git(repo, 'add', '--', tracked.name)
    assert repository_revision(repo)['status'] == 'unavailable'
    git(repo, 'commit', '-m', 'first')
    first = repository_revision(repo)
    assert first == dict(revision=git(repo, 'rev-parse', 'HEAD'), tracked_changes=False, status='recorded')
    (repo / 'untracked.txt').write_text('ignored by provenance')
    assert repository_revision(repo) == first
    tracked.write_text('second')
    assert repository_revision(repo) == {**first, 'tracked_changes': True}
    git(repo, 'add', '--', tracked.name)
    assert repository_revision(repo) == {**first, 'tracked_changes': True}
    git(repo, 'commit', '-m', 'second')
    current = repository_revision(repo)
    assert current == dict(revision=git(repo, 'rev-parse', 'HEAD'), tracked_changes=False, status='recorded')
    assert current['revision'] != first['revision']

    invalid = tmp_path / 'invalid'
    (invalid / '.git').mkdir(parents=True)
    assert repository_revision(invalid)['revision'] is None
    monkeypatch.setenv('PATH', '')
    assert repository_revision(repo)['revision'] is None
