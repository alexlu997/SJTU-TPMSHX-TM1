"""Read-only finite-volume momentum equations for native 3D audits."""
import numpy as np

from .momentum_audit_2d import _sou_axis, diffusion_conductance


def _eps_ratio(value, centre, use_eps):
    if use_eps == 0 or value == centre:
        return 1.0
    return value / centre


def _mass_x_3d(velocity, rho, eps, i, j, k, eps_cv, use_eps=1):
    if i == 0 or i == rho.shape[0]:
        return 0.0
    left = rho[i - 1, j, k] * _eps_ratio(eps[i - 1, j, k], eps_cv, use_eps)
    right = rho[i, j, k] * _eps_ratio(eps[i, j, k], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j, k]


def _mass_y_3d(velocity, rho, eps, i, j, k, eps_cv, use_eps=1):
    left = rho[i, max(j - 1, 0), k] * _eps_ratio(eps[i, max(j - 1, 0), k], eps_cv, use_eps)
    right = rho[i, min(j, rho.shape[1] - 1), k] * _eps_ratio(eps[i, min(j, rho.shape[1] - 1), k], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j, k]


def _mass_z_3d(velocity, rho, eps, i, j, k, eps_cv, use_eps=1):
    if k == 0 or k == rho.shape[2]:
        return 0.0
    left = rho[i, j, k - 1] * _eps_ratio(eps[i, j, k - 1], eps_cv, use_eps)
    right = rho[i, j, k] * _eps_ratio(eps[i, j, k], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j, k]


