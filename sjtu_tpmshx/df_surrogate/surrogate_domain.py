"""Production geometry-node and per-fluid Nu-window guard.

Provides `check_surrogate_domain_at_point` for callers that need to verify a
    single (u, T, P, L, t) point lies inside the CFD geometry grid and in
the selected fluid's Nu-fit Reynolds-number window.

This file used to live in `optimization.optimizer` but was hoisted out when the
patch-zoning optimizer was retired in favor of the continuous-field design.
"""
from __future__ import annotations
from typing import List

from sjtu_tpmshx.models.tpms_props import geometry as _geom

_SURROGATE_L_MM = (4.0, 5.0, 6.0, 7.0, 8.0)
_SURROGATE_T_MM = (0.3, 0.4, 0.5, 0.6)


def check_surrogate_domain_at_point(tpms_type: str,
                                    L_mm: float,
                                    t_mm: float,
                                    k_s: float,
                                    u: float,
                                    T: float,
                                    P: float = 101325.0,
                                    side: str = 'A',
                                    allow_extrap: bool = False,
                                    fluid: str = 'air', *,
                                    nu_reasons: list[str] | None = None) -> List[str]:
    """Point-form surrogate-domain check for the Compute path.

    Computes Re with the selected fluid and checks only that fluid's Nu fit
    window. Darcy--Forchheimer K/cF are interpolated only in L/t and therefore
    have no Re or fluid-dependent validation window.

    Parameters
    ----------
    tpms_type : str — 'Diamond' or 'Gyroid' (used for D_h via tpms_calc.geometry)
    L_mm, t_mm : unit cell + wall [mm]
    k_s : solid conductivity [W/(m K)] (only forwarded; not bound-checked)
    u, T, P : velocity [m/s], temperature [K], pressure [Pa]
    side : 'A' or 'B' — labels the failing side in error / warning text
    allow_extrap : bool — when True (or env TPMSHX_ALLOW_EXTRAP=1), out-of-window
        inputs warn instead of raising; this function returns the reason strings
        so callers can surface them on results / plots.
    nu_reasons : optional output list — receive Nu reasons separately, leaving
        only D-F geometry reasons in the return value. All checks and rejection
        rules still apply; omitted preserves the standalone combined result.

    Returns
    -------
    list[str] — empty if fully inside; populated with reason strings if any
    boundary is violated. When `allow_extrap=False` and reasons exist, raises
    ValueError instead of returning.

    Raises
    ------
    ValueError when out-of-window and `allow_extrap` is False.
    """
    import os as _os
    import warnings as _w

    if _os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes'):
        allow_extrap = True

    from sjtu_tpmshx.models.fluid_props import get as _get_fluid
    from sjtu_tpmshx.models.nu_correlations import (
        NU_RE_FIT_RANGE, SCO2_NU_RE_RANGE, WATER_NU_RE_RANGE,
    )
    model = _get_fluid(fluid)
    rho = float(model.rho(T, P))
    mu = float(model.mu(T, P))
    D_h = _geom(tpms_type, L_mm, t_mm, k_s)['D_h']
    Re = rho * u * D_h / mu

    nu_at_point: list[str] = []
    re_range = {'air': NU_RE_FIT_RANGE, 'water': WATER_NU_RE_RANGE,
                'sco2': SCO2_NU_RE_RANGE}[model.name]
    if not re_range[0] <= Re <= re_range[1]:
        nu_at_point.append(
            f"Fluid {side}: Re = {Re:.0f} outside {model.name} Nu window "
            f"[{re_range[0]:.0f}, {re_range[1]:.0f}] "
            f"(u={u} m/s, T={T} K, P={P:.0f} Pa, L={L_mm}mm, t={t_mm}mm)."
        )
    geometry_reasons: list[str] = []
    if not _SURROGATE_L_MM[0] <= float(L_mm) <= _SURROGATE_L_MM[-1]:
        geometry_reasons.append("V2 L_cell must be inside the 4..8 mm CFD grid.")
    if not _SURROGATE_T_MM[0] <= float(t_mm) <= _SURROGATE_T_MM[-1]:
        geometry_reasons.append("V2 wall thickness must be inside the 0.3..0.6 mm CFD grid.")

    reasons = nu_at_point + geometry_reasons
    if reasons:
        if allow_extrap:
            for r in reasons:
                _w.warn("[surrogate extrap] " + r, stacklevel=2)
        else:
            raise ValueError(" | ".join(reasons))
    if nu_reasons is not None:
        nu_reasons.extend(nu_at_point)
        return geometry_reasons
    return reasons
