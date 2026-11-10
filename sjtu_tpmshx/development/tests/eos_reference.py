"""Direct locked-CoolProp contracts frozen before batch four at fad54db1.

This reference does not call production properties or native preparation.
It verifies the adapter contract, not the physical accuracy of CoolProp.
"""
from functools import lru_cache

import CoolProp.CoolProp as CP
import numpy as np


T_RANGE_K = (280.0, 700.0)
P_RANGE_PA = (7900000.0, 16000000.0)
CO2_KEYS = ('D', 'V', 'L', 'C', 'H')


class WaterStateError(ValueError):
    pass


def check_water_state(fluid, T, P, *, where='water state'):
    if fluid.strip().lower() != 'water':
        return
    try:
        temperatures, pressures = np.broadcast_arrays(
            np.asarray(T, dtype=float), np.asarray(P, dtype=float))
    except (TypeError, ValueError) as error:
        raise WaterStateError(f'{where}: water requires paired T/P states') from error
    if not temperatures.size:
        raise WaterStateError(f'{where}: water requires finite positive K and Pa(abs)')
    if not (np.isfinite(temperatures).all() and np.isfinite(pressures).all()
            and (temperatures > 0).all() and (pressures > 0).all()):
        index = tuple(map(int, np.unravel_index(np.flatnonzero(
            ~np.isfinite(temperatures) | ~np.isfinite(pressures)
            | (temperatures <= 0) | (pressures <= 0))[0], temperatures.shape)))
        raise WaterStateError(
            f'{where}: water index={index}, T={temperatures[index]:g} K, '
            f'P_abs={pressures[index]:g} Pa: requires finite positive K and Pa(abs)')
    state = CP.AbstractState('HEOS', 'Water')
    for flat_index, (temperature, pressure) in enumerate(zip(temperatures.flat, pressures.flat)):
        try:
            state.update(CP.PT_INPUTS, float(pressure), float(temperature))
            phase = state.phase()
            if phase == CP.iphase_supercritical_liquid:
                raise WaterStateError('high-pressure liquid: T-only model applicability unconfirmed')
            if phase != CP.iphase_liquid:
                raise WaterStateError('only stable single-phase liquid water is supported')
            if not state.has_melting_line():
                raise WaterStateError('solid/liquid stability unconfirmed')
            melting = state.melting_line(CP.iT, CP.iP, float(pressure))
            if not np.isfinite(melting) or temperature <= melting:
                raise WaterStateError('freezing boundary or solid/metastable water unsupported')
        except (ValueError, RuntimeError) as error:
            index = tuple(map(int, np.unravel_index(flat_index, temperatures.shape)))
            raise WaterStateError(
                f'{where}: water index={index}, T={temperature:g} K, '
                f'P_abs={pressure:g} Pa: {error}') from error


def _co2_states(T, P):
    if P is None:
        raise ValueError('CO2 requires absolute pressure P in Pa')
    temperature, pressure = np.broadcast_arrays(np.asarray(T, dtype=float), np.asarray(P, dtype=float))
    if not temperature.size or not (np.isfinite(temperature).all() and np.isfinite(pressure).all()
                                    and (temperature > 0).all() and (pressure > 0).all()):
        raise ValueError('CO2 requires finite positive temperature [K] and pressure [Pa(abs)]')
    if (temperature <= float(CP.PropsSI('Ttriple', 'CO2'))).any():
        raise ValueError('CO2 at/below its triple-point temperature is outside this fluid model')
    return temperature, pressure


def _co2_evaluate(keys, temperature, pressure):
    shape = temperature.shape
    try:
        result = np.asarray(CP.PropsSI(list(keys) + ['Phase'], 'T', temperature.ravel(),
                                      'P', pressure.ravel(), 'HEOS::CO2'), dtype=float)
        result = result.reshape(-1, len(keys) + 1)
        phases = result[:, -1]
        allowed = [CP.iphase_liquid, CP.iphase_gas, CP.iphase_supercritical,
                   CP.iphase_supercritical_gas, CP.iphase_supercritical_liquid]
        valid = np.isfinite(result).all(axis=1) & np.isin(phases, allowed)
        for column, key in enumerate(keys):
            if key in ('D', 'V', 'L', 'C'):
                valid &= result[:, column] > 0
        if not valid.all():
            index = int(np.flatnonzero(~valid)[0])
            raise ValueError(
                f'unsupported/nonfinite state at T={temperature.flat[index]:g} K, '
                f'P_abs={pressure.flat[index]:g} Pa; phase code={phases[index]:g}')
        return tuple(result[:, column].reshape(shape) for column in range(len(keys)))
    except (ValueError, RuntimeError) as error:
        raise ValueError(
            'CO2 requires a stable single-phase PT state; '
            'saturation, two-phase and critical-point states are unsupported. '
            f'{error}') from error


