"""2D SIMPLE momentum, continuity and pressure-correction kernels."""

import numpy as np
from numba import njit
from ._kernels_2d import limited_face_increment, diffusion_conductance


@njit(cache=True, inline='always')
def _sou_axis(p_mm, p_m, p_c, p_p, p_pp,
              lo_pos, hi_pos, hi_neg, lo_neg, Flo, Fhi,
              widths=None, index=0, staggered=False):
    """Deferred face increments on physical cell-centre or face coordinates.

    The optional unit grid retains the historical direct helper API. Production
    callers always supply their actual widths and velocity-node placement.
    """
    dm2 = dm = dp = dp2 = 1.0
    lm = lp = hm = hp = 0.5
    if widths is not None:
        n = len(widths)
        if staggered:
            dm2 = widths[max(index - 2, 0)]
            dm = widths[max(index - 1, 0)]
            dp = widths[min(index, n - 1)]
            dp2 = widths[min(index + 1, n - 1)]
            lm = lp = 0.5 * dm
            hm = hp = 0.5 * dp
        else:
            wm2 = widths[max(index - 2, 0)]
            wm = widths[max(index - 1, 0)]
            wc = widths[index]
            wp = widths[min(index + 1, n - 1)]
            wp2 = widths[min(index + 2, n - 1)]
            dm2, dm = 0.5 * (wm2 + wm), 0.5 * (wm + wc)
            dp, dp2 = 0.5 * (wc + wp), 0.5 * (wp + wp2)
            lm, lp, hm, hp = 0.5 * wm, 0.5 * wc, 0.5 * wc, 0.5 * wp
    lo = 0.0
    if Flo >= 0.0:
        if lo_pos:
            lo = limited_face_increment(p_mm, p_m, p_c, dm2, dm, lm)
    elif lo_neg:
        lo = limited_face_increment(p_m, p_c, p_p, dm, dp, -lp)
    hi = 0.0
    if Fhi >= 0.0:
        if hi_pos:
            hi = limited_face_increment(p_m, p_c, p_p, dm, dp, hm)
    elif hi_neg:
        hi = limited_face_increment(p_c, p_p, p_pp, dp, dp2, -hp)
    return Flo * lo - Fhi * hi


@njit(cache=True, inline='always')
def _sou_diagonal_bound(pm, pc, pp, lo_neg, hi_pos, Flo, Fhi,
                        widths, index, staggered):
    """Bound the negative local derivative of deferred SOU at fixed flux.

    Only outflow faces reconstruct from this node. In a monotone stencil,
    minmod can switch between its two gradient branches: retain the bound
    for either branch, not just the currently selected one. Adding this
    coefficient on both sides of the predictor leaves its fixed point intact.
    """
    # prange indices may be unsigned; signed neighbours must remain integers.
    index = np.int64(index)
    wm = widths[max(index - 1, 0)]
    wc = widths[min(index, len(widths) - 1)]
    wp = widths[min(index + 1, len(widths) - 1)]
    if staggered:
        dm, dp = wm, wc
        lo_distance, hi_distance = 0.5 * wm, 0.5 * wc
    else:
        dm, dp = 0.5 * (wm + wc), 0.5 * (wc + wp)
        lo_distance = hi_distance = 0.5 * wc
    if (pc - pm) * (pp - pc) <= 0.0:
        return 0.0
    return ((max(Fhi, 0.0) * hi_distance / dm if hi_pos else 0.0)
            + (max(-Flo, 0.0) * lo_distance / dp if lo_neg else 0.0))


@njit(cache=True)
def _sou_corr_u_x(u, i, j, Nx, Fe, Fw, widths=None):
    return _sou_axis(u[max(i - 2, 0), j], u[max(i - 1, 0), j], u[i, j], u[min(i + 1, Nx), j], u[min(i + 2, Nx), j],
                     i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1, Fw, Fe, widths, i, True)


@njit(cache=True)
def _sou_corr_u_y(u, i, j, Ny, Fn, Fs, widths=None):
    return _sou_axis(u[i, max(j - 2, 0)], u[i, max(j - 1, 0)], u[i, j], u[i, min(j + 1, Ny - 1)], u[i, min(j + 2, Ny - 1)],
                     j > 1, j > 0 and j < Ny - 1, j < Ny - 2, j > 0 and j < Ny - 1, Fs, Fn, widths, j, False)


