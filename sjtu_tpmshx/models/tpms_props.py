"""tpms_props.py — leaf module: TPMS geometry + fluid property correlations.

Split out of ``tpms_calc.py`` (openspec arch-b-c-e, batch B, 2026-07-02) so
``df_surrogate`` can depend on geometry/props WITHOUT importing the full
``tpms_calc`` orchestrator (whose ``compute()`` in turn needs
``df_surrogate.predict`` — the old two-way coupling was held shut by deferred
imports on the solvers side). New direction, module-load level:

    tpms_geometry  ←  tpms_props  ←  df_surrogate  ←  tpms_calc / simple_solver

``tpms_calc`` re-exports every name below verbatim, so existing consumers
(``from solvers.tpms_calc import geometry, air_viscosity, ...``) are
unaffected. Dependencies stay limited to stdlib / numpy / ``.tpms_geometry``
and the Qt-free ``domain.run_warnings`` leaf.

All functions moved verbatim (bit-identical); see tpms_calc.py's module
docstring for the project-wide Re/Nu conventions.
"""
from __future__ import annotations

import os
import warnings

import numpy as np

from .tpms_geometry import compute_geometry as _tpms_geom
from sjtu_tpmshx.domain.run_warnings import record_range

# ── Physical constants ────────────────────────────────────────
R     = 8.314      # Universal gas constant [J/(mol·K)]
M_air = 0.028966   # Molar mass of dry air [kg/mol]
P_atm = 101325.0   # Standard atmospheric pressure [Pa] (for Re reference density)


# ── Air property correlations ─────────────────────────────────

# Validity ranges for the fitted correlations (per docstrings below).
_AIR_T_RANGE    = (200.0, 1100.0)   # Sutherland + kappa fits
_AIR_CP_RANGE   = (250.0, 1000.0)   # polynomial cp fit
_WATER_T_RANGE  = (273.15, 363.15)  # 0 - 90 °C polynomial water fits
_AIR_CP_COEFFICIENTS = (1004.5, 0.172, -7.56e-5)
_WATER_CP = 4182.0


def model_h_coefficients(fluid):
    """Existing cp polynomial, temperature origin and model-h reference (K)."""
    if fluid == 'air':
        return (*_AIR_CP_COEFFICIENTS, 273.15, 300.0)
    if fluid == 'water':
        return (_WATER_CP, 0.0, 0.0, 273.15, 300.0)
    raise ValueError('model h supports only air and water')

_range_warnings_emitted = set()


def record_temperature_ranges(fluid, T):
    """Compare a temperature-model state with existing fits, without property calls.

    Callers select only the empirical temperature/model-h route, not HEOS Air.
    This is run-local evidence; standalone property warning behavior is unchanged.
    """
    if T is None:
        return
    if fluid == 'air':
        fits = (('air_viscosity', _AIR_T_RANGE),
                ('air_conductivity', _AIR_T_RANGE), ('air_cp', _AIR_CP_RANGE))
    elif fluid == 'water':
        fits = tuple((f'water_{name}', _WATER_T_RANGE)
                     for name in ('density', 'viscosity', 'conductivity', 'cp'))
    else:
        return
    for name, bounds in fits:
        record_range(('property_state', name), T, bounds,
                     label=name, quantity='T', unit='K')


def _warn_range_once(name: str, T, lo: float, hi: float) -> None:
    """Emit a single UserWarning per (name) key when T goes outside the
    fitted validity range. Keeps logs readable when coupled solvers
    call these functions millions of times per run."""
    T_arr = np.asarray(T, dtype=float)
    if T_arr.size == 0:
        return
    if record_range(('property', name), T_arr, (lo, hi),
                    label=name, quantity='T', unit='K'):
        return
    T_min = float(T_arr.min())
    T_max = float(T_arr.max())
    if T_min < lo or T_max > hi:
        message = (
            f"{name}: T=[{T_min:.1f}, {T_max:.1f}] K outside fitted range "
            f"[{lo:.1f}, {hi:.1f}] K — extrapolating.")
        key = (name, round(T_min, 1), round(T_max, 1))
        if key in _range_warnings_emitted:
            return
        _range_warnings_emitted.add(key)
        warnings.warn(message, stacklevel=3)


