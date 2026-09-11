"""
tpms_geometry.py — Numerical computation of TPMS geometric properties.

Given TPMS type, unit cell size L [mm], and wall thickness t [mm],
computes porosity (epsilon) and specific surface area (A_0) by numerical
integration on a 3D voxel grid.

TPMS implicit functions:
  Diamond: phi = sin(kx)*sin(ky)*sin(kz) + sin(kx)*cos(ky)*cos(kz)
           + cos(kx)*sin(ky)*cos(kz) + cos(kx)*cos(ky)*sin(kz)
  Gyroid:  phi = sin(kx)*cos(ky) + sin(ky)*cos(kz) + sin(kz)*cos(kx)

  where k = 2*pi/L

Solid region: |phi| <= C(t), where C is the level-set threshold
corresponding to wall thickness t. The wall is the band between the two
bounding isosurfaces phi=-C and phi=+C, centered on the minimal surface phi=0.

The relationship between C and t is established numerically by fitting C(t/L)
to CAD porosity data (see _C_COEFFS). Geometrically, t is the FULL wall
thickness across that band (phi=-C to phi=+C), not the half-distance from
phi=0 to phi=C. Because phi is a trig sum (not a signed-distance field), the
physical thickness is t = 2*C / |grad phi|_phys, with |grad phi|_phys =
(2*pi/L)*g and g = |grad phi| ~ 1.5 at the surface; hence t != 2*C in mm even
though the band spans 2*C in phi-units.
"""

import numpy as np
from functools import lru_cache

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ── TPMS implicit functions ──────────────────────────────────────

def _phi_diamond(x, y, z):
    """Diamond TPMS level-set function."""
    return (np.sin(x)*np.sin(y)*np.sin(z)
            + np.sin(x)*np.cos(y)*np.cos(z)
            + np.cos(x)*np.sin(y)*np.cos(z)
            + np.cos(x)*np.cos(y)*np.sin(z))


def _phi_gyroid(x, y, z):
    """Gyroid TPMS level-set function."""
    return np.sin(x)*np.cos(y) + np.sin(y)*np.cos(z) + np.sin(z)*np.cos(x)


_PHI_FUNCS = {
    'Diamond': _phi_diamond,
    'Gyroid': _phi_gyroid,
}


# ── Pre-computed phi grid (cached per TPMS type + resolution) ────

