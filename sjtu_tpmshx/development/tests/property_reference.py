"""Independent empirical expressions frozen before batch four at fad54db1.

The empirical functions keep independent Python/NumPy expressions and data.
The final section freezes the 7abad5ba scalar combination. It shares unchanged
geometry/material and water-state boundaries, but no production query arithmetic.
Warning contexts and original public source locations are host contracts.
"""
import warnings
from dataclasses import dataclass
from contextvars import ContextVar
from types import SimpleNamespace

import numpy as np


R = 8.314
M_air = 0.028966
P_atm = 101325.0
_AIR_T_RANGE = (200.0, 1100.0)
_AIR_CP_RANGE = (250.0, 1000.0)
_WATER_T_RANGE = (273.15, 363.15)
_AIR_CP_COEFFICIENTS = (1004.5, 0.172, -7.56e-05)
_WATER_CP = 4182.0
_CELSIUS_ZERO = 273.15
_AIR_SUTHERLAND = (273.15, 1.716e-05, 110.4)
_AIR_CONDUCTIVITY = (0.0241, 273.15, 0.82)
_WATER_DENSITY = (999.84, 0.05, 0.004)
_WATER_VISCOSITY = (2.414e-05, 10.0, 247.8, 140.0, 10.0)
_WATER_CONDUCTIVITY = (0.569, 0.0018)
_range_warnings_emitted = set()
_query_warning_origin = ContextVar("query_reference_warning_origin", default=None)


def _warn_range_once(name, temperature, lo, hi):
    from sjtu_tpmshx.development.tests.result_warning_reference import record_range

    values = np.asarray(temperature, dtype=float)
    if values.size == 0:
        return
    if record_range(('property', name), values, (lo, hi),
                    label=name, quantity='T', unit='K'):
        return
    minimum, maximum = float(values.min()), float(values.max())
    if minimum < lo or maximum > hi:
        key = (name, round(minimum, 1), round(maximum, 1))
        if key in _range_warnings_emitted:
            return
        _range_warnings_emitted.add(key)
        message = (f'{name}: T=[{minimum:.1f}, {maximum:.1f}] K outside fitted range '
                   f'[{lo:.1f}, {hi:.1f}] K — extrapolating.')
        origin = _query_warning_origin.get()
        if origin is None:
            warnings.warn(message, stacklevel=3)
        else:
            _query_warning(message, origin)


def air_viscosity(T_K):
    _warn_range_once('air_viscosity', T_K, *_AIR_T_RANGE)
    T0, mu0, S = _AIR_SUTHERLAND
    return mu0 * (T_K / T0) ** 1.5 * (T0 + S) / (T_K + S)


def air_conductivity(T_K):
    _warn_range_once('air_conductivity', T_K, *_AIR_T_RANGE)
    k0, T0, exponent = _AIR_CONDUCTIVITY
    return k0 * (T_K / T0) ** exponent


def air_density(T_K, P_Pa=101325.0):
    return P_Pa * M_air / (R * T_K)


def air_cp(T_K):
    _warn_range_once('air_cp', T_K, *_AIR_CP_RANGE)
    dT = T_K - _CELSIUS_ZERO
    a, b, c = _AIR_CP_COEFFICIENTS
    return a + b * dT + c * dT**2


