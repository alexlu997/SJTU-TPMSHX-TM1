"""tpms_props.py — leaf module: TPMS geometry + fluid property correlations.

Split out of ``tpms_calc.py`` (openspec arch-b-c-e, batch B, 2026-07-02) so
``df_surrogate`` can depend on geometry/props WITHOUT importing the full
``tpms_calc`` orchestrator (whose ``compute()`` in turn needs
``df_surrogate.predict`` — the old two-way coupling was held shut by deferred
imports on the solvers side). New direction, module-load level:

    tpms_geometry  ←  tpms_props  ←  df_surrogate  ←  tpms_calc / simple_solver

Current imports use ``sjtu_tpmshx.shared.models.tpms_props``. The calculator
re-exports selected primitives for its existing consumers. Dependencies remain
Qt-free; Re/Nu conventions are documented in ``models.tpms_calc``.
"""
from __future__ import annotations

import os
import warnings

import numpy as np

from .tpms_geometry import compute_geometry as _tpms_geom
from .tpms_geometry import compute_geometry_fields as _tpms_geom_fields
from . import _native_geometry
from sjtu_tpmshx.shared.configs.model_parameters import load_model_parameters
from sjtu_tpmshx.shared.domain.run_warnings import record_range

_MODEL_PARAMETERS = load_model_parameters()

# ── Physical constants ────────────────────────────────────────
R = _MODEL_PARAMETERS['constants']['gas_constant']
M_air = _MODEL_PARAMETERS['constants']['air_molar_mass']
P_atm = _MODEL_PARAMETERS['constants']['standard_pressure_pa']


# ── Air property correlations ─────────────────────────────────

# Validity ranges for the fitted correlations (per docstrings below).
_AIR_T_RANGE = tuple(_MODEL_PARAMETERS['air']['temperature_range_K'])
_AIR_CP_RANGE = tuple(_MODEL_PARAMETERS['air']['cp_temperature_range_K'])
_WATER_T_RANGE = tuple(_MODEL_PARAMETERS['water']['temperature_range_K'])
_AIR_CP_COEFFICIENTS = tuple(_MODEL_PARAMETERS['air']['cp_coefficients'])
_WATER_CP = _MODEL_PARAMETERS['water']['cp']
_CELSIUS_ZERO = _MODEL_PARAMETERS['constants']['celsius_zero_K']
_MODEL_H_REFERENCE = _MODEL_PARAMETERS['constants']['model_h_reference_K']
_AIR_SUTHERLAND = tuple(_MODEL_PARAMETERS['air']['sutherland'])
_AIR_CONDUCTIVITY = tuple(_MODEL_PARAMETERS['air']['conductivity'])
_WATER_DENSITY = tuple(_MODEL_PARAMETERS['water']['density'])
_WATER_VISCOSITY = tuple(_MODEL_PARAMETERS['water']['viscosity'])
_WATER_CONDUCTIVITY = tuple(_MODEL_PARAMETERS['water']['conductivity'])


def model_h_coefficients(fluid):
    """Existing cp polynomial, temperature origin and model-h reference (K)."""
    if fluid == 'air':
        return (*_AIR_CP_COEFFICIENTS, _CELSIUS_ZERO, _MODEL_H_REFERENCE)
    if fluid == 'water':
        return (_WATER_CP, 0.0, 0.0, _CELSIUS_ZERO, _MODEL_H_REFERENCE)
    raise ValueError('model h supports only air and water')

_range_warnings_emitted = set()


def record_temperature_ranges(fluid, T, *, source='property_state'):
    """Compare a temperature-model state with existing fits, without property calls.

    Callers select only the empirical temperature/model-h route, not HEOS Air.
    This is run-local evidence; standalone property warning behavior is unchanged.
    """
    if T is None:
        return
    if fluid == 'air':
        fits = (('air_viscosity', _AIR_T_RANGE),
                ('air_conductivity', _AIR_T_RANGE), ('air_cp', _AIR_CP_RANGE))
    elif fluid == 'water':
        fits = tuple((f'water_{name}', _WATER_T_RANGE)
                     for name in ('density', 'viscosity', 'conductivity', 'cp'))
    else:
        return
    for name, bounds in fits:
        record_range((source, name), T, bounds,
                     label=name, quantity='T', unit='K')


