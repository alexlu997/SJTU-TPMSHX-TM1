"""
ltne_energy.py — Full-domain steady-state 2-fluid LTNE solver

Solves the coupled energy equations on the ENTIRE L × H domain
using spatially-varying velocity fields from SIMPLE solvers.

Supports zone-based partitioning: per-cell K_ff, K_ss, h_v, eps_f
via 2D arrays. Internal face conductance sums the two physical half-cell resistances.

Energy equations (steady state, LTNE):
  eps_f * rho_cp_A * (u_Ax * dTa/dx + u_Ay * dTa/dy) = K_ffA * nabla²Ta + h_vA * (Ts - Ta)
  eps_f * rho_cp_B * (u_Bx * dTb/dx + u_By * dTb/dy) = K_ffB * nabla²Tb + h_vB * (Ts - Tb)
  0 = K_ss * nabla²Ts + h_vA * (Ta - Ts) + h_vB * (Tb - Ts)

Velocity fields u_Ax(x,y), u_Ay(x,y), u_Bx(x,y), u_By(x,y) come from
SIMPLE solver (cell-centre interpolated), not assumed uniform.

Cell-coupled Gauss-Seidel: at each cell, update Ta → Ts → Tb sequentially
so that coupling information propagates within a single sweep.

Production R2 air/water callers explicitly supply full mass faces and fluid
identifiers. That mode solves conservative model-h transport with T unknown;
the temperature-form equations above remain the default for direct callers.
"""

import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError
from numba import njit, prange
from ._kernels_2d import (_model_h, MODEL_H_RELAXATION,
                         limited_face_increment, diffusion_conductance)


@njit(cache=True)
def _model_h_faces(T, mass, coefficients, direction, Tin, ifrac, sou, dx=None, dy=None):
    """Picard capacity/intercept per signed mass face, frozen per sweep.

    The shared enthalpy helper has an explicit strict-math compilation policy.
    """
    dx = np.ones(T.shape[0]) if dx is None else dx
    dy = np.ones(T.shape[1]) if dy is None else dy
    a, b, c, origin, _ = coefficients
    capacity = (np.empty_like(mass[0]), np.empty_like(mass[1]))
    deferred = (np.empty_like(mass[0]), np.empty_like(mass[1]))
    for axis in range(2):
        widths = dx if axis == 0 else dy
        for i in range(mass[axis].shape[0]):
            for j in range(mass[axis].shape[1]):
                pos = i if axis == 0 else j
                count = T.shape[axis]
                m = mass[axis][i, j]
                u = min(max(pos - 1 if m >= 0.0 else pos, 0), count - 1)
                up = (u, j) if axis == 0 else (i, u)
                t = T[up]
                inc = 0.0
                if sou and 0 < pos < count and 0 < u < count - 1:
                    prev = (u-1, j) if axis == 0 else (i, u-1)
                    nxt = (u+1, j) if axis == 0 else (i, u+1)
                    dm = .5*(widths[u-1]+widths[u])
                    dp = .5*(widths[u]+widths[u+1])
                    offset = .5*widths[u]
                    inc = limited_face_increment(T[prev], t, T[nxt], dm, dp,
                                                 offset if m >= 0.0 else -offset)
                if axis == direction // 2 and pos == (0 if direction % 2 == 0 else count):
                    patch = j if axis == 0 else i
                    inward = m if direction % 2 == 0 else -m
                    if ifrac[patch] > 0.0 and inward > 0.0:
                        t = Tin[patch]
                x = t - origin
                cp = a + b*x + c*x*x
                capacity[axis][i, j] = m * cp
                deferred[axis][i, j] = m * (_model_h(t+inc, coefficients) - cp*t)
    return capacity, deferred


@njit(cache=True)
def _thermal_diffusion_rows(K, dx, dy, direction=-1, ifrac=None, solid=False):
    """Fixed W/E/S/N conductances for one chunk, retaining directed row order."""
    nx, ny = K.shape
    rows = np.empty((nx, ny, 4))
    for i in range(nx):
        for j in range(ny):
            for face in range(4):
                axis = face // 2
                sign = -1 if face % 2 == 0 else 1
                ni = i + (sign if axis == 0 else 0)
                nj = j + (sign if axis == 1 else 0)
                area = dy[j] if axis == 0 else dx[i]
                width = dx[i] if axis == 0 else dy[j]
                value = 0.0
                if 0 <= ni < nx and 0 <= nj < ny:
                    dl = .5*dx[i] if axis == 0 else .5*dy[j]
                    dr = .5*dx[ni] if axis == 0 else .5*dy[nj]
                    value = diffusion_conductance(K[i, j], K[ni, nj], dl, dr)*area
                elif solid:
                    # Keep the adiabatic self-neighbor term: it affects GS,
                    # although its two sides cancel in the converged row.
                    value = K[i, j]*area/width
                elif face == direction and ifrac is not None:
                    patch = j if axis == 0 else i
                    value = 2*K[i, j]*area*ifrac[patch]/width
                rows[i, j, face] = value
    return rows


@njit(cache=True, inline='always')
def _model_h_cell(T, Ts, K, hv, i, j, dx, dy, direction, Tin, ifrac,
                  mass, capacity, deferred, fixed_conductance=None, fixed_hv=None):
    """Damped conservative row; no temperature-form minus T div(capacity)."""
    nx, ny = T.shape
    if fixed_hv is None:
        volume = dx[i] * dy[j]
        diagonal = hv[i, j] * volume
    else:
        diagonal = fixed_hv[i, j]
    rhs = diagonal * Ts[i, j]
    for face in range(4):
        axis = face // 2
        sign = -1.0 if face % 2 == 0 else 1.0
        ni = i + (int(sign) if axis == 0 else 0)
        nj = j + (int(sign) if axis == 1 else 0)
        fi = i + (1 if axis == 0 and sign > 0 else 0)
        fj = j + (1 if axis == 1 and sign > 0 else 0)
        cap = sign * capacity[axis][fi, fj]
        outward = sign * mass[axis][fi, fj]
        rhs -= sign * deferred[axis][fi, fj]
        inside = 0 <= ni < nx and 0 <= nj < ny
        neighbor = T[ni, nj] if inside else T[i, j]
        conductance = 0.0
        if inside:
            if fixed_conductance is None:
                area = dy[j] if axis == 0 else dx[i]
                dl = .5*dx[i] if axis == 0 else .5*dy[j]
                dr = .5*dx[ni] if axis == 0 else .5*dy[nj]
                conductance = diffusion_conductance(K[i,j], K[ni,nj], dl, dr)*area
            else:
                conductance = fixed_conductance[i, j, face]
        elif axis == direction // 2 and face % 2 == direction % 2:
            patch = j if axis == 0 else i
            if fixed_conductance is None:
                area = dy[j] if axis == 0 else dx[i]
                width = dx[i] if axis == 0 else dy[j]
                conductance = 2*K[i,j]*area*ifrac[patch]/width
            else:
                conductance = fixed_conductance[i, j, face]
            rhs += conductance * Tin[patch]
            diagonal += conductance
            conductance = 0.0
            if ifrac[patch] > 0.0 and outward < 0.0:
                neighbor = Tin[patch]
        diagonal += conductance + (cap if outward >= 0.0 else 0.0)
        rhs += (conductance - (cap if outward < 0.0 else 0.0)) * neighbor
    return T[i, j] + MODEL_H_RELAXATION * (rhs / diagonal - T[i, j])


