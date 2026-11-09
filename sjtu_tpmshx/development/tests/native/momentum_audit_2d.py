"""Read-only finite-volume momentum equations for native 2D audits."""
import numpy as np

from .thermal_face_audit import limited_face_increment


def diffusion_conductance(kl, kr, dl, dr):
    """Unit-area conductance of the two centre-to-face resistances in series."""
    if kl <= 0.0 or kr <= 0.0:
        return 0.0
    return kl * kr / (dl * kr + dr * kl)


def _sou_axis(p_mm, p_m, p_c, p_p, p_pp, lo_pos, hi_pos, hi_neg, lo_neg, Flo, Fhi, widths=None, index=0, staggered=False):
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
            dm2, dm = (0.5 * (wm2 + wm), 0.5 * (wm + wc))
            dp, dp2 = (0.5 * (wc + wp), 0.5 * (wp + wp2))
            lm, lp, hm, hp = (0.5 * wm, 0.5 * wc, 0.5 * wc, 0.5 * wp)
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


def _sou_corr_u_x(u, i, j, Nx, Fe, Fw, widths=None):
    return _sou_axis(u[max(i - 2, 0), j], u[max(i - 1, 0), j], u[i, j], u[min(i + 1, Nx), j], u[min(i + 2, Nx), j], i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1, Fw, Fe, widths, i, True)


def _sou_corr_u_y(u, i, j, Ny, Fn, Fs, widths=None):
    return _sou_axis(u[i, max(j - 2, 0)], u[i, max(j - 1, 0)], u[i, j], u[i, min(j + 1, Ny - 1)], u[i, min(j + 2, Ny - 1)], j > 1, j > 0 and j < Ny - 1, j < Ny - 2, j > 0 and j < Ny - 1, Fs, Fn, widths, j, False)


def _sou_corr_v_x(v, i, j, Nx, Fe, Fw, widths=None):
    return _sou_axis(v[max(i - 2, 0), j], v[max(i - 1, 0), j], v[i, j], v[min(i + 1, Nx - 1), j], v[min(i + 2, Nx - 1), j], i > 1, i > 0 and i < Nx - 1, i < Nx - 2, i > 0 and i < Nx - 1, Fw, Fe, widths, i, False)


def _sou_corr_v_y(v, i, j, Ny, Fn, Fs, widths=None):
    return _sou_axis(v[i, max(j - 2, 0)], v[i, max(j - 1, 0)], v[i, j], v[i, min(j + 1, Ny)], v[i, min(j + 2, Ny)], j > 2, j > 1 and j + 1 <= Ny, j + 2 <= Ny, j > 1, Fs, Fn, widths, j, True)


def _eps_ratio(value, centre, use_eps):
    if use_eps == 0 or value == centre:
        return 1.0
    return value / centre


def _mass_x_2d(velocity, rho, eps, i, j, eps_cv, use_eps=1):
    if i == 0 or i == rho.shape[0]:
        return 0.0
    left = rho[i - 1, j] * _eps_ratio(eps[i - 1, j], eps_cv, use_eps)
    right = rho[i, j] * _eps_ratio(eps[i, j], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j]


def _mass_y_2d(velocity, rho, eps, i, j, eps_cv, use_eps=1):
    left = rho[i, max(j - 1, 0)] * _eps_ratio(eps[i, max(j - 1, 0)], eps_cv, use_eps)
    right = rho[i, min(j, rho.shape[1] - 1)] * _eps_ratio(eps[i, min(j, rho.shape[1] - 1)], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j]