def _u_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field, dx, dy, dz, i, j, k, outlet_u_frac, use_eps=1):
    eps_cv = 0.5 * (eps_field[i - 1, j, k] + eps_field[i, j, k]) if use_eps == 1 else 1.0
    wl = 0.5 * dx[i - 1]
    wr = 0.5 * dx[i]
    De = mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps) * (dy[j] * dz[k]) / dx[i]
    Fe = 0.5 * (_mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps) + _mass_x_3d(u, rho_field, eps_field, i + 1, j, k, eps_cv, use_eps)) * (dy[j] * dz[k])
    Dw = mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps) * (dy[j] * dz[k]) / dx[i - 1]
    Fw = 0.5 * (_mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps) + _mass_x_3d(u, rho_field, eps_field, i - 1, j, k, eps_cv, use_eps)) * (dy[j] * dz[k])
    if j < rho_field.shape[1] - 1:
        Dn = (wl * diffusion_conductance(mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps), mu_eff_field[i - 1, j + 1, k] * _eps_ratio(eps_field[i - 1, j + 1, k], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j + 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j + 1, k] * _eps_ratio(eps_field[i, j + 1, k], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j + 1])) * dz[k]
    else:
        Dn = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dy[j]
        Dn *= 1.0 - outlet_u_frac[i, k]
    Fn = (wl * _mass_y_3d(v, rho_field, eps_field, i - 1, j + 1, k, eps_cv, use_eps) + wr * _mass_y_3d(v, rho_field, eps_field, i, j + 1, k, eps_cv, use_eps)) * dz[k]
    if j > 0:
        Ds = (wl * diffusion_conductance(mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps), mu_eff_field[i - 1, j - 1, k] * _eps_ratio(eps_field[i - 1, j - 1, k], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j - 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j - 1])) * dz[k]
    else:
        Ds = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dy[j]
    Fs = (wl * _mass_y_3d(v, rho_field, eps_field, i - 1, j, k, eps_cv, use_eps) + wr * _mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dz[k]
    if k < rho_field.shape[2] - 1:
        Dt = (wl * diffusion_conductance(mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps), mu_eff_field[i - 1, j, k + 1] * _eps_ratio(eps_field[i - 1, j, k + 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k + 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j, k + 1] * _eps_ratio(eps_field[i, j, k + 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k + 1])) * dy[j]
    else:
        Dt = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dz[k]
    Ft = (wl * _mass_z_3d(w, rho_field, eps_field, i - 1, j, k + 1, eps_cv, use_eps) + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k + 1, eps_cv, use_eps)) * dy[j]
    if k > 0:
        Db = (wl * diffusion_conductance(mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps), mu_eff_field[i - 1, j, k - 1] * _eps_ratio(eps_field[i - 1, j, k - 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k - 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k - 1])) * dy[j]
    else:
        Db = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dz[k]
    Fb = (wl * _mass_z_3d(w, rho_field, eps_field, i - 1, j, k, eps_cv, use_eps) + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dy[j]
    return (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb)


def _v_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field, dx, dy, dz, i, j, k, use_eps=1):
    eps_cv = 0.5 * (eps_field[i, j - 1, k] + eps_field[i, j, k]) if use_eps == 1 else 1.0
    wl = 0.5 * dy[j - 1]
    wr = 0.5 * dy[j]
    if i < rho_field.shape[0] - 1:
        De = (wl * diffusion_conductance(mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps), mu_eff_field[i + 1, j - 1, k] * _eps_ratio(eps_field[i + 1, j - 1, k], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i + 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i + 1, j, k] * _eps_ratio(eps_field[i + 1, j, k], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i + 1])) * dz[k]
    else:
        De = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dx[i]
    Fe = (wl * _mass_x_3d(u, rho_field, eps_field, i + 1, j - 1, k, eps_cv, use_eps) + wr * _mass_x_3d(u, rho_field, eps_field, i + 1, j, k, eps_cv, use_eps)) * dz[k]
    if i > 0:
        Dw = (wl * diffusion_conductance(mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps), mu_eff_field[i - 1, j - 1, k] * _eps_ratio(eps_field[i - 1, j - 1, k], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i - 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i - 1])) * dz[k]
    else:
        Dw = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dx[i]
    Fw = (wl * _mass_x_3d(u, rho_field, eps_field, i, j - 1, k, eps_cv, use_eps) + wr * _mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dz[k]
    Dn = mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps) * (dx[i] * dz[k]) / dy[j]
    Fn = 0.5 * (_mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps) + _mass_y_3d(v, rho_field, eps_field, i, j + 1, k, eps_cv, use_eps)) * (dx[i] * dz[k])
    Ds = mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps) * (dx[i] * dz[k]) / dy[j - 1]
    Fs = 0.5 * (_mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps) + _mass_y_3d(v, rho_field, eps_field, i, j - 1, k, eps_cv, use_eps)) * (dx[i] * dz[k])
    if k < rho_field.shape[2] - 1:
        Dt = (wl * diffusion_conductance(mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps), mu_eff_field[i, j - 1, k + 1] * _eps_ratio(eps_field[i, j - 1, k + 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k + 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j, k + 1] * _eps_ratio(eps_field[i, j, k + 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k + 1])) * dx[i]
    else:
        Dt = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dz[k]
    Ft = (wl * _mass_z_3d(w, rho_field, eps_field, i, j - 1, k + 1, eps_cv, use_eps) + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k + 1, eps_cv, use_eps)) * dx[i]
    if k > 0:
        Db = (wl * diffusion_conductance(mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps), mu_eff_field[i, j - 1, k - 1] * _eps_ratio(eps_field[i, j - 1, k - 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k - 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps), 0.5 * dz[k], 0.5 * dz[k - 1])) * dx[i]
    else:
        Db = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dz[k]
    Fb = (wl * _mass_z_3d(w, rho_field, eps_field, i, j - 1, k, eps_cv, use_eps) + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dx[i]
    return (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb)


def _w_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field, dx, dy, dz, i, j, k, outlet_w_frac, use_eps=1):
    eps_cv = 0.5 * (eps_field[i, j, k - 1] + eps_field[i, j, k]) if use_eps == 1 else 1.0
    wl = 0.5 * dz[k - 1]
    wr = 0.5 * dz[k]
    if i < rho_field.shape[0] - 1:
        De = (wl * diffusion_conductance(mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps), mu_eff_field[i + 1, j, k - 1] * _eps_ratio(eps_field[i + 1, j, k - 1], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i + 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i + 1, j, k] * _eps_ratio(eps_field[i + 1, j, k], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i + 1])) * dy[j]
    else:
        De = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dx[i]
    Fe = (wl * _mass_x_3d(u, rho_field, eps_field, i + 1, j, k - 1, eps_cv, use_eps) + wr * _mass_x_3d(u, rho_field, eps_field, i + 1, j, k, eps_cv, use_eps)) * dy[j]
    if i > 0:
        Dw = (wl * diffusion_conductance(mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps), mu_eff_field[i - 1, j, k - 1] * _eps_ratio(eps_field[i - 1, j, k - 1], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i - 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps), 0.5 * dx[i], 0.5 * dx[i - 1])) * dy[j]
    else:
        Dw = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dx[i]
    Fw = (wl * _mass_x_3d(u, rho_field, eps_field, i, j, k - 1, eps_cv, use_eps) + wr * _mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dy[j]
    if j < rho_field.shape[1] - 1:
        Dn = (wl * diffusion_conductance(mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps), mu_eff_field[i, j + 1, k - 1] * _eps_ratio(eps_field[i, j + 1, k - 1], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j + 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j + 1, k] * _eps_ratio(eps_field[i, j + 1, k], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j + 1])) * dx[i]
    else:
        Dn = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dy[j]
        Dn *= 1.0 - outlet_w_frac[i, k]
    Fn = (wl * _mass_y_3d(v, rho_field, eps_field, i, j + 1, k - 1, eps_cv, use_eps) + wr * _mass_y_3d(v, rho_field, eps_field, i, j + 1, k, eps_cv, use_eps)) * dx[i]
    if j > 0:
        Ds = (wl * diffusion_conductance(mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps), mu_eff_field[i, j - 1, k - 1] * _eps_ratio(eps_field[i, j - 1, k - 1], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j - 1]) + wr * diffusion_conductance(mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps), mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps), 0.5 * dy[j], 0.5 * dy[j - 1])) * dx[i]
    else:
        Ds = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps)) + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dy[j]
    Fs = (wl * _mass_y_3d(v, rho_field, eps_field, i, j, k - 1, eps_cv, use_eps) + wr * _mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dx[i]
    Dt = mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps) * (dx[i] * dy[j]) / dz[k]
    Ft = 0.5 * (_mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps) + _mass_z_3d(w, rho_field, eps_field, i, j, k + 1, eps_cv, use_eps)) * (dx[i] * dy[j])
    Db = mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps) * (dx[i] * dy[j]) / dz[k - 1]
    Fb = 0.5 * (_mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps) + _mass_z_3d(w, rho_field, eps_field, i, j, k - 1, eps_cv, use_eps)) * (dx[i] * dy[j])
    return (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb)


