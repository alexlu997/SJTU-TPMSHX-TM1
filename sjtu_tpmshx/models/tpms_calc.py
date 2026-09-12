"""
tpms_calc.py — TPMS Property Calculator

Given TPMS geometry (type, L_cell, t) and flow conditions (u, T_in, P_in),
computes all parameters needed by solve.py:
  epsilon, A_0, D_h, Re, Nu, f, dP/L, H_sf, K_ff, K_ss, rho, mu, k_f

Includes:
  - Geometry via numerical TPMS voxelization (epsilon, A_0 for any L, t)
  - Air property correlations (Sutherland, ideal gas)
  - Nu correlations (Diamond / Gyroid)
  - Darcy-Forchheimer dP closure (no f-Re): dP via df_surrogate K / c_F

Supported TPMS types: 'Diamond', 'Gyroid'
Fluids: air, water, and sCO2 through the shared property registry

──────────────────────────────────────────────────────────────────────
REYNOLDS NUMBER CONVENTION (project-wide, confirmed 2026-04-22)
──────────────────────────────────────────────────────────────────────

All Re computations use hydraulic diameter D_h:

    Re = ρ · u · D_h / μ    (single-channel interstitial u)

Training Excel (试验记录表_整理版.xlsx) mass flow back-calculation:
    m_total = Re × μ / D_h × A_cross × 2   (×2 = two TPMS channels)

The ×2 is for converting single-channel to total mass flow, NOT for
the Re definition. Nu correlations fitted on D_h Re.

Nu OUTPUT convention: Nu = h · D_h / k_f   (standard D_h definition).

Nu correlations take D_h-convention Re as input
but output D_h-convention Nu. All solver callers use the correct
convention on both sides, so downstream Q calculations are consistent.
──────────────────────────────────────────────────────────────────────
"""

import functools
import warnings
import numpy as np  # noqa: F401 - preserve existing module surface
from sjtu_tpmshx.domain.run_warnings import (
    cache_warning_records, current_warnings, merge_warnings,
)
from .tpms_geometry import compute_geometry as _tpms_geom

# arch-b-c-e batch B (2026-07-02): geometry + fluid-property correlations
# moved verbatim to the LEAF module tpms_props so df_surrogate can import
# them without pulling this orchestrator (whose compute() needs
# df_surrogate.predict). Re-exported here so existing consumers keep their
# `from solvers.tpms_calc import ...` paths unchanged.
from .tpms_props import (  # noqa: F401 — re-exports
    CHI_S, chi_s_eff, M_air, P_atm, R,
    air_conductivity, air_cp, air_density, air_viscosity,
    geometry,
    water_conductivity, water_cp, water_density, water_viscosity,
    _warn_range_once,
)
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

# ── Physical constants ────────────────────────────────────────
Pr    = 0.72       # Prandtl number (air, approximately constant)
Sa_mm = 0.031      # Surface roughness Sa [mm]  (= 31 μm, constant for both TPMS types)


def nu_water_gyroid_yan6(Re, Pr):
    """Water-side Nusselt number for Gyroid TPMS, Yan et al 2024 [6].

        Nu = 0.471 · Re^0.627 · Pr^(1/3)

    Source: K. Yan, H. Deng, Y. Xiao, J. Wang, Y. Luo,
    'Thermo-hydraulic performance evaluation through experiment and
    simulation of additive manufactured Gyroid-structured heat exchanger',
    Appl. Therm. Eng. 241 (2024) 122402.
    doi:10.1016/j.applthermaleng.2024.122402

    Validated range: 150 < Re < 3000 (water, AM Gyroid).

    Convention:
      Re = ρ·u·D_h / μ        (single-stream, D_h = 4·ε_A/A_0)
      Nu = h_sf · D_h / k_f   (face heat-transfer coefficient h_sf)
      Pr = μ·c_p / k_f

    Notes:
      * Experiment + CFD double-fit on AM gyroid sample (cell 20 mm).
      * Surface roughness from AM is naturally embedded; do not apply
        an extra ×1.28 roughness factor on top.
      * Project Shanghai cases 3-16 (Re 173-1146) fall in-range.
      * Cases 1-2 (Re 54, 108) extrapolate to lower Re, ≈ -9 % on Nu
        relative to Yan [58] in-range; acceptable since h_vB dominates U.
    """
    return 0.471 * Re ** 0.627 * Pr ** (1.0 / 3.0)


