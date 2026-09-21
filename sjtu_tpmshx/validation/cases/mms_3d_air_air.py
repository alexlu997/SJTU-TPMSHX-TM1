"""mms_3d_air_air.py — Method of Manufactured Solutions for 3D LTNE solver.

Phase A.2 of Standard Tier V&V (ASME V&V 20).

Three test cases (sympy-derived analytical sources, kernel-driver harness):
- MMS-1D: T_alpha(x) only — isolates axial advection-diffusion + LTNE coupling.
- MMS-2D: T_alpha(x, y) — z-independent, exercises 2D stencil.
- MMS-3D: T_alpha(x, y, z) — full 3D trigonometric.

For each: pick smooth analytical T_alpha satisfying the implemented BCs
(Dirichlet inlet, Neumann zero-grad outlet/lateral walls), derive S_alpha
from PDE residual symbolically via sympy, evaluate on cell-centered grid,
drive `_gs_full_chunk_3d_stag` with uniform material properties +
manufactured S, compare numeric vs exact at single grid.

Phase A.3 (separate harness) does multi-grid h-refinement for observed
order p_obs.

Hard gates per case (single grid 20):
  rel L2 err per phase < 2.0%   (1st-order Patankar at high cell-Pe outlet)
  Linf err per phase  < 3.0 K

PDE form (volumetric, kernel-consistent):
  A: eps*rho_cp*u_A*dT_a/dx - K_ffA*Lap(T_a) - h_vA*(T_s - T_a) = S_a
  B: eps*rho_cp*u_B*dT_b/dy - K_ffB*Lap(T_b) - h_vB*(T_s - T_b) = S_b
  s: -K_ss*Lap(T_s) - h_vA*(T_a - T_s) - h_vB*(T_b - T_s) = S_s

Manufactured T satisfy:
  T_a inlet at x=0:    Dirichlet from analytical T_a(0, y_c, z_c)
  T_a outlet at x=L:   Neumann zero-grad — cos(pi x/L) gives sin(pi)=0
  T_a lateral (y,z):   Neumann zero-grad — cos(pi y/H), cos(pi z/Lz) give 0
  T_b inlet at y=0:    Dirichlet from analytical T_b(x_c, 0, z_c)
  T_b outlet at y=H:   Neumann zero-grad
  T_s lateral (all):   Neumann zero-grad
"""
from __future__ import annotations
import argparse
import sys
import time
import warnings

import numpy as np
import sympy as sp

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.solvers.ltne_energy_3d import _gs_full_chunk_3d_stag


# ─────────────────────────────────────────────────────────────────────────
# Domain + uniform material properties
# ─────────────────────────────────────────────────────────────────────────
# Shanghai-like aspect ratio (kept identical to audit T2).
L_DOM, H_DOM, LZ = 0.182, 0.042, 0.042

# Uniform material — chosen to be physically representative of Air-Air HX,
# but free of TPMS porosity zoning so kernel face-mean / harmonic-K reduce
# to constants and MMS source derivation is exact.
EPS_F     = 0.85                 # fluid fraction (eps_f in kernel)
RHO_CP_A  = 1.10 * 1006.0        # rho*cp ~ 1107 J/m3K (P=1atm, T=350K air)
RHO_CP_B  = 1.10 * 1006.0
K_FFA     = 0.030                # W/mK eff (~ eps * k_air)
K_FFB     = 0.030
K_SS      = (1.0 - EPS_F) * 16.0 # ~ 2.4 W/mK steel * (1-eps)
H_VA      = 5.0e4                # W/m3K LTNE volumetric coupling (moderate)
H_VB      = 5.0e4
U_A       = 5.0                  # m/s axial (A flows in +x)
U_B       = 5.0                  # m/s cross-stream (B flows in +y)

# Manufactured solution amplitudes
T0   = 350.0                     # K reference
DA   = 30.0                      # K amplitude for T_a
DB   = 20.0                      # K amplitude for T_b
DS   = 25.0                      # K amplitude for T_s


