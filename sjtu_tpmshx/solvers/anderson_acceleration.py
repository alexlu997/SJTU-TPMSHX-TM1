"""Anderson acceleration for SIMPLE outer Picard iteration.

Treats the SIMPLE step as a fixed-point map G: x → x' where
``x = stack(u, v, w, P)``. Anderson Type-II uses a window of m past residuals
to extrapolate a better next state via a least-squares mixing of recent steps.

Mass conservation note
----------------------
Anderson on raw (u,v,w,P) does NOT inherently preserve ∇·(ρu)=0. The caller
MUST run one extra pressure correction (`_solve_pp_amg` + `_correct_jit_3d`)
after every Anderson step so the projected velocity is divergence-free again.
The Anderson step is therefore a candidate; the projection makes it admissible.

Safety gates
------------
- Apply only every K outer iterations (default 3) — pure Picard between to
  let SIMPLE re-establish self-consistency.
- Skip if ΔR is rank-deficient (cond > 1e10).
- Roll back to Picard if the Anderson candidate increases the residual norm.
"""
from __future__ import annotations
import numpy as np
from collections import deque
from typing import Tuple


def advance_energy(step, fields, sweeps, snapshots=()):
    """Accelerate an existing GS chunk, accepting only smaller GS residuals.

    Trial sweeps count against the original iteration budget. ``snapshots``
    are the 2D deferred-flux temperatures, restored with a rejected trial.
    The caller retains its original convergence and conservation checks.
    """
    accelerator = AndersonSIMPLE(m=5, K=1)
    size = fields[0].size

    def pack():
        return np.concatenate([field.ravel() for field in fields])

    def restore(values):
        for index, field in enumerate(fields):
            field[:] = values[index * size:(index + 1) * size].reshape(field.shape)

    done = 0
    residual = 0.0
    while done < sweeps:
        previous = pack()
        count = min(25, sweeps - done)
        residual = step(count)
        done += count
        picard = pack()
        accelerator.push(previous, picard)
        candidate, applied = accelerator.candidate(picard)
        if not applied or done + 2 > sweeps:
            continue
        picard_residual = step(1)
        picard = pack()
        saved = [field.copy() for field in snapshots]
        restore(candidate)
        candidate_residual = step(1)
        done += 2
        if np.isfinite(candidate_residual) and candidate_residual <= picard_residual:
            residual = candidate_residual
        else:
            restore(picard)
            for field, value in zip(snapshots, saved):
                field[:] = value
            residual = picard_residual
    return residual


class AndersonSIMPLE:
    """Type-II Anderson acceleration for SIMPLE outer loop.

    Parameters
    ----------
    m : int
        History depth. m=5 is a robust default for SIMPLE.
    K : int
        Apply Anderson every K outer iterations; pure Picard between.
    beta : float
        Damping factor. 1.0 = full Anderson; <1.0 mixes with Picard. Default
        1.0 — SIMPLE under-relaxation already provides damping.
    cond_max : float
        Skip Anderson if cond(ΔR) exceeds this. Default 1e10.
    """

    def __init__(self, m: int = 5, K: int = 3, beta: float = 1.0,
                 cond_max: float = 1e10):
        self.m = int(m)
        self.K = int(K)
        self.beta = float(beta)
        self.cond_max = float(cond_max)
        # ring buffers of past states x_k and residuals r_k = G(x_k) - x_k
        self._X: deque = deque(maxlen=self.m + 1)
        self._R: deque = deque(maxlen=self.m + 1)
        self.applied_count: int = 0
        self.skipped_count: int = 0
        self.rolled_back_count: int = 0

    def reset(self) -> None:
        self._X.clear()
        self._R.clear()
        self.applied_count = 0
        self.skipped_count = 0
        self.rolled_back_count = 0

    def push(self, x: np.ndarray, gx: np.ndarray) -> None:
        """Record an iterate ``x`` and its image ``gx = G(x)``."""
        self._X.append(np.ascontiguousarray(x, dtype=np.float64))
        self._R.append(np.ascontiguousarray(gx - x, dtype=np.float64))

    def candidate(self, gx_picard: np.ndarray) -> Tuple[np.ndarray, bool]:
        """Return Anderson-accelerated candidate or pass-through Picard.

        Parameters
        ----------
        gx_picard : np.ndarray
            The pure Picard step output G(x_k) at the current iteration.

        Returns
        -------
        x_new : np.ndarray
            Either the Anderson-mixed candidate or ``gx_picard`` unchanged.
        applied : bool
            True if Anderson mixing was applied.
        """
        if len(self._X) < 2:
            return gx_picard, False

        X = np.stack(list(self._X), axis=1)        # (n, k+1)
        R = np.stack(list(self._R), axis=1)        # (n, k+1)
        dX = np.diff(X, axis=1)                    # (n, k)
        dR = np.diff(R, axis=1)                    # (n, k)

        # cond check via ratio of singular values; cheap for m≤5
        try:
            s = np.linalg.svd(dR, compute_uv=False)
            if s.size == 0 or s[0] == 0.0 or (s[0] / max(s[-1], 1e-30)) > self.cond_max:
                self.skipped_count += 1
                return gx_picard, False
        except np.linalg.LinAlgError:
            self.skipped_count += 1
            return gx_picard, False

        r_curr = R[:, -1]
        try:
            gamma, *_ = np.linalg.lstsq(dR, r_curr, rcond=None)
        except np.linalg.LinAlgError:
            self.skipped_count += 1
            return gx_picard, False

        # x_anderson = G(x_k) - (dX + dR) @ gamma  (Type-II)
        x_anderson = gx_picard - (dX + dR) @ gamma
        if self.beta < 1.0:
            x_anderson = self.beta * x_anderson + (1.0 - self.beta) * gx_picard

        if not np.all(np.isfinite(x_anderson)):
            self.skipped_count += 1
            return gx_picard, False

        self.applied_count += 1
        return x_anderson, True

    def maybe_rollback(self, x_anderson: np.ndarray, gx_picard: np.ndarray,
                        res_anderson: float, res_picard: float) -> np.ndarray:
        """Roll back to Picard if Anderson candidate increased residual."""
        if not np.isfinite(res_anderson) or res_anderson > res_picard:
            self.rolled_back_count += 1
            return gx_picard
        return x_anderson


