"""3D LTNE numba kernels, moved verbatim from ltne_energy_3d.py (openspec
split-solver-kernels, 2026-07-03); bit-identical. Epsilon-split contract
untouched — see ltne_energy_3d.py / docs/architecture.md."""

import numpy as np
from numba import njit, prange
from ._kernels_2d import _model_h  # Shared explicit strict-math enthalpy policy.


# ---------------------------------------------------------------------------
# SOU limiter — three axes
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True, inline='always')
def _va_limit(gu, gd):
    """minmod slope limiter (signed). Returns 0 at extrema (gu*gd<=0), else
    the smaller-magnitude gradient with gu's sign. Factored into a helper
    (2026-05-22) so the SOU stencils read cleanly; behaviour is identical to
    the original inline minmod."""
    if gu * gd <= 0.0:
        return 0.0
    m = abs(gu) if abs(gu) < abs(gd) else abs(gd)
    return m if gu > 0.0 else -m


@njit(cache=True, fastmath=True)
def _sou_corr_x_3d(T, i, j, k, Nx, u_loc, Fx):
    if u_loc >= 0:
        phi_w = 0.0
        if i > 1:
            phi_w = _va_limit(T[i-1, j, k] - T[i-2, j, k],
                              T[i, j, k] - T[i-1, j, k])
        phi_e = 0.0
        if i < Nx - 1 and i > 0:
            phi_e = _va_limit(T[i, j, k] - T[i-1, j, k],
                              T[i+1, j, k] - T[i, j, k])
        return 0.5 * Fx * (phi_w - phi_e)
    else:
        phi_e = 0.0
        if i < Nx - 2:
            phi_e = _va_limit(T[i+1, j, k] - T[i+2, j, k],
                              T[i, j, k] - T[i+1, j, k])
        phi_w = 0.0
        if i > 0 and i < Nx - 1:
            phi_w = _va_limit(T[i, j, k] - T[i+1, j, k],
                              T[i-1, j, k] - T[i, j, k])
        return 0.5 * Fx * (phi_e - phi_w)


@njit(cache=True, fastmath=True)
def _sou_corr_y_3d(T, i, j, k, Ny, v_loc, Fy):
    if v_loc >= 0:
        phi_s = 0.0
        if j > 1:
            phi_s = _va_limit(T[i, j-1, k] - T[i, j-2, k],
                              T[i, j, k] - T[i, j-1, k])
        phi_n = 0.0
        if j < Ny - 1 and j > 0:
            phi_n = _va_limit(T[i, j, k] - T[i, j-1, k],
                              T[i, j+1, k] - T[i, j, k])
        return 0.5 * Fy * (phi_s - phi_n)
    else:
        phi_n = 0.0
        if j < Ny - 2:
            phi_n = _va_limit(T[i, j+1, k] - T[i, j+2, k],
                              T[i, j, k] - T[i, j+1, k])
        phi_s = 0.0
        if j > 0 and j < Ny - 1:
            phi_s = _va_limit(T[i, j, k] - T[i, j+1, k],
                              T[i, j-1, k] - T[i, j, k])
        return 0.5 * Fy * (phi_n - phi_s)


@njit(cache=True, fastmath=True)
def _sou_corr_z_3d(T, i, j, k, Nz, w_loc, Fz):
    if w_loc >= 0:
        phi_b = 0.0
        if k > 1:
            phi_b = _va_limit(T[i, j, k-1] - T[i, j, k-2],
                              T[i, j, k] - T[i, j, k-1])
        phi_t = 0.0
        if k < Nz - 1 and k > 0:
            phi_t = _va_limit(T[i, j, k] - T[i, j, k-1],
                              T[i, j, k+1] - T[i, j, k])
        return 0.5 * Fz * (phi_b - phi_t)
    else:
        phi_t = 0.0
        if k < Nz - 2:
            phi_t = _va_limit(T[i, j, k+1] - T[i, j, k+2],
                              T[i, j, k] - T[i, j, k+1])
        phi_b = 0.0
        if k > 0 and k < Nz - 1:
            phi_b = _va_limit(T[i, j, k] - T[i, j, k+1],
                              T[i, j, k-1] - T[i, j, k])
        return 0.5 * Fz * (phi_t - phi_b)


# ---------------------------------------------------------------------------
# Conservative (telescoping) SOU deferred correction — face-shared.
#
# Unlike _sou_corr_*_3d (cell-local: each cell uses its own |u_c| magnitude, so
# the correction at a shared face differs between the two adjacent cells and
# breaks conservation), these use the SIGNED shared face flux to pick the
# upwind side. The HO increment (T_HO_face − T_up_face) = 0.5·minmod(...) is a
# pure function of the face + neighbour T values, identical from both cells'
# view, so the deferred source Σ_faces ∓F_face·inc telescopes ⇒ strictly
# conservative AND 2nd-order. Source convention matches the kernel:
#   sou = −Σ_faces F_face·(T_HO−T_up)·(outward sign)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _sou_face_x_cons(T, i, j, k, Nx, Fw, Fe):
    inc_e = 0.0
    if Fe >= 0.0:                      # east face upwind = cell i
        if 0 < i < Nx - 1:
            inc_e = 0.5 * _va_limit(T[i, j, k] - T[i-1, j, k],
                                    T[i+1, j, k] - T[i, j, k])
    else:                              # east face upwind = cell i+1
        if i < Nx - 2:
            inc_e = 0.5 * _va_limit(T[i+1, j, k] - T[i+2, j, k],
                                    T[i, j, k] - T[i+1, j, k])
    inc_w = 0.0
    if Fw >= 0.0:                      # west face upwind = cell i-1
        if i > 1:
            inc_w = 0.5 * _va_limit(T[i-1, j, k] - T[i-2, j, k],
                                    T[i, j, k] - T[i-1, j, k])
    else:                              # west face upwind = cell i
        if 0 < i < Nx - 1:
            inc_w = 0.5 * _va_limit(T[i, j, k] - T[i+1, j, k],
                                    T[i-1, j, k] - T[i, j, k])
    return -Fe * inc_e + Fw * inc_w


@njit(cache=True, fastmath=True)
def _sou_face_y_cons(T, i, j, k, Ny, Fs, Fn):
    inc_n = 0.0
    if Fn >= 0.0:
        if 0 < j < Ny - 1:
            inc_n = 0.5 * _va_limit(T[i, j, k] - T[i, j-1, k],
                                    T[i, j+1, k] - T[i, j, k])
    else:
        if j < Ny - 2:
            inc_n = 0.5 * _va_limit(T[i, j+1, k] - T[i, j+2, k],
                                    T[i, j, k] - T[i, j+1, k])
    inc_s = 0.0
    if Fs >= 0.0:
        if j > 1:
            inc_s = 0.5 * _va_limit(T[i, j-1, k] - T[i, j-2, k],
                                    T[i, j, k] - T[i, j-1, k])
    else:
        if 0 < j < Ny - 1:
            inc_s = 0.5 * _va_limit(T[i, j, k] - T[i, j+1, k],
                                    T[i, j-1, k] - T[i, j, k])
    return -Fn * inc_n + Fs * inc_s


@njit(cache=True, fastmath=True)
def _sou_face_z_cons(T, i, j, k, Nz, Fb, Ft):
    inc_t = 0.0
    if Ft >= 0.0:
        if 0 < k < Nz - 1:
            inc_t = 0.5 * _va_limit(T[i, j, k] - T[i, j, k-1],
                                    T[i, j, k+1] - T[i, j, k])
    else:
        if k < Nz - 2:
            inc_t = 0.5 * _va_limit(T[i, j, k+1] - T[i, j, k+2],
                                    T[i, j, k] - T[i, j, k+1])
    inc_b = 0.0
    if Fb >= 0.0:
        if k > 1:
            inc_b = 0.5 * _va_limit(T[i, j, k-1] - T[i, j, k-2],
                                    T[i, j, k] - T[i, j, k-1])
    else:
        if 0 < k < Nz - 1:
            inc_b = 0.5 * _va_limit(T[i, j, k] - T[i, j, k+1],
                                    T[i, j, k-1] - T[i, j, k])
    return -Ft * inc_t + Fb * inc_b


