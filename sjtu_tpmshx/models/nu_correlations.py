"""Nu correlations — single source of truth for scalar + vector paths.

Replaces the previous lock-step pattern where Nu coefficients lived in BOTH
``tpms_calc._nu_diamond`` / ``_nu_gyroid`` (scalar path) AND
``sigmoid_field._nu_vec`` (vector path). After 2026-05-28 refactor (per
audit finding H1), both call sites import from here, so refitting Nu
requires editing exactly ``NU_COEFFS`` below.

API
---
``nu_from_Re(tpms, Re, eps_f, L_mm, D_h_mm)``       — scalar path, air
``nu_vec(tpms, Re_arr, L_mm, D_h_mm, *, Re_floor=10)`` — vector path, air
``nu_water_topo(tpms, Re, Pr_water)`` — PRODUCTION water (per-topology direct
                                       water-CFD fit, WATER_NU_COEFFS)
``nu_water_from_Re(tpms, Re, eps_f, L_mm, D_h_mm, Pr_water)`` — legacy Pr-sub
                                       water (cross-check / test-only)

Roughness factor
----------------
``NU_ROUGHNESS_FACTOR = 1.28`` — SLM Sa≈31 µm roughness enhancement.
Multiplies the smooth-wall Nu uniformly. See
``vault/reports/method/2026-04-28-nu-correlation-v4-3p-PL-CN.md`` for the
experimental derivation (φ_rough = ⟨Q_exp / Q_DB(Re)⟩ across 0°/30°/45°/
60°/90° print angles ≈ 1.28).

Form
----
3p pure power-law (refit 2026-04-28 on 试验记录表_整理版_v3.1.xlsx)::

    Nu_smooth = c · Pr^(1/3) · Re^a · (D_h/L)^d
    Nu        = NU_ROUGHNESS_FACTOR · Nu_smooth

Convention
----------
``Re = ρ·u·D_h / μ``      (D_h-based, single-stream u)
``eps_f = ε_full / 2``    (single-stream porosity — currently unused in Nu,
                          kept for API back-compat)
``Nu = h · D_h / k_f``    (standard, smooth wall)
"""
from __future__ import annotations

import os
import warnings
from sjtu_tpmshx.domain.run_warnings import record_range, record_warning
import numpy as np

# ── Constants ────────────────────────────────────────────────────────────

Pr_AIR = 0.72
NU_ROUGHNESS_FACTOR = 1.28           # SLM Sa≈31 µm enhancement (φ_rough)
NU_RE_FIT_RANGE = (400.0, 16000.0)   # Re fit window for extrap warnings
NU_LAM_FLOOR = 4.36                  # laminar Hagen-Poiseuille limit — floor
                                     # for local-Re h_v paths (wall cells with
                                     # u→0 must not extrapolate Nu→0). Single
                                     # source for the 2D and 3D h_v builders.

# 3p PL coefficients (refit 2026-04-28; user-locked).
# Refitting Nu = edit this dict, nothing else.
NU_COEFFS = {
    'Diamond': {'c': 0.0944, 'a': 0.8273, 'd': 0.226},
    'Gyroid':  {'c': 0.126,  'a': 0.7898, 'd': 0.2409},
}

# Module-level mutable: one-shot extrap warning per (tpms, side).
# Set is a session-scoped registry; clear by importer if tests need fresh
# warnings (rare — most tests should suppress via warnings.catch_warnings).
_EXTRAP_WARNED: set[tuple[str, str]] = set()


def reset_extrap_warn_registry() -> None:
    """Re-arm the standalone air Nu registry; pipeline runs own their records."""
    _EXTRAP_WARNED.clear()


# ── Internal ─────────────────────────────────────────────────────────────

def _smooth_nu(tpms_type, Re, L_mm, D_h_mm, *, Pr=Pr_AIR):
    """Smooth-wall Nu (no roughness factor). Vector-friendly: accepts scalar
    or ndarray Re / L_mm / D_h_mm via numpy broadcasting."""
    c = NU_COEFFS[tpms_type]
    return c['c'] * Pr ** (1/3) * Re ** c['a'] * (D_h_mm / L_mm) ** c['d']