# ─────────────────────────────────────────────────────────────────────────
# Sympy: build T_alpha and analytical S_alpha
# ─────────────────────────────────────────────────────────────────────────
def _build_mms(case='3d'):
    """sympy-derive analytical T_alpha and PDE residual S_alpha.

    Returns dict of np.lambdified callables:
        Ta_fn(x,y,z,Lx,Ly,Lz), Tb_fn, Ts_fn,
        SA_fn, SB_fn, SS_fn   (all volumetric, W/m3)
    """
    x, y, z, Lx_, Ly_, Lz_ = sp.symbols('x y z Lx Ly Lz', positive=True)
    PI = sp.pi

    if case == '1d':
        # Axial only; lateral walls trivially adiabatic (T constant in y, z).
        # Outlet at x=L: cos(pi) sine = 0 -> Neumann auto.
        Ta = T0 + DA * sp.cos(PI * x / Lx_)
        Tb = T0 + DB * sp.cos(PI * x / Lx_)
        Ts = T0 + DS * sp.cos(PI * x / Lx_)

    elif case == '2d':
        # x,y; z-independent. Cosines give zero gradient at all 4 in-plane walls.
        Ta = T0 + DA * sp.cos(PI * x / Lx_) * sp.cos(PI * y / Ly_)
        Tb = T0 + DB * sp.cos(2 * PI * x / Lx_) * sp.cos(PI * y / Ly_)
        Ts = T0 + DS * sp.cos(PI * x / Lx_) * sp.cos(2 * PI * y / Ly_)

    elif case == '3d':
        # Full 3D trig — different shape per phase to make h_v coupling non-trivial.
        Ta = T0 + DA * sp.cos(PI * x / Lx_) * sp.cos(PI * y / Ly_) * sp.cos(PI * z / Lz_)
        Tb = T0 + DB * sp.cos(2 * PI * x / Lx_) * sp.cos(PI * y / Ly_) * sp.cos(PI * z / Lz_)
        Ts = T0 + DS * sp.cos(PI * x / Lx_) * sp.cos(2 * PI * y / Ly_) * sp.cos(PI * z / Lz_)

    else:
        raise ValueError(f"Unknown MMS case {case!r}")

    def lap(T):
        return sp.diff(T, x, 2) + sp.diff(T, y, 2) + sp.diff(T, z, 2)

    # PDE residual (volumetric source, W/m3) — kernel-consistent sign convention
    S_A = (EPS_F * RHO_CP_A * U_A * sp.diff(Ta, x)
           - K_FFA * lap(Ta)
           - H_VA * (Ts - Ta))
    S_B = (EPS_F * RHO_CP_B * U_B * sp.diff(Tb, y)
           - K_FFB * lap(Tb)
           - H_VB * (Ts - Tb))
    S_s = (-K_SS * lap(Ts)
           - H_VA * (Ta - Ts)
           - H_VB * (Tb - Ts))

    args = (x, y, z, Lx_, Ly_, Lz_)
    return dict(
        Ta_fn=sp.lambdify(args, Ta, 'numpy'),
        Tb_fn=sp.lambdify(args, Tb, 'numpy'),
        Ts_fn=sp.lambdify(args, Ts, 'numpy'),
        SA_fn=sp.lambdify(args, S_A, 'numpy'),
        SB_fn=sp.lambdify(args, S_B, 'numpy'),
        SS_fn=sp.lambdify(args, S_s, 'numpy'),
        sym_Ta=Ta, sym_Tb=Tb, sym_Ts=Ts,
        sym_SA=S_A, sym_SB=S_B, sym_Ss=S_s,
    )


def _eval_grid(fn, X, Y, Z):
    """Evaluate lambdified function on grid; broadcast scalars to grid shape."""
    val = fn(X, Y, Z, L_DOM, H_DOM, LZ)
    val = np.asarray(val, dtype=np.float64)
    if val.shape != X.shape:
        val = np.broadcast_to(val, X.shape).copy()
    return np.ascontiguousarray(val)


