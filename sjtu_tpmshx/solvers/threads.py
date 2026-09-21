"""Runtime control of the Numba thread pool used by the parallel energy kernels
(`@njit(parallel=True)` red-black GS) and any other parallel `@njit` code.

Three control layers, all funnelling through `set_solver_threads`:

  * ``NUMBA_NUM_THREADS`` (native Numba env) — the HARD CAP, fixed before Numba
    initialises. Set it in the shell/launcher to bound the pool (e.g. leave
    cores free). The active count can never exceed it.
  * ``TPMSHX_NUM_THREADS`` (project env) — the runtime active count for
    headless / script / batch runs (validation, optimizer) where there is no
    GUI. Read once at import via `init_from_env`. Unset → Numba default
    (all cores, up to the cap).
  * `set_solver_threads(n)` — the runtime knob the GUI "CPU cores" spinbox calls.

The active mask is local to the calling thread. It governs `parallel=True`
kernels launched from that thread, not only the energy solve. Reused worker
threads must apply the launch setting themselves and restore their prior mask;
the GUI's ComputeOrchestrator handles this for ordinary calculations.
"""
import os

import numba


def max_threads() -> int:
    """Hard upper bound = Numba's compiled pool size (all logical cores, or the
    `NUMBA_NUM_THREADS` env if it was set before Numba initialised)."""
    return int(numba.config.NUMBA_NUM_THREADS)


def get_solver_threads() -> int:
    """The calling thread's active count for the next Numba parallel kernel."""
    return int(numba.get_num_threads())


def set_solver_threads(n: int) -> int:
    """Set this thread's active Numba count, clamped to ``[1, max_threads()]``.

    Returns the value actually applied (after clamping)."""
    n = max(1, min(int(n), max_threads()))
    numba.set_num_threads(n)
    return n


def init_from_env() -> int:
    """Apply ``TPMSHX_NUM_THREADS`` if set (the headless/script knob). No-op on
    unset/invalid → leaves the Numba default. Returns the active count."""
    raw = os.environ.get("TPMSHX_NUM_THREADS", "").strip()
    if raw:
        try:
            return set_solver_threads(int(raw))
        except ValueError:
            pass
    return get_solver_threads()


# ── Large-grid thread-count advisory (P3.2, 2026-07-20) ─────────────────────
# The red-black GS kernels are memory-bandwidth bound: past ~one socket's
# physical cores, extra (SMT) threads only add contention. On the 128-logical
# EPYC dev server the unpinned all-cores default measurably thrashed
# (scripts/run_tests_server.ps1 header: 7 CPU-hours wasted), while 64 was the
# sweet spot. The advisory NEVER changes the pool — production defaults stay
# untouched (a pool change reorders prange reductions → bit-level drift with
# no golden coverage at production grid sizes).

def recommend_solver_threads() -> int:
    """Recommended active count for bandwidth-bound kernels.

    Heuristic: half the logical cores (SMT-off physical-core estimate),
    capped at 64 (measured single-socket sweet spot) and at the pool max.
    """
    logical = os.cpu_count() or 1
    return max(1, min(64, logical // 2 or 1, max_threads()))


_advised_default_pool = False


def warn_if_default_pool(n_cells: int) -> int:
    """One-shot advisory when a large grid engages ``prange`` on the unpinned
    all-cores default. Returns the recommendation; NEVER changes the pool.

    Silent when ``TPMSHX_NUM_THREADS`` is set (user pinned it), when the
    active count was lowered from the cap (GUI spinbox / set_solver_threads),
    or when the machine is small enough that the default ≈ recommendation.
    """
    global _advised_default_pool
    rec = recommend_solver_threads()
    if _advised_default_pool:
        return rec
    if os.environ.get("TPMSHX_NUM_THREADS", "").strip():
        return rec
    active, cap = get_solver_threads(), max_threads()
    if active >= cap and cap > rec:
        _advised_default_pool = True
        from sjtu_tpmshx.logutil import get_logger
        get_logger(__name__).warning(
            "large grid (%d cells) engages parallel kernels on the numba "
            "all-cores default (%d threads). Red-black GS is memory-bandwidth "
            "bound — past one socket extra threads add contention; "
            "recommended: TPMSHX_NUM_THREADS=%d (or the GUI CPU-cores "
            "spinbox). Advisory only — pool unchanged.",
            n_cells, active, rec)
    return rec
