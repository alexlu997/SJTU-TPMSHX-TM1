"""Desktop shutdown/restart gate, including queued worker result delivery."""
from __future__ import annotations


def has_active_tasks(window) -> bool:
    compute = getattr(window, 'compute', None)
    return bool(
        (compute is not None and not compute.is_idle())
        or getattr(window, '_opt_worker', None) is not None
        or getattr(getattr(window, '_qd_dialog', None), '_qd_worker', None) is not None
    )
