"""Shared log-log observed-order fits for native manufactured-solution tests.

Historical refactor B1 1.2 replaced four local implementations with different
return signatures:

  * mms_phase_a3_h_refine.fit_order        -> (p, c, R2)   np.polyfit
  * mms_phase_a4_boundary._fit_order       -> (p, R2)      np.polyfit
                                              (+ a redundant second polyfit
                                              call for the intercept)
  * mms_phase_b4_order._fit                -> (slope, R2)  np.linalg.lstsq
  * phase_c_gci._fit_order_loglog          -> p            np.polyfit,
                                              err floor 1e-6

Those functions fitted ``log(err) = p*log(h) + c``. The shared fit uses
``np.polyfit`` (the b4 lstsq variant solves the same least-squares
problem; any difference is last-ulp). R^2 is computed in log space with
the historical ``+1e-30`` denominator epsilon preserved verbatim.
Current ``phase_c_gci`` uses a Richardson triplet instead of this fit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OrderFitResult:
    p: float        # observed order (slope)
    c: float        # intercept
    r2: float       # R^2 in log space
    n_used: int     # points surviving the (err > err_floor) & finite mask


def fit_order_loglog(h_arr, err_arr, *, err_floor: float = 0.0,
                     min_points: int = 2) -> OrderFitResult:
    """Fit ``log(err) = p*log(h) + c`` over masked finite positive errors.

    err_floor : strict lower bound on err for a point to participate
                (0.0 keeps the historical ``err > 0`` mask).
    Returns all-NaN result when fewer than ``min_points`` survive.
    """
    h = np.asarray(h_arr, dtype=np.float64)
    e = np.asarray(err_arr, dtype=np.float64)
    mask = (e > err_floor) & np.isfinite(e)
    n_used = int(mask.sum())
    if n_used < min_points:
        return OrderFitResult(float('nan'), float('nan'), float('nan'), n_used)
    lh = np.log(h[mask])
    le = np.log(e[mask])
    p, c = np.polyfit(lh, le, 1)
    le_pred = p * lh + c
    ss_res = np.sum((le - le_pred) ** 2)
    ss_tot = np.sum((le - le.mean()) ** 2)
    r2 = 1.0 - ss_res / (ss_tot + 1e-30)
    return OrderFitResult(float(p), float(c), float(r2), n_used)