def _warn_extrap(tpms_type, Re_min, Re_max, raw):
    """One-shot warning per (tpms, 'lo'|'hi') when Re leaves the fit window."""
    if record_range(('nu', 'air', tpms_type), raw, NU_RE_FIT_RANGE,
                    label=f'[Nu extrap] {tpms_type}', quantity='Re', unit='-'):
        return
    lo, hi = NU_RE_FIT_RANGE
    for side, oob in (('lo', Re_min < lo), ('hi', Re_max > hi)):
        if not oob:
            continue
        message = (
            f"[Nu extrap] {tpms_type}: Re=[{Re_min:.0f},{Re_max:.0f}] "
            f"outside fit window [{lo:.0f},{hi:.0f}]. "
            "Suppressing further warnings for this (tpms, side).")
        if (tpms_type, side) not in _EXTRAP_WARNED:
            _EXTRAP_WARNED.add((tpms_type, side))
            warnings.warn(message, stacklevel=3)


# ── Public API ───────────────────────────────────────────────────────────

def nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, *, Pr=Pr_AIR):
    """Nu (air, smooth × roughness). ``eps_f`` kept for back-compat
    signature; currently unused in the Nu formula.

    Accepts scalar OR ndarray ``Re``. The scalar branch is byte-identical to
    the historical implementation (``float(Re)`` into ``_smooth_nu``); the
    array branch (2026-06-09) forwards the array straight through — same
    element-wise formula ``_smooth_nu`` already serves to ``nu_vec`` — so a
    per-cell loop and a single vectorised call give identical results. NOTE:
    no ``Re_floor`` is applied here (unlike ``nu_vec``'s floor=10); callers
    that need a floor apply their own (e.g. the LTNE h_v path floors at 1.0)."""
    del eps_f
    Re_arr = np.asarray(Re, dtype=np.float64)
    if Re_arr.ndim == 0:
        _warn_extrap(tpms_type, float(Re_arr), float(Re_arr), Re_arr)
        return NU_ROUGHNESS_FACTOR * _smooth_nu(
            tpms_type, float(Re_arr), L_mm, D_h_mm, Pr=Pr)
    if Re_arr.size:
        _warn_extrap(tpms_type, float(Re_arr.min()), float(Re_arr.max()), Re)
    return NU_ROUGHNESS_FACTOR * _smooth_nu(
        tpms_type, Re_arr, L_mm, D_h_mm, Pr=Pr)


def nu_vec(tpms_type, Re, L_mm, D_h_mm, *, Re_floor=10.0, Pr=Pr_AIR):
    """Vectorised Nu. ``Re_floor=10`` matches legacy
    ``sigmoid_field._nu_vec`` behaviour (prevents Re^a blow-up at u→0).
    L_mm / D_h_mm accept scalar or ndarray broadcastable to ``Re``."""
    Re_arr = np.maximum(np.asarray(Re, dtype=np.float64), Re_floor)
    if Re_arr.size:
        _warn_extrap(tpms_type, float(Re_arr.min()), float(Re_arr.max()), Re)
    return NU_ROUGHNESS_FACTOR * _smooth_nu(
        tpms_type, Re_arr, L_mm, D_h_mm, Pr=Pr)


def nu_water_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr_water):
    """Water-side Nu via Pr-substitution onto the air-fit correlation
    (Reynolds analogy, Dittus-Boelter / Sieder-Tate basis).

    Legacy / cross-check only — NOT the production water path. Production
    water Nu now uses ``nu_water_topo`` (per-topology direct water-CFD fit,
    ``WATER_NU_COEFFS``). This function and ``nu_water_gyroid_yan6`` (Yan
    [6] 2024) are retained for cross-check / test only.
    """
    return nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm) \
           * (Pr_water / Pr_AIR) ** (1/3)


