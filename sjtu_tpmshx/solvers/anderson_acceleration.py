"""Anderson mixing for thermal sweeps.

Callers validate candidates and restore rejected states. The inner SIMPLE
momentum iteration does not use Anderson acceleration.
"""
from __future__ import annotations
import numpy as np
from collections import deque
from typing import Tuple
from sjtu_tpmshx.domain.cancellation import CancelledError


def advance_energy(step, fields, sweeps, snapshots=(), cancel_check=None):
    """Accelerate an existing GS chunk, accepting only smaller GS residuals.

    Trial sweeps count against the original iteration budget. ``snapshots``
    are the 2D deferred-flux temperatures, restored with a rejected trial.
    The caller retains its original convergence and conservation checks.
    """
    accelerator = AndersonSIMPLE(m=5)
    size = fields[0].size

    def advance(count):
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        residual = step(count)
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        return residual

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
        residual = advance(count)
        done += count
        picard = pack()
        accelerator.push(previous, picard)
        candidate, applied = accelerator.candidate(picard)
        if not applied or done + 2 > sweeps:
            continue
        picard_residual = advance(1)
        picard = pack()
        saved = [field.copy() for field in snapshots]
        restore(candidate)
        candidate_residual = advance(1)
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
    """Type-II Anderson candidate generator for an externally validated map.

    Parameters
    ----------
    m : int
        History depth.
    beta : float
        Damping factor. 1.0 = full Anderson; <1.0 mixes with Picard. Default
        1.0; the caller retains its own acceptance and damping policy.
    cond_max : float
        Skip Anderson if cond(ΔR) exceeds this. Default 1e10.
    """

    def __init__(self, m: int = 5, beta: float = 1.0,
                 cond_max: float = 1e10):
        self.m = int(m)
        self.beta = float(beta)
        self.cond_max = float(cond_max)
        # ring buffers of past states x_k and residuals r_k = G(x_k) - x_k
        self._X: deque = deque(maxlen=self.m + 1)
        self._R: deque = deque(maxlen=self.m + 1)
        self.applied_count: int = 0
        self.skipped_count: int = 0

    def reset(self) -> None:
        self._X.clear()
        self._R.clear()
        self.applied_count = 0
        self.skipped_count = 0

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