# ─────────────────────────────────────────────────────────────────────────
# MMS driver — calls kernel directly with manufactured S
# ─────────────────────────────────────────────────────────────────────────
def run_mms(case='3d', Nx=20, Ny=20, Nz=20,
            max_outer=5000, inner=50,
            tol=1e-10, alpha_f=0.7, alpha_s=1.0, verbose=True,
            conservative=0):
    """Run MMS test on grid Nx x Ny x Nz; return error metrics dict.

    conservative=1 drives the face-shared conservative HO kernel branch
    (B-plan B4 order verification); 0 keeps the legacy cell-local SOU path."""
    mms = _build_mms(case)

    dx = L_DOM / Nx
    dy = H_DOM / Ny
    dz = LZ / Nz
    xc = (np.arange(Nx) + 0.5) * dx
    yc = (np.arange(Ny) + 0.5) * dy
    zc = (np.arange(Nz) + 0.5) * dz
    Xc, Yc, Zc = np.meshgrid(xc, yc, zc, indexing='ij')

    # Analytical fields and sources at cell centers
    Ta_exact = _eval_grid(mms['Ta_fn'], Xc, Yc, Zc)
    Tb_exact = _eval_grid(mms['Tb_fn'], Xc, Yc, Zc)
    Ts_exact = _eval_grid(mms['Ts_fn'], Xc, Yc, Zc)
    mms_S_A  = _eval_grid(mms['SA_fn'], Xc, Yc, Zc)
    mms_S_B  = _eval_grid(mms['SB_fn'], Xc, Yc, Zc)
    mms_S_s  = _eval_grid(mms['SS_fn'], Xc, Yc, Zc)

    # Init at T0 (constant) — robust starting guess
    Ta = np.full((Nx, Ny, Nz), T0, dtype=np.float64)
    Tb = np.full((Nx, Ny, Nz), T0, dtype=np.float64)
    Ts = np.full((Nx, Ny, Nz), T0, dtype=np.float64)

    # Uniform property arrays
    dx_arr = np.full(Nx, dx, dtype=np.float64)
    dy_arr = np.full(Ny, dy, dtype=np.float64)
    dz_arr = np.full(Nz, dz, dtype=np.float64)
    K_ffA_arr = np.full((Nx, Ny, Nz), K_FFA, dtype=np.float64)
    K_ffB_arr = np.full((Nx, Ny, Nz), K_FFB, dtype=np.float64)
    K_ss_arr  = np.full((Nx, Ny, Nz), K_SS,  dtype=np.float64)
    h_vA_arr  = np.full((Nx, Ny, Nz), H_VA,  dtype=np.float64)
    h_vB_arr  = np.full((Nx, Ny, Nz), H_VB,  dtype=np.float64)
    eps_f_arr = np.full((Nx, Ny, Nz), EPS_F, dtype=np.float64)
    rho_cp_fA = np.full((Nx, Ny, Nz), RHO_CP_A, dtype=np.float64)
    rho_cp_fB = np.full((Nx, Ny, Nz), RHO_CP_B, dtype=np.float64)

    # Plug-flow staggered velocities (faces; A in +x, B in +y)
    ufA = np.full((Nx + 1, Ny, Nz), U_A, dtype=np.float64)
    vfA = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
    wfA = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)
    ufB = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
    vfB = np.full((Nx, Ny + 1, Nz), U_B, dtype=np.float64)
    wfB = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)

    # Inlet profiles live on the physical faces; end cells remain unknowns.
    Yi_grid, Zi_grid = np.meshgrid(yc, zc, indexing='ij')   # (Ny, Nz)
    x_inlet = np.zeros_like(Yi_grid)
    T_inA_arr = _eval_grid_2d(mms['Ta_fn'], x_inlet, Yi_grid, Zi_grid)

    Xi_grid, Zii_grid = np.meshgrid(xc, zc, indexing='ij')   # (Nx, Nz)
    y_inlet = np.zeros_like(Xi_grid)
    T_inB_arr = _eval_grid_2d(mms['Tb_fn'], Xi_grid, y_inlet, Zii_grid)

    # Inlet fraction = 1 (full-face inlet, no partial mask)
    ifrac_A = np.ones((Ny, Nz), dtype=np.float64)
    ifrac_B = np.ones((Nx, Nz), dtype=np.float64)


    # ── Iterate kernel ───────────────────────────────────────────────────
    t0 = time.time()
    converged = False
    last_chg = float('inf')
    for outer in range(max_outer):
        chg = _gs_full_chunk_3d_stag(
            Ta, Tb, Ts, Nx, Ny, Nz,
            dx_arr, dy_arr, dz_arr,
            K_ffA_arr, K_ffB_arr, K_ss_arr,
            h_vA_arr, h_vB_arr, eps_f_arr, eps_f_arr,  # eps_fA=eps_fB (symmetric MMS): per-asym kernel split, same array reproduces pre-asym single-eps behavior
            rho_cp_fA, rho_cp_fB,
            ufA, vfA, wfA, ufB, vfB, wfB,
            0, 2,                              # bc_A=+x, bc_B=+y
            T_inA_arr, T_inB_arr,
            ifrac_A, ifrac_B,
            inner, 0,                          # n_iters per call, freeze_Tb=0
            alpha_f, alpha_s, alpha_f,         # under-relaxation (SOU at high Pe)
            mms_S_A, mms_S_B, mms_S_s,
            conservative,                      # 0=cell-local SOU; 1=face-shared conservative HO
        )
        last_chg = float(chg)
        if last_chg < tol:
            converged = True
            break

    elapsed = time.time() - t0

    # ── Error metrics ────────────────────────────────────────────────────
    def rel_l2(num, exact):
        return float(np.sqrt(np.mean((num - exact) ** 2))
                     / (np.sqrt(np.mean(exact ** 2)) + 1e-30))

    def linf(num, exact):
        return float(np.max(np.abs(num - exact)))

    L2_A = rel_l2(Ta, Ta_exact);  Linf_A = linf(Ta, Ta_exact)
    L2_B = rel_l2(Tb, Tb_exact);  Linf_B = linf(Tb, Tb_exact)
    L2_s = rel_l2(Ts, Ts_exact);  Linf_s = linf(Ts, Ts_exact)

    if verbose:
        print(f"[MMS-{case}] grid {Nx}x{Ny}x{Nz}  "
              f"converged={converged}  outers={outer + 1}  "
              f"last_chg={last_chg:.2e}  [{elapsed:.1f}s]")
        print(f"  rel L2  : A={L2_A:.4%}  B={L2_B:.4%}  s={L2_s:.4%}")
        print(f"  Linf K  : A={Linf_A:.3f}  B={Linf_B:.3f}  s={Linf_s:.3f}")

    return dict(
        case=case, Nx=Nx, Ny=Ny, Nz=Nz,
        converged=converged, outer_iters=outer + 1,
        last_chg=last_chg, elapsed=elapsed,
        L2_A=L2_A, L2_B=L2_B, L2_s=L2_s,
        Linf_A=Linf_A, Linf_B=Linf_B, Linf_s=Linf_s,
        Ta_num=Ta, Tb_num=Tb, Ts_num=Ts,
        Ta_exact=Ta_exact, Tb_exact=Tb_exact, Ts_exact=Ts_exact,
    )