# ── Topology-specific DIRECT water fits (design-tool lineage) ────────
# Direct per-topology fits Nu = c·Re^a·Pr^(1/3) on water unit-cell CFD.
# REFIT 2026-07-23 on the corrected upload (data/raw_data/Water-CFD/
# 水数值模拟数据.xlsx, 40 geometries D+G L∈[4,8]×t∈[0.3,0.6], ~46 Re each,
# Re 94–50624), loaded via df_surrogate/load_water_cfd.py (repo Dh, entrance
# period dropped → Nu_dev target). Replaces the 2026-06-12 coeffs (fit on the
# retired water-cfd-raw.xlsx, kept in git). Adding a (D_h/L)^d geometry term
# does NOT help water (d≈0 Diamond / +0.08 Gyroid, RMSRE unchanged) — the
# 2-parameter form is kept. Accuracy: RMSRE ~10%, LOGO (leave-one-geometry-out)
# medAPE Diamond 6.8% / Gyroid 8.2%. D_7_3/4/5 share the sCO2 flow-data quirk
# but Nu is velocity-free so they stay in the fit.
WATER_NU_RE_RANGE = (90.0, 51000.0)
WATER_NU_COEFFS = {
    'Diamond': {'c': 0.3201, 'a': 0.6679},
    'Gyroid':  {'c': 0.3941, 'a': 0.6435},
}
# Retired 2026-06-12 coeffs (old data), for reference:
#   Diamond c=0.3427 a=0.6626;  Gyroid c=0.4445 a=0.6361.

# One-shot extrapolation warning per side for the water Nu fit (robustness
# 2026-06-25): the air path already warns outside its window; the water path
# previously extrapolated silently.
_WATER_NU_WARNED: set[str] = set()


def _warn_water_nu(Re_min, Re_max, tpms_type, raw):
    if record_range(('nu', 'water', tpms_type), raw, WATER_NU_RE_RANGE,
                    label=f'[water Nu extrap] {tpms_type}', quantity='Re', unit='-'):
        return
    lo, hi = WATER_NU_RE_RANGE
    for side, oob in (('lo', Re_min < lo), ('hi', Re_max > hi)):
        if not oob:
            continue
        message = (f"[water Nu extrap] Re=[{Re_min:.0f},{Re_max:.0f}] outside "
                   f"water-CFD fit window [{lo:.0f},{hi:.0f}].")
        if side not in _WATER_NU_WARNED:
            _WATER_NU_WARNED.add(side)
            warnings.warn(message, stacklevel=3)


def nu_water_topo(tpms_type, Re, Pr_water):
    """Topology-specific direct water Nu = c·Re^a·Pr^(1/3) (table above).
    ``np.maximum(Re, 1.0)`` floor (array-safe; identical to the design-tool
    fit's ``max(Re, 1.0)`` for scalar Re, but also works on per-cell arrays
    when the solver routes its vectorised water path through here)."""
    Re_safe = np.maximum(Re, 1.0)             # original expression (unchanged)
    _Re_arr = np.asarray(Re_safe, dtype=np.float64)
    if _Re_arr.size:
        _warn_water_nu(float(_Re_arr.min()), float(_Re_arr.max()), tpms_type, Re)
    co = WATER_NU_COEFFS[tpms_type]
    return co['c'] * Re_safe ** co['a'] * Pr_water ** (1 / 3)


