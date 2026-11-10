"""Independent empirical expressions frozen before batch four at fad54db1.

These functions keep the original Python/NumPy operations and fixed data.
They do not call production property functions or native libraries.
"""
import warnings
from dataclasses import dataclass
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


def _warn_range_once(name, temperature, lo, hi):
    from sjtu_tpmshx.shared.domain.run_warnings import record_range

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
        warnings.warn(
            f'{name}: T=[{minimum:.1f}, {maximum:.1f}] K outside fitted range '
            f'[{lo:.1f}, {hi:.1f}] K — extrapolating.', stacklevel=3)


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
