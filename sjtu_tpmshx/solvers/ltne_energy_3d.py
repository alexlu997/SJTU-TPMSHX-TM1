"""
ltne_energy_3d.py — Full-domain 3D steady-state 2-fluid LTNE solver

Three-temperature (Ta, Tb, Ts) LTNE on an (Nx, Ny, Nz) grid.

Energy equations (steady, incompressible, homogenised porous):
  eps_f * rho_cp_A * (u_A * dTa/dx + v_A * dTa/dy + w_A * dTa/dz)
      = div(K_ffA * grad Ta) + h_vA * (Ts - Ta)
  eps_f * rho_cp_B * (u_B * dTb/dx + v_B * dTb/dy + w_B * dTb/dz)
      = div(K_ffB * grad Tb) + h_vB * (Ts - Tb)
  0 = div(K_ss * grad Ts) + h_vA * (Ta - Ts) + h_vB * (Tb - Ts)

7-point Laplacian (harmonic-mean face conductivity). Upwind convection with
SOU deferred correction in all three axes. Cell-coupled Gauss-Seidel with
Ta -> Ts -> Tb updates in each sweep (k innermost, cache-friendly).

dir code: 0=+x, 1=-x, 2=+y, 3=-y, 4=+z, 5=-z.

Phase 1 additions (2026-04-20):
  * alpha_T under-relaxation (default 0.7) — shared by all three fields.
  * SOU limiter in x/y/z (promoted from Phase 1b).
  * Nz == 1 fast path: delegate to 2D solve_full_domain; bitwise-identical.
  * Conservation probes: energy_balance_3d, mass_balance_3d helpers.
"""

import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError

from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain as _solve_full_2d
from sjtu_tpmshx.models.tpms_props import model_h_coefficients


# ---------------------------------------------------------------------------
# Helmholtz/MAC divergence cleaner (B-plan B2)
# ---------------------------------------------------------------------------

# Relative-divergence threshold below which a face field is treated as already
# solenoidal and the projection solve is skipped (forward-dir fluids).
_PROJ_SKIP_TOL = 1e-9

# Cache: grid shape (Nx,Ny,Nz) -> {'L': graph Laplacian csr, 'ml': AMG hierarchy}.
# Read-only reuse contract: pyamg's multilevel solve() does not mutate the
# hierarchy, and the csr is only used as an operator — a caller mutating
# either would poison every later solve on that grid shape (audit §5c).
_LAPLACIAN_AMG_CACHE = {}


def clear_laplacian_amg_cache() -> None:
    """Reset hook (P1.6): drop all cached Laplacian/AMG hierarchies.

    Unbounded by distinct grid shapes; long-lived processes sweeping many
    grids (GCI studies, BO with adaptive grids) can use this to bound
    memory. Also gives tests isolation.
    """
    _LAPLACIAN_AMG_CACHE.clear()


def _laplacian_amg_cache(Nx, Ny, Nz):
    """Pure 7-point graph Laplacian + its Ruge-Stuben AMG hierarchy, cached by
    grid shape.

    The projection operator depends only on cell connectivity (unit ±1 face
    couplings — the ε·ρcp·A face weights enter only the post-solve velocity
    correction, never the Laplacian), so a single build is reused across both
    fluids and every outer iteration. This is what makes the AMG-CG path cheap:
    the hierarchy is assembled once per grid, not per solve.
    """
    key = (Nx, Ny, Nz)
    cached = _LAPLACIAN_AMG_CACHE.get(key)
    if cached is not None:
        return cached
    import pyamg
    from scipy.sparse import csr_matrix
    n = Nx * Ny * Nz
    idx = np.arange(n).reshape(Nx, Ny, Nz)
    rows = []; cols = []; vals = []

    def _add(a, b):
        # Symmetric Laplacian coupling for an interior face between cells a,b
        a = a.ravel(); b = b.ravel()
        rows.append(a); cols.append(a); vals.append(np.ones_like(a, np.float64))
        rows.append(a); cols.append(b); vals.append(-np.ones_like(a, np.float64))
        rows.append(b); cols.append(b); vals.append(np.ones_like(b, np.float64))
        rows.append(b); cols.append(a); vals.append(-np.ones_like(b, np.float64))

    if Nx > 1: _add(idx[:-1, :, :], idx[1:, :, :])
    if Ny > 1: _add(idx[:, :-1, :], idx[:, 1:, :])
    if Nz > 1: _add(idx[:, :, :-1], idx[:, :, 1:])
    L = csr_matrix((np.concatenate(vals),
                    (np.concatenate(rows), np.concatenate(cols))),
                   shape=(n, n))
    ml = pyamg.ruge_stuben_solver(L, max_coarse=200)
    cached = {'L': L, 'ml': ml}
    _LAPLACIAN_AMG_CACHE[key] = cached
    return cached