# ── Fluid type validation ─────────────────────────────────────

# Each fluid keeps its own property and Nu model. Production pressure loss uses
# one geometry-only fixed CFD table shared by both sides and all fluid types.
_SUPPORTED_FLUIDS = {'air', 'water', 'sco2'}


def parse_fluid_type(combo):
    """Normalise a QComboBox current text to an internal fluid_type key.

    Returns one of: 'air', 'water', 'sco2'.
    """
    t = combo.currentText().lower().replace('₂', '2')
    if 'co2' in t or 'sco' in t:
        return 'sco2'
    if 'water' in t:
        return 'water'
    return 'air'


def validate_fluid_type(fluid_type: str, side: str) -> None:
    """Raise NotImplementedError for fluid types without fitted correlations.

    Air + water + sCO2 are supported. sCO2 uses direct CoolProp properties and
    the smooth-wall CFD Nu correlation. Production K/cF are selected only by
    TPMS topology, L, and t from the fixed water+sCO2 CFD table; they do not
    depend on fluid type or Reynolds number.

    For water:
      * Properties: NIST-grade rho/mu/k (Vogel viscosity, < 2 % vs NIST 0–90 °C).
      * Nu (heat transfer): nu_water_topo — per-topology direct water-CFD
        fit (WATER_NU_COEFFS, Re 100-50000, smooth-wall, no air ×1.28).
        nu_water_from_Re (Pr-substitution) and nu_water_gyroid_yan6 (Yan
        2024 [6]) are retired to cross-check / test only.
      * dP closure: the same geometry-only fixed CFD K/cF used by all fluids.
    """
    if fluid_type not in _SUPPORTED_FLUIDS:
        label = {'water': 'Water', 'sco2': 'sCO₂'}.get(fluid_type, fluid_type)
        raise NotImplementedError(
            f"Fluid {side} = {label} is not supported yet — no fitted "
            f"correlations (Nu / f-Re / D-F surrogate) for this fluid. "
            f"Select Air for now."
        )


# ── Nu correlations ───────────────────────────────────────────
# Single source of truth lives in `solvers.nu_correlations` (2026-05-28
# audit Item 1 / H1). Detailed roughness rationale + known limitations
# moved to that module's docstring.

from .nu_correlations import (  # noqa: F401 - existing public re-exports
    nu_from_Re,
    nu_vec,
    nu_water_from_Re,
    nu_water_topo,
    nu_sco2_topo,
    NU_ROUGHNESS_FACTOR as _NU_ROUGHNESS_FACTOR,  # back-compat re-export
    NU_RE_FIT_RANGE,
    WATER_NU_RE_RANGE,
    NU_COEFFS,
    SCO2_NU_COEFFS,
    SCO2_NU_RE_RANGE,
)

# Per-fluid Re fit windows for the compute()-level out-of-range warning. The
# Nu correlations have DIFFERENT validated Re ranges per fluid; warning every
# fluid against the air window (400,16000) mis-flagged in-range water/sCO2 and
# silently passed out-of-range sCO2 below 9000 (audit 2026-06-28 N5).
_RE_FIT_RANGE_BY_FLUID = {
    'air': NU_RE_FIT_RANGE,
    'water': WATER_NU_RE_RANGE,
    'sco2': SCO2_NU_RE_RANGE,
}


# ── Geometry-only interface ────────────────────────────────────
# geometry() + CHI_S moved to tpms_props (leaf; re-exported above).