def _u_transport_2d(u, v, rho_field, mu_eff_field, eps_field, dx, dy, i, j, outlet_u_frac):
    eps_cv = 0.5 * (eps_field[i - 1, j] + eps_field[i, j])
    wl = 0.5 * dx[i - 1]
    wr = 0.5 * dx[i]
    De = mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1) * dy[j] / dx[i]
    Fe = 0.5 * (_mass_x_2d(u, rho_field, eps_field, i, j, eps_cv, 1) + _mass_x_2d(u, rho_field, eps_field, i + 1, j, eps_cv, 1)) * dy[j]
    Dw = mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1) * dy[j] / dx[i - 1]
    Fw = 0.5 * (_mass_x_2d(u, rho_field, eps_field, i, j, eps_cv, 1) + _mass_x_2d(u, rho_field, eps_field, i - 1, j, eps_cv, 1)) * dy[j]
    if j < rho_field.shape[1] - 1:
        Dn = wl * diffusion_conductance(mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1), mu_eff_field[i - 1, j + 1] * _eps_ratio(eps_field[i - 1, j + 1], eps_cv, 1), 0.5 * dy[j], 0.5 * dy[j + 1]) + wr * diffusion_conductance(mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1), mu_eff_field[i, j + 1] * _eps_ratio(eps_field[i, j + 1], eps_cv, 1), 0.5 * dy[j], 0.5 * dy[j + 1])
    else:
        Dn = 2.0 * (wl * (mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1)) + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dy[j]
        Dn *= 1.0 - outlet_u_frac[i]
    Fn = wl * _mass_y_2d(v, rho_field, eps_field, i - 1, j + 1, eps_cv, 1) + wr * _mass_y_2d(v, rho_field, eps_field, i, j + 1, eps_cv, 1)
    if j > 0:
        Ds = wl * diffusion_conductance(mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1), mu_eff_field[i - 1, j - 1] * _eps_ratio(eps_field[i - 1, j - 1], eps_cv, 1), 0.5 * dy[j], 0.5 * dy[j - 1]) + wr * diffusion_conductance(mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1), mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1), 0.5 * dy[j], 0.5 * dy[j - 1])
    else:
        Ds = 2.0 * (wl * (mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1)) + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dy[j]
    Fs = wl * _mass_y_2d(v, rho_field, eps_field, i - 1, j, eps_cv, 1) + wr * _mass_y_2d(v, rho_field, eps_field, i, j, eps_cv, 1)
    return (De, Dw, Dn, Ds, Fe, Fw, Fn, Fs)


def _v_transport_2d(u, v, rho_field, mu_eff_field, eps_field, dx, dy, i, j):
    eps_cv = 0.5 * (eps_field[i, j - 1] + eps_field[i, j])
    wl = 0.5 * dy[j - 1]
    wr = 0.5 * dy[j]
    if i < rho_field.shape[0] - 1:
        De = wl * diffusion_conductance(mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1), mu_eff_field[i + 1, j - 1] * _eps_ratio(eps_field[i + 1, j - 1], eps_cv, 1), 0.5 * dx[i], 0.5 * dx[i + 1]) + wr * diffusion_conductance(mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1), mu_eff_field[i + 1, j] * _eps_ratio(eps_field[i + 1, j], eps_cv, 1), 0.5 * dx[i], 0.5 * dx[i + 1])
    else:
        De = 2.0 * (wl * (mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1)) + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dx[i]
    Fe = wl * _mass_x_2d(u, rho_field, eps_field, i + 1, j - 1, eps_cv, 1) + wr * _mass_x_2d(u, rho_field, eps_field, i + 1, j, eps_cv, 1)
    if i > 0:
        Dw = wl * diffusion_conductance(mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1), mu_eff_field[i - 1, j - 1] * _eps_ratio(eps_field[i - 1, j - 1], eps_cv, 1), 0.5 * dx[i], 0.5 * dx[i - 1]) + wr * diffusion_conductance(mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1), mu_eff_field[i - 1, j] * _eps_ratio(eps_field[i - 1, j], eps_cv, 1), 0.5 * dx[i], 0.5 * dx[i - 1])
    else:
        Dw = 2.0 * (wl * (mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1)) + wr * (mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1))) / dx[i]
    Fw = wl * _mass_x_2d(u, rho_field, eps_field, i, j - 1, eps_cv, 1) + wr * _mass_x_2d(u, rho_field, eps_field, i, j, eps_cv, 1)
    Dn = mu_eff_field[i, j] * _eps_ratio(eps_field[i, j], eps_cv, 1) * dx[i] / dy[j]
    Fn = 0.5 * (_mass_y_2d(v, rho_field, eps_field, i, j, eps_cv, 1) + _mass_y_2d(v, rho_field, eps_field, i, j + 1, eps_cv, 1)) * dx[i]
    Ds = mu_eff_field[i, j - 1] * _eps_ratio(eps_field[i, j - 1], eps_cv, 1) * dx[i] / dy[j - 1]
    Fs = 0.5 * (_mass_y_2d(v, rho_field, eps_field, i, j, eps_cv, 1) + _mass_y_2d(v, rho_field, eps_field, i, j - 1, eps_cv, 1)) * dx[i]
    return (De, Dw, Dn, Ds, Fe, Fw, Fn, Fs)


def _porous_src_df(umag, K, cF, mu, rho):
    if umag < 1e-10:
        return mu / K
    return mu / K + rho * cF * umag


def _umag_u(u, v, i, j, Nx):
    il = max(i - 1, 0)
    ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j] + v[ir, j] + v[il, j + 1] + v[ir, j + 1])
    return np.sqrt(u[i, j] ** 2 + va ** 2)


