"""2D SIMPLE numba kernels + pressure-Poisson infra, moved verbatim from simple_solver.py (openspec split-solver-kernels, 2026-07-03); bit-identical."""

import numpy as np
from numba import njit
from ._kernels_2d import minmod


# ===================================================================
#  Numba kernels
# ===================================================================

# ── SOU deferred correction for momentum (minmod limiter) ──────────
# N2 (audit 2026-06-28): the momentum SOU deferred correction must scale the
# west/south-face limiter by the WEST/SOUTH-face flux (Fw/Fs) and the
# east/north-face limiter by the EAST/NORTH-face flux (Fe/Fn) — the SAME face
# fluxes the first-order aE/aW/aN/aS coefficients already use. The legacy form
# scaled BOTH faces by the single cell-east (or north) flux, so at a shared face
# cell i applied Fe(i)·φ_e while cell i+1 applied Fe(i+1)·φ_w ≠ Fw(i+1)=Fe(i):
# the deferred correction did not telescope and injected a spurious momentum
# source wherever ρ·u varied between neighbours (the exact defect already fixed
# in ltne_energy._sou_corr_x/_y). For a uniform flux field (Fe==Fw) this reduces
# to the legacy `0.5*F*(phi_w - phi_e)`, but on a developing / variable-ρ flow it
# differs at truncation level — an intentional 2D-golden re-baseline.
@njit(cache=True)
def _sou_corr_u_x(u, i, j, Nx, Fe, Fw):
    """Conservative SOU correction using each face's own upwind direction."""
    low = 0.0
    if Fw >= 0.0:
        if i > 2:
            low = minmod(u[i - 1, j] - u[i - 2, j], u[i, j] - u[i - 1, j])
    elif i > 1 and i + 1 <= Nx:
        low = -minmod(u[i, j] - u[i + 1, j], u[i - 1, j] - u[i, j])
    high = 0.0
    if Fe >= 0.0:
        if i > 1 and i + 1 < Nx:
            high = minmod(u[i, j] - u[i - 1, j], u[i + 1, j] - u[i, j])
    elif i + 2 <= Nx:
        high = -minmod(u[i + 1, j] - u[i + 2, j], u[i, j] - u[i + 1, j])
    return 0.5 * (Fw * low - Fe * high)


@njit(cache=True)
def _sou_corr_u_y(u, i, j, Ny, Fn, Fs):
    """Conservative SOU correction using each face's own upwind direction."""
    low = 0.0
    if Fs >= 0.0:
        if j > 1:
            low = minmod(u[i, j - 1] - u[i, j - 2], u[i, j] - u[i, j - 1])
    elif j > 0 and j < Ny - 1:
        low = -minmod(u[i, j] - u[i, j + 1], u[i, j - 1] - u[i, j])
    high = 0.0
    if Fn >= 0.0:
        if j > 0 and j < Ny - 1:
            high = minmod(u[i, j] - u[i, j - 1], u[i, j + 1] - u[i, j])
    elif j < Ny - 2:
        high = -minmod(u[i, j + 1] - u[i, j + 2], u[i, j] - u[i, j + 1])
    return 0.5 * (Fs * low - Fn * high)


@njit(cache=True)
def _sou_corr_v_x(v, i, j, Nx, Fe, Fw):
    """Conservative SOU correction using each face's own upwind direction."""
    low = 0.0
    if Fw >= 0.0:
        if i > 1:
            low = minmod(v[i - 1, j] - v[i - 2, j], v[i, j] - v[i - 1, j])
    elif i > 0 and i < Nx - 1:
        low = -minmod(v[i, j] - v[i + 1, j], v[i - 1, j] - v[i, j])
    high = 0.0
    if Fe >= 0.0:
        if i > 0 and i < Nx - 1:
            high = minmod(v[i, j] - v[i - 1, j], v[i + 1, j] - v[i, j])
    elif i < Nx - 2:
        high = -minmod(v[i + 1, j] - v[i + 2, j], v[i, j] - v[i + 1, j])
    return 0.5 * (Fw * low - Fe * high)


@njit(cache=True)
def _sou_corr_v_y(v, i, j, Ny, Fn, Fs):
    """Conservative SOU correction using each face's own upwind direction."""
    low = 0.0
    if Fs >= 0.0:
        if j > 2:
            low = minmod(v[i, j - 1] - v[i, j - 2], v[i, j] - v[i, j - 1])
    elif j > 1 and j + 1 <= Ny:
        low = -minmod(v[i, j] - v[i, j + 1], v[i, j - 1] - v[i, j])
    high = 0.0
    if Fn >= 0.0:
        if j > 1 and j + 1 <= Ny:
            high = minmod(v[i, j] - v[i, j - 1], v[i, j + 1] - v[i, j])
    elif j + 2 <= Ny:
        high = -minmod(v[i, j + 1] - v[i, j + 2], v[i, j] - v[i, j + 1])
    return 0.5 * (Fs * low - Fn * high)



@njit(cache=True)
def _porous_src_df(umag, K, cF, mu, rho):
    """Linearised Darcy-Forchheimer resistance coefficient [kg/(m3 s)].

    Darcy-Forchheimer closure: Sp * u = (mu/K) * u + rho * c_F * |u| * u.
    K and c_F are geometry-level constants supplied by the caller. Production
    preparation pins the fixed water+sCO2 CFD baseline and applies any selected
    experiment correction once; gamma_df and rbf are retired. Caller provides
    K, cF per-cell (2026-07-10
    lateral-K: kernels now consume 2D (Nx, Ny) fields; a laterally-uniform
    field reproduces the historical per-row behaviour bit-identically).
    """
    if umag < 1e-10:
        return mu / K  # pure Darcy when velocity vanishes
    return mu / K + rho * cF * umag


@njit(cache=True)
def _umag_u(u, v, i, j, Nx, Ny):
    """Speed at u-face (i,j)."""
    il = max(i - 1, 0); ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j] + v[ir, j] + v[il, j + 1] + v[ir, j + 1])
    return np.sqrt(u[i, j] ** 2 + va ** 2)