@njit(cache=True)
def _sou_corr_x(T, i, j, Nx, Fx_field, dx=None):
    """Shared signed-flux x correction on the actual cell-centre coordinates."""
    correction = 0.0
    for face in (i, i+1):
        if 0 < face < Nx:
            flux = .5*(Fx_field[face-1, j]+Fx_field[face, j])
            up = face-1 if flux >= 0.0 else face
            if 0 < up < Nx-1:
                dm = .5*(dx[up-1]+dx[up]) if dx is not None else 1.
                dp = .5*(dx[up]+dx[up+1]) if dx is not None else 1.
                offset = .5*dx[up] if dx is not None else .5
                inc = limited_face_increment(T[up-1,j], T[up,j], T[up+1,j],
                                             dm, dp, offset if flux >= 0.0 else -offset)
                correction += (1.0 if face == i else -1.0)*flux*inc
    return correction


@njit(cache=True)
def _sou_corr_y(T, i, j, Ny, Fy_field, dy=None):
    """Shared signed-flux y correction on the actual cell-centre coordinates."""
    correction = 0.0
    for face in (j, j+1):
        if 0 < face < Ny:
            flux = .5*(Fy_field[i, face-1]+Fy_field[i, face])
            up = face-1 if flux >= 0.0 else face
            if 0 < up < Ny-1:
                dm = .5*(dy[up-1]+dy[up]) if dy is not None else 1.
                dp = .5*(dy[up]+dy[up+1]) if dy is not None else 1.
                offset = .5*dy[up] if dy is not None else .5
                inc = limited_face_increment(T[i,up-1], T[i,up], T[i,up+1],
                                             dm, dp, offset if flux >= 0.0 else -offset)
                correction += (1.0 if face == j else -1.0)*flux*inc
    return correction