def _umag_v(u, v, i, j, Ny):
    jb = max(j - 1, 0)
    jt = min(j, Ny - 1)
    ua = 0.25 * (u[i, jb] + u[i + 1, jb] + u[i, jt] + u[i + 1, jt])
    return np.sqrt(ua ** 2 + v[i, j] ** 2)


def _u_coeffs_df_2d(u, v, P, i, j, Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field, K_arr, cF_arr, mu_field, eps_field, outlet_u_frac, cf_aniso):
    dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
    dyj = dy_arr[j]
    vol = dxi * dyj
    il_r = i - 1
    ir_r = i
    De, Dw, Dn, Ds, Fe, Fw, Fn, Fs = _u_transport_2d(u, v, rho_field, mu_eff_field, eps_field, dx_arr, dy_arr, i, j, outlet_u_frac)
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
        va_c = 0.25 * (v[il_r, j] + v[ir_r, j] + v[il_r, j + 1] + v[ir_r, j + 1])
        ux2 = u[i, j] * u[i, j]
        uy2 = va_c * va_c
        xi4 = 4.0 * ux2 * uy2 / (umag * umag * umag * umag)
        cF_u = cF_u * (1.0 + cf_aniso * xi4)
    Sp = _porous_src_df(umag, K_u, cF_u, mu_loc, rho_loc) * vol
    p_src = (P[i - 1, j] - P[i, j]) * dyj
    sou = _sou_corr_u_x(u, i, j, Nx, Fe, Fw, dx_arr) + _sou_corr_u_y(u, i, j, Ny, Fn, Fs, dy_arr)
    aP0 = De + Dw + Dn + Ds + Sp + max(Fe, 0.0) + max(-Fw, 0.0) + max(Fn, 0.0) + max(-Fs, 0.0)
    rhs = aE * uE + aW * uW + aN * uN + aS * uS + p_src + sou
    return (aP0, rhs)


def _v_coeffs_df_2d(u, v, P, i, j, Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field, K_arr, cF_arr, mu_field, eps_field, cf_aniso):
    jc = min(j, Ny - 1)
    dxi = dx_arr[i]
    dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
    vol = dxi * dyj
    jb = j - 1
    jt = j
    De, Dw, Dn, Ds, Fe, Fw, Fn, Fs = _v_transport_2d(u, v, rho_field, mu_eff_field, eps_field, dx_arr, dy_arr, i, j)
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
        ua_c = 0.25 * (u[i, jb] + u[i + 1, jb] + u[i, jt] + u[i + 1, jt])
        ux2 = ua_c * ua_c
        uy2 = v[i, j] * v[i, j]
        xi4 = 4.0 * ux2 * uy2 / (umag * umag * umag * umag)
        cF_v = cF_v * (1.0 + cf_aniso * xi4)
    Sp = _porous_src_df(umag, K_arr[i, jc], cF_v, mu_loc, rho_loc) * vol
    p_src = (P[i, j - 1] - P[i, j]) * dxi
    sou = _sou_corr_v_x(v, i, j, Nx, Fe, Fw, dx_arr) + _sou_corr_v_y(v, i, j, Ny, Fn, Fs, dy_arr)
    aP0 = De + Dw + Dn + Ds + Sp + max(Fe, 0.0) + max(-Fw, 0.0) + max(Fn, 0.0) + max(-Fs, 0.0)
    rhs = aE * vE + aW * vW + aN * vN + aS * vS + p_src + sou
    return (aP0, rhs)


def _mom_res_jit_2d(u, v, P, Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field, K_arr, cF_arr, mu_field, eps_field, outlet_u_frac, cf_aniso):
    nu_ = 0.0
    du_ = 0.0
    for i in range(1, Nx):
        for j in range(Ny):
            aP0, rhs = _u_coeffs_df_2d(u, v, P, i, j, Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field, K_arr, cF_arr, mu_field, eps_field, outlet_u_frac, cf_aniso)
            lhs = aP0 * u[i, j]
            nu_ += abs(lhs - rhs)
            du_ += 0.5 * (abs(lhs) + abs(rhs))
    nv_ = 0.0
    dv_ = 0.0
    for i in range(Nx):
        for j in range(1, Ny):
            aP0, rhs = _v_coeffs_df_2d(u, v, P, i, j, Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field, K_arr, cF_arr, mu_field, eps_field, cf_aniso)
            lhs = aP0 * v[i, j]
            nv_ += abs(lhs - rhs)
            dv_ += 0.5 * (abs(lhs) + abs(rhs))
    return (nu_, du_, nv_, dv_)
