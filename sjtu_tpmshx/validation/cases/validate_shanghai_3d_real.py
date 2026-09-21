"""Validate 16 Shanghai Electric water-air cases against their recorded inputs.

The default pipeline solves both fluids through the public module interface,
using the confirmed local water ports and current-model mass-flow conversion.
Without explicit grid options it uses the port/wall mesh in models.grid;
reported counts always come from the actual prepared result.

The kernel runner is a separate historical comparison with water temperature
prescribed from the measured outlet. Its scores are not production acceptance.
Historical migration scores and discussion remain at Git commit 51eb05388b6a.
See docs/tools.md and docs/history/README.md for current usage,
mesh evidence, numerical precision and experimental-error boundaries.
"""

from __future__ import annotations
import sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
# Targeted silencing only: deprecation-class noise is muted, but UserWarning
# stays VISIBLE — that class carries the degradation channel (flux-weight
# fallback "Q degraded", choke rescue, conservation-NaN notices). The old
# blanket filterwarnings('ignore') silenced exactly the messages this gate
# script exists to surface (blind-spot audit W4, 2026-07-07).
for _cat in (DeprecationWarning, PendingDeprecationWarning, FutureWarning):
    warnings.filterwarnings('ignore', category=_cat)

from sjtu_tpmshx.models.tpms_calc import (
    compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp,
    water_density, water_viscosity, water_conductivity, water_cp,
    nu_water_topo,
    P_atm,
)
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers.ltne_energy_3d import (solve_full_domain_3d, _inlet_transport_3d,
                                     energy_balance_3d, mass_balance_3d)
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.models.roughness import (f_enhancement, nu_extra_factor,
                                 apply_to_K_cF, resolve_mode_from_env)

R_AIR = 287.05

# ── Specimen geometry — canonical spec from validation/_case_sets ──
# (B1 1.3, 2026-06-12: replaces the old module-global monkey-patch. The
# globals below are kept as a
# read-only Shanghai view for printing and test back-compat (V.EPS);
# the runner itself threads `spec` explicitly.)
from sjtu_tpmshx.validation.harness._harness import load_cases_df
from sjtu_tpmshx.validation.harness._case_sets import shanghai_spec, SHANGHAI_XLSX

SPEC = shanghai_spec()
TPMS = SPEC.tpms
L_CELL = SPEC.L_cell_mm
T_WALL = SPEC.t_wall_mm
K_S = SPEC.k_s_W_mK
EPS = SPEC.eps; EPS_A = SPEC.eps_A; D_H = SPEC.D_h; R_H = SPEC.r_h; A0 = SPEC.A_0
L_DOM = SPEC.L_dom_m
H_DOM = SPEC.H_dom_m
LZ = SPEC.Lz_m  # arbitrary 3D depth (water uniform along z)
A_FLOW = SPEC.a_flow_m2

# Outer coupling parameters (mirror 2D)
# 2026-07-12 — 4→12, and the exit criterion below now tracks Ts as well as Ta.
# BOTH are PROVEN no-ops on this gate: re-running the 16 Shanghai cases with
# max_outer=12 (criterion unchanged), and again with the Ts-augmented criterion,
# reproduces 5.28% / 3.21% and every per-case value bit-identically, with the
# same per-case outer counts (3,3,4,4,4,4,4,4,4,4,4,3,3,3,3,3). So:
#   * the old cap of 4 was never binding — the loop already exits on the
#     criterion at 3–4, so the "fewer than 2D's 8 for 3D speed" rationale it
#     carried was buying nothing;
#   * the Ta-only criterion was not hiding a lagging Ts on THESE cases.
# Both are kept as hardening for the other specimens this runner drives (d76,
# future ones), where a slower solid field would otherwise exit early or a
# harder case would truncate silently — the failure mode the production
# pipeline's A2 fix (2026-07-06) closed by tracking all three fields.
# `Tb` is deliberately NOT tracked: this is the frozen-B runner
# (`Tb_prescribed` linear profile), so Tb does not evolve here.
MAX_OUTER = 12         # cap, not a budget — the loop exits on the criterion
OUTER_TOL = 0.5        # K
ALPHA_T = 0.6

# Water properties — canonical NIST-grade funcs from tpms_calc.
# 2026-05-13 audit fix: previously declared local water_rho/water_mu/water_cp
# with the **old exponential viscosity** mu = 1.79e-3 · exp(-0.035 · T_C)
# (40 °C off by -33 % vs NIST per memory `reference_water_viscosity_fix`).
# Replaced by the Vogel form already in tpms_calc.water_viscosity which
# matches NIST 0-90 °C to < 2 %. Aliases preserve call sites below.
water_rho = water_density
water_mu  = water_viscosity