def air_viscosity(T_K: float) -> float:
    """Dynamic viscosity of air via Sutherland's law [Pa·s]."""
    _warn_range_once('air_viscosity', T_K, *_AIR_T_RANGE)
    T0, mu0, S = 273.15, 1.716e-5, 110.4
    return mu0 * (T_K / T0) ** 1.5 * (T0 + S) / (T_K + S)


def air_conductivity(T_K: float) -> float:
    """Thermal conductivity of air [W/(m·K)]."""
    _warn_range_once('air_conductivity', T_K, *_AIR_T_RANGE)
    return 0.0241 * (T_K / 273.15) ** 0.82


def air_density(T_K, P_Pa: float = 101325.0):
    """Density of air via ideal gas law [kg/m³]. Accepts scalar or ndarray T_K;
    return type matches input shape."""
    return P_Pa * M_air / (R * T_K)


def air_cp(T_K):
    """Specific heat capacity of air [J/(kg·K)] (250-1000 K, < 0.5% error).
    Accepts scalar or ndarray T_K; return type matches input shape."""
    _warn_range_once('air_cp', T_K, *_AIR_CP_RANGE)
    dT = T_K - 273.15
    a, b, c = _AIR_CP_COEFFICIENTS
    return a + b * dT + c * dT**2


# ── Water property correlations ───────────────────────────────