# Fluid-phase thermal dispersion coefficient. K_ff = ε·k_f + C_DISP·ρcp·|u|·D_h.
# Zero default = pure molecular conduction. Literature range 0.05-0.3 for TPMS.
#
# B4 step-0 sensitivity verdict (2026-07-06) — KEEP 0.0 BY EVIDENCE:
# sweeping C ∈ {0.05, 0.1, 0.3} (bounding value) moved the Shanghai gates by
# sub-percent amounts and consistently DEGRADED the Q agreement (3D gate
# RMSRE_Q 3.21→3.54%, fine 64-grid 2.94→3.20%; 2D evaluator Q +1.8% at
# C=0.3, dP unchanged; sweep knob: validate_shanghai_3d_real --disp-c).
# Interpretation: the fitted Nu (h_v) already absorbs the mixing the
# experiments contain, so adding dispersion on top DOUBLE-COUNTS (boundary
# rule R1). Do not set C_DISP > 0 unless the Nu correlations are refit
# simultaneously against data that separates interfacial exchange from
# macroscopic dispersion (e.g. axial-profile fits, not integral duty).
C_DISP = 0.0


def adaptive_grid(L_domain: float, H_domain: float,
                  D_h: float, alpha: float = 0.4) -> tuple:
    """Compute grid dimensions for a target dx/D_h ratio.

    Parameters
    ----------
    L_domain, H_domain : float — domain size [m]
    D_h    : float — hydraulic diameter [m]
    alpha  : float — target dx/D_h (0.8 coarse, 0.4 display, 0.2 fine)

    Returns
    -------
    Nx, Ny : int
    """
    Nx = max(20, round(L_domain / (alpha * D_h)))
    Ny = max(10, round(H_domain / (alpha * D_h)))
    return Nx, Ny


# ── Main interface ────────────────────────────────────────────