@njit(cache=True, fastmath=True)
def _sou_field_cons(T, Fx, Fy, Fz):
    """Per-cell face-shared SOU deferred-correction field, using the SAME
    helpers as the conservative kernel. Lets the strict-conservation metric
    subtract the exact deferred source so the certificate stays valid with HO
    active (converged: r_FO = sou ⇒ true residual r_FO − sou → 0)."""
    Nx, Ny, Nz = T.shape
    sou = np.zeros_like(T)
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                sou[i, j, k] = (
                    _sou_face_x_cons(T, i, j, k, Nx, Fx[i, j, k], Fx[i+1, j, k])
                    + _sou_face_y_cons(T, i, j, k, Ny, Fy[i, j, k], Fy[i, j+1, k])
                    + _sou_face_z_cons(T, i, j, k, Nz, Fz[i, j, k], Fz[i, j, k+1]))
    return sou


# ---------------------------------------------------------------------------
# inlet helpers
# ---------------------------------------------------------------------------

@njit(cache=True)
def _model_h_faces(T, mass, coefficients, direction, Tin, ifrac):
    """Shared Picard faces: flux = capacity*T_up + deferred.

    Freeze once per sweep, including both RB colours. Retain the temperature
    minmod stencil and its edge exclusions, integrating cp at its face T.
    Boundary backflow outside the inlet retains numerical self-extrapolation;
    the ledger must identify that missing physical inflow state.
    """
    a, b, c, origin, _ = coefficients
    capacity = (np.empty_like(mass[0]), np.empty_like(mass[1]), np.empty_like(mass[2]))
    deferred = (np.empty_like(mass[0]), np.empty_like(mass[1]), np.empty_like(mass[2]))
    for axis in range(3):
        for i in range(mass[axis].shape[0]):
            for j in range(mass[axis].shape[1]):
                for k in range(mass[axis].shape[2]):
                    face = (i, j, k)
                    pos = face[axis]
                    count = T.shape[axis]
                    m = mass[axis][face]
                    u = pos - 1 if m >= 0.0 else pos
                    u = min(max(u, 0), count - 1)
                    up = (u, j, k) if axis == 0 else ((i, u, k) if axis == 1 else (i, j, u))
                    t = T[up]
                    inc = 0.0
                    if 0 < pos < count and 0 < u < count - 1:
                        prev = (u-1, j, k) if axis == 0 else ((i, u-1, k) if axis == 1 else (i, j, u-1))
                        nxt = (u+1, j, k) if axis == 0 else ((i, u+1, k) if axis == 1 else (i, j, u+1))
                        if m >= 0.0:
                            inc = 0.5 * _va_limit(t-T[prev], T[nxt]-t)
                        else:
                            inc = 0.5 * _va_limit(t-T[nxt], T[prev]-t)
                    if axis == direction // 2 and pos == (0 if direction % 2 == 0 else count):
                        patch = (j, k) if axis == 0 else ((i, k) if axis == 1 else (i, j))
                        inward = m if direction % 2 == 0 else -m
                        if ifrac[patch] > 0.0 and inward > 0.0:
                            t = Tin[patch]
                    x = t - origin
                    cp = a + b*x + c*x*x
                    capacity[axis][face] = m * cp
                    deferred[axis][face] = m * (_model_h(t+inc, coefficients) - cp*t)
    return capacity, deferred


@njit(cache=True)
def _face_divergence(faces):
    return (faces[0][1:] - faces[0][:-1]
            + faces[1][:, 1:] - faces[1][:, :-1]
            + faces[2][:, :, 1:] - faces[2][:, :, :-1])

@njit(cache=True, fastmath=True, inline='always')
def _is_inlet(dir_code, i, j, k, Nx, Ny, Nz):
    if dir_code == 0: return i == 0
    if dir_code == 1: return i == Nx - 1
    if dir_code == 2: return j == 0
    if dir_code == 3: return j == Ny - 1
    if dir_code == 4: return k == 0
    return k == Nz - 1


@njit(cache=True, fastmath=True, inline='always')
def _inlet_frac(ifrac2d, dir_code, i, j, k):
    # ifrac2d shape depends on dir: (Ny, Nz) / (Nx, Nz) / (Nx, Ny)
    if dir_code <= 1:
        return ifrac2d[j, k]
    if dir_code <= 3:
        return ifrac2d[i, k]
    return ifrac2d[i, j]


@njit(cache=True, fastmath=True, inline='always')
def _inlet_val(Tin2d, dir_code, i, j, k):
    if dir_code <= 1:
        return Tin2d[j, k]
    if dir_code <= 3:
        return Tin2d[i, k]
    return Tin2d[i, j]


@njit(cache=True, fastmath=True, inline='always')
def _inlet_face_terms(dir_code, i, j, k, Nx, Ny, Nz, ifrac, Tin,
                      K, dx, dy, dz, aE, aW, aN, aS, aT, aB,
                      tE, tW, tN, tS, tT, tB, inlet_flux=None):
    """Physical Tin face, with half-CV diffusion; transport is already in a*.

    K includes its existing porosity factor. SIMPLE face velocities already
    include opening area, so only diffusion receives the raw opening fraction.
    Other external faces keep zero diffusion and their cell temperature.
    """
    if _is_inlet(dir_code, i, j, k, Nx, Ny, Nz):
        f = _inlet_frac(ifrac, dir_code, i, j, k)
        if f > 0.0:
            tin = _inlet_val(Tin, dir_code, i, j, k)
            if inlet_flux is not None:
                incoming = max(_inlet_val(inlet_flux, dir_code, i, j, k), 0.0)
                if dir_code == 0: aW = incoming
                elif dir_code == 1: aE = incoming
                elif dir_code == 2: aS = incoming
                elif dir_code == 3: aN = incoming
                elif dir_code == 4: aB = incoming
                else: aT = incoming
            if dir_code == 0:
                aW += 2.0*K*dy*dz*f/dx; tW = tin
            elif dir_code == 1:
                aE += 2.0*K*dy*dz*f/dx; tE = tin
            elif dir_code == 2:
                aS += 2.0*K*dx*dz*f/dy; tS = tin
            elif dir_code == 3:
                aN += 2.0*K*dx*dz*f/dy; tN = tin
            elif dir_code == 4:
                aB += 2.0*K*dx*dy*f/dz; tB = tin
            else:
                aT += 2.0*K*dx*dy*f/dz; tT = tin
    return aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB


@njit(cache=True, fastmath=True, inline='always')
def _inlet_capacity_faces(direction, i, j, k, Nx, Ny, Nz, ifrac, inlet_flux,
                          Fe, Fw, Fn, Fs, Ft, Fb):
    """Replace only the physical inlet F before coefficients and net_out."""
    if inlet_flux is not None and _is_inlet(direction, i, j, k, Nx, Ny, Nz):
        if _inlet_frac(ifrac, direction, i, j, k) > 0.0:
            incoming = _inlet_val(inlet_flux, direction, i, j, k)
            if direction == 0: Fw = incoming
            elif direction == 1: Fe = -incoming
            elif direction == 2: Fs = incoming
            elif direction == 3: Fn = -incoming
            elif direction == 4: Fb = incoming
            else: Ft = -incoming
    return Fe, Fw, Fn, Fs, Ft, Fb


