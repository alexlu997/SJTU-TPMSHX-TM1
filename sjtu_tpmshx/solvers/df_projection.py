"""Historical cell-row pressure reductions used by validation comparisons.

Current public pressure metrics use physical port-face evidence in postprocess.
Geometry projection and grids are owned by models.df_projection and models.grid.
"""
from __future__ import annotations
from typing import Any

import numpy as np
def extract_dP_from_simple(s: Any) -> float:
    """Extract inlet/outlet-averaged dP from a converged SIMPLE instance.

    Uses the inlet_frac/outlet_frac weighting (same convention as the Shanghai
    2D validation, now validate_shanghai_aligned.py) to handle partial
    inlet/outlet openings correctly. Geometric open-area
    weights; current formal metrics instead extrapolate to physical port faces.
    """
    wA_in = s.inlet_frac; wA_out = s.outlet_frac
    mI = wA_in > 0.01; mO = wA_out > 0.5
    if not (mI.any() and mO.any()):
        return 0.0
    return float(np.average(s.P[mI, 0], weights=wA_in[mI])
               - np.average(s.P[mO, -1], weights=wA_out[mO]))
