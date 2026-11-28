"""
tpms_calc.py — TPMS Property Calculator

Given TPMS geometry (type, L_cell, t) and flow conditions (u, T_in, P_in),
computes geometry and closure parameters for prepared solver inputs:
  epsilon, A_0, D_h, Re, Nu, dP/L, H_sf, K_ff, K_ss, rho, mu, k_f

Includes:
  - Geometry and material queries through the native geometry library
  - One native query for properties, Nu and fixed CFD Darcy-Forchheimer drag
  - Detached scalar values and warning records for the Python caller

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

from functools import wraps
import sys
import warnings
import numpy as np  # noqa: F401 - preserve existing module surface
from tm1.run_control.run_warnings import (
    cache_warning_records, current_warnings, merge_warnings,
)
from .tpms_geometry import compute_geometry as _tpms_geom
from tm1.cpp_interface import inlet_properties
from tm1.cpp_interface._native_properties import cache_controls

# Geometry and property primitives live in tpms_props. Current consumers may
# also import the explicitly re-exported names from models.tpms_calc.
from .tpms_props import (  # noqa: F401 — re-exports
    chi_s_eff, M_air, P_atm, R,
    air_conductivity, air_cp, air_density, air_viscosity,
    geometry as geometry,
    water_conductivity, water_cp, water_density, water_viscosity,
    _warn_range_once,
)
from tm1.physical_models.df_surrogate.predict import predict_K_cF, SCO2_DF_METHOD  # noqa: F401 - public re-exports

from tm1.run_control.logutil import get_logger

_log = get_logger(__name__)

from .fluid_props import validate_fluid_type as validate_fluid_type


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


def nu_re_window(fluid: str):
    """Return the validated Reynolds number range for the fluid's Nu correlation."""
    if fluid == 'air':
        return NU_RE_FIT_RANGE
    if fluid == 'water':
        return WATER_NU_RE_RANGE
    if fluid == 'sco2':
        return SCO2_NU_RE_RANGE
    if fluid == 'co2':
        from .co2_correlations import RE_RANGE
        return RE_RANGE
    raise ValueError(f'unknown fluid {fluid!r}')


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
    from tm1.cpp_interface._native_grid import adaptive
    return adaptive(L_domain, H_domain, D_h, alpha)


# ── Main interface ────────────────────────────────────────────

def _reynolds_notice(tpms_type, Re, fluid_type):
    """Return the existing uncached standalone inlet Re notice."""
    from .fluid_props import get

    lo, hi = nu_re_window(get(fluid_type).name)
    if not (lo <= Re <= hi):
        return (f"{tpms_type}: Re = {Re:.1f} is outside the validated range "
                f"[{lo:.0f}, {hi:.0f}]. Correlation accuracy may be reduced.")
    return None


class _InletValues(tuple):
    """Keep cp and Pr with the detached source records."""
    def __new__(cls, values, records, cp, pr):
        result = super().__new__(cls, (values, records))
        result.cp, result.pr = cp, pr
        return result


