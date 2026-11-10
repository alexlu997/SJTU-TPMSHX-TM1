"""Native raw-phi geometry entry points for offset isosurfaces.

Raw queries retain separate voxel and marching-cubes area definitions.
Offline searches and connectivity checks live in development tools.
"""
import warnings

import numpy as np

from . import _native_geometry
from .tpms_geometry import _AREA_CORRECTION


def _warn_empty_phase_means(phi):
    """Retain the default warnings from the two original empty means."""
    if np.size(phi) == 0:
        for _ in range(2):
            warnings.warn('Mean of empty slice.', RuntimeWarning, stacklevel=3)
            warnings.warn('invalid value encountered in scalar divide', RuntimeWarning, stacklevel=3)


def eps_sides(phi: np.ndarray, C: float, delta: float = 0.0):
    """Return side A, side B and total void fractions from native counts."""
    _warn_empty_phase_means(phi)
    return tuple(float(value) for value in _native_geometry.eps_sides(phi, C, delta))


def a0_sides(phi: np.ndarray, C: float, delta: float, L_m: float, N: int):
    """Return the native voxel area density for each side in 1/m."""
    values = _native_geometry.area_sides(phi, C, delta, L_m, N, _AREA_CORRECTION)
    return tuple(float(value) for value in values)


def a0_sides_mc(phi: np.ndarray, C: float, delta: float, L_m: float, N: int):
    """Return the native marching-cubes area density for each side in 1/m."""
    values = _native_geometry.area_sides(phi, C, delta, L_m, N, _AREA_CORRECTION, mc=True)
    return tuple(float(value) for value in values)


def dh_from_sides(eps_A: float, eps_B: float, A0_A: float, A0_B: float):
    """Return native side diameters in m from porosity and area density."""
    return tuple(float(value) for value in _native_geometry.dh_from_sides(eps_A, eps_B, A0_A, A0_B))


def dh_sides(phi: np.ndarray, C: float, delta: float, L_m: float, N: int,
             mc: bool = False):
    """Return native side diameters with the selected area definition."""
    _warn_empty_phase_means(phi)
    values = _native_geometry.dh_sides(phi, C, delta, L_m, N, _AREA_CORRECTION, mc=mc)
    return tuple(float(value) for value in values)


def wall_thickness_from_sides(eps_total: float, A0_A: float, A0_B: float) -> float:
    """Return native mean slab wall thickness in m."""
    return float(_native_geometry.wall_from_sides(eps_total, A0_A, A0_B))


def wall_thickness(phi: np.ndarray, C: float, delta: float, L_m: float, N: int) -> float:
    """Return native mean wall thickness from the supplied raw phi field."""
    _warn_empty_phase_means(phi)
    return float(_native_geometry.wall_thickness(phi, C, delta, L_m, N, _AREA_CORRECTION))