def _compute_h_vA_field_3d(Ta_field, ucA_field, sA, *, spec):
    """Local single-stream Nu → h_vA field (mirror 2D _compute_h_vA_field).

    Uses post-refit single-stream convention: ε_f = ε/2, Re = ρ·u·D_h/μ,
    Nu = h·D_h/k_f via _nu_vec (Diamond F4-D / Gyroid F7).

    ``spec`` is REQUIRED (B1 1.3): the old default args (eps=EPS, …)
    froze Shanghai geometry at import time, which silently defeated the
    d76 module-global patch — the d76 gate ran with Gyroid eps/D_h here.

    Ta_field, ucA_field : (Nx, Ny, Nz) real-coord cell-centre
    sA: SIMPLESolver3D for fluid A (internal dims (Ny, Nx, Nz))
    Returns h_vA shape (Nx, Ny, Nz).
    """
    from sjtu_tpmshx.models.sigmoid_field import _nu_vec
    d_h = spec.D_h
    P_abs_sf = (sA.P_ref_abs + sA.P).transpose(1, 0, 2)  # (Nx, Ny, Nz)
    rho_loc = P_abs_sf / (R_AIR * Ta_field)
    mu_loc = air_viscosity(Ta_field)
    k_loc = air_conductivity(Ta_field)
    Re_loc = rho_loc * np.abs(ucA_field) * d_h / mu_loc
    Re_loc = np.clip(Re_loc, 1.0, None)
    L_mm_arr = np.full_like(Re_loc, spec.L_cell_mm)
    D_h_mm_arr = np.full_like(Re_loc, d_h * 1000.0)
    Nu_field = _nu_vec(spec.tpms, Re_loc, np.full_like(Re_loc, spec.eps),
                       L_mm_arr, D_h_mm_arr)
    H_sf = Nu_field * k_loc / d_h
    return spec.A_0 * H_sf


def _build_grid(Nx_u, Ny_u, Nz_u, wall_refine=False, spec=None):
    """Build (dx, dy, dz, Nx, Ny, Nz). Optional six-wall refinement."""
    spec = SPEC if spec is None else spec
    if wall_refine:
        from sjtu_tpmshx.models.grid import build_master_refined_grid_3d
        dx, dy, dz, Nx, Ny, Nz = build_master_refined_grid_3d(
            spec.L_dom_m, spec.H_dom_m, spec.Lz_m, Nx_u, Ny_u, Nz_u,
            n_refine=8, first_cell=0.02e-3)
    else:
        dx = np.full(Nx_u, spec.L_dom_m / Nx_u)
        dy = np.full(Ny_u, spec.H_dom_m / Ny_u)
        dz = np.full(Nz_u, spec.Lz_m / Nz_u)
        Nx, Ny, Nz = Nx_u, Ny_u, Nz_u
    return dx, dy, dz, Nx, Ny, Nz


def _build_inlet_profile(Nx_simA, Nz_simA, u_mean, kind='uniform', eta=0.0):
    """Build v_inlet_field (Nx_simA, Nz_simA) with mass-conserving profile.

    kind : 'uniform' → flat u_mean everywhere (baseline)
           'parabolic' → f(i, k) peaks at centre, normalised to ∫ f = 1
                         max = 1 + eta, min = 1 - eta*extrema_factor (mass conserved)
           'edge'     → f(i, k) higher near cross-stream edges (inverted parabola)
    eta : amplitude of deviation [0, 1]; 0 == uniform (any kind)
    """
    if eta <= 0.0 or kind == 'uniform':
        return np.full((Nx_simA, Nz_simA), u_mean, dtype=np.float64)

    # Normalized cross-stream coords [-0.5, 0.5]
    ii = (np.arange(Nx_simA) + 0.5) / Nx_simA - 0.5
    kk = (np.arange(Nz_simA) + 0.5) / Nz_simA - 0.5
    II, KK = np.meshgrid(ii, kk, indexing='ij')
    r2 = II ** 2 + KK ** 2   # [0, 0.5]

    if kind == 'parabolic':
        # f unnormalized: 1 + eta * (1 - 8 * r2); max at centre ≈ 1+eta, corners ≈ 1-eta
        f_raw = 1.0 + eta * (1.0 - 8.0 * r2)
    elif kind == 'edge':
        f_raw = 1.0 + eta * (8.0 * r2 - 1.0)
    else:
        raise ValueError(f"unknown profile kind {kind!r}")

    # A large eta drives the corner cells of the parabolic profile (and the
    # centre of the 'edge' profile) negative — f_raw = 1 - 3*eta < 0 for
    # eta > 1/3 — which would inject physical BACKFLOW at the inlet. Floor to a
    # small positive value, THEN renormalise so the area-mean still equals
    # u_mean (mass conserved, strictly positive). Audit: r2-val-02.
    f_raw = np.maximum(f_raw, 1e-3)
    f = f_raw / f_raw.mean()
    return (u_mean * f).astype(np.float64)


