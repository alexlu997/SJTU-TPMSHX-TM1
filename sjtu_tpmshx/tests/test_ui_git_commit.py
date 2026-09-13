"""UI provenance follows the source checkout, including linked worktrees."""
import subprocess
import os

import pytest

from sjtu_tpmshx.domain.provenance import repository_revision


@pytest.mark.parametrize('override', [None, 'GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE'])
def test_source_checkout_worktree_and_no_metadata(tmp_path, monkeypatch, override):
    def git(root, *args):
        return subprocess.check_output(
            ['git', '-C', str(root), *args], text=True,
            stderr=subprocess.DEVNULL,
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
    revisions = []
    with monkeypatch.context() as env_patch:
        if override:
            target = {'GIT_DIR': foreign / '.git',
                      'GIT_COMMON_DIR': foreign / 'missing-metadata',
                      'GIT_WORK_TREE': foreign}[override]
            env_patch.setenv(override, str(target))
        inherited = os.environ.copy()
        monkeypatch.chdir(repo)  # Different commit from the running worktree.
        assert (worktree / '.git').is_file()
        for root, subject in ((worktree, 'first'), (repo, 'second')):
            context = repository_revision(root)
            assert context['status'] == 'recorded'
            assert context['tracked_changes'] is False
            revisions.append((context['revision'], subject))

        # An installed/frozen layout inside another repo must not inherit its HEAD.
        assert repository_revision(repo / 'installed')['revision'] is None
        assert os.environ == inherited

    # Read source semantics after restoring the intentionally overridden environment.
    # The foreign clone contains all three uniquely named commits.
    for revision, subject in revisions:
        assert git(foreign, 'show', '-s', '--format=%s', revision) == subject


def test_git_unavailable_or_invalid_metadata(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    assert repository_revision(tmp_path)['revision'] is None
    monkeypatch.setenv('PATH', '')
    assert repository_revision(tmp_path)['revision'] is None
