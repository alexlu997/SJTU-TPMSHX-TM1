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

from sjtu_tpmshx.domain.compute_config import SCO2_P_RANGE_PA as P_RANGE_PA

try:
    from CoolProp.CoolProp import PropsSI as _PropsSI
    _HAVE_COOLPROP = True
except Exception:                       # pragma: no cover - import guard
    _HAVE_COOLPROP = False

    def _PropsSI(*_a, **_k):
        raise ImportError(
            "CoolProp is required for the sCO2 fluid but is not installed. "
            "Use the project's locked environment; see README.md.")


_FLUID = "CO2"
T_RANGE_K = (280.0, 700.0)


def _validate_state(T_K, P_Pa, *, where=None) -> None:
    import numpy as _np
    T = _np.asarray(T_K, dtype=float)
    P = _np.asarray(P_Pa, dtype=float)
    if not (_np.all(_np.isfinite(T)) and _np.all(_np.isfinite(P))):
        message = "sCO2 state must be finite"
        invalid = ~_np.isfinite(T) | ~_np.isfinite(P)
    elif _np.any((T < T_RANGE_K[0]) | (T > T_RANGE_K[1])):
        message = "sCO2 temperature must be within 280..700 K"
        invalid = (T < T_RANGE_K[0]) | (T > T_RANGE_K[1])
    elif _np.any((P < P_RANGE_PA[0]) | (P > P_RANGE_PA[1])):
        message = "sCO2 pressure must be within 7.9..16 MPa"
        invalid = (P < P_RANGE_PA[0]) | (P > P_RANGE_PA[1])
    else:
        return
    if where is not None:
        T, P, invalid = _np.broadcast_arrays(T, P, invalid)
        index = _np.unravel_index(_np.flatnonzero(invalid)[0], T.shape)
        index = tuple(int(i) for i in index)
        message += f"; {where}, index={index}, T={T[index]} K, P={P[index]} Pa"
    raise ValueError(message)


@lru_cache(maxsize=4096)
def _prop(key: str, T_K: float, P_Pa: float) -> float:
    """Cache scalar CoolProp queries for repeated identical (key, T, P)."""
    _validate_state(T_K, P_Pa)
    return float(_PropsSI(key, "T", float(T_K), "P", float(P_Pa), _FLUID))


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
    out = _PropsSI(key, "T", Tf, "P", Pf, _FLUID)
    if not isinstance(key, str):
        return _np.ascontiguousarray(_np.asarray(out, dtype=float).reshape(-1, len(key)).T).reshape(
            (len(key),) + shape)
    return _np.asarray(out, dtype=float).reshape(shape)












@lru_cache(maxsize=4096)
def sco2_temperature(h_Jkg: float, P_Pa: float) -> float:
    """Inverse T [K] = T(h, P) using CoolProp at supplied absolute pressure.

    Validate both the supplied pressure and the returned temperature against
    this module's state bounds.
    """
    if not P_RANGE_PA[0] <= float(P_Pa) <= P_RANGE_PA[1]:
        raise ValueError("sCO2 pressure must be within 7.9..16 MPa")
    T = float(_PropsSI("T", "H", float(h_Jkg), "P", float(P_Pa), _FLUID))
    _validate_state(T, P_Pa)
    return T


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
    if _np.any((Pf < P_RANGE_PA[0]) | (Pf > P_RANGE_PA[1])):
        raise ValueError("sCO2 pressure must be within 7.9..16 MPa")
    T = _np.asarray(_PropsSI("T", "H", hf, "P", Pf, _FLUID), dtype=float)
    T = T.reshape(shape)
    _validate_state(T, _np.broadcast_to(P, shape))
    return T