# ── Supercritical CO2 DIRECT fit (smooth-wall unit-cell CFD) ──
# REFIT 2026-07-26 on the Gyroid L=8 completion — Diamond 20 + Gyroid **20**
# geometries (Gyroid was 17). The 07-26 upload is PURELY ADDITIVE: all 4400
# prior Gyroid core rows survive bit-identically (max rel dev 3e-16), and the
# 1000 new rows are all at L=8 — G_8_3 went 80→270 cases (it had been only 7%
# sampled) and G_8_4/5/6 went 0→270 (they had been ABSENT, i.e. RBF-
# extrapolated). Diamond is untouched and its coefficients are unchanged to
# the stored precision — that is the control for this re-baseline.
# Gyroid moved c 0.201101→0.192994, a 0.720625→0.722221, d −0.013529→−0.044313:
# the geometry exponent d is what a filled-in L=8 column should move most.
#
# Prior lineage — REFIT 2026-07-23 on the corrected upload, Diamond 20 +
# Gyroid 17 geometries L∈[4,8]×t∈[0.3,0.6] mm (was 15+12 on L∈[4,7]); the earlier
# export's mesh Dh ran ~6% high and D_7_6/G_7_6 were RBF-EXTRAPOLATED, so the
# 2026-07-15 coeffs below (kept in git) fit a partly-wrong geometry envelope.
# The new data corrects Dh (agrees with tpms_calc to <0.4%) and gives REAL CFD
# at D_7_6/G_7_6, which is why the geometry exponent d moved most
# (Diamond −0.434→−0.282, Gyroid −0.109→−0.014). P∈{8,10,12,15} MPa on the
# pseudocritical line, Twall = Tref+50K, RANS, no gravity. Fitted on period-2/3
# segments with LOCAL bulk properties (CoolProp at (P, T_b)); V0b pure-bulk
# form (no wall-ratio — ΔT≡50K makes those exponents non-general, user
# decision 2026-07-15). Fit + validation: validation/sco2_cfd/fit_nu_sco2.py,
# reports/sco2_cfd/, ledger SCO2-CFD.
#   ⚠ Diamond D_7_3/4/5 carry a flow-data (mdot/Um) inconsistency, but Nu is
#     velocity-free so their Nu is sound and they are kept in the fit; see
#     df_surrogate/load_sco2_cfd.py module doc.
#
# Form  Nu = c·Re^a·Pr_b^(1/3)·(D_h/L)^d      [bulk properties at (T_b, P)]
# Accuracy (2026-07-26): far-critical RMSRE Diamond 9.3% / Gyroid 7.4%,
# all-data ~19% both; LOGO (leave-one-geometry-out) medAPE Diamond 9.5% /
# Gyroid 7.9% (was 8.4% on 17 geometries — it IMPROVED while the fit task got
# harder by 3 geometries, which is the sign the L=8 column was the weak spot).
#
# ⚠ SMOOTH WALL — SLM roughness deliberately NOT included. With D_7_6/G_7_6
# now REAL CFD, the experiment/CFD ratio is a CLEAN roughness factor (no more
# geometry-extrapolation contamination): γ ≈ 1.80 (Diamond) / 1.13 (Gyroid) on
# the D-7-6/G-7-6 rough SLM specimens. Re-anchor if the print process changes.
# This lineage REPLACED the D-7-6 single-geometry EXPERIMENTAL fit
# (0.28·Re^0.75·Pr^⅓, rough, Diamond 7/0.6 only) on 2026-07-15; that fit could
# not extrapolate in geometry (kept only in projects/703-sCO2-D76/).
#
# VALIDITY (per-cell medAPE, see validation/sco2_cfd/README.md):
#   usable    P ≥ 10 MPa and T_b ≥ T_pc(P) − 2 K  →  4–12 %
#   FAILURE   8 MPa near-critical (T_b−T_pc ∈ [−2,+5] K): 18–61 %
#   FAILURE   liquid-like side T_b ≤ T_pc − 5 K at P ≤ 10 MPa: up to ~27 %
# Re window = local-property Re_b coverage of the fit data.
SCO2_NU_RE_RANGE = (2600.0, 128000.0)
SCO2_NU_COEFFS = {
    'Diamond': {'c': 0.184809, 'a': 0.707421, 'd': -0.281792},
    'Gyroid':  {'c': 0.192994, 'a': 0.722221, 'd': -0.044313},
}
# Retired Gyroid coeffs from the 2026-07-23 fit (17 geometries, L=8 column
# only 7% sampled at t=0.3 and absent at t=0.4/0.5/0.6), for reference:
#            Gyroid  c=0.201101 a=0.720625 d=-0.013529.
# Retired 2026-07-15 coeffs (old data, wrong-Dh + extrapolated 7/0.6), for
# reference: Diamond c=0.166714 a=0.705490 d=-0.434198;
#            Gyroid  c=0.199133 a=0.719463 d=-0.109010.