@njit(cache=True, nogil=True)
def _gs_full_chunk(Ta, Tb, Ts, Nx, Ny, dx_arr, dy_arr,
                   K_ffA_arr, K_ffB_arr, K_ss_arr,
                   h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                   rho_cp_fA, rho_cp_fB,
                   ucA, vcA, ucB, vcB,
                   bc_A, bc_B, T_inA_arr, T_inB_arr,
                   ifrac_A, ifrac_B,
                   n_iters, freeze_Tb, sou_B, inlet_flux_A=None, inlet_flux_B=None,
                   mass_A=None, mass_B=None, cp_A=None, cp_B=None,
                   last_Ta=None, last_Tb=None):
    """Cell-coupled Gauss-Seidel: at each cell update Ta → Ts → Tb.
    dx_arr: 1D [Nx], dy_arr: 1D [Ny] — non-uniform cell widths.

    A3 (2026-07-06) — shared-face convection: the upwind base flux is now
    the SIGNED shared-face flux Fe = 0.5*(F_P + F_E) (same face averaging
    as the SOU correction), so the two cells sharing a face apply the
    IDENTICAL flux — removing the cell-local |u|-magnitude mismatch that
    leaked enthalpy on non-uniform (eps*rho_cp*u) fields. The net signed
    outflow is deliberately NOT added to aP (Patankar mass-consistent /
    temperature-form): the governing LTNE equation is eps*rho_cp*u·grad(T)
    = div(F T) − T div(F), and with the 2D CELL-CENTRE interpolated
    velocities the discrete div(F) is nonzero, so keeping net_out would
    make a uniform temperature field a non-fixed-point (verified: it broke
    the isothermal outer-loop consistency test). The 3D staggered kernel
    can keep net_out because its face velocities are discretely
    divergence-free. Uniform-flux fields reproduce the legacy scheme
    exactly. ``sou_B`` (0/1) optionally enables the
    face-consistent SOU for fluid B — RE-TESTED 2026-07-06 (A3): even in
    the telescoping face-consistent form the B-side deferred correction
    still oscillates (residual plateaus ~1 K, serial/red-black fixed
    points differ ~0.4 K on a uniform counterflow case), confirming the
    2026-06-24 diagnosis that the instability is the deferred-correction
    fixed point on a near-isothermal high-rho_cp field, NOT the old
    non-conservative flux. Default stays OFF (accuracy cost documented
    <0.4% of Q); the conservative BASE flux above is the A3 fix. This
    temperature-form policy does not apply to model-h: its driver enables
    SOU for both fluids with the shared damped conservative row.
    """
    max_chg = 0.0

    # Determine sweep direction: compromise between A and B
    # i-direction: follow A's preference
    if bc_A == 1:
        i0, i1, di = Nx - 1, -1, -1
    else:
        i0, i1, di = 0, Nx, 1
    # j-direction: follow B's preference
    if bc_B == 3 or (bc_A == 3 and bc_B == 0):
        j0, j1, dj = Ny - 1, -1, -1
    else:
        j0, j1, dj = 0, Ny, 1

    # Per-cell convective flux fields (velocity / rho_cp / eps_f frozen
    # across the GS sweep). FOU and SOU share the same signed face fluxes.
    FxAs = np.empty((Nx, Ny)); FyAs = np.empty((Nx, Ny))
    FxBs = np.empty((Nx, Ny)); FyBs = np.empty((Nx, Ny))
    # Rebuild at chunk boundaries: progress callbacks may update coefficients.
    diff_A = _thermal_diffusion_rows(K_ffA_arr, dx_arr, dy_arr, bc_A, ifrac_A)
    diff_B = _thermal_diffusion_rows(K_ffB_arr, dx_arr, dy_arr, bc_B, ifrac_B)
    diff_s = _thermal_diffusion_rows(K_ss_arr, dx_arr, dy_arr, solid=True)
    hvA_vol = np.empty((Nx, Ny)); hvB_vol = np.empty((Nx, Ny))
    diagonal_s = np.empty((Nx, Ny))
    for _i in range(Nx):
        for _j in range(Ny):
            _efr = eps_fA_arr[_i, _j] * rho_cp_fA[_i, _j]
            FxAs[_i, _j] = _efr * ucA[_i, _j] * dy_arr[_j]
            FyAs[_i, _j] = _efr * vcA[_i, _j] * dx_arr[_i]
            _efrB = eps_fB_arr[_i, _j] * rho_cp_fB[_i, _j]
            FxBs[_i, _j] = _efrB * ucB[_i, _j] * dy_arr[_j]
            FyBs[_i, _j] = _efrB * vcB[_i, _j] * dx_arr[_i]
            volume = dx_arr[_i] * dy_arr[_j]
            hvA_vol[_i, _j] = h_vA_arr[_i, _j] * volume
            hvB_vol[_i, _j] = h_vB_arr[_i, _j] * volume
            diagonal_s[_i, _j] = (diff_s[_i, _j, 1] + diff_s[_i, _j, 0]
                                       + diff_s[_i, _j, 3] + diff_s[_i, _j, 2]
                                       + hvA_vol[_i, _j] + hvB_vol[_i, _j])

    for _it in range(n_iters):
        max_chg = 0.0
        if mass_A is not None:
            last_Ta[:] = Ta
            last_Tb[:] = Tb
            cap_A, def_A = _model_h_faces(last_Ta, mass_A, cp_A, bc_A, T_inA_arr, ifrac_A, True, dx_arr, dy_arr)
            cap_B, def_B = _model_h_faces(last_Tb, mass_B, cp_B, bc_B, T_inB_arr, ifrac_B, sou_B == 1, dx_arr, dy_arr)

        for i in range(i0, i1, di):
            for j in range(j0, j1, dj):

                # ── Update Fluid A ──
                hvA = hvA_vol[i, j]

                # Face spacing δx_e = 0.5·(dx_P + dx_E) ensures conservative
                # diffusion stencil — same value used by cell P (as east-flux)
                # and cell E (as west-flux) at shared face. Old /dxi used cell
                # P width only; non-uniform grids broke face-flux symmetry.
                dE = diff_A[i, j, 1]
                dW = diff_A[i, j, 0]
                dN = diff_A[i, j, 3]
                dS = diff_A[i, j, 2]

                # A3: signed shared-face fluxes (arithmetic mean of the
                # two cells' signed fluxes — identical value on both
                # sides of a face ⇒ globally telescoping). Domain-edge
                # faces fall back to the cell's own flux.
                FxP = FxAs[i, j]; FyP = FyAs[i, j]
                Fe = 0.5 * (FxP + (FxAs[i+1, j] if i < Nx-1 else FxP))
                Fw = 0.5 * ((FxAs[i-1, j] if i > 0 else FxP) + FxP)
                Fn = 0.5 * (FyP + (FyAs[i, j+1] if j < Ny-1 else FyP))
                Fs = 0.5 * ((FyAs[i, j-1] if j > 0 else FyP) + FyP)
                aE = dE + max(-Fe, 0.0)
                aW = dW + max(Fw, 0.0)
                aN = dN + max(-Fn, 0.0)
                aS = dS + max(Fs, 0.0)

                tE = Ta[i+1,j] if i < Nx-1 else Ta[i,j]
                tW = Ta[i-1,j] if i > 0    else Ta[i,j]
                tN = Ta[i,j+1] if j < Ny-1 else Ta[i,j]
                tS = Ta[i,j-1] if j > 0    else Ta[i,j]
                # Dirichlet temperature on the open physical inlet face only.
                # All real cells retain diffusion, convection and full hv*dV.
                if (bc_A == 0 and i == 0) or (bc_A == 1 and i == Nx-1) or \
                   (bc_A == 2 and j == 0) or (bc_A == 3 and j == Ny-1):
                    idx_in = j if bc_A <= 1 else i
                    frac = ifrac_A[idx_in]
                    d_in = diff_A[i, j, bc_A]
                    f_in = Fw if bc_A == 0 else (-Fe if bc_A == 1 else
                            (Fs if bc_A == 2 else -Fn))
                    if inlet_flux_A is not None:
                        f_in = inlet_flux_A[idx_in]
                    a_in = d_in + (max(f_in, 0.0) if frac > 0.0 else 0.0)
                    if bc_A == 0:
                        aW = a_in
                        tW = T_inA_arr[idx_in]
                    elif bc_A == 1:
                        aE = a_in
                        tE = T_inA_arr[idx_in]
                    elif bc_A == 2:
                        aS = a_in
                        tS = T_inA_arr[idx_in]
                    else:
                        aN = a_in
                        tN = T_inA_arr[idx_in]

                # Model-h uses its own frozen-face SOU, computed above.
                sou = (_sou_corr_x(Ta, i, j, Nx, FxAs, dx_arr)
                       + _sou_corr_y(Ta, i, j, Ny, FyAs, dy_arr)) if mass_A is None else 0.0

                aP = aE + aW + aN + aS + hvA
                if mass_A is not None:
                    new = _model_h_cell(Ta, Ts, K_ffA_arr, h_vA_arr, i, j,
                                        dx_arr, dy_arr, bc_A, T_inA_arr, ifrac_A, mass_A, cap_A, def_A, diff_A, hvA_vol)
                else:
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + hvA*Ts[i,j] + sou) / aP
                # Model-h already damps both fluids, including outlet cells.
                is_outlet_A = ((bc_A == 0 and i == Nx-1) or (bc_A == 1 and i == 0) or
                               (bc_A == 2 and j == Ny-1) or (bc_A == 3 and j == 0))
                if mass_A is None and not is_outlet_A:
                    new = Ta[i,j] + 0.7 * (new - Ta[i,j])
                chg = abs(new - Ta[i,j])
                if chg > max_chg: max_chg = chg
                Ta[i,j] = new

                # ── Update Solid (using just-updated Ta, old Tb) ──
                hvA_s = hvA_vol[i, j]
                hvB_s = hvB_vol[i, j]

                # Face spacing for solid diffusion stencil (conservative)
                Ds_e = diff_s[i, j, 1]
                Ds_w = diff_s[i, j, 0]
                Ds_n = diff_s[i, j, 3]
                Ds_s = diff_s[i, j, 2]

                sE = Ts[i+1,j] if i < Nx-1 else Ts[i,j]
                sW = Ts[i-1,j] if i > 0    else Ts[i,j]
                sN = Ts[i,j+1] if j < Ny-1 else Ts[i,j]
                sS = Ts[i,j-1] if j > 0    else Ts[i,j]

                aP_s = diagonal_s[i, j]
                new_s = (Ds_e*sE + Ds_w*sW + Ds_n*sN + Ds_s*sS + hvA_s*Ta[i,j] + hvB_s*Tb[i,j]) / aP_s
                chg = abs(new_s - Ts[i,j])
                if chg > max_chg: max_chg = chg
                Ts[i,j] = new_s

                # ── Update Fluid B (using just-updated Ts) ──
                # C-1: when freeze_Tb == 1, Tb is pinned to a prescribed field;
                # skip the entire B update. Solid equation still uses the pinned
                # Tb via hvB_s*Tb[i,j] above, so the air→solid→water coupling
                # remains intact.
                if freeze_Tb == 0:
                    hvB = hvB_vol[i, j]

                    # Face spacing for B diffusion stencil (conservative)
                    dE = diff_B[i, j, 1]
                    dW = diff_B[i, j, 0]
                    dN = diff_B[i, j, 3]
                    dS = diff_B[i, j, 2]

                    # A3: conservative signed shared-face fluxes (see the
                    # fluid-A block).
                    FxP = FxBs[i, j]; FyP = FyBs[i, j]
                    Fe = 0.5 * (FxP + (FxBs[i+1, j] if i < Nx-1 else FxP))
                    Fw = 0.5 * ((FxBs[i-1, j] if i > 0 else FxP) + FxP)
                    Fn = 0.5 * (FyP + (FyBs[i, j+1] if j < Ny-1 else FyP))
                    Fs = 0.5 * ((FyBs[i, j-1] if j > 0 else FyP) + FyP)
                    aE = dE + max(-Fe, 0.0)
                    aW = dW + max(Fw, 0.0)
                    aN = dN + max(-Fn, 0.0)
                    aS = dS + max(Fs, 0.0)

                    tE = Tb[i+1,j] if i < Nx-1 else Tb[i,j]
                    tW = Tb[i-1,j] if i > 0    else Tb[i,j]
                    tN = Tb[i,j+1] if j < Ny-1 else Tb[i,j]
                    tS = Tb[i,j-1] if j > 0    else Tb[i,j]
                    # Dirichlet temperature on the open physical inlet face only.
                    # All real cells retain diffusion, convection and full hv*dV.
                    if (bc_B == 0 and i == 0) or (bc_B == 1 and i == Nx-1) or \
                       (bc_B == 2 and j == 0) or (bc_B == 3 and j == Ny-1):
                        idx_in = j if bc_B <= 1 else i
                        frac = ifrac_B[idx_in]
                        d_in = diff_B[i, j, bc_B]
                        f_in = Fw if bc_B == 0 else (-Fe if bc_B == 1 else
                                (Fs if bc_B == 2 else -Fn))
                        if inlet_flux_B is not None:
                            f_in = inlet_flux_B[idx_in]
                        a_in = d_in + (max(f_in, 0.0) if frac > 0.0 else 0.0)
                        if bc_B == 0:
                            aW = a_in
                            tW = T_inB_arr[idx_in]
                        elif bc_B == 1:
                            aE = a_in
                            tE = T_inB_arr[idx_in]
                        elif bc_B == 2:
                            aS = a_in
                            tS = T_inB_arr[idx_in]
                        else:
                            aN = a_in
                            tN = T_inB_arr[idx_in]


                    # History: fluid-B SOU was disabled 2026-06-24 — the
                    # then NON-conservative correction injected spurious
                    # ρcp-scaled energy and destabilised the outer
                    # coupling at fine grids (water dT_B oscillated at
                    # N=80). A3 (2026-07-06) re-enables it in the
                    # face-consistent telescoping form, gated by sou_B
                    # (kill switch: solve_full_domain(use_sou_B=False)).
                    if sou_B == 1 and mass_A is None:
                        sou = (_sou_corr_x(Tb, i, j, Nx, FxBs, dx_arr)
                               + _sou_corr_y(Tb, i, j, Ny, FyBs, dy_arr))
                    else:
                        sou = 0.0

                    aP = aE + aW + aN + aS + hvB
                    if mass_A is not None:
                        new = _model_h_cell(Tb, Ts, K_ffB_arr, h_vB_arr, i, j,
                                            dx_arr, dy_arr, bc_B, T_inB_arr, ifrac_B, mass_B, cap_B, def_B, diff_B, hvB_vol)
                    else:
                        new = (aE*tE + aW*tW + aN*tN + aS*tS + hvB*Ts[i,j] + sou) / aP
                    chg = abs(new - Tb[i,j])
                    if chg > max_chg: max_chg = chg
                    Tb[i,j] = new

        if max_chg < 1e-10:
            break

    return max_chg


