"""TPMS geometry entry points backed by the native geometry core.

Cell length and full wall thickness use mm. Area density uses 1/m.
Hydraulic diameter uses m. The default voxel resolution remains N=128.
The native core owns phi generation, inclusive counts and calibrated geometry.
"""
from functools import lru_cache

import numpy as np

from sjtu_tpmshx.shared.configs.model_parameters import load_model_parameters
from . import _native_geometry


_TOPOLOGIES = ('Diamond', 'Gyroid')
_GEOMETRY_KEYS = ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h')
_AREA_CORRECTION = load_model_parameters()['geometry']['area_correction']


def _phi_grid(tpms_type: str, N: int):
    """Return the cached, read-only native phi grid."""
    return _native_geometry.phi_grid(tpms_type, N)


_phi_grid.cache_clear = _native_geometry._cached_phi.cache_clear
_phi_grid.cache_info = _native_geometry._cached_phi.cache_info


def _C_from_tL(tpms_type: str, t_over_L: float | np.ndarray):
    """Return the calibrated native threshold with the input shape."""
    result = _native_geometry.threshold(tpms_type, t_over_L)
    return result[()] if result.ndim == 0 else result


def minimum_solid_geometry(tpms_type, L_bounds, t_bounds):
    """Return the native minimum-solid-volume point within the supplied bounds."""
    result = _native_geometry.standard_minimum(tpms_type, L_bounds, t_bounds)
    return {key: float(result[key]) for key in ('L_mm', 't_mm', 'epsilon')}


@lru_cache(maxsize=32768)
def _compute_geometry_cached(tpms_type: str, L_mm: float, t_mm: float,
                             N: int = 128) -> dict:
    """Cache scalar geometry without material or environment state."""
    if tpms_type not in _TOPOLOGIES:
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{tpms_type}'")
    if L_mm <= 0:
        raise ValueError(f"L_mm must be positive, got {L_mm}")
    if t_mm <= 0:
        raise ValueError(f"t_mm must be positive, got {t_mm}")
    if 2 * t_mm >= L_mm:
        raise ValueError(f"Wall thickness t={t_mm}mm >= L={L_mm}mm, no pore space")
    try:
        values = _native_geometry.standard_fields(tpms_type, L_mm, t_mm, 1., N=N)
    except ValueError as error:
        if str(error).startswith('Degenerate TPMS geometry:'):
            raise ValueError(
                f"Degenerate TPMS geometry: {tpms_type} L={L_mm}mm t={t_mm}mm "
                "has no usable pore space. Reduce t or increase L.") from error
        raise
    result = {key: values[key][()] for key in _GEOMETRY_KEYS}
    for key in ('epsilon', 'epsilon_A', 'epsilon_B'):
        result[key] = float(result[key])
    return result


def compute_geometry(tpms_type: str, L_mm: float, t_mm: float,
                     N: int = 128) -> dict:
    """Return a fresh scalar geometry mapping from the process-local cache."""
    return dict(_compute_geometry_cached(tpms_type, L_mm, t_mm, N))


def compute_geometry_fields(tpms_type: str, L_field_mm, t_field_mm,
                            N: int = 128) -> dict:
    """Return independent writable C-order float64 geometry arrays."""
    if tpms_type not in _TOPOLOGIES:
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{tpms_type}'")
    length = np.asarray(L_field_mm, dtype=np.float64)
    wall = np.asarray(t_field_mm, dtype=np.float64)
    if length.ndim == 0 or wall.ndim == 0 or length.shape != wall.shape:
        raise ValueError('L/t fields must have the same array shape')
    if not np.all(np.isfinite(length) & np.isfinite(wall)):
        raise ValueError('L/t fields must be finite')
    if np.any(length <= 0.):
        raise ValueError('L_mm must be positive')
    if np.any(wall <= 0.):
        raise ValueError('t_mm must be positive')
    if np.any(2. * wall >= length):
        raise ValueError('Wall thickness must satisfy 2*t < L, with usable pore space')
    if isinstance(N, (bool, np.bool_)) or not isinstance(N, (int, np.integer)) or N < 1:
        raise ValueError('geometry resolution N must be a positive integer')
    values = _native_geometry.standard_fields(tpms_type, length, wall, 1., N=N)
    return {key: values[key] for key in _GEOMETRY_KEYS}


compute_geometry.cache_clear = _compute_geometry_cached.cache_clear
compute_geometry.cache_info = _compute_geometry_cached.cache_info
