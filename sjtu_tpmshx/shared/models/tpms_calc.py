"""
tpms_calc.py — TPMS Property Calculator

Given TPMS geometry (type, L_cell, t) and flow conditions (u, T_in, P_in),
computes geometry and closure parameters for prepared solver inputs:
  epsilon, A_0, D_h, Re, Nu, dP/L, H_sf, K_ff, K_ss, rho, mu, k_f

Includes:
  - Geometry and material queries through the native geometry library
  - One native query for properties, Nu and fixed CFD Darcy-Forchheimer drag
  - Public caches, scalar types and warning records in the Python host

Supported TPMS types: 'Diamond', 'Gyroid'
Fluids: air, water, sCO2 and CO2 with their existing property and Nu models

──────────────────────────────────────────────────────────────────────
REYNOLDS NUMBER CONVENTION (project-wide, confirmed 2026-04-22)
──────────────────────────────────────────────────────────────────────

All Re computations use hydraulic diameter D_h:

    Re = ρ · u · D_h / μ    (single-channel interstitial u)

Training Excel (试验记录表_整理版.xlsx) mass flow back-calculation:
    m_total = Re × μ / D_h × A_cross × 2   (×2 = two TPMS channels)

The ×2 is for converting single-channel to total mass flow, NOT for
the Re definition. Nu correlations fitted on D_h Re.

Nu OUTPUT convention: Nu = h · D_h / k_f   (standard D_h definition).

Nu correlations take D_h-convention Re as input
but output D_h-convention Nu. All solver callers use the correct
convention on both sides, so downstream Q calculations are consistent.
──────────────────────────────────────────────────────────────────────
"""

from . import preparation_cache
import sys
import warnings
import numpy as np  # noqa: F401 - preserve existing module surface
from sjtu_tpmshx.shared.domain.run_warnings import (
    cache_warning_records, current_warnings, merge_warnings,
)
from .tpms_geometry import compute_geometry as _tpms_geom
from . import _native_preparation_case

# Geometry and property primitives live in tpms_props. Current consumers may
# also import the explicitly re-exported names from models.tpms_calc.
from .tpms_props import (  # noqa: F401 — re-exports
    chi_s_eff, M_air, P_atm, R,
    air_conductivity, air_cp, air_density, air_viscosity,
    geometry,
    water_conductivity, water_cp, water_density, water_viscosity,
    _warn_range_once,
)
from sjtu_tpmshx.shared.df_surrogate.predict import predict_K_cF, SCO2_DF_METHOD  # noqa: F401 - public re-exports

from sjtu_tpmshx.shared.logutil import get_logger

_log = get_logger(__name__)

# ── Fluid type validation ─────────────────────────────────────

# Each fluid keeps its own property and Nu model. Production pressure loss uses
# one geometry-only fixed CFD table shared by both sides and all fluid types.
_SUPPORTED_FLUIDS = {'air', 'water', 'sco2', 'co2'}




def validate_fluid_type(fluid_type: str, side: str) -> None:
    """Reject fluid names outside the supported air, water, sCO2 and CO2 set."""
    if fluid_type not in _SUPPORTED_FLUIDS:
        label = {'water': 'Water', 'sco2': 'sCO₂'}.get(fluid_type, fluid_type)
        raise NotImplementedError(
            f"Fluid {side} = {label} is not supported yet — no fitted "
            f"correlations (Nu / f-Re / D-F surrogate) for this fluid. "
            f"Supported fluids: air, water, sco2, co2."
        )


# ── Nu correlations ───────────────────────────────────────────
# Single source of truth lives in `models.nu_correlations` (2026-05-28
# audit Item 1 / H1). Detailed roughness rationale + known limitations
# moved to that module's docstring.

from .nu_correlations import (  # noqa: F401 - existing public re-exports
    Pr_AIR as Pr,
    nu_from_Re,
    nu_vec,
    nu_water_topo,
    nu_sco2_topo,
    NU_RE_FIT_RANGE,
    WATER_NU_RE_RANGE,
    NU_COEFFS,
    SCO2_NU_COEFFS,
    SCO2_NU_RE_RANGE,
)