def _umag_u_3d(u, v, w, i, j, k, Nx):
    il = max(i - 1, 0)
    ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j, k] + v[ir, j, k] + v[il, j + 1, k] + v[ir, j + 1, k])
    wa = 0.25 * (w[il, j, k] + w[ir, j, k] + w[il, j, k + 1] + w[ir, j, k + 1])
    return np.sqrt(u[i, j, k] ** 2 + va ** 2 + wa ** 2)


def _umag_v_3d(u, v, w, i, j, k, Ny):
    jb = max(j - 1, 0)
    jt = min(j, Ny - 1)
    ua = 0.25 * (u[i, jb, k] + u[i + 1, jb, k] + u[i, jt, k] + u[i + 1, jt, k])
    wa = 0.25 * (w[i, jb, k] + w[i, jt, k] + w[i, jb, k + 1] + w[i, jt, k + 1])
    return np.sqrt(ua ** 2 + v[i, j, k] ** 2 + wa ** 2)


def _umag_w_3d(u, v, w, i, j, k, Nz):
    kb = max(k - 1, 0)
    kt = min(k, Nz - 1)
    ua = 0.25 * (u[i, j, kb] + u[i + 1, j, kb] + u[i, j, kt] + u[i + 1, j, kt])
    va = 0.25 * (v[i, j, kb] + v[i, j + 1, kb] + v[i, j, kt] + v[i, j + 1, kt])
    return np.sqrt(ua ** 2 + va ** 2 + w[i, j, k] ** 2)


def _porous_src_df_3d(umag, K, cF, mu, rho):
    if umag < 1e-10:
        return mu / K
    return mu / K + rho * cF * umag


