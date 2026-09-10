"""Supercritical CO2 transport/thermo properties via CoolProp (Span-Wagner).

Phase A backend for the ``'sco2'`` fluid (2026-06-26). Unlike air (ideal-gas,
T-only) and water (incompressible, T-only), sCO2 properties depend on BOTH
temperature and pressure — strongly so near the pseudocritical line. All
functions therefore take ``(T_K, P_Pa)``.

CoolProp's CO2 model is the Span-Wagner reference EOS; equilibrium properties
(ρ, cp, h) match REFPROP exactly, transport (μ, k) within ~1 %
(see vault [[reference_coolprop_refprop_co2]]).

Far-from-critical use is robust; near the critical point (304 K / 7.38 MPa)
the property derivatives are stiff — that regime is Phase C, not Phase A.
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
            "`pip install CoolProp` (see requirements.txt).")


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
        message = "sCO2 V1 temperature must be within 280..700 K"
        invalid = (T < T_RANGE_K[0]) | (T > T_RANGE_K[1])
    elif _np.any((P < P_RANGE_PA[0]) | (P > P_RANGE_PA[1])):
        message = "sCO2 V1 pressure must be within 7.9..16 MPa"
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
    """Cached scalar CoolProp query. CO2 EOS calls are ~µs but repeat heavily
    across solver iterations at near-identical (T,P); cache keeps it cheap."""
    _validate_state(T_K, P_Pa)
    return float(_PropsSI(key, "T", float(T_K), "P", float(P_Pa), _FLUID))


def sco2_prop(key: str, T_K, P_Pa):
    """Scalar-OR-vectorised CoolProp query of `key` over (T, P).

    The registry primitives (fluid_props) call rho/cp/mu/k both with scalars
    (inlet references) and with whole 2D/3D FIELDS (the variable-property outer
    loop passes a T field and the local absolute-P field). Span-Wagner real-gas
    ρ/cp depend on BOTH, so neither can be frozen. Dispatch:

      * scalar T and scalar P  -> the cached scalar `_prop` (hot path, cached);
      * any array T or P       -> a single vectorised CoolProp call, T and P
        broadcast to a common shape (so a scalar P broadcasts across a T field,
        and a per-cell P field is honoured cell-by-cell).

    Returns a float for the all-scalar case, else an ndarray shaped like the
    broadcast of T and P.
    """
    import numpy as _np
    T = _np.asarray(T_K, dtype=float)
    P = _np.asarray(P_Pa, dtype=float)
    if T.ndim == 0 and P.ndim == 0:
        return _prop(key, float(T), float(P))
    _validate_state(T, P)
    shape = _np.broadcast_shapes(T.shape, P.shape)
    Tf = _np.ascontiguousarray(_np.broadcast_to(T, shape)).ravel()
    Pf = _np.ascontiguousarray(_np.broadcast_to(P, shape)).ravel()
    out = _PropsSI(key, "T", Tf, "P", Pf, _FLUID)
    return _np.asarray(out, dtype=float).reshape(shape)


def sco2_density(T_K: float, P_Pa: float) -> float:
    """ρ [kg/m³] = ρ(T, P) — real-gas, NOT ideal."""
    return _prop("D", T_K, P_Pa)


def sco2_cp(T_K: float, P_Pa: float) -> float:
    """Isobaric specific heat cp [J/(kg·K)] = cp(T, P)."""
    return _prop("C", T_K, P_Pa)


def sco2_viscosity(T_K: float, P_Pa: float) -> float:
    """Dynamic viscosity μ [Pa·s] = μ(T, P)."""
    return _prop("V", T_K, P_Pa)


def sco2_conductivity(T_K: float, P_Pa: float) -> float:
    """Thermal conductivity k [W/(m·K)] = k(T, P)."""
    return _prop("L", T_K, P_Pa)


def sco2_enthalpy(T_K: float, P_Pa: float) -> float:
    """Specific enthalpy h [J/kg] = h(T, P). Used for enthalpy-based duty
    Q = ṁ·Δh (sCO2 cp is not constant across a HX temperature span)."""
    return _prop("H", T_K, P_Pa)


@lru_cache(maxsize=4096)
def sco2_temperature(h_Jkg: float, P_Pa: float) -> float:
    """Inverse: T [K] = T(h, P). Span-Wagner is monotone in h at fixed P, so
    the inversion is single-valued. Needed for the Phase C (near-critical)
    enthalpy formulation — across the pseudocritical line cp spikes ×10-20, so
    the energy balance is carried in enthalpy and converted back to T here
    rather than integrating an ill-conditioned cp·dT."""
    if not P_RANGE_PA[0] <= float(P_Pa) <= P_RANGE_PA[1]:
        raise ValueError("sCO2 V1 pressure must be within 7.9..16 MPa")
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
        raise ValueError("sCO2 V1 pressure must be within 7.9..16 MPa")
    T = _np.asarray(_PropsSI("T", "H", hf, "P", Pf, _FLUID), dtype=float)
    T = T.reshape(shape)
    _validate_state(T, _np.broadcast_to(P, shape))
    return T


# ── Vectorised field queries (Phase C: per-cell property updates) ──────────
# CoolProp's PropsSI broadcasts over the state arrays, so a whole temperature
# field at a (near-constant) pressure is one call instead of N cached scalars.
# Used by the variable-property outer loop where the cp/ρ field is refreshed
# every iteration as T evolves through the pseudocritical zone.

def clear_field_cache() -> None:
    """Clear the scalar CoolProp cache (kept for existing callers/tests)."""
    _prop.cache_clear()


def sco2_field(key: str, T_K, P_Pa: float):
    """Direct vectorised CoolProp query over a temperature field."""
    return sco2_prop(key, T_K, P_Pa)


def sco2_density_field(T_K, P_Pa: float):
    """ρ field [kg/m³] over a T field at fixed P."""
    return sco2_field("D", T_K, P_Pa)


def sco2_cp_field(T_K, P_Pa: float):
    """cp field [J/(kg·K)] over a T field at fixed P."""
    return sco2_field("C", T_K, P_Pa)


def sco2_rho_cp_field(T_K, P_Pa: float):
    """ρ·cp field [J/(m³·K)] — the energy-equation convective coefficient that
    swings ×10-20 through the pseudocritical line (Phase C)."""
    return sco2_density_field(T_K, P_Pa) * sco2_cp_field(T_K, P_Pa)


def sco2_enthalpy_field(T_K, P_Pa: float):
    """h field [J/kg] over a T field at fixed P. Vectorised counterpart of
    ``sco2_enthalpy`` for the mass-weighted mean outlet enthalpy ⟨h(T)⟩ in the
    duty extraction (the scalar lru_cache form can't take an array face)."""
    return sco2_field("H", T_K, P_Pa)


def sco2_temperature_field(h_Jkg, P_Pa: float):
    """T field [K] = T(h, P) over an enthalpy field at fixed P. Vectorised
    inverse of ``sco2_enthalpy_field`` (Span-Wagner is monotone in h at fixed
    P → single-valued). The Option B enthalpy-form 3D LTNE kernel keeps h as the
    primary fluid unknown; the pipeline inverts T = T(h,P) each outer iteration
    to feed the diffusion / inter-phase coupling. Array form of
    ``sco2_temperature``."""
    return sco2_temperature_from_enthalpy(h_Jkg, P_Pa)


def sco2_viscosity_field(T_K, P_Pa: float):
    """μ field [Pa·s] over a T field at fixed P."""
    return sco2_field("V", T_K, P_Pa)


def sco2_conductivity_field(T_K, P_Pa: float):
    """k field [W/(m·K)] over a T field at fixed P."""
    return sco2_field("L", T_K, P_Pa)
