"""homogenize_chi_s.py — B2: unit-cell numerical homogenization of chi_S.

Computes the effective solid-phase thermal conductivity of the TPMS sheet
skeleton by periodic homogenization on the SAME voxel geometry used for
epsilon / A_0 (solvers/tpms_geometry: |phi| <= C(t/L), cell-centred N^3
grid), closing the TODO at solvers/tpms_props.py CHI_S ("replace with
numerical homogenisation from a unit-cell simulation").

Method
------
Steady conduction, unit macroscopic gradient G along axis a:
    T = T_tilde - G*x_a,  T_tilde periodic on the unit cell.
7-point finite-volume stencil, harmonic-mean face conductivity,
k_solid = 1, k_void = K_VOID (tiny; the fluid's conduction is carried by
K_ff, LTNE convention — K_ss is the solid skeleton alone). Matrix-free
Jacobi-preconditioned CG on the periodic stencil.

    k_eff_a = <k * (G - dT_tilde/dx_a)> / G      (volume average)
    chi_a   = k_eff_a / (1 - eps)                (K_ss = chi*(1-eps)*k_s)

Self-checks: full-solid chi=1, laminate series/parallel bounds, 3-axis
isotropy at the Shanghai point, N-refinement drift.

Usage
-----
    python -u runs/tools/homogenize_chi_s.py --selftest
    python -u runs/tools/homogenize_chi_s.py --sweep   # -> CSV + fit coeffs
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from sjtu_tpmshx.models.tpms_geometry import _phi_grid, _C_from_tL  # noqa: E402

K_VOID = 1e-6      # void conductivity (units of k_s); flux error O(K_VOID)
CG_TOL = 1e-9      # relative residual
CG_MAXIT = 20000


# ── periodic FV operator ─────────────────────────────────────────

def _face_k(k, axis):
    """Harmonic-mean conductivity on the 'east' faces along `axis`
    (face between cell i and i+1, periodic wrap)."""
    kn = np.roll(k, -1, axis=axis)
    return 2.0 * k * kn / (k + kn)


def _solve_chi(solid: np.ndarray, axis: int, verbose=False):
    """Periodic homogenization along `axis`. Returns (k_eff, iters, relres).

    Grid spacing h=1 (drops out of k_eff). G=1.
    """
    k = np.where(solid, 1.0, K_VOID)
    faces = [_face_k(k, a) for a in range(3)]   # east faces per axis

    def matvec(T):
        # SPD form: (-A) T = sum_faces k_f (T_P - T_neigh)
        out = np.zeros_like(T)
        for a in range(3):
            kf = faces[a]
            out += kf * (T - np.roll(T, -1, axis=a))
            kw = np.roll(kf, 1, axis=a)
            out += kw * (T - np.roll(T, 1, axis=a))
        return out

    # Cell balance with T = T_tilde - G*x_a (h=1, G=1):
    #   sum_f k_f (T~_n - T~_P) = G*(k_e - k_w)
    # SPD-negated: (-A) T~ = (k_w - k_e).
    kf = faces[axis]
    kw = np.roll(kf, 1, axis=axis)
    b = kw - kf

    # Jacobi preconditioner: diag(-A) = sum of face k's (positive).
    diag = np.zeros_like(k)
    for a in range(3):
        diag += faces[a] + np.roll(faces[a], 1, axis=a)
    Minv = 1.0 / diag

    b_norm = float(np.linalg.norm(b))
    if b_norm < 1e-30:          # homogeneous medium: T_tilde = 0 exactly
        k_eff = float(np.mean(kf))
        return k_eff, 0, 0.0

    # CG on the singular-but-consistent periodic system (nullspace =
    # constants; b sums to 0 by construction).
    x = np.zeros_like(b)
    r = b.copy()
    z = Minv * r
    p = z.copy()
    rz = float(np.sum(r * z))
    it = 0
    relres = 1.0
    for it in range(1, CG_MAXIT + 1):
        Ap = matvec(p)
        alpha = rz / float(np.sum(p * Ap))
        x += alpha * p
        r -= alpha * Ap
        relres = float(np.linalg.norm(r)) / b_norm
        if relres < CG_TOL:
            break
        z = Minv * r
        rz_new = float(np.sum(r * z))
        p = z + (rz_new / rz) * p
        rz = rz_new
        if verbose and it % 500 == 0:
            print(f"    cg it={it}  relres={relres:.2e}")
    x -= x.mean()

    # k_eff = <k_f * (G - dT/dx)> over east faces along `axis`; h=1, G=1.
    dT = np.roll(x, -1, axis=axis) - x
    k_eff = float(np.mean(faces[axis] * (1.0 - dT)))
    return k_eff, it, relres


def solid_mask(tpms_type: str, t_over_L: float, N: int) -> np.ndarray:
    phi = _phi_grid(tpms_type, N)
    C = max(_C_from_tL(tpms_type, t_over_L), 0.0)
    return np.abs(phi) <= C


def chi_s(tpms_type: str, t_over_L: float, N: int = 96, axes=(1,)):
    """chi per requested axis. Returns (eps, {axis: chi}, iters)."""
    solid = solid_mask(tpms_type, t_over_L, N)
    frac_solid = float(np.mean(solid))
    eps = 1.0 - frac_solid
    out = {}
    its = {}
    for a in axes:
        k_eff, it, relres = _solve_chi(solid, a)
        out[a] = k_eff / frac_solid
        its[a] = it
    return eps, out, its


# ── self-tests ───────────────────────────────────────────────────

def selftest():
    N = 48
    ok = True

    # 1. full solid -> chi = 1
    solid = np.ones((N, N, N), dtype=bool)
    k_eff, *_ = _solve_chi(solid, 0)
    print(f"full solid: k_eff = {k_eff:.6f} (expect 1)")
    ok &= abs(k_eff - 1.0) < 1e-6

    # 2. laminate slabs PERPENDICULAR to x (series) -> k_eff ~ K_VOID scale
    solid = np.zeros((N, N, N), dtype=bool)
    solid[: N // 2] = True                     # half-space slab, normal = x
    k_series, *_ = _solve_chi(solid, 0)
    k_series_exact = 1.0 / (0.5 / 1.0 + 0.5 / K_VOID)
    print(f"laminate series : k_eff = {k_series:.3e} (exact {k_series_exact:.3e})")
    ok &= abs(k_series - k_series_exact) / k_series_exact < 0.05

    # 3. same laminate ALONG y (parallel) -> k_eff = 0.5*(1 + K_VOID)
    k_par, *_ = _solve_chi(solid, 1)
    k_par_exact = 0.5 * (1.0 + K_VOID)
    print(f"laminate parallel: k_eff = {k_par:.6f} (exact {k_par_exact:.6f})")
    ok &= abs(k_par - k_par_exact) / k_par_exact < 1e-4

    # 4. isotropy + refinement at the Shanghai point (Gyroid t/L=0.6/7)
    tL = 0.6 / 7.0
    for N_ in (64, 96, 128):
        t0 = time.time()
        eps, chis, its = chi_s('Gyroid', tL, N=N_, axes=(0, 1, 2))
        v = list(chis.values())
        aniso = (max(v) - min(v)) / np.mean(v) * 100
        print(f"Gyroid t/L={tL:.4f} N={N_}: eps={eps:.4f} "
              f"chi=({v[0]:.4f},{v[1]:.4f},{v[2]:.4f}) aniso={aniso:.2f}% "
              f"[{time.time()-t0:.0f}s, cg its {list(its.values())}]")

    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


# ── sweep + fit ──────────────────────────────────────────────────

def sweep(N=96, out_csv=None):
    rows = []
    # production window: L 4-8 mm, t 0.2-1.0 mm -> t/L 0.03-0.20
    tL_values = [0.03, 0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20]
    for tp in ('Diamond', 'Gyroid'):
        for tL in tL_values:
            t0 = time.time()
            eps, chis, its = chi_s(tp, tL, N=N, axes=(1,))
            chi = chis[1]
            rows.append((tp, tL, eps, chi))
            print(f"{tp:8s} t/L={tL:.3f}  eps={eps:.4f}  chi={chi:.4f}  "
                  f"[{time.time()-t0:.0f}s, {its[1]} its]")
    # fit chi = c0 + c1*(1-eps) per type (thin-sheet limit c0 ~ 2/3)
    print("\nfit chi = c0 + c1*(1-eps):")
    coeffs = {}
    for tp in ('Diamond', 'Gyroid'):
        d = [(e, c) for (t, _, e, c) in rows if t == tp]
        x = np.array([1.0 - e for e, _ in d])
        y = np.array([c for _, c in d])
        c1, c0 = np.polyfit(x, y, 1)
        resid = y - (c0 + c1 * x)
        coeffs[tp] = (c0, c1)
        print(f"  {tp:8s}: c0={c0:.4f}  c1={c1:.4f}  "
              f"max|resid|={np.max(np.abs(resid)):.4f}")
    if out_csv:
        import csv
        with open(out_csv, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['tpms', 't_over_L', 'eps', 'chi_s'])
            w.writerows(rows)
        print(f"saved {out_csv}")
    return rows, coeffs


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--sweep', action='store_true')
    ap.add_argument('--N', type=int, default=96)
    ap.add_argument('--csv', default=None)
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.sweep:
        sweep(N=args.N, out_csv=args.csv)