@njit(cache=True)
def _sou_corr_v_x(v, i, j, Nx, Fe, Fw, widths=None):
    return _sou_axis(v[max(i - 2, 0), j], v[max(i - 1, 0), j], v[i, j], v[min(i + 1, Nx - 1), j], v[min(i + 2, Nx - 1), j],
                     i > 1, i > 0 and i < Nx - 1, i < Nx - 2, i > 0 and i < Nx - 1, Fw, Fe, widths, i, False)


@njit(cache=True)
def _sou_corr_v_y(v, i, j, Ny, Fn, Fs, widths=None):
    return _sou_axis(v[i, max(j - 2, 0)], v[i, max(j - 1, 0)], v[i, j], v[i, min(j + 1, Ny)], v[i, min(j + 2, Ny)],
                     j > 2, j > 1 and j + 1 <= Ny, j + 2 <= Ny, j > 1, Fs, Fn, widths, j, True)


@njit(cache=True, inline='always')
def _eps_ratio(value, centre, use_eps):
    if use_eps == 0 or value == centre:
        return 1.0
    return value / centre


@njit(cache=True, inline='always')
def _mass_x_2d(velocity, rho, eps, i, j, eps_cv, use_eps=1):
    """The continuity mass-flux density, divided by this momentum CV epsilon."""
    if i == 0 or i == rho.shape[0]:
        return 0.0
    left = rho[i - 1, j] * _eps_ratio(eps[i - 1, j], eps_cv, use_eps)
    right = rho[i, j] * _eps_ratio(eps[i, j], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j]


@njit(cache=True, inline='always')
def _mass_y_2d(velocity, rho, eps, i, j, eps_cv, use_eps=1):
    """The continuity mass-flux density, divided by this momentum CV epsilon."""
    left = rho[i, max(j - 1, 0)] * _eps_ratio(eps[i, max(j - 1, 0)], eps_cv, use_eps)
    right = rho[i, min(j, rho.shape[1] - 1)] * _eps_ratio(eps[i, min(j, rho.shape[1] - 1)], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j]


@njit(cache=True, inline='always')
def _u_transport_2d(u, v, rho_field, mu_eff_field, eps_field,
                    dx, dy, i, j, outlet_u_frac):
    """Shared viscous subfaces and half-cell continuity mass fluxes.

    Axial faces lie at primary cell centres. Transverse faces consist
    of two parallel half-cell strips, each with its own series resistance.
    Epsilon division belongs to this momentum equation, after the shared
    physical flux; ratios preserve the uniform-epsilon cancellation.
    """
    eps_cv = 0.5 * (eps_field[i - 1, j] + eps_field[i, j])
    wl = 0.5 * dx[i - 1]
    wr = 0.5 * dx[i]
    De = (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1)) * dy[j] / dx[i]
    Fe = 0.5 * (_mass_x_2d(u, rho_field, eps_field, i, j, eps_cv, 1)
                           + _mass_x_2d(u, rho_field, eps_field, i + 1, j, eps_cv, 1)) * dy[j]
    Dw = (mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1)) * dy[j] / dx[i - 1]
    Fw = 0.5 * (_mass_x_2d(u, rho_field, eps_field, i, j, eps_cv, 1)
                           + _mass_x_2d(u, rho_field, eps_field, i - 1, j, eps_cv, 1)) * dy[j]
    if j < rho_field.shape[1] - 1:
        Dn = (wl * diffusion_conductance(
            mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1),
            mu_eff_field[i - 1, j + 1] * _eps_ratio(eps_field[i - 1, j + 1], eps_cv, 1),
            0.5 * dy[j], 0.5 * dy[j + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1),
            mu_eff_field[i, j + 1] * _eps_ratio(eps_field[i, j + 1], eps_cv, 1),
            0.5 * dy[j], 0.5 * dy[j + 1]))
    else:
        Dn = 2.0 * (wl * (mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1))
                      + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dy[j]
        Dn *= 1.0 - outlet_u_frac[i]
    Fn = (wl * _mass_y_2d(v, rho_field, eps_field, i - 1, j + 1, eps_cv, 1)
           + wr * _mass_y_2d(v, rho_field, eps_field, i, j + 1, eps_cv, 1))
    if j > 0:
        Ds = (wl * diffusion_conductance(
            mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1),
            mu_eff_field[i - 1, j - 1] * _eps_ratio(eps_field[i - 1, j - 1], eps_cv, 1),
            0.5 * dy[j], 0.5 * dy[j - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1),
            mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1),
            0.5 * dy[j], 0.5 * dy[j - 1]))
    else:
        Ds = 2.0 * (wl * (mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1))
                      + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dy[j]
    Fs = (wl * _mass_y_2d(v, rho_field, eps_field, i - 1, j, eps_cv, 1)
           + wr * _mass_y_2d(v, rho_field, eps_field, i, j, eps_cv, 1))
    return De, Dw, Dn, Ds, Fe, Fw, Fn, Fs