def _warn_range_once(name: str, T, lo: float, hi: float) -> None:
    """Emit a single UserWarning per (name) key when T goes outside the
    fitted validity range. Keeps logs readable when coupled solvers
    call these functions millions of times per run."""
    T_arr = np.asarray(T, dtype=float)
    if T_arr.size == 0:
        return
    if record_range(('property', name), T_arr, (lo, hi),
                    label=name, quantity='T', unit='K'):
        return
    T_min = float(T_arr.min())
    T_max = float(T_arr.max())
    if T_min < lo or T_max > hi:
        message = (
            f"{name}: T=[{T_min:.1f}, {T_max:.1f}] K outside fitted range "
            f"[{lo:.1f}, {hi:.1f}] K — extrapolating.")
        key = (name, round(T_min, 1), round(T_max, 1))
        if key in _range_warnings_emitted:
            return
        _range_warnings_emitted.add(key)
        warnings.warn(message, stacklevel=3)


def air_viscosity(T_K: float) -> float:
    """Dynamic viscosity of air via Sutherland's law [Pa·s]."""
    _warn_range_once('air_viscosity', T_K, *_AIR_T_RANGE)
    T0, mu0, S = _AIR_SUTHERLAND
    return mu0 * (T_K / T0) ** 1.5 * (T0 + S) / (T_K + S)


def air_conductivity(T_K: float) -> float:
    """Thermal conductivity of air [W/(m·K)]."""
    _warn_range_once('air_conductivity', T_K, *_AIR_T_RANGE)
    k0, T0, exponent = _AIR_CONDUCTIVITY
    return k0 * (T_K / T0) ** exponent


def air_density(T_K, P_Pa: float = 101325.0):
    """Density of air via ideal gas law [kg/m³]. Accepts scalar or ndarray T_K;
    return type matches input shape."""
    return P_Pa * M_air / (R * T_K)


def air_cp(T_K):
    """Specific heat capacity of air [J/(kg·K)] (250-1000 K, < 0.5% error).
    Accepts scalar or ndarray T_K; return type matches input shape."""
    _warn_range_once('air_cp', T_K, *_AIR_CP_RANGE)
    dT = T_K - _CELSIUS_ZERO
    a, b, c = _AIR_CP_COEFFICIENTS
    return a + b * dT + c * dT**2


# ── Water property correlations ───────────────────────────────

