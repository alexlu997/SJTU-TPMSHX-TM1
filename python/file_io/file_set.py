"""Stage related sibling files and restore previous exports on write failure."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def staged_files(paths, *, remove=()):
    """Write each named file in the yielded directory, then publish the set.

    ponytail: one writer per export target; this recovers Python exceptions,
    not a machine crash. A leftover .tm1-publish-* directory is incomplete
    work (previous/ holds recovery files), never a completed export.
    """
    paths = [Path(p) for p in paths]
    targets = paths + [Path(p) for p in remove]
    if len(set(targets)) != len(targets) or any(p.parent != paths[0].parent for p in targets):
        raise ValueError('export files must be distinct siblings')
    stage = Path(tempfile.mkdtemp(prefix='.tm1-publish-', dir=paths[0].parent))
    keep = False
    try:
        yield stage
        for path in paths:
            if not (stage / path.name).is_file():
                raise FileNotFoundError(f'incomplete export: {path.name}')
        previous = stage / 'previous'
        previous.mkdir()
        backed_up, published = [], []
        try:
            for path in targets:
                if path.exists():
                    if not path.is_file():
                        raise IsADirectoryError(path)
                    os.replace(path, previous / path.name)
                    backed_up.append(path)
            for path in paths:
                os.replace(stage / path.name, path)
                published.append(path)
        except BaseException:
            try:
                for path in reversed(published):
                    path.unlink()
                for path in reversed(backed_up):
                    os.replace(previous / path.name, path)
            except OSError as exc:
                keep = True
                raise OSError(f'export recovery incomplete; retained files: {stage}') from exc
            raise
    finally:
        if not keep:
            shutil.rmtree(stage)