def _project_faces_div_free(uf, vf, wf, eps_f, rcp, dx, dy, dz):
    """Project staggered real-coords face velocities onto a discretely
    solenoidal field so the conservative LTNE kernel telescopes exactly.

    SIMPLE's solver-frame face fluxes are divergence-free, but
    `_solver_staggered_to_real` negates the stream component for reverse-dir
    fluids without reordering the shared cell fields, leaving a per-cell
    real-coords mass divergence of −2·(stream div) (≈17–69 % of the h_v
    scale, measured 2026-06-03). A single MAC/Helmholtz projection removes it:

        F_face = (ε·ρcp·u·A)_face                      (energy mass flux)
        D[c]   = Σ_faces F  (outward)                  (per-cell divergence)
        L φ = D    with L the 7-point graph Laplacian over INTERIOR faces
                   only (homogeneous-Neumann; boundary faces never corrected,
                   so inlet/outlet mass flow + the BC stay untouched)
        F*_face = F_face − (φ[nb] − φ[c])              (interior faces)
        u*_face = u_face + (F*_face − F_face) / C_face

    Returns corrected (uf, vf, wf). Forward-dir fluids are already
    solenoidal (D≈0 ⇒ φ≈0 ⇒ ~no change), so this is safe to apply to all.
    """
    from scipy.sparse.linalg import spsolve

    Nx, Ny, Nz = eps_f.shape
    Ax = (dy[None, :, None] * dz[None, None, :])   # (1,Ny,Nz)
    Ay = (dx[:, None, None] * dz[None, None, :])   # (Nx,1,Nz)
    Az = (dx[:, None, None] * dy[None, :, None])   # (Nx,Ny,1)

    coef = eps_f * rcp                              # cell ε·ρcp

    # Interior-face coefficients C = ε_f·ρcp·A (arithmetic-mean face value,
    # matching the kernel's face interpolation).
    Cx = 0.5 * (coef[:-1, :, :] + coef[1:, :, :]) * np.broadcast_to(Ax, (Nx-1, Ny, Nz))
    Cy = 0.5 * (coef[:, :-1, :] + coef[:, 1:, :]) * np.broadcast_to(Ay, (Nx, Ny-1, Nz))
    Cz = 0.5 * (coef[:, :, :-1] + coef[:, :, 1:]) * np.broadcast_to(Az, (Nx, Ny, Nz-1))

    # Per-cell divergence from current fluxes (interior + boundary faces).
    AxF = np.broadcast_to(Ax, uf.shape)
    AyF = np.broadcast_to(Ay, vf.shape)
    AzF = np.broadcast_to(Az, wf.shape)
    cf_x = np.empty_like(uf)
    cf_x[1:-1, :, :] = 0.5 * (coef[:-1, :, :] + coef[1:, :, :])
    cf_x[0, :, :] = coef[0, :, :]; cf_x[-1, :, :] = coef[-1, :, :]
    cf_y = np.empty_like(vf)
    cf_y[:, 1:-1, :] = 0.5 * (coef[:, :-1, :] + coef[:, 1:, :])
    cf_y[:, 0, :] = coef[:, 0, :]; cf_y[:, -1, :] = coef[:, -1, :]
    cf_z = np.empty_like(wf)
    cf_z[:, :, 1:-1] = 0.5 * (coef[:, :, :-1] + coef[:, :, 1:])
    cf_z[:, :, 0] = coef[:, :, 0]; cf_z[:, :, -1] = coef[:, :, -1]
    Fx = cf_x * uf * AxF
    Fy = cf_y * vf * AyF
    Fz = cf_z * wf * AzF
    D = ((Fx[1:, :, :] - Fx[:-1, :, :])
         + (Fy[:, 1:, :] - Fy[:, :-1, :])
         + (Fz[:, :, 1:] - Fz[:, :, :-1])).ravel()

    n = Nx * Ny * Nz
    if n == 0:
        return uf, vf, wf

    # #2 — skip the O(N) solve when the field is already (near-)solenoidal.
    # Forward-dir fluids enter divergence-free (the reverse-dir staggered→real
    # transform is what injects divergence); for them φ ~ 0 and the correction
    # is pure roundoff, so returning the input unchanged is both faster and
    # cleaner. The threshold is relative to the face-flux scale and sits far
    # below any physical divergence (reverse-dir D is O(0.1–0.7) of the h_v
    # scale, measured 2026-06-03), so a real correction is never skipped.
    flux_scale = max(float(np.abs(Fx).max()),
                     float(np.abs(Fy).max()),
                     float(np.abs(Fz).max()), 1e-300)
    if float(np.abs(D).max()) <= _PROJ_SKIP_TOL * flux_scale:
        return uf, vf, wf

    # #1 — solve the singular SPD graph-Laplacian system L φ = D with a cached
    # AMG-preconditioned CG. This replaces a dense-bordered direct LU which, at
    # 64k cells, cost ~56 s/solve: the Lagrange border row/column destroyed the
    # sparse fill pattern, making the LU factor near-dense. L is the pure 7-point
    # connectivity Laplacian — a function of (Nx,Ny,Nz) only — so it and its AMG
    # hierarchy are built once (`_laplacian_amg_cache`) and reused everywhere.
    #
    # The bordered Lagrange system [[L,e],[eᵀ,0]][φ;μ]=[D;0] is algebraically
    # equivalent to solving L φ = D − mean(D) with mean(φ)=0 (μ = mean(D)).
    # Projecting D onto range(L) (subtract its mean) makes the singular system
    # consistent for CG; de-meaning φ afterwards removes the null-space part.
    # Both the operator and the mean-zero constraint are reflection-symmetric,
    # so a z-even D yields a z-even φ — preserving the 2026-06-09 z-symmetry fix
    # WITHOUT the corner-pin that originally broke it.
    cache = _laplacian_amg_cache(Nx, Ny, Nz)
    L = cache['L']
    D0 = D - D.mean()
    M = cache['ml'].aspreconditioner(cycle='V')
    from scipy.sparse.linalg import cg as _cg
    phi_flat, info = _cg(L, D0, M=M, rtol=1e-10, maxiter=500)
    if info != 0:
        # Robustness fallback: the original dense-bordered direct solve (exact
        # and symmetric, just slow). Should never trigger for a well-posed L.
        from scipy.sparse import bmat
        e = np.ones((n, 1))
        L_aug = bmat([[L, e], [e.T, None]], format='csr')
        phi_flat = spsolve(L_aug, np.concatenate([D, [0.0]]))[:n]
    phi_flat = phi_flat - phi_flat.mean()
    phi = phi_flat.reshape(Nx, Ny, Nz)

    # Correct interior faces only. With L φ = D (L = graph Laplacian), the
    # per-cell post-correction divergence is D − Lφ = 0 iff the face flux is
    # adjusted by δF_face = +(φ[c+] − φ[c−]) along +axis ⇒ u* = u + δF/C.
    uf = uf.copy(); vf = vf.copy(); wf = wf.copy()
    if Nx > 1:
        dF = phi[1:, :, :] - phi[:-1, :, :]
        uf[1:-1, :, :] += dF / (Cx + 1e-30)
    if Ny > 1:
        dF = phi[:, 1:, :] - phi[:, :-1, :]
        vf[:, 1:-1, :] += dF / (Cy + 1e-30)
    if Nz > 1:
        dF = phi[:, :, 1:] - phi[:, :, :-1]
        wf[:, :, 1:-1] += dF / (Cz + 1e-30)
    return (np.ascontiguousarray(uf), np.ascontiguousarray(vf),
            np.ascontiguousarray(wf))


# Denominator floor (W) for the relative strict-conservation metric. Guards the
# degenerate no-net-heat-exchange cases (equi-T, or one fluid disabled so solid
# equilibrates to the live fluid) where ∫S → 0 and a relative residual divides
# by ~0. Real audit/production sources are O(100 W) ≫ floor, so unaffected; in
# the degenerate cases the absolute residual is machine-level, so eps → ~0.
_Q_FLOOR_W = 1.0


