"""pipelines/flux_3d.py — 3D face-flux / outlet postprocessing + roughness.

Flux/outlet postprocessing + roughness application, moved verbatim from
stages_3d.py (openspec split-pipelines, 2026-07-03); behavior bit-identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.solvers.roughness import (f_enhancement, nu_extra_factor,
                                 resolve_mode_from_env)


# ⚠ 2026-05-14 (revised): `norris_1a` is now a no-op for friction (f×1.0,
# alias of `baseline`). The ×1.28 Nu factor in tpms_calc air-Gyroid is the
# only roughness compensation; c_F was trained on real SLM dP so the friction
# side already encodes Sa. See `solvers/roughness.py` module docstring for
# the audit history (1.46 → 1.28 → 1.0).
#
# Naming retained for back-compat with existing config files / BO defaults
# (optimization/evaluator_3d.py also defaults to 'norris_1a'). 2D path in
# run_calculation.py defaults to 'baseline' — label asymmetry is cosmetic
# only (verified 2026-05-28 audit C2 follow-up). Stale earlier comment had
# claimed "norris_1a closes 44.74 %→24.15 %"; that data is from the pre-
# revert multiplier-bearing version and is obsolete post-2026-05-14.
_UI_ROUGH_MODE_DEFAULT = 'norris_1a'


def _resolve_ui_roughness() -> tuple[str, float]:
    """Read mode + ε from env; default to norris_1a so UI matches BO."""
    return resolve_mode_from_env(default=_UI_ROUGH_MODE_DEFAULT)


# ---------------------------------------------------------------------------
# Face-flux helpers (module-level so they can be unit-tested independently)
# ---------------------------------------------------------------------------
def _face_flux_weights(solver: SIMPLESolver3D, dir_code: int,
                       face: str = 'real_outlet',
                       eps_mode: str = 'ltne',
                       chi_face: np.ndarray | None = None,
                       eps_f_per_side: float | None = None,
                       eps_side_override: float | None = None) -> np.ndarray:
    """Unified face-flux weight array for T_out, m_dot, Q_enth.

    Parameters
    ----------
    solver : SIMPLESolver3D
    dir_code : int — 0=+x,1=-x,2=+y,3=-y,4=+z,5=-z
    face : 'real_inlet' or 'real_outlet'
    eps_mode : 'ltne' (× eps_f) or 'physical' (no eps_f)
    chi_face : optional 2D array — χ_B at this face for ghost suppression
    eps_f_per_side : optional scalar fallback when solver has no eps_field

    Returns
    -------
    w : 2D ndarray — face flux weights [kg/s] or eps_f·[kg/s].
        sum(w) = effective mass flow through this face.
    """
    # approach-(a): the solver is direction-agnostic — it always injects at
    # j=0 (inlet_frac) and exhausts at j=-1 (outlet_frac). The reverse-dir
    # spatial flip lives in the velocity transforms, NOT here, so the real
    # inlet maps to solver j=0 and the real outlet to j=-1 for ALL dirs.
    # (Was: an is_reverse branch swapping faces/masks — that was approach-(b)
    # and double-counted the flip, mirroring the reverse accounting.)
    if face == 'real_outlet':
        v_face = solver.v[:, -1, :]
        rho_face = solver.rho_field[:, -1, :]
        face_idx = -1
    else:  # real_inlet
        v_face = solver.v[:, 0, :]
        rho_face = solver.rho_field[:, 0, :]
        face_idx = 0
    dx_sol = solver.dx[:, None]; dz_sol = solver.dz[None, :]
    w = rho_face * np.abs(v_face) * dx_sol * dz_sol
    if eps_mode == 'ltne':
        if eps_side_override is not None:
            # Asymmetric (offset-isosurface δ): per-side single-channel void
            # fraction ε_side directly (already split, NOT halved). Takes
            # precedence over the symmetric 0.5·eps_field path so m_dot ≡
            # ∫ ε_side·ρ·u·dA matches the per-side advective mass flow.
            w = w * float(eps_side_override)
        else:
            eps_full = getattr(solver, 'eps_field', None)
            if eps_full is not None:
                w = w * (0.5 * np.asarray(eps_full[:, face_idx, :],
                                          dtype=np.float64))
            else:
                if eps_f_per_side is None:
                    raise ValueError(
                        "_face_flux_weights: eps_mode='ltne' requires either "
                        "solver.eps_field or explicit eps_f_per_side")
                w = w * float(eps_f_per_side)
    # Face-average velocity already contains the open-area fraction.
    if chi_face is not None:
        w = w * np.asarray(chi_face, dtype=np.float64)
    return w


def _mass_weighted_T_out(T_face: np.ndarray, solver: SIMPLESolver3D,
                          dir_code: int, eps_f_scalar: float | None,
                          chi_face: np.ndarray | None = None,
                          eps_side_override: float | None = None) -> float:
    """Mass-flux-weighted T average at the REAL outlet face.
    Delegates to _face_flux_weights for consistent weighting.

    Falls back to naive face mean when the effective mass flow drops below
    1e-30 (e.g. no active outlet, fully blocked face). Mass-flux weights
    naturally suppress stagnant warm cells where ρ·|v| ≈ 0.
    """
    try:
        w = _face_flux_weights(solver, dir_code, face='real_outlet',
                               eps_mode='ltne', chi_face=chi_face,
                               eps_f_per_side=eps_f_scalar,
                               eps_side_override=eps_side_override)
        tot = float(np.sum(w))
        if tot < 1e-30:
            return float(np.mean(T_face))
        return float(np.sum(T_face * w) / tot)
    except Exception as _e:
        # except-audit 2026-07-03: the fallback stays (a T_out is better
        # than a crash mid-solve) but it is no longer silent — an exception
        # here means _face_flux_weights itself broke (real bug), and the
        # naive mean quietly changes T_out/Q.
        import warnings as _w
        _w.warn(f"_mass_weighted_T_out: flux weighting failed ({_e!r}); "
                f"falling back to naive face mean — T_out/Q degraded.")
        return float(np.mean(T_face))


def _mass_weighted_h_out(T_face: np.ndarray, P_ref: float,
                          enthalpy_fn: Callable[[np.ndarray, float], np.ndarray],
                          solver: SIMPLESolver3D, dir_code: int,
                          eps_f_scalar: float | None,
                          chi_face: np.ndarray | None = None,
                          eps_side_override: float | None = None) -> float:
    """Mass-flux-weighted mean ENTHALPY at the real outlet face: ⟨h(T)⟩_w.

    For a strongly nonlinear h(T) (sCO2 across the pseudocritical cp spike)
    ⟨h(T)⟩ ≠ h(⟨T⟩) (Jensen). The 3D sCO2 duty must use the mass-flux-weighted
    mean of the per-cell enthalpy, NOT the enthalpy of the mean outlet
    temperature — otherwise the reported Q (and Q_AB_imbalance_rel built from
    it) is biased by several percent exactly where the enthalpy form was meant
    to be exact (audit 2026-06-28 D2). Weights mirror ``_mass_weighted_T_out``
    so ṁ and ⟨h⟩ stay consistent.
    """
    h_face = np.asarray(enthalpy_fn(np.asarray(T_face, dtype=np.float64), P_ref),
                        dtype=np.float64)
    try:
        w = _face_flux_weights(solver, dir_code, face='real_outlet',
                               eps_mode='ltne', chi_face=chi_face,
                               eps_f_per_side=eps_f_scalar,
                               eps_side_override=eps_side_override)
        tot = float(np.sum(w))
        if tot < 1e-30:
            return float(np.mean(h_face))
        return float(np.sum(h_face * w) / tot)
    except Exception as _e:
        # except-audit 2026-07-03: same rationale as _mass_weighted_T_out —
        # keep the fallback, surface the degradation.
        import warnings as _w
        _w.warn(f"_mass_weighted_h_out: flux weighting failed ({_e!r}); "
                f"falling back to naive face mean — Q (sCO2 duty) degraded.")
        return float(np.mean(h_face))


from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field  # noqa: F401


# ── Direction → axis single source ──────────────────────────────────────────
# dir_code: 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z (matches the 2D _dir_int convention).
# These helpers are the ONE place the dir→axis/index mapping is encoded; every
# face-slice / BC-mask / streamwise-component dispatch derives from them, so a
# direction cannot go inconsistent across call sites (the failure mode the
# reverse-dir saga kept reintroducing). Forward dirs (even) inject at stream
# index 0 and exhaust at -1; reverse dirs (odd) mirror that. 2026-06-09 A3.
def _simple_mass_flow(solver: SIMPLESolver3D, dir_code: int,
                      eps_f_per_side: float | None = None,
                      eps_side_override: float | None = None) -> float:
    """LTNE-effective m_dot at REAL inlet face via _face_flux_weights."""
    try:
        w = _face_flux_weights(solver, dir_code, face='real_inlet',
                               eps_mode='ltne',
                               eps_f_per_side=eps_f_per_side,
                               eps_side_override=eps_side_override)
        return float(np.sum(w))
    except Exception as _e:
        # except-audit 2026-07-03: a silent 0.0 here zeroes the duty of the
        # side downstream (ṁ=0 → Q=0) with no trace. Keep the fallback,
        # make the failure visible.
        import warnings as _w
        _w.warn(f"_simple_mass_flow: flux weighting failed ({_e!r}); "
                f"returning m_dot=0 — downstream Q for this side is wrong.")
        return 0.0


def _apply_roughness_KcF(K_arr: np.ndarray, cF_arr: np.ndarray,
                         fluid_type: str, rho: float, mu: float, u: float,
                         D_h_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Scale K/cF arrays by f_enhancement; skip fluids whose closure already
    embeds AM roughness (water: the per-topology water fit (`nu_water_topo`))
    — registry flag, B1 1.1."""
    if fluid_props.get(fluid_type).embeds_roughness:
        return K_arr, cF_arr
    mode, eps_um = _resolve_ui_roughness()
    if mode == 'baseline':
        return K_arr, cF_arr
    Re_loc = float(rho * abs(u) * D_h_m / max(mu, 1.0e-12))
    f_gain = float(f_enhancement(Re_loc, mode,
                                  eps_um=eps_um, D_h_mm=D_h_m * 1000.0))
    return (K_arr / f_gain).astype(np.float64, copy=False), \
           (cF_arr * f_gain).astype(np.float64, copy=False)


def _apply_roughness_h_v(h_v_field: np.ndarray, fluid_type: str,
                         rho: float, mu: float, u: float,
                         D_h_m: float) -> np.ndarray:
    """Multiply h_v by nu_extra_factor; skip roughness-embedding fluids
    (registry flag, B1 1.1). Norris 1a returns 1.0 (Nu unchanged ×1.28),
    so this is a no-op for the default mode; only bhatti_shah_1b actually
    rescales Nu."""
    if fluid_props.get(fluid_type).embeds_roughness:
        return h_v_field
    mode, eps_um = _resolve_ui_roughness()
    if mode == 'baseline':
        return h_v_field
    Re_loc = float(rho * abs(u) * D_h_m / max(mu, 1.0e-12))
    nu_extra = float(nu_extra_factor(Re_loc, mode,
                                      eps_um=eps_um, D_h_mm=D_h_m * 1000.0))
    if nu_extra == 1.0:
        return h_v_field
    return (h_v_field * nu_extra).astype(np.float64, copy=False)
