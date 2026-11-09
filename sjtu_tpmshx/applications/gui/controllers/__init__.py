"""GUI compute lifecycle, result cache, session persistence and signal ownership.

The exported controllers use Qt and load lazily. Headless result mapping
belongs to applications.result_adapter.
"""
_LAZY = {
    'ComputeOrchestrator': '.compute_orchestrator',
    'ResultCache': '.result_cache',
    'SessionManager': '.session_manager',
    'SignalRouter': '.signal_router',
}


def __getattr__(name):
    if name in _LAZY:
        from importlib import import_module
        return getattr(import_module(_LAZY[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals()) + list(_LAZY))

__all__ = [
    'ComputeOrchestrator', 'ResultCache', 'SessionManager', 'SignalRouter',
]
