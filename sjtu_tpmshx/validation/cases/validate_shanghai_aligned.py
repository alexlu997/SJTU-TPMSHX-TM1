"""validate_shanghai_aligned.py — Shanghai 2D validation gate.

Two runners, selected by ``--runner``:

  ``pipeline``  (DEFAULT since 2026-07-12)
      The production stack — ``controllers.compute_pipeline.Pipeline2D``, the
      same code the GUI drives and the optimizer's Pareto re-solve goes through —
      with a REAL SIMPLE-B water solve and a real water energy solve.

  ``kernel``    (legacy; kept so the old numbers reproduce exactly)
      A hand-built kernel-direct loop with the water side FROZEN.

WHY THE DEFAULT SWITCHED. The legacy runner had three independent problems, any
one of which disqualifies it as a gate:

1. **It was fed part of the answer.** ``Tb_prescribed`` is a linear profile built
   from the MEASURED water inlet AND OUTLET temperatures (Excel cols 24, 25). Q
   is ``Σ h_vB·(Ts − Tb)·dV``, so Tb sets the driving force directly — and the
   measured outlet temperature already encodes the true duty through the water
   enthalpy balance. The gate was scoring the solver on a number it had handed it.

2. **The water side had no velocity field at all.** ``ucB_real`` / ``vcB_real``
   were literally ``np.zeros(...)``. SIMPLE-B was never even built, let alone
   solved — water-side advection did not exist.

3. **It validated a code path production never runs.** The loop called
   ``SIMPLESolver(...).solve(max_iter=3000, tol=1e-4)`` directly; ``Pipeline2D``
   and ``pipelines.stages_2d`` appear nowhere in it. So a convergence defect in
   the PRODUCTION path could not be caught here — and measurably was not: forcing
   the SIMPLE exit open moves this gate's dP RMSRE by 0.03 pp (8.76 → 8.79 %),
   while the same forcing on the production Pipeline2D moves dP by up to **3.4 %**
   (ledger C9 — the 2D tol-tautology finding; C8 is the pressure-anchor bug
   found in the same campaign — 2026-07-12).

The pipeline runner fixes all three: it PREDICTS the water outlet temperature
instead of being handed it, it solves the water momentum field, and it exercises
the shipped code.

Legacy numbers reproduce exactly with ``--runner kernel``.
"""
from __future__ import annotations
import os, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]   # .../sjtu_tpmshx
_DATA = _ROOT.parent / 'data'                 # .../SJTU-TPMSHX/data

sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from sjtu_tpmshx.models.tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_cp, P_atm,
    water_density, water_viscosity, water_conductivity, water_cp,
    nu_water_topo,
)
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain
from sjtu_tpmshx.solvers.df_projection import build_master_refined_grid, extract_dP_from_simple
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.solvers.roughness import (f_enhancement, nu_extra_factor,
                                 resolve_mode_from_env)

# 2026-05-13 — roughness mode from env (baseline / norris_1a / bhatti_shah_1b).
_ROUGH_MODE, _ROUGH_EPS = resolve_mode_from_env()
print(f"[Shanghai aligned] roughness mode = {_ROUGH_MODE}"
      f"{f' (ε={_ROUGH_EPS} μm)' if _ROUGH_MODE == 'bhatti_shah_1b' else ''}")

R_AIR_VAL = 287.05

# ── Match the production compute-path constants (pipelines/stages_2d.py) ──
# Bumped 5→10 on 2026-05-14 to align with the then run_calculation.py (Phase
# bump 2026-05-09). Old baseline at 5 sometimes left B residual ~3e-3
# instead of converging to 1e-3; unifying keeps validation in lock-step
# with production.
_MAX_COUPLING = 10
_COUPLING_TOL = 0.01
_DT_TOL_K     = 1.0
_ALPHA_COUP   = 0.7

# ── Geometry (Shanghai Electric Gyroid prototype) ──
# Canonical params from configs/shanghai_baseline.json (Item 3 / AR8, 2026-05-28).
from sjtu_tpmshx.configs import load_shanghai_baseline
from sjtu_tpmshx.domain.compute_config import ComputeConfig
# Audit C3 (2026-05-28): sourced through ComputeConfig.
_SH = load_shanghai_baseline()
_SH_CC = ComputeConfig.from_dict(_SH)
TPMS = _SH_CC.geometry.tpms
L_CELL = _SH_CC.geometry.L_cell_mm
T_WALL = _SH_CC.geometry.t_wall_mm
K_S = _SH_CC.geometry.k_s_W_mK
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; EPS_A = g['epsilon_A']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = _SH_CC.geometry.L_dom_m
H_DOM = _SH_CC.geometry.H_dom_m
N_UNITS = _SH['domain']['n_units']
A_FLOW_PER_UNIT = _SH['domain']['a_flow_per_unit_m2']
A_FLOW = N_UNITS * A_FLOW_PER_UNIT