_SCO2_NU_WARNED: set[str] = set()


def record_raw_nu_range(fluid, tpms_type, Re):
    """Observe an upstream Re before its floor, separately from Nu source inputs."""
    bounds = {'air': NU_RE_FIT_RANGE, 'water': WATER_NU_RE_RANGE,
              'sco2': SCO2_NU_RE_RANGE}[fluid]
    record_range(('nu_raw', fluid, tpms_type), Re, bounds,
                 label=f'[{fluid} Nu raw] {tpms_type}', quantity='Re', unit='-')


def _warn_sco2_nu(Re_min, Re_max, tpms_type, raw):
    if record_range(('nu', 'sco2', tpms_type), raw, SCO2_NU_RE_RANGE,
                    label=f'[sCO2 Nu extrap] {tpms_type}', quantity='Re', unit='-'):
        return
    lo, hi = SCO2_NU_RE_RANGE
    for side, oob in (('lo', Re_min < lo), ('hi', Re_max > hi)):
        if not oob:
            continue
        message = (f"[sCO2 Nu extrap] Re=[{Re_min:.0f},{Re_max:.0f}] outside "
                   f"sCO2-CFD fit window [{lo:.0f},{hi:.0f}].")
        if side not in _SCO2_NU_WARNED:
            _SCO2_NU_WARNED.add(side)
            warnings.warn(message, stacklevel=3)


def warn_sco2_nu_evidence(*, side, stage, tpms_type, L_mm, t_mm, P_in):
    # Source: SCO2_NU_COEFFS lineage/VALIDITY above and
    # validation/sco2_cfd/README.md, Nu validity and campaign pressure levels.
    if np.ndim(L_mm) > 0:
        geometry = (f'zoned L=[{np.min(L_mm):g},{np.max(L_mm):g}] mm, '
                    f't=[{np.min(t_mm):g},{np.max(t_mm):g}] mm')
    else:
        geometry = f'L={L_mm:g} mm, t={t_mm:g} mm'
    message = (
        f'[sCO2 Nu evidence] {stage}, side={side}, {tpms_type}, '
        f'{geometry}; Nu uses scalar P_in={P_in:g} Pa. '
        'Joint qualification remains unverified: the old CFD evidence uses '
        'heating at Twall=Tref+50 K and period-2/3 bulk properties. '
        'The reported subset requires P>=10 MPa AND Tb>=Tpc(P)-2 K within '
        'that campaign; Tpc, joint Pr/P/T coverage, actual wall temperature '
        'and heating/cooling qualification are not established here. '
        'Pressure or Re-window membership alone is not a PASS.')
    if P_in < 10e6:
        message += ' P_in<10 MPa does not meet the subset necessary pressure condition.'
    if P_in > 15e6:
        message += ' P_in>15 MPa exceeds the old campaign pressure envelope (8/10/12/15 MPa).'
    if not record_warning(('nu-evidence', 'sco2', side, stage), message):
        warnings.warn(message, stacklevel=2)


def nu_sco2_topo(tpms_type, Re, Pr_sco2, L_mm, D_h_mm):
    """Supercritical-CO2 Nu = c·Re^a·Pr^(1/3)·(D_h/L)^d (smooth wall; table
    above). Array-safe ``np.maximum(Re, 1.0)`` floor, mirroring
    ``nu_water_topo``. ``L_mm`` / ``D_h_mm`` feed the geometry term — the
    ratio is unit-agnostic but both must be in the SAME unit (convention:
    mm, matching the FluidModel.nu signature).

    Raises NotImplementedError for topologies without an sCO2 CFD fit.
    Pr is the BULK Prandtl at (T_b, P) — no wall-property ratio by design.
    Validity/failure bands: see SCO2_NU_COEFFS block comment.

    STAYS SMOOTH-WALL by contract. Experimental γ_Nu below is retained for
    historical validation only; sCO2 V1 production calls this function
    directly."""
    if tpms_type not in SCO2_NU_COEFFS:
        raise NotImplementedError(
            f"sCO2 Nu fit only available for {sorted(SCO2_NU_COEFFS)} "
            f"(2026-07 sCO2 CFD campaign); {tpms_type!r} unsupported.")
    Re_safe = np.maximum(Re, 1.0)
    _Re_arr = np.asarray(Re_safe, dtype=np.float64)
    if _Re_arr.size:
        _warn_sco2_nu(float(_Re_arr.min()), float(_Re_arr.max()), tpms_type, Re)
    co = SCO2_NU_COEFFS[tpms_type]
    return (co['c'] * Re_safe ** co['a'] * Pr_sco2 ** (1 / 3)
            * (D_h_mm / L_mm) ** co['d'])