@lru_cache(maxsize=4)
def _phi_grid(tpms_type: str, N: int):
    """Compute and cache phi values on [0, 2*pi]^3 grid. L-independent.

    The cached ndarray is SHARED across all callers, so it is frozen
    (writeable=False): a caller mutating it would poison every later cache
    hit silently (W7b hazard family; same hardening as sco2_props
    _FIELD_CACHE). Callers needing a scratch copy must .copy().
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
    # Voxel face counting overestimates smooth surface area by a constant
    # factor (~pi/2 in 3D). Calibrated correction: 1.553 from known data.
    _AREA_CORRECTION = 1.553
    return n_faces * dx**2 / (2.0 * L_m**3 * _AREA_CORRECTION)


def _find_C_for_eps(phi: np.ndarray, target_eps: float) -> float:
    """Binary search for C that gives target porosity."""
    C_lo, C_hi = 0.0, float(np.max(np.abs(phi)))
    for _ in range(60):  # ~18 digits of precision
        C_mid = (C_lo + C_hi) / 2.0
        eps = _eps_from_C(phi, C_mid)
        if eps > target_eps:  # not enough solid → increase C
            C_lo = C_mid
        else:
            C_hi = C_mid
    return (C_lo + C_hi) / 2.0


# ── Calibration: C(t/L) from known data ──────────────────────────
#
# Strategy:
#   1. For each known (L, t, eps), find C that gives eps on the phi grid.
#   2. Since phi is L-independent, C depends only on t/L.
#   3. Fit C(t/L) → use for arbitrary (L, t).

_DIAMOND_TABLE = {
    (4, 0.3): 0.713, (4, 0.4): 0.621, (4, 0.5): 0.532,
    (5, 0.3): 0.770, (5, 0.4): 0.695, (5, 0.5): 0.621,
    (6, 0.3): 0.808, (6, 0.4): 0.745, (6, 0.5): 0.682,
    (8, 0.3): 0.855, (8, 0.4): 0.808, (8, 0.5): 0.760,
}
_GYROID_TABLE = {
    (4, 0.3): 0.769, (4, 0.4): 0.694, (4, 0.5): 0.620,
    (5, 0.3): 0.815, (5, 0.4): 0.754, (5, 0.5): 0.694,
    (6, 0.3): 0.845, (6, 0.4): 0.794, (6, 0.5): 0.744,
    (8, 0.3): 0.884, (8, 0.4): 0.845, (8, 0.5): 0.807,
}
_DIAMOND_A0_TABLE = {
    (4, 0.3): 925, (4, 0.4): 897, (4, 0.5): 858,
    (5, 0.3): 751, (5, 0.4): 736, (5, 0.5): 717,
    (6, 0.3): 631, (6, 0.4): 622, (6, 0.5): 611,
    (8, 0.3): 476, (8, 0.4): 473, (8, 0.5): 468,
}
_GYROID_A0_TABLE = {
    (4, 0.3): 755, (4, 0.4): 740, (4, 0.5): 721,
    (5, 0.3): 609, (5, 0.4): 602, (5, 0.5): 592,
    (6, 0.3): 510, (6, 0.4): 506, (6, 0.5): 500,
    (8, 0.3): 385, (8, 0.4): 383, (8, 0.5): 380,
}

# Pre-computed calibration coefficients for C(t/L) = a*(t/L) + b*(t/L)^2.
# Calibrated against 12 CAD data points per TPMS type (N=256 grid).
# Max calibration error < 0.5%.
_C_COEFFS = {
    'Diamond': (4.804355187041238, -2.0288570445530025),
    'Gyroid':  (4.890319597988319, -1.6151811942086873),
}


def _C_from_tL(tpms_type: str, t_over_L: float) -> float:
    """Get level-set threshold C from t/L ratio using pre-computed calibration."""
    a, b = _C_COEFFS[tpms_type]
    return a * t_over_L + b * t_over_L**2


# ── Core computation ─────────────────────────────────────────────

# perf-wave1 (2026-07-03): 64 → 2048. The continuous-field optimizer
# quantizes designs to hundreds of unique (L, t) pairs per eval; at
# maxsize=64 the 128³ voxel scan (~10–30 ms) re-ran on every eviction
# miss. Entries are two floats — memory cost is nil.
@lru_cache(maxsize=2048)
def _compute_raw(tpms_type: str, L_mm: float, t_mm: float,
                 N: int = 128) -> dict:
    """
    Compute epsilon and A_0 using calibrated level-set thresholding.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_mm      : unit cell size [mm]
    t_mm      : wall thickness [mm]
    N         : grid resolution (default 128, audit M-d / P3 2026-05-28;
                16 MiB/proc vs 128 MiB at N=256; epsilon drift <0.3 %,
                A_0 drift <1 % per test_tpms_geometry_n128)

    Returns
    -------
    dict with keys: epsilon, A_0 [m^-1]
    """
    L_m = L_mm / 1000.0
    tL = t_mm / L_mm

    # Get calibrated C threshold
    C = _C_from_tL(tpms_type, tL)
    if C < 0:
        C = 0.0

    # Compute on phi grid
    phi = _phi_grid(tpms_type, N)
    eps = _eps_from_C(phi, C)
    A0 = _A0_from_C(phi, C, L_m, N)

    return {'epsilon': eps, 'A_0': A0}


@lru_cache(maxsize=4096)   # perf-wave1: 1024 → 4096, same rationale as above
def _compute_geometry_cached(tpms_type: str, L_mm: float, t_mm: float,
                             N: int = 128) -> dict:
    """
    Compute TPMS geometric properties with validation.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_mm      : unit cell size [mm]  (must be > 0)
    t_mm      : wall thickness [mm]  (must be > 0, t < L)

    Returns
    -------
    dict with keys: epsilon, A_0 [m^-1], D_h [m]
    """
    if tpms_type not in _PHI_FUNCS:
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{tpms_type}'")
    if L_mm <= 0:
        raise ValueError(f"L_mm must be positive, got {L_mm}")
    if t_mm <= 0:
        raise ValueError(f"t_mm must be positive, got {t_mm}")
    if 2 * t_mm >= L_mm:
        raise ValueError(f"Wall thickness t={t_mm}mm >= L={L_mm}mm, no pore space")

    result = _compute_raw(tpms_type, L_mm, t_mm, N)
    eps = result['epsilon']
    A0 = result['A_0']
    # Per-stream void fractions for the bicontinuous sheet HX.
    # Sheet TPMS splits the void ε equally between two fluid channels A and B,
    # so each fluid occupies ε_A = ε_B = ε/2 of the total domain volume.
    # Each fluid contacts the FULL wall area A_0 from its own side.
    eps_A = 0.5 * eps
    eps_B = 0.5 * eps
    # Standard hydraulic diameter for a single fluid stream:
    # D_h = 4·V_void_single / A_wet_single = 4·ε_A / A_0
    # (Same coefficient 4 as the textbook D_h definition; the per-stream void
    # fraction ε_A already absorbs the bicontinuous sheet split. Equivalent to
    # the legacy form 2·ε/A_0 used before 2026-04-29. See memory
    # `reference_dh_convention.md`.)
    D_h = 4.0 * eps_A / A0 if A0 > 0 else 0.0

    # Robustness (2026-06-25): the 2t>=L guard above leaves a near-degenerate
    # band (t just under L/2) where _compute_raw returns epsilon~0 / A_0~0, so
    # D_h collapses to 0 and every downstream Re = rho*u*D_h/mu and
    # H_sf = Nu*k/D_h silently divides by zero. Fail loud instead of emitting a
    # zero-porosity cell. Valid geometries (epsilon ~ 0.3-0.8) are unaffected.
    if eps <= 1e-9 or A0 <= 0.0 or D_h <= 0.0:
        raise ValueError(
            f"Degenerate TPMS geometry: {tpms_type} L={L_mm}mm t={t_mm}mm "
            f"yields epsilon={eps:.3e}, A_0={A0:.3e}, D_h={D_h:.3e} m — no "
            "usable pore space (t too close to L/2). Reduce t or increase L.")

    return {
        'epsilon': eps,
        'epsilon_A': eps_A,
        'epsilon_B': eps_B,
        'A_0': A0,
        'D_h': D_h,
    }


def compute_geometry(tpms_type: str, L_mm: float, t_mm: float,
                     N: int = 128) -> dict:
    """Public entry: fresh shallow copy of the cached geometry dict.

    The lru_cache used to hand every caller the SAME dict object; a caller
    mutating its result would poison all later cache hits (the W7b hazard
    tpms_calc.compute was bitten by — see test_cache_and_source_guards).
    Values are all scalars, so a shallow copy fully detaches the caller.
    """
    return dict(_compute_geometry_cached(tpms_type, L_mm, t_mm, N))


# Cache management re-exposed (the wrapper hides the lru_cache attributes).
compute_geometry.cache_clear = _compute_geometry_cached.cache_clear
compute_geometry.cache_info = _compute_geometry_cached.cache_info


# ── Verification against lookup table data ───────────────────────

if __name__ == '__main__':
    print("=" * 80)
    print("Verification: numerical computation vs Excel lookup table")
    print("=" * 80)

    for tpms in ['Diamond', 'Gyroid']:
        table = _DIAMOND_TABLE if tpms == 'Diamond' else _GYROID_TABLE
        print(f"\n  {tpms}")
        print(f"  {'(L,t)':10s}  {'eps_table':>9s} {'eps_calc':>9s} {'err%':>6s}  "
              f"{'A0_table':>8s} {'A0_calc':>8s} {'err%':>6s}")
        print(f"  {'-'*65}")

        a0_table = _DIAMOND_A0_TABLE if tpms == 'Diamond' else _GYROID_A0_TABLE
        for (L, t), eps_tbl in sorted(table.items()):
            A0_tbl = a0_table[(L, t)]
            r = compute_geometry(tpms, L, t)
            eps_err = abs(r['epsilon'] - eps_tbl) / eps_tbl * 100
            A0_err = abs(r['A_0'] - A0_tbl) / A0_tbl * 100
            print(f"  L={L} t={t}    {eps_tbl:9.3f} {r['epsilon']:9.3f} {eps_err:5.1f}%  "
                  f"{A0_tbl:8.1f} {r['A_0']:8.1f} {A0_err:5.1f}%")

    print(f"\n{'=' * 80}")