def _conservation_residual_sum(T, Ts, uf, vf, wf, eps_f, K, rcp, hv,
                               dx, dy, dz, dir_code, Tin, ifrac, mms_source,
                               inlet_flux=None, model_mass=None, model_cp=None,
                               return_field=False):
    """Full-CV conservative temperature-equation residual for one fluid phase (B-plan B2).

    Evaluates, on the CONVERGED field, the residual of the *conservative*
    discrete energy equation per cell — using the exact same shared face
    fluxes, harmonic-mean diffusion and hybrid-upwind coefficients as the
    conservative kernel, with the (F_e−F_w+…) net-out term in a_P:

        r[c] = a_P·T_c − Σ a_nb·T_nb − h_v·V·Ts

    All actual cells, including both end layers, are included. The physical
    inlet has Tin and half-cell diffusion; other exterior diffusion is zero.
    Returns (sum residual, full-volume solid exchange, max cell residual).
    With model_mass, rebuild nonlinear model-h fluxes at the returned T.
    Otherwise this certifies the original capacity-temperature discretisation.
    """
    Nx, Ny, Nz = T.shape
    Ax = (dy[None, :, None] * dz[None, None, :])
    Ay = (dx[:, None, None] * dz[None, None, :])
    Az = (dx[:, None, None] * dy[None, :, None])
    vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]

    # Kernel interpolates eps and rho*cp separately, then multiplies them.
    face_coefs = []
    for axis in range(3):
        ef = np.moveaxis(eps_f, axis, 0)
        rc = np.moveaxis(rcp, axis, 0)
        cf = np.empty((ef.shape[0] + 1, *ef.shape[1:]))
        cf[1:-1] = 0.25 * (ef[:-1] + ef[1:]) * (rc[:-1] + rc[1:])
        cf[0] = ef[0] * rc[0]; cf[-1] = ef[-1] * rc[-1]
        face_coefs.append(np.moveaxis(cf, 0, axis))
    cf_x, cf_y, cf_z = face_coefs
    Fx = cf_x * uf * np.broadcast_to(Ax, uf.shape)   # (Nx+1,Ny,Nz)
    Fy = cf_y * vf * np.broadcast_to(Ay, vf.shape)
    Fz = cf_z * wf * np.broadcast_to(Az, wf.shape)
    if inlet_flux is not None:
        inlet_face = np.moveaxis((Fx, Fy, Fz)[dir_code // 2], dir_code // 2, 0)[
            0 if dir_code % 2 == 0 else -1]
        inlet_face[:] = np.where(
            ifrac > 0.0, inlet_flux * (1.0 if dir_code % 2 == 0 else -1.0), inlet_face)
    if model_mass is not None:
        (Fx, Fy, Fz), deferred = _model_h_faces(
            T, model_mass, model_cp, dir_code, Tin, ifrac)
    Fe = Fx[1:]; Fw = Fx[:-1]; Fn = Fy[:, 1:]; Fs = Fy[:, :-1]
    Ft = Fz[:, :, 1:]; Fb = Fz[:, :, :-1]
    net_out = (Fe - Fw) + (Fn - Fs) + (Ft - Fb)

    # Harmonic-mean diffusion conductances, shared faces (matches kernel).
    dxe = 0.5 * (dx[:-1] + dx[1:]); dyn = 0.5 * (dy[:-1] + dy[1:])
    dzt = 0.5 * (dz[:-1] + dz[1:])
    dE = np.zeros_like(T); dW = np.zeros_like(T)
    dN = np.zeros_like(T); dS = np.zeros_like(T)
    dT_ = np.zeros_like(T); dB = np.zeros_like(T)
    if Nx > 1:
        h = 2.0 * K[:-1] * K[1:] / (K[:-1] + K[1:] + 1e-30) \
            * np.broadcast_to(Ax, (Nx - 1, Ny, Nz)) / dxe[:, None, None]
        dE[:-1] = h; dW[1:] = h
    if Ny > 1:
        h = 2.0 * K[:, :-1] * K[:, 1:] / (K[:, :-1] + K[:, 1:] + 1e-30) \
            * np.broadcast_to(Ay, (Nx, Ny - 1, Nz)) / dyn[None, :, None]
        dN[:, :-1] = h; dS[:, 1:] = h
    if Nz > 1:
        h = 2.0 * K[:, :, :-1] * K[:, :, 1:] / (K[:, :, :-1] + K[:, :, 1:] + 1e-30) \
            * np.broadcast_to(Az, (Nx, Ny, Nz - 1)) / dzt[None, None, :]
        dT_[:, :, :-1] = h; dB[:, :, 1:] = h

    aE = dE + np.maximum(-Fe, 0.0); aW = dW + np.maximum(Fw, 0.0)
    aN = dN + np.maximum(-Fn, 0.0); aS = dS + np.maximum(Fs, 0.0)
    aT = dT_ + np.maximum(-Ft, 0.0); aB = dB + np.maximum(Fb, 0.0)
    aP = aE + aW + aN + aS + aT + aB + net_out + hv * vol

    # Neighbour T with boundary = self (kernel convention).
    TE = T.copy(); TE[:-1] = T[1:]
    TW = T.copy(); TW[1:] = T[:-1]
    TN = T.copy(); TN[:, :-1] = T[:, 1:]
    TS = T.copy(); TS[:, 1:] = T[:, :-1]
    TT = T.copy(); TT[:, :, :-1] = T[:, :, 1:]
    TB = T.copy(); TB[:, :, 1:] = T[:, :, :-1]
    r = (aP * T - aE * TE - aW * TW - aN * TN - aS * TS - aT * TT - aB * TB
         - hv * vol * Ts)
    # Subtract the conservative HO deferred source so this measures the TRUE
    # residual of the equation the kernel actually solves (FO implicit + sou).
    # The sou itself telescopes, so conservation is preserved; r → 0 at
    # convergence. (For pure-upwind it is identically 0 ⇒ no-op.)
    r = (r + _face_divergence(deferred) if model_mass is not None
         else r - _sou_field_cons(T, Fx, Fy, Fz))

    axis = dir_code // 2
    sl = [slice(None)] * 3
    sl[axis] = 0 if dir_code % 2 == 0 else -1
    sl = tuple(sl)
    area = np.broadcast_to((Ax, Ay, Az)[axis], T.shape)[sl]
    dn = (dx, dy, dz)[axis][0 if dir_code % 2 == 0 else -1]
    Din = 2.0 * K[sl] * area * ifrac / dn
    incoming = (np.maximum(Fw, 0.0), np.maximum(-Fe, 0.0),
                np.maximum(Fs, 0.0), np.maximum(-Fn, 0.0),
                np.maximum(Fb, 0.0), np.maximum(-Ft, 0.0))[dir_code][sl]
    r[sl] += (Din + np.where(ifrac > 0.0, incoming, 0.0)) * (T[sl] - Tin)
    r -= mms_source * vol
    src = hv * vol * (Ts - T)
    if return_field:
        return r, src, Din * (Tin - T[sl])
    return float(np.sum(r)), float(np.sum(src)), float(np.max(np.abs(r)))


# ---------------------------------------------------------------------------
# Numba kernels — moved verbatim to _kernels_ltne_3d.py (openspec
# split-solver-kernels, 2026-07-03); bit-identical, epsilon-split contract
# untouched. Re-exported here so existing imports keep working (e.g.
# `from solvers.ltne_energy_3d import _gs_full_chunk_3d_stag` in
# validation/cases/mms_3d_air_air.py, and _warmup_jit below).
# ---------------------------------------------------------------------------
from ._kernels_ltne_3d import (  # noqa: F401
    _va_limit,
    _sou_corr_x_3d,
    _sou_corr_y_3d,
    _sou_corr_z_3d,
    _sou_face_x_cons,
    _sou_face_y_cons,
    _sou_face_z_cons,
    _sou_field_cons,
    _model_h,
    _model_h_faces,
    _face_divergence,
    _is_inlet,
    _inlet_frac,
    _inlet_val,
    _gs_full_chunk_3d_stag,
    _gs_full_chunk_3d_stag_rb,
    _is_bc_face_inlet,
    _is_bc_face_outlet,
    _ifrac_at_face,
    _Tin_at_face,
    _gs_full_chunk_3d,
)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def _inlet_transport_3d(faces, eps_f, rho, cp_in, dx, dy, dz, direction):
    """Actual SIMPLE inlet face mass times physical inlet cp (W/K)."""
    axis = direction // 2
    index = 0 if direction % 2 == 0 else -1
    shape = (len(dx), len(dy), len(dz))
    coefficient = np.broadcast_to(eps_f, shape) * np.broadcast_to(rho, shape) * cp_in
    cross = [width for dim, width in enumerate((dx, dy, dz)) if dim != axis]
    area = cross[0][:, None] * cross[1][None, :]
    return np.ascontiguousarray(
        np.take(coefficient, index, axis=axis) * np.take(faces[axis], index, axis=axis)
        * area * (1.0 if direction % 2 == 0 else -1.0))


def _delegate_to_2d(L, H, D, Nx, Ny, Nz,
                    T_inA, T_inB,
                    K_ffA, K_ffB, K_ss,
                    h_vA, h_vB,
                    rho_cp_fA, rho_cp_fB,
                    epsilon,
                    ucA, vcA, wcA, ucB, vcB, wcB,
                    dir_A, dir_B,
                    T_inA_profile, T_inB_profile,
                    max_iter, tol,
                    progress_cb, return_info,
                    Ta_init, Tb_init, Ts_init,
                    dx_arr, dy_arr, dz_arr,
                    inlet_mask_A, inlet_mask_B,
                    Tb_prescribed,
                    alpha_T,
                    q_rel_tol=None, conv_chunk=None,
                    eps_A=None, eps_B=None,
                    chi_B_field=None,
                    mms_S_A_field=None, mms_S_B_field=None,
                    mms_S_s_field=None, cancel_check=None, inlet_flux_A=None, inlet_flux_B=None):
    """Nz == 1 shortcut: squeeze z axis and call 2D solver for bitwise equivalence.
    alpha_T is accepted but ignored (2D uses Q-chunk convergence).
    q_rel_tol / conv_chunk passed through to the 2D solver (None = legacy).

    Kwarg contract (2026-07-13 audit — these used to be dropped SILENTLY):
      * eps_A / eps_B — forwarded (the 2D solver has the same asym hooks);
        dropping them reverted a δ≠0 asymmetric Nz=1 call to the symmetric
        ε/2 split with converged=True.
      * chi_B_field / mms_S_* — no 2D equivalent: RAISE instead of silently
        solving a different problem.
      * conservative_ltne — intentionally NOT forwarded: the 2D solver's own
        A3 signed shared-face scheme is its conservative form, and the Nz=1
        delegate has always mapped onto it (the Nz=1 bitwise regression pins
        this). Staggered ufA..wfB faces are unused for the same reason.
    """
    if chi_B_field is not None:
        raise NotImplementedError(
            "Nz==1 delegates to the 2D LTNE solver, which has no chi_B_field "
            "hook — refusing to silently drop it. Use Nz >= 2.")
    if any(s is not None for s in (mms_S_A_field, mms_S_B_field,
                                   mms_S_s_field)):
        raise NotImplementedError(
            "Nz==1 delegates to the 2D LTNE solver, which has no MMS source "
            "hooks — refusing to silently drop them. Use Nz >= 2.")

    def _sq3(a):
        if a is None:
            return None
        a = np.asarray(a)
        if a.ndim == 3 and a.shape[-1] == 1:
            return np.ascontiguousarray(a[..., 0])
        return a

    def _sq_mask(m, dir_code):
        if m is None:
            return None
        m = np.asarray(m)
        # 2D (n,1) collapsed to 1D when dir_code <= 3 and z extent is 1
        if m.ndim == 2 and m.shape[1] == 1:
            return np.ascontiguousarray(m[:, 0])
        if m.ndim == 2:
            return np.ascontiguousarray(m[:, 0])
        return m

    # Ask the 2D solver for its REAL verdict when the caller wants info.
    # This used to pass return_info=False unconditionally and then hard-code
    # {'converged': True, 'iterations': -1, 'residual': 0.0} — so every Nz==1
    # run reported a converged LTNE inner pass no matter what the delegated 2D
    # solve actually did, and that lie propagated straight into
    # `solver_converged` (run_stack_3d.py). Audit 2026-07-12.
    _d2 = _solve_full_2d(
        L, H, Nx, Ny,
        T_inA, T_inB,
        _sq3(K_ffA) if np.ndim(K_ffA) > 0 else K_ffA,
        _sq3(K_ffB) if np.ndim(K_ffB) > 0 else K_ffB,
        _sq3(K_ss)  if np.ndim(K_ss)  > 0 else K_ss,
        _sq3(h_vA)  if np.ndim(h_vA)  > 0 else h_vA,
        _sq3(h_vB)  if np.ndim(h_vB)  > 0 else h_vB,
        _sq3(rho_cp_fA) if np.ndim(rho_cp_fA) > 0 else rho_cp_fA,
        _sq3(rho_cp_fB) if np.ndim(rho_cp_fB) > 0 else rho_cp_fB,
        _sq3(epsilon) if np.ndim(epsilon) > 0 else epsilon,
        _sq3(ucA), _sq3(vcA), _sq3(ucB), _sq3(vcB),
        dir_A, dir_B,
        T_inA_profile=T_inA_profile, T_inB_profile=T_inB_profile,
        max_iter=max_iter, tol=tol,
        progress_cb=progress_cb, return_info=return_info,
        Ta_init=_sq3(Ta_init), Tb_init=_sq3(Tb_init), Ts_init=_sq3(Ts_init),
        dx_arr=dx_arr, dy_arr=dy_arr,
        inlet_mask_A=_sq_mask(inlet_mask_A, dir_A),
        inlet_mask_B=_sq_mask(inlet_mask_B, dir_B),
        Tb_prescribed=_sq3(Tb_prescribed),
        eps_A=_sq3(eps_A), eps_B=_sq3(eps_B),
        q_rel_tol=q_rel_tol, conv_chunk=conv_chunk, cancel_check=cancel_check,
        inlet_flux_A=None if inlet_flux_A is None else _sq_mask(inlet_flux_A, dir_A) / D,
        inlet_flux_B=None if inlet_flux_B is None else _sq_mask(inlet_flux_B, dir_B) / D)

    if return_info:
        Ta2, Tb2, Ts2, _info2 = _d2
    else:
        Ta2, Tb2, Ts2 = _d2
    Ta3 = Ta2[..., None].copy()
    Tb3 = Tb2[..., None].copy()
    Ts3 = Ts2[..., None].copy()
    if return_info:
        return Ta3, Tb3, Ts3, {**_info2, 'delegated_to_2d': True}
    return Ta3, Tb3, Ts3


# Diagnostic-only convergence trace (point 0 quantify, 2026-05-22). When set
# to a list, the LTNE loop appends per-chunk (done, rel_chg, max|ΔT|, mean|ΔT|,
# Q_B) so a caller can tell slow-but-converging from stalled/oscillating.
# None in production → zero overhead, no behaviour change.
_CONV_TRACE = None

# Energy GS kernel selector. The red-black `prange`-parallel twin
# (`_gs_full_chunk_3d_stag_rb`) converges to the same solution as the serial
# lexicographic `_gs_full_chunk_3d_stag` but uses all cores. Gated by grid size:
# below `_RB_ENERGY_GATE` cells the thread-launch overhead outweighs the benefit
# AND small grids stay bit-for-bit on the proven serial reference (so the test
# suite is unaffected). Set `_RB_ENERGY=False` to force serial everywhere.
_RB_ENERGY = True
_RB_ENERGY_GATE = 30_000


def _model_h_balance(temperatures, Ts, masses, coefficients, directions, inlets,
                     masks, conductivities, Kss, exchanges, porosities, sources,
                     solid_source, dx, dy, dz):
    """Last returned thermal state; no EOS, flow correction or physical PASS."""
    volume = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    zeros = np.zeros_like(Ts)
    zero_faces = tuple(np.zeros_like(f) for f in masses[0])
    result = dict(reference_K=coefficients[0][4], cell_count=int(Ts.size),
                  full_volume_m3=float(volume.sum()),
                  mass_source='completed SIMPLE raw faces before capacity balance/MAC',
                  thermal_state='last returned temperatures; nonlinear model h and temperature SOU',
                  sides={}, _native_faces={})
    residuals = []
    exchange_fields = []
    for side, T, mass, coeff, direction, Tin, mask, K, hv, eps, source in zip(
            ('A', 'B'), temperatures, masses, coefficients, directions, inlets,
            masks, conductivities, exchanges, porosities, sources):
        capacity, deferred = _model_h_faces(T, mass, coeff, direction, Tin, mask)
        r, exchange, inlet_diffusion = _conservation_residual_sum(
            T, Ts, *zero_faces, eps, K, zeros, hv, dx, dy, dz, direction, Tin,
            mask, source, model_mass=mass, model_cp=coeff, return_field=True)
        faces = {}
        native_faces = {}
        for axis in range(3):
            for end, sign in ((0, -1), (-1, 1)):
                face_T = np.take(T, end, axis=axis)
                outward_mass = sign * np.take(mass[axis], end, axis=axis)
                inlet = axis == direction // 2 and end == (0 if direction % 2 == 0 else -1)
                patch = mask > 0 if inlet else np.zeros_like(face_T, dtype=bool)
                inflow = outward_mass < 0.0
                up_T = np.where(patch & inflow, Tin if inlet else face_T, face_T)
                energy = sign * (np.take(capacity[axis], end, axis=axis) * up_T
                                 + np.take(deferred[axis], end, axis=axis))
                native_faces['xyz'[axis] + ('-' if end == 0 else '+')] = energy.copy()
                unknown = inflow & ~patch
                faces['xyz'[axis] + ('-' if end == 0 else '+')] = dict(
                    outward_mass_kg_s=float(outward_mass.sum()),
                    outward_model_h_W=float(energy.sum()),
                    non_inlet_inward_mass_kg_s=float(-outward_mass[unknown].sum()),
                    unknown_inflow_count=int(unknown.sum()),
                    inlet_reverse_outward_mass_kg_s=float(outward_mass[patch & ~inflow].sum()))
        result['_native_faces'][side] = native_faces
        complete = all(f['unknown_inflow_count'] == 0 for f in faces.values())
        convective_inward = -sum(f['outward_model_h_W'] for f in faces.values())
        diffusion_inward = float(inlet_diffusion.sum())
        result['sides'][side] = dict(
            faces=faces, physical_boundary_complete=complete,
            model_cp_coefficients=list(coeff),
            temperature_range_K=[float(T.min()), float(T.max())],
            net_outward_mass_kg_s=sum(f['outward_mass_kg_s'] for f in faces.values()),
            convective_inward_W=convective_inward,
            inlet_diffusion_inward_W=diffusion_inward,
            numerical_external_inward_W=convective_inward+diffusion_inward,
            physical_external_inward_W=convective_inward+diffusion_inward if complete else None,
            fluid_solid_exchange_to_fluid_W=float(exchange.sum()),
            explicit_source_W=float((source*volume).sum()),
            residual_sum_W=float(r.sum()), residual_max_abs_W=float(np.max(np.abs(r))),
            strict_normalization_W=max(abs(float(exchange.sum())), _Q_FLOOR_W))
        residuals.append(r)
        exchange_fields.append(exchange)
    # Reuse the existing nonuniform conduction operator for the solid, with
    # zero advection/inlet area; exchange cancels the two fluid equations.
    rsolid, _, _ = _conservation_residual_sum(
        Ts, Ts, *zero_faces, porosities[0], Kss, zeros, zeros, dx, dy, dz, 0,
        Ts[0], np.zeros_like(Ts[0]), solid_source, return_field=True)
    rsolid += exchange_fields[0] + exchange_fields[1]
    all_residual = residuals[0] + residuals[1] + rsolid
    external = sum(s['numerical_external_inward_W'] for s in result['sides'].values())
    explicit = float(((sources[0]+sources[1]+solid_source)*volume).sum())
    complete = all(s['physical_boundary_complete'] for s in result['sides'].values())
    result.update(
        physical_boundary_complete=complete,
        numerical_external_inward_W=external,
        physical_external_inward_W=external if complete else None,
        explicit_source_W=explicit, solid_external_diffusion_W=0.0,
        solid_residual_sum_W=float(rsolid.sum()),
        solid_residual_max_abs_W=float(np.max(np.abs(rsolid))),
        full_residual_sum_W=float(all_residual.sum()),
        telescoping_error_W=float(all_residual.sum())+external+explicit,
        qualification='No physical acceptance inferred. Non-inlet inflow uses numerical self-extrapolation; its external h is unspecified.')
    return result


def solve_full_domain_3d(L, H, D, Nx, Ny, Nz,
                          T_inA, T_inB,
                          K_ffA, K_ffB, K_ss,
                          h_vA, h_vB,
                          rho_cp_fA, rho_cp_fB,
                          epsilon,
                          ucA, vcA, wcA, ucB, vcB, wcB,
                          dir_A, dir_B,
                          T_inA_profile=None, T_inB_profile=None,
                          max_iter=10000, tol=1e-6,
                          progress_cb=None, return_info=False,
                          Ta_init=None, Tb_init=None, Ts_init=None,
                          dx_arr=None, dy_arr=None, dz_arr=None,
                          inlet_mask_A=None, inlet_mask_B=None,
                          Tb_prescribed=None,
                          alpha_T=0.7,
                          alpha_T_s=None, alpha_T_fA=None, alpha_T_fB=None,
                          eps_A=None, eps_B=None,
                          ufA=None, vfA=None, wfA=None,
                          ufB=None, vfB=None, wfB=None,
                          chi_B_field=None,
                          chi_B_kernel_threshold=0.0,
                          mms_S_A_field=None,
                          mms_S_B_field=None,
                          mms_S_s_field=None,
                          conservative_ltne=False,
                          cancel_check=None,
                          q_rel_tol=None, conv_chunk=None, inlet_flux_A=None, inlet_flux_B=None,
                          model_mass_A=None, model_mass_B=None, model_fluids=None):
    """3D full-domain 2-fluid LTNE solver (Ta, Tb, Ts).

    Shape contracts
    ---------------
    K_ffA/K_ffB/K_ss, h_vA/h_vB, rho_cp_fA/rho_cp_fB : scalar or (Nx, Ny, Nz).
    epsilon : scalar or (Nx, Ny, Nz). **Pass the FULL porosity ε_full**
              (= ε_A + ε_B for symmetric Gyroid). The kernel internally
              applies a SINGLE halving `eps_f = 0.5 * epsilon` (see
              ~line 1391) to get the single-channel ε_A = ε_full/2 used
              in the convective face flux F = ε_f · ρcp · u · A_face.
              Do NOT pre-halve at the call site — that double-halves to
              ε_full/4 (the 2026-05-14 regression; fixed under Option A
              on 2026-05-19, every production caller now passes full ε,
              guarded by tests/test_eps_contract_3d.py). The explicit
              `eps_A` / `eps_B` kwargs below ARE single-channel and are
              consumed without further halving. Rationale + Shanghai
              case-1 evidence: the historical run_calculation_3d.py
              comment (now the ε-contract block in pipelines/run_stack_3d).
    ucA/vcA/wcA/ucB/vcB/wcB    : (Nx, Ny, Nz) cell-centre.
    dir_A/dir_B ∈ {0=+x, 1=-x, 2=+y, 3=-y, 4=+z, 5=-z}.
    inlet_mask_*               : 2D cross-section or None.
    inlet_flux_A/B             : optional signed inward eps*rho*cp*u*A (W/K)
                                at physical inlet faces, separate from internal
                                cell capacity coefficients in CC/staggered modes.
    alpha_T                    : 0 < α ≤ 1 under-relax (default 0.7).

    Nz == 1 fast path: delegates to solvers.ltne_energy.solve_full_domain
    (bitwise-identical Nz=1 regression).
    """
    Nx, Ny, Nz = int(Nx), int(Ny), int(Nz)
    model_enabled = any(x is not None for x in (model_mass_A, model_mass_B, model_fluids))
    model_cp_A = model_cp_B = None
    if model_enabled:
        if (model_mass_A is None or model_mass_B is None
                or model_fluids not in (('air', 'air'), ('air', 'water'), ('water', 'air'))
                or Nz <= 1 or not conservative_ltne or Tb_prescribed is not None
                or chi_B_kernel_threshold > 0.0 or eps_A is not None or eps_B is not None):
            raise ValueError('model h requires unmasked symmetric 3D AA/AW/WA with two solved fluids')
        shapes = ((Nx+1, Ny, Nz), (Nx, Ny+1, Nz), (Nx, Ny, Nz+1))
        for mass in (model_mass_A, model_mass_B):
            if len(mass) != 3 or any(np.shape(f) != shape or not np.all(np.isfinite(f))
                                     for f, shape in zip(mass, shapes)):
                raise ValueError('model h requires finite signed staggered mass faces')
        model_mass_A = tuple(np.ascontiguousarray(f, dtype=np.float64) for f in model_mass_A)
        model_mass_B = tuple(np.ascontiguousarray(f, dtype=np.float64) for f in model_mass_B)
        model_cp_A, model_cp_B = (model_h_coefficients(fluid) for fluid in model_fluids)

    def _inlet_shape(dir_code):
        if dir_code <= 1: return (Ny, Nz)
        if dir_code <= 3: return (Nx, Nz)
        return (Nx, Ny)

    inlet_flux_A, inlet_flux_B = (
        None if flux is None else np.ascontiguousarray(flux, dtype=np.float64)
        for flux in (inlet_flux_A, inlet_flux_B))
    for name, flux, direction in (('A', inlet_flux_A, dir_A), ('B', inlet_flux_B, dir_B)):
        if flux is not None and (
                np.shape(flux) != _inlet_shape(direction) or not np.all(np.isfinite(flux))):
            raise ValueError(f"inlet_flux_{name} must be finite with shape {_inlet_shape(direction)}")

    if Nz == 1:
        return _delegate_to_2d(
            L, H, D, Nx, Ny, Nz, T_inA, T_inB,
            K_ffA, K_ffB, K_ss, h_vA, h_vB,
            rho_cp_fA, rho_cp_fB, epsilon,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A, dir_B,
            T_inA_profile, T_inB_profile,
            max_iter, tol, progress_cb, return_info,
            Ta_init, Tb_init, Ts_init,
            dx_arr, dy_arr, dz_arr,
            inlet_mask_A, inlet_mask_B, Tb_prescribed, alpha_T,
            q_rel_tol=q_rel_tol, conv_chunk=conv_chunk,
            eps_A=eps_A, eps_B=eps_B,
            chi_B_field=chi_B_field,
            mms_S_A_field=mms_S_A_field, mms_S_B_field=mms_S_B_field,
            mms_S_s_field=mms_S_s_field, cancel_check=cancel_check,
            inlet_flux_A=inlet_flux_A, inlet_flux_B=inlet_flux_B)

    if not (0.0 < alpha_T <= 1.0):
        raise ValueError(f"alpha_T must be in (0, 1], got {alpha_T}")
    # Three-phase under-relax: default to common alpha_T, override per phase if given.
    a_s  = float(alpha_T if alpha_T_s  is None else alpha_T_s)
    a_fA = float(alpha_T if alpha_T_fA is None else alpha_T_fA)
    a_fB = float(alpha_T if alpha_T_fB is None else alpha_T_fB)
    for name, v in (('alpha_T_s', a_s), ('alpha_T_fA', a_fA), ('alpha_T_fB', a_fB)):
        if not (0.0 < v <= 1.0):
            raise ValueError(f"{name} must be in (0, 1], got {v}")

    # Grid arrays
    if dx_arr is None:
        dx_arr = np.full(Nx, L / Nx, dtype=np.float64)
    else:
        dx_arr = np.ascontiguousarray(dx_arr, dtype=np.float64)
    if dy_arr is None:
        dy_arr = np.full(Ny, H / Ny, dtype=np.float64)
    else:
        dy_arr = np.ascontiguousarray(dy_arr, dtype=np.float64)
    if dz_arr is None:
        dz_arr = np.full(Nz, D / Nz, dtype=np.float64)
    else:
        dz_arr = np.ascontiguousarray(dz_arr, dtype=np.float64)

    def _to_3d(val):
        if np.ndim(val) == 0:
            return np.full((Nx, Ny, Nz), float(val), dtype=np.float64)
        arr = np.asarray(val, dtype=np.float64)
        if arr.shape != (Nx, Ny, Nz):
            raise ValueError(f"field shape {arr.shape} != ({Nx}, {Ny}, {Nz})")
        return np.ascontiguousarray(arr)

    K_ffA_arr = _to_3d(K_ffA)
    K_ffB_arr = _to_3d(K_ffB)
    K_ss_arr  = _to_3d(K_ss)
    h_vA_arr  = _to_3d(h_vA)
    h_vB_arr  = _to_3d(h_vB)
    rho_cp_fA_arr = _to_3d(rho_cp_fA)
    rho_cp_fB_arr = _to_3d(rho_cp_fB)

    # Per-fluid single-channel void fractions. Default (eps_A/eps_B None) =
    # symmetric ε_A = ε_B = ε/2 — both names bind the SAME array object, so the
    # dual-ε kernel reproduces the legacy single-eps_f arithmetic bit-for-bit.
    # Explicit eps_A/eps_B (asymmetric offset-isosurface δ) are single-channel
    # per-side fractions, routed per-side through the kernel WITHOUT further
    # halving (caller passes ε_A, ε_B directly; see docstring).
    if eps_A is None and eps_B is None:
        if np.ndim(epsilon) == 0:
            eps_fA_arr = np.full((Nx, Ny, Nz), 0.5 * float(epsilon), dtype=np.float64)
        else:
            eps_fA_arr = np.ascontiguousarray(0.5 * np.asarray(epsilon, dtype=np.float64))
            if eps_fA_arr.shape != (Nx, Ny, Nz):
                raise ValueError("epsilon 3D shape mismatch")
        eps_fB_arr = eps_fA_arr
    else:
        if eps_A is None or eps_B is None:
            raise ValueError("eps_A and eps_B must be provided together.")
        eps_fA_arr = _to_3d(eps_A)
        eps_fB_arr = _to_3d(eps_B)
        eps_tot_arr = _to_3d(epsilon)
        # Two-sided (2026-07-13 audit; mirrors ltne_energy.py): a sum BELOW ε
        # means pre-halved per-side values (double-halving bug class) — fail
        # loud instead of running with half the convective capacity.
        if np.any(np.abs(eps_fA_arr + eps_fB_arr - eps_tot_arr) > 1e-9):
            raise ValueError(
                "eps_A + eps_B must equal epsilon cell-wise (they partition "
                "the total void fraction; a sum below it usually means "
                "pre-halved per-side values — double-halving bug class).")

    # Cell-centre velocity shape check
    for name, arr in (('ucA', ucA), ('vcA', vcA), ('wcA', wcA),
                      ('ucB', ucB), ('vcB', vcB), ('wcB', wcB)):
        if np.asarray(arr).shape != (Nx, Ny, Nz):
            raise ValueError(f"{name} shape {np.asarray(arr).shape} != ({Nx}, {Ny}, {Nz})")
    ucA = np.ascontiguousarray(ucA, dtype=np.float64)
    vcA = np.ascontiguousarray(vcA, dtype=np.float64)
    wcA = np.ascontiguousarray(wcA, dtype=np.float64)
    ucB = np.ascontiguousarray(ucB, dtype=np.float64)
    vcB = np.ascontiguousarray(vcB, dtype=np.float64)
    wcB = np.ascontiguousarray(wcB, dtype=np.float64)

    # Inlet profiles — 2D cross-section
    def _mk_profile(profile, T_scalar, shape):
        if profile is None:
            return np.full(shape, float(T_scalar), dtype=np.float64)
        arr = np.asarray(profile, dtype=np.float64)
        if arr.shape == shape:
            return np.ascontiguousarray(arr)
        if arr.ndim == 1:
            # broadcast 1D to 2D face (uniform along other axis)
            return np.ascontiguousarray(np.broadcast_to(
                np.interp(np.linspace(0, 1, shape[0]),
                          np.linspace(0, 1, len(arr)), arr)[:, None],
                shape).copy())
        raise ValueError(f"inlet profile shape {arr.shape} != {shape}")

    T_inA_arr = _mk_profile(T_inA_profile, T_inA, _inlet_shape(dir_A))
    T_inB_arr = _mk_profile(T_inB_profile, T_inB, _inlet_shape(dir_B))

    def _mk_mask(mask, shape):
        if mask is None:
            return np.ones(shape, dtype=np.float64)
        arr = np.asarray(mask, dtype=np.float64)
        if arr.shape == shape:
            return np.ascontiguousarray(arr)
        if arr.ndim == 1:
            return np.ascontiguousarray(np.broadcast_to(arr[:, None], shape).copy())
        raise ValueError(f"inlet mask shape {arr.shape} != {shape}")

    ifrac_A = _mk_mask(inlet_mask_A, _inlet_shape(dir_A))
    ifrac_B = _mk_mask(inlet_mask_B, _inlet_shape(dir_B))

    # Initial guesses only: every physical end CV subsequently solves its equation.
    if Ta_init is not None:
        Ta = np.ascontiguousarray(Ta_init.copy(), dtype=np.float64)
        Tb = np.ascontiguousarray(Tb_init.copy(), dtype=np.float64)
        Ts = np.ascontiguousarray(Ts_init.copy(), dtype=np.float64)
    else:
        # Each fluid starts at its inlet temperature; solid starts midway.
        Ta = np.full((Nx, Ny, Nz), float(T_inA), dtype=np.float64)
        Tb = np.full((Nx, Ny, Nz), float(T_inB), dtype=np.float64)
        Ts = np.full((Nx, Ny, Nz), 0.5 * (T_inA + T_inB), dtype=np.float64)

    freeze_Tb = 0
    if Tb_prescribed is not None:
        Tb_arr = np.ascontiguousarray(np.asarray(Tb_prescribed, dtype=np.float64))
        if Tb_arr.shape != (Nx, Ny, Nz):
            raise ValueError(f"Tb_prescribed shape {Tb_arr.shape} != ({Nx}, {Ny}, {Nz})")
        Tb = Tb_arr.copy()
        freeze_Tb = 1

    # Chunk iterate, convergence = (Q stable) AND (field stable per chunk).
    # chunk=250 (2026-06-24): the old chunk=500 forced >=2 chunks (=1000 sweeps)
    # because the first Q-delta check is skipped (Q_prev starts at 0), so a
    # field that converged within the first chunk still ran a second, fully
    # redundant one (measured: the 2nd 500-sweep chunk changed the 40^3 field by
    # 1.7e-13 — pure waste; halving energy time at identical Q/dP). A finer
    # chunk detects convergence earlier. The tiny-grid false-exit the old
    # comment guarded against is now prevented by the `max ΔT < T_abs_tol`
    # AND-guard in the convergence test below (Q-stable alone could false-exit;
    # Q-stable AND field-stable cannot), so 250 is safe on small grids too.
    chunk = 250 if conv_chunk is None else int(conv_chunk); done = 0
    cell_vol = dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :]
    Q_prev = 0.0
    Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()
    converged = False
    q_tol = max(tol * 10.0, 1e-4) if q_rel_tol is None else float(q_rel_tol)
    T_abs_tol = 0.01  # K between chunks — mirror 2D ltne_energy.py (#4)
    chg = 0.0

    # Dispatch: if caller passed staggered face velocities (ufA, vfA, wfA)
    # use the mass-conserving staggered kernel; else fall back to the
    # legacy cell-centered kernel (still valid but has Q_enthalpy ↔ Q_source
    # drift on ρ-varying flows due to cell-averaged face u).
    use_stag = (ufA is not None and vfA is not None and wfA is not None
                and ufB is not None and vfB is not None and wfB is not None)
    # Strict energy-conservation path (B-plan B2): only the staggered kernel
    # carries the shared face fluxes needed for telescoping, so it is a hard
    # prerequisite for the conservative form.
    _cons = 1 if conservative_ltne else 0
    if conservative_ltne and not use_stag:
        raise ValueError(
            "conservative_ltne=True requires staggered face velocities "
            "(ufA/vfA/wfA + ufB/vfB/wfB); pass them (force_cc_ltne=False).")
    if use_stag:
        ufA = np.ascontiguousarray(ufA, dtype=np.float64)
        vfA = np.ascontiguousarray(vfA, dtype=np.float64)
        wfA = np.ascontiguousarray(wfA, dtype=np.float64)
        ufB = np.ascontiguousarray(ufB, dtype=np.float64)
        vfB = np.ascontiguousarray(vfB, dtype=np.float64)
        wfB = np.ascontiguousarray(wfB, dtype=np.float64)
        if ufA.shape != (Nx+1, Ny, Nz):
            raise ValueError(f"ufA shape {ufA.shape} != ({Nx+1}, {Ny}, {Nz})")
        if vfA.shape != (Nx, Ny+1, Nz):
            raise ValueError(f"vfA shape {vfA.shape} != ({Nx}, {Ny+1}, {Nz})")
        if wfA.shape != (Nx, Ny, Nz+1):
            raise ValueError(f"wfA shape {wfA.shape} != ({Nx}, {Ny}, {Nz+1})")

    # H6 ghost-pin support: build chi_B_arr (default ones) for kernel pass-through
    if chi_B_field is None:
        chi_B_arr = np.ones((Nx, Ny, Nz), dtype=np.float64)
    else:
        chi_B_arr = np.ascontiguousarray(chi_B_field, dtype=np.float64)
        if chi_B_arr.shape != (Nx, Ny, Nz):
            raise ValueError(
                f"chi_B_field shape {chi_B_arr.shape} != ({Nx},{Ny},{Nz})")
    chi_B_thr = float(chi_B_kernel_threshold)

    # MMS source field arrays (default zeros = no-op).
    def _mms_arr(field):
        if field is None:
            return np.zeros((Nx, Ny, Nz), dtype=np.float64)
        arr = np.ascontiguousarray(field, dtype=np.float64)
        if arr.shape != (Nx, Ny, Nz):
            raise ValueError(
                f"MMS source field shape {arr.shape} != ({Nx},{Ny},{Nz})")
        return arr
    mms_S_A_arr = _mms_arr(mms_S_A_field)
    mms_S_B_arr = _mms_arr(mms_S_B_field)
    mms_S_s_arr = _mms_arr(mms_S_s_field)

    # Project the original internal capacity faces. The specified physical
    # inlet F is applied afterwards and may change the boundary-CV divergence;
    # the residual below uses that new F rather than the old projection alone.
    if _cons == 1 and not model_enabled:
        ufA, vfA, wfA = _project_faces_div_free(
            ufA, vfA, wfA, eps_fA_arr, rho_cp_fA_arr, dx_arr, dy_arr, dz_arr)
        ufB, vfB, wfB = _project_faces_div_free(
            ufB, vfB, wfB, eps_fB_arr, rho_cp_fB_arr, dx_arr, dy_arr, dz_arr)

    while done < max_iter:
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        n = min(chunk, max_iter - done)
        if use_stag:
            _use_rb = _RB_ENERGY and (Nx * Ny * Nz > _RB_ENERGY_GATE)
            _stag_fn = (_gs_full_chunk_3d_stag_rb if _use_rb
                        else _gs_full_chunk_3d_stag)
            chg = _stag_fn(
                Ta, Tb, Ts, Nx, Ny, Nz,
                dx_arr, dy_arr, dz_arr,
                K_ffA_arr, K_ffB_arr, K_ss_arr,
                h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                rho_cp_fA_arr, rho_cp_fB_arr,
                ufA, vfA, wfA, ufB, vfB, wfB,
                dir_A, dir_B, T_inA_arr, T_inB_arr,
                ifrac_A, ifrac_B,
                n, freeze_Tb, a_fA, a_s, a_fB,
                chi_B_arr, chi_B_thr,
                mms_S_A_arr, mms_S_B_arr, mms_S_s_arr,
                _cons, inlet_flux_A, inlet_flux_B,
                model_mass_A, model_mass_B, model_cp_A, model_cp_B)
        else:
            chg = _gs_full_chunk_3d(
                Ta, Tb, Ts, Nx, Ny, Nz,
                dx_arr, dy_arr, dz_arr,
                K_ffA_arr, K_ffB_arr, K_ss_arr,
                h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                rho_cp_fA_arr, rho_cp_fB_arr,
                ucA, vcA, wcA, ucB, vcB, wcB,
                dir_A, dir_B, T_inA_arr, T_inB_arr,
                ifrac_A, ifrac_B,
                n, freeze_Tb, a_fA, a_s, a_fB, inlet_flux_A, inlet_flux_B)
        done += n
        if progress_cb:
            progress_cb(done, max_iter)
        # Cooperative cancel (point 4): bail between GS chunks so a long LTNE
        # solve aborts promptly instead of waiting out all max_iter sweeps.
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")

        # Convergence: AND of (relative ΔQ_B) and (max |ΔT*|). Q-only
        # could flag converged while Ta/Ts drifted — especially when Tb
        # is frozen (prescribed validation cases) the B-interface Q is
        # decoupled from A-side relaxation.
        Q_cur = float(np.sum(h_vB_arr * (Ts - Tb) * cell_vol))
        dTa_max = float(np.max(np.abs(Ta - Ta_prev)))
        dTb_max = float(np.max(np.abs(Tb - Tb_prev)))
        dTs_max = float(np.max(np.abs(Ts - Ts_prev)))
        if _CONV_TRACE is not None:
            _rc = (abs(Q_cur - Q_prev) / (abs(Q_cur) + 1e-30)
                   if (done >= chunk and Q_prev != 0.0) else float('nan'))
            _CONV_TRACE.append((done, _rc,
                                max(dTa_max, dTb_max, dTs_max),
                                float(np.mean(np.abs(Tb - Tb_prev))),
                                Q_cur))
        if done >= chunk and Q_prev != 0.0:
            rel_chg = abs(Q_cur - Q_prev) / (abs(Q_cur) + 1e-30)
            # Converge on BOTH Q-stable AND field-stable (max per-chunk ΔT below
            # T_abs_tol). Q-alone can false-exit while Ta/Ts still drift (10-15%
            # Q error — 2026-04-24 FV finding); field-stable alone can false-exit
            # while Q drifts. Requiring both is robust AND lets a genuinely
            # converged solve stop at the first qualifying chunk instead of
            # overshooting to max_iter (2026-06-24 — with chunk=250 this halves
            # energy sweeps at bit-identical Q/dP on the 40^3 benchmark).
            if rel_chg < q_tol and max(dTa_max, dTb_max, dTs_max) < T_abs_tol:
                converged = True
                break
        Q_prev = Q_cur
        Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()

    info = {
        'converged': converged,
        'iterations': done,
        'residual': float(chg),
        'delegated_to_2d': False,
    }
    if _cons == 1:
        # Strict-conservation certificate: residual of the conservative
        # discretisation on the converged field. The summed form is the global
        # balance over all actual CVs; the cell-max form (normalised by
        # the mean per-cell source) certifies per-cell ∮F·n = ∫S.
        ncell = Ta.size
        rA, QA, mA = _conservation_residual_sum(
            Ta, Ts, ufA, vfA, wfA, eps_fA_arr, K_ffA_arr, rho_cp_fA_arr,
            h_vA_arr, dx_arr, dy_arr, dz_arr, dir_A, T_inA_arr, ifrac_A, mms_S_A_arr,
            inlet_flux_A, model_mass_A, model_cp_A)
        info['eps_A_strict'] = abs(rA) / max(abs(QA), _Q_FLOOR_W)
        info['eps_A_strict_cellmax'] = mA * ncell / max(abs(QA), _Q_FLOOR_W)
        if freeze_Tb == 0:
            rB, QB, mB = _conservation_residual_sum(
                Tb, Ts, ufB, vfB, wfB, eps_fB_arr, K_ffB_arr, rho_cp_fB_arr,
                h_vB_arr, dx_arr, dy_arr, dz_arr, dir_B, T_inB_arr, ifrac_B, mms_S_B_arr,
                inlet_flux_B, model_mass_B, model_cp_B)
            info['eps_B_strict'] = abs(rB) / max(abs(QB), _Q_FLOOR_W)
            info['eps_B_strict_cellmax'] = mB * ncell / max(abs(QB), _Q_FLOOR_W)
        else:
            info['eps_B_strict'] = None
            info['eps_B_strict_cellmax'] = None
    if model_enabled:
        info['model_h_balance'] = _model_h_balance(
            (Ta, Tb), Ts, (model_mass_A, model_mass_B), (model_cp_A, model_cp_B),
            (dir_A, dir_B), (T_inA_arr, T_inB_arr), (ifrac_A, ifrac_B),
            (K_ffA_arr, K_ffB_arr), K_ss_arr, (h_vA_arr, h_vB_arr),
            (eps_fA_arr, eps_fB_arr), (mms_S_A_arr, mms_S_B_arr), mms_S_s_arr,
            dx_arr, dy_arr, dz_arr)
        info['_native_model_h'] = info['model_h_balance'].pop('_native_faces')
    if return_info:
        return Ta, Tb, Ts, info
    return Ta, Tb, Ts