@njit(cache=True, parallel=True)
def _gs_full_chunk_rb(Ta, Tb, Ts, Nx, Ny, dx_arr, dy_arr,
                      K_ffA_arr, K_ffB_arr, K_ss_arr,
                      h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                      rho_cp_fA, rho_cp_fB,
                      ucA, vcA, ucB, vcB,
                      bc_A, bc_B, T_inA_arr, T_inB_arr,
                      ifrac_A, ifrac_B,
                      n_iters, freeze_Tb, sou_B, inlet_flux_A=None, inlet_flux_B=None,
                      mass_A=None, mass_B=None, cp_A=None, cp_B=None,
                      last_Ta=None, last_Tb=None):
    """Red-black `prange`-parallel twin of `_gs_full_chunk` (2D).

    Same construction as the 3D `_gs_full_chunk_3d_stag_rb`: cells are swept by
    checkerboard colour (i+j parity) so same-colour cells update independently,
    and the 2-away SOU deferred correction is read from a start-of-sweep snapshot
    (the only same-colour dependency). Converges to the same field as the serial
    kernel; used on large 2D grids (> `_RB_ENERGY_2D_GATE`).
    """
    max_chg = 0.0
    ncell = Nx * Ny
    # Per-cell signed convective flux fields, shared by FOU and SOU.
    FxAs = np.empty((Nx, Ny)); FyAs = np.empty((Nx, Ny))
    FxBs = np.empty((Nx, Ny)); FyBs = np.empty((Nx, Ny))
    # Rebuild at chunk boundaries: progress callbacks may update coefficients.
    diff_A = _thermal_diffusion_rows(K_ffA_arr, dx_arr, dy_arr, bc_A, ifrac_A)
    diff_B = _thermal_diffusion_rows(K_ffB_arr, dx_arr, dy_arr, bc_B, ifrac_B)
    diff_s = _thermal_diffusion_rows(K_ss_arr, dx_arr, dy_arr, solid=True)
    hvA_vol = np.empty((Nx, Ny)); hvB_vol = np.empty((Nx, Ny))
    diagonal_s = np.empty((Nx, Ny))
    for _ii in range(Nx):
        for _jj in range(Ny):
            _efr = eps_fA_arr[_ii, _jj] * rho_cp_fA[_ii, _jj]
            FxAs[_ii, _jj] = _efr * ucA[_ii, _jj] * dy_arr[_jj]
            FyAs[_ii, _jj] = _efr * vcA[_ii, _jj] * dx_arr[_ii]
            _efrB = eps_fB_arr[_ii, _jj] * rho_cp_fB[_ii, _jj]
            FxBs[_ii, _jj] = _efrB * ucB[_ii, _jj] * dy_arr[_jj]
            FyBs[_ii, _jj] = _efrB * vcB[_ii, _jj] * dx_arr[_ii]
            volume = dx_arr[_ii] * dy_arr[_jj]
            hvA_vol[_ii, _jj] = h_vA_arr[_ii, _jj] * volume
            hvB_vol[_ii, _jj] = h_vB_arr[_ii, _jj] * volume
            diagonal_s[_ii, _jj] = (diff_s[_ii, _jj, 1] + diff_s[_ii, _jj, 0]
                                       + diff_s[_ii, _jj, 3] + diff_s[_ii, _jj, 2]
                                       + hvA_vol[_ii, _jj] + hvB_vol[_ii, _jj])
    for _it in range(n_iters):
        Ta_snap = Ta.copy()
        Tb_snap = Tb.copy()
        if mass_A is not None:
            last_Ta[:] = Ta_snap
            last_Tb[:] = Tb_snap
            cap_A, def_A = _model_h_faces(last_Ta, mass_A, cp_A, bc_A, T_inA_arr, ifrac_A, True, dx_arr, dy_arr)
            cap_B, def_B = _model_h_faces(last_Tb, mass_B, cp_B, bc_B, T_inB_arr, ifrac_B, sou_B == 1, dx_arr, dy_arr)
        sweep_chg = 0.0
        for color in range(2):
            color_chg = 0.0
            for idx in prange(ncell):
                i = idx // Ny
                j = idx - i * Ny
                if ((i + j) & 1) != color:
                    continue
                cell_chg = 0.0

                # ── Fluid A ──
                hvA = hvA_vol[i, j]
                dE = diff_A[i, j, 1]
                dW = diff_A[i, j, 0]
                dN = diff_A[i, j, 3]
                dS = diff_A[i, j, 2]
                # A3: conservative signed shared-face fluxes (serial twin).
                FxP = FxAs[i, j]; FyP = FyAs[i, j]
                Fe = 0.5 * (FxP + (FxAs[i+1, j] if i < Nx-1 else FxP))
                Fw = 0.5 * ((FxAs[i-1, j] if i > 0 else FxP) + FxP)
                Fn = 0.5 * (FyP + (FyAs[i, j+1] if j < Ny-1 else FyP))
                Fs = 0.5 * ((FyAs[i, j-1] if j > 0 else FyP) + FyP)
                aE = dE + max(-Fe, 0.0)
                aW = dW + max(Fw, 0.0)
                aN = dN + max(-Fn, 0.0)
                aS = dS + max(Fs, 0.0)
                tE = Ta[i+1,j] if i < Nx-1 else Ta[i,j]
                tW = Ta[i-1,j] if i > 0    else Ta[i,j]
                tN = Ta[i,j+1] if j < Ny-1 else Ta[i,j]
                tS = Ta[i,j-1] if j > 0    else Ta[i,j]
                # Dirichlet temperature on the open physical inlet face only.
                # All real cells retain diffusion, convection and full hv*dV.
                if (bc_A == 0 and i == 0) or (bc_A == 1 and i == Nx-1) or \
                   (bc_A == 2 and j == 0) or (bc_A == 3 and j == Ny-1):
                    idx_in = j if bc_A <= 1 else i
                    frac = ifrac_A[idx_in]
                    d_in = diff_A[i, j, bc_A]
                    f_in = Fw if bc_A == 0 else (-Fe if bc_A == 1 else
                            (Fs if bc_A == 2 else -Fn))
                    if inlet_flux_A is not None:
                        f_in = inlet_flux_A[idx_in]
                    a_in = d_in + (max(f_in, 0.0) if frac > 0.0 else 0.0)
                    if bc_A == 0:
                        aW = a_in
                        tW = T_inA_arr[idx_in]
                    elif bc_A == 1:
                        aE = a_in
                        tE = T_inA_arr[idx_in]
                    elif bc_A == 2:
                        aS = a_in
                        tS = T_inA_arr[idx_in]
                    else:
                        aN = a_in
                        tN = T_inA_arr[idx_in]

                # Model-h uses its own frozen-face SOU, computed above.
                sou = (_sou_corr_x(Ta_snap, i, j, Nx, FxAs, dx_arr)
                       + _sou_corr_y(Ta_snap, i, j, Ny, FyAs, dy_arr)) if mass_A is None else 0.0
                aP = aE + aW + aN + aS + hvA
                if mass_A is not None:
                    new = _model_h_cell(Ta, Ts, K_ffA_arr, h_vA_arr, i, j,
                                        dx_arr, dy_arr, bc_A, T_inA_arr, ifrac_A, mass_A, cap_A, def_A, diff_A, hvA_vol)
                else:
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + hvA*Ts[i,j] + sou) / aP
                # Retain the serial policy; model-h is damped in its row.
                is_outlet_A = ((bc_A == 0 and i == Nx-1) or (bc_A == 1 and i == 0) or
                               (bc_A == 2 and j == Ny-1) or (bc_A == 3 and j == 0))
                if mass_A is None and not is_outlet_A:
                    new = Ta[i,j] + 0.7 * (new - Ta[i,j])
                c = abs(new - Ta[i,j])
                if c > cell_chg: cell_chg = c
                Ta[i,j] = new

                # ── Solid ──
                hvA_s = hvA_vol[i, j]
                hvB_s = hvB_vol[i, j]
                Ds_e = diff_s[i, j, 1]
                Ds_w = diff_s[i, j, 0]
                Ds_n = diff_s[i, j, 3]
                Ds_s = diff_s[i, j, 2]
                sE = Ts[i+1,j] if i < Nx-1 else Ts[i,j]
                sW = Ts[i-1,j] if i > 0    else Ts[i,j]
                sN = Ts[i,j+1] if j < Ny-1 else Ts[i,j]
                sS = Ts[i,j-1] if j > 0    else Ts[i,j]
                aP_s = diagonal_s[i, j]
                new_s = (Ds_e*sE + Ds_w*sW + Ds_n*sN + Ds_s*sS + hvA_s*Ta[i,j] + hvB_s*Tb[i,j]) / aP_s
                c = abs(new_s - Ts[i,j])
                if c > cell_chg: cell_chg = c
                Ts[i,j] = new_s

                # ── Fluid B ──
                if freeze_Tb == 0:
                    hvB = hvB_vol[i, j]
                    dE = diff_B[i, j, 1]
                    dW = diff_B[i, j, 0]
                    dN = diff_B[i, j, 3]
                    dS = diff_B[i, j, 2]
                    # A3: conservative signed shared-face fluxes; SOU
                    # re-enabled in face-consistent form, gated by sou_B
                    # (see the serial kernel for the 2026-06-24 history).
                    FxP = FxBs[i, j]; FyP = FyBs[i, j]
                    Fe = 0.5 * (FxP + (FxBs[i+1, j] if i < Nx-1 else FxP))
                    Fw = 0.5 * ((FxBs[i-1, j] if i > 0 else FxP) + FxP)
                    Fn = 0.5 * (FyP + (FyBs[i, j+1] if j < Ny-1 else FyP))
                    Fs = 0.5 * ((FyBs[i, j-1] if j > 0 else FyP) + FyP)
                    aE = dE + max(-Fe, 0.0)
                    aW = dW + max(Fw, 0.0)
                    aN = dN + max(-Fn, 0.0)
                    aS = dS + max(Fs, 0.0)
                    tE = Tb[i+1,j] if i < Nx-1 else Tb[i,j]
                    tW = Tb[i-1,j] if i > 0    else Tb[i,j]
                    tN = Tb[i,j+1] if j < Ny-1 else Tb[i,j]
                    tS = Tb[i,j-1] if j > 0    else Tb[i,j]
                    # Dirichlet temperature on the open physical inlet face only.
                    # All real cells retain diffusion, convection and full hv*dV.
                    if (bc_B == 0 and i == 0) or (bc_B == 1 and i == Nx-1) or \
                       (bc_B == 2 and j == 0) or (bc_B == 3 and j == Ny-1):
                        idx_in = j if bc_B <= 1 else i
                        frac = ifrac_B[idx_in]
                        d_in = diff_B[i, j, bc_B]
                        f_in = Fw if bc_B == 0 else (-Fe if bc_B == 1 else
                                (Fs if bc_B == 2 else -Fn))
                        if inlet_flux_B is not None:
                            f_in = inlet_flux_B[idx_in]
                        a_in = d_in + (max(f_in, 0.0) if frac > 0.0 else 0.0)
                        if bc_B == 0:
                            aW = a_in
                            tW = T_inB_arr[idx_in]
                        elif bc_B == 1:
                            aE = a_in
                            tE = T_inB_arr[idx_in]
                        elif bc_B == 2:
                            aS = a_in
                            tS = T_inB_arr[idx_in]
                        else:
                            aN = a_in
                            tN = T_inB_arr[idx_in]

                    if sou_B == 1 and mass_A is None:
                        sou = (_sou_corr_x(Tb_snap, i, j, Nx, FxBs, dx_arr)
                               + _sou_corr_y(Tb_snap, i, j, Ny, FyBs, dy_arr))
                    else:
                        sou = 0.0
                    aP = aE + aW + aN + aS + hvB
                    if mass_A is not None:
                        new = _model_h_cell(Tb, Ts, K_ffB_arr, h_vB_arr, i, j,
                                            dx_arr, dy_arr, bc_B, T_inB_arr, ifrac_B, mass_B, cap_B, def_B, diff_B, hvB_vol)
                    else:
                        new = (aE*tE + aW*tW + aN*tN + aS*tS + hvB*Ts[i,j] + sou) / aP
                    c = abs(new - Tb[i,j])
                    if c > cell_chg: cell_chg = c
                    Tb[i,j] = new

                color_chg = max(color_chg, cell_chg)
            if color_chg > sweep_chg:
                sweep_chg = color_chg

        max_chg = sweep_chg
        if max_chg < 1e-10:
            break

    return max_chg