from sjtu_tpmshx.models.tpms_calc import adaptive_grid
N_X_USER, N_Y_USER = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)
DX_REFINED, DY_REFINED, N_X, N_Y = build_master_refined_grid(
    L_DOM, H_DOM, N_X_USER, N_Y_USER, n_refine=8, first_cell=0.02e-3, growth=1.8)

print(f"[Shanghai aligned] Geometry: {TPMS} L={L_CELL} t={T_WALL} "
      f"eps={EPS:.4f} D_h={D_H*1000:.3f}mm")
print(f"[Shanghai aligned] Domain {L_DOM*1000:.0f}x{H_DOM*1000:.0f}mm, "
      f"Grid {N_X}x{N_Y} (refined)")
K0, cF0 = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)
print(f"[Shanghai aligned] D-F ConstDF-v1: K={K0:.3e} m², c_F={cF0:.3e} 1/m\n")


def _apply_rough_to_simple(s, Re_case):
    """Scale SIMPLE internal K, cF arrays by f_enhancement for the current
    case Re. Norris 1a: 1.0 (alias of baseline since 2026-05-14 revert
    — c_F already encodes 试验记录表 SLM friction). Bhatti-Shah 1b: Re-dep
    Haaland. Baseline: no-op."""
    if _ROUGH_MODE == 'baseline':
        return
    f_gain = f_enhancement(Re_case, _ROUGH_MODE,
                            eps_um=_ROUGH_EPS, D_h_mm=D_H * 1000.0)
    s._K_arr = (s._K_arr / f_gain).astype(np.float64, copy=False)
    s._cF_arr = (s._cF_arr * f_gain).astype(np.float64, copy=False)


def _run_simple_A(rho_field, mu_field, u_in, T_in, P_ref_abs_seed,
                    Re_case=None, T_field=None, rho_inlet_ref=None):
    """Build + solve SIMPLE for Fluid A (+x, full-width).

    Mirrors run_calculation.py._run_simple (closure) but with Shanghai-
    specific axis mapping baked in: Fluid A flows along real +x, so
    SIMPLE's streamwise axis (y) maps to real x, and SIMPLE's cross-
    stream axis (x) maps to real y.

    T_field (optional, 2026-05-14 fix): solver-coord 2D T_field to
    propagate the energy-equation T into SIMPLE before the first
    `_update_density` call. Without this, the solver's internal
    self.T_field stays at scalar T_in across every outer iter, so
    the `rho_field` argument is overwritten by ρ(P, T_in) on the
    first inner iter — breaking compressible T-ρ coupling.
    """
    s = SIMPLESolver(
        H_DOM, L_DOM, N_Y, N_X,
        TPMS, L_CELL, T_WALL,
        EPS, R_H,
        rho_field, mu_field, T_in,
        0.0, H_DOM, u_in,
        outlet_lo=0.0, outlet_hi=H_DOM,
        P_ref_abs=P_ref_abs_seed,
        rho_inlet_ref=rho_inlet_ref,
        wall_refine=False,
    )
    # A/B toggle: TPMSHX_2D_MASSFLUX=0 reverts to the legacy velocity-inlet
    # (fixed v) for comparison. Default (unset / '1') = mass-flux inlet on.
    if os.environ.get('TPMSHX_2D_MASSFLUX', '1') == '0':
        s.massflux_inlet = False
    s.dx_arr = DY_REFINED.copy()
    s.dy_arr = DX_REFINED.copy()
    if T_field is not None:
        s.update_T_field(np.ascontiguousarray(T_field, dtype=np.float64))
    if Re_case is not None:
        _apply_rough_to_simple(s, Re_case)
    s.solve(max_iter=3000, tol=1e-4, verbose=False)
    # Cell-centre velocity in real-coord (N_X, N_Y) shape
    v_cell = 0.5 * (s.v[:, :-1] + s.v[:, 1:])   # (N_Y, N_X)
    ucA_real = np.ascontiguousarray(v_cell.T, dtype=np.float64)  # (N_X, N_Y)
    vcA_real = np.zeros((N_X, N_Y), dtype=np.float64)
    return ucA_real, vcA_real, s