@njit(cache=True)
def _umag_v(u, v, i, j, Nx, Ny):
    """Speed at v-face (i,j)."""
    jb = max(j - 1, 0); jt = min(j, Ny - 1)
    ua = 0.25 * (u[i, jb] + u[i + 1, jb] + u[i, jt] + u[i + 1, jt])
    return np.sqrt(ua ** 2 + v[i, j] ** 2)


# ── SIMPLE Step 1: x-momentum with D-F closure ───────────────────
@njit(cache=True)
def _sweep_u_jit_df(u, v, P, d_u, outlet_u_frac,
                    Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                    K_arr, cF_arr, mu_field, eps_field,
                    alpha_u, n_sweeps, cf_aniso):
    """D-F variant of _sweep_u_jit: porous source uses (K, c_F) per row from
    the ConstDF-v1 surrogate, no phi_arr correction (MLP covers training range
    natively). mu_eff_field and mu_field are 2D (Nx, Ny) arrays so that
    viscosity tracks the temperature field in non-isothermal compressible flow.

    M2 (2026-07-09, VANS ∇ε): momentum discretizes the ε-DIVIDED volume-
    averaged form  (1/ε_P)∇·(ε ρ u u) = −∇p + (1/ε_P)∇·(μ ∇u) + f_DF —
    every flux face carries the ratio r_f = ε_f / ε_CV multiplying both the
    convective flux F_f and the diffusion conductance D_f. The pressure term
    needs NO factor in this form (−ε∇p/ε cancels exactly) and the DF drag
    stays untouched (experiment-anchored calibration absorbed its volume
    convention). Uniform ε → all r ≡ 1.0 bit-exactly (arithmetic means of
    equal values are exact; ×1.0 is an IEEE no-op), so the pre-M2 fields are
    reproduced bit-identically — that is the regression gate.
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
                dyj = dy_arr[j]
                vol = dxi * dyj

                il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
                mu_e = 0.5 * (mu_eff_field[il_r, j] + mu_eff_field[ir_r, j])

                # M2: ε at the u-CV centre + the four flux-face ratios.
                # u-node sits on the x-interface between cells il_r/ir_r, so
                # its E/W flux faces are the CELL CENTRES; N/S faces are the
                # 4-cell corners.
                eps_u = 0.5 * (eps_field[il_r, j] + eps_field[ir_r, j])
                r_e = eps_field[ir_r, j] / eps_u
                r_w = eps_field[il_r, j] / eps_u
                r_n = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                               + eps_field[il_r, j + 1]
                               + eps_field[ir_r, j + 1]) / eps_u
                       if j < Ny - 1 else 1.0)
                r_s = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                               + eps_field[il_r, j - 1]
                               + eps_field[ir_r, j - 1]) / eps_u
                       if j > 0 else 1.0)

                # N4 (2026-07-07): diffusion conductances use the ACTUAL
                # neighbour-node distance, not the CV width. u-nodes sit on
                # x-interfaces: E neighbour at dx[i], W at dx[i-1]; cross-
                # stream neighbours at 0.5*(dy[j]+dy[j±1]). Uniform grids
                # reduce to the old dxi/dyj form bit-identically.
                De = r_e * mu_e * dyj / dx_arr[ir_r]
                Dw = r_w * mu_e * dyj / dx_arr[il_r]
                Dn = (r_n * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j + 1]))
                      if j < Ny - 1 else 2.0 * mu_e * dxi / dyj * (1.0 - outlet_u_frac[i]))
                Ds = (r_s * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j - 1]))
                      if j > 0 else 2.0 * mu_e * dxi / dyj)

                uE = u[i + 1, j] if i + 1 < Nx else 0.0
                uW = u[i - 1, j] if i > 1 else 0.0
                uN = u[i, j + 1] if j < Ny - 1 else 0.0
                uS = u[i, j - 1] if j > 0 else 0.0

                ue = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
                uw = 0.5 * (u[max(i - 1, 0), j] + u[i, j])
                il = max(i - 1, 0); ir = min(i, Nx - 1)
                vn = 0.5 * (v[il, j + 1] + v[ir, j + 1])
                vs = 0.5 * (v[il, j] + v[ir, j])

                rho_loc = 0.5 * (rho_field[il_r, j] + rho_field[ir_r, j])
                mu_loc  = 0.5 * (mu_field[il_r, j] + mu_field[ir_r, j])

                Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
                Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_u(u, v, i, j, Nx, Ny)
                # 2026-07-10 lateral-K: K/cF are 2D (Nx, Ny) SIMPLE-coord
                # fields. u-node straddles cells il_r/ir_r laterally → arith
                # mean. Laterally-uniform fields give 0.5*(a+a) = a exactly
                # (IEEE), reproducing the old per-row K_arr[j] bit-identically.
                K_u = 0.5 * (K_arr[il_r, j] + K_arr[ir_r, j])
                cF_u = 0.5 * (cF_arr[il_r, j] + cF_arr[ir_r, j])
                # 2026-07-10 cf-aniso: oblique-flow Forchheimer direction
                # factor cF_eff = cF·(1 + a·ξ4), ξ4 = 4·nx²·ny² ∈ [0,1] — the
                # lowest cubic-symmetry invariant (0 on-axis, 1 at 45°). The
                # on-axis value stays the calibration-anchored cF exactly; a=0
                # (default) skips the branch (bit-identical). Darcy K is left
                # isotropic (cubic symmetry ⇒ K tensor ∝ I). Calibrate `a`
                # from direction-resolved unit-cell CFD (validation/cf_aniso).
                if cf_aniso != 0.0 and umag > 1e-10:
                    va_c = 0.25 * (v[il_r, j] + v[ir_r, j]
                                   + v[il_r, j + 1] + v[ir_r, j + 1])
                    ux2 = u[i, j] * u[i, j]
                    uy2 = va_c * va_c
                    xi4 = 4.0 * ux2 * uy2 / (umag * umag * umag * umag)
                    cF_u = cF_u * (1.0 + cf_aniso * xi4)
                Sp = _porous_src_df(umag, K_u, cF_u, mu_loc, rho_loc) * vol

                p_src = (P[i - 1, j] - P[i, j]) * dyj
                sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw)
                     + _sou_corr_u_y(u, i, j, Ny, Fn, Fs))
                aP0 = aE + aW + aN + aS + Sp
                rhs = aE * uE + aW * uW + aN * uN + aS * uS + p_src + sou
                aP = aP0 / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP0 * u[i, j]

                u[i, j] = rhs / aP
                d_u[i, j] = dyj / aP0

    for j in range(Ny):
        u[0, j] = 0.0; u[Nx, j] = 0.0


# ── SIMPLE Step 2: y-momentum with D-F closure ───────────────────
@njit(cache=True)
def _close_outlet_mass(u, v, outlet_frac, Nx, Ny, dx_arr, dy_arr,
                       rho_field, eps_field):
    """Close each pressure-outlet CV: Fn = Fs + Fw - Fe.

    outlet_frac is raw geometric overlap; every positive overlap is open.
    Use the PPE's face-averaged rho*eps, divided by the outlet CV's eps.
    Epsilon ratios keep uniform-epsilon momentum independent of its value.
    """
    j = Ny - 1
    for i in range(Nx):
        if outlet_frac[i] > 0.0:
            rho_c = rho_field[i, j]
            eps_c = eps_field[i, j]
            rho_s = (0.5 * (rho_field[i, j - 1] * (eps_field[i, j - 1] / eps_c)
                            + rho_c) if j > 0 else rho_c)
            rho_w = (0.5 * (rho_field[i - 1, j] * (eps_field[i - 1, j] / eps_c)
                            + rho_c) if i > 0 else rho_c)
            rho_e = (0.5 * (rho_c + rho_field[i + 1, j]
                            * (eps_field[i + 1, j] / eps_c))
                     if i < Nx - 1 else rho_c)
            lateral = (rho_e * u[i + 1, j] - rho_w * u[i, j]) * dy_arr[j] / dx_arr[i]
            v[i, Ny] = (rho_s * v[i, j] - lateral) / rho_c
        else:
            v[i, Ny] = 0.0


@njit(cache=True)
def _sweep_v_jit_df(u, v, P, d_v, inlet_frac, v_inlet_field, outlet_frac,
                    Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                    K_arr, cF_arr, mu_field, eps_field,
                    alpha_u, n_sweeps, cf_aniso):
    """D-F variant of _sweep_v_jit, mirrors _sweep_u_jit_df changes.
    mu_eff_field and mu_field are 2D (Nx, Ny) for non-isothermal coupling.
    M2 (2026-07-09): VANS ε-ratio factors — see _sweep_u_jit_df docstring;
    v-node sits on the y-interface between cells jb/jt, so N/S flux faces
    are the cell centres and E/W faces are the 4-cell corners. Wall
    branches (no-slip conductance) carry no ratio: the wall face has no
    ε gradient across it (zero-normal-gradient ε at the housing)."""
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                jc = min(j, Ny - 1)
                dxi = dx_arr[i]
                dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
                vol = dxi * dyj

                jb = max(j - 1, 0); jt = min(j, Ny - 1)
                mu_e = 0.5 * (mu_eff_field[i, jb] + mu_eff_field[i, jt])

                # M2: ε at the v-CV centre + flux-face ratios (uniform → 1.0
                # bit-exactly).
                eps_v = 0.5 * (eps_field[i, jb] + eps_field[i, jt])
                r_n = eps_field[i, jt] / eps_v
                r_s = eps_field[i, jb] / eps_v
                r_e = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                               + eps_field[i + 1, jb] + eps_field[i + 1, jt])
                       / eps_v if i < Nx - 1 else 1.0)
                r_w = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                               + eps_field[i - 1, jb] + eps_field[i - 1, jt])
                       / eps_v if i > 0 else 1.0)

                # No-slip at side walls (x=0, x=W): tangential velocity v=0 at
                # wall. Distance from cell centre to wall = dxi/2, so the wall
                # diffusion coefficient is mu_e * dyj / (0.5*dxi).
                # Previously free-slip (De=0 at i=Nx-1, Dw=0 at i=0); corrected
                # 2026-04-17 to match physical outer-housing walls in TPMS heat
                # exchangers. For symmetry/periodic boundaries, revert to 0/0.
                # N4 (2026-07-07): interior conductances use the ACTUAL
                # neighbour-node distances — E/W v-neighbours sit at
                # 0.5*(dx[i]+dx[i±1]), N/S at dy[j]/dy[j-1] (v-nodes on
                # y-interfaces). Uniform grids reduce bit-identically.
                if i < Nx - 1:
                    vE = v[i + 1, j]
                    De = r_e * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i + 1]))
                else:
                    vE = 0.0; De = 2.0 * mu_e * dyj / dxi   # east wall (no-slip)
                if i > 0:
                    vW = v[i - 1, j]
                    Dw = r_w * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i - 1]))
                else:
                    vW = 0.0; Dw = 2.0 * mu_e * dyj / dxi   # west wall (no-slip)
                vN = v[i, j + 1]
                vS = v[i, j - 1]

                Dn = r_n * mu_e * dxi / dy_arr[jt]
                Ds = r_s * mu_e * dxi / dy_arr[jb]

                ue = 0.5 * (u[i + 1, jb] + u[i + 1, jt]) if i < Nx - 1 else 0.0
                uw = 0.5 * (u[i, jb] + u[i, jt]) if i > 0 else 0.0
                vn = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
                vs = 0.5 * (v[i, max(j - 1, 0)] + v[i, j])

                rho_loc = 0.5 * (rho_field[i, jb] + rho_field[i, jt])
                mu_loc  = 0.5 * (mu_field[i, jb] + mu_field[i, jt])

                Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
                Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_v(u, v, i, j, Nx, Ny)
                # 2026-07-10 lateral-K: K/cF are 2D (Nx, Ny). v-node keeps the
                # legacy streamwise pick K[jc] (a jb/jt mean would move
                # streamwise-graded cases), extended laterally to column i.
                cF_v = cF_arr[i, jc]
                # 2026-07-10 cf-aniso: mirrors _sweep_u_jit_df (see there).
                if cf_aniso != 0.0 and umag > 1e-10:
                    ua_c = 0.25 * (u[i, jb] + u[i + 1, jb]
                                   + u[i, jt] + u[i + 1, jt])
                    ux2 = ua_c * ua_c
                    uy2 = v[i, j] * v[i, j]
                    xi4 = 4.0 * ux2 * uy2 / (umag * umag * umag * umag)
                    cF_v = cF_v * (1.0 + cf_aniso * xi4)
                Sp = _porous_src_df(umag, K_arr[i, jc], cF_v, mu_loc, rho_loc) * vol

                p_src = (P[i, j - 1] - P[i, j]) * dxi
                sou = (_sou_corr_v_x(v, i, j, Nx, Fe, Fw)
                     + _sou_corr_v_y(v, i, j, Ny, Fn, Fs))
                aP0 = aE + aW + aN + aS + Sp
                rhs = aE * vE + aW * vW + aN * vN + aS * vS + p_src + sou
                aP = aP0 / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP0 * v[i, j]

                v[i, j] = rhs / aP
                d_v[i, j] = dxi / aP0

    for i in range(Nx):
        v[i, 0] = v_inlet_field[i] * inlet_frac[i]
    _close_outlet_mass(u, v, outlet_frac, Nx, Ny, dx_arr, dy_arr, rho_field, eps_field)


# ── SIMPLE Steps 3-4: pressure correction (sparse direct solver) ──

from scipy import sparse
from scipy.sparse.linalg import spsolve


def _build_pp_sparsity_pattern(Nx, Ny, outlet_frac):
    """Precompute CSR sparsity pattern for the pressure-Poisson operator.

    For each cell (i, j) we allocate up to 5 slots in the CSR data array:
    one for the diagonal (always present), and up to 4 for the east/west/
    north/south off-diagonal couplings. Boundary cells and outlet-reference
    cells have fewer non-zeros, but we still allocate 5 slots each and write
    0.0 into the unused ones at assembly time — simpler bookkeeping and the
    extra zeros cost nothing in the sparse solve.

    Returns a dict with:
        indptr   : int32[N+1]  — CSR row pointer
        indices  : int32[nnz]  — CSR column indices
        cell_base: int32[N]    — data-array offset for cell k's first slot
        cell_kind: int8[N]     — 0=interior, 1=outlet_ref
    All arrays are contiguous and ready to pass to the Numba assembler.
    """
    N = Nx * Ny
    def idx(i, j): return i * Ny + j

    indptr = np.zeros(N + 1, dtype=np.int32)
    indices_list = []
    cell_base = np.zeros(N, dtype=np.int32)
    cell_kind = np.zeros(N, dtype=np.int8)

    pos = 0
    for i in range(Nx):
        for j in range(Ny):
            k = idx(i, j)
            cell_base[k] = pos
            # Outlet reference: diagonal only, Pp = 0.
            # The same raw support owns normal flow, pressure pins and walls.
            if j == Ny - 1 and outlet_frac[i] > 0.0:
                cell_kind[k] = 1
                indices_list.append(k)
                pos += 1
                indptr[k + 1] = pos
                continue
            # Standard interior/edge cell: diagonal + up-to-4 off-diagonals.
            # Order: [self, E, W, N, S]. Unused neighbours still get a slot
            # pointing back to self (diagonal) with data 0, so the CSR
            # structure is uniform.
            indices_list.append(k)                                      # diag
            indices_list.append(idx(i+1, j) if i < Nx-1 else k)        # E
            indices_list.append(idx(i-1, j) if i > 0    else k)        # W
            indices_list.append(idx(i, j+1) if j < Ny-1 else k)        # N
            indices_list.append(idx(i, j-1) if j > 0    else k)        # S
            pos += 5
            indptr[k + 1] = pos

    indices = np.asarray(indices_list, dtype=np.int32)
    return {
        'indptr': indptr,
        'indices': indices,
        'cell_base': cell_base,
        'cell_kind': cell_kind,
        'nnz': pos,
    }


@njit(cache=True)
def _assemble_pp_data_jit(data, rhs, u, v, d_u, d_v, outlet_frac,
                          Nx, Ny, dx_arr, dy_arr, rho_field,
                          cell_base, cell_kind):
    """Fill CSR `data` array and `rhs` vector for the pressure-Poisson operator.

    For each cell (i, j), writes 5 consecutive slots [diag, E, W, N, S] into
    `data[cell_base[k] : cell_base[k]+5]`, or a single slot [1.0] for outlet
    reference cells. `cell_kind` disambiguates:
        0 = standard interior/edge cell
        1 = outlet reference (Pp = 0 enforced)
    """
    for i in range(Nx):
        for j in range(Ny):
            k = i * Ny + j
            base = cell_base[k]

            if cell_kind[k] == 1:
                # Outlet reference: single diagonal entry = 1.0
                data[base] = 1.0
                rhs[k] = 0.0
                continue

            dxi = dx_arr[i]
            dyj = dy_arr[j]

            # Face densities (linear interpolation from cell centres)
            if i < Nx - 1:
                rho_e = 0.5 * (rho_field[i, j] + rho_field[i+1, j])
            else:
                rho_e = rho_field[i, j]
            if i > 0:
                rho_w = 0.5 * (rho_field[i-1, j] + rho_field[i, j])
            else:
                rho_w = rho_field[i, j]
            if j < Ny - 1:
                rho_n = 0.5 * (rho_field[i, j] + rho_field[i, j+1])
            else:
                rho_n = rho_field[i, j]
            if j > 0:
                rho_s = 0.5 * (rho_field[i, j-1] + rho_field[i, j])
            else:
                rho_s = rho_field[i, j]

            aE = rho_e * d_u[i+1, j] * dyj if i < Nx - 1 else 0.0
            aW = rho_w * d_u[i,   j] * dyj if i > 0      else 0.0
            aN = rho_n * d_v[i, j+1] * dxi if j < Ny - 1 else 0.0
            aS = rho_s * d_v[i, j  ] * dxi if j > 0      else 0.0
            aP = aE + aW + aN + aS

            if aP < 1e-30:
                # Degenerate cell: pin Pp = 0
                data[base] = 1.0
                data[base + 1] = 0.0  # E slot
                data[base + 2] = 0.0  # W
                data[base + 3] = 0.0  # N
                data[base + 4] = 0.0  # S
                rhs[k] = 0.0
                continue

            # Standard 5-point stencil, [diag, E, W, N, S]
            data[base    ] = aP
            data[base + 1] = -aE
            data[base + 2] = -aW
            data[base + 3] = -aN
            data[base + 4] = -aS

            rhs[k] = -((rho_e * u[i+1, j] - rho_w * u[i, j]) * dyj
                      + (rho_n * v[i, j+1] - rho_s * v[i, j]) * dxi)


def _solve_pp_sparse_fast(Pp, u, v, d_u, d_v, outlet_frac,
                          Nx, Ny, dx_arr, dy_arr, rho_field, sparsity):
    """Pressure-Poisson solve with precomputed sparsity pattern.

    Caller must pass `sparsity` as returned by `_build_pp_sparsity_pattern`.
    Returns (A, rhs) alongside writing Pp in place, so regression tests can
    compare the assembled matrix directly.
    """
    N = Nx * Ny
    nnz = sparsity['nnz']
    data = np.zeros(nnz, dtype=np.float64)
    rhs = np.zeros(N, dtype=np.float64)

    _assemble_pp_data_jit(data, rhs, u, v, d_u, d_v, outlet_frac,
                          Nx, Ny, dx_arr, dy_arr, rho_field,
                          sparsity['cell_base'], sparsity['cell_kind'])

    # NOTE: scipy csr_matrix takes ownership of indptr without copying, and
    # spsolve may reorder it in-place. We copy indices/indptr so the cached
    # sparsity pattern is not corrupted across SIMPLE iterations.
    A = sparse.csr_matrix(
        (data, sparsity['indices'].copy(), sparsity['indptr'].copy()),
        shape=(N, N),
    )
    pp_flat = spsolve(A, rhs)
    if not np.isfinite(pp_flat).all():
        from sjtu_tpmshx.domain.run_warnings import record_warning
        record_warning(('pressure_poisson', 'nonfinite'),
                       'pressure-Poisson solve returned non-finite corrections')
    Pp[:, :] = pp_flat.reshape(Nx, Ny)
    return A, rhs



# ── SIMPLE Step 5: correction ─────────────────────────────────────
@njit(cache=True)
def _correct_jit(u, v, P, Pp, d_u, d_v, inlet_frac, v_inlet_field, outlet_frac,
                 Nx, Ny, dx_arr, dy_arr, alpha_p, rho_field, eps_field):
    # Pressure correction (skip only outlet cells at j=Ny-1)
    for i in range(Nx):
        for j in range(Ny):
            if j == Ny - 1 and outlet_frac[i] > 0.0:
                continue  # outlet: Pp=0, no correction
            P[i, j] += alpha_p * Pp[i, j]
    # u correction
    for i in range(1, Nx):
        for j in range(Ny):
            u[i, j] += d_u[i, j] * (Pp[i - 1, j] - Pp[i, j])
    # v correction
    for i in range(Nx):
        for j in range(1, Ny):
            v[i, j] += d_v[i, j] * (Pp[i, j - 1] - Pp[i, j])
    # Re-apply BCs
    for j in range(Ny):
        u[0, j] = 0.0; u[Nx, j] = 0.0
    for i in range(Nx):
        v[i, 0] = v_inlet_field[i] * inlet_frac[i]
    _close_outlet_mass(u, v, outlet_frac, Nx, Ny, dx_arr, dy_arr, rho_field, eps_field)


# ── SIMPLE Step 6: convergence ────────────────────────────────────
@njit(cache=True)
def _mass_res_jit(u, v, Nx, Ny, dx_arr, dy_arr, rho_field):
    """Global mass conservation residual for variable-density flow.

    Returns max |Q(j) - Q_inlet| / Q_inlet where Q(j) = Σ_i ρ_face·v[i,j]·dx[i]
    is the cross-sectional MASS flux (not volumetric).

    This is a PLANE-INTEGRATED defect, NOT a per-cell divergence — transverse
    per-cell imbalances cancel within a plane (u = 0 at the i = 0 / i = Nx walls
    makes the x-flux telescope to zero over any j-plane) and are invisible here.
    The 3D `_mass_res_jit_3d` returns the per-cell divergence instead, i.e. a
    strictly stronger quantity — yet both solvers are handed the same `tol`.
    THAT mismatch, not any 2D band-aid, is why 2D's `tol` is reachable and 3D's
    is not (ledger C6).

    Historical correction (2026-07-12): the former global outlet rescale
    happened only AFTER the exit decision, so it could not make tol fire.
    The current `_enforce_mass_conservation` instead closes local outlet CVs
    with the latest density, still only on exit. It cannot trigger the pre-tol
    check either. Legacy `final_res` remains the pre-closeout residual, not a
    certificate of the returned field; F2 separately rechecks its certificate.

    Like 3D, this residual is evaluated against the PRE-`_update_density`
    rho_eps (`simple_solver.py:880-882`), so it shares 3D's staleness too.
    """
    # Inlet mass flux (j=0): rho at face = rho at cell j=0 (boundary)
    Q_in = 0.0
    for i in range(Nx):
        Q_in += rho_field[i, 0] * abs(v[i, 0]) * dx_arr[i]
    if Q_in < 1e-30:
        return 0.0
    Rmax = 0.0
    for j in range(1, Ny + 1):
        Q_j = 0.0
        for i in range(Nx):
            # rho at v-face (i, j): average of cells j-1 and j
            if j < Ny:
                rho_f = 0.5 * (rho_field[i, j - 1] + rho_field[i, j])
            else:
                rho_f = rho_field[i, Ny - 1]
            Q_j += rho_f * v[i, j] * dx_arr[i]
        R = abs(Q_j - Q_in) / Q_in
        if R > Rmax:
            Rmax = R
    return Rmax


# ── Temperature solver (frozen velocity) ──────────────────────────
@njit(cache=True)
def _solve_temp_jit(Tf, Ts, u, v, inlet_mask,
                    Nx, Ny, dx_arr, dy_arr, eps,
                    K_ff, K_ss, h_v, h_v2, rho_cp_f,
                    T_in, T_other,
                    max_iter, tol):
    """
    Iterate fluid + solid temperature to steady state.
    dx_arr: 1D [Nx], dy_arr: 1D [Ny] — non-uniform cell widths.
    """
    for it in range(max_iter):
        max_chg = 0.0

        # ── Fluid temperature ──
        for i in range(Nx):
            for j in range(Ny):
                dxi = dx_arr[i]; dyj = dy_arr[j]
                vol = dxi * dyj
                Df_e = K_ff * dyj / dxi; Df_n = K_ff * dxi / dyj
                hv  = h_v * vol

                # Diffusion coefficients (0 at boundaries = adiabatic)
                dE = Df_e if i < Nx - 1 else 0.0
                dW = Df_e if i > 0      else 0.0
                dN = Df_n if j < Ny - 1 else 0.0
                dS = Df_n if j > 0      else 0.0

                # Convective fluxes (staggered velocities at cell faces)
                Fe = eps * rho_cp_f * u[i + 1, j] * dyj
                Fw = eps * rho_cp_f * u[i, j]     * dyj
                Fn = eps * rho_cp_f * v[i, j + 1] * dxi
                Fs = eps * rho_cp_f * v[i, j]     * dxi

                aE = dE + max(-Fe, 0.0)
                aW = dW + max(Fw, 0.0)
                aN = dN + max(-Fn, 0.0)
                aS = dS + max(Fs, 0.0)

                # Neighbours (adiabatic = zero-grad at boundaries)
                tE = Tf[i + 1, j] if i < Nx - 1 else Tf[i, j]
                tW = Tf[i - 1, j] if i > 0      else Tf[i, j]
                tN = Tf[i, j + 1] if j < Ny - 1 else Tf[i, j]
                if j > 0:
                    tS = Tf[i, j - 1]
                else:
                    tS = T_in if inlet_mask[i] else Tf[i, j]

                aP = aE + aW + aN + aS + hv
                rhs = aE * tE + aW * tW + aN * tN + aS * tS + hv * Ts[i, j]
                # Note: hv and hv2_loc computed per-cell above

                Tf_new = rhs / aP
                chg = abs(Tf_new - Tf[i, j])
                if chg > max_chg:
                    max_chg = chg
                Tf[i, j] = Tf_new

        # ── Solid temperature ──
        for i in range(Nx):
            for j in range(Ny):
                dxi = dx_arr[i]; dyj = dy_arr[j]
                Ds_e_loc = K_ss * dyj / dxi; Ds_n_loc = K_ss * dxi / dyj
                hv_loc = h_v * dxi * dyj
                hv2_loc2 = h_v2 * dxi * dyj

                sE = Ts[i + 1, j] if i < Nx - 1 else Ts[i, j]
                sW = Ts[i - 1, j] if i > 0      else Ts[i, j]
                sN = Ts[i, j + 1] if j < Ny - 1 else Ts[i, j]
                sS = Ts[i, j - 1] if j > 0      else Ts[i, j]

                aP_s = 2.0 * Ds_e_loc + 2.0 * Ds_n_loc + hv_loc + hv2_loc2
                rhs_s = (Ds_e_loc * (sE + sW) + Ds_n_loc * (sN + sS)
                         + hv_loc * Tf[i, j] + hv2_loc2 * T_other)

                Ts_new = rhs_s / aP_s
                chg = abs(Ts_new - Ts[i, j])
                if chg > max_chg:
                    max_chg = chg
                Ts[i, j] = Ts_new

        if max_chg < tol:
            return it + 1

    return max_iter


# ═══════════════════════════════════════════════════════════════════════
#  F2 convergence residuals — 2D (ledger C6 / C7 / C9)
# ═══════════════════════════════════════════════════════════════════════
#
# The 2D `tol` is even more degenerate than 3D's. `_mass_res_jit` is a
# PLANE-INTEGRATED flux defect, and the pp solve drives the per-cell divergence
# to zero, so every plane's flux telescopes to the inlet's — on a FULL-FACE
# outlet the residual is a TAUTOLOGY. Measured: it reaches 1.6e-15, so `tol`
# fires at the MIN-ITER FLOOR (iteration 20) and the solve stops there.
#
# Cost of that, measured on the production Pipeline2D (golden air-air config,
# ledger C9): dP_A is under-converged by -3.3 %, and 50 iterations per SIMPLE
# call removes it for 1.21x wall. (3D's premature exit costs only 0.13-0.23 %.)
#
# These kernels give 2D the same honest three-gate criterion 3D got in C7.


@njit(cache=True)
def _u_coeffs_df_2d(u, v, P, i, j, Nx, Ny, dx_arr, dy_arr,
                    rho_field, mu_eff_field, K_arr, cF_arr, mu_field,
                    eps_field, outlet_u_frac, cf_aniso):
    """(aP0, rhs) for the u-face (i, j): the UNRELAXED discrete x-momentum
    equation ``aP0 * u = rhs``, with ``rhs = sum(a_nb*u_nb) + p_src + SOU``.

    DELIBERATE PARALLEL ASSEMBLY of `_sweep_u_jit_df`'s coefficient block, for
    `_mom_res_jit_2d` only. NOT shared with the sweep — the same decision as 3D
    (`_u_coeffs_df_3d`) and for the same reason: factoring the coefficients out
    of the sweep and having both call one helper moved golden-3D by fastmath
    re-association at the inline boundary, and a diagnostic must not cost a
    re-baseline.

    The duplication is GUARDED, not trusted: `_mom_res_jit_2d` must return ~0 at
    the SWEEP's own momentum fixed point (`tests/test_f2_convergence_2d.py`).
    Edit `_sweep_u_jit_df` and not this, and that test fails loudly. KEEP THEM IN
    LOCKSTEP.

    Two 2D-vs-3D differences that are easy to get wrong: the SOU deferred
    correction is ALWAYS applied here (2D has no `use_sou` flag), and the VANS
    eps-ratio factors are ALWAYS computed (no `use_eps` flag — uniform eps gives
    r == 1.0 exactly).
    """
    dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
    dyj = dy_arr[j]
    vol = dxi * dyj

    il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
    mu_e = 0.5 * (mu_eff_field[il_r, j] + mu_eff_field[ir_r, j])

    eps_u = 0.5 * (eps_field[il_r, j] + eps_field[ir_r, j])
    r_e = eps_field[ir_r, j] / eps_u
    r_w = eps_field[il_r, j] / eps_u
    r_n = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                   + eps_field[il_r, j + 1]
                   + eps_field[ir_r, j + 1]) / eps_u
           if j < Ny - 1 else 1.0)
    r_s = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                   + eps_field[il_r, j - 1]
                   + eps_field[ir_r, j - 1]) / eps_u
           if j > 0 else 1.0)

    De = r_e * mu_e * dyj / dx_arr[ir_r]
    Dw = r_w * mu_e * dyj / dx_arr[il_r]
    Dn = (r_n * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j + 1]))
          if j < Ny - 1 else 2.0 * mu_e * dxi / dyj * (1.0 - outlet_u_frac[i]))
    Ds = (r_s * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j - 1]))
          if j > 0 else 2.0 * mu_e * dxi / dyj)

    uE = u[i + 1, j] if i + 1 < Nx else 0.0
    uW = u[i - 1, j] if i > 1 else 0.0
    uN = u[i, j + 1] if j < Ny - 1 else 0.0
    uS = u[i, j - 1] if j > 0 else 0.0

    ue = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
    uw = 0.5 * (u[max(i - 1, 0), j] + u[i, j])
    il = max(i - 1, 0); ir = min(i, Nx - 1)
    vn = 0.5 * (v[il, j + 1] + v[ir, j + 1])
    vs = 0.5 * (v[il, j] + v[ir, j])

    rho_loc = 0.5 * (rho_field[il_r, j] + rho_field[ir_r, j])
    mu_loc = 0.5 * (mu_field[il_r, j] + mu_field[ir_r, j])

    Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
    Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)

    umag = _umag_u(u, v, i, j, Nx, Ny)
    K_u = 0.5 * (K_arr[il_r, j] + K_arr[ir_r, j])
    cF_u = 0.5 * (cF_arr[il_r, j] + cF_arr[ir_r, j])
    if cf_aniso != 0.0 and umag > 1e-10:
        va_c = 0.25 * (v[il_r, j] + v[ir_r, j]
                       + v[il_r, j + 1] + v[ir_r, j + 1])
        ux2 = u[i, j] * u[i, j]
        uy2 = va_c * va_c
        xi4 = 4.0 * ux2 * uy2 / (umag * umag * umag * umag)
        cF_u = cF_u * (1.0 + cf_aniso * xi4)
    Sp = _porous_src_df(umag, K_u, cF_u, mu_loc, rho_loc) * vol

    p_src = (P[i - 1, j] - P[i, j]) * dyj
    sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw)
           + _sou_corr_u_y(u, i, j, Ny, Fn, Fs))
    aP0 = aE + aW + aN + aS + Sp
    rhs = aE * uE + aW * uW + aN * uN + aS * uS + p_src + sou
    return aP0, rhs


@njit(cache=True)
def _v_coeffs_df_2d(u, v, P, i, j, Nx, Ny, dx_arr, dy_arr,
                    rho_field, mu_eff_field, K_arr, cF_arr, mu_field,
                    eps_field, cf_aniso):
    """(aP0, rhs) for the v-face (i, j) — UNRELAXED discrete y-momentum.
    Parallel assembly of `_sweep_v_jit_df`; see `_u_coeffs_df_2d`."""
    jc = min(j, Ny - 1)
    dxi = dx_arr[i]
    dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
    vol = dxi * dyj

    jb = max(j - 1, 0); jt = min(j, Ny - 1)
    mu_e = 0.5 * (mu_eff_field[i, jb] + mu_eff_field[i, jt])

    eps_v = 0.5 * (eps_field[i, jb] + eps_field[i, jt])
    r_n = eps_field[i, jt] / eps_v
    r_s = eps_field[i, jb] / eps_v
    r_e = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                   + eps_field[i + 1, jb] + eps_field[i + 1, jt])
           / eps_v if i < Nx - 1 else 1.0)
    r_w = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                   + eps_field[i - 1, jb] + eps_field[i - 1, jt])
           / eps_v if i > 0 else 1.0)

    if i < Nx - 1:
        vE = v[i + 1, j]
        De = r_e * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i + 1]))
    else:
        vE = 0.0; De = 2.0 * mu_e * dyj / dxi
    if i > 0:
        vW = v[i - 1, j]
        Dw = r_w * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i - 1]))
    else:
        vW = 0.0; Dw = 2.0 * mu_e * dyj / dxi
    vN = v[i, j + 1]
    vS = v[i, j - 1]

    Dn = r_n * mu_e * dxi / dy_arr[jt]
    Ds = r_s * mu_e * dxi / dy_arr[jb]

    ue = 0.5 * (u[i + 1, jb] + u[i + 1, jt]) if i < Nx - 1 else 0.0
    uw = 0.5 * (u[i, jb] + u[i, jt]) if i > 0 else 0.0
    vn = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
    vs = 0.5 * (v[i, max(j - 1, 0)] + v[i, j])

    rho_loc = 0.5 * (rho_field[i, jb] + rho_field[i, jt])
    mu_loc = 0.5 * (mu_field[i, jb] + mu_field[i, jt])

    Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
    Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)

    umag = _umag_v(u, v, i, j, Nx, Ny)
    cF_v = cF_arr[i, jc]
    if cf_aniso != 0.0 and umag > 1e-10:
        ua_c = 0.25 * (u[i, jb] + u[i + 1, jb]
                       + u[i, jt] + u[i + 1, jt])
        ux2 = ua_c * ua_c
        uy2 = v[i, j] * v[i, j]
        xi4 = 4.0 * ux2 * uy2 / (umag * umag * umag * umag)
        cF_v = cF_v * (1.0 + cf_aniso * xi4)
    Sp = _porous_src_df(umag, K_arr[i, jc], cF_v, mu_loc, rho_loc) * vol

    p_src = (P[i, j - 1] - P[i, j]) * dxi
    sou = (_sou_corr_v_x(v, i, j, Nx, Fe, Fw)
           + _sou_corr_v_y(v, i, j, Ny, Fn, Fs))
    aP0 = aE + aW + aN + aS + Sp
    rhs = aE * vE + aW * vW + aN * vN + aS * vS + p_src + sou
    return aP0, rhs


@njit(cache=True)
def _mom_res_jit_2d(u, v, P, Nx, Ny, dx_arr, dy_arr,
                    rho_field, mu_eff_field, K_arr, cF_arr, mu_field,
                    eps_field, outlet_u_frac, cf_aniso):
    """Momentum residual  R = aP0*phi - (sum a_nb*phi_nb + p_src + SOU), on the
    CURRENT (post-correction, post-`_update_density`) fields.

    Same construction and the same BALANCED denominator as 3D
    (`_mom_res_jit_3d` — read its docstring for why the mass residual cannot do
    this job, and why `den = sum(0.5*(|lhs| + |rhs|))` makes a false zero
    structurally impossible: |lhs-rhs| <= |lhs|+|rhs| gives num <= 2*den, so
    num > 0 IMPLIES den > 0, and the ratio is bounded by 2).

    Returns raw (num_u, den_u, num_v, den_v) so the normalisation can be
    revisited without re-running.
    """
    nu_ = 0.0; du_ = 0.0
    for i in range(1, Nx):
        for j in range(Ny):
            aP0, rhs = _u_coeffs_df_2d(
                u, v, P, i, j, Nx, Ny, dx_arr, dy_arr,
                rho_field, mu_eff_field, K_arr, cF_arr, mu_field,
                eps_field, outlet_u_frac, cf_aniso)
            lhs = aP0 * u[i, j]
            nu_ += abs(lhs - rhs)
            du_ += 0.5 * (abs(lhs) + abs(rhs))

    nv_ = 0.0; dv_ = 0.0
    for i in range(Nx):
        for j in range(1, Ny):
            aP0, rhs = _v_coeffs_df_2d(
                u, v, P, i, j, Nx, Ny, dx_arr, dy_arr,
                rho_field, mu_eff_field, K_arr, cF_arr, mu_field,
                eps_field, cf_aniso)
            lhs = aP0 * v[i, j]
            nv_ += abs(lhs - rhs)
            dv_ += 0.5 * (abs(lhs) + abs(rhs))

    return nu_, du_, nv_, dv_


@njit(cache=True)
def _mass_res_solved_jit_2d(u, v, Nx, Ny, dx_arr, dy_arr,
                            rho_eps_field, cell_kind):
    """LOCAL continuity residual over the cells the pp equation ACTUALLY SOLVES.

    Three deliberate differences from `_mass_res_jit` (ledger C6 / C9):

      1. `cell_kind` (from `_build_pp_sparsity_pattern`) selects `== 0`. Outlet
         cells are `cell_kind == 1`: their continuity equation was REPLACED by
         `Pp = 0` (a Dirichlet pressure outlet), so they have no continuity
         residual to converge. Select by cell_kind, NOT by row index — a partial
         outlet pins only some cells of the row.
      2. The caller must pass a rho_eps rebuilt from the CURRENT (post-
         `_update_density`) rho. `_mass_res_jit` is handed the pre-update array
         the pp solve already zeroed itself against.
      3. It is a PER-CELL divergence, not a plane-integrated flux defect. The
         plane-integrated form telescopes to a TAUTOLOGY on a full-face outlet
         (measured 1.6e-15) — which is exactly why 2D's `tol` fires at the
         min-iter floor and stops the solve at iteration 20.

    Normalisation is per-cell and grid-scale invariant:
        R_cell = |net flux| / sum|face fluxes|      in [0, 1]
    NOT `max|net| / mdot_inlet` — that shrinks as the mesh refines (a finer cell
    simply carries less flux), so a fixed tolerance on it silently loosens.

    Returns (max_local, n_cells_counted).
    """
    r_max = 0.0
    n_cnt = 0
    for i in range(Nx):
        for j in range(Ny):
            k = i * Ny + j
            if cell_kind[k] != 0:
                continue                      # Dirichlet outlet: not solved
            dxi = dx_arr[i]; dyj = dy_arr[j]

            re_ = (0.5 * (rho_eps_field[i, j] + rho_eps_field[i + 1, j])
                   if i < Nx - 1 else rho_eps_field[i, j])
            rw_ = (0.5 * (rho_eps_field[i - 1, j] + rho_eps_field[i, j])
                   if i > 0 else rho_eps_field[i, j])
            rn_ = (0.5 * (rho_eps_field[i, j] + rho_eps_field[i, j + 1])
                   if j < Ny - 1 else rho_eps_field[i, j])
            rs_ = (0.5 * (rho_eps_field[i, j - 1] + rho_eps_field[i, j])
                   if j > 0 else rho_eps_field[i, j])

            fe = re_ * u[i + 1, j] * dyj
            fw = rw_ * u[i, j] * dyj
            fn = rn_ * v[i, j + 1] * dxi
            fs = rs_ * v[i, j] * dxi

            net = (fe - fw) + (fn - fs)
            thru = abs(fe) + abs(fw) + abs(fn) + abs(fs)
            if thru <= 0.0:
                continue                      # no flux -> nothing to violate
            n_cnt += 1
            r = abs(net) / thru
            if r > r_max:
                r_max = r
    return r_max, n_cnt


@njit(cache=True)
def _mass_global_jit_2d(v, Nx, Ny, dx_arr, rho_eps_field):
    """GLOBAL boundary mass balance on the streamwise (j) faces.

    Returns (mdot_in, mdot_out, backflow_frac_out). Signed, so a reversed outlet
    cell SUBTRACTS — the right global balance, but it also means positive and
    negative outlet fluxes can cancel and hide a recirculating outlet. Hence
    `backflow_frac_out = sum|negative outlet flux| / sum|outlet flux|` alongside.
    (Neither dimension has an outlet backflow clamp — ledger C2, still open.)
    """
    mdot_in = 0.0
    mdot_out = 0.0
    out_pos = 0.0
    out_neg = 0.0
    for i in range(Nx):
        A = dx_arr[i]
        fin = rho_eps_field[i, 0] * v[i, 0] * A
        fout = rho_eps_field[i, Ny - 1] * v[i, Ny] * A
        mdot_in += fin
        mdot_out += fout
        if fout >= 0.0:
            out_pos += fout
        else:
            out_neg += -fout
    tot = out_pos + out_neg
    bf = (out_neg / tot) if tot > 0.0 else 0.0
    return mdot_in, mdot_out, bf