@functools.lru_cache(maxsize=4096)
def _compute_cached(tpms_type: str,
                    L_cell_mm: float,
                    t_mm: float,
                    u: float,
                    T_in_K: float,
                    P_in_Pa: float,
                    k_s: float,
                    fluid_type: str = 'air',
                    _df_env: tuple = ('', ''), sco2_nu=None) -> tuple[dict, dict]:
    """
    Compute all TPMS heat-transfer and fluid properties.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_cell_mm : TPMS unit cell size [mm]  (valid range: 4–8 mm)
    t_mm      : wall thickness [mm]        (valid range: 0.3–0.5 mm)
    u         : fluid (air) velocity [m/s]
    T_in_K    : inlet temperature [K]
    P_in_Pa   : inlet pressure [Pa]
    k_s       : solid thermal conductivity [W/(m·K)]

    Returns
    -------
    tuple[dict, dict]
        Numerical values and source warning records. Public ``compute``
        returns only a copy of the numerical dict; records stay internal.

    Numerical dict keys:
        epsilon   – porosity [-]
        A_0       – single-side specific surface area [m⁻¹] (area seen by one
                    fluid stream per unit total volume — NOT double-sided;
                    see tpms_geometry.py for derivation). h_vA = A_0 × H_sf_A
                    and h_vB = A_0 × H_sf_B therefore do NOT double-count.
        D_h       – hydraulic diameter [m]
        Re        – Reynolds number (based on D_h, interstitial velocity) [-]
        Nu        – Nusselt number [-]
        K_df      – permeability [m²] (fixed CFD D-F closure)
        cF_df     – Forchheimer coefficient [1/m] (fixed CFD D-F closure)
        dP_per_L  – pressure drop per unit length [Pa/m]
        H_sf      – face heat transfer coefficient [W/(m²·K)]
        K_ff      – fluid effective thermal conductivity [W/(m·K)]
        K_ss      – solid effective thermal conductivity [W/(m·K)]
        rho       – air density [kg/m³]
        mu        – air dynamic viscosity [Pa·s]
        k_f       – air thermal conductivity [W/(m·K)]
    """
    with cache_warning_records({}) as records:
        # ── Geometry from numerical computation ─────────────────────
        g = _tpms_geom(tpms_type, L_cell_mm, t_mm)
        eps   = g['epsilon']
        A0    = g['A_0']
        D_h_m = g['D_h']
        D_h_mm = D_h_m * 1000.0        # [mm]  (used in Nu correlation)

        # ── Fluid properties at inlet conditions ──────────────────
        # B1 1.1 (2026-06-12): property primitives via the fluid_props
        # registry (water rho ignores P — incompressible; air ideal-gas).
        # Function-level import: fluid_props imports tpms_calc at module level.
        from sjtu_tpmshx.models import fluid_props as _fluids
        _m = _fluids.get(fluid_type, sco2_nu=sco2_nu)
        # Pass P to all primitives: air/water ignore it (T-only), sCO2 needs it
        # (real-gas cp/mu/k/rho depend on both T and P). Widened 2026-06-26.
        mu = float(_m.mu(T_in_K, P_in_Pa))
        k_f = float(_m.k(T_in_K, P_in_Pa))
        rho = float(_m.rho(T_in_K, P_in_Pa))
        cp_f = float(_m.cp(T_in_K, P_in_Pa))

        # ── Reynolds number ──────────────────────────────────────
        # Re = rho * u * D_h / mu   (length scale = D_h, not r_h)
        #
        # Uses ACTUAL inlet density (at inlet T and inlet P), because physical
        # Nu depends on true Re, not on a canonical atmospheric Re (previous
        # bug was rho_ref=P_atm, which under-predicted high-Re Q by ~22%).
        #
        # D_h convention: Re = ρ·u·D_h / μ (single-channel interstitial u).
        # Training Excel: m_total = Re × μ / D_h × A × 2 (×2 for two channels).
        # Nu correlations fitted on D_h-convention Re.
        Re = rho * u * D_h_m / mu

        # Warn if outside correlation valid range. Single-sourced to the per-fluid
        # fit windows in nu_correlations (was a duplicate hard-coded [600, 30000];
        # unified 2026-06-25). Fluid-aware since 2026-06-28 (N5): water/sCO2 have
        # their own windows, so warning them against the air window mis-flagged.
        _nu_lo, _nu_hi = _RE_FIT_RANGE_BY_FLUID.get(fluid_type, NU_RE_FIT_RANGE)
        # A run records the actual Nu source below; standalone keeps this notice.
        if not (_nu_lo <= Re <= _nu_hi) and current_warnings() is None:
            warnings.warn(
                f"{tpms_type}: Re = {Re:.1f} is outside the validated range "
                f"[{_nu_lo:.0f}, {_nu_hi:.0f}]. Correlation accuracy may be reduced.",
                UserWarning, stacklevel=2
            )

        # ── Nusselt number and heat transfer coefficient ──────────
        # Single-stream convention (post-refit 2026-04-26): pass ε_A (per-stream
        # void fraction; sheet HX splits ε equally between two fluid channels).
        eps_A = 0.5 * eps
        # 2026-05-09 — route air through nu_from_Re() (not _nu_diamond / _nu_gyroid
        # directly). nu_from_Re applies the ×1.28 _NU_ROUGHNESS_FACTOR
        # (production, see memory project_nu_v3_cfd4_s8 — Shanghai Q RMSRE 2.02%
        # only with ×1.28 applied). Direct calls to _nu_diamond / _nu_gyroid
        # returned the smooth-wall Nu, which under-displayed Nu in the UI by 28%
        # while the SIMPLE/LTNE runtime correctly used ×1.28 via nu_from_Re —
        # cosmetic mismatch that confused users sanity-checking Nu vs Q.
        # Water path routes through nu_water_topo (per-topology direct water-CFD
        # fit, no ×1.28); the ×1.28 _NU_ROUGHNESS_FACTOR is AIR-only. Only the
        # air branch was ever buggy on the ×1.28 display.
        # B1 1.1: Nu via the registry's per-fluid dispatch — water forwards the
        # caller-computed Pr to nu_water_topo; the air adapter ignores Pr and
        # uses nu_from_Re's built-in Pr_AIR.
        Pr_f = mu * cp_f / k_f
        Nu = _m.nu(tpms_type, Re, eps_A, L_cell_mm, D_h_mm, Pr_f)

        H_sf = Nu * k_f / D_h_m        # face heat transfer coefficient [W/(m²·K)]

        # ── Pressure drop via fixed geometry-only CFD D-F table ─────────
        # dP/L = μu/K + ρ c_F u² (interstitial form; matches simple_solver
        # convention, see df_surrogate/predict.py). Import is module-level since
        # arch-b-c-e batch B (tpms_props leaf broke the old two-way coupling).
        K_df, cF_df = predict_K_cF(
            tpms_type, float(L_cell_mm), float(t_mm), float(eps) / 2.0,
            method=_df_env[0] or None,
        )
        dP_per_L = mu * u / K_df + rho * cF_df * u * u

        # ── Effective thermal conductivities (volume-averaged) ────
        # Fluid phase: molecular only by default. Optional thermal dispersion
        # K_disp = C_DISP * ρ·cp·|u|·D_h captures tortuous-channel mixing at
        # high Pe. Zero default preserves prior behaviour; calibrate per TPMS
        # from experimental Nu vs Pe data and expose via compute_ext if needed.
        K_ff = eps * k_f
        if C_DISP > 0.0:
            K_ff = K_ff + C_DISP * rho * cp_f * abs(u) * D_h_m
        K_ss = chi_s_eff(tpms_type, eps) * (1.0 - eps) * k_s

        return {
            'epsilon':   eps,
            'epsilon_A': eps_A,
            'epsilon_B': eps_A,     # symmetric sheet HX: ε_B = ε_A = ε/2
            'A_0':       A0,
            'D_h':       D_h_m,
            'Re':        Re,
            'Nu':        Nu,
            'K_df':      K_df,      # permeability [m²] (fixed CFD)
            'cF_df':     cF_df,     # Forchheimer coeff [1/m] (fixed CFD)
            'dP_per_L':  dP_per_L,
            'H_sf':      H_sf,
            'K_ff':      K_ff,
            'K_ss':      K_ss,
            'rho':       rho,
            'mu':        mu,
            'k_f':       k_f,
        }, records


