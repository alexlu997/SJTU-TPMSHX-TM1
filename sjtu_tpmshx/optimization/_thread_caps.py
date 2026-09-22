"""Worker thread environment defaults, with no numerical-library imports.

The process-pool initializer sets these before the submitted seed job runs.
Spawn may import NumPy while restoring the parent's main module, before the
initializer. Updating the environment does not resize already loaded library
pools; callers needing import-time caps must set them before process launch.
"""
import os

_CAP_KEYS = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'NUMBA_NUM_THREADS')


def set_worker_thread_caps() -> None:
    """Set worker thread environment variables (default 1).

    Override inherited values; use TPMSHX_WORKER_THREADS for another value.
    Libraries loaded before this call may already have initialized their pools.
    """
    n = os.environ.get('TPMSHX_WORKER_THREADS', '1')
    try:
        n = str(max(1, int(n)))
    except ValueError:
        n = '1'
    for k in _CAP_KEYS:
        os.environ[k] = n