# ---------------------------------------------------------------------------
# Gauss-Seidel chunk — STAGGERED face-velocity version (2026-04-25 FV#6)
#
# Uses staggered velocities with shared internal capacity coefficients.
# Explicit physical inlet capacity replaces only its boundary F; net_out
# includes that replacement and need not vanish under the old projection.
#
# Face velocity arrays:
#   uf : (Nx+1, Ny, Nz) — u at x-faces (signed along +x)
#   vf : (Nx, Ny+1, Nz) — v at y-faces (signed along +y)
#   wf : (Nx, Ny, Nz+1) — w at z-faces (signed along +z)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _gs_full_chunk_3d_stag(Ta, Tb, Ts, Nx, Ny, Nz,
                            dx_arr, dy_arr, dz_arr,
                            K_ffA_arr, K_ffB_arr, K_ss_arr,
                            h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                            rho_cp_fA, rho_cp_fB,
                            ufA, vfA, wfA, ufB, vfB, wfB,
                            bc_A, bc_B, T_inA_arr, T_inB_arr,
                            ifrac_A, ifrac_B,
                            n_iters, freeze_Tb,
                            alpha_fA, alpha_s, alpha_fB,
                            mms_S_A_arr, mms_S_B_arr, mms_S_s_arr,
                            conservative, inlet_flux_A=None, inlet_flux_B=None,
                            model_mass_A=None, model_mass_B=None,
                            model_cp_A=None, model_cp_B=None):
    max_chg = 0.0

    if bc_A == 1:
        i0, i1, di = Nx - 1, -1, -1
    else:
        i0, i1, di = 0, Nx, 1
    if bc_B == 3:
        j0, j1, dj = Ny - 1, -1, -1
    else:
        j0, j1, dj = 0, Ny, 1
    if bc_A == 5:
        k0, k1, dk = Nz - 1, -1, -1
    else:
        k0, k1, dk = 0, Nz, 1

    for _it in range(n_iters):
        model_FA = (ufA, vfA, wfA)
        model_FB = (ufB, vfB, wfB)
        model_source_A = Ta
        model_source_B = Tb
        if model_mass_A is not None:
            model_FA, deferred_A = _model_h_faces(
                Ta, model_mass_A, model_cp_A, bc_A, T_inA_arr, ifrac_A)
            model_FB, deferred_B = _model_h_faces(
                Tb, model_mass_B, model_cp_B, bc_B, T_inB_arr, ifrac_B)
            model_source_A = -_face_divergence(deferred_A)
            model_source_B = -_face_divergence(deferred_B)
        max_chg = 0.0
        for i in range(i0, i1, di):
            for j in range(j0, j1, dj):
                for k in range(k0, k1, dk):

                    # ── Fluid A ──
                    dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                    vol = dxi * dyj * dzk
                    Kc = K_ffA_arr[i, j, k]
                    hvA = h_vA_arr[i, j, k] * vol

                    Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                    # Face spacing δx_e = 0.5(dx_P+dx_E) for conservative
                    # diffusion stencil (#3D-7 fix). Same value used by both
                    # adjacent cells; old /dxi broke symmetry on non-uniform.
                    dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxe if i < Nx-1 else 0.0
                    dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxw if i > 0 else 0.0
                    dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyn if j < Ny-1 else 0.0
                    dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dys if j > 0 else 0.0
                    dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzt if k < Nz-1 else 0.0
                    dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzb if k > 0 else 0.0

                    # Face-centered staggered velocities (directly from SIMPLE).
                    # u_face_x at (i, i+1), v_face_y at (j, j+1), w_face_z at (k, k+1).
                    u_e = ufA[i+1, j, k]
                    u_w = ufA[i, j, k]
                    v_n = vfA[i, j+1, k]
                    v_s = vfA[i, j, k]
                    w_t = wfA[i, j, k+1]
                    w_b = wfA[i, j, k]

                    # ρcp and eps_f at faces — arithmetic mean of cell values.
                    rcpA_c = rho_cp_fA[i,j,k]; ef_c = eps_fA_arr[i,j,k]
                    rcp_e = 0.5*(rcpA_c + rho_cp_fA[i+1,j,k]) if i < Nx-1 else rcpA_c
                    rcp_w = 0.5*(rho_cp_fA[i-1,j,k] + rcpA_c) if i > 0 else rcpA_c
                    rcp_n = 0.5*(rcpA_c + rho_cp_fA[i,j+1,k]) if j < Ny-1 else rcpA_c
                    rcp_s = 0.5*(rho_cp_fA[i,j-1,k] + rcpA_c) if j > 0 else rcpA_c
                    rcp_t = 0.5*(rcpA_c + rho_cp_fA[i,j,k+1]) if k < Nz-1 else rcpA_c
                    rcp_b = 0.5*(rho_cp_fA[i,j,k-1] + rcpA_c) if k > 0 else rcpA_c
                    ef_e = 0.5*(ef_c + eps_fA_arr[i+1,j,k]) if i < Nx-1 else ef_c
                    ef_w = 0.5*(eps_fA_arr[i-1,j,k] + ef_c) if i > 0 else ef_c
                    ef_n = 0.5*(ef_c + eps_fA_arr[i,j+1,k]) if j < Ny-1 else ef_c
                    ef_s = 0.5*(eps_fA_arr[i,j-1,k] + ef_c) if j > 0 else ef_c
                    ef_t = 0.5*(ef_c + eps_fA_arr[i,j,k+1]) if k < Nz-1 else ef_c
                    ef_b = 0.5*(eps_fA_arr[i,j,k-1] + ef_c) if k > 0 else ef_c

                    # Signed face mass-flux (+axis direction)
                    F_e = ef_e * rcp_e * u_e * Ax
                    F_w = ef_w * rcp_w * u_w * Ax
                    F_n = ef_n * rcp_n * v_n * Ay
                    F_s = ef_s * rcp_s * v_s * Ay
                    F_t = ef_t * rcp_t * w_t * Az
                    F_b = ef_b * rcp_b * w_b * Az

                    F_e, F_w, F_n, F_s, F_t, F_b = _inlet_capacity_faces(
                        bc_A, i, j, k, Nx, Ny, Nz, ifrac_A, inlet_flux_A,
                        F_e, F_w, F_n, F_s, F_t, F_b)
                    if model_mass_A is not None:
                        F_e = model_FA[0][i+1, j, k]
                        F_w = model_FA[0][i, j, k]
                        F_n = model_FA[1][i, j+1, k]
                        F_s = model_FA[1][i, j, k]
                        F_t = model_FA[2][i, j, k+1]
                        F_b = model_FA[2][i, j, k]

                    # Patankar hybrid upwind on signed face flux
                    aE = dE + max(-F_e, 0.0)
                    aW = dW + max( F_w, 0.0)
                    aN = dN + max(-F_n, 0.0)
                    aS = dS + max( F_s, 0.0)
                    aT = dT_ + max(-F_t, 0.0)
                    aB = dB + max( F_b, 0.0)

                    tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                    tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                    tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                    tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                    tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                    tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                    (aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB) = _inlet_face_terms(
                        bc_A, i, j, k, Nx, Ny, Nz, ifrac_A, T_inA_arr,
                        Kc, dxi, dyj, dzk, aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB)

                    if conservative == 1:
                        # Strict-conservation (B-plan B2): the SIMPLE
                        # staggered face flux is the SAME value for the two
                        # cells sharing a face (F_e of cell i ≡ F_w of cell
                        # i+1), so advection telescopes. Adding the signed
                        # net-mass-out term to aP completes the Patankar
                        # conservative form — summing the discrete per-cell
                        # balance over the domain then collapses to
                        # ∮F·n dA = ∫S dV (machine-accurate, see 1D PoC).
                        # HO accuracy via face-SHARED SOU deferred
                        # correction (B-plan B4): the increment uses the
                        # signed shared face flux to pick the upwind side,
                        # so it telescopes ⇒ conservation preserved AND
                        # 2nd-order. (cell-local _sou_corr_* would break it.)
                        sou = (_sou_face_x_cons(Ta, i, j, k, Nx, F_w, F_e)
                               + _sou_face_y_cons(Ta, i, j, k, Ny, F_s, F_n)
                               + _sou_face_z_cons(Ta, i, j, k, Nz, F_b, F_t))
                        if model_mass_A is not None:
                            sou = model_source_A[i, j, k]
                        net_out = (F_e - F_w) + (F_n - F_s) + (F_t - F_b)
                        aP = aE + aW + aN + aS + aT + aB + net_out + hvA
                    else:
                        # SOU deferred correction with cell-center velocity
                        u_c_sou = 0.5*(u_e + u_w)
                        v_c_sou = 0.5*(v_n + v_s)
                        w_c_sou = 0.5*(w_t + w_b)
                        Fx_mag = ef_c * rcpA_c * abs(u_c_sou) * Ax
                        Fy_mag = ef_c * rcpA_c * abs(v_c_sou) * Ay
                        Fz_mag = ef_c * rcpA_c * abs(w_c_sou) * Az
                        sou = (_sou_corr_x_3d(Ta, i, j, k, Nx, u_c_sou, Fx_mag)
                               + _sou_corr_y_3d(Ta, i, j, k, Ny, v_c_sou, Fy_mag)
                               + _sou_corr_z_3d(Ta, i, j, k, Nz, w_c_sou, Fz_mag))
                        # aP = Σa_nb + hvA. NET_OUT (mass-imbal) tried in
                        # multiple variants (full, interior-only, BC pin
                        # penalty, source split): all destabilise because BC
                        # face flux ≠ adjacent interior face flux when SIMPLE
                        # has any per-cell residual. cell-local stable + 13-22%
                        # AB imbal accepted as discretisation limit.
                        aP = aE + aW + aN + aS + aT + aB + hvA
                    if aP < 1e-30:
                        aP = 1e-30
                    # MMS source injection (volume-integrated, units W).
                    # Default zero-array → production no-op.
                    S_A_cell = mms_S_A_arr[i, j, k] * vol
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + aT*tT + aB*tB
                           + hvA * Ts[i, j, k] + sou + S_A_cell) / aP
                    old = Ta[i, j, k]
                    upd = old + alpha_fA * (new - old)
                    chg = abs(upd - old)
                    if chg > max_chg: max_chg = chg
                    Ta[i, j, k] = upd

                    # ── Solid ──
                    dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                    vol_s = dxi * dyj * dzk
                    Ks = K_ss_arr[i, j, k]
                    hvA_s = h_vA_arr[i, j, k] * vol_s
                    hvB_s = h_vB_arr[i, j, k] * vol_s

                    Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                    # Face spacing for solid (stag) — same as A
                    dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt_s = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb_s = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxe_s if i < Nx-1 else Ks*Ax/dxi
                    Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxw_s if i > 0    else Ks*Ax/dxi
                    Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyn_s if j < Ny-1 else Ks*Ay/dyj
                    Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dys_s if j > 0    else Ks*Ay/dyj
                    Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzt_s if k < Nz-1 else Ks*Az/dzk
                    Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzb_s if k > 0    else Ks*Az/dzk

                    sE = Ts[i+1, j, k] if i < Nx-1 else Ts[i, j, k]
                    sW = Ts[i-1, j, k] if i > 0    else Ts[i, j, k]
                    sN = Ts[i, j+1, k] if j < Ny-1 else Ts[i, j, k]
                    sS = Ts[i, j-1, k] if j > 0    else Ts[i, j, k]
                    sT = Ts[i, j, k+1] if k < Nz-1 else Ts[i, j, k]
                    sB = Ts[i, j, k-1] if k > 0    else Ts[i, j, k]

                    aP_s = De + Dw + Dn + Ds + Dt + Db + hvA_s + hvB_s
                    # MMS source for solid (vol-integrated, [W]).
                    S_s_cell = mms_S_s_arr[i, j, k] * vol_s
                    new_s = (De*sE + Dw*sW + Dn*sN + Ds*sS + Dt*sT + Db*sB
                             + hvA_s*Ta[i, j, k] + hvB_s*Tb[i, j, k]
                             + S_s_cell) / aP_s
                    old_s = Ts[i, j, k]
                    upd_s = old_s + alpha_s * (new_s - old_s)
                    chg = abs(upd_s - old_s)
                    if chg > max_chg: max_chg = chg
                    Ts[i, j, k] = upd_s

                    # ── Fluid B ── (stag kernel)
                    if freeze_Tb == 0:
                        vol_b = dxi * dyj * dzk
                        Kc_b = K_ffB_arr[i, j, k]
                        hvB = h_vB_arr[i, j, k] * vol_b

                        # Face spacing for B (stag) — same as A
                        dxe_b = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw_b = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn_b = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys_b = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dzt_b = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                        dzb_b = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                        dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxe_b if i < Nx-1 else 0.0
                        dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxw_b if i > 0 else 0.0
                        dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyn_b if j < Ny-1 else 0.0
                        dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dys_b if j > 0 else 0.0
                        dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzt_b if k < Nz-1 else 0.0
                        dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzb_b if k > 0 else 0.0

                        uB_e = ufB[i+1, j, k]
                        uB_w = ufB[i, j, k]
                        vB_n = vfB[i, j+1, k]
                        vB_s = vfB[i, j, k]
                        wB_t = wfB[i, j, k+1]
                        wB_b = wfB[i, j, k]

                        rcpB_c = rho_cp_fB[i,j,k]; efB_c = eps_fB_arr[i,j,k]
                        rcpB_e = 0.5*(rcpB_c + rho_cp_fB[i+1,j,k]) if i < Nx-1 else rcpB_c
                        rcpB_w = 0.5*(rho_cp_fB[i-1,j,k] + rcpB_c) if i > 0 else rcpB_c
                        rcpB_n = 0.5*(rcpB_c + rho_cp_fB[i,j+1,k]) if j < Ny-1 else rcpB_c
                        rcpB_s = 0.5*(rho_cp_fB[i,j-1,k] + rcpB_c) if j > 0 else rcpB_c
                        rcpB_t = 0.5*(rcpB_c + rho_cp_fB[i,j,k+1]) if k < Nz-1 else rcpB_c
                        rcpB_b = 0.5*(rho_cp_fB[i,j,k-1] + rcpB_c) if k > 0 else rcpB_c
                        efB_e = 0.5*(efB_c + eps_fB_arr[i+1,j,k]) if i < Nx-1 else efB_c
                        efB_w = 0.5*(eps_fB_arr[i-1,j,k] + efB_c) if i > 0 else efB_c
                        efB_n = 0.5*(efB_c + eps_fB_arr[i,j+1,k]) if j < Ny-1 else efB_c
                        efB_s = 0.5*(eps_fB_arr[i,j-1,k] + efB_c) if j > 0 else efB_c
                        efB_t = 0.5*(efB_c + eps_fB_arr[i,j,k+1]) if k < Nz-1 else efB_c
                        efB_b = 0.5*(eps_fB_arr[i,j,k-1] + efB_c) if k > 0 else efB_c

                        FB_e = efB_e * rcpB_e * uB_e * Ax
                        FB_w = efB_w * rcpB_w * uB_w * Ax
                        FB_n = efB_n * rcpB_n * vB_n * Ay
                        FB_s = efB_s * rcpB_s * vB_s * Ay
                        FB_t = efB_t * rcpB_t * wB_t * Az
                        FB_b = efB_b * rcpB_b * wB_b * Az

                        FB_e, FB_w, FB_n, FB_s, FB_t, FB_b = _inlet_capacity_faces(
                            bc_B, i, j, k, Nx, Ny, Nz, ifrac_B, inlet_flux_B,
                            FB_e, FB_w, FB_n, FB_s, FB_t, FB_b)
                        if model_mass_A is not None:
                            FB_e = model_FB[0][i+1, j, k]
                            FB_w = model_FB[0][i, j, k]
                            FB_n = model_FB[1][i, j+1, k]
                            FB_s = model_FB[1][i, j, k]
                            FB_t = model_FB[2][i, j, k+1]
                            FB_b = model_FB[2][i, j, k]

                        aEb = dEb  + max(-FB_e, 0.0)
                        aWb = dWb  + max( FB_w, 0.0)
                        aNb = dNb  + max(-FB_n, 0.0)
                        aSb = dSb  + max( FB_s, 0.0)
                        aTb = dTb_ + max(-FB_t, 0.0)
                        aBb = dBb  + max( FB_b, 0.0)

                        tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                        tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                        tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                        tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                        tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                        tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]

                        (aEb, aWb, aNb, aSb, aTb, aBb, tEb, tWb, tNb, tSb, tTb, tBb) = _inlet_face_terms(
                            bc_B, i, j, k, Nx, Ny, Nz, ifrac_B, T_inB_arr,
                            Kc_b, dxi, dyj, dzk, aEb, aWb, aNb, aSb, aTb, aBb, tEb, tWb, tNb, tSb, tTb, tBb)

                        if conservative == 1:
                            # Strict-conservation B side (mirror of A):
                            # face-shared SOU deferred correction (HO + telescoping).
                            soub = (_sou_face_x_cons(Tb, i, j, k, Nx, FB_w, FB_e)
                                    + _sou_face_y_cons(Tb, i, j, k, Ny, FB_s, FB_n)
                                    + _sou_face_z_cons(Tb, i, j, k, Nz, FB_b, FB_t))
                            if model_mass_A is not None:
                                soub = model_source_B[i, j, k]
                            net_outB = ((FB_e - FB_w) + (FB_n - FB_s)
                                        + (FB_t - FB_b))
                            aPb = (aEb + aWb + aNb + aSb + aTb + aBb
                                   + net_outB + hvB)
                        else:
                            uBc_sou = 0.5*(uB_e + uB_w)
                            vBc_sou = 0.5*(vB_n + vB_s)
                            wBc_sou = 0.5*(wB_t + wB_b)
                            FxB_mag = efB_c * rcpB_c * abs(uBc_sou) * Ax
                            FyB_mag = efB_c * rcpB_c * abs(vBc_sou) * Ay
                            FzB_mag = efB_c * rcpB_c * abs(wBc_sou) * Az
                            soub = (_sou_corr_x_3d(Tb, i, j, k, Nx, uBc_sou, FxB_mag)
                                    + _sou_corr_y_3d(Tb, i, j, k, Ny, vBc_sou, FyB_mag)
                                    + _sou_corr_z_3d(Tb, i, j, k, Nz, wBc_sou, FzB_mag))
                            aPb = aEb + aWb + aNb + aSb + aTb + aBb + hvB
                        if aPb < 1e-30:
                            aPb = 1e-30
                        # MMS source for B (vol-integrated, [W]).
                        S_B_cell = mms_S_B_arr[i, j, k] * vol_b
                        new_b = (aEb*tEb + aWb*tWb + aNb*tNb + aSb*tSb
                                 + aTb*tTb + aBb*tBb + hvB*Ts[i, j, k]
                                 + soub + S_B_cell) / aPb
                        old_b = Tb[i, j, k]
                        upd_b = old_b + alpha_fB * (new_b - old_b)
                        chg = abs(upd_b - old_b)
                        if chg > max_chg: max_chg = chg
                        Tb[i, j, k] = upd_b


        if max_chg < 1e-10:
            break
    return max_chg


