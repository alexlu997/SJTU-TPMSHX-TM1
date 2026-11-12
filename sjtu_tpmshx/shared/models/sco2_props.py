"""Supercritical CO2 transport/thermo properties via CoolProp (Span-Wagner).

Scalar and field APIs query CoolProp's CO2 model at supplied temperature and
absolute pressure; inverse queries recover temperature from enthalpy and
pressure. Thermodynamic properties use its equation of state, while viscosity
and conductivity use its transport-property models.

Properties can vary sharply near the pseudocritical line. The state bounds
checked here are independent of Nu-fit applicability and solver validation.
"""
from __future__ import annotations

from functools import lru_cache

from sjtu_tpmshx.shared.configs.model_parameters import load_model_parameters
from sjtu_tpmshx.shared.domain.compute_config import SCO2_P_RANGE_PA as P_RANGE_PA  # noqa: F401 - public range constant
from . import _native_properties
from .preparation_cache import scalar_cache
T_RANGE_K = tuple(load_model_parameters()['sco2']['temperature_range_K'])


def _validate_state(T_K, P_Pa, *, where=None) -> None:
    import numpy as _np
    T = _np.asarray(T_K, dtype=float)
    P = _np.asarray(P_Pa, dtype=float)
    try:
        _native_properties.sco2_validate(T, P)
    except _native_properties.StateError as error:
        message, failure = str(error), error.failure
    else:
        return
    _raise_state_error(message, failure, T, P, where=where)


def _raise_state_error(message, failure, T, P, *, where=None):
    """Keep shape and location errors at the original state boundary."""
    import numpy as _np
    if failure.reason == 1:
        try:
            _np.broadcast_shapes(T.shape, P.shape)
        except ValueError:
            raise _native_properties._ufunc_shape_error(T.shape, P.shape) from None
    if where is not None:
        broadcast_T, broadcast_P = _np.broadcast_arrays(T, P)
        if not broadcast_T.size:
            raise IndexError('index 0 is out of bounds for axis 0 with size 0')
        candidates = []
        absent = _np.iinfo(_np.uintp).max
        for original, first in ((T, failure.first_t_index), (P, failure.first_p_index)):
            if first == absent:
                continue
            local = _np.unravel_index(first, original.shape)
            index = (0,) * (broadcast_T.ndim - original.ndim) + tuple(int(value) for value in local)
            candidates.append(int(_np.ravel_multi_index(index, broadcast_T.shape)))
        index = tuple(int(value) for value in _np.unravel_index(min(candidates), broadcast_T.shape))
        message += f'; {where}, index={index}, T={broadcast_T[index]} K, P={broadcast_P[index]} Pa'
    raise ValueError(message) from None


@scalar_cache(maxsize=4096)
def _prop(key: str, T_K: float, P_Pa: float) -> float:
    """Cache scalar CoolProp queries for repeated identical (key, T, P)."""
    _validate_state(T_K, P_Pa)
    try:
        return _native_properties.sco2_pt(key, float(T_K), float(P_Pa), scalar=True)
    except _native_properties.StateError as error:
        raise ValueError(str(error)) from None


def sco2_prop(key: str | tuple[str, ...], T_K, P_Pa):
    """Scalar-OR-vectorised CoolProp query of `key` over (T, P).

    The caller supplies inlet or local absolute pressure for the property
    evaluation. Temperature and pressure may each be scalar or arrays:

      * scalar T and scalar P  -> the cached scalar `_prop` (hot path, cached);
      * any array T or P       -> a single vectorised CoolProp call, T and P
        broadcast to a common shape (so a scalar P broadcasts across a T field,
        and a per-cell P field is honoured cell-by-cell).

    A tuple of keys queries one HEOS state per cell for all requested outputs;
    its result has a leading property axis. A single key returns a float for
    the all-scalar case, else an ndarray shaped like the broadcast of T and P.
    """
    import numpy as _np
    T = _np.asarray(T_K, dtype=float)
    P = _np.asarray(P_Pa, dtype=float)
    if isinstance(key, str) and T.ndim == 0 and P.ndim == 0:
        return _prop(key, float(T), float(P))
    _validate_state(T, P)
    shape = _np.broadcast_shapes(T.shape, P.shape)
    Tf = _np.ascontiguousarray(_np.broadcast_to(T, shape)).ravel()
    Pf = _np.ascontiguousarray(_np.broadcast_to(P, shape)).ravel()
    try:
        out = _native_properties.sco2_pt(key, Tf, Pf)
    except _native_properties.StateError as error:
        raise ValueError(str(error)) from None
    if not isinstance(key, str):
        return _np.ascontiguousarray(_np.asarray(out, dtype=float)).reshape(
            (len(key),) + shape)
    return _np.asarray(out, dtype=float).reshape(shape)












@lru_cache(maxsize=4096)
def sco2_temperature(h_Jkg: float, P_Pa: float) -> float:
    """Inverse T [K] = T(h, P) using CoolProp at supplied absolute pressure.

    Validate both the supplied pressure and the returned temperature against
    this module's state bounds.
    """
    _native_properties.sco2_scalar_pressure(float(P_Pa))
    try:
        return _native_properties.sco2_hp(float(h_Jkg), float(P_Pa), scalar=True)
    except _native_properties.StateError as error:
        raise ValueError(str(error)) from None


def sco2_temperature_from_enthalpy(h_Jkg, P_Pa):
    """Scalar-or-field inverse ``T(h, P)`` using direct CoolProp."""
    import numpy as _np
    h = _np.asarray(h_Jkg, dtype=float)
    P = _np.asarray(P_Pa, dtype=float)
    if h.ndim == 0 and P.ndim == 0:
        return sco2_temperature(float(h), float(P))
    shape = _np.broadcast_shapes(h.shape, P.shape)
    hf = _np.ascontiguousarray(_np.broadcast_to(h, shape)).ravel()
    Pf = _np.ascontiguousarray(_np.broadcast_to(P, shape)).ravel()
    try:
        return _native_properties.sco2_hp(hf, Pf).reshape(shape)
    except _native_properties.StateError as error:
        raise ValueError(str(error)) from None
