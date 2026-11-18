"""Error statistics for the Shanghai lumped comparison.

Input is already in the desired unit, typically ``(pred-exp)/exp*100``;
the function does not multiply by 100.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def err_stats_pct(err_pct) -> Tuple[float, float, float]:
    """Return ``(rmsre, mean_bias, max_abs)`` from a percent-error array.

    All three are in the same unit as the input. Used by
    ``validate_shanghai_lumped_dual_nu.py`` for its summary table.
    """
    arr = np.asarray(err_pct, dtype=np.float64)
    return (
        float(np.sqrt(np.mean(arr ** 2))),
        float(np.mean(arr)),
        float(np.max(np.abs(arr))),
    )


__all__ = ["err_stats_pct"]