def nu_sco2_selected(tpms_type, Re, Pr, L_mm, D_h_mm, *, settings):
    """Apply the shared effective multiplier before the caller's existing floor."""
    settings.validate()
    base = nu_sco2_topo(tpms_type, Re, Pr, L_mm, D_h_mm)
    if settings.mode == 'cfd_smooth':
        return base
    alpha = settings.alpha_D if tpms_type == 'Diamond' else settings.alpha_G
    return alpha * base


def sco2_nu_metadata(settings):
    """Actual selected model, without attributing inactive parameters to CFD."""
    if settings is None:
        from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
        settings = Sco2NuConfig()
    settings.validate()
    info = {'mode': settings.mode, 'model_version': 'sco2-cfd-common-multiplier-v1'}
    if settings.mode == 'experimental':
        info.update(alpha_D=settings.alpha_D, alpha_G=settings.alpha_G,
                    parameter_version=settings.parameter_version, source=settings.source,
                    applicability=settings.applicability,
                    interpretation='Frozen-model effective heat transfer; not measured local Nu')
    else:
        info.update(model_version='sco2-cfd-smooth', coefficients={name: dict(values) for name, values in SCO2_NU_COEFFS.items()})
    return info


def sco2_nu_notices(config):
    """Source scope remains distinct from a successful numerical solve."""
    if getattr(config, 'sco2_nu', None) is None or config.sco2_nu.mode != 'experimental':
        return []
    settings = config.sco2_nu
    if 'sco2' not in (config.fluid_A.type, config.fluid_B.type):
        return []
    settings.validate()
    message = (f"sCO2 Nu experimental effective correction [{settings.parameter_version}]; "
               f"source: {settings.source}; declared applicability: {settings.applicability}. "
               "This selection does not certify local Nu or whole-unit validation.")
    g = config.geometry
    if g.L_cell_mm != 7.0 or g.t_wall_mm != 0.6 or g.delta_levelset != 0.0 or config.zones.enabled:
        message += ' Experimental geometry extrapolation beyond the uniform 7 mm / 0.6 mm specimen.'
    return [message]