# Diagnostic-only convergence trace (point 0 quantify, 2026-05-22) — mirrors
# ltne_energy_3d._CONV_TRACE. None in production → zero overhead.
_CONV_TRACE = None

# Red-black parallel 2D energy kernel selector (mirrors ltne_energy_3d).
# OPT-IN (default off): the 2D cell-centre SOU (`_sou_corr_x/y`, minmod limiter)
# is now globally conservative (face-consistent flux since 2026-06-25), but the
# RB kernel still reads the 2-away SOU stencil from a start-of-sweep snapshot,
# and that lag is more sensitive here than the 3D face-shared deferred form
# (which matches serial to ~1e-5 K), so the RB converged field can differ from
# serial by
# ~0.1 K on strongly-advective cases (still <0.03% of T, Q-negligible). 2D grids
# are also usually < the gate (so RB rarely fires anyway). Enable explicitly
# (`_RB_ENERGY_2D = True`) for large 2D runs where the small difference is
# acceptable. The 3D path is default-on because its conservative kernel is clean.
_RB_ENERGY_2D = False
_RB_ENERGY_2D_GATE = 30_000


@njit(cache=True)
def _model_face_values(T, mass, capacity, deferred, direction, Tin, ifrac):
    flux = (np.empty_like(capacity[0]), np.empty_like(capacity[1]))
    for axis in range(2):
        for i in range(capacity[axis].shape[0]):
            for j in range(capacity[axis].shape[1]):
                pos = i if axis == 0 else j
                count = T.shape[axis]
                cap = capacity[axis][i, j]
                m = mass[axis][i, j]
                u = min(max(pos-1 if m >= 0.0 else pos, 0), count-1)
                t = T[u, j] if axis == 0 else T[i, u]
                if axis == direction // 2 and pos == (0 if direction % 2 == 0 else count):
                    patch = j if axis == 0 else i
                    inward = m if direction % 2 == 0 else -m
                    if ifrac[patch] > 0.0 and inward > 0.0:
                        t = Tin[patch]
                flux[axis][i, j] = cap*t + deferred[axis][i, j]
    return flux