# ---------------------------------------------------------------------------
# Conservation probes (verification matrix)
# ---------------------------------------------------------------------------

def energy_balance_3d(Ta, Tb, Ts, h_vA_arr, h_vB_arr,
                       dx_arr, dy_arr, dz_arr):
    """LTNE source residual: ∫ h_vA (Ts − Ta) dV + ∫ h_vB (Ts − Tb) dV balance.

    Returns dict:
      Q_sA  : ∫ h_vA (Ts − Ta) dV      [W] (solid → A)
      Q_sB  : ∫ h_vB (Ts − Tb) dV      [W] (solid → B)
      Q_net : Q_sA + Q_sB               [W] (should → 0 in steady state)
    """
    vol = dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :]
    Q_sA = float(np.sum(h_vA_arr * (Ts - Ta) * vol))
    Q_sB = float(np.sum(h_vB_arr * (Ts - Tb) * vol))
    return {'Q_sA': Q_sA, 'Q_sB': Q_sB, 'Q_net': Q_sA + Q_sB}


def mass_balance_3d(u, v, w, rho_field, dy_arr, dx_arr, dz_arr, dir_code):
    """Mass flux imbalance across a flow pair.

    Integrates inlet and outlet face mass flow for a given streamwise direction.
    u / v / w are staggered faces (Nx+1, Ny, Nz) etc. rho_field cell-centre.

    Returns dict:
      m_in  : inlet mass flow  [kg/s]
      m_out : outlet mass flow [kg/s]
      rel   : abs(m_in − m_out) / (|m_in| + 1e-30)
    """
    # For Phase 1 Shanghai this is called on the SIMPLE output.
    if dir_code == 0:
        # +x: inlet face u[0,:,:], outlet u[Nx,:,:]
        A = dy_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[0, :, :]
        rho_out = rho_field[-1, :, :]
        m_in  = float(np.sum(rho_in  * u[0, :, :]  * A))
        m_out = float(np.sum(rho_out * u[-1, :, :] * A))
    elif dir_code == 1:
        A = dy_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[-1, :, :]
        rho_out = rho_field[0, :, :]
        m_in  = -float(np.sum(rho_in  * u[-1, :, :] * A))
        m_out = -float(np.sum(rho_out * u[0, :, :]  * A))
    elif dir_code == 2:
        A = dx_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[:, 0, :]
        rho_out = rho_field[:, -1, :]
        m_in  = float(np.sum(rho_in  * v[:, 0, :]  * A))
        m_out = float(np.sum(rho_out * v[:, -1, :] * A))
    elif dir_code == 3:
        A = dx_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[:, -1, :]
        rho_out = rho_field[:, 0, :]
        m_in  = -float(np.sum(rho_in  * v[:, -1, :] * A))
        m_out = -float(np.sum(rho_out * v[:, 0, :]  * A))
    elif dir_code == 4:
        A = dx_arr[:, None] * dy_arr[None, :]
        rho_in  = rho_field[:, :, 0]
        rho_out = rho_field[:, :, -1]
        m_in  = float(np.sum(rho_in  * w[:, :, 0]  * A))
        m_out = float(np.sum(rho_out * w[:, :, -1] * A))
    else:
        A = dx_arr[:, None] * dy_arr[None, :]
        rho_in  = rho_field[:, :, -1]
        rho_out = rho_field[:, :, 0]
        m_in  = -float(np.sum(rho_in  * w[:, :, -1] * A))
        m_out = -float(np.sum(rho_out * w[:, :, 0]  * A))

    denom = abs(m_in) + 1e-30
    return {'m_in': m_in, 'm_out': m_out, 'rel': abs(m_in - m_out) / denom}