@njit(cache=True, inline='always')
def _v_transport_2d(u, v, rho_field, mu_eff_field, eps_field,
                    dx, dy, i, j):
    """Shared viscous subfaces and half-cell continuity mass fluxes.

    Axial faces lie at primary cell centres. Transverse faces consist
    of two parallel half-cell strips, each with its own series resistance.
    Epsilon division belongs to this momentum equation, after the shared
    physical flux; ratios preserve the uniform-epsilon cancellation.
    """
    eps_cv = 0.5 * (eps_field[i, j - 1] + eps_field[i, j])
    wl = 0.5 * dy[j - 1]
    wr = 0.5 * dy[j]
    if i < rho_field.shape[0] - 1:
        De = (wl * diffusion_conductance(
            mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1),
            mu_eff_field[i + 1, j - 1] * _eps_ratio(eps_field[i + 1, j - 1], eps_cv, 1),
            0.5 * dx[i], 0.5 * dx[i + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1),
            mu_eff_field[i + 1, j] * _eps_ratio(eps_field[i + 1, j], eps_cv, 1),
            0.5 * dx[i], 0.5 * dx[i + 1]))
    else:
        De = 2.0 * (wl * (mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1))
                      + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dx[i]
    Fe = (wl * _mass_x_2d(u, rho_field, eps_field, i + 1, j - 1, eps_cv, 1)
           + wr * _mass_x_2d(u, rho_field, eps_field, i + 1, j, eps_cv, 1))
    if i > 0:
        Dw = (wl * diffusion_conductance(
            mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1),
            mu_eff_field[i - 1, j - 1] * _eps_ratio(eps_field[i - 1, j - 1], eps_cv, 1),
            0.5 * dx[i], 0.5 * dx[i - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1),
            mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1),
            0.5 * dx[i], 0.5 * dx[i - 1]))
    else:
        Dw = 2.0 * (wl * (mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1))
                      + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dx[i]
    Fw = (wl * _mass_x_2d(u, rho_field, eps_field, i, j - 1, eps_cv, 1)
           + wr * _mass_x_2d(u, rho_field, eps_field, i, j, eps_cv, 1))
    Dn = (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1)) * dx[i] / dy[j]
    Fn = 0.5 * (_mass_y_2d(v, rho_field, eps_field, i, j, eps_cv, 1)
                           + _mass_y_2d(v, rho_field, eps_field, i, j + 1, eps_cv, 1)) * dx[i]
    Ds = (mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1)) * dx[i] / dy[j - 1]
    Fs = 0.5 * (_mass_y_2d(v, rho_field, eps_field, i, j, eps_cv, 1)
                           + _mass_y_2d(v, rho_field, eps_field, i, j - 1, eps_cv, 1)) * dx[i]
    return De, Dw, Dn, Ds, Fe, Fw, Fn, Fs


# ===================================================================
#  Numba kernels
# ===================================================================

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
def _umag_u(u, v, i, j, Nx):
    """Speed at u-face (i,j)."""
    il = max(i - 1, 0); ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j] + v[ir, j] + v[il, j + 1] + v[ir, j + 1])
    return np.sqrt(u[i, j] ** 2 + va ** 2)