class AndersonOuterCoupling:
    """Anderson acceleration for the SIMPLE↔LTNE **outer** coupling map.

    Fixed-point variable
    --------------------
    The property state handed to SIMPLE on one side of the HX,
    ``x = (rho_field, mu_field)``. Its image ``G(x)`` is the same pair
    recomputed from the LTNE temperature field that ``x`` produced::

        x_k --SIMPLE--> u,P --LTNE--> T --rho(T,P), mu(T)--> G(x_k)

    Production updates this with damped Picard,
    ``x_{k+1} = a*G(x_k) + (1-a)*x_k`` (``a = _ALPHA_T = 0.6``, a fixed
    constant). This class replaces the fixed ``a`` with a least-squares mix
    over the last ``m`` ``(x, G(x))`` pairs — i.e. a quasi-Newton step on the
    coupling map instead of a hand-tuned relaxation.

    Why acceleration is SAFE on this map (and needs care on the inner one)
    ---------------------------------------------------------------------
    :class:`AndersonSIMPLE`'s docstring warns that mixing raw ``(u,v,w,P)``
    breaks ``div(rho*u)=0`` and the caller must re-project. On the OUTER map
    that requirement is satisfied **for free**: the extrapolated quantity is a
    *property field* (rho, mu), and the very next thing the loop does is
    re-solve SIMPLE from it — which re-establishes the discrete mass balance by
    construction. Anderson can move rho; it cannot make the velocity field
    non-solenoidal, because that field is recomputed, not extrapolated.

    Safety gates (a bad extrapolation must cost at most one Picard iteration)
    ------------------------------------------------------------------------
    * **Admissibility** — the candidate is rejected outright unless every entry
      is finite and strictly positive (rho and mu are positive by physics), and
      unless it stays inside a trust region ``||cand - x|| <= trust*||G(x) - x||``.
      A rejected candidate falls back to the production damped-Picard blend.
    * **Windowed reset, not per-iteration** — the history is dropped only when
      the true fixed-point residual fails to improve on its running minimum for
      ``patience`` consecutive iterations.

      This is deliberate. The un-accelerated outer loop is *oscillatory*: the
      residual reliably GROWS on the second iteration (measured 2026-07-12:
      x1.36 on all three of a mild / baseline / hot+fast air case) before
      collapsing. A naive "residual went up => diverging" reset would therefore
      fire on essentially every healthy run.
    * **Per-block scaling** — rho ~ 1e0 and mu ~ 1e-5 live in one vector, so
      each block is normalised by its own reference magnitude before the
      least-squares solve; otherwise the mu residual is invisible to it.

    Off by default in the pipeline (``cfg['outer_anderson']``); when disabled
    the production blend runs untouched and the golden gates stay bit-identical.
    """

    def __init__(self, m: int = 3, trust: float = 5.0, patience: int = 3,
                 cond_max: float = 1e10):
        self._and = AndersonSIMPLE(m=m, K=1, beta=1.0, cond_max=cond_max)
        self.trust = float(trust)
        self.patience = int(patience)
        self._scales: np.ndarray | None = None
        self._shapes: list[tuple[int, ...]] = []
        self._sizes: list[int] = []
        self._res_min: float = float('inf')
        self._stale: int = 0
        # stats
        self.applied_count = 0
        self.rejected_count = 0
        self.reset_count = 0
        self.residuals: list[float] = []

    # ── flat <-> blocks, with per-block normalisation ────────────────────────
    def _init_scales(self, blocks: list[np.ndarray]) -> None:
        self._shapes = [np.shape(b) for b in blocks]
        self._sizes = [int(np.size(b)) for b in blocks]
        sc = []
        for b in blocks:
            s = float(np.mean(np.abs(np.asarray(b, dtype=np.float64))))
            sc.append(s if (np.isfinite(s) and s > 0.0) else 1.0)
        self._scales = np.asarray(sc, dtype=np.float64)

    def _flat(self, blocks: list[np.ndarray]) -> np.ndarray:
        return np.concatenate([
            np.asarray(b, dtype=np.float64).ravel() / self._scales[i]
            for i, b in enumerate(blocks)])

    def _unflat(self, x: np.ndarray) -> list[np.ndarray]:
        out, o = [], 0
        for i, n in enumerate(self._sizes):
            out.append(np.ascontiguousarray(
                (x[o:o + n] * self._scales[i]).reshape(self._shapes[i]),
                dtype=np.float64))
            o += n
        return out

    # ── the step ────────────────────────────────────────────────────────────
    def step(self, x_blocks: list[np.ndarray], g_blocks: list[np.ndarray],
             alpha: float) -> tuple[list[np.ndarray], bool]:
        """One accelerated outer update.

        Parameters
        ----------
        x_blocks : current iterate (the property fields SIMPLE just used)
        g_blocks : G(x) (the property fields recomputed from the new T)
        alpha    : the production damped-Picard factor, used as the fallback
                   and as the baseline the trust region is measured against.

        Returns
        -------
        (new_blocks, applied) — ``applied`` is False when the candidate was
        rejected or there was not enough history, in which case ``new_blocks``
        is *exactly* the production blend ``alpha*G + (1-alpha)*x``.
        """
        if self._scales is None:
            self._init_scales(x_blocks)

        x = self._flat(x_blocks)
        g = self._flat(g_blocks)
        picard = alpha * g + (1.0 - alpha) * x     # production fallback

        r = g - x
        res = float(np.linalg.norm(r))
        self.residuals.append(res)

        # Windowed staleness check (see class docstring — a per-iteration
        # "residual grew" test would fire on every healthy run).
        if res < self._res_min - 1e-14:
            self._res_min = res
            self._stale = 0
        else:
            self._stale += 1
            if self._stale >= self.patience:
                self._and.reset()
                self._res_min = res
                self._stale = 0
                self.reset_count += 1
                return self._unflat(picard), False

        self._and.push(x, g)
        cand, applied = self._and.candidate(g)
        if not applied:
            return self._unflat(picard), False

        # ── admissibility ───────────────────────────────────────────────────
        # Trust region: the step must not be wildly longer than the Picard one.
        if not np.all(np.isfinite(cand)):
            self.rejected_count += 1
            return self._unflat(picard), False
        if np.linalg.norm(cand - x) > self.trust * max(res, 1e-30):
            self.rejected_count += 1
            return self._unflat(picard), False
        # Physical positivity: rho and mu are strictly positive. Checked on the
        # UNSCALED blocks (the scales are positive, so the sign survives, but be
        # explicit — a future block with a signed quantity must not slip past).
        cand_blocks = self._unflat(cand)
        for b in cand_blocks:
            if not np.all(np.isfinite(b)) or float(np.min(b)) <= 0.0:
                self.rejected_count += 1
                return self._unflat(picard), False

        self.applied_count += 1
        return cand_blocks, True

    def stats(self) -> dict:
        return dict(applied=self.applied_count, rejected=self.rejected_count,
                    resets=self.reset_count,
                    residuals=[float(v) for v in self.residuals])