def _u_coeffs_df_3d(u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, outlet_u_frac, use_sou, use_eps):
    dxi = 0.5 * (dx[i - 1] + dx[min(i, Nx - 1)])
    dyj = dy[j]
    dzk = dz[k]
    vol = dxi * dyj * dzk
    il_r = i - 1
    ir_r = i
    De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb = _u_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field, dx, dy, dz, i, j, k, outlet_u_frac, use_eps)
    uE = u[i + 1, j, k] if i + 1 < Nx else 0.0
    uW = u[i - 1, j, k] if i > 0 else 0.0
    uN = u[i, j + 1, k] if j < Ny - 1 else 0.0
    uS = u[i, j - 1, k] if j > 0 else 0.0
    uT = u[i, j, k + 1] if k < Nz - 1 else 0.0
    uB = u[i, j, k - 1] if k > 0 else 0.0
    rho_loc = 0.5 * (rho_field[i - 1, j, k] + rho_field[i, j, k])
    mu_loc = 0.5 * (mu_field[i - 1, j, k] + mu_field[i, j, k])
    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)
    aT = Dt + max(-Ft, 0.0)
    aB = Db + max(Fb, 0.0)
    umag = _umag_u_3d(u, v, w, i, j, k, Nx)
    K_u = 0.5 * (K_arr[il_r, j, k] + K_arr[ir_r, j, k])
    cF_u = 0.5 * (cF_arr[il_r, j, k] + cF_arr[ir_r, j, k])
    Sp = _porous_src_df_3d(umag, K_u, cF_u, mu_loc, rho_loc) * vol
    p_src = (P[i - 1, j, k] - P[i, j, k]) * dyj * dzk
    aP0 = De + Dw + Dn + Ds + Dt + Db + Sp + max(Fe, 0.0) + max(-Fw, 0.0) + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0)
    rhs = aE * uE + aW * uW + aN * uN + aS * uS + aT * uT + aB * uB + p_src
    if use_sou == 1:
        rhs += _sou_axis(u[max(i - 2, 0), j, k], u[max(i - 1, 0), j, k], u[i, j, k], u[min(i + 1, Nx), j, k], u[min(i + 2, Nx), j, k], i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1, Fw, Fe, dx, i, True) + _sou_axis(u[i, max(j - 2, 0), k], u[i, max(j - 1, 0), k], u[i, j, k], u[i, min(j + 1, Ny - 1), k], u[i, min(j + 2, Ny - 1), k], j > 1, j > 0 and j < Ny - 1, j < Ny - 2, j > 0 and j < Ny - 1, Fs, Fn, dy, j, False) + _sou_axis(u[i, j, max(k - 2, 0)], u[i, j, max(k - 1, 0)], u[i, j, k], u[i, j, min(k + 1, Nz - 1)], u[i, j, min(k + 2, Nz - 1)], k > 1, k > 0 and k < Nz - 1, k < Nz - 2, k > 0 and k < Nz - 1, Fb, Ft, dz, k, False)
    return (aP0, rhs)


def _v_coeffs_df_3d(u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, use_sou, use_eps):
    jc = min(j, Ny - 1)
    dxi = dx[i]
    dyj = 0.5 * (dy[j - 1] + dy[min(j, Ny - 1)])
    dzk = dz[k]
    vol = dxi * dyj * dzk
    De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb = _v_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field, dx, dy, dz, i, j, k, use_eps)
    vE = v[i + 1, j, k] if i < Nx - 1 else 0.0
    vW = v[i - 1, j, k] if i > 0 else 0.0
    vN = v[i, j + 1, k]
    vS = v[i, j - 1, k]
    vT = v[i, j, k + 1] if k < Nz - 1 else 0.0
    vB = v[i, j, k - 1] if k > 0 else 0.0
    rho_loc = 0.5 * (rho_field[i, j - 1, k] + rho_field[i, j, k])
    mu_loc = 0.5 * (mu_field[i, j - 1, k] + mu_field[i, j, k])
    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)
    aT = Dt + max(-Ft, 0.0)
    aB = Db + max(Fb, 0.0)
    umag = _umag_v_3d(u, v, w, i, j, k, Ny)
    Sp = _porous_src_df_3d(umag, K_arr[i, jc, k], cF_arr[i, jc, k], mu_loc, rho_loc) * vol
    p_src = (P[i, j - 1, k] - P[i, j, k]) * dxi * dzk
    aP0 = De + Dw + Dn + Ds + Dt + Db + Sp + max(Fe, 0.0) + max(-Fw, 0.0) + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0)
    rhs = aE * vE + aW * vW + aN * vN + aS * vS + aT * vT + aB * vB + p_src
    if use_sou == 1:
        rhs += _sou_axis(v[max(i - 2, 0), j, k], v[max(i - 1, 0), j, k], v[i, j, k], v[min(i + 1, Nx - 1), j, k], v[min(i + 2, Nx - 1), j, k], i > 1, i > 0 and i < Nx - 1, i < Nx - 2, i > 0 and i < Nx - 1, Fw, Fe, dx, i, False) + _sou_axis(v[i, max(j - 2, 0), k], v[i, max(j - 1, 0), k], v[i, j, k], v[i, min(j + 1, Ny), k], v[i, min(j + 2, Ny), k], j > 2, j > 1, j + 2 <= Ny, j > 1, Fs, Fn, dy, j, True) + _sou_axis(v[i, j, max(k - 2, 0)], v[i, j, max(k - 1, 0)], v[i, j, k], v[i, j, min(k + 1, Nz - 1)], v[i, j, min(k + 2, Nz - 1)], k > 1, k > 0 and k < Nz - 1, k < Nz - 2, k > 0 and k < Nz - 1, Fb, Ft, dz, k, False)
    return (aP0, rhs)