@lru_cache(maxsize=4096)
def _co2_scalar(T, P):
    return tuple(float(value) for value in _co2_evaluate(CO2_KEYS, np.asarray(T), np.asarray(P)))


def co2_prop(keys, T, P):
    one = isinstance(keys, str)
    requested = (keys,) if one else tuple(keys)
    if any(key not in CO2_KEYS for key in requested):
        raise ValueError(f'CO2 property keys are {CO2_KEYS}')
    temperature, pressure = _co2_states(T, P)
    if temperature.ndim == 0:
        bundle = _co2_scalar(float(temperature), float(pressure))
        values = tuple(bundle[CO2_KEYS.index(key)] for key in requested)
    else:
        values = _co2_evaluate(requested, temperature, pressure)
    return values[0] if one else values


def validate_sco2_state(T_K, P_Pa, *, where=None):
    T, P = np.asarray(T_K, dtype=float), np.asarray(P_Pa, dtype=float)
    if not (np.all(np.isfinite(T)) and np.all(np.isfinite(P))):
        message = 'sCO2 state must be finite'
        invalid = ~np.isfinite(T) | ~np.isfinite(P)
    elif np.any((T < T_RANGE_K[0]) | (T > T_RANGE_K[1])):
        message = 'sCO2 temperature must be within 280..700 K'
        invalid = (T < T_RANGE_K[0]) | (T > T_RANGE_K[1])
    elif np.any((P < P_RANGE_PA[0]) | (P > P_RANGE_PA[1])):
        message = 'sCO2 pressure must be within 7.9..16 MPa'
        invalid = (P < P_RANGE_PA[0]) | (P > P_RANGE_PA[1])
    else:
        return
    if where is not None:
        T, P, invalid = np.broadcast_arrays(T, P, invalid)
        index = tuple(int(item) for item in np.unravel_index(np.flatnonzero(invalid)[0], T.shape))
        message += f'; {where}, index={index}, T={T[index]} K, P={P[index]} Pa'
    raise ValueError(message)


@lru_cache(maxsize=4096)
def _sco2_prop(key, T_K, P_Pa):
    validate_sco2_state(T_K, P_Pa)
    return float(CP.PropsSI(key, 'T', float(T_K), 'P', float(P_Pa), 'CO2'))


def sco2_prop(key, T_K, P_Pa):
    T, P = np.asarray(T_K, dtype=float), np.asarray(P_Pa, dtype=float)
    if isinstance(key, str) and T.ndim == 0 and P.ndim == 0:
        return _sco2_prop(key, float(T), float(P))
    validate_sco2_state(T, P)
    shape = np.broadcast_shapes(T.shape, P.shape)
    temperatures = np.ascontiguousarray(np.broadcast_to(T, shape)).ravel()
    pressures = np.ascontiguousarray(np.broadcast_to(P, shape)).ravel()
    output = CP.PropsSI(key, 'T', temperatures, 'P', pressures, 'CO2')
    if not isinstance(key, str):
        return np.ascontiguousarray(np.asarray(output, dtype=float).reshape(-1, len(key)).T).reshape((len(key),) + shape)
    return np.asarray(output, dtype=float).reshape(shape)


@lru_cache(maxsize=4096)
def sco2_temperature(h_Jkg, P_Pa):
    if not P_RANGE_PA[0] <= float(P_Pa) <= P_RANGE_PA[1]:
        raise ValueError('sCO2 pressure must be within 7.9..16 MPa')
    temperature = float(CP.PropsSI('T', 'H', float(h_Jkg), 'P', float(P_Pa), 'CO2'))
    validate_sco2_state(temperature, P_Pa)
    return temperature


def sco2_temperature_from_enthalpy(h_Jkg, P_Pa):
    enthalpy, pressure = np.asarray(h_Jkg, dtype=float), np.asarray(P_Pa, dtype=float)
    if enthalpy.ndim == 0 and pressure.ndim == 0:
        return sco2_temperature(float(enthalpy), float(pressure))
    shape = np.broadcast_shapes(enthalpy.shape, pressure.shape)
    hf = np.ascontiguousarray(np.broadcast_to(enthalpy, shape)).ravel()
    pf = np.ascontiguousarray(np.broadcast_to(pressure, shape)).ravel()
    if np.any((pf < P_RANGE_PA[0]) | (pf > P_RANGE_PA[1])):
        raise ValueError('sCO2 pressure must be within 7.9..16 MPa')
    temperature = np.asarray(CP.PropsSI('T', 'H', hf, 'P', pf, 'CO2'), dtype=float).reshape(shape)
    validate_sco2_state(temperature, np.broadcast_to(pressure, shape))
    return temperature