@njit(cache=True, fastmath=True, parallel=True)
def _gs_full_chunk_3d_stag_rb(Ta, Tb, Ts, Nx, Ny, Nz,
                               dx_arr, dy_arr, dz_arr,
                               K_ffA_arr, K_ffB_arr, K_ss_arr,
                               h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                               rho_cp_fA, rho_cp_fB,
                               ufA, vfA, wfA, ufB, vfB, wfB,
                               bc_A, bc_B, T_inA_arr, T_inB_arr,
                               ifrac_A, ifrac_B,
                               n_iters, freeze_Tb,
                               alpha_fA, alpha_s, alpha_fB,
                               mms_S_A_arr, mms_S_B_arr, mms_S_s_arr,
                               conservative, inlet_flux_A=None, inlet_flux_B=None,
                            model_mass_A=None, model_mass_B=None,
                            model_cp_A=None, model_cp_B=None):
    """Red-black parallel twin of `_gs_full_chunk_3d_stag`.

    Two race-free changes vs the serial kernel make it `prange`-parallelisable:
      1. Cells are swept by checkerboard colour (i+j+k parity). Within a colour
         pass every cell's 7-point neighbours are the OTHER colour (frozen this
         pass), so same-colour cells update independently — no GS read/write race.
      2. The SOU deferred correction reaches 2 cells away (same colour), so it is
         read from a START-OF-SWEEP SNAPSHOT (`Ta_snap`/`Tb_snap`) instead of the
         live field. SOU is a deferred (lagged) correction and the advection
         face fluxes are T-independent, so this changes only the iteration path,
         not the converged fixpoint — Q/dP and the conservation certificate match
         the serial kernel at convergence.

    The per-cell update math is otherwise identical to the serial kernel.
    Parity note: a z-reflection flips colour when Nz is even, so the colour
    SWEEP order is not reflection-symmetric — but neither is the serial
    lexicographic order, and both converge to the same (symmetric) linear-system
    solution, so a converged z-symmetric case stays z-symmetric (verified).
    """
    max_chg = 0.0
    ncell = Nx * Ny * Nz
    nyz = Ny * Nz
    for _it in range(n_iters):
        model_FA = (ufA, vfA, wfA)
        model_FB = (ufB, vfB, wfB)
        model_source_A = Ta
        model_source_B = Tb
        if model_mass_A is not None:
            model_FA, deferred_A = _model_h_faces(
                Ta, model_mass_A, model_cp_A, bc_A, T_inA_arr, ifrac_A)
            model_FB, deferred_B = _model_h_faces(
                Tb, model_mass_B, model_cp_B, bc_B, T_inB_arr, ifrac_B)
            model_source_A = -_face_divergence(deferred_A)
            model_source_B = -_face_divergence(deferred_B)
        # Start-of-sweep snapshot for the (2-away, same-colour) deferred SOU.
        Ta_snap = Ta.copy()
        Tb_snap = Tb.copy()
        sweep_chg = 0.0
        for color in range(2):
            color_chg = 0.0
            for idx in prange(ncell):
                i = idx // nyz
                rem = idx - i * nyz
                j = rem // Nz
                k = rem - j * Nz
                if ((i + j + k) & 1) != color:
                    continue
                cell_chg = 0.0

                # ── Fluid A ──
                dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                vol = dxi * dyj * dzk
                Kc = K_ffA_arr[i, j, k]
                hvA = h_vA_arr[i, j, k] * vol

                Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                dzt = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                dzb = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxe if i < Nx-1 else 0.0
                dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxw if i > 0 else 0.0
                dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyn if j < Ny-1 else 0.0
                dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dys if j > 0 else 0.0
                dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzt if k < Nz-1 else 0.0
                dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzb if k > 0 else 0.0

                u_e = ufA[i+1, j, k]; u_w = ufA[i, j, k]
                v_n = vfA[i, j+1, k]; v_s = vfA[i, j, k]
                w_t = wfA[i, j, k+1]; w_b = wfA[i, j, k]

                rcpA_c = rho_cp_fA[i,j,k]; ef_c = eps_fA_arr[i,j,k]
                rcp_e = 0.5*(rcpA_c + rho_cp_fA[i+1,j,k]) if i < Nx-1 else rcpA_c
                rcp_w = 0.5*(rho_cp_fA[i-1,j,k] + rcpA_c) if i > 0 else rcpA_c
                rcp_n = 0.5*(rcpA_c + rho_cp_fA[i,j+1,k]) if j < Ny-1 else rcpA_c
                rcp_s = 0.5*(rho_cp_fA[i,j-1,k] + rcpA_c) if j > 0 else rcpA_c
                rcp_t = 0.5*(rcpA_c + rho_cp_fA[i,j,k+1]) if k < Nz-1 else rcpA_c
                rcp_b = 0.5*(rho_cp_fA[i,j,k-1] + rcpA_c) if k > 0 else rcpA_c
                ef_e = 0.5*(ef_c + eps_fA_arr[i+1,j,k]) if i < Nx-1 else ef_c
                ef_w = 0.5*(eps_fA_arr[i-1,j,k] + ef_c) if i > 0 else ef_c
                ef_n = 0.5*(ef_c + eps_fA_arr[i,j+1,k]) if j < Ny-1 else ef_c
                ef_s = 0.5*(eps_fA_arr[i,j-1,k] + ef_c) if j > 0 else ef_c
                ef_t = 0.5*(ef_c + eps_fA_arr[i,j,k+1]) if k < Nz-1 else ef_c
                ef_b = 0.5*(eps_fA_arr[i,j,k-1] + ef_c) if k > 0 else ef_c

                F_e = ef_e * rcp_e * u_e * Ax
                F_w = ef_w * rcp_w * u_w * Ax
                F_n = ef_n * rcp_n * v_n * Ay
                F_s = ef_s * rcp_s * v_s * Ay
                F_t = ef_t * rcp_t * w_t * Az
                F_b = ef_b * rcp_b * w_b * Az

                F_e, F_w, F_n, F_s, F_t, F_b = _inlet_capacity_faces(
                    bc_A, i, j, k, Nx, Ny, Nz, ifrac_A, inlet_flux_A,
                    F_e, F_w, F_n, F_s, F_t, F_b)
                if model_mass_A is not None:
                    F_e = model_FA[0][i+1, j, k]
                    F_w = model_FA[0][i, j, k]
                    F_n = model_FA[1][i, j+1, k]
                    F_s = model_FA[1][i, j, k]
                    F_t = model_FA[2][i, j, k+1]
                    F_b = model_FA[2][i, j, k]

                aE = dE + max(-F_e, 0.0); aW = dW + max( F_w, 0.0)
                aN = dN + max(-F_n, 0.0); aS = dS + max( F_s, 0.0)
                aT = dT_ + max(-F_t, 0.0); aB = dB + max( F_b, 0.0)

                tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                (aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB) = _inlet_face_terms(
                    bc_A, i, j, k, Nx, Ny, Nz, ifrac_A, T_inA_arr,
                    Kc, dxi, dyj, dzk, aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB)

                if conservative == 1:
                    sou = (_sou_face_x_cons(Ta_snap, i, j, k, Nx, F_w, F_e)
                           + _sou_face_y_cons(Ta_snap, i, j, k, Ny, F_s, F_n)
                           + _sou_face_z_cons(Ta_snap, i, j, k, Nz, F_b, F_t))
                    if model_mass_A is not None:
                        sou = model_source_A[i, j, k]
                    net_out = (F_e - F_w) + (F_n - F_s) + (F_t - F_b)
                    aP = aE + aW + aN + aS + aT + aB + net_out + hvA
                else:
                    u_c_sou = 0.5*(u_e + u_w); v_c_sou = 0.5*(v_n + v_s)
                    w_c_sou = 0.5*(w_t + w_b)
                    Fx_mag = ef_c * rcpA_c * abs(u_c_sou) * Ax
                    Fy_mag = ef_c * rcpA_c * abs(v_c_sou) * Ay
                    Fz_mag = ef_c * rcpA_c * abs(w_c_sou) * Az
                    sou = (_sou_corr_x_3d(Ta_snap, i, j, k, Nx, u_c_sou, Fx_mag)
                           + _sou_corr_y_3d(Ta_snap, i, j, k, Ny, v_c_sou, Fy_mag)
                           + _sou_corr_z_3d(Ta_snap, i, j, k, Nz, w_c_sou, Fz_mag))
                    aP = aE + aW + aN + aS + aT + aB + hvA
                if aP < 1e-30:
                    aP = 1e-30
                S_A_cell = mms_S_A_arr[i, j, k] * vol
                new = (aE*tE + aW*tW + aN*tN + aS*tS + aT*tT + aB*tB
                       + hvA * Ts[i, j, k] + sou + S_A_cell) / aP
                old = Ta[i, j, k]
                upd = old + alpha_fA * (new - old)
                c = abs(upd - old)
                if c > cell_chg: cell_chg = c
                Ta[i, j, k] = upd

                # ── Solid ──
                dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                vol_s = dxi * dyj * dzk
                Ks = K_ss_arr[i, j, k]
                hvA_s = h_vA_arr[i, j, k] * vol_s
                hvB_s = h_vB_arr[i, j, k] * vol_s
                Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                dzt_s = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                dzb_s = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxe_s if i < Nx-1 else Ks*Ax/dxi
                Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxw_s if i > 0    else Ks*Ax/dxi
                Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyn_s if j < Ny-1 else Ks*Ay/dyj
                Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dys_s if j > 0    else Ks*Ay/dyj
                Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzt_s if k < Nz-1 else Ks*Az/dzk
                Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzb_s if k > 0    else Ks*Az/dzk
                sE = Ts[i+1, j, k] if i < Nx-1 else Ts[i, j, k]
                sW = Ts[i-1, j, k] if i > 0    else Ts[i, j, k]
                sN = Ts[i, j+1, k] if j < Ny-1 else Ts[i, j, k]
                sS = Ts[i, j-1, k] if j > 0    else Ts[i, j, k]
                sT = Ts[i, j, k+1] if k < Nz-1 else Ts[i, j, k]
                sB = Ts[i, j, k-1] if k > 0    else Ts[i, j, k]
                aP_s = De + Dw + Dn + Ds + Dt + Db + hvA_s + hvB_s
                S_s_cell = mms_S_s_arr[i, j, k] * vol_s
                new_s = (De*sE + Dw*sW + Dn*sN + Ds*sS + Dt*sT + Db*sB
                         + hvA_s*Ta[i, j, k] + hvB_s*Tb[i, j, k]
                         + S_s_cell) / aP_s
                old_s = Ts[i, j, k]
                upd_s = old_s + alpha_s * (new_s - old_s)
                c = abs(upd_s - old_s)
                if c > cell_chg: cell_chg = c
                Ts[i, j, k] = upd_s

                # ── Fluid B ──
                if freeze_Tb == 0:
                    vol_b = dxi * dyj * dzk
                    Kc_b = K_ffB_arr[i, j, k]
                    hvB = h_vB_arr[i, j, k] * vol_b
                    dxe_b = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw_b = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn_b = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys_b = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt_b = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb_b = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxe_b if i < Nx-1 else 0.0
                    dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxw_b if i > 0 else 0.0
                    dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyn_b if j < Ny-1 else 0.0
                    dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dys_b if j > 0 else 0.0
                    dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzt_b if k < Nz-1 else 0.0
                    dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzb_b if k > 0 else 0.0
                    uB_e = ufB[i+1, j, k]; uB_w = ufB[i, j, k]
                    vB_n = vfB[i, j+1, k]; vB_s = vfB[i, j, k]
                    wB_t = wfB[i, j, k+1]; wB_b = wfB[i, j, k]
                    rcpB_c = rho_cp_fB[i,j,k]; efB_c = eps_fB_arr[i,j,k]
                    rcpB_e = 0.5*(rcpB_c + rho_cp_fB[i+1,j,k]) if i < Nx-1 else rcpB_c
                    rcpB_w = 0.5*(rho_cp_fB[i-1,j,k] + rcpB_c) if i > 0 else rcpB_c
                    rcpB_n = 0.5*(rcpB_c + rho_cp_fB[i,j+1,k]) if j < Ny-1 else rcpB_c
                    rcpB_s = 0.5*(rho_cp_fB[i,j-1,k] + rcpB_c) if j > 0 else rcpB_c
                    rcpB_t = 0.5*(rcpB_c + rho_cp_fB[i,j,k+1]) if k < Nz-1 else rcpB_c
                    rcpB_b = 0.5*(rho_cp_fB[i,j,k-1] + rcpB_c) if k > 0 else rcpB_c
                    efB_e = 0.5*(efB_c + eps_fB_arr[i+1,j,k]) if i < Nx-1 else efB_c
                    efB_w = 0.5*(eps_fB_arr[i-1,j,k] + efB_c) if i > 0 else efB_c
                    efB_n = 0.5*(efB_c + eps_fB_arr[i,j+1,k]) if j < Ny-1 else efB_c
                    efB_s = 0.5*(eps_fB_arr[i,j-1,k] + efB_c) if j > 0 else efB_c
                    efB_t = 0.5*(efB_c + eps_fB_arr[i,j,k+1]) if k < Nz-1 else efB_c
                    efB_b = 0.5*(eps_fB_arr[i,j,k-1] + efB_c) if k > 0 else efB_c
                    FB_e = efB_e * rcpB_e * uB_e * Ax
                    FB_w = efB_w * rcpB_w * uB_w * Ax
                    FB_n = efB_n * rcpB_n * vB_n * Ay
                    FB_s = efB_s * rcpB_s * vB_s * Ay
                    FB_t = efB_t * rcpB_t * wB_t * Az
                    FB_b = efB_b * rcpB_b * wB_b * Az
                    FB_e, FB_w, FB_n, FB_s, FB_t, FB_b = _inlet_capacity_faces(
                        bc_B, i, j, k, Nx, Ny, Nz, ifrac_B, inlet_flux_B,
                        FB_e, FB_w, FB_n, FB_s, FB_t, FB_b)
                    if model_mass_A is not None:
                        FB_e = model_FB[0][i+1, j, k]
                        FB_w = model_FB[0][i, j, k]
                        FB_n = model_FB[1][i, j+1, k]
                        FB_s = model_FB[1][i, j, k]
                        FB_t = model_FB[2][i, j, k+1]
                        FB_b = model_FB[2][i, j, k]
                    aEb = dEb  + max(-FB_e, 0.0); aWb = dWb  + max( FB_w, 0.0)
                    aNb = dNb  + max(-FB_n, 0.0); aSb = dSb  + max( FB_s, 0.0)
                    aTb = dTb_ + max(-FB_t, 0.0); aBb = dBb  + max( FB_b, 0.0)
                    tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                    tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                    tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                    tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                    tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                    tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]

                    (aEb, aWb, aNb, aSb, aTb, aBb, tEb, tWb, tNb, tSb, tTb, tBb) = _inlet_face_terms(
                        bc_B, i, j, k, Nx, Ny, Nz, ifrac_B, T_inB_arr,
                        Kc_b, dxi, dyj, dzk, aEb, aWb, aNb, aSb, aTb, aBb, tEb, tWb, tNb, tSb, tTb, tBb)
                    if conservative == 1:
                        soub = (_sou_face_x_cons(Tb_snap, i, j, k, Nx, FB_w, FB_e)
                                + _sou_face_y_cons(Tb_snap, i, j, k, Ny, FB_s, FB_n)
                                + _sou_face_z_cons(Tb_snap, i, j, k, Nz, FB_b, FB_t))
                        if model_mass_A is not None:
                            soub = model_source_B[i, j, k]
                        net_outB = ((FB_e - FB_w) + (FB_n - FB_s)
                                    + (FB_t - FB_b))
                        aPb = (aEb + aWb + aNb + aSb + aTb + aBb
                               + net_outB + hvB)
                    else:
                        uBc_sou = 0.5*(uB_e + uB_w); vBc_sou = 0.5*(vB_n + vB_s)
                        wBc_sou = 0.5*(wB_t + wB_b)
                        FxB_mag = efB_c * rcpB_c * abs(uBc_sou) * Ax
                        FyB_mag = efB_c * rcpB_c * abs(vBc_sou) * Ay
                        FzB_mag = efB_c * rcpB_c * abs(wBc_sou) * Az
                        soub = (_sou_corr_x_3d(Tb_snap, i, j, k, Nx, uBc_sou, FxB_mag)
                                + _sou_corr_y_3d(Tb_snap, i, j, k, Ny, vBc_sou, FyB_mag)
                                + _sou_corr_z_3d(Tb_snap, i, j, k, Nz, wBc_sou, FzB_mag))
                        aPb = aEb + aWb + aNb + aSb + aTb + aBb + hvB
                    if aPb < 1e-30:
                        aPb = 1e-30
                    S_B_cell = mms_S_B_arr[i, j, k] * vol_b
                    new_b = (aEb*tEb + aWb*tWb + aNb*tNb + aSb*tSb
                             + aTb*tTb + aBb*tBb + hvB*Ts[i, j, k]
                             + soub + S_B_cell) / aPb
                    old_b = Tb[i, j, k]
                    upd_b = old_b + alpha_fB * (new_b - old_b)
                    c = abs(upd_b - old_b)
                    if c > cell_chg: cell_chg = c
                    Tb[i, j, k] = upd_b

                color_chg = max(color_chg, cell_chg)
            if color_chg > sweep_chg:
                sweep_chg = color_chg


        max_chg = sweep_chg
        if max_chg < 1e-10:
            break
    return max_chg