def _w_coeffs_df_3d(u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, outlet_w_frac, use_sou, use_eps):
    kc = min(k, Nz - 1)
    dxi = dx[i]
    dyj = dy[j]
    dzk = 0.5 * (dz[k - 1] + dz[min(k, Nz - 1)])
    vol = dxi * dyj * dzk
    De, Dw, Dn, Ds, Dt, Db, Fe, Fw_, Fn, Fs, Ft, Fb = _w_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field, dx, dy, dz, i, j, k, outlet_w_frac, use_eps)
    wE = w[i + 1, j, k] if i < Nx - 1 else 0.0
    wW = w[i - 1, j, k] if i > 0 else 0.0
    wN = w[i, j + 1, k] if j < Ny - 1 else 0.0
    wS = w[i, j - 1, k] if j > 0 else 0.0
    wT = w[i, j, k + 1]
    wB = w[i, j, k - 1]
    rho_loc = 0.5 * (rho_field[i, j, k - 1] + rho_field[i, j, k])
    mu_loc = 0.5 * (mu_field[i, j, k - 1] + mu_field[i, j, k])
    aE = De + max(-Fe, 0.0)
    aW = Dw + max(Fw_, 0.0)
    aN = Dn + max(-Fn, 0.0)
    aS = Ds + max(Fs, 0.0)
    aT = Dt + max(-Ft, 0.0)
    aB = Db + max(Fb, 0.0)
    umag = _umag_w_3d(u, v, w, i, j, k, Nz)
    Sp = _porous_src_df_3d(umag, K_arr[i, j, kc], cF_arr[i, j, kc], mu_loc, rho_loc) * vol
    p_src = (P[i, j, k - 1] - P[i, j, k]) * dxi * dyj
    aP0 = De + Dw + Dn + Ds + Dt + Db + Sp + max(Fe, 0.0) + max(-Fw_, 0.0) + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0)
    rhs = aE * wE + aW * wW + aN * wN + aS * wS + aT * wT + aB * wB + p_src
    if use_sou == 1:
        rhs += _sou_axis(w[max(i - 2, 0), j, k], w[max(i - 1, 0), j, k], w[i, j, k], w[min(i + 1, Nx - 1), j, k], w[min(i + 2, Nx - 1), j, k], i > 1, i > 0 and i < Nx - 1, i < Nx - 2, i > 0 and i < Nx - 1, Fw_, Fe, dx, i, False) + _sou_axis(w[i, max(j - 2, 0), k], w[i, max(j - 1, 0), k], w[i, j, k], w[i, min(j + 1, Ny - 1), k], w[i, min(j + 2, Ny - 1), k], j > 1, j > 0 and j < Ny - 1, j < Ny - 2, j > 0 and j < Ny - 1, Fs, Fn, dy, j, False) + _sou_axis(w[i, j, max(k - 2, 0)], w[i, j, max(k - 1, 0)], w[i, j, k], w[i, j, min(k + 1, Nz)], w[i, j, min(k + 2, Nz)], k > 2, k > 1, k + 2 <= Nz, k > 1, Fb, Ft, dz, k, True)
    return (aP0, rhs)


def _mom_res_jit_3d(u, v, w, P, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, outlet_u_frac, outlet_w_frac, use_sou, use_eps):
    nu_ = 0.0
    du_ = 0.0
    for i in range(1, Nx):
        for j in range(Ny):
            for k in range(Nz):
                aP0, rhs = _u_coeffs_df_3d(u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, outlet_u_frac, use_sou, use_eps)
                lhs = aP0 * u[i, j, k]
                nu_ += abs(lhs - rhs)
                du_ += 0.5 * (abs(lhs) + abs(rhs))
    nv_ = 0.0
    dv_ = 0.0
    for i in range(Nx):
        for j in range(1, Ny):
            for k in range(Nz):
                aP0, rhs = _v_coeffs_df_3d(u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, use_sou, use_eps)
                lhs = aP0 * v[i, j, k]
                nv_ += abs(lhs - rhs)
                dv_ += 0.5 * (abs(lhs) + abs(rhs))
    nw_ = 0.0
    dw_ = 0.0
    for i in range(Nx):
        for j in range(Ny):
            for k in range(1, Nz):
                aP0, rhs = _w_coeffs_df_3d(u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz, rho_field, mu_eff_field, mu_field, eps_field, K_arr, cF_arr, outlet_w_frac, use_sou, use_eps)
                lhs = aP0 * w[i, j, k]
                nw_ += abs(lhs - rhs)
                dw_ += 0.5 * (abs(lhs) + abs(rhs))
    return (nu_, du_, nv_, dv_, nw_, dw_)
