"""Independent NumPy voxel scans retained from the pre-port numerical owner.

Reference source: 9fb5401d. Coefficients stay frozen for this porting check.
No production geometry or native bridge supplies expected values.
"""
from functools import lru_cache
import numpy as np

_C_COEFFS = {
    'Diamond': (4.804355187041238, -2.0288570445530025),
    'Gyroid': (4.890319597988319, -1.6151811942086873),
}
_AREA_CORRECTION = 1.553
_CHI_S_FIT = {'Diamond': (.5446, .3765), 'Gyroid': (.5630, .3292)}

def _phi_diamond(x, y, z):
    """Diamond TPMS level-set function."""
    return (np.sin(x)*np.sin(y)*np.sin(z)
            + np.sin(x)*np.cos(y)*np.cos(z)
            + np.cos(x)*np.sin(y)*np.cos(z)
            + np.cos(x)*np.cos(y)*np.sin(z))


def _phi_gyroid(x, y, z):
    """Gyroid TPMS level-set function."""
    return np.sin(x)*np.cos(y) + np.sin(y)*np.cos(z) + np.sin(z)*np.cos(x)


_PHI_FUNCS = {'Diamond': _phi_diamond, 'Gyroid': _phi_gyroid}


@lru_cache(maxsize=4)
def _phi_grid(tpms_type: str, N: int):
    """Compute and cache phi values on [0, 2*pi]^3 grid. L-independent.

    The cached ndarray is SHARED across all callers, so it is frozen
    (writeable=False): a caller mutating it would poison every later cache
    hit silently. Callers needing a scratch copy must .copy().
    """
    phi_func = _PHI_FUNCS[tpms_type]
    h = 2 * np.pi / N
    x1d = np.linspace(h / 2, 2 * np.pi - h / 2, N)
    X, Y, Z = np.meshgrid(x1d, x1d, x1d, indexing='ij')
    phi = phi_func(X, Y, Z)
    phi.flags.writeable = False
    return phi


def _eps_from_C(phi: np.ndarray, C: float) -> float:
    """Porosity for a given level-set threshold C."""
    return float(1.0 - np.mean(np.abs(phi) <= C))


def _A0_from_C(phi: np.ndarray, C: float, L_m: float, N: int) -> float:
    """Single-side specific surface area [m^-1] for threshold C."""
    dx = L_m / N
    solid = np.abs(phi) <= C
    n_faces = 0
    n_faces += np.sum(solid[:-1, :, :] != solid[1:, :, :])
    n_faces += np.sum(solid[:, :-1, :] != solid[:, 1:, :])
    n_faces += np.sum(solid[:, :, :-1] != solid[:, :, 1:])
    return n_faces * dx**2 / (2.0 * L_m**3 * _AREA_CORRECTION)


def _C_from_tL(tpms_type: str, t_over_L: float | np.ndarray):
    """Return the calibrated threshold for scalar or array t/L."""
    a, b = _C_COEFFS[tpms_type]
    return a * t_over_L + b * np.float_power(t_over_L, 2)