@njit(cache=True)
def _umag_v(u, v, i, j, Ny):
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
    """Sweep interstitial x momentum with the existing D-F closure.

    The VANS equation is epsilon-divided: div(eps*rho*u*u)/eps_cv
    = -grad(p) + div(mu*grad(u))/eps_cv - drag. Shared physical
    face fluxes are divided by this CV's epsilon, while pressure and
    calibrated D-F terms keep their existing convention. mu_eff=mu/eps.
    The deferred diagonal term only stabilizes the nonlinear iteration.
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
                dyj = dy_arr[j]
                vol = dxi * dyj

                il_r = i - 1; ir_r = i
                (De, Dw, Dn, Ds, Fe, Fw, Fn, Fs) = _u_transport_2d(
                    u, v, rho_field, mu_eff_field, eps_field,
                    dx_arr, dy_arr, i, j, outlet_u_frac)
                uE = u[i + 1, j] if i + 1 < Nx else 0.0
                uW = u[i - 1, j] if i > 1 else 0.0
                uN = u[i, j + 1] if j < Ny - 1 else 0.0
                uS = u[i, j - 1] if j > 0 else 0.0
                rho_loc = 0.5 * (rho_field[i - 1, j] + rho_field[i, j])
                mu_loc = 0.5 * (mu_field[i - 1, j] + mu_field[i, j])

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_u(u, v, i, j, Nx)
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
                sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw, dx_arr)
                     + _sou_corr_u_y(u, i, j, Ny, Fn, Fs, dy_arr))
                aP0 = (De + Dw + Dn + Ds + Sp
                       + max(Fe, 0.0) + max(-Fw, 0.0)
                       + max(Fn, 0.0) + max(-Fs, 0.0))
                rhs = aE * uE + aW * uW + aN * uN + aS * uS + p_src + sou
                # Deferred diagonal compensation stabilizes a mass-deficit iterate.
                # It cancels at the fixed point: this is no physical source.
                compensation = max(-(Fe - Fw + Fn - Fs), 0.0)
                compensation += (_sou_diagonal_bound(
                    u[i - 1, j], u[i, j], u[i + 1, j],
                    i > 1, i > 1 and i + 1 < Nx, Fw, Fe, dx_arr, i, True)
                    + _sou_diagonal_bound(
                    u[i, max(j - 1, 0)], u[i, j], u[i, min(j + 1, Ny - 1)],
                    j > 0 and j < Ny - 1, j > 0 and j < Ny - 1,
                    Fs, Fn, dy_arr, j, False))
                aP_predict = aP0 + compensation
                rhs += compensation * u[i, j]
                aP = aP_predict / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP_predict * u[i, j]

                u[i, j] = rhs / aP
                d_u[i, j] = dyj / aP_predict

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
    """Sweep y momentum; physical and iteration conventions match x momentum."""
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                jc = min(j, Ny - 1)
                dxi = dx_arr[i]
                dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
                vol = dxi * dyj

                jb = j - 1; jt = j
                (De, Dw, Dn, Ds, Fe, Fw, Fn, Fs) = _v_transport_2d(
                    u, v, rho_field, mu_eff_field, eps_field,
                    dx_arr, dy_arr, i, j)
                vE = v[i + 1, j] if i < Nx - 1 else 0.0
                vW = v[i - 1, j] if i > 0 else 0.0
                vN = v[i, j + 1]
                vS = v[i, j - 1]
                rho_loc = 0.5 * (rho_field[i, j - 1] + rho_field[i, j])
                mu_loc = 0.5 * (mu_field[i, j - 1] + mu_field[i, j])

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_v(u, v, i, j, Ny)
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
                sou = (_sou_corr_v_x(v, i, j, Nx, Fe, Fw, dx_arr)
                     + _sou_corr_v_y(v, i, j, Ny, Fn, Fs, dy_arr))
                aP0 = (De + Dw + Dn + Ds + Sp
                       + max(Fe, 0.0) + max(-Fw, 0.0)
                       + max(Fn, 0.0) + max(-Fs, 0.0))
                rhs = aE * vE + aW * vW + aN * vN + aS * vS + p_src + sou
                # Deferred diagonal compensation stabilizes a mass-deficit iterate.
                # It cancels at the fixed point: this is no physical source.
                compensation = max(-(Fe - Fw + Fn - Fs), 0.0)
                compensation += (_sou_diagonal_bound(
                    v[max(i - 1, 0), j], v[i, j], v[min(i + 1, Nx - 1), j],
                    i > 0 and i < Nx - 1, i > 0 and i < Nx - 1,
                    Fw, Fe, dx_arr, i, False)
                    + _sou_diagonal_bound(
                    v[i, j - 1], v[i, j], v[i, j + 1],
                    j > 1, j > 1, Fs, Fn, dy_arr, j, True))
                aP_predict = aP0 + compensation
                rhs += compensation * v[i, j]
                aP = aP_predict / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP_predict * v[i, j]

                v[i, j] = rhs / aP
                d_v[i, j] = dxi / aP_predict

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
def _assemble_pp_data_jit(data, rhs, u, v, d_u, d_v, Nx, Ny, dx_arr, dy_arr, rho_field,
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


def _solve_pp_sparse_fast(Pp, u, v, d_u, d_v,
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

    _assemble_pp_data_jit(data, rhs, u, v, d_u, d_v, Nx, Ny, dx_arr, dy_arr, rho_field,
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
def _mass_res_jit(v, Nx, Ny, dx_arr, rho_field):
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
    """Unrelaxed conservative equation ``aP0*u = rhs`` for F2 residuals.

    Face transport is shared with the sweep. This assembly excludes its
    under-relaxation and deferred diagonal compensation, which cancel at a
    fixed point. tests/test_f2_convergence_2d.py guards that equality.
    SOU and epsilon ratios are always active in 2D.
    """
    dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
    dyj = dy_arr[j]
    vol = dxi * dyj

    il_r = i - 1; ir_r = i
    (De, Dw, Dn, Ds, Fe, Fw, Fn, Fs) = _u_transport_2d(
        u, v, rho_field, mu_eff_field, eps_field,
        dx_arr, dy_arr, i, j, outlet_u_frac)
    uE = u[i + 1, j] if i + 1 < Nx else 0.0
    uW = u[i - 1, j] if i > 1 else 0.0
    uN = u[i, j + 1] if j < Ny - 1 else 0.0
    uS = u[i, j - 1] if j > 0 else 0.0
    rho_loc = 0.5 * (rho_field[i - 1, j] + rho_field[i, j])
    mu_loc = 0.5 * (mu_field[i - 1, j] + mu_field[i, j])

    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)

    umag = _umag_u(u, v, i, j, Nx)
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
    sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw, dx_arr)
           + _sou_corr_u_y(u, i, j, Ny, Fn, Fs, dy_arr))
    aP0 = (De + Dw + Dn + Ds + Sp
                       + max(Fe, 0.0) + max(-Fw, 0.0)
                       + max(Fn, 0.0) + max(-Fs, 0.0))
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

    jb = j - 1; jt = j
    (De, Dw, Dn, Ds, Fe, Fw, Fn, Fs) = _v_transport_2d(
        u, v, rho_field, mu_eff_field, eps_field,
        dx_arr, dy_arr, i, j)
    vE = v[i + 1, j] if i < Nx - 1 else 0.0
    vW = v[i - 1, j] if i > 0 else 0.0
    vN = v[i, j + 1]
    vS = v[i, j - 1]
    rho_loc = 0.5 * (rho_field[i, j - 1] + rho_field[i, j])
    mu_loc = 0.5 * (mu_field[i, j - 1] + mu_field[i, j])

    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)

    umag = _umag_v(u, v, i, j, Ny)
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
    sou = (_sou_corr_v_x(v, i, j, Nx, Fe, Fw, dx_arr)
           + _sou_corr_v_y(v, i, j, Ny, Fn, Fs, dy_arr))
    aP0 = (De + Dw + Dn + Ds + Sp
                       + max(Fe, 0.0) + max(-Fw, 0.0)
                       + max(Fn, 0.0) + max(-Fs, 0.0))
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