# ---------------------------------------------------------------------------
# Gauss-Seidel chunk — face-centered Patankar with Moukalled BC source
# (2026-04-26 strict-conservation refactor; PoC validated AB imbal < 0.1% in 1D)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _is_bc_face_inlet(face_dir, dir_code):
    """Return 1 if the given face direction (0=W, 1=E, 2=S, 3=N, 4=B, 5=T)
    matches the inlet face for this fluid's flow direction (dir_code), else 0.

    dir_code: 0=+x→inlet at W (face 0), 1=-x→inlet at E (face 1),
              2=+y→inlet at S (face 2), 3=-y→inlet at N (face 3),
              4=+z→inlet at B (face 4), 5=-z→inlet at T (face 5).
    """
    return 1 if face_dir == dir_code else 0


@njit(cache=True, fastmath=True)
def _is_bc_face_outlet(face_dir, dir_code):
    """Return 1 if face is outlet for this fluid. Outlet is opposite face of
    inlet: dir 0↔1, 2↔3, 4↔5."""
    if dir_code == 0 and face_dir == 1: return 1
    if dir_code == 1 and face_dir == 0: return 1
    if dir_code == 2 and face_dir == 3: return 1
    if dir_code == 3 and face_dir == 2: return 1
    if dir_code == 4 and face_dir == 5: return 1
    if dir_code == 5 and face_dir == 4: return 1
    return 0