def water_density(T_K):
    """Density of liquid water [kg/m³]. Polynomial valid 0-90 °C."""
    _warn_range_once('water_density', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - _CELSIUS_ZERO
    a, b, c = _WATER_DENSITY
    return a - b * T_C - c * T_C**2


def water_viscosity(T_K):
    """Dynamic viscosity of liquid water [Pa·s].

    Vogel form (Andrade equation), NIST 0–90 °C max error < 2 %:
        mu = 2.414e-5 * 10^(247.8 / (T_K - 140))   [Pa·s, T_K in K]

    Replaced legacy `1.79e-3·exp(-0.035·T_C)` (2026-04-29) which decayed
    far too fast (-33 % at 40 °C, -53 % at 60 °C vs NIST). The legacy
    formula matched only 0–15 °C; Shanghai water bulk T 20-40 °C was
    systematically under-viscous → over-predicted Re_water ~50 % at hi T.
    """
    _warn_range_once('water_viscosity', T_K, *_WATER_T_RANGE)
    T_K_arr = np.asarray(T_K, dtype=float)
    # Floor the (T-140) denominator at 10 K so the 10**(247.8/denom) term stays
    # finite: at T~141 K the raw exponent ~247.8 overflows to +inf in float64
    # (robustness 2026-06-25). Physical liquid water (T>=273 K -> denom>=133)
    # is far above the floor, so this is bit-identical in range.
    mu0, base, exponent, shift, minimum = _WATER_VISCOSITY
    denom = np.maximum(T_K_arr - shift, minimum)
    return mu0 * base ** (exponent / denom)


def water_conductivity(T_K):
    """Thermal conductivity of liquid water [W/(m·K)]. Linear fit 0-90 °C."""
    _warn_range_once('water_conductivity', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - _CELSIUS_ZERO
    a, b = _WATER_CONDUCTIVITY
    return a + b * T_C


def water_cp(T_K):
    """Specific heat of liquid water [J/(kg·K)]. ~constant 280-370 K."""
    _warn_range_once('water_cp', T_K, *_WATER_T_RANGE)
    return _WATER_CP


# ── Geometry-only interface (no fluid needed) ─────────────────

# Solid-conduction tortuosity correction chi_s: K_ss = chi_s*(1-eps)*k_s.
# The naive `K_ss = (1 - eps) * k_s` assumes parallel solid paths aligned
# with the heat-flow direction; the real curved sheet network conducts less.
#
# B2 (2026-07-06): chi_s is now FITTED from unit-cell periodic numerical
# homogenization (runs/tools/homogenize_chi_s.py — steady conduction on the
# production N=128 voxel geometry, the same |phi|<=C(t/L) mask as eps/A_0;
# per-point 3-axis isotropy 0.00% by cubic symmetry, full-solid/laminate
# analytic checks exact; data validation/chi_s_homogenization.csv).
# Linear fit over the production window t/L 0.03-0.20 (eps 0.27-0.91),
# max residual ~0.012:
#     chi_s = c0 + c1*(1-eps)
# Thin-wall caveat: at t/L <~ 0.05 the wall spans only ~4 voxels and the
# fit inherits a small low bias; N-refinement at the Shanghai point
# (Gyroid, eps 0.737) extrapolates chi 0.655(N=128) -> ~0.667 (thin-sheet
# theoretical limit 2/3), i.e. the baked values sit ~2% below continuum.
#
# Env var TPMSHX_CHI_S (a constant) still overrides everything — legacy
# escape hatch; the historical default was the uncalibrated 1.0.
def _resolve_chi_s(chi_s=None):
    """Resolve an explicit value before the current environment setting."""
    if chi_s is not None:
        return float(chi_s)
    value = os.environ.get('TPMSHX_CHI_S')
    return None if value is None else float(value)


def chi_s_eff(tpms_type: str, eps):
    """Return native tortuosity with the current per-call override."""
    result = _native_geometry.chi_fields(tpms_type, eps, chi_s=_resolve_chi_s())
    return float(result) if result.ndim == 0 else result


def geometry(tpms_type: str, L_cell_mm: float, t_mm: float, k_s: float,
             chi_s: float | None = None, N: int = 128) -> dict:
    """Return native geometry and the current solid conductivity in W/(m K)."""
    result = _tpms_geom(tpms_type, L_cell_mm, t_mm, N)
    material = _native_geometry.material_fields(
        tpms_type, result['epsilon'], k_s, chi_s=_resolve_chi_s(chi_s))
    value = material['K_ss'][()]
    result['K_ss'] = value if isinstance(k_s, np.generic) else float(value)
    return result


def geometry_fields(tpms_type: str, L_field_mm, t_field_mm, k_s: float,
                    chi_s: float | None = None, N: int = 128) -> dict:
    """Return geometry fields and native material fields with per-call overrides."""
    fields = _tpms_geom_fields(tpms_type, L_field_mm, t_field_mm, N)
    material = _native_geometry.material_fields(
        tpms_type, fields['epsilon'], k_s, chi_s=_resolve_chi_s(chi_s))
    fields['K_ss'] = material['K_ss']
    return fields