def _model_h_balance(Ta, Tb, Ts, K_A, K_B, K_s, hv_A, hv_B, dx, dy,
                     mass_A, mass_B, cp_A, cp_B, dir_A, dir_B,
                     Tin_A, Tin_B, frac_A, frac_B, sou_B, last_Ta, last_Tb):
    """Evaluate final nonlinear raw-state balances without another sweep."""
    area = dx[:, None] * dy[None, :]

    def divergence(face):
        return face[0][1:] - face[0][:-1] + face[1][:, 1:] - face[1][:, :-1]

    def conduction(T, K):
        fx, fy = np.zeros((T.shape[0]+1, T.shape[1])), np.zeros((T.shape[0], T.shape[1]+1))
        rx = .5*(dx[:-1, None]*K[1:] + dx[1:, None]*K[:-1])
        ry = .5*(dy[None, :-1]*K[:, 1:] + dy[None, 1:]*K[:, :-1])
        gx = np.divide(K[:-1]*K[1:], rx, out=np.zeros_like(rx), where=rx > 0)
        gy = np.divide(K[:, :-1]*K[:, 1:], ry, out=np.zeros_like(ry), where=ry > 0)
        fx[1:-1] = gx * dy[None, :] * (T[:-1]-T[1:])
        fy[:, 1:-1] = gy * dx[:, None] * (T[:, :-1]-T[:, 1:])
        return -divergence((fx, fy))

    def boundaries(face):
        return (-face[0][0], face[0][-1], -face[1][:, 0], face[1][:, -1])

    sides = {}
    residuals = []
    defects = []
    exchanges = []
    for label, T, K, hv, mass, cp, direction, tin, frac, sou, snapshot in (
            ('A', Ta, K_A, hv_A, mass_A, cp_A, dir_A, Tin_A, frac_A, True, last_Ta),
            ('B', Tb, K_B, hv_B, mass_B, cp_B, dir_B, Tin_B, frac_B, sou_B, last_Tb)):
        cap, deferred = _model_h_faces(T, mass, cp, direction, tin, frac, sou, dx, dy)
        flux = _model_face_values(T, mass, cap, deferred, direction, tin, frac)
        old_cap, old_deferred = _model_h_faces(snapshot, mass, cp, direction, tin, frac, sou, dx, dy)
        linear_flux = _model_face_values(T, mass, old_cap, old_deferred, direction, tin, frac)
        defect = divergence(linear_flux) - divergence(flux)
        exchange = hv*(Ts-T)*area
        residual = -divergence(flux) + conduction(T, K) + exchange
        inlet = (0, slice(None)) if direction == 0 else ((-1, slice(None)) if direction == 1
                 else ((slice(None), 0) if direction == 2 else (slice(None), -1)))
        cross = dy if direction <= 1 else dx
        width = (dx[0] if direction == 0 else dx[-1]) if direction <= 1 else (dy[0] if direction == 2 else dy[-1])
        diffusion_in = 2*K[inlet]*cross*frac/width*(tin-T[inlet])
        residual[inlet] += diffusion_in
        outward_mass = boundaries(mass)
        outward_h = boundaries(flux)
        unknown = sum(int(np.count_nonzero((m < 0) & (frac <= 0))) if f == direction
                      else int(np.count_nonzero(m < 0)) for f, m in enumerate(outward_mass))
        q = -sum(float(f.sum()) for f in outward_h)
        sides[label] = dict(
            Q_advective_W_per_m=q, inlet_conduction_W_per_m=float(diffusion_in.sum()),
            exchange_W_per_m=float(exchange.sum()), source_W_per_m=0.0,
            residual_sum_W_per_m=float(residual.sum()),
            residual_max_abs_W_per_m=float(np.max(np.abs(residual))),
            linearized_residual_sum_W_per_m=float((residual-defect).sum()),
            linearized_residual_max_abs_W_per_m=float(np.max(np.abs(residual-defect))),
            linearization_defect_sum_W_per_m=float(defect.sum()),
            linearization_defect_max_abs_W_per_m=float(np.max(np.abs(defect))),
            mass_net_out_kg_s_per_m=float(divergence(mass).sum()),
            mass_local_max_abs_kg_s_per_m=float(np.max(np.abs(divergence(mass)))),
            mass_in_kg_s_per_m=sum(float(np.maximum(-m, 0).sum()) for m in outward_mass),
            mass_out_kg_s_per_m=sum(float(np.maximum(m, 0).sum()) for m in outward_mass),
            boundary_mass_out_kg_s_per_m=[f.tolist() for f in outward_mass],
            boundary_h_out_W_per_m=[f.tolist() for f in outward_h],
            mass_faces_kg_s_per_m=[f.tolist() for f in mass],
            h_faces_W_per_m=[f.tolist() for f in flux],
            inlet_conduction_faces_W_per_m=diffusion_in.tolist(),
            cp_coefficients=list(cp), unknown_inflow_faces=unknown,
            physical_boundary_complete=(unknown == 0))
        # Native 2D power is W/m. The 1 W/m floor also defines the
        # near-zero-load absolute scale; this is not a temperature tolerance.
        side_scale = max(abs(float(exchange.sum())), 1.0)
        sides[label]['strict_normalization_W_per_m'] = side_scale
        sides[label]['residual_cellmax_rel'] = float(np.max(np.abs(residual))) * Ta.size / side_scale
        residuals.append(residual)
        defects.append(defect)
        exchanges.append(exchange)
    solid = conduction(Ts, K_s) - exchanges[0] - exchanges[1]
    net = sum(s['Q_advective_W_per_m'] + s['inlet_conduction_W_per_m'] for s in sides.values())
    scale = max(abs(sides['A']['exchange_W_per_m']), abs(sides['B']['exchange_W_per_m']), 1.0)
    solid_sum = float(solid.sum())
    finite = all(np.all(np.isfinite(a)) for a in (
        Ta, Tb, Ts, K_A, K_B, K_s, hv_A, hv_B, dx, dy,
        *mass_A, *mass_B, cp_A, cp_B, last_Ta, last_Tb,
        *residuals, *defects, solid)) and np.isfinite(net)
    complete = all(s['physical_boundary_complete'] for s in sides.values())
    solid_cellmax = float(np.max(np.abs(solid))) * Ta.size / scale
    equations_ok = bool(finite and complete and solid_cellmax <= .01
                        and all(s['residual_cellmax_rel'] <= .01 for s in sides.values()))
    return dict(
        units='W/m; kg/(s m)', state='raw final thermal return',
        boundary_order=['-x', '+x', '-y', '+y'], A=sides['A'], B=sides['B'],
        sou_A=True, sou_B=bool(sou_B), cell_count=int(Ta.size),
        dx_m=dx.tolist(), dy_m=dy.tolist(), area_m2=float(area.sum()),
        solid_boundary_W_per_m=0.0, solid_source_W_per_m=0.0,
        solid_residual_sum_W_per_m=solid_sum,
        solid_residual_max_abs_W_per_m=float(np.max(np.abs(solid))),
        solid_residual_cellmax_rel=solid_cellmax, equation_tolerance=.01,
        residual_sum_W_per_m=float(sum(r.sum() for r in residuals)+solid_sum),
        telescoping_error_W_per_m=float(sum(r.sum() for r in residuals)+solid_sum-net),
        net_boundary_in_W_per_m=net, D2_W_per_m=scale,
        energy_imbalance_rel=abs(net)/scale, solid_imbalance_rel=abs(solid_sum)/scale,
        physical_boundary_complete=complete, finite=bool(finite),
        energy_ok=bool(finite and complete and abs(net)/scale <= .005),
        solid_ok=bool(finite and complete and abs(solid_sum)/scale <= .01),
        equations_ok=equations_ok,
        passed=bool(equations_ok and abs(net)/scale <= .005 and abs(solid_sum)/scale <= .01))