# Per-fluid Re fit windows for the compute()-level out-of-range warning. The
# Nu correlations have DIFFERENT validated Re ranges per fluid; warning every
# fluid against the air window (400,16000) mis-flagged in-range water/sCO2 and
# silently passed out-of-range sCO2 below 9000 (audit 2026-06-28 N5).
_RE_FIT_RANGE_BY_FLUID = {
    'air': NU_RE_FIT_RANGE,
    'water': WATER_NU_RE_RANGE,
    'sco2': SCO2_NU_RE_RANGE,
    'co2': (3000., 60000.),
}


# ── Geometry-only interface ────────────────────────────────────
# Geometry and solid conductivity live in tpms_props (re-exported above).

# No uncalibrated thermal dispersion is added to the molecular conductivity.


def adaptive_grid(L_domain: float, H_domain: float,
                  D_h: float, alpha: float = 0.4) -> tuple:
    """Compute grid dimensions for a target dx/D_h ratio.

    Parameters
    ----------
    L_domain, H_domain : float — domain size [m]
    D_h    : float — hydraulic diameter [m]
    alpha  : float — target dx/D_h (0.8 coarse, 0.4 display, 0.2 fine)

    Returns
    -------
    Nx, Ny : int
    """
    from ._native_grid import adaptive
    return adaptive(L_domain, H_domain, D_h, alpha)


# ── Main interface ────────────────────────────────────────────

def _reynolds_notice(tpms_type, Re, fluid_type):
    """Return the existing uncached standalone inlet Re notice."""
    lo, hi = _RE_FIT_RANGE_BY_FLUID.get(fluid_type, NU_RE_FIT_RANGE)
    if not (lo <= Re <= hi):
        return (f"{tpms_type}: Re = {Re:.1f} is outside the validated range "
                f"[{lo:.0f}, {hi:.0f}]. Correlation accuracy may be reduced.")
    return None


class _InletCacheValue(tuple):
    """Keep native-only intermediate values outside the public property mapping."""
    def __new__(cls, values, records, cp, pr):
        result = super().__new__(cls, (values, records))
        result.cp, result.pr = cp, pr
        return result


