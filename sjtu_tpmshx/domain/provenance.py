"""Source context recorded at module entry, independent of GUI and solvers."""
import os
from pathlib import Path
import subprocess

from sjtu_tpmshx._version import __version__

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def repository_revision(root):
    root = Path(root).resolve()
    if not (root / '.git').exists():
        return dict(revision=None, tracked_changes=None, status='unavailable')
    env = {k:v for k,v in os.environ.items()
           if k not in ('GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE')}
    try:
        revision = subprocess.check_output(['git','rev-parse','--verify','HEAD'],
            cwd=root,env=env,stderr=subprocess.DEVNULL,text=True).strip()
        dirty = subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],
            cwd=root,env=env,stderr=subprocess.DEVNULL,text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return dict(revision=None, tracked_changes=None, status='unavailable')
    return dict(revision=revision, tracked_changes=bool(dirty), status='recorded')


def source_context():
    """A revision context, not a claim that every configured data file was used."""
    pin = SOURCE_ROOT / 'data-revision.txt'
    raw = SOURCE_ROOT / 'data' / 'raw_data'
    return dict(code=dict(package_version=__version__, **repository_revision(SOURCE_ROOT)),
                data=dict(declared_revision=pin.read_text().strip() if pin.exists() else None,
                          raw_data_available=raw.is_dir(),
                          repository=repository_revision(raw.resolve().parent),
                          scope='configured raw-data repository; consumed model versions are model_refs'))