def solve_full_domain(L, H, Nx, Ny,
                      T_inA, T_inB,
                      K_ffA, K_ffB, K_ss,
                      h_vA, h_vB,
                      rho_cp_fA, rho_cp_fB,
                      epsilon,
                      ucA, vcA, ucB, vcB,
                      dir_A, dir_B,
                      T_inA_profile=None, T_inB_profile=None,
                      max_iter=50000, tol=1e-6,
                      progress_cb=None, return_info=False,
                      Ta_init=None, Tb_init=None, Ts_init=None,
                      dx_arr=None, dy_arr=None,
                      inlet_mask_A=None, inlet_mask_B=None,
                      Tb_prescribed=None,
                      eps_A=None, eps_B=None,
                      q_rel_tol=None, conv_chunk=None,
                      use_sou_B=False, cancel_check=None,
                      inlet_flux_A=None, inlet_flux_B=None,
                      model_fluids=None, mass_flux_A=None, mass_flux_B=None,
                      accelerate=False):
    """Full-domain steady-state 2-fluid LTNE solver.

    q_rel_tol : float or None — per-chunk Q-relative convergence threshold.
                None (default) keeps the legacy `min(tol*2e-3, 1e-3)` (very
                tight, rarely fires → runs to max_iter). Callers that only need
                a converged field (e.g. the design sizing tool) can pass a
                looser, effective value (e.g. 1e-4) so the solve early-stops at
                true convergence instead of burning max_iter.
    conv_chunk : int or None — GS sweeps between convergence checks. None →
                legacy 500. A smaller value (e.g. 100) lets the early-stop
                trigger sooner. Default None preserves bitwise legacy behaviour.

    Parameters
    ----------
    K_ffA, K_ffB, K_ss : scalar or 2D array (Nx, Ny)
    h_vA, h_vB         : scalar or 2D array (Nx, Ny)
    epsilon             : scalar or 2D array (Nx, Ny)
    ucA, vcA : 2D arrays (Nx, Ny) — Fluid A cell-centre x/y velocity
    ucB, vcB : 2D arrays (Nx, Ny) — Fluid B cell-centre x/y velocity
    dir_A, dir_B : int — flow direction (0=+x, 1=-x, 2=+y, 3=-y)
    inlet_mask_A, inlet_mask_B : physical open-area fractions, not velocity taper.
    inlet_flux_A, inlet_flux_B : optional signed inward rho*cp*eps*u*A at the
        physical inlet, in W/(m K). Already area-integrated, never multiplied
        by the opening fraction again. Direct cell-centre callers omit these
        and retain their boundary-cell transport coefficient.
    return_info : bool — if True, return (Ta, Tb, Ts, info_dict)
    model_fluids : optional internal (fluid_A, fluid_B) air/water identifiers.
        Enables conservative model-h transport with both complete signed
        mass_flux_A/B face tuples, already integrated in kg/(s m). Both fluids
        use SOU and the same damping; use_sou_B controls temperature-form only.
    Ta_init, Tb_init, Ts_init : 2D arrays (Nx, Ny) — warm-start initial guess
    Tb_prescribed : 2D array (Nx, Ny) or None
        If provided, Tb is pinned to this field and NOT updated by the solver.
        Solid equation still couples via h_vB·(Tb − Ts). Use for validation
        cases where the water-side temperature is measured and should be
        imposed rather than solved.

    Returns
    -------
    Ta, Tb, Ts : 2D arrays (Nx, Ny)
    info : dict (only if return_info=True) — convergence metadata
    """
    Nx, Ny = int(Nx), int(Ny)
    # Non-uniform grid: use provided arrays or generate uniform
    if dx_arr is None:
        dx_arr = np.full(Nx, L / Nx, dtype=np.float64)
    else:
        dx_arr = np.ascontiguousarray(dx_arr, dtype=np.float64)
    if dy_arr is None:
        dy_arr = np.full(Ny, H / Ny, dtype=np.float64)
    else:
        dy_arr = np.ascontiguousarray(dy_arr, dtype=np.float64)

    # Promote scalars to uniform 2D arrays
    def _to_2d(val, Nx, Ny):
        if np.ndim(val) == 0:
            return np.full((Nx, Ny), float(val), dtype=np.float64)
        return np.ascontiguousarray(np.asarray(val, dtype=np.float64))

    K_ffA_arr = _to_2d(K_ffA, Nx, Ny)
    K_ffB_arr = _to_2d(K_ffB, Nx, Ny)
    K_ss_arr  = _to_2d(K_ss,  Nx, Ny)
    h_vA_arr  = _to_2d(h_vA,  Nx, Ny)
    h_vB_arr  = _to_2d(h_vB,  Nx, Ny)
    rho_cp_fA_arr = _to_2d(rho_cp_fA, Nx, Ny)
    rho_cp_fB_arr = _to_2d(rho_cp_fB, Nx, Ny)

    # Per-fluid void-fraction split. Default is symmetric 50/50
    # (ε_A = ε_B = ε/2) — matches symmetric bicontinuous sheet TPMS.
    #
    # **eps_A / eps_B kwargs are private hooks, NOT a public API** — they
    # carry distinct per-side void fractions ε_A, ε_B (offset-isosurface δ)
    # already split UPSTREAM in the pipeline so they sum to ε; the kernel
    # consumes them without re-halving (mirrors the 3D asym path). The UI /
    # optimizer never pass them and get the symmetric ε/2 split below.
    # The kernel takes eps_fA_arr / eps_fB_arr; the symmetric path passes the
    # SAME array object to both sides so δ=0 is bit-identical (golden gate).
    if eps_A is None and eps_B is None:
        if np.ndim(epsilon) == 0:
            eps_f_arr = np.full((Nx, Ny), 0.5 * float(epsilon), dtype=np.float64)
        else:
            eps_f_arr = np.ascontiguousarray(
                0.5 * np.asarray(epsilon, dtype=np.float64))
        eps_fA_arr = eps_f_arr
        eps_fB_arr = eps_f_arr   # same object → bit-identical to legacy
    else:
        if eps_A is None or eps_B is None:
            raise ValueError("eps_A and eps_B must be provided together.")
        eps_A_arr = _to_2d(eps_A, Nx, Ny)
        eps_B_arr = _to_2d(eps_B, Nx, Ny)
        eps_tot_arr = _to_2d(epsilon, Nx, Ny)
        # Two-sided (2026-07-13 audit): a sum BELOW ε is just as wrong as one
        # above it — accidentally pre-halved per-side values (the historical
        # double-halving bug class) used to sail through the one-sided check
        # with half the convective capacity.
        if np.any(np.abs(eps_A_arr + eps_B_arr - eps_tot_arr) > 1e-9):
            raise ValueError(
                "eps_A + eps_B must equal epsilon cell-wise (they partition "
                "the total void fraction). A sum above ε over-fills the void; "
                "a sum below it usually means the caller passed PRE-HALVED "
                "per-side values (double-halving bug class).")
        # Asymmetric ε_A ≠ ε_B is now routed per-side through the kernel: fluid
        # A's convection is weighted by ε_A, fluid B's by ε_B. A symmetric
        # explicit input (ε_A = ε_B = ε/2) reproduces the default path because
        # the two arrays carry the same values.
        eps_fA_arr = eps_A_arr
        eps_fB_arr = eps_B_arr

    # Inlet boundary codes
    bc_A = dir_A
    bc_B = dir_B

    # Build inlet profiles
    def _arr(profile, T_scalar, n):
        if profile is not None:
            a = np.asarray(profile, dtype=np.float64)
            if len(a) != n:
                a = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(a)), a)
            return a
        return np.full(n, T_scalar)

    nA = Ny if dir_A <= 1 else Nx
    nB = Ny if dir_B <= 1 else Nx
    T_inA_arr = _arr(T_inA_profile, T_inA, nA)
    T_inB_arr = _arr(T_inB_profile, T_inB, nB)

    # Physical open-area fractions (not a velocity taper).
    if inlet_mask_A is None:
        ifrac_A = np.ones(nA, dtype=np.float64)
    else:
        ifrac_A = np.ascontiguousarray(np.asarray(inlet_mask_A, dtype=np.float64))
    if inlet_mask_B is None:
        ifrac_B = np.ones(nB, dtype=np.float64)
    else:
        ifrac_B = np.ascontiguousarray(np.asarray(inlet_mask_B, dtype=np.float64))

    # Initialise (warm start if provided)
    if Ta_init is not None:
        Ta = np.ascontiguousarray(Ta_init.copy(), dtype=np.float64)
        Tb = np.ascontiguousarray(Tb_init.copy(), dtype=np.float64)
        Ts = np.ascontiguousarray(Ts_init.copy(), dtype=np.float64)
    else:
        # Per-fluid cold starts; every real fluid and solid cell is updated.
        Ta = np.full((Nx, Ny), float(T_inA))
        Tb = np.full((Nx, Ny), float(T_inB))
        Ts = np.full((Nx, Ny), 0.5 * (T_inA + T_inB))

    # C-1: if a prescribed Tb field is provided, pin Tb to it
    freeze_Tb = 0
    if Tb_prescribed is not None:
        Tb_arr = np.ascontiguousarray(np.asarray(Tb_prescribed, dtype=np.float64))
        if Tb_arr.shape != (Nx, Ny):
            raise ValueError(
                f"Tb_prescribed shape {Tb_arr.shape} != expected ({Nx}, {Ny})"
            )
        Tb = Tb_arr.copy()
        freeze_Tb = 1

    model_args = ()
    if model_fluids is not None:
        from sjtu_tpmshx.models.tpms_props import model_h_coefficients
        use_sou_B = True
        if len(model_fluids) != 2 or freeze_Tb:
            raise ValueError('model h requires two solved air/water fluids')
        cp_A, cp_B = (model_h_coefficients(f) for f in model_fluids)
        masses = []
        for mass in (mass_flux_A, mass_flux_B):
            if mass is None or len(mass) != 2:
                raise ValueError('model h requires complete x/y mass faces for both fluids')
            faces = tuple(np.ascontiguousarray(f, dtype=np.float64) for f in mass)
            if (faces[0].shape != (Nx+1, Ny) or faces[1].shape != (Nx, Ny+1)
                    or not all(np.all(np.isfinite(f)) for f in faces)):
                raise ValueError('model h mass faces must be finite and match the grid')
            masses.append(faces)
        mass_A, mass_B = masses
        last_Ta, last_Tb = Ta.copy(), Tb.copy()
        model_args = (mass_A, mass_B, cp_A, cp_B, last_Ta, last_Tb)
    elif mass_flux_A is not None or mass_flux_B is not None:
        raise ValueError('mass faces require explicit model_fluids')

    # Iterate in chunks. Convergence uses AND of three criteria (#6):
    #   (1) relative change in Q_B interface integral  < q_rel_tol
    #   (2) max|ΔTa|, max|ΔTb|, max|ΔTs| between chunks < T_rel_tol·|T|
    # Q-only could flag converged while T-fields were still drifting
    # (rho = P/(R·T) damps T swings at fixed Q). T-only is grid-dependent.
    chunk = 500 if conv_chunk is None else int(conv_chunk);  done = 0
    cell_area = dx_arr[:, None] * dy_arr[None, :]
    Q_prev = None
    Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()
    converged = False
    model_balance = None
    energy_checks = []
    q_tol = min(tol * 2e-3, 1e-3) if q_rel_tol is None else float(q_rel_tol)
    T_abs_tol = 0.01  # K between chunks
    # 2026-05-20 code-bug sweep (Tier 23): pre-init `chg` so the
    # `return_info` path (L551 `float(chg)`) cannot hit NameError when
    # the while loop never executes (max_iter <= 0). ltne_energy_3d.py
    # already guards this; mirror it here.
    chg = 0.0

    _use_rb = _RB_ENERGY_2D and (Nx * Ny > _RB_ENERGY_2D_GATE)
    _gs_fn = _gs_full_chunk_rb if _use_rb else _gs_full_chunk
    if accelerate and model_fluids is None:
        raise ValueError('energy acceleration requires model-h transport')

    def step(n):
        return _gs_fn(
            Ta, Tb, Ts, Nx, Ny, dx_arr, dy_arr,
            K_ffA_arr, K_ffB_arr, K_ss_arr,
            h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
            rho_cp_fA_arr, rho_cp_fB_arr,
            ucA, vcA, ucB, vcB,
            bc_A, bc_B, T_inA_arr, T_inB_arr,
            ifrac_A, ifrac_B,
            n, freeze_Tb, 1 if use_sou_B else 0, inlet_flux_A, inlet_flux_B,
            *model_args)

    def current_model_balance():
        return _model_h_balance(
            Ta, Tb, Ts, K_ffA_arr, K_ffB_arr, K_ss_arr, h_vA_arr, h_vB_arr,
            dx_arr, dy_arr, mass_A, mass_B, cp_A, cp_B, dir_A, dir_B,
            T_inA_arr, T_inB_arr, ifrac_A, ifrac_B, use_sou_B, last_Ta, last_Tb)

    while done < max_iter:
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        n = min(chunk, max_iter - done)
        if accelerate:
            from sjtu_tpmshx.solvers.anderson_acceleration import advance_energy
            chg = advance_energy(step, (Ta, Tb, Ts), n, (last_Ta, last_Tb),
                                 cancel_check=cancel_check)
        else:
            chg = step(n)
        model_balance = None
        done += n
        if progress_cb:
            progress_cb(done, max_iter)
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")

        Q_cur = float(np.sum(h_vB_arr * (Ts - Tb) * cell_area))
        dTa_max = float(np.max(np.abs(Ta - Ta_prev)))
        dTb_max = float(np.max(np.abs(Tb - Tb_prev)))
        dTs_max = float(np.max(np.abs(Ts - Ts_prev)))
        if _CONV_TRACE is not None:
            _rc = (abs(Q_cur - Q_prev) / max(abs(Q_cur), abs(Q_prev), 1.0)
                   if (Q_prev is not None) else float('nan'))
            _CONV_TRACE.append((done, _rc,
                                max(dTa_max, dTb_max, dTs_max),
                                float(np.mean(np.abs(Tb - Tb_prev))),
                                Q_cur))
        if Q_prev is not None:
            # One native W/m supplies an absolute scale near zero duty;
            # field stability remains an independent acceptance condition.
            rel_chg = abs(Q_cur - Q_prev) / max(abs(Q_cur), abs(Q_prev), 1.0)
            T_ok = (dTa_max < T_abs_tol and dTb_max < T_abs_tol
                    and dTs_max < T_abs_tol)
            if rel_chg < q_tol and T_ok:
                if model_fluids is not None:
                    model_balance = current_model_balance()
                    converged = model_balance['passed']
                    energy_checks.append(dict(
                        iterations=done, passed=converged,
                        equations_ok=model_balance['equations_ok']))
                    if not model_balance['physical_boundary_complete']:
                        break  # These fixed mass faces need another flow update.
                else:
                    converged = True
                if converged:
                    break
        Q_prev = Q_cur
        Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()

    if return_info:
        info = {
            'converged': converged,
            'iterations': done,
            'residual': float(chg),
        }
        if model_fluids is not None:
            info['model_h_balance'] = (model_balance if model_balance is not None
                                       else current_model_balance())
            info['energy_finishing_checks'] = energy_checks
            info['model_h_balance'].update(
                thermal_converged=bool(converged), thermal_iterations=int(done),
                thermal_residual_K=float(chg))
        return Ta, Tb, Ts, info
    return Ta, Tb, Ts