def _transform_rho_mu_to_simple_coords(field_real):
    """(N_X, N_Y) real-coord 2D field → SIMPLE coords (N_Y, N_X) for
    Fluid A (+x). Same transform run_calculation.py._run_simple uses.
    """
    if np.ndim(field_real) != 2:
        return field_real
    return np.ascontiguousarray(field_real.T, dtype=np.float64)


def _transform_simple_P_to_real(s):
    """SIMPLE P + P_ref_abs → real-coord (N_X, N_Y) absolute P field."""
    P_loc = s.P_ref_abs + s.P   # (N_Y, N_X) solver coords for dir_A=+x
    return np.ascontiguousarray(P_loc.T, dtype=np.float64)


# ── Load Shanghai cases (canonical loader, B1 1.3) ──
from sjtu_tpmshx.validation.harness._harness import load_cases_df
from sjtu_tpmshx.validation.harness._case_sets import SHANGHAI_XLSX


# ═══════════════════════════════════════════════════════════════════════
#  PRODUCTION-PIPELINE RUNNER (default) — real water solve, shipped code
# ═══════════════════════════════════════════════════════════════════════

def _run_one_case_pipeline(ci, df):
    """Drive the production `Pipeline2D` — the stack the GUI runs.

    Deliberately a DIFFERENT physics path from the kernel runner above: the water
    side gets a real SIMPLE-B momentum solve and a real energy solve, instead of
    a zero velocity field and a Tb profile interpolated from the MEASURED water
    outlet temperature. See the module docstring for why the frozen-B runner is
    not a valid gate.

    Returns the same result dict shape as the kernel loop so the summary code is
    shared. Fields the frozen-B path computed from its prescribed Tb (Q_solid_B,
    the enthalpy-balance residual) are NaN here — they were only ever a
    self-consistency check on a prescribed profile.
    """
    from sjtu_tpmshx.domain.compute_config import (FluidConfig, GeometryConfig,
                                       SolverConfig, PartialBCConfig,
                                       ExtrapPolicy, FeatureFlags)
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D

    case = ci + 1
    m_air = float(df.iloc[ci, 5])
    T_Ain_K = float(df.iloc[ci, 28]) + 273.15
    P_Ain_g = float(df.iloc[ci, 30])
    P_Ain = P_atm + P_Ain_g
    m_water = float(df.iloc[ci, 7])
    T_Bin_K = float(df.iloc[ci, 24]) + 273.15
    dP_A_exp = P_Ain_g - float(df.iloc[ci, 31])
    Q_exp = float(df.iloc[ci, 33])

    rho_A0 = float(air_density(T_Ain_K, P_Ain))
    u_A = m_air / (rho_A0 * A_FLOW)
    u_B = m_water / (float(water_density(T_Bin_K)) * A_FLOW)

    cc = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=u_A, T_in_K=T_Ain_K,
                            P_in_Pa=P_Ain),
        fluid_B=FluidConfig(type='water', u_mps=u_B, T_in_K=T_Bin_K,
                            P_in_Pa=float(df['water_P_in_abs_Pa'].iloc[ci])),
        geometry=GeometryConfig(tpms=TPMS, L_cell_mm=L_CELL, t_wall_mm=T_WALL,
                                k_s_W_mK=K_S, L_dom_m=L_DOM, H_dom_m=H_DOM),
        # Nz omitted -> 1 -> the 2D path. Grid from the same adaptive_grid the
        # kernel runner uses, so the two runners are compared on the same mesh.
        solver=SolverConfig(Nx=N_X_USER, Ny=N_Y_USER),
        # Full-face crossflow: A along +x, B along -y (the production Shanghai
        # topology, and what the kernel runner models with outlet_lo/hi = 0..H).
        bc_A=PartialBCConfig(dir=0, in_ctr=H_DOM / 2, in_w=H_DOM,
                             out_ctr=H_DOM / 2, out_w=H_DOM),
        bc_B=PartialBCConfig(dir=3, in_ctr=L_DOM / 2, in_w=L_DOM,
                             out_ctr=L_DOM / 2, out_w=L_DOM),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )
    res = Pipeline2D(cc).run()

    dP_A_sim = float(res.dP_A_Pa)

    # Q via the AIR-SIDE ENTHALPY BALANCE, exactly as the kernel runner does
    # (`Q_enthalpy_A = m_air * cp * (T_in - T_out)`), so the two runners report
    # the same quantity and are directly comparable.
    #
    # Do NOT use `res.Q_W` here. The 2D pipeline's Q is a domain integral over a
    # 2D cell AREA (`solve_2d.py`: `cell_area = dx * dy`, and h_v is W/(m³·K)),
    # so it is **W per metre of depth**, not watts — the 2D model has no third
    # dimension. Converting it would need the machine depth (for Shanghai,
    # Lz = 0.042 m: 60 737 W/m x 0.042 m = 2551 W vs the measured 2514 W, which
    # is how this was diagnosed). The enthalpy balance sidesteps the whole
    # question because `m_air` is the measured TOTAL mass flow.
    cp_A0 = float(air_cp(T_Ain_K))
    Q_sim = float(m_air * cp_A0 * (T_Ain_K - float(res.T_out_A_K)))

    err_dP = ((dP_A_sim - dP_A_exp) / dP_A_exp * 100
              if dP_A_exp != 0 else float('nan'))
    err_Q = (Q_sim - Q_exp) / Q_exp * 100 if Q_exp != 0 else float('nan')

    d = res.diagnostics or {}
    cd = d.get('convergence_detail') or {}
    if res.warnings:
        print(f"  [case {case}] pipeline warnings: "
              f"{'; '.join(str(w) for w in res.warnings)}")

    _nan = float('nan')
    return {
        'Case': case, 'u_air': round(u_A, 2), 'u_water': round(u_B, 4),
        'T_air_in': round(T_Ain_K - 273.15, 1),
        'T_water_in': round(T_Bin_K - 273.15, 1),
        'P_in_abs_kPa': round(P_Ain / 1000.0, 1),
        'dP_air_exp': round(dP_A_exp), 'dP_air_sim': round(dP_A_sim),
        'err_dP%': round(err_dP, 1),
        'Q_exp': round(Q_exp, 1), 'Q_sim': round(Q_sim, 1),
        'err_Q%': round(err_Q, 1),
        # Frozen-B self-consistency numbers: meaningless once Tb is SOLVED.
        'Q_solid_A': _nan, 'Q_solid_B': _nan, 'eb_resid%': _nan,
        'Q_enthalpy_A': round(Q_sim, 1), 'Q_total_max': round(abs(Q_sim), 1),
        # 2D exposes its verdict as per-gate flags, not the single
        # `solver_converged` key 3D has (and it has no outer-iteration counter).
        # Reading 3D's key here silently reported conv=False on every case.
        'outer_iters': int(cd.get('outer_iters', -1)),
        'converged': bool(cd.get('simple_ok', False)
                          and cd.get('ltne_ok', False)
                          and cd.get('outer_converged', False)
                          and cd.get('envelope_ok', False)
                          and not cd.get('energy_nan_hit', False)),
        'h_vA': _nan, 'h_vB': _nan,
        # 2D water-side outputs the frozen runner could not produce at all.
        'dP_B_sim': float(res.dP_B_Pa),
        'T_water_out_sim': float(res.T_out_B_K) - 273.15,
        'T_water_out_exp': float(df.iloc[ci, 25]),
    }


