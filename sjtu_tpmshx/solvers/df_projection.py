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
    weights — see `extract_dP_mass_flux_from_simple` for the ρ·|v| variant.
    """
    wA_in = s.inlet_frac; wA_out = s.outlet_frac
    mI = wA_in > 0.01; mO = wA_out > 0.5
    if not (mI.any() and mO.any()):
        return 0.0
    return float(np.average(s.P[mI, 0], weights=wA_in[mI])
               - np.average(s.P[mO, -1], weights=wA_out[mO]))


def extract_dP_mass_flux_from_simple(s: Any) -> float:
    """Mass-flux-weighted inlet/outlet dP.

    Weights each face cell by ρ·|v| so high-mass-flux streams dominate the
    reduction — closer to the physical inlet/outlet pressure the fluid
    actually "feels" when the profile is skewed. Falls back to
    `extract_dP_from_simple` when mass flux is zero (cold solution).

    SIMPLE 2D axis convention: P[i, j], streamwise = j, inlet face at
    j=0, outlet at j=Ny-1. v is staggered along j.
    """
    import numpy as _np
    v_in = s.v[:, 0] if s.v.shape[1] > 0 else _np.zeros(s.P.shape[0])
    v_out = s.v[:, -1] if s.v.shape[1] > 0 else _np.zeros(s.P.shape[0])
    rho_in = s.rho_field[:, 0]
    rho_out = s.rho_field[:, -1]
    wI = rho_in * _np.abs(v_in) * s.inlet_frac
    wO = rho_out * _np.abs(v_out) * s.outlet_frac
    mI = wI > 1e-9; mO = wO > 1e-9
    if not (mI.any() and mO.any()):
        return extract_dP_from_simple(s)
    return float(_np.average(s.P[mI, 0], weights=wI[mI])
               - _np.average(s.P[mO, -1], weights=wO[mO]))