def _calculate(tpms_type, cell, wall, u, temperature, pressure, fluid, selection, co2_geometry, *, cached, caller):
    from .fluid_props import get

    fluid_name = get(fluid).name
    co2 = co2_geometry or fluid_name == 'co2'
    if not co2 and tpms_type not in ('Diamond', 'Gyroid'):
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{tpms_type}'")

    def notice(kind, side, value, message):
        if kind != 0:
            raise RuntimeError(f'unknown property query notice kind {kind}')
        message = _reynolds_notice(tpms_type, value, fluid) if current_warnings() is None else None
        if message is not None:
            warnings.warn_explicit(message, UserWarning, caller.f_code.co_filename, caller.f_lineno,
                module=caller.f_globals['__name__'], registry=caller.f_globals.setdefault('__warningregistry__', {}))

    with cache_warning_records({}) as records:
        if cached:
            scalars, row = inlet_query(tpms_type, cell, wall, u, temperature, pressure, fluid_name,
                selection, None, records, notice, co2_geometry=co2_geometry, caller=caller)
            g = {key: np.float64(value) if co2 or key in ('A_0', 'D_h') else value
                 for key, value in zip(('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h'), scalars, strict=True)}
        else:
            if co2:
                from .co2_correlations import geometry as geometry_model
            else:
                geometry_model = _tpms_geom
            g = geometry_model(tpms_type, cell, wall)
            row = inlet_query(tpms_type, cell, wall, u, temperature, pressure, fluid_name,
                selection, g, records, notice, caller=caller)
        rho, mu, k_f, cp, pr, re, nu, permeability, drag, gradient, transfer, conductivity = row
        values = {key: g[key] for key in ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h')}
        values.update(Re=re, Nu=nu, K_df=permeability, cF_df=drag, dP_per_L=gradient,
                      H_sf=transfer, K_ff=conductivity, rho=rho, mu=mu, k_f=k_f)
        return _InletValues(values, records, cp, pr)


def _compute_uncached(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, fluid_type='air',
                      sco2_nu=None, co2_geometry=False):
    return _calculate(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, fluid_type,
                      sco2_nu, co2_geometry, cached=False, caller=sys._getframe(1))


@cache_controls(3)
@wraps(_compute_uncached)
def _compute_cached(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, fluid_type='air',
                    sco2_nu=None, co2_geometry=False):
    return _calculate(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, fluid_type,
                      sco2_nu, co2_geometry, cached=True, caller=sys._getframe(1))


# ── Public cached property calculation ────────────────────────
def compute(tpms_type: str,
            L_cell_mm: float,
            t_mm: float,
            u: float,
            T_in_K: float,
            P_in_Pa: float,
            k_s: float,
            fluid_type: str = 'air', *, sco2_nu=None, co2_geometry=False,
            df_mode='cfd_smooth') -> dict:
    """Return cached properties plus solid conductivity ``K_ss`` [W/(m·K)].

    See ``_compute_cached`` for the other fields. ``K_ss`` uses the current
    CHI_S setting and ``k_s`` on every call, including cache hits.

    The default uses the fixed CFD D-F table. In experimental mode, apply the
    selected campaign correction to K_df, cF_df and dP_per_L on the copy.
    Single-phase CO₂ always uses its fixed factors.

    Return a fresh shallow copy with scalar values on every call.
    """
    from .df_surrogate.experimental_correction import DF_MODES, EXPERIMENTAL
    from .fluid_props import check_water_state

    if df_mode not in DF_MODES:
        raise ValueError(f'Unsupported D-F mode {df_mode!r}')
    check_water_state(fluid_type, T_in_K, P_in_Pa, where='compute inlet')
    # Production V2 closure is fluid-independent and fixed for a TPMS/L/t
    # geometry.
    result, records = _compute_cached(tpms_type, L_cell_mm, t_mm, u, T_in_K,
                                     P_in_Pa, fluid_type, sco2_nu, co2_geometry)
    result = dict(result)
    fluid = fluid_type.strip().lower()
    if df_mode == EXPERIMENTAL and fluid != 'co2':
        from tm1.cpp_interface._native_df import pressure_gradient
        from .df_surrogate.experimental_correction import apply_correction
        K, cF, _ = apply_correction(tpms_type, fluid, L_cell_mm, t_mm, result['K_df'], result['cF_df'], u)
        result.update(K_df=K, cF_df=cF, dP_per_L=pressure_gradient(result['rho'], result['mu'], u, K, cF))
    from tm1.cpp_interface import _native_geometry
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


def inlet_query(topology, cell, wall, velocity, temperature, pressure, fluid,
                selection, geometry, records, notice, *, co2_geometry=False, caller=None):
    """Select the fluid, pressure, and corrections for an inlet with supplied geometry."""
    from . import fluid_props
    from .preparation_notices import range_notices

    fluid_name = fluid_props.get(fluid).name

    def validate_model():
        fluid_props.get(fluid, sco2_nu=selection)
        if fluid_name in ('sco2', 'co2') and pressure is None:
            if fluid_name == 'co2':
                raise ValueError('CO2 requires absolute pressure P in Pa')
            raise ValueError('sCO2 properties require pressure P [Pa]; caller passed P=None. '
                             'Fix the call site to forward the inlet/local pressure.')

    if geometry is not None:
        validate_model()

    def observe(key, record, cached, scalar):
        for message in range_notices(key, record, cached, scalar, records=records):
            warnings.warn(message, UserWarning)

    if caller is None:
        caller = sys._getframe(1)

    def floating_warning(message):
        warnings.warn_explicit(message, RuntimeWarning, caller.f_code.co_filename, caller.f_lineno,
            module=caller.f_globals['__name__'], registry=caller.f_globals.setdefault('__warningregistry__', {}))

    def observe_event(kind, logger, message, code, replay):
        if kind == 2:
            replay([code], warn=floating_warning)
        elif kind == 0:
            get_logger(logger.removeprefix('tpmshx.')).info(message)
        elif kind == 1:
            warnings.warn(message, UserWarning)
        else:
            raise RuntimeError(f'unknown preparation event kind {kind}')

    def property_error(status, text, cause):
        if status in (10, 11, 12):
            raise ValueError(text) from (ValueError(cause) if cause is not None else None)

    missing_pressure = pressure is None and fluid_name in ('co2', 'sco2')
    query_pressure = 0. if missing_pressure or (geometry is not None and fluid_name == 'water') else pressure
    nu_settings = selection if geometry is None or fluid_name == 'sco2' else None
    from .tpms_props import _resolve_chi_s
    return inlet_properties.query_values(topology, cell, wall, velocity, temperature, query_pressure, fluid_name,
        nu_settings, geometry, observe, notice, observe_event, property_error, fluid_props.WaterStateError,
        exact_co2_drag=fluid_name == 'co2', co2_geometry=co2_geometry, records=records,
        validate_geometry=_resolve_chi_s, validate_model=validate_model)