def _run_one_case(ci, df, Nx_u, Ny_u, Nz_u, wall_refine=False, verbose=False,
                    profile_kind='uniform', profile_eta=0.0,
                    max_outer=None, spec=None, disp_c=0.0):
    """Run one experimental case (index ci). Returns result dict.

    max_outer : override module-level MAX_OUTER (default None → use MAX_OUTER).
    spec      : SpecimenSpec (default None → Shanghai). B1 1.3 replaces the
                old module-global specimen monkey-patch —
                the locals unpacked below shadow the Shanghai module
                globals for the rest of this function body.
    """
    spec = SPEC if spec is None else spec
    TPMS, L_CELL, T_WALL, K_S = (spec.tpms, spec.L_cell_mm,
                                 spec.t_wall_mm, spec.k_s_W_mK)
    EPS, EPS_A, D_H, A0 = spec.eps, spec.eps_A, spec.D_h, spec.A_0
    L_DOM, H_DOM, LZ = spec.L_dom_m, spec.H_dom_m, spec.Lz_m
    A_FLOW = spec.a_flow_m2

    max_outer_local = MAX_OUTER if max_outer is None else int(max_outer)
    case = ci + 1

    # ── Air (Fluid A) ──
    m_air = float(df.iloc[ci, 5])
    T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
    P_Ain_g = float(df.iloc[ci, 30])
    P_Ain = P_atm + P_Ain_g
    rho_A = air_density(T_Ain_K, P_Ain)
    mu_A = air_viscosity(T_Ain_K)
    cp_A = air_cp(T_Ain_K)
    u_A = m_air / (rho_A * A_FLOW)

    # ── Water (Fluid B) ──
    m_water = float(df.iloc[ci, 7])
    T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
    T_Bout_C = float(df.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15
    rho_B = water_rho(T_Bin_K)

    # ── Experimental ──
    P_Aout_g = float(df.iloc[ci, 31])
    dP_A_exp = P_Ain_g - P_Aout_g
    Q_exp = float(df.iloc[ci, 33])

    # ── Grid (optional six-wall refinement) ──
    dx, dy, dz, Nx, Ny, Nz = _build_grid(Nx_u, Ny_u, Nz_u,
                                         wall_refine=wall_refine, spec=spec)

    eps_arr = np.full((Nx, Ny, Nz), EPS)
    K_ffA = np.full((Nx, Ny, Nz), EPS_A * air_conductivity(T_Ain_K))
    K_ffB = np.full((Nx, Ny, Nz), EPS_A * water_conductivity(T_Bin_K))  # ε_B = ε_A
    # B4 step-0 sensitivity knob (--disp-c): thermal-dispersion augmentation
    # K_disp = C·ρ·cp·|u|·D_h per side (same form as the tpms_calc C_DISP /
    # run_stack_3d disp_C_A hooks). Default 0.0 = production behaviour.
    if disp_c > 0.0:
        K_ffA += disp_c * rho_A * cp_A * u_A * D_H
        u_B_disp = m_water / (rho_B * A_FLOW)
        K_ffB += disp_c * rho_B * float(water_cp(T_Bin_K)) * u_B_disp * D_H
    # B2 (2026-07-06): χ_s from the unit-cell homogenization fit — matches
    # the production K_ss path (run_stack_3d / tpms_calc). Was the inline
    # (1−ε)·k_s, which silently bypassed even the legacy CHI_S constant.
    from sjtu_tpmshx.models.tpms_props import chi_s_eff as _chi_s_eff
    K_ss = np.full((Nx, Ny, Nz), _chi_s_eff(TPMS, EPS) * (1.0 - EPS) * K_S)

    # D-F coeffs from surrogate (per-stream void fraction ε_A)
    K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)
    # 2026-05-13 — roughness correction (Norris 1971 / Bhatti-Shah-Haaland) for
    # air side only. Env-controlled; baseline preserves prior behavior. Water
    # side (nu_water_topo) already embeds AM roughness, do NOT apply here.
    _rough_mode, _rough_eps = resolve_mode_from_env()
    if _rough_mode != 'baseline':
        Re_A_case = rho_A * abs(u_A) * D_H / mu_A
        _f_gain = f_enhancement(Re_A_case, _rough_mode,
                                  eps_um=_rough_eps, D_h_mm=D_H * 1000.0)
        K_pred, cF_pred = apply_to_K_cF(K_pred, cF_pred, _f_gain)
        if ci == 0 and verbose:
            print(f"  [roughness] mode={_rough_mode} eps={_rough_eps} μm  "
                  f"Re_A=case1={Re_A_case:.0f}  f_gain={_f_gain:.3f}")
    K_A_arr = np.full((Nx, Nz), K_pred)         # SIMPLE A: (Ny_sA=Nx, Nz)
    cF_A_arr = np.full((Nx, Nz), cF_pred)

    # Inlet h_vA (uniform at inlet temperature)
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA0 = A0 * r_A['H_sf']
    # 2026-05-13 — for bhatti_shah_1b, override the scalar ×1.28 baked into
    # tpms_compute() with Re-dep g_Nu(Re,ε)/1.28. Norris (1a) keeps Nu unchanged.
    if _rough_mode != 'baseline':
        _nu_extra = nu_extra_factor(rho_A * abs(u_A) * D_H / mu_A,
                                     _rough_mode, eps_um=_rough_eps,
                                     D_h_mm=D_H * 1000.0)
        h_vA0 *= _nu_extra
    h_vA_field = np.full((Nx, Ny, Nz), h_vA0)

    # Physical h_vB via nu_water_topo('Gyroid') gyroid water correlation
    # (Nu = 0.4445 · Re^0.6361 · Pr^(1/3), Re 100-50000).
    # 2026-05-13 audit fix: previously used `nu_from_Re` (air, ×1.28
    # roughness) which inflated water Nu by ~ Pr^(1/3) factor missing
    # and applied an air-only roughness multiplier; mirror the 2D
    # validate_shanghai_aligned.py nu_water_topo water path.
    mu_B0 = water_mu(T_Bin_K)
    cp_B0 = float(water_cp(T_Bin_K))
    k_B = float(water_conductivity(T_Bin_K))
    Pr_B = float(mu_B0 * cp_B0 / k_B)
    # m_water already read at line ~172 (Excel col 7); reuse, don't re-read.
    u_B = m_water / (rho_B * A_FLOW)
    Re_B = rho_B * abs(u_B) * D_H / mu_B0
    Nu_B = float(nu_water_topo('Gyroid', max(Re_B, 1.0), Pr_B))
    H_sf_B = Nu_B * k_B / D_H
    h_vB0 = A0 * H_sf_B
    h_vB_field = np.full((Nx, Ny, Nz), h_vB0)

    rho_cp_A = rho_A * cp_A
    rho_cp_B = rho_B * water_cp(T_Bin_K)

    # ── P_ref_abs 1D closed-form seed ──
    G_A = m_air / A_FLOW
    C_est = mu_A * G_A / K_pred + cF_pred * G_A * G_A
    P_out_sq = P_Ain ** 2 - 2.0 * R_AIR * T_Ain_K * C_est * L_DOM
    P_ref_A = float(np.sqrt(max(P_out_sq, 1.0e4)))

    # ── SIMPLE A (3D) ──
    # SIMPLE A internal: Nx_sA = Ny (cross-stream real y), Nz_sA = Nz.
    # v_inlet_field shape (Nx_sA, Nz_sA) = (Ny, Nz)
    v_inlet_A = _build_inlet_profile(Ny, Nz, u_A,
                                      kind=profile_kind, eta=profile_eta)
    sA = SIMPLESolver3D(Lx=H_DOM, Ly=L_DOM, Lz=LZ,
                        Nx=Ny, Ny=Nx, Nz=Nz,
                        rho=rho_A, mu=mu_A, T_in=T_Ain_K,
                        v_inlet=v_inlet_A,
                        eps=EPS, K_arr=K_A_arr, cF_arr=cF_A_arr,
                        P_ref_abs=P_ref_A,
                        fluid_type='ideal_gas')   # compressible air (P1b-d)
    # Wall-refined grids inject post-init (fluid A axis swap)
    if wall_refine:
        sA.dx = np.ascontiguousarray(dy, dtype=np.float64)
        sA.dy = np.ascontiguousarray(dx, dtype=np.float64)
        sA.dz = np.ascontiguousarray(dz, dtype=np.float64)
    # P2-a' + B: enable outlet_frac taper → activates wall_out penalty in
    # v-momentum kernel near outlet corners. Shanghai full-width air → corner
    # taper reduces artificial pressure spikes at wall-outlet corners.
    sA.apply_outlet_taper(n_taper=8, min_frac=0.2)
    sA.solve(max_iter=400, tol=1e-3, verbose=False)

    # Water side is frozen → no SIMPLE B
    ucB_real = np.zeros((Nx, Ny, Nz))
    vcB_real = np.zeros((Nx, Ny, Nz))
    wcB_real = np.zeros((Nx, Ny, Nz))

    # Tb_prescribed: linear along real y (water flows -y: inlet at j=Ny-1, outlet j=0)
    y_centres = (np.arange(Ny) + 0.5) * (H_DOM / Ny)
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centres / H_DOM)
    Tb_prescribed = np.broadcast_to(Tb_1d[None, :, None], (Nx, Ny, Nz)).copy()

    # ── Outer SIMPLE ↔ LTNE coupling loop ──
    Ta = Tb = Ts = None
    Ta_prev = None
    Ts_prev = None
    outer_iters = 0

    for outer in range(max_outer_local):
        outer_iters = outer + 1

        # Cell-centred air velocity: real (Nx, Ny, Nz)
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])   # (Ny, Nx, Nz)
        ucA_real = vA_cc.transpose(1, 0, 2).copy()         # (Nx, Ny, Nz)
        vcA_real = np.zeros((Nx, Ny, Nz))
        wcA_real = np.zeros((Nx, Ny, Nz))

        # Update h_vA from local T/v/P after first iter
        if Ta is not None:
            h_vA_field = _compute_h_vA_field_3d(Ta, ucA_real, sA, spec=spec)

        # 2026-05-19 ε contract (Option A): pass FULL porosity ε_full.
        # The kernel internally does eps_f = 0.5*epsilon (single halving →
        # ε_A = ε_full/2). Pre-halving here double-halved to ε_full/4.
        # K_ffA/K_ffB are built with EPS_A (= ε_full/2) — correct, untouched.
        Ta, Tb, Ts = solve_full_domain_3d(
            L_DOM, H_DOM, LZ, Nx, Ny, Nz, T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss,
            h_vA_field, h_vB_field,
            rho_cp_A, rho_cp_B, eps_arr,
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            dir_A=0, dir_B=3,
            inlet_flux_A=_inlet_transport_3d(
                (sA.v.transpose(1, 0, 2), sA.u.transpose(1, 0, 2),
                 sA.w.transpose(1, 0, 2)),
                0.5*eps_arr, sA.rho_field.transpose(1, 0, 2), cp_A, dx, dy, dz, 0),
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            Tb_prescribed=Tb_prescribed,
            max_iter=50000, tol=1e-6,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=0.7)

        # Outer exit criterion. Ts joined Ta on 2026-07-12: the production
        # pipeline's A2 fix (2026-07-06) had already widened its own gate from
        # ('Ta',) to ('Ta','Tb','Ts') because "the old ('Ta',)-only criterion
        # let Tb/Ts drift unmonitored" (run_stack_3d.py) — this runner was never
        # brought along. Tb is NOT tracked here and must not be: this is the
        # frozen-B runner, Tb is prescribed and does not evolve.
        # Measured: on the 16 Shanghai cases this changes nothing (identical
        # per-case outer counts and identical 5.28%/3.21%) — Ts is already
        # inside tol whenever Ta is. It is defence for the harder specimens.
        if Ta_prev is not None:
            _dTa = float(np.max(np.abs(Ta - Ta_prev)))
            _dTs = (float(np.max(np.abs(Ts - Ts_prev)))
                    if Ts_prev is not None else float('inf'))
            dT_max = max(_dTa, _dTs)
            if dT_max < OUTER_TOL:
                break
        Ta_prev = Ta.copy()
        Ts_prev = Ts.copy()

        # Update SIMPLE A T_field/rho/mu/mu_eff from new Ta.
        # Critical: SIMPLE _update_density() uses sA.T_field — must propagate
        # Ta here, otherwise ρ drifts back to T_in inside the inner SIMPLE loop
        # (causing ρ to reflect only P drop, missing the T-cooling densification).
        Ta_sA = Ta.transpose(1, 0, 2).copy()
        sA.update_T_field(Ta_sA)
        P_abs_sA = sA.P_ref_abs + sA.P
        rho_A_new = P_abs_sA / (R_AIR * Ta_sA)
        mu_A_new = air_viscosity(Ta_sA)
        if outer > 0:
            sA.rho_field = np.ascontiguousarray(
                ALPHA_T * rho_A_new + (1.0 - ALPHA_T) * sA.rho_field, dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(
                ALPHA_T * mu_A_new + (1.0 - ALPHA_T) * sA.mu_field, dtype=np.float64)
        else:
            sA.rho_field = np.ascontiguousarray(rho_A_new, dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(mu_A_new, dtype=np.float64)
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / sA.eps, dtype=np.float64)

        # Refresh P_ref_abs from updated mean T
        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / K_pred + cF_pred * G_A * G_A
        P_out_sq_new = P_Ain ** 2 - 2.0 * R_AIR * T_avg * C_avg * L_DOM
        sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))

        # Re-solve SIMPLE A
        sA.solve(max_iter=400, tol=1e-3, verbose=False)

    # ── Extract Q and dP ──
    #   2026-05-19 (Codex #4): mass-flux-weighted outlet T (down-weights
    #   stagnant corner cells) instead of plain arithmetic mean. Air is
    #   near-plug so ρ≈const across the outlet plane → ρ·|u| weighting ≡
    #   |u| weighting; weight by |ucA_real| at the real-x outlet plane.
    #   Both reductions reported so the bias is visible.
    #   Codex follow-up: recompute the outlet |u| weight from the FINAL
    #   sA.v (post last sA.solve), not the loop-top `ucA_real` which is one
    #   SIMPLE-solve stale when the outer loop exits by max-iter rather than
    #   the converged-break. Same (Ny,Nx,Nz)->(Nx,Ny,Nz) transform as L281.
    _vA_cc_f = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])      # (Ny,Nx,Nz)
    _ucA_final = _vA_cc_f.transpose(1, 0, 2)                 # (Nx,Ny,Nz)
    _Ta_out = Ta[-1, :, :]                    # real-x outlet plane
    _w = np.abs(_ucA_final[-1, :, :])         # FINAL air outlet |u|
    _wsum = float(_w.sum())
    T_A_out_mw = (float((_Ta_out * _w).sum() / _wsum)
                  if _wsum > 1e-30 else float(_Ta_out.mean()))
    T_A_out_am = float(_Ta_out.mean())        # legacy arithmetic mean
    T_A_out_sim = T_A_out_mw                  # primary: mass-flux weighted
    Q_sim = m_air * cp_A * (T_Ain_K - T_A_out_sim)
    Q_sim_am = m_air * cp_A * (T_Ain_K - T_A_out_am)
    Q_mw_am_rel = (abs(Q_sim - Q_sim_am) / abs(Q_sim_am) * 100.0
                   if Q_sim_am != 0 else float('nan'))

    #   dP from SIMPLE A's converged P field; P2-a' uses pipe-weighted mean
    #   with numerical f*g*A weights to down-weight corner cells (mirror 2D).
    #   This historical report functional is not a geometric area average.
    # 2nd-order: extrapolate P to the inlet/outlet FACES (removes the O(h)
    # cell-centre half-cell offset that capped the boundary dP at ~1st order).
    dP_A_sim = SIMPLESolver3D.extract_dP_face_extrap(sA, numerical_taper=True)

    err_dP = (dP_A_sim - dP_A_exp) / dP_A_exp * 100 if dP_A_exp != 0 else float('nan')
    err_Q = (Q_sim - Q_exp) / Q_exp * 100 if Q_exp != 0 else float('nan')

    # ── Conservation diagnostics (短期 #4) ──
    # Energy balance on solid: Q_sA + Q_sB should → 0 in steady state.
    # Shanghai water side frozen (Tb_prescribed), h_vB=1e10 → solid balance may be
    # dominated by Q_sA (air → solid). Q_sA should ≈ -Q_sim (heat air gives to solid).
    ebal = energy_balance_3d(Ta, Tb, Ts, h_vA_field, h_vB_field, dx, dy, dz)
    e_rel = abs(ebal['Q_net']) / (abs(ebal['Q_sA']) + abs(ebal['Q_sB']) + 1e-30)

    # Mass balance on fluid A (SIMPLE A): inlet v[:, 0, :] to outlet v[:, -1, :].
    # SIMPLE A streamwise axis = SIMPLE internal y → dir_code=2 (+y).
    # Note: mass_balance_3d expects (dy, dx, dz) ordering — pass SIMPLE A's own grid
    mbal_A = mass_balance_3d(sA.u, sA.v, sA.w, sA.rho_field,
                              sA.dy, sA.dx, sA.dz, dir_code=2)

    return {
        'case': case, 'u_air': u_A, 'u_water': m_water / (rho_B * A_FLOW),
        'T_Ain_C': T_Ain_C, 'T_Bin_C': T_Bin_C,
        'dP_exp': dP_A_exp, 'dP_sim': dP_A_sim, 'err_dP%': err_dP,
        'Q_exp': Q_exp, 'Q_sim': Q_sim, 'err_Q%': err_Q,
        'Q_sim_am': Q_sim_am, 'Q_mw_am_rel%': Q_mw_am_rel,
        'outer_iters': outer_iters,
        'Qs_A': ebal['Q_sA'], 'Qs_B': ebal['Q_sB'],
        'Q_net_rel': e_rel,
        'mass_rel_A': mbal_A['rel'],
        # Codex #6: surface the SIMPLE P_abs-clip engagement (was silent).
        # `pressure_clip_hits` is the LIFETIME count over the reused solver
        # (accumulates across every outer iter / warm restart) — informational.
        # Validity must judge the CONVERGED field, not the lifetime counter:
        # a single transient early-iteration clip that the solve then heals
        # would otherwise permanently (and wrongly) mark the case suspect and
        # drop it from the RMSRE (audit: clip-hits-monotonic-validity-poison).
        'pressure_clip_hits': int(getattr(sA, '_p_clip_hits', 0)),
        'pressure_state_valid': bool(
            ((sA.P_ref_abs + sA.P) >= 1.0e3).all()
            and ((sA.P_ref_abs + sA.P) <= 10.0e6).all()),
    }


