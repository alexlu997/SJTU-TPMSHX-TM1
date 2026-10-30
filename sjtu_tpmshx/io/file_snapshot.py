"""Share saved files without linking mutable native build outputs."""
import errno
import os
from pathlib import Path
import shutil

from .file_set import staged_files


# Reuse a retained image so native property tables stay in one loaded library.
_runtime_files = {}


def copy_snapshot(source, target):
    """Share an immutable file, or copy it when the filesystem cannot link it."""
    source, target = Path(source), Path(target)
    with staged_files([target]) as stage:
        temporary = stage / target.name
        try:
            os.link(source, temporary)
        except OSError as error:
            # Windows: invalid function (1), unsupported operation (50), too many links (1142).
            if (error.errno not in (errno.EXDEV, errno.EPERM, errno.EACCES,
                                   errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK)
                    and getattr(error, 'winerror', None) not in (1, 50, 1142)):
                raise
            shutil.copy2(source, temporary)
    return str(target)


def copy_saved_file(source, target):
    """Share binary snapshots during recovery; keep editable text independent."""
    if Path(source).suffix.lower() in ('.h5', '.dylib', '.dll', '.so'):
        return copy_snapshot(source, target)
    return shutil.copy2(source, target)


def register_runtime_snapshot(path):
    """Register the fixed parent-batch runtime in a new worker process."""
    path = Path(path).resolve(strict=True)
    _runtime_files[path] = path


def retain_runtime(source, target):
    """Retain a checked runtime and return the identical image used for execution."""
    source, target = Path(source).resolve(strict=True), Path(target)
    contents = source.read_bytes()
    retained = _runtime_files.get(source)
    if retained is not None and (not retained.is_file() or retained.read_bytes() != contents):
        retained = None
    # Windows cannot remove a loaded DLL, including its other hard links.
    if target.is_file() and target.read_bytes() == contents:
        retained = retained or target
    elif retained is not None:
        copy_snapshot(retained, target)
    else:
        with staged_files([target]) as stage:
            temporary = stage / target.name
            shutil.copy2(source, temporary)
            if temporary.read_bytes() != contents or source.read_bytes() != contents:
                raise OSError('native library changed while its runtime was retained')
        retained = target
    _runtime_files[source] = retained
    register_runtime_snapshot(target)
    return retained