@njit(cache=True, fastmath=True)
def _ifrac_at_face(ifrac, dir_code, i, j, k, Nx, Ny, Nz):
    """Lookup partial-inlet fraction at the inlet face for cell (i,j,k).

    Returns 0 if cell is not on the inlet face. ifrac shape depends on dir_code:
    dir 0/1 → (Ny,Nz); 2/3 → (Nx,Nz); 4/5 → (Nx,Ny).
    """
    if dir_code == 0 and i == 0:    return ifrac[j, k]
    if dir_code == 1 and i == Nx-1: return ifrac[j, k]
    if dir_code == 2 and j == 0:    return ifrac[i, k]
    if dir_code == 3 and j == Ny-1: return ifrac[i, k]
    if dir_code == 4 and k == 0:    return ifrac[i, j]
    if dir_code == 5 and k == Nz-1: return ifrac[i, j]
    return 0.0


@njit(cache=True, fastmath=True)
def _Tin_at_face(T_in_arr, dir_code, i, j, k, Nx, Ny, Nz):
    """Lookup inlet temperature at face for cell (i,j,k)."""
    if dir_code == 0 and i == 0:    return T_in_arr[j, k]
    if dir_code == 1 and i == Nx-1: return T_in_arr[j, k]
    if dir_code == 2 and j == 0:    return T_in_arr[i, k]
    if dir_code == 3 and j == Ny-1: return T_in_arr[i, k]
    if dir_code == 4 and k == 0:    return T_in_arr[i, j]
    if dir_code == 5 and k == Nz-1: return T_in_arr[i, j]
    return 0.0