def water_density(T_K):
    """Density of liquid water [kg/m³]. Polynomial valid 0-90 °C."""
    _warn_range_once('water_density', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - 273.15
    return 999.84 - 0.05 * T_C - 0.004 * T_C**2


def water_viscosity(T_K):
    """Dynamic viscosity of liquid water [Pa·s].

    Vogel form (Andrade equation), NIST 0–90 °C max error < 2 %:
        mu = 2.414e-5 * 10^(247.8 / (T_K - 140))   [Pa·s, T_K in K]

    Replaced legacy `1.79e-3·exp(-0.035·T_C)` (2026-04-29) which decayed
    far too fast (-33 % at 40 °C, -53 % at 60 °C vs NIST). The legacy
    formula matched only 0–15 °C; Shanghai water bulk T 20-40 °C was
    systematically under-viscous → over-predicted Re_water ~50 % at hi T.
    """
    _warn_range_once('water_viscosity', T_K, *_WATER_T_RANGE)
    T_K_arr = np.asarray(T_K, dtype=float)
    # Floor the (T-140) denominator at 10 K so the 10**(247.8/denom) term stays
    # finite: at T~141 K the raw exponent ~247.8 overflows to +inf in float64
    # (robustness 2026-06-25). Physical liquid water (T>=273 K -> denom>=133)
    # is far above the floor, so this is bit-identical in range.
    denom = np.maximum(T_K_arr - 140.0, 10.0)
    return 2.414e-5 * 10.0 ** (247.8 / denom)


def water_conductivity(T_K):
    """Thermal conductivity of liquid water [W/(m·K)]. Linear fit 0-90 °C."""
    _warn_range_once('water_conductivity', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - 273.15
    return 0.569 + 0.0018 * T_C


def water_cp(T_K):
    """Specific heat of liquid water [J/(kg·K)]. ~constant 280-370 K."""
    _warn_range_once('water_cp', T_K, *_WATER_T_RANGE)
    return _WATER_CP


# ── Geometry-only interface (no fluid needed) ─────────────────

# Solid-conduction tortuosity correction chi_s: K_ss = chi_s*(1-eps)*k_s.
# The naive `K_ss = (1 - eps) * k_s` assumes parallel solid paths aligned
# with the heat-flow direction; the real curved sheet network conducts less.
#
# B2 (2026-07-06): chi_s is now FITTED from unit-cell periodic numerical
# homogenization (runs/tools/homogenize_chi_s.py — steady conduction on the
# production N=128 voxel geometry, the same |phi|<=C(t/L) mask as eps/A_0;
# per-point 3-axis isotropy 0.00% by cubic symmetry, full-solid/laminate
# analytic checks exact; data validation/chi_s_homogenization.csv).
# Linear fit over the production window t/L 0.03-0.20 (eps 0.27-0.91),
# max residual ~0.012:
#     chi_s = c0 + c1*(1-eps)
# Thin-wall caveat: at t/L <~ 0.05 the wall spans only ~4 voxels and the
# fit inherits a small low bias; N-refinement at the Shanghai point
# (Gyroid, eps 0.737) extrapolates chi 0.655(N=128) -> ~0.667 (thin-sheet
# theoretical limit 2/3), i.e. the baked values sit ~2% below continuum.
#
# Env var TPMSHX_CHI_S (a constant) still overrides everything — legacy
# escape hatch; the historical default was the uncalibrated 1.0.
_CHI_S_FIT = {
    'Diamond': (0.5446, 0.3765),
    'Gyroid':  (0.5630, 0.3292),
}
_CHI_S_ENV = os.environ.get('TPMSHX_CHI_S')
# Legacy module constant: env value when set, else the pre-B2 default 1.0.
# Kept for import back-compat; production K_ss paths use chi_s_eff below.
CHI_S = float(_CHI_S_ENV) if _CHI_S_ENV is not None else 1.0


def chi_s_eff(tpms_type: str, eps):
    """Effective solid-conduction tortuosity chi_s(type, eps).

    Vectorized over `eps` (scalar or ndarray). Priority:
    env TPMSHX_CHI_S constant (legacy override) > per-type linear fit.

    The env var is read PER CALL (P1.6, audit §5d): the old import-time
    snapshot silently ignored TPMSHX_CHI_S set after the first import —
    monkeypatch.setenv in tests and runtime overrides both hit that trap.
    (The module constant CHI_S above keeps its documented import-time
    snapshot semantics for back-compat.)
    """
    env = os.environ.get('TPMSHX_CHI_S')
    if env is not None:
        c = float(env)
        e = np.asarray(eps, dtype=np.float64)
        return c if e.ndim == 0 else np.full_like(e, c)
    c0, c1 = _CHI_S_FIT[tpms_type]
    out = c0 + c1 * (1.0 - np.asarray(eps, dtype=np.float64))
    return float(out) if out.ndim == 0 else out


def geometry(tpms_type: str, L_cell_mm: float, t_mm: float, k_s: float,
             chi_s: float | None = None, N: int = 128) -> dict:
    """
    Return TPMS geometric properties without fluid information.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_cell_mm : unit cell size [mm]
    t_mm      : wall thickness [mm]
    k_s       : solid thermal conductivity [W/(m·K)]
    chi_s     : solid tortuosity factor (optional). Explicit value wins;
                default = `chi_s_eff(tpms_type, eps)` (B2 homogenization
                fit; env TPMSHX_CHI_S constant overrides the fit).
                K_ss = chi_s * (1 - eps) * k_s.
    N         : voxelisation grid resolution (default 128 as of audit M-d /
                P3 2026-05-28; was 256). The phi grid is N^3 float64
                (16 MiB at N=128 vs 128 MiB at N=256), so the lower default
                cuts per-process memory ~8x for parallel BO with un-shared
                lru_caches. epsilon drift <0.3 % and A_0 drift <1 % vs
                N=256, guarded by test_tpms_geometry_n128.

    Returns
    -------
    dict with keys: epsilon, epsilon_A, epsilon_B, A_0, D_h, K_ss

    Notes
    -----
    epsilon_A = epsilon_B = epsilon / 2 are the per-stream void fractions for
    the bicontinuous sheet HX (two fluid channels sharing the void equally).
    D_h is the single-stream hydraulic diameter D_h = 4·epsilon_A / A_0.
    """
    g = _tpms_geom(tpms_type, L_cell_mm, t_mm, N)
    chi = float(chi_s_eff(tpms_type, g['epsilon']) if chi_s is None
                else chi_s)
    return {
        'epsilon':   g['epsilon'],
        'epsilon_A': g['epsilon_A'],
        'epsilon_B': g['epsilon_B'],
        'A_0':       g['A_0'],
        'D_h':       g['D_h'],
        'K_ss':      chi * (1.0 - g['epsilon']) * k_s,
    }