# ── sCO2 experimental heat-transfer correction γ_Nu (D-2sc-3, 2026-07-22) ──
# HX-level amplitude on top of the smooth-wall fit above, anchored on the
# D-7-6 / G-7-6 sCO2 experiments (both sides pooled — the subst.v2 use-card's
# "换热修正 · 两侧合用" row; anchored-fit convention: exponent a fixed at the
# CFD value, γ = c_exp/c_cfd_eff). Amplitude-ONLY by measurement: the fitted
# Re-slopes are ±0.02 (flat — unlike γ_f's significant hot-side slope).
# Applied per-element inside the experimental Re window; outside, the element
# keeps the smooth value (never extrapolate an experimental anchor) with a
# one-shot warning. Kill switch TPMSHX_SCO2_GAMMA_NU=0 → pre-anchor smooth.
# REFROZEN 2026-07-23 against the refit SCO2_NU_COEFFS (corrected upload,
# REAL CFD at D_7_6/G_7_6): both anchors are now CLEAN roughness factors —
# the former Gyroid caveat (γ conflated with the G L=7 RBF extrapolation)
# is RESOLVED by the backfill. Exp windows unchanged (same experiment set).
# REFROZEN 2026-07-26 (Gyroid only) against the Gyroid L=8 completion —
# the smooth base moved, so the base-relative anchor had to follow. Diamond is
# bit-identical (its CFD did not change), which is the control. Gyroid moved
# only γ +0.33% / σln +0.39%; the EXPERIMENT is untouched (same 80 points,
# same Re window), so this is purely the smooth denominator being better
# resolved at L=8. Retired 2026-07-23 Gyroid values, for reference:
#   Gyroid  γ=1.1253904125495358 σln=0.03404943924575467.
# Retired 2026-07-22 values (old wrong-Dh/extrapolated base), for reference:
#   Diamond γ=1.7557581458289075 σln=0.1284497503774956;
#   Gyroid  γ=1.0743811537767434 σln=0.033961111486825596.
# Uncertainty: pointwise ln-residual σln frozen for downstream UQ.
# REFROZEN 2026-09-06 with user approval on coolprop-heos-gauge-101325-v1:
# corrected absolute pressure and measured endpoint-Q reference; same pooled
# Diamond52/Gyroid80 sides, anchored-amplitude method and smooth CFD base.
# Re windows follow that same set's corrected reduction. Historical validation
# only; current solver Nu and the former parameters in Git (0f21d97) are intact.
GAMMA_NU_SCO2 = {
    'Diamond': {'gamma': 1.8090199573275527,
                're_lo': 8939.609650115377, 're_hi': 35098.141764163316,
                'sig_ln': 0.1283563539008298, 'n': 52},
    'Gyroid':  {'gamma': 1.1303616727629382,
                're_lo': 10620.777013615836, 're_hi': 48860.02078334884,
                'sig_ln': 0.03428100882817446, 'n': 80},
}

_GAMMA_NU_WARNED: set[tuple[str, str]] = set()


def gamma_nu_sco2(tpms_type, Re):
    """Historical validation-only γ_Nu for ``nu_sco2_topo``.

    Returns an array shaped like ``Re`` (or a scalar for scalar input):
    γ inside the experimental window, 1.0 outside / for unanchored
    topologies. The sCO2 V1 solver does not call this helper."""
    if os.environ.get('TPMSHX_SCO2_GAMMA_NU', '1') == '0':
        return np.ones_like(np.asarray(Re, dtype=np.float64)) \
            if np.ndim(Re) else 1.0
    p = GAMMA_NU_SCO2.get(tpms_type)
    if p is None:
        key = (str(tpms_type), 'topo')
        if key not in _GAMMA_NU_WARNED:
            _GAMMA_NU_WARNED.add(key)
            warnings.warn(
                f"[sCO2 gamma_Nu] no experimental anchor for topology "
                f"{tpms_type!r} — smooth-wall Nu kept.", stacklevel=3)
        return np.ones_like(np.asarray(Re, dtype=np.float64)) \
            if np.ndim(Re) else 1.0
    Re_arr = np.asarray(Re, dtype=np.float64)
    inside = (Re_arr >= p['re_lo']) & (Re_arr <= p['re_hi'])
    if Re_arr.size and not bool(np.all(inside)):
        key = (str(tpms_type), 'window')
        if key not in _GAMMA_NU_WARNED:
            _GAMMA_NU_WARNED.add(key)
            warnings.warn(
                f"[sCO2 gamma_Nu] {tpms_type}: part of the Re field "
                f"(range [{float(Re_arr.min()):,.0f}, "
                f"{float(Re_arr.max()):,.0f}]) lies outside the experimental "
                f"window [{p['re_lo']:,.0f}, {p['re_hi']:,.0f}] — those "
                f"cells keep the SMOOTH-WALL Nu (the anchor never "
                f"extrapolates).", stacklevel=3)
    out = np.where(inside, p['gamma'], 1.0)
    return out if np.ndim(Re) else float(out)


def reset_gamma_nu_warn_registry():
    """Test hook (mirrors _SCO2_NU_WARNED / sco2_gamma_f conventions)."""
    _GAMMA_NU_WARNED.clear()