# ---------------------------------------------------------------------------
# JIT warmup
# ---------------------------------------------------------------------------

def _warmup_jit():
    """Pre-compile the LTNE GS kernels on import so the user's first 3D Run does
    not pay the multi-second numba compile. Best-effort, never raises.

    E1 (audit 2026-06-28): must warm the DEFAULT-path STAGGERED kernels
    (_gs_full_chunk_3d_stag + the >30k-cell red-black _stag_rb), not just the
    legacy cell-centered kernel. PRODUCTION runs conservative_ltne=True (injected
    by the pipeline cfg.get('conservative_ltne', True) and core.evaluators —
    solve_full_domain_3d's OWN signature default is False), so the stag kernel is
    what production dispatches (the cc kernel is unreachable once
    conservative_ltne=True). The prior warmup also passed one too few `eps`
    args (34 vs 35), so its TypeError was swallowed and it compiled NOTHING.
    """
    try:
        Nx = Ny = Nz = 4
        Ta = np.full((Nx, Ny, Nz), 300.0)
        Tb = np.full((Nx, Ny, Nz), 290.0)
        Ts = np.full((Nx, Ny, Nz), 295.0)
        dx = np.full(Nx, 0.01); dy = np.full(Ny, 0.01); dz = np.full(Nz, 0.01)
        K = np.full((Nx, Ny, Nz), 0.1); hv = np.full((Nx, Ny, Nz), 100.0)
        ef = np.full((Nx, Ny, Nz), 0.5); rcp = np.full((Nx, Ny, Nz), 1000.0)
        uc = np.full((Nx, Ny, Nz), 0.5); v0 = np.zeros((Nx, Ny, Nz))
        TinA = np.full((Ny, Nz), 300.0); TinB = np.full((Nx, Nz), 290.0)
        fA = np.ones((Ny, Nz)); fB = np.ones((Nx, Nz))
        chi = np.ones((Nx, Ny, Nz)); mms = np.zeros((Nx, Ny, Nz))
        # staggered face velocities for the conservative default path
        ufA = np.full((Nx + 1, Ny, Nz), 0.5)
        vfA = np.zeros((Nx, Ny + 1, Nz)); wfA = np.zeros((Nx, Ny, Nz + 1))
        ufB = np.full((Nx + 1, Ny, Nz), 0.5)
        vfB = np.zeros((Nx, Ny + 1, Nz)); wfB = np.zeros((Nx, Ny, Nz + 1))
        # legacy cell-centered kernel (force_cc_ltne fallback path)
        _gs_full_chunk_3d(
            Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz, dx, dy, dz,
            K, K, K, hv, hv, ef, ef, rcp, rcp,
            uc, v0, v0, uc, v0, v0,
            0, 3, TinA, TinB, fA, fB, 1, 0, 0.7, 0.7, 0.7)
        # default-path staggered kernels (serial + red-black), conservative form
        for _stag in (_gs_full_chunk_3d_stag, _gs_full_chunk_3d_stag_rb):
            _stag(
                Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz, dx, dy, dz,
                K, K, K, hv, hv, ef, ef, rcp, rcp,
                ufA, vfA, wfA, ufB, vfB, wfB,
                0, 3, TinA, TinB, fA, fB, 1, 0, 0.7, 0.7, 0.7,
                chi, 0.5, mms, mms, mms, 1)
    except Exception:
        pass  # warmup is best-effort; never block import (same as ltne_energy)


_warmup_jit()