def _pipeline_config(ci, df, Nx_u, Ny_u, Nz_u, spec=None, max_outer=None, wall_refine=False,
                     port_wall_refine=False):
    from sjtu_tpmshx.domain.compute_config import SolverConfig
    from sjtu_tpmshx.validation.harness._case_sets import shanghai_pipeline_config
    return shanghai_pipeline_config(ci, df,
        SolverConfig(Nx=Nx_u, Ny=Ny_u, Nz=Nz_u,
                     max_outer_ltne=None if max_outer is None else int(max_outer)),
        wall_refine=wall_refine, port_wall_refine=port_wall_refine, spec=spec)


def _run_one_case_pipeline(ci, df, Nx_u, Ny_u, Nz_u, spec=None,
                           max_outer=None, wall_refine=False, port_wall_refine=False):
    """B2 2.1d — production-path runner: ComputeConfig → Pipeline3D
    (the exact stack the GUI drives: _run_3d_stack with a REAL
    incompressible water-B SIMPLE solve).

    Deliberately a DIFFERENT physics path from :func:`_run_one_case`
    (kernel-direct, frozen-B ``Tb_prescribed`` linear profile).

    HISTORY (2026-07-13 update — this paragraph used to say "the gate runner
    stays kernel-direct … do not silently swap the gate", contradicting the
    module docstring after 2026-07-12): the gate DID swap to this pipeline
    runner, deliberately and loudly (module docstring lists the three
    reasons; RMSRE 5.28/3.21 → 4.93/2.12, then 4.88 under F2). The rule the
    old wording was protecting still holds in its real form: never swap a
    gate SILENTLY. ``--runner kernel`` reproduces the frozen-B era numbers.
    """
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
    cc = _pipeline_config(ci, df, Nx_u, Ny_u, Nz_u, spec, max_outer, wall_refine,
                          port_wall_refine)
    case = ci + 1
    u_A, u_B = cc.fluid_A.u_mps, cc.fluid_B.u_mps
    dP_A_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])
    Q_exp = float(df.iloc[ci, 33])
    result = Pipeline3D(cc).run()
    dP_sim = result.dP_A_Pa
    Q_sim = result.Q_W
    err_dP = ((dP_sim - dP_A_exp) / dP_A_exp * 100
              if dP_A_exp != 0 else float('nan'))
    err_Q = (Q_sim - Q_exp) / Q_exp * 100 if Q_exp != 0 else float('nan')
    # Read the REAL pipeline diagnostics. These two were hard-coded 0/1, which
    # made `valid_mask` below (and therefore the pressure-invalid exclusion the
    # RMSRE口径 depends on) a permanent no-op on this branch — the exact
    # "silent exclusion" the main() comment forbids. envelope_valid is the
    # post-solve gate verdict (Mach + positive-pressure, models/envelope.py);
    # p_clip_hits is the lifetime P_abs-clip counter summed over both sides.
    _diag = result.diagnostics or {}
    _env_valid = bool(_diag.get('envelope_valid', True))
    _clip_hits = int(_diag.get('p_clip_hits', 0))
    # The ACTUAL outer-iteration count, not the cap. `diagnostics['_max_outer']`
    # is the CAP (`_result['_max_outer'] = _max_outer` in run_stack_3d); reading
    # it here made the printed `outer=` track --max-outer instead of the work
    # actually done (a cap of 12 and a cap of 30 both printed their own value
    # while returning bit-identical fields — the tell that it was echoing the
    # cap). The real count is on convergence_detail.
    _cdet = _diag.get('convergence_detail') or {}
    _outer_done = int(_cdet.get('outer_iters', 0)) or -1
    _outer_conv = bool(_cdet.get('outer_converged', False))
    # A non-converged SIMPLE solve is not a pressure-validity failure, but it
    # must not vanish either — surface it the way the kernel branch surfaces
    # its own outer-loop count.
    if result.warnings:
        print(f"  [case {case}] pipeline warnings: "
              f"{'; '.join(str(w) for w in result.warnings)}")
    return {
        'case': case, 'u_air': u_A, 'u_water': u_B,
        'dP_exp': dP_A_exp, 'dP_sim': dP_sim, 'err_dP%': err_dP,
        'Q_exp': Q_exp, 'Q_sim': Q_sim, 'err_Q%': err_Q,
        'Q_native': float(result.Q_W), 'Q_native_unit': 'W',
        **{'grid_n' + axis: len(result.fields['d' + axis]) for axis in 'xyz'},
        'Q_sim_am': float('nan'), 'Q_mw_am_rel%': float('nan'),
        'outer_iters': _outer_done,
        'outer_converged': _outer_conv,
        'Qs_A': float('nan'), 'Qs_B': float('nan'),
        'Q_net_rel': float('nan'), 'mass_rel_A': float('nan'),
        'pressure_clip_hits': _clip_hits,
        'pressure_state_valid': int(_env_valid),
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    # DEFAULT SWITCHED kernel → pipeline (2026-07-12). See the module docstring
    # for the full rationale and evidence; in short: the pipeline runner SOLVES
    # the water side, is more accurate against experiment, converges, and is the
    # code path production actually runs. `kernel` stays available as the
    # frozen-B reference.
    ap.add_argument('--runner', choices=['pipeline', 'kernel'],
                    default='pipeline',
                    help="pipeline (DEFAULT) solves both fluids on the prepared grid; "
                         "kernel prescribes water temperature from the measured outlet "
                         "and is a separate historical comparison")
    ap.add_argument('--wall-refine', action='store_true', help='Enable 6-wall refinement')
    ap.add_argument('--port-wall-refine', action='store_true',
                    help='Use port/wall grading; counts include all refinement cells')
    ap.add_argument('--disp-c', type=float, default=None,
                    help='B4 thermal-dispersion coefficient C '
                         '(K_ff += C*rho*cp*|u|*D_h per side; 0 = off)')
    ap.add_argument('--nx', type=int)
    ap.add_argument('--ny', type=int)
    ap.add_argument('--nz', type=int)
    ap.add_argument('--cases', type=int, default=16, help='Run first N cases (default 16)')
    ap.add_argument('--suffix', type=str, default='', help='CSV output suffix')
    ap.add_argument('--profile', choices=['uniform', 'parabolic', 'edge'],
                    default=None, help='Kernel-only inlet profile shape (default uniform)')
    ap.add_argument('--eta', type=float, default=None,
                    help='Profile amplitude [0,1]; 0=uniform baseline')
    ap.add_argument('--max-outer', type=int, default=MAX_OUTER,
                    help=f'Outer SIMPLE<->LTNE coupling iters (default {MAX_OUTER})')
    # Hard gate (blind-spot audit T1, 2026-07-07): this script is the
    # docs/architecture.md designates this gate for surrogate-backend changes,
    # yet it always
    # exited 0 — headline accuracy could degrade with every automatic check
    # green. Thresholds are deliberately generous (current Nz=3 gate values
    # are RMSRE_dP 4.88% / RMSRE_Q 2.12% — production pipeline, F2 default;
    # the frozen-B kernel era's 5.28/3.21 stays reproducible via --runner
    # kernel; the per-case grid-convergence dP floor is ~10%): they catch
    # the historical failure class (order-of-magnitude surrogate
    # regressions), not tuning noise.
    ap.add_argument('--gate-dp', type=float, default=12.0,
                    help='FAIL (exit 1) if RMSRE_dP exceeds this %% (default 12)')
    ap.add_argument('--gate-q', type=float, default=6.0,
                    help='FAIL (exit 1) if RMSRE_Q exceeds this %% (default 6)')
    ap.add_argument('--no-gate', action='store_true',
                    help='Report only; always exit 0 (legacy behaviour)')
    args = ap.parse_args(argv)
    if args.port_wall_refine and (args.wall_refine or args.runner == 'kernel'):
        ap.error('--port-wall-refine requires the pipeline and cannot combine with --wall-refine')
    explicit_grid = any(n is not None for n in (args.nx, args.ny, args.nz))
    port_refine = args.port_wall_refine or (
        args.runner == 'pipeline' and not explicit_grid and not args.wall_refine)
    from sjtu_tpmshx.models.grid import SHANGHAI_GRID_3D
    defaults = SHANGHAI_GRID_3D if port_refine else (20, 10, 3)
    Nx_u, Ny_u, Nz_u = (default if value is None else value
                        for value, default in zip((args.nx, args.ny, args.nz), defaults))
    if args.runner == 'pipeline' and any(value is not None for value in
                                         (args.profile, args.eta, args.disp_c)):
        ap.error('--profile, --eta and --disp-c are kernel-only options; the production pipeline does not support them')
    args.profile = 'uniform' if args.profile is None else args.profile
    args.eta = 0.0 if args.eta is None else args.eta
    args.disp_c = 0.0 if args.disp_c is None else args.disp_c

    df = load_cases_df(SHANGHAI_XLSX)

    print(f"Shanghai 3D validation (Gyroid L={L_CELL} t={T_WALL} eps={EPS:.4f})")
    print(f"Domain: {L_DOM*1000:.0f}x{H_DOM*1000:.0f}x{LZ*1000:.0f} mm")
    print(f"Requested grid: {Nx_u} x {Ny_u} x {Nz_u}; "
          f"wall_refine={args.wall_refine}, port_wall_refine={port_refine}")
    if args.runner == 'kernel':
        _dx, _dy, _dz, Nx, Ny, Nz = _build_grid(Nx_u, Ny_u, Nz_u, wall_refine=args.wall_refine)
        print(f"Kernel grid: {Nx} x {Ny} x {Nz}")
    print(f"Requested outer budget: max_outer={args.max_outer}\n")

    print(f"Inlet profile: kind={args.profile}, eta={args.eta:.2f}")
    print(f"Runner: {args.runner}"
          + ("  (production Pipeline3D, both fluids solved)"
             if args.runner == 'pipeline' else "") + "\n")
    results = []
    for ci in range(args.cases):
        if args.runner == 'pipeline':
            r = _run_one_case_pipeline(ci, df, Nx_u, Ny_u, Nz_u,
                                       max_outer=args.max_outer, wall_refine=args.wall_refine,
                                       port_wall_refine=port_refine)
            print(f"Actual prepared grid: {r['grid_nx']} x {r['grid_ny']} x {r['grid_nz']}")
        else:
            r = _run_one_case(ci, df, Nx_u, Ny_u, Nz_u,
                              wall_refine=args.wall_refine,
                              profile_kind=args.profile,
                              profile_eta=args.eta,
                              max_outer=args.max_outer,
                              disp_c=args.disp_c)
        results.append(r)
        # `outer=N` is the count of outer iterations ACTUALLY run. `!` marks a
        # run that exhausted the cap without meeting the coupling criterion —
        # i.e. a TRUNCATED result. (Only the pipeline runner reports this; the
        # kernel runner breaks on its own criterion and has no separate flag.)
        _oc = r.get('outer_converged')
        _omark = '' if _oc is None or _oc else '!'
        print(f"Case {r['case']:2d}: dP {r['dP_exp']:.0f}/{r['dP_sim']:.0f} "
              f"({r['err_dP%']:+.1f}%)  Q {r['Q_exp']:.0f}/{r['Q_sim']:.0f} "
              f"({r['err_Q%']:+.1f}%)  outer={r['outer_iters']}{_omark}  "
              f"[Qnet_rel={r['Q_net_rel']:.2e} mA_rel={r['mass_rel_A']:.2e}]")

    # Summary statistics
    # Codex #6 follow-up: RMSRE口径 must exclude pressure-invalid cases
    # (compressible P_abs-clip fired → solution leaned on the clamp, the
    # reported dP/Q is not a faithful prediction). Count + list them so the
    # exclusion is auditable, never silent.
    valid_mask = np.array([bool(r['pressure_state_valid']) for r in results])
    n_total = len(results)
    n_invalid = int((~valid_mask).sum())
    invalid_cases = [results[i]['case'] for i in range(n_total) if not valid_mask[i]]

    err_dP_all = np.array([r['err_dP%'] for r in results])
    err_Q_all = np.array([r['err_Q%'] for r in results])
    # Re>600 filter via u_air (matches 2D convention)

    if valid_mask.any():
        err_dP = err_dP_all[valid_mask]
        err_Q = err_Q_all[valid_mask]
    else:
        # Degenerate: every case clipped. Fall back to all so the run still
        # prints a number, but the n_invalid banner makes it un-trustable.
        err_dP, err_Q = err_dP_all, err_Q_all

    from sjtu_tpmshx.validation.harness._metrics import rmsre_from_pct
    rmsre_dP = rmsre_from_pct(err_dP)
    rmsre_Q = rmsre_from_pct(err_Q)
    max_err_Q = float(np.max(np.abs(err_Q)))
    max_err_dP = float(np.max(np.abs(err_dP)))

    print()
    print("=" * 70)
    print(f"  cases         : {n_total} total, {n_total - n_invalid} valid, "
          f"{n_invalid} pressure-INVALID (clip fired)")
    if n_invalid:
        print(f"  invalid cases : {invalid_cases}  (EXCLUDED from RMSRE below)")
    # 2D baseline = validate_shanghai_aligned.py headline. Updated 2026-07-13:
    # the 2D gate is now the production Pipeline2D with solved water + F2
    # (8.62% / 2.49%, ledger C8/C9); the older kernel-runner numbers
    # (8.35/2.51 after the 2026-06-25 mass-flux inlet port) stay reproducible
    # there via --runner kernel.
    print(f"  RMSRE_dP      : {rmsre_dP:.2f}%  (2D baseline 8.62%)  "
          f"[over {len(err_dP)} valid]")
    print(f"  max|err_dP|   : {max_err_dP:.2f}%")
    print(f"  RMSRE_Q       : {rmsre_Q:.2f}%  (2D baseline 2.49%)  "
          f"[over {len(err_Q)} valid]")
    print(f"  max|err_Q|    : {max_err_Q:.2f}%")
    print("=" * 70)

    # Save CSV (pipeline runner auto-suffixes — must never overwrite the
    # kernel gate baseline CSV)
    # The DEFAULT runner writes the canonical filename; the non-default one is
    # marked. This flipped with the default on 2026-07-12 (was `_pipeline` when
    # pipeline was the opt-in) so that `shanghai_3d_baseline*.csv` keeps meaning
    # "the gate's output" rather than silently becoming the legacy runner's.
    _suffix = args.suffix + ('_kernel' if args.runner == 'kernel' else '')
    csv_name = f"shanghai_3d_baseline{_suffix}.csv"
    out_path = Path(__file__).parent.parent / csv_name
    pd.DataFrame(results).to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\nSaved: {out_path}")

    if args.no_gate:
        return 0
    gate_fail = (rmsre_dP > args.gate_dp) or (rmsre_Q > args.gate_q)
    verdict = 'FAIL' if gate_fail else 'PASS'
    print(f"\nGATE {verdict}: RMSRE_dP {rmsre_dP:.2f}% (limit {args.gate_dp:.1f}%), "
          f"RMSRE_Q {rmsre_Q:.2f}% (limit {args.gate_q:.1f}%)")
    return 1 if gate_fail else 0


if __name__ == '__main__':
    sys.exit(main())