# ---------------------------------------------------------------------------
# Gauss-Seidel chunk — 7-point + SOU + coupled Ta/Ts/Tb  (cell-centered u)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _gs_full_chunk_3d(Ta, Tb, Ts, Nx, Ny, Nz,
                      dx_arr, dy_arr, dz_arr,
                      K_ffA_arr, K_ffB_arr, K_ss_arr,
                      h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                      rho_cp_fA, rho_cp_fB,
                      ucA, vcA, wcA, ucB, vcB, wcB,
                      bc_A, bc_B, T_inA_arr, T_inB_arr,
                      ifrac_A, ifrac_B,
                      n_iters, freeze_Tb,
                      alpha_fA, alpha_s, alpha_fB, inlet_flux_A=None, inlet_flux_B=None):
    max_chg = 0.0

    # Sweep direction: follow A on i, B on j, A on k
    if bc_A == 1:
        i0, i1, di = Nx - 1, -1, -1
    else:
        i0, i1, di = 0, Nx, 1
    if bc_B == 3:
        j0, j1, dj = Ny - 1, -1, -1
    else:
        j0, j1, dj = 0, Ny, 1
    if bc_A == 5:
        k0, k1, dk = Nz - 1, -1, -1
    else:
        k0, k1, dk = 0, Nz, 1

    for _it in range(n_iters):
        max_chg = 0.0

        for i in range(i0, i1, di):
            for j in range(j0, j1, dj):
                for k in range(k0, k1, dk):

                    # ── Fluid A ──
                    dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                    vol = dxi * dyj * dzk
                    Kc = K_ffA_arr[i, j, k]
                    hvA = h_vA_arr[i, j, k] * vol

                    Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                    # Face spacing δx_e (#3D-7 fix) — conservative diffusion
                    dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxe if i < Nx-1 else 0.0
                    dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxw if i > 0 else 0.0
                    dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyn if j < Ny-1 else 0.0
                    dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dys if j > 0 else 0.0
                    dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzt if k < Nz-1 else 0.0
                    dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzb if k > 0 else 0.0

                    # Cell-local upwind (2026-04-25 FV#5): match 2D scheme.
                    # Each cell uses its own |u_c| for face flux magnitudes.
                    # F_x = F_w = ρcp·|u_c|·Ax → NET_OUT = 0 at cell level by
                    # construction, so the Patankar aP=Σa_nb + hvA form is
                    # locally conservative without a NET_OUT correction.
                    # Face-centered interpolation (FV-1) was theoretically
                    # more accurate but introduced a ~3× Q_enthalpy/Q_source
                    # mismatch because cell-averaged face u did not satisfy
                    # discrete mass conservation cell-wise. 2D has used this
                    # cell-local pattern forever with <1% AB imbalance.
                    u_c = ucA[i,j,k]; v_c = vcA[i,j,k]; w_c = wcA[i,j,k]
                    rcpA_c = rho_cp_fA[i,j,k]; ef_c = eps_fA_arr[i,j,k]
                    Fx = ef_c * rcpA_c * abs(u_c) * Ax
                    Fy = ef_c * rcpA_c * abs(v_c) * Ay
                    Fz = ef_c * rcpA_c * abs(w_c) * Az

                    if u_c >= 0.0: aW = dW + Fx; aE = dE
                    else:          aE = dE + Fx; aW = dW
                    if v_c >= 0.0: aS = dS + Fy; aN = dN
                    else:          aN = dN + Fy; aS = dS
                    if w_c >= 0.0: aB = dB + Fz; aT = dT_
                    else:          aT = dT_ + Fz; aB = dB

                    tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                    tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                    tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                    tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                    tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                    tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                    (aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB) = _inlet_face_terms(
                        bc_A, i, j, k, Nx, Ny, Nz, ifrac_A, T_inA_arr,
                        Kc, dxi, dyj, dzk, aE, aW, aN, aS, aT, aB, tE, tW, tN, tS, tT, tB, inlet_flux_A)

                    sou = (_sou_corr_x_3d(Ta, i, j, k, Nx, u_c, Fx)
                           + _sou_corr_y_3d(Ta, i, j, k, Ny, v_c, Fy)
                           + _sou_corr_z_3d(Ta, i, j, k, Nz, w_c, Fz))

                    aP = aE + aW + aN + aS + aT + aB + hvA
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + aT*tT + aB*tB
                           + hvA * Ts[i, j, k] + sou) / aP
                    old = Ta[i, j, k]
                    upd = old + alpha_fA * (new - old)
                    chg = abs(upd - old)
                    if chg > max_chg: max_chg = chg
                    Ta[i, j, k] = upd

                    # ── Solid ──
                    dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                    vol_s = dxi * dyj * dzk
                    Ks = K_ss_arr[i, j, k]
                    hvA_s = h_vA_arr[i, j, k] * vol_s
                    hvB_s = h_vB_arr[i, j, k] * vol_s

                    Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                    # Face spacing for solid (cell-local kernel)
                    dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt_s = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb_s = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxe_s if i < Nx-1 else Ks*Ax/dxi
                    Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxw_s if i > 0    else Ks*Ax/dxi
                    Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyn_s if j < Ny-1 else Ks*Ay/dyj
                    Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dys_s if j > 0    else Ks*Ay/dyj
                    Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzt_s if k < Nz-1 else Ks*Az/dzk
                    Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzb_s if k > 0    else Ks*Az/dzk

                    sE = Ts[i+1, j, k] if i < Nx-1 else Ts[i, j, k]
                    sW = Ts[i-1, j, k] if i > 0    else Ts[i, j, k]
                    sN = Ts[i, j+1, k] if j < Ny-1 else Ts[i, j, k]
                    sS = Ts[i, j-1, k] if j > 0    else Ts[i, j, k]
                    sT = Ts[i, j, k+1] if k < Nz-1 else Ts[i, j, k]
                    sB = Ts[i, j, k-1] if k > 0    else Ts[i, j, k]

                    aP_s = De + Dw + Dn + Ds + Dt + Db + hvA_s + hvB_s
                    new_s = (De*sE + Dw*sW + Dn*sN + Ds*sS + Dt*sT + Db*sB
                             + hvA_s*Ta[i, j, k] + hvB_s*Tb[i, j, k]) / aP_s
                    old_s = Ts[i, j, k]
                    upd_s = old_s + alpha_s * (new_s - old_s)
                    chg = abs(upd_s - old_s)
                    if chg > max_chg: max_chg = chg
                    Ts[i, j, k] = upd_s

                    # ── Fluid B ──
                    if freeze_Tb == 0:
                        vol_b = dxi * dyj * dzk
                        Kc_b = K_ffB_arr[i, j, k]
                        hvB = h_vB_arr[i, j, k] * vol_b

                        # Face spacing for B (cell-local kernel)
                        dxe_b = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw_b = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn_b = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys_b = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dzt_b = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                        dzb_b = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                        dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxe_b if i < Nx-1 else 0.0
                        dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxw_b if i > 0 else 0.0
                        dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyn_b if j < Ny-1 else 0.0
                        dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dys_b if j > 0 else 0.0
                        dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzt_b if k < Nz-1 else 0.0
                        dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzb_b if k > 0 else 0.0

                        # Cell-local upwind (2026-04-25 FV#5): match A branch + 2D.
                        uBc = ucB[i,j,k]; vBc = vcB[i,j,k]; wBc = wcB[i,j,k]
                        rcpB_c = rho_cp_fB[i,j,k]; efB_c = eps_fB_arr[i,j,k]
                        FxB = efB_c * rcpB_c * abs(uBc) * Ax
                        FyB = efB_c * rcpB_c * abs(vBc) * Ay
                        FzB = efB_c * rcpB_c * abs(wBc) * Az

                        if uBc >= 0.0: aWb = dWb + FxB; aEb = dEb
                        else:          aEb = dEb + FxB; aWb = dWb
                        if vBc >= 0.0: aSb = dSb + FyB; aNb = dNb
                        else:          aNb = dNb + FyB; aSb = dSb
                        if wBc >= 0.0: aBb = dBb + FzB; aTb = dTb_
                        else:          aTb = dTb_ + FzB; aBb = dBb

                        tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                        tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                        tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                        tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                        tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                        tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]

                        (aEb, aWb, aNb, aSb, aTb, aBb, tEb, tWb, tNb, tSb, tTb, tBb) = _inlet_face_terms(
                            bc_B, i, j, k, Nx, Ny, Nz, ifrac_B, T_inB_arr,
                            Kc_b, dxi, dyj, dzk, aEb, aWb, aNb, aSb, aTb, aBb, tEb, tWb, tNb, tSb, tTb, tBb, inlet_flux_B)

                        soub = (_sou_corr_x_3d(Tb, i, j, k, Nx, uBc, FxB)
                                + _sou_corr_y_3d(Tb, i, j, k, Ny, vBc, FyB)
                                + _sou_corr_z_3d(Tb, i, j, k, Nz, wBc, FzB))

                        aPb = aEb + aWb + aNb + aSb + aTb + aBb + hvB
                        new_b = (aEb*tEb + aWb*tWb + aNb*tNb + aSb*tSb
                                 + aTb*tTb + aBb*tBb + hvB*Ts[i, j, k] + soub) / aPb
                        old_b = Tb[i, j, k]
                        upd_b = old_b + alpha_fB * (new_b - old_b)
                        chg = abs(upd_b - old_b)
                        if chg > max_chg: max_chg = chg
                        Tb[i, j, k] = upd_b


        if max_chg < 1e-10:
            break

    return max_chg