def water_density(T_K):
    _warn_range_once('water_density', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - _CELSIUS_ZERO
    a, b, c = _WATER_DENSITY
    return a - b * T_C - c * T_C**2


def water_viscosity(T_K):
    _warn_range_once('water_viscosity', T_K, *_WATER_T_RANGE)
    T_K_arr = np.asarray(T_K, dtype=float)
    mu0, base, exponent, shift, minimum = _WATER_VISCOSITY
    denom = np.maximum(T_K_arr - shift, minimum)
    return mu0 * base ** (exponent / denom)


def water_conductivity(T_K):
    _warn_range_once('water_conductivity', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - _CELSIUS_ZERO
    a, b = _WATER_CONDUCTIVITY
    return a + b * T_C


def water_cp(T_K):
    _warn_range_once('water_cp', T_K, *_WATER_T_RANGE)
    return _WATER_CP


@dataclass
class Props:
    rho: float
    mu: float
    k: float
    cp: float
    Pr: float


def fluid_model(fluid, *, sco2_nu=None):
    from . import eos_reference as eos
    from . import nu_reference as nu

    def describe(model):
        model.name = fluid
        model.nu_floor_multiplier = 1.28 if fluid == 'co2' else 1.
        def evaluate(topology, reynolds, epsilon, cell, diameter, pr):
            if fluid == 'air':
                return nu.nu_from_Re(topology, reynolds, epsilon, cell, diameter)
            if fluid == 'water':
                return nu.nu_water_topo(topology, reynolds, pr)
            if fluid == 'co2':
                return nu.co2_nusselt(topology, reynolds, pr, cell, diameter)
            if sco2_nu is None:
                return nu.nu_sco2_topo(topology, reynolds, pr, cell, diameter)
            return nu.nu_sco2_selected(topology, reynolds, pr, cell, diameter, settings=sco2_nu)
        model.nu = evaluate
        return model

    if fluid == 'air':
        return describe(SimpleNamespace(rho=air_density, mu=lambda T, P=None: air_viscosity(T),
                        k=lambda T, P=None: air_conductivity(T), cp=lambda T, P=None: air_cp(T)))
    if fluid == 'water':
        return describe(SimpleNamespace(rho=lambda T, P=None: water_density(T), mu=lambda T, P=None: water_viscosity(T),
                        k=lambda T, P=None: water_conductivity(T), cp=lambda T, P=None: water_cp(T)))
    query = eos.co2_prop if fluid == 'co2' else eos.sco2_prop
    if fluid not in ('co2', 'sco2'):
        raise ValueError(f'unknown reference fluid {fluid!r}')
    return describe(SimpleNamespace(rho=lambda T, P=None: query('D', T, P), mu=lambda T, P=None: query('V', T, P),
                    k=lambda T, P=None: query('L', T, P), cp=lambda T, P=None: query('C', T, P)))


def fluid_props(fluid, temperature, pressure):
    from .eos_reference import check_water_state

    model = fluid_model(fluid)
    check_water_state(fluid, temperature, pressure, where='quick-design properties')
    rho, mu = model.rho(temperature, pressure), model.mu(temperature, pressure)
    conductivity, cp = model.k(temperature, pressure), model.cp(temperature, pressure)
    return Props(rho, mu, conductivity, cp, mu * cp / conductivity)


def fluid_nu(fluid, topology, re, epsilon, cell, diameter):
    from . import nu_reference as nu

    if fluid == 'air':
        return nu.nu_from_Re(topology, re, epsilon, cell, diameter)
    if fluid == 'water':
        return nu.nu_water_topo(topology, re, fluid_props('water', 320., 200000.).Pr)
    if fluid == 'sco2':
        return nu.nu_sco2_topo(topology, re, fluid_props('sco2', 480., 9000000.).Pr, cell, diameter)
    raise ValueError(f'unknown fluid {fluid!r}')


# Complete scalar query frozen from 7abad5ba before the N13 combination move.
# Geometry and host warning contexts are shared. Property/Nu/DF arithmetic and
# cache storage are independent of the production scalar query.
from functools import lru_cache
import sys

from sjtu_tpmshx.shared.domain.run_warnings import (
    cache_warning_records, current_warnings, merge_warnings,
)
from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry as _tpms_geom
from .df_reference import predict_K_cF, pressure_gradient

_QUERY_RE_RANGES = {'air': (400., 16000.), 'water': (90., 51000.),
                    'sco2': (2600., 128000.), 'co2': (3000., 60000.)}
_QUERY_CO2_PR_RANGE = [1.0137227801530173, 3.760086553568298]
_query_nu_warned = set()


class _InletCacheValue(tuple):
    """Retain the old internal cp/pr payload without publishing new keys."""
    def __new__(cls, values, records, cp, pr):
        result = super().__new__(cls, (values, records))
        result.cp, result.pr = cp, pr
        return result


def _query_warning(message, origin, marker=None):
    """Use the original public source location without its calculation."""
    import dis

    instructions = list(dis.get_instructions(origin))
    start = next(index for index, item in enumerate(instructions)
                 if item.argval == marker) if marker else 0
    line = next(item.positions.lineno for item in instructions[start:]
                if item.opname == 'CALL')
    module = sys.modules[origin.__module__]
    warnings.warn_explicit(message, UserWarning, origin.__code__.co_filename, line,
        module=module.__name__, registry=module.__dict__.setdefault('__warningregistry__', {}))


def _query_property(function, origin, temperature, pressure):
    token = _query_warning_origin.set(origin)
    try:
        return float(function(temperature, pressure))
    finally:
        _query_warning_origin.reset(token)


def _query_nu_notice(fluid, topology, value, origin, *, quantity='Re'):
    from .result_warning_reference import record_range

    bounds = _QUERY_CO2_PR_RANGE if quantity == 'Pr' else _QUERY_RE_RANGES[fluid]
    prefix = {'air': 'Nu', 'water': 'water Nu', 'sco2': 'sCO2 Nu', 'co2': 'CO2 Nu'}[fluid]
    source = 'nu_pr' if quantity == 'Pr' else 'nu'
    if record_range((source, fluid, topology), value, bounds,
                    label=f'[{prefix} extrap] {topology}', quantity=quantity, unit='-'):
        return
    notice_value = np.maximum(value, 1.) if fluid in ('water', 'sco2') else value
    minimum, maximum = float(np.min(notice_value)), float(np.max(notice_value))
    low, high = bounds
    if fluid == 'co2':
        if minimum < low or maximum > high:
            _query_warning(f'CO2 {quantity} outside CFD calibration {bounds}; '
                           'extrapolation, not validation.', origin)
        return
    for side, outside in (('lo', minimum < low), ('hi', maximum > high)):
        key = (fluid, topology if fluid == 'air' else None, side)
        if not outside or key in _query_nu_warned:
            continue
        _query_nu_warned.add(key)
        if fluid == 'air':
            message = (f'[Nu extrap] {topology}: Re=[{minimum:.0f},{maximum:.0f}] '
                       f'outside fit window [{low:.0f},{high:.0f}]. '
                       'Suppressing further warnings for this (tpms, side).')
        else:
            name = 'water' if fluid == 'water' else 'sCO2'
            message = (f'[{name} Nu extrap] Re=[{minimum:.0f},{maximum:.0f}] outside '
                       f'{name}-CFD fit window [{low:.0f},{high:.0f}].')
        _query_warning(message, origin, '_sco2_nu' if origin.__name__ == 'nu_sco2_selected' else None)


def _query_model(fluid, settings):
    try:
        normalized = fluid.strip().lower()
        if normalized not in _QUERY_RE_RANGES:
            raise KeyError(normalized)
    except (KeyError, AttributeError):
        raise ValueError(f"unknown fluid {fluid!r}; known: ['air', 'co2', 'sco2', 'water']")
    if normalized == 'sco2' and settings is not None:
        settings.validate()
    selected = settings if normalized == 'sco2' and settings is not None and settings.mode == 'experimental' else None
    return normalized, fluid_model(normalized, sco2_nu=selected)


@lru_cache(maxsize=4096)
def _compute_cached(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa,
                    fluid_type='air', sco2_nu=None, co2_geometry=False):
    """Run the frozen scalar sequence with independent primitive expressions."""
    with cache_warning_records({}) as records:
        if co2_geometry or fluid_type == 'co2':
            from sjtu_tpmshx.shared.models.co2_correlations import geometry
            g = geometry(tpms_type, L_cell_mm, t_mm)
        else:
            g = _tpms_geom(tpms_type, L_cell_mm, t_mm)
        eps, area, diameter = g['epsilon'], g['A_0'], g['D_h']
        diameter_mm = diameter * 1000.0
        normalized, model = _query_model(fluid_type, sco2_nu)
        from sjtu_tpmshx.shared.models import fluid_props, nu_correlations, tpms_calc
        origins = fluid_props.FLUIDS[normalized]
        mu = _query_property(model.mu, origins.mu, T_in_K, P_in_Pa)
        conductivity = _query_property(model.k, origins.k, T_in_K, P_in_Pa)
        rho = _query_property(model.rho, origins.rho, T_in_K, P_in_Pa)
        cp = _query_property(model.cp, origins.cp, T_in_K, P_in_Pa)
        reynolds = rho * u * diameter / mu
        low, high = _QUERY_RE_RANGES.get(fluid_type, _QUERY_RE_RANGES['air'])
        if current_warnings() is None and not (low <= reynolds <= high):
            _query_warning(
                f'{tpms_type}: Re = {reynolds:.1f} is outside the validated range '
                f'[{low:.0f}, {high:.0f}]. Correlation accuracy may be reduced.',
                tpms_calc.compute, '_compute_cached')
        epsilon_a = g['epsilon_A']
        prandtl = mu * cp / conductivity
        nu_origin = origins.nu
        if normalized == 'sco2':
            nu_origin = (nu_correlations.nu_sco2_selected if sco2_nu is not None
                         and sco2_nu.mode != 'cfd_smooth' else nu_correlations.nu_sco2_topo)
        # Native Nu input preparation has the same scalar conversions and guards.
        if normalized == 'co2':
            re, pr, cell, dh = np.broadcast_arrays(*(np.asarray(value, dtype=float)
                for value in (reynolds, prandtl, L_cell_mm, diameter_mm)))
            if not all(value.size and np.isfinite(value).all() and (value > 0).all()
                       for value in (re, pr, cell, dh)):
                raise ValueError('CO2 closure inputs must be finite and positive')
            _query_nu_notice(normalized, tpms_type, re, nu_origin)
            _query_nu_notice(normalized, tpms_type, pr, nu_origin, quantity='Pr')
        else:
            raw_re = np.asarray(reynolds, dtype=np.float64) if normalized == 'air' else reynolds
            _query_nu_notice(normalized, tpms_type, raw_re, nu_origin)
        nu = model.nu(tpms_type, reynolds, epsilon_a, L_cell_mm, diameter_mm, prandtl)
        surface = nu * conductivity / diameter
        permeability, forchheimer = predict_K_cF(
            tpms_type, float(L_cell_mm), float(t_mm), float(epsilon_a))
        if fluid_type == 'co2':
            from .df_reference import apply_prepared_correction
            permeability, forchheimer, _ = apply_prepared_correction(
                permeability, forchheimer, {'scale_K': 1. / 2.5, 'scale_F': 2.5})
        gradient = pressure_gradient(rho, mu, u, permeability, forchheimer)
        pore_conductivity = epsilon_a * conductivity
        return _InletCacheValue({
            'epsilon': eps, 'epsilon_A': epsilon_a, 'epsilon_B': epsilon_a,
            'A_0': area, 'D_h': diameter, 'Re': reynolds, 'Nu': nu,
            'K_df': permeability, 'cF_df': forchheimer, 'dP_per_L': gradient,
            'H_sf': surface, 'K_ff': pore_conductivity,
            'rho': rho, 'mu': mu, 'k_f': conductivity,
        }, records, cp, prandtl)


def compute(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, k_s,
            fluid_type='air', *, sco2_nu=None, co2_geometry=False):
    """Retain validation, cache copies, material refresh, and warning replay."""
    from sjtu_tpmshx.shared.models.fluid_props import check_water_state
    from sjtu_tpmshx.shared.models import _native_geometry
    from sjtu_tpmshx.shared.models.tpms_props import _resolve_chi_s

    check_water_state(fluid_type, T_in_K, P_in_Pa, where='compute inlet')
    values, records = _compute_cached(tpms_type, L_cell_mm, t_mm, u, T_in_K,
                                     P_in_Pa, fluid_type, sco2_nu, co2_geometry)
    result = dict(values)
    epsilon = result['epsilon']
    material = _native_geometry.material_fields(tpms_type, epsilon, k_s, chi_s=_resolve_chi_s())
    value = material['K_ss'][()]
    result['K_ss'] = value if isinstance(epsilon, np.generic) or isinstance(k_s, np.generic) else float(value)
    merge_warnings(current_warnings(), [records], bind_context=True)
    return result


compute.cache_clear = _compute_cached.cache_clear
compute.cache_info = _compute_cached.cache_info
compute.cache_parameters = _compute_cached.cache_parameters