# 2026-06-30: guard execution so importing this module has no side
# effects (no SIMPLE solve, no xlsx write). Was an unguarded top-level script.
if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    # DEFAULT SWITCHED kernel -> pipeline (2026-07-12). See the module docstring:
    # the kernel runner freezes the water side from MEASURED data, never solves
    # SIMPLE-B at all, and exercises a code path production does not run.
    _ap.add_argument('--runner', choices=['pipeline', 'kernel'],
                     default='pipeline',
                     help="pipeline (DEFAULT) = production Pipeline2D with the "
                          "water side SOLVED. kernel = the legacy frozen-B "
                          "kernel-direct loop (reproduces the old numbers).")
    _args = _ap.parse_args()

    df = load_cases_df(SHANGHAI_XLSX)

    results = []

    print(f"\n[Shanghai aligned] Runner: {_args.runner}"
          + ("  (production Pipeline2D, water SOLVED)"
             if _args.runner == 'pipeline'
             else "  (LEGACY frozen-B kernel loop — water Tb PRESCRIBED from "
                  "measured data, SIMPLE-B never solved)") + "\n")

    if _args.runner == 'pipeline':
        for _ci in range(16):
            _r = _run_one_case_pipeline(_ci, df)
            results.append(_r)
            print(f"Case {_r['Case']:2d}: "
                  f"dP {_r['dP_air_exp']:.0f}/{_r['dP_air_sim']:.0f} "
                  f"({_r['err_dP%']:+.1f}%)  "
                  f"Q {_r['Q_exp']:.0f}/{_r['Q_sim']:.0f} ({_r['err_Q%']:+.1f}%)  "
                  f"T_w_out {_r['T_water_out_exp']:.1f}/"
                  f"{_r['T_water_out_sim']:.1f}°C  "
                  f"outer={_r['outer_iters']} conv={_r['converged']}")
        _KERNEL_LOOP = False
    else:
        _KERNEL_LOOP = True

    for ci in (range(16) if _KERNEL_LOOP else range(0)):
        case = ci + 1

        # ── Case inputs ──
        m_air = float(df.iloc[ci, 5])
        T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
        P_Ain_g = float(df.iloc[ci, 30])
        P_Ain = P_atm + P_Ain_g

        m_water = float(df.iloc[ci, 7])
        T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
        T_Bout_C = float(df.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15

        P_Aout_g = float(df.iloc[ci, 31])
        dP_A_exp = P_Ain_g - P_Aout_g
        Q_exp = float(df.iloc[ci, 33])

        # ── Scalar fluid properties at inlet (for first-iter seeds) ──
        rho_A0 = float(air_density(T_Ain_K, P_Ain))
        mu_A0  = float(air_viscosity(T_Ain_K))
        cp_A0  = float(air_cp(T_Ain_K))
        u_A    = m_air / (rho_A0 * A_FLOW)

        rho_B0 = float(water_density(T_Bin_K))
        mu_B0  = float(water_viscosity(T_Bin_K))
        cp_B0  = float(water_cp(T_Bin_K))
        u_B    = m_water / (rho_B0 * A_FLOW)

        # ── LTNE coefficients via tpms_compute (same as run_calculation) ──
        # Fluid A: air
        r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
        h_vA = A0 * r_A['H_sf']
        # 2026-05-13 — bhatti_shah_1b overrides scalar ×1.28 baked into tpms_compute
        # with Re-dep g_Nu(Re,ε)/1.28. Norris (1a) leaves Nu unchanged.
        _Re_A_case = rho_A0 * abs(u_A) * D_H / mu_A0
        if _ROUGH_MODE != 'baseline':
            h_vA *= nu_extra_factor(_Re_A_case, _ROUGH_MODE,
                                     eps_um=_ROUGH_EPS, D_h_mm=D_H * 1000.0)
        k_A  = r_A['k_f']
        K_ffA = EPS_A * k_A

        # Fluid B: water. Per-topology direct water-CFD fit (nu_water_topo):
        #   Gyroid Nu = 0.4445 · Re^0.6361 · Pr^(1/3)   (Re 100-50000)
        # No air ×1.28; replaces the Yan [6] correlation (2026-06-18).
        # Cases 1-2 (Re 54, 108) extrapolate below the 100 floor.
        k_B  = float(water_conductivity(T_Bin_K))
        Pr_B = float(mu_B0 * cp_B0 / k_B)
        Re_B = rho_B0 * abs(u_B) * D_H / mu_B0
        Nu_B = float(nu_water_topo('Gyroid', max(Re_B, 1.0), Pr_B))
        H_sf_B = Nu_B * k_B / D_H
        h_vB = A0 * H_sf_B
        K_ffB = EPS_A * k_B    # symmetric sheet HX: ε_B = ε_A

        K_ss = (1.0 - EPS) * K_S

        # ── Water-side frozen Tb: linear between T_in / T_out along +y (dir_B=3
        # = -y so inlet at high y, outlet at low y — match run_calculation convention) ──
        y_edges = np.concatenate([[0.0], np.cumsum(DY_REFINED)])
        y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
        Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centers / H_DOM)
        Tb_prescribed = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

        # ── Seed P_ref_abs via 1D compressible closed-form estimate ──
        G_A = m_air / A_FLOW
        C_est = mu_A0 * G_A / K0 + cF0 * G_A**2
        P_out_sq = P_Ain**2 - 2.0 * R_AIR_VAL * T_Ain_K * C_est * L_DOM
        P_ref_abs_seed = float(np.sqrt(max(P_out_sq, 1.0e4)))

        # ── Outer coupling loop — mirrors run_calculation.py._run_solvers ──
        rho_A_field_real = np.full((N_X, N_Y), rho_A0, dtype=np.float64)
        mu_A_field_real  = np.full((N_X, N_Y), mu_A0,  dtype=np.float64)
        rho_cp_A_real    = rho_A0 * cp_A0  # scalar initial — becomes 2D after first energy solve

        Ta = Tb = Ts = None
        Ta_prev = Tb_prev = None
        coupling_converged = False
        outer_iters = 0

        ucB_real = np.zeros((N_X, N_Y), dtype=np.float64)
        vcB_real = np.zeros((N_X, N_Y), dtype=np.float64)

        for _coup_it in range(_MAX_COUPLING):
            outer_iters = _coup_it + 1

            # 1. SIMPLE with current rho / mu fields (transform to SIMPLE coords)
            rho_A_simple = _transform_rho_mu_to_simple_coords(rho_A_field_real)
            mu_A_simple  = _transform_rho_mu_to_simple_coords(mu_A_field_real)
            # 2026-05-14: from iter 1 onward, propagate current Ta into SIMPLE
            # so _update_density uses real cell T (not stale T_in).
            T_A_simple = (_transform_rho_mu_to_simple_coords(Ta)
                           if Ta is not None else None)
            ucA_real, vcA_real, sA = _run_simple_A(
                rho_A_simple, mu_A_simple, u_A, T_Ain_K, P_ref_abs_seed,
                Re_case=_Re_A_case, T_field=T_A_simple, rho_inlet_ref=rho_A0)

            # 2. Energy solve with Tb prescribed
            Ta, Tb, Ts, e_info = solve_full_domain(
                L_DOM, H_DOM, N_X, N_Y,
                T_Ain_K, T_Bin_K,
                K_ffA, K_ffB, K_ss,
                h_vA, h_vB,
                rho_cp_A_real, rho_B0 * cp_B0,  # fluid-B rho_cp scalar (frozen Tb)
                EPS,
                ucA_real, vcA_real, ucB_real, vcB_real,
                dir_A=0, dir_B=3,
                Tb_prescribed=Tb_prescribed,
                tol=0.5, max_iter=5000, return_info=True,
                dx_arr=DX_REFINED, dy_arr=DY_REFINED,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            )

            # 3. Update rho / mu / rho_cp from per-cell T and local absolute P
            P_abs_A = _transform_simple_P_to_real(sA)  # (N_X, N_Y)
            rho_A_new = air_density(Ta, P_abs_A).astype(np.float64)
            mu_A_new  = air_viscosity(Ta).astype(np.float64)
            rho_cp_A_new = rho_A_new * air_cp(Ta).astype(np.float64)

            # 4. Convergence diagnostics (drho mass-flux weighted AND dT max)
            w = np.sqrt(ucA_real ** 2 + vcA_real ** 2) + 1e-12
            drho_A = float(np.sum(np.abs((rho_A_new - rho_A_field_real) /
                                          rho_A_field_real) * w) / np.sum(w))
            if Ta_prev is not None:
                dT_A = float(np.max(np.abs(Ta - Ta_prev)))
            else:
                dT_A = float('inf')

            print(f"  Case {case:2d} [iter {_coup_it+1}] drho_A={drho_A:.4f} "
                  f"dT_A={dT_A:.2f}K  T_avg={float(Ta.mean()):.1f}K")

            if drho_A < _COUPLING_TOL and dT_A < _DT_TOL_K:
                coupling_converged = True
                break

            # 5. Under-relax + prep next iteration
            Ta_prev = Ta.copy()
            rho_A_field_real = _ALPHA_COUP * rho_A_new + (1.0 - _ALPHA_COUP) * rho_A_field_real
            mu_A_field_real  = _ALPHA_COUP * mu_A_new  + (1.0 - _ALPHA_COUP) * mu_A_field_real
            if np.ndim(rho_cp_A_real) == 0:
                rho_cp_A_real = rho_cp_A_new.copy()
            else:
                rho_cp_A_real = _ALPHA_COUP * rho_cp_A_new + (1.0 - _ALPHA_COUP) * rho_cp_A_real

        # ── Extract dP (pipe-weighted) via same utility as UI ──
        dP_A_sim = float(extract_dP_from_simple(sA))

        # ── Q_sim: enthalpy-based (Option C, 2026-04-24 alignment with UI 2D).
        # Old code reported Q_enthalpy_A. Q_solid_B is kept as a diagnostic — it
        # is the signed volume integral ∑h_vB·(Ts−Tb), the quantity that flipped
        # negative before the Option-C refactor. Q_total_max matches the UI
        # Q_total = max(|Q_A|, |Q_B|). B is prescribed via Tb so Q_enthalpy_B
        # cannot be independently recovered; fall back to Q_enthalpy_A.
        cell_area = DX_REFINED[:, None] * DY_REFINED[None, :]
        Q_solid_A = float(np.sum(h_vA * (Ta - Ts) * cell_area))   # air → solid
        Q_solid_B = float(np.sum(h_vB * (Ts - Tb) * cell_area))   # solid → water
        eb_resid_pct = (Q_solid_A - Q_solid_B) / max(abs(Q_solid_A), 1e-30) * 100.0
        T_A_out_mean = float(np.mean(Ta[-1, :]))
        Q_enthalpy_A = float(m_air * cp_A0 * (T_Ain_K - T_A_out_mean))
        Q_enthalpy_B_est = float(np.sum(h_vB * (Ts - Tb) * cell_area))  # = Q_solid_B
        Q_total_max = max(abs(Q_enthalpy_A), abs(Q_enthalpy_B_est))
        Q_sim = Q_enthalpy_A  # keep as primary vs experiment (m·cp·ΔT matches)

        err_dP = (dP_A_sim - dP_A_exp) / dP_A_exp * 100 if dP_A_exp != 0 else float('nan')
        err_Q  = (Q_sim   - Q_exp ) / Q_exp   * 100 if Q_exp   != 0 else float('nan')

        results.append({
            'Case': case, 'u_air': round(u_A, 2), 'u_water': round(u_B, 4),
            'T_air_in': round(T_Ain_C, 1), 'T_water_in': round(T_Bin_C, 1),
            'P_in_abs_kPa': round(P_Ain / 1000.0, 1),
            'dP_air_exp': round(dP_A_exp), 'dP_air_sim': round(dP_A_sim),
            'err_dP%': round(err_dP, 1),
            'Q_exp': round(Q_exp, 1), 'Q_sim': round(Q_sim, 1), 'err_Q%': round(err_Q, 1),
            'Q_solid_A': round(Q_solid_A, 1),
            'Q_solid_B': round(Q_solid_B, 1),
            'eb_resid%': round(eb_resid_pct, 4),
            'Q_enthalpy_A': round(Q_enthalpy_A, 1),
            'Q_total_max': round(Q_total_max, 1),
            'outer_iters': outer_iters, 'converged': coupling_converged,
            'h_vA': round(h_vA, 1), 'h_vB': round(h_vB, 1),
        })

        print(f"Case {case:2d}: dP {dP_A_exp:.0f}/{dP_A_sim:.0f} ({err_dP:+.0f}%)  "
              f"Q {Q_exp:.0f}/{Q_sim:.0f} ({err_Q:+.1f}%)  "
              f"Q_sA={Q_solid_A:.1f} Q_sB={Q_solid_B:.1f} eb={eb_resid_pct:+.3f}%  "
              f"iters={outer_iters} conv={coupling_converged}\n")


    # ── Summary + save ──
    from sjtu_tpmshx.validation.harness._metrics import err_stats_pct
    out_df = pd.DataFrame(results)
    err_dp = np.array([r['err_dP%'] for r in results])
    err_q  = np.array([r['err_Q%']  for r in results])
    rmsre_dp, bias_dp, maxabs_dp = err_stats_pct(err_dp)
    rmsre_q,  bias_q,  maxabs_q  = err_stats_pct(err_q)
    print('='*72)
    print(f"RMSRE_dP = {rmsre_dp:.2f}%   "
          f"mean_bias_dP = {bias_dp:+.2f}%   "
          f"max|err_dP| = {maxabs_dp:.1f}%")
    print(f"RMSRE_Q  = {rmsre_q:.2f}%   "
          f"mean_bias_Q  = {bias_q:+.2f}%   "
          f"max|err_Q|  = {np.max(np.abs(err_q)):.1f}%")

    out_path = _DATA / 'shanghai_validation_aligned.xlsx'
    out_df.to_excel(out_path, index=False, engine='openpyxl')
    print(f"\nSaved: {out_path}")
