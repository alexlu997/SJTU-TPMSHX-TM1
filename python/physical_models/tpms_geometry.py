"""TPMS geometry entry points backed by the native geometry and preparation libraries.

Cell length and full wall thickness use mm. Area density uses 1/m.
Hydraulic diameter uses m. The default voxel resolution remains N=128.
The native core owns phi generation, inclusive counts and calibrated geometry.
"""

import numpy as np

from tm1.model_configs.model_parameters import load_model_parameters
from tm1.cpp_interface import _native_geometry, _native_properties
from tm1.cpp_interface._native_values import TOPOLOGIES, real_array


_GEOMETRY_KEYS = ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h')
_AREA_CORRECTION = load_model_parameters()['geometry']['area_correction']


def _phi_grid(tpms_type: str, N: int):
    """Return the cached, read-only native phi grid."""
    return _native_geometry.phi_grid(tpms_type, N)


_phi_grid.cache_clear = _native_geometry._cached_phi.cache_clear
_phi_grid.cache_info = _native_geometry._cached_phi.cache_info


def lattice_cell_size(L_mm) -> tuple[float | None, str | None]:
    """Return the common cell length in mm or the reason that the lattice is unavailable."""
    cells = real_array(L_mm, name='L_mm')
    if not cells.size or cells.min() <= 0.:
        raise ValueError('L_mm must contain positive cell lengths')
    cell = float(cells.flat[0])
    if np.any(cells != cell):
        return None, 'The lattice phase rule for graded L is undefined.'
    return cell, None


def signed_wall_grid(
    tpms_type: str, L_mm, box_mm, sample_counts, t_mm, delta=0.,
) -> tuple[dict[str, np.ndarray] | None, str | None]:
    """Return (samples, None) for uniform L or (None, reason) for graded L.

    Each axis runs from zero to its box length in mm and includes both faces.
    Supply t_mm and delta as scalars or as arrays with sample_counts shape in (x, y, z) order.
    The owned arrays phi, lower (delta - C) and upper (delta + C) have that shape.
    C is the calibrated threshold at t_mm / L_mm. Fluid A has phi < lower.
    Fluid B has phi > upper. Both limits belong to the solid.
    """
    cell, reason = lattice_cell_size(L_mm)
    if reason is not None:
        return None, reason
    return _native_geometry.signed_wall_grid(tpms_type, cell, box_mm, sample_counts, t_mm, delta), None


def _C_from_tL(tpms_type: str, t_over_L: float | np.ndarray):
    """Return the calibrated native threshold with the input shape."""
    result = _native_geometry.threshold(tpms_type, t_over_L)
    return result[()] if result.ndim == 0 else result


def minimum_solid_geometry(tpms_type, L_bounds, t_bounds):
    """Return the native minimum-solid-volume point within the supplied bounds."""
    result = _native_geometry.standard_minimum(tpms_type, L_bounds, t_bounds)
    return {key: float(result[key]) for key in ('L_mm', 't_mm', 'epsilon')}


@_native_properties.cache_controls(_native_properties.GEOMETRY_CACHE)
def compute_geometry(tpms_type: str, L_mm: float, t_mm: float, N: int = 128) -> dict:
    """Return a fresh mapping for the cached scalar geometry."""
    if tpms_type not in TOPOLOGIES:
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{tpms_type}'")
    try:
        resolution = _native_geometry._resolution(N)
    except ValueError:
        # The native operation reports invalid dimensions before an invalid resolution.
        resolution = 0
    values = _native_properties.cached_geometry(tpms_type, L_mm, t_mm, resolution)
    return dict(zip(_GEOMETRY_KEYS, (float(values[0]), float(values[1]), float(values[2]), *values[3:]), strict=True))


def compute_geometry_fields(tpms_type: str, L_field_mm, t_field_mm,
                            N: int = 128) -> dict:
    """Return independent writable C-order float64 geometry arrays."""
    if tpms_type not in TOPOLOGIES:
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
