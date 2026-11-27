"""Source context recorded at module entry, independent of GUI and solvers."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import threading

from sjtu_tpmshx._version import __version__

SOURCE_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_LIBRARY_DIR = SOURCE_ROOT / "sjtu_tpmshx/solvers/native/lib"
_study = threading.local()


def repository_environment(root):
    """Keep Git discovery local to this checkout, including linked worktrees."""
    root = Path(root).resolve()
    if not (root / '.git').exists():
        return None
    env = {k:v for k,v in os.environ.items()
           if k not in ('GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE')}
    env['GIT_CEILING_DIRECTORIES'] = str(root.parent)
    return env


def repository_revision(root):
    root = Path(root).resolve()
    env = repository_environment(root)
    if env is None:
        return dict(revision=None, tracked_changes=None, status='unavailable')
    try:
        lines = subprocess.check_output(
            ['git','status','--porcelain=v2','--branch','--no-ahead-behind','--untracked-files=no'],
            cwd=root,env=env,stderr=subprocess.DEVNULL,text=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return dict(revision=None, tracked_changes=None, status='unavailable')
    revision = next((line.removeprefix('# branch.oid ') for line in lines
                     if line.startswith('# branch.oid ')), None)
    if revision in (None, '(initial)'):
        return dict(revision=None, tracked_changes=None, status='unavailable')
    return dict(revision=revision, tracked_changes=any(not line.startswith('# ') for line in lines),
                status='recorded')


def source_context():
    """A revision context, not a claim that every configured data file was used.

    In a study scope, return a copy of the snapshot of that study. Outside a study, read the live source state.
    """
    snapshot = getattr(_study, 'snapshot', None)
    return _live_source_context() if snapshot is None else deepcopy(snapshot)


def _live_source_context():
    pin = SOURCE_ROOT / 'data-revision.txt'
    raw = SOURCE_ROOT / 'data' / 'raw_data'
    return dict(code=dict(package_version=__version__, **repository_revision(SOURCE_ROOT)),
                data=dict(declared_revision=pin.read_text().strip() if pin.exists() else None,
                          raw_data_available=raw.is_dir(),
                          repository=repository_revision(raw.resolve().parent),
                          scope='configured raw-data repository; consumed model versions are model_refs'))


@contextmanager
def study_source(snapshot=None):
    """Record the source context one time for all runs of a study in this thread.

    Each study reads the live source state at entry. A worker process enters this scope
    with the snapshot of its parent study. At exit, the scope restores the previous snapshot.
    """
    previous = getattr(_study, 'snapshot', None)
    _study.snapshot = _live_source_context() if snapshot is None else deepcopy(snapshot)
    try:
        yield
    finally:
        _study.snapshot = previous
