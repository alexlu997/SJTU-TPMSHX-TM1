"""Runtime inference from the fixed, geometry-only water+sCO2 CFD table.

Scalar and broadcast-array K/cF use the same bilinear interpolation. Direct
calls may name the supported method explicitly; retired method names fail.
Production pipelines pin the fixed model regardless of environment state.
"""
from __future__ import annotations

import os
import sys
import warnings
from math import sqrt

import numpy as np

from sjtu_tpmshx.domain.run_warnings import record_warning

R_AIR = 287.05

# One-shot warning when the 1D compressible dP is infeasible (choked) and the
# non-strict path rescues to P_in (robustness 2026-06-25).
_CHOKE_WARNED: set = set()


def reset_choke_warn_registry() -> None:
    """Re-arm the standalone choke registry; pipeline runs own their records."""
    _CHOKE_WARNED.clear()


from .backend import METHOD as SCO2_DF_METHOD, available_methods, get_backend  # noqa: E402

_DF_DEFAULT = SCO2_DF_METHOD


def _resolve_method(method: str | None = None) -> str:
    """Per-call ``method`` wins; else env TPMSHX_DF_METHOD; else default."""
    m = (method if method is not None
         else os.environ.get("TPMSHX_DF_METHOD", _DF_DEFAULT)).strip().lower()
    if m not in available_methods():
        raise ValueError(f"unknown DF method {m!r}; "
                         f"valid: {available_methods()}")
    return m


def _get_model(tpms_type: str, method: str | None = None):
    """Return the cached surrogate backend for (tpms_type, method).

    Only the fixed CFD model is supported.
    """
    return get_backend(tpms_type, _resolve_method(method))


# ==================================================================
# Public API
# ==================================================================

def predict_K_cF(tpms_type: str, L_mm: float, t_mm: float,
                 eps_f: float, method: str | None = None) -> tuple[float, float]:
    """Return (K [m²], cF [1/m]) from the fixed geometry table."""
    return _get_model(tpms_type, method).predict(L_mm, t_mm, eps_f)


def predict_K_cF_vec(tpms_type: str, L_mm: np.ndarray, t_mm: np.ndarray,
                     eps_f: np.ndarray, method: str | None = None
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised variant for solver iteration over grid cells.

    Shape-agnostic: accepts any compatible array shape (1D, 2D, 3D). The
    returned (K, c_F) arrays match the input shape. Inputs are broadcast
    together.

    """
    L_arr = np.asarray(L_mm, dtype=np.float64)
    t_arr = np.asarray(t_mm, dtype=np.float64)
    e_arr = np.asarray(eps_f, dtype=np.float64)
    shape = np.broadcast(L_arr, t_arr, e_arr).shape

    model = _get_model(tpms_type, method)
    L_flat = np.broadcast_to(L_arr, shape).ravel()
    t_flat = np.broadcast_to(t_arr, shape).ravel()
    e_flat = np.broadcast_to(e_arr, shape).ravel()
    K = np.empty(L_flat.size)
    cF = np.empty(L_flat.size)
    for i in range(L_flat.size):
        K[i], cF[i] = model.predict(float(L_flat[i]), float(t_flat[i]),
                                   float(e_flat[i]))
    return K.reshape(shape), cF.reshape(shape)


def predict_dP(tpms_type: str, L_mm: float, t_mm: float, eps_f: float,
               u: float, rho: float, mu: float,
               L_channel_m: float, method: str | None = None) -> float:
    """Compute dP via incompressible D-F (backward-compatible interface).

    For compressible flow, use predict_dP_compressible instead.
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=method)
    return (mu * u / K + rho * c_F * u ** 2) * L_channel_m


def predict_dP_compressible(tpms_type: str, L_mm: float, t_mm: float,
                            eps_f: float, G: float, T: float,
                            P_in: float, mu: float,
                            L: float, strict: bool = False,
                            method: str | None = None) -> float:
    """1D compressible isothermal D-F pressure drop.

    P_out^2 = P_in^2 - 2*R*T*(mu*G/K + c_F*G^2)*L

    Parameters
    ----------
    G : mass flux [kg/(m^2 s)]
    T : temperature [K]
    P_in : inlet absolute pressure [Pa]
    mu : dynamic viscosity [Pa s]
    L : channel length [m]
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=method)
    C = mu * G / K + c_F * G ** 2
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
    if P_out_sq <= 0:
        # Codex #6: infeasible (no real P_out). strict → NaN for
        # detect+exclude+count; default → legacy P_in (optimizer untouched).
        # Robustness (2026-06-25): the non-strict P_in rescue used to be
        # silent. Warn once so a choked operating point isn't mistaken for a
        # genuine dP ≈ P_in result.
        _choke_key = (tpms_type, round(float(L_mm), 2), round(float(t_mm), 2))
        message = (
            f"[D-F choke] 1D compressible dP infeasible "
            f"(P_out^2={P_out_sq:.3e} <= 0, predicted dP >= P_in): the flow "
            "is choked at these conditions; returning P_in as the dP "
            "rescue. Reduce velocity/length or raise inlet pressure.")
        if (not record_warning(('df_choke', *_choke_key), message)
                and _choke_key not in _CHOKE_WARNED):
            _CHOKE_WARNED.add(_choke_key)
            warnings.warn(message, stacklevel=2)
        return float('nan') if strict else P_in
    return P_in - sqrt(P_out_sq)


# ==================================================================
# Smoke test
# ==================================================================

def smoke_test() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    # Quick Shanghai check
    from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry
    g = tpms_geometry("Gyroid", 7.0, 0.6, 16.0)
    K, cF = predict_K_cF("Gyroid", 7.0, 0.6, g["epsilon"] / 2)
    print(f"\nL=7 t=0.6: K={K:.4e}, c_F={cF:.2f}")


if __name__ == "__main__":
    smoke_test()