def _eval_grid_2d(fn, X, Y, Z):
    """Eval lambdified on 2D grids (for inlet profiles)."""
    val = fn(X, Y, Z, L_DOM, H_DOM, LZ)
    val = np.asarray(val, dtype=np.float64)
    if val.shape != X.shape:
        val = np.broadcast_to(val, X.shape).copy()
    return np.ascontiguousarray(val)


# ─────────────────────────────────────────────────────────────────────────
# CLI driver
# ─────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='MMS Phase A.2 — single-grid sanity check')
    ap.add_argument('--case', choices=['1d', '2d', '3d', 'all'], default='all')
    ap.add_argument('--grid', type=int, default=20, help='Nx=Ny=Nz')
    ap.add_argument('--inner', type=int, default=50, help='Inner GS iters per outer')
    ap.add_argument('--max_outer', type=int, default=5000)
    ap.add_argument('--tol', type=float, default=1e-10)
    ap.add_argument('--alpha_f', type=float, default=0.7,
                    help='Fluid under-relaxation (SOU at high cell-Pe)')
    ap.add_argument('--alpha_s', type=float, default=1.0,
                    help='Solid under-relaxation')
    args = ap.parse_args()

    cases = ['1d', '2d', '3d'] if args.case == 'all' else [args.case]

    print(f"{'='*72}")
    print(f"  MMS Phase A.2 — sanity check (single-grid {args.grid}^3)")
    print(f"{'='*72}")
    print(f"  Domain: {L_DOM*1000:.0f}x{H_DOM*1000:.0f}x{LZ*1000:.0f} mm")
    print(f"  Material (uniform): eps={EPS_F}  K_ffA/B={K_FFA}  K_ss={K_SS:.3f}")
    print(f"                      h_vA/B={H_VA:.0e} W/m3K")
    print(f"                      rho_cp_A/B={RHO_CP_A:.0f}  u_A/B={U_A}/{U_B} m/s")
    print(f"  T0={T0}K  Delta_A={DA}  Delta_B={DB}  Delta_s={DS} K")
    print("  PDE: eps*rho_cp*u*dT/dx_i - K*Lap(T) - h_v*(T_other - T) = S_mms")
    print()

    results = []
    fail_cases = []
    for c in cases:
        print(f"--- MMS-{c} ---")
        r = run_mms(c, Nx=args.grid, Ny=args.grid, Nz=args.grid,
                    max_outer=args.max_outer, inner=args.inner, tol=args.tol,
                    alpha_f=args.alpha_f, alpha_s=args.alpha_s)
        results.append(r)
        ok = (r['L2_A'] < 0.020 and r['L2_B'] < 0.020 and r['L2_s'] < 0.020
              and r['Linf_A'] < 3.0 and r['Linf_B'] < 3.0 and r['Linf_s'] < 3.0)
        gate_str = 'PASS' if ok else 'FAIL'
        print(f"  GATES (L2<2.0%, Linf<3K): {gate_str}\n")
        if not ok:
            fail_cases.append(c)

    # Summary
    print(f"\n{'='*72}")
    print("  Summary")
    print(f"{'='*72}")
    print(f"  {'case':<6} {'L2_A':>9} {'L2_B':>9} {'L2_s':>9} "
          f"{'Linf_A':>8} {'Linf_B':>8} {'Linf_s':>8} {'iters':>6}")
    for r in results:
        print(f"  MMS-{r['case']:<2} "
              f"{r['L2_A']:>8.3%} {r['L2_B']:>8.3%} {r['L2_s']:>8.3%} "
              f"{r['Linf_A']:>7.3f} {r['Linf_B']:>7.3f} {r['Linf_s']:>7.3f} "
              f"{r['outer_iters']:>6}")
    if fail_cases:
        print(f"\n  FAILED cases: {fail_cases}")
        return 1
    print("\n  All cases PASS hard gates.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
