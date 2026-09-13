"""coupling_skeleton.py — shared outer SIMPLE↔LTNE coupling-loop support.

The 2D and 3D drivers under `solvers/backends/python/` run an outer Picard
loop that couples the momentum solve (SIMPLE) to the energy solve (LTNE)
by feeding temperature-dependent properties (ρ, μ, cp, K) back into
SIMPLE until the temperature field stops moving. This module owns the two
pieces of that loop both drivers share:

  * :class:`OuterConvergence` — the warm-start ``prev = field.copy()``
    tracking + the ``max|field − prev|`` delta and AND-gate break decision
    (2D: dual ΔT_A/ΔT_B + mass-flux-weighted Δρ; 3D: single ΔT).
  * :func:`run_outer_coupling` — the loop skeleton itself: iterate, run a
    ``step``, break on convergence, otherwise run the between-iteration
    ``post`` update.

The loop *bodies* (the ``step``/``post`` callables each driver passes in)
stay dimension-specific — they differ in solve order (2D SIMPLE→LTNE;
3D LTNE→SIMPLE), in the physics one side carries (χ_B closure, conservative
staggered-face LTNE, frozen-B, per-outer P_ref recompute), in their
progress budgets and RunControl callbacks, and numerical duty diagnostics
(2D Richardson vs 3D enthalpy). Formal reporting consumes the captured result.
The driver owns only the control flow; the ``step``/``post`` closures keep
each body's arithmetic and copy timing verbatim, so behaviour stays
bit-identical to the prior inline loops — verified end-to-end by the 3D
golden hash and the 2D golden gate. ``OuterConvergence`` is the predicate
seam those closures call; ``run_outer_coupling`` supplies their shared loop.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import numpy as np


class OuterConvergence:
    """Warm-start delta tracker + break predicate for the outer coupling loop.

    Owns the per-iteration ``prev = field.copy()`` bookkeeping and the
    ``max|field − prev|`` temperature deltas that both the 2D and 3D loops
    computed inline. The break decision is an AND-gate over (a) every
    tracked temperature field's delta below ``tol_T`` and (b) any
    dim-specific extra criteria the caller passes in (e.g. the 2D
    mass-flux-weighted Δρ), each below its own tolerance.

    Parameters
    ----------
    tol_T : float
        Temperature-delta tolerance [K]. 2D uses 1.0, 3D uses 0.5.
    track : iterable of str
        Names of the temperature fields to track across iterations.
        2D tracks ('Ta', 'Tb'); 3D tracks ('Ta',).

    Notes
    -----
    First call (no ``prev`` yet) reports ``inf`` deltas and never
    converges, matching the legacy ``dT = inf`` first-iteration guard.
    ``check`` copies the current fields into ``prev`` on EVERY call; the
    legacy 2D path skipped the copy on the converged iteration (it broke
    first), but ``prev`` is unused after the loop exits, so the observable
    result is identical.
    """

    def __init__(self, *, tol_T: float, track: Iterable[str] = ('Ta',)) -> None:
        self.tol_T = float(tol_T)
        self.track: Tuple[str, ...] = tuple(track)
        self._prev: Dict[str, Optional[np.ndarray]] = {k: None for k in self.track}

    def check(self, fields: Dict[str, np.ndarray], *,
              extra: Optional[Iterable[float]] = None,
              extra_tol: Optional[float] = None) -> Tuple[bool, Dict[str, float]]:
        """Update warm-start state and decide whether the loop has converged.

        Parameters
        ----------
        fields : dict
            Maps each tracked name to its current array (this iteration's
            temperature field, real-coords, same shape as last call).
        extra : iterable of float, optional
            Dim-specific secondary convergence quantities (e.g. 2D's
            ``(drho_A, drho_B)``). Each must be below ``extra_tol``.
        extra_tol : float, optional
            Tolerance for every ``extra`` value. Required if ``extra`` given.

        Returns
        -------
        (converged, deltas) : (bool, dict)
            ``deltas`` maps each tracked name to ``max|field − prev|``
            (``inf`` on the first call), for the caller's status print.
        """
        first = any(self._prev[k] is None for k in self.track)
        deltas: Dict[str, float] = {}
        for k in self.track:
            prev = self._prev[k]
            if prev is None:
                deltas[k] = float('inf')
            else:
                deltas[k] = float(np.max(np.abs(fields[k] - prev)))

        T_ok = all(deltas[k] < self.tol_T for k in self.track)
        extra_ok = True
        if extra is not None:
            if extra_tol is None:
                raise ValueError("extra_tol required when extra is given")
            extra_ok = all(float(v) < extra_tol for v in extra)
        converged = (not first) and T_ok and extra_ok

        # Warm-start for the next iteration (copy so later in-place writes
        # to `fields` do not alias prev).
        for k in self.track:
            self._prev[k] = fields[k].copy()
        return converged, deltas


def run_outer_coupling(
    *,
    max_iter: int,
    step: Callable[[int], Tuple[bool, Any]],
    post: Optional[Callable[[int, Any], None]] = None,
) -> Tuple[int, bool]:
    """Drive the outer SIMPLE↔LTNE Picard loop shared by the 2D and 3D stacks.

    Both drivers run the identical control flow — solve the coupled phases,
    test convergence, and (only if not yet converged) update the carried
    state for the next iteration::

        for it in range(max_iter):
            converged, carry = step(it)
            if converged:
                break
            post(it, carry)

    The ``step``/``post`` bodies are dimension-specific (2D SIMPLE→LTNE with
    a dual ΔT + Δρ gate; 3D LTNE→SIMPLE with a single ΔT gate) and live in
    their own modules — this owns only the loop skeleton and the
    converged / last-iteration bookkeeping each caller needs afterwards.

    Note the legacy ``for`` loops ran ``post`` on EVERY non-converged
    iteration, including the final one when the cap is hit without
    converging; this driver preserves that (``post`` runs whenever ``step``
    did not converge), so the post-loop solver state is identical.

    Parameters
    ----------
    max_iter : int
        Outer-iteration cap (2D ``_MAX_COUPLING``, 3D ``_max_outer``).
    step : callable(it) -> (converged: bool, carry)
        Runs one iteration's solves and the convergence check. Returns the
        break decision and an opaque ``carry`` handed straight to ``post``
        (2D passes its under-relaxation inputs through it; 3D passes
        ``None``). May raise (e.g. ``InterruptedError`` for a cooperative
        cancel) — the exception propagates unchanged, matching the inline
        ``raise`` inside the legacy loop body.
    post : callable(it, carry) -> None, optional
        Applied between iterations, only when ``step`` did NOT converge —
        the next-iteration property update (2D under-relax / 3D SIMPLE
        re-solve). Omitted ⇒ no between-iteration work.

    Returns
    -------
    (last_iter, converged) : (int, bool)
        ``last_iter`` is the 0-based index of the final iteration executed
        (for the caller's not-converged warning); ``converged`` is whether
        ``step`` ever reported convergence.
    """
    last_iter = 0
    for it in range(max_iter):
        last_iter = it
        converged, carry = step(it)
        if converged:
            return it, True
        if post is not None:
            post(it, carry)
    return last_iter, False