@preparation_cache.scalar_cache(maxsize=4096)
def _compute_cached(tpms_type: str,
                    L_cell_mm: float,
                    t_mm: float,
                    u: float,
                    T_in_K: float,
                    P_in_Pa: float,
                    fluid_type: str = 'air',
                    sco2_nu=None, co2_geometry=False) -> tuple[dict, dict]:
    """
    Cache TPMS geometry and fluid properties.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_cell_mm : TPMS unit cell size [mm]  (geometry/D-F table: 4–8 mm)
    t_mm      : wall thickness [mm]       (geometry/D-F table: 0.3–0.6 mm)
        Nu fits and experimental corrections have independent applicability
        ranges; the table domain does not extend those ranges.
    u         : selected fluid's interstitial velocity [m/s]
    T_in_K    : inlet temperature [K]
    P_in_Pa   : inlet pressure [Pa]

    Returns
    -------
    tuple[dict, dict]
        Numerical values and source warning records. Public ``compute``
        returns only a copy of the numerical dict; records stay internal.

    Numerical dict keys:
        epsilon   – porosity [-]
        A_0       – single-side specific surface area [m⁻¹] (area seen by one
                    fluid stream per unit total volume — NOT double-sided;
                    see tpms_geometry.py for derivation). h_vA = A_0 × H_sf_A
                    and h_vB = A_0 × H_sf_B therefore do NOT double-count.
        D_h       – hydraulic diameter [m]
        Re        – Reynolds number (based on D_h, interstitial velocity) [-]
        Nu        – Nusselt number [-]
        K_df      – permeability [m²] (fixed CFD D-F closure)
        cF_df     – Forchheimer coefficient [1/m] (fixed CFD D-F closure)
        dP_per_L  – pressure drop per unit length [Pa/m]
        H_sf      – face heat transfer coefficient [W/(m²·K)]
        K_ff      – single-stream effective conductivity epsilon_A*k_f [W/(m·K)]
        rho       – selected fluid density [kg/m³]
        mu        – selected fluid dynamic viscosity [Pa·s]
        k_f       – selected fluid thermal conductivity [W/(m·K)]
    """
    with cache_warning_records({}) as records:
        # ── Geometry from numerical computation ─────────────────────
        if co2_geometry or fluid_type == 'co2':
            from .co2_correlations import geometry as geometry_model
            g = geometry_model(tpms_type, L_cell_mm, t_mm)
        else:
            g = _tpms_geom(tpms_type, L_cell_mm, t_mm)
        eps   = g['epsilon']
        A0    = g['A_0']
        D_h_m = g['D_h']
        eps_A = g['epsilon_A']
        caller = sys._getframe(1)
        if caller.f_code is _compute_cached.__code__:
            caller = caller.f_back

        def notice(kind, side, value, message):
            if kind != 0:
                raise RuntimeError(f'unknown property query notice kind {kind}')
            message = _reynolds_notice(tpms_type, value, fluid_type) if current_warnings() is None else None
            if message is not None:
                warnings.warn_explicit(message, UserWarning, caller.f_code.co_filename, caller.f_lineno,
                    module=caller.f_globals['__name__'],
                    registry=caller.f_globals.setdefault('__warningregistry__', {}))

        rho, mu, k_f, cp_f, Pr_f, Re, Nu, K_df, cF_df, dP_per_L, H_sf, K_ff = (
            _native_preparation_case.inlet_query(tpms_type, L_cell_mm, t_mm, u, T_in_K,
                P_in_Pa, fluid_type, sco2_nu, g, records, notice))

        return _InletCacheValue({
            'epsilon':   eps,
            'epsilon_A': eps_A,
            'epsilon_B': eps_A,     # symmetric sheet HX: ε_B = ε_A = ε/2
            'A_0':       A0,
            'D_h':       D_h_m,
            'Re':        Re,
            'Nu':        Nu,
            'K_df':      K_df,      # permeability [m²] (fixed CFD)
            'cF_df':     cF_df,     # Forchheimer coeff [1/m] (fixed CFD)
            'dP_per_L':  dP_per_L,
            'H_sf':      H_sf,
            'K_ff':      K_ff,
            'rho':       rho,
            'mu':        mu,
            'k_f':       k_f,
        }, records, cp_f, Pr_f)


# ── Public cached property calculation ────────────────────────
def compute(tpms_type: str,
            L_cell_mm: float,
            t_mm: float,
            u: float,
            T_in_K: float,
            P_in_Pa: float,
            k_s: float,
            fluid_type: str = 'air', *, sco2_nu=None, co2_geometry=False) -> dict:
    """Return cached properties plus solid conductivity ``K_ss`` [W/(m·K)].

    See ``_compute_cached`` for the other fields. ``K_ss`` uses the current
    CHI_S setting and ``k_s`` on every call, including cache hits.

    Production uses the fixed water+sCO2 CFD closure; environment state does
    not select a different backend. Experimental correction, when requested,
    is applied by the caller after assembling these CFD properties.

    Return a fresh shallow copy with scalar values on every call.
    """
    from .fluid_props import check_water_state
    check_water_state(fluid_type, T_in_K, P_in_Pa, where='compute inlet')
    # Production V2 closure is fluid-independent and fixed for a TPMS/L/t
    # geometry.
    result, records = _compute_cached(tpms_type, L_cell_mm, t_mm, u, T_in_K,
                                     P_in_Pa, fluid_type, sco2_nu, co2_geometry)
    result = dict(result)
    from . import _native_geometry
    from .tpms_props import _resolve_chi_s
    eps = result['epsilon']
    material = _native_geometry.material_fields(tpms_type, eps, k_s, chi_s=_resolve_chi_s())
    value = material['K_ss'][()]
    result['K_ss'] = value if isinstance(eps, np.generic) or isinstance(k_s, np.generic) else float(value)
    merge_warnings(current_warnings(), [records], bind_context=True)
    return result


# Tests and property sweeps explicitly inspect or clear this process-local cache.
compute.cache_clear = _compute_cached.cache_clear
compute.cache_info = _compute_cached.cache_info
compute.cache_parameters = _compute_cached.cache_parameters