# ── Quick verification ────────────────────────────────────────
def compute(tpms_type: str,
            L_cell_mm: float,
            t_mm: float,
            u: float,
            T_in_K: float,
            P_in_Pa: float,
            k_s: float,
            fluid_type: str = 'air', *, sco2_nu=None) -> dict:
    """Public entry — see ``_compute_cached`` for the full docstring.

    Production uses the fixed water+sCO2 CFD closure; environment state does
    not select a different backend. Experimental correction, when requested,
    is applied by the caller after assembling these CFD properties.

    Cache hits used to return the SAME mutable dict object; a caller
       mutating its result would silently poison every later hit. The
       wrapper returns a shallow copy (values are scalars).
    """
    from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
    from .fluid_props import check_water_state
    check_water_state(fluid_type, T_in_K, P_in_Pa, where='compute inlet')
    # Production V2 closure is fluid-independent and fixed for a TPMS/L/t
    # geometry.
    _df_method = SCO2_DF_METHOD
    _df_env = (_df_method, '')
    result, records = _compute_cached(tpms_type, L_cell_mm, t_mm, u, T_in_K,
                                     P_in_Pa, k_s, fluid_type, _df_env, sco2_nu)
    merge_warnings(current_warnings(), [records], bind_context=True)
    return dict(result)


# Back-compat: tests/sweeps clear the props cache via compute.cache_clear()
# (per-process sweep trap, see ledger CDISP notes).
compute.cache_clear = _compute_cached.cache_clear
compute.cache_info = _compute_cached.cache_info


if __name__ == '__main__':
    print("=" * 60)
    for name in ('Diamond', 'Gyroid'):
        print(f"{name}  L=8mm  t=0.3mm  u=3m/s  T=300K  P=101325Pa")
        r = compute(name, 8.0, 0.3, 3.0, 300.0, 101325.0, k_s=17.0)
        for k, v in r.items():
            print(f"  {k:10s} = {v:.6g}")
        L_domain = 0.10  # m
        dP = r['dP_per_L'] * L_domain
        print(f"  {'dP':10s} = {dP:.1f} Pa  (L_domain={L_domain}m)")
        print()
    print("=" * 60)
