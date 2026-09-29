"""3D SIMPLE momentum, continuity and pressure-correction kernels."""
import numpy as np
from numba import njit, prange

from ._kernels_2d import diffusion_conductance
from ._kernels_simple_2d import _sou_axis, _sou_diagonal_bound


@njit(cache=True, inline='always')
def _eps_ratio(value, centre, use_eps):
    if use_eps == 0 or value == centre:
        return 1.0
    return value / centre


@njit(cache=True, inline='always')
def _mass_x_3d(velocity, rho, eps, i, j, k, eps_cv, use_eps=1):
    """The continuity mass-flux density, divided by this momentum CV epsilon."""
    if i == 0 or i == rho.shape[0]:
        return 0.0
    left = rho[i - 1, j, k] * _eps_ratio(eps[i - 1, j, k], eps_cv, use_eps)
    right = rho[i, j, k] * _eps_ratio(eps[i, j, k], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j, k]


@njit(cache=True, inline='always')
def _mass_y_3d(velocity, rho, eps, i, j, k, eps_cv, use_eps=1):
    """The continuity mass-flux density, divided by this momentum CV epsilon."""
    left = rho[i, max(j - 1, 0), k] * _eps_ratio(eps[i, max(j - 1, 0), k], eps_cv, use_eps)
    right = rho[i, min(j, rho.shape[1] - 1), k] * _eps_ratio(eps[i, min(j, rho.shape[1] - 1), k], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j, k]


@njit(cache=True, inline='always')
def _mass_z_3d(velocity, rho, eps, i, j, k, eps_cv, use_eps=1):
    """The continuity mass-flux density, divided by this momentum CV epsilon."""
    if k == 0 or k == rho.shape[2]:
        return 0.0
    left = rho[i, j, k - 1] * _eps_ratio(eps[i, j, k - 1], eps_cv, use_eps)
    right = rho[i, j, k] * _eps_ratio(eps[i, j, k], eps_cv, use_eps)
    return 0.5 * (left + right) * velocity[i, j, k]


@njit(cache=True, inline='always')
def _u_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field,
                    dx, dy, dz, i, j, k, outlet_u_frac, use_eps=1):
    """Shared viscous subfaces and half-cell continuity mass fluxes.

    Axial faces lie at primary cell centres. Transverse faces consist
    of two parallel half-cell strips, each with its own series resistance.
    Epsilon division belongs to this momentum equation, after the shared
    physical flux; ratios preserve the uniform-epsilon cancellation.
    """
    eps_cv = 0.5 * (eps_field[i - 1, j, k] + eps_field[i, j, k]) if use_eps == 1 else 1.0
    wl = 0.5 * dx[i - 1]
    wr = 0.5 * dx[i]
    De = (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps)) * (dy[j] * dz[k]) / dx[i]
    Fe = 0.5 * (_mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps)
                           + _mass_x_3d(u, rho_field, eps_field, i + 1, j, k, eps_cv, use_eps)) * (dy[j] * dz[k])
    Dw = (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps)) * (dy[j] * dz[k]) / dx[i - 1]
    Fw = 0.5 * (_mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps)
                           + _mass_x_3d(u, rho_field, eps_field, i - 1, j, k, eps_cv, use_eps)) * (dy[j] * dz[k])
    if j < rho_field.shape[1] - 1:
        Dn = (wl * diffusion_conductance(
            mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j + 1, k] * _eps_ratio(eps_field[i - 1, j + 1, k], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j + 1, k] * _eps_ratio(eps_field[i, j + 1, k], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j + 1])) * dz[k]
    else:
        Dn = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dy[j]
        Dn *= 1.0 - outlet_u_frac[i, k]
    Fn = (wl * _mass_y_3d(v, rho_field, eps_field, i - 1, j + 1, k, eps_cv, use_eps)
           + wr * _mass_y_3d(v, rho_field, eps_field, i, j + 1, k, eps_cv, use_eps)) * dz[k]
    if j > 0:
        Ds = (wl * diffusion_conductance(
            mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j - 1, k] * _eps_ratio(eps_field[i - 1, j - 1, k], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j - 1])) * dz[k]
    else:
        Ds = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dy[j]
    Fs = (wl * _mass_y_3d(v, rho_field, eps_field, i - 1, j, k, eps_cv, use_eps)
           + wr * _mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dz[k]
    if k < rho_field.shape[2] - 1:
        Dt = (wl * diffusion_conductance(
            mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j, k + 1] * _eps_ratio(eps_field[i - 1, j, k + 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j, k + 1] * _eps_ratio(eps_field[i, j, k + 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k + 1])) * dy[j]
    else:
        Dt = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dz[k]
    Ft = (wl * _mass_z_3d(w, rho_field, eps_field, i - 1, j, k + 1, eps_cv, use_eps)
           + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k + 1, eps_cv, use_eps)) * dy[j]
    if k > 0:
        Db = (wl * diffusion_conductance(
            mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j, k - 1] * _eps_ratio(eps_field[i - 1, j, k - 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k - 1])) * dy[j]
    else:
        Db = 2.0 * (wl * (mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dz[k]
    Fb = (wl * _mass_z_3d(w, rho_field, eps_field, i - 1, j, k, eps_cv, use_eps)
           + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dy[j]
    return De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb


@njit(cache=True, inline='always')
def _v_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field,
                    dx, dy, dz, i, j, k, use_eps=1):
    """Shared viscous subfaces and half-cell continuity mass fluxes.

    Axial faces lie at primary cell centres. Transverse faces consist
    of two parallel half-cell strips, each with its own series resistance.
    Epsilon division belongs to this momentum equation, after the shared
    physical flux; ratios preserve the uniform-epsilon cancellation.
    """
    eps_cv = 0.5 * (eps_field[i, j - 1, k] + eps_field[i, j, k]) if use_eps == 1 else 1.0
    wl = 0.5 * dy[j - 1]
    wr = 0.5 * dy[j]
    if i < rho_field.shape[0] - 1:
        De = (wl * diffusion_conductance(
            mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps),
            mu_eff_field[i + 1, j - 1, k] * _eps_ratio(eps_field[i + 1, j - 1, k], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i + 1, j, k] * _eps_ratio(eps_field[i + 1, j, k], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i + 1])) * dz[k]
    else:
        De = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dx[i]
    Fe = (wl * _mass_x_3d(u, rho_field, eps_field, i + 1, j - 1, k, eps_cv, use_eps)
           + wr * _mass_x_3d(u, rho_field, eps_field, i + 1, j, k, eps_cv, use_eps)) * dz[k]
    if i > 0:
        Dw = (wl * diffusion_conductance(
            mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j - 1, k] * _eps_ratio(eps_field[i - 1, j - 1, k], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i - 1])) * dz[k]
    else:
        Dw = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dz[k] / dx[i]
    Fw = (wl * _mass_x_3d(u, rho_field, eps_field, i, j - 1, k, eps_cv, use_eps)
           + wr * _mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dz[k]
    Dn = (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps)) * (dx[i] * dz[k]) / dy[j]
    Fn = 0.5 * (_mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps)
                           + _mass_y_3d(v, rho_field, eps_field, i, j + 1, k, eps_cv, use_eps)) * (dx[i] * dz[k])
    Ds = (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps)) * (dx[i] * dz[k]) / dy[j - 1]
    Fs = 0.5 * (_mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps)
                           + _mass_y_3d(v, rho_field, eps_field, i, j - 1, k, eps_cv, use_eps)) * (dx[i] * dz[k])
    if k < rho_field.shape[2] - 1:
        Dt = (wl * diffusion_conductance(
            mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps),
            mu_eff_field[i, j - 1, k + 1] * _eps_ratio(eps_field[i, j - 1, k + 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j, k + 1] * _eps_ratio(eps_field[i, j, k + 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k + 1])) * dx[i]
    else:
        Dt = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dz[k]
    Ft = (wl * _mass_z_3d(w, rho_field, eps_field, i, j - 1, k + 1, eps_cv, use_eps)
           + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k + 1, eps_cv, use_eps)) * dx[i]
    if k > 0:
        Db = (wl * diffusion_conductance(
            mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps),
            mu_eff_field[i, j - 1, k - 1] * _eps_ratio(eps_field[i, j - 1, k - 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps),
            0.5 * dz[k], 0.5 * dz[k - 1])) * dx[i]
    else:
        Db = 2.0 * (wl * (mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dz[k]
    Fb = (wl * _mass_z_3d(w, rho_field, eps_field, i, j - 1, k, eps_cv, use_eps)
           + wr * _mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dx[i]
    return De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb


@njit(cache=True, inline='always')
def _w_transport_3d(u, v, w, rho_field, mu_eff_field, eps_field,
                    dx, dy, dz, i, j, k, outlet_w_frac, use_eps=1):
    """Shared viscous subfaces and half-cell continuity mass fluxes.

    Axial faces lie at primary cell centres. Transverse faces consist
    of two parallel half-cell strips, each with its own series resistance.
    Epsilon division belongs to this momentum equation, after the shared
    physical flux; ratios preserve the uniform-epsilon cancellation.
    """
    eps_cv = 0.5 * (eps_field[i, j, k - 1] + eps_field[i, j, k]) if use_eps == 1 else 1.0
    wl = 0.5 * dz[k - 1]
    wr = 0.5 * dz[k]
    if i < rho_field.shape[0] - 1:
        De = (wl * diffusion_conductance(
            mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps),
            mu_eff_field[i + 1, j, k - 1] * _eps_ratio(eps_field[i + 1, j, k - 1], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i + 1, j, k] * _eps_ratio(eps_field[i + 1, j, k], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i + 1])) * dy[j]
    else:
        De = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dx[i]
    Fe = (wl * _mass_x_3d(u, rho_field, eps_field, i + 1, j, k - 1, eps_cv, use_eps)
           + wr * _mass_x_3d(u, rho_field, eps_field, i + 1, j, k, eps_cv, use_eps)) * dy[j]
    if i > 0:
        Dw = (wl * diffusion_conductance(
            mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps),
            mu_eff_field[i - 1, j, k - 1] * _eps_ratio(eps_field[i - 1, j, k - 1], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i - 1, j, k] * _eps_ratio(eps_field[i - 1, j, k], eps_cv, use_eps),
            0.5 * dx[i], 0.5 * dx[i - 1])) * dy[j]
    else:
        Dw = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dy[j] / dx[i]
    Fw = (wl * _mass_x_3d(u, rho_field, eps_field, i, j, k - 1, eps_cv, use_eps)
           + wr * _mass_x_3d(u, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dy[j]
    if j < rho_field.shape[1] - 1:
        Dn = (wl * diffusion_conductance(
            mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps),
            mu_eff_field[i, j + 1, k - 1] * _eps_ratio(eps_field[i, j + 1, k - 1], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j + 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j + 1, k] * _eps_ratio(eps_field[i, j + 1, k], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j + 1])) * dx[i]
    else:
        Dn = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dy[j]
        Dn *= 1.0 - outlet_w_frac[i, k]
    Fn = (wl * _mass_y_3d(v, rho_field, eps_field, i, j + 1, k - 1, eps_cv, use_eps)
           + wr * _mass_y_3d(v, rho_field, eps_field, i, j + 1, k, eps_cv, use_eps)) * dx[i]
    if j > 0:
        Ds = (wl * diffusion_conductance(
            mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps),
            mu_eff_field[i, j - 1, k - 1] * _eps_ratio(eps_field[i, j - 1, k - 1], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j - 1])
            + wr * diffusion_conductance(
            mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps),
            mu_eff_field[i, j - 1, k] * _eps_ratio(eps_field[i, j - 1, k], eps_cv, use_eps),
            0.5 * dy[j], 0.5 * dy[j - 1])) * dx[i]
    else:
        Ds = 2.0 * (wl * (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps))
                      + wr * (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps))) * dx[i] / dy[j]
    Fs = (wl * _mass_y_3d(v, rho_field, eps_field, i, j, k - 1, eps_cv, use_eps)
           + wr * _mass_y_3d(v, rho_field, eps_field, i, j, k, eps_cv, use_eps)) * dx[i]
    Dt = (mu_eff_field[i, j, k] * _eps_ratio(eps_field[i, j, k], eps_cv, use_eps)) * (dx[i] * dy[j]) / dz[k]
    Ft = 0.5 * (_mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps)
                           + _mass_z_3d(w, rho_field, eps_field, i, j, k + 1, eps_cv, use_eps)) * (dx[i] * dy[j])
    Db = (mu_eff_field[i, j, k - 1] * _eps_ratio(eps_field[i, j, k - 1], eps_cv, use_eps)) * (dx[i] * dy[j]) / dz[k - 1]
    Fb = 0.5 * (_mass_z_3d(w, rho_field, eps_field, i, j, k, eps_cv, use_eps)
                           + _mass_z_3d(w, rho_field, eps_field, i, j, k - 1, eps_cv, use_eps)) * (dx[i] * dy[j])
    return De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb


# ===================================================================
#  Numba kernels
# ===================================================================

# ── Face-averaged velocity magnitudes (needed for the Forchheimer source) ──

@njit(cache=True, fastmath=True)
def _umag_u_3d(u, v, w, i, j, k, Nx, ):
    """Speed at u-face (i, j, k): |U| = sqrt(u² + <v>² + <w>²)."""
    il = max(i - 1, 0); ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j, k] + v[ir, j, k]
                 + v[il, j + 1, k] + v[ir, j + 1, k])
    wa = 0.25 * (w[il, j, k] + w[ir, j, k]
                 + w[il, j, k + 1] + w[ir, j, k + 1])
    return np.sqrt(u[i, j, k] ** 2 + va ** 2 + wa ** 2)


@njit(cache=True, fastmath=True)
def _umag_v_3d(u, v, w, i, j, k, Ny):
    """Speed at v-face (i, j, k)."""
    jb = max(j - 1, 0); jt = min(j, Ny - 1)
    ua = 0.25 * (u[i, jb, k] + u[i + 1, jb, k]
                 + u[i, jt, k] + u[i + 1, jt, k])
    wa = 0.25 * (w[i, jb, k] + w[i, jt, k]
                 + w[i, jb, k + 1] + w[i, jt, k + 1])
    return np.sqrt(ua ** 2 + v[i, j, k] ** 2 + wa ** 2)


@njit(cache=True, fastmath=True)
def _umag_w_3d(u, v, w, i, j, k, Nz):
    """Speed at w-face (i, j, k)."""
    kb = max(k - 1, 0); kt = min(k, Nz - 1)
    ua = 0.25 * (u[i, j, kb] + u[i + 1, j, kb]
                 + u[i, j, kt] + u[i + 1, j, kt])
    va = 0.25 * (v[i, j, kb] + v[i, j + 1, kb]
                 + v[i, j, kt] + v[i, j + 1, kt])
    return np.sqrt(ua ** 2 + va ** 2 + w[i, j, k] ** 2)


@njit(cache=True, fastmath=True)
def _porous_src_df_3d(umag, K, cF, mu, rho):
    """Linearised porous resistance [kg/(m³ s)] — D-F closure.

    Sp * u = (μ/K) * u + ρ * c_F * |U| * u.
    Matches `_porous_src_df` in 2D simple_solver.py.
    """
    if umag < 1e-10:
        return mu / K
    return mu / K + rho * cF * umag


# ── SOU deferred correction, shared axis kernel (R4, opt-in) ───────
# openspec solver-efficiency-r1-r4. Minmod second-order-upwind deferred
# correction in the 2D N2 telescoping convention (lo-face limiter × Flo,
# hi-face limiter × Fhi — the SAME face fluxes the first-order a_nb use).
# One kernel serves all 9 (component × axis) combinations; the call sites
# only gather the 5-point stencil (clamped indices) and the boundary flags
# that mirror simple_solver.py's _sou_corr_* index conditions. Enabled per
# solve via `use_sou_momentum` (default False → term is exactly 0.0).


# ── SIMPLE Step 1: u-momentum (x-direction), 7-point first-order upwind ──

@njit(cache=True, fastmath=True, inline='always')
def _u_cell_df_3d(u, v, w, P, d_u, i, j, k,
                  Nx, Ny, Nz, dx, dy, dz,
                  rho_field, mu_eff_field, mu_field, eps_field,
                  K_arr, cF_arr, outlet_u_frac, alpha_u, use_sou,
                  use_eps):
    """One u-face Gauss-Seidel update, shared by serial and parallel sweeps.

    Transport uses the epsilon-divided VANS convention documented in the
    2D kernels. use_eps=0 omits ratios for uniform porosity; use_sou=1 adds
    physical-distance deferred reconstruction. The deferred diagonal
    compensation stabilizes iteration and cancels at the fixed point.
    """
    # Volume + face areas
    dxi = 0.5 * (dx[i - 1] + dx[min(i, Nx - 1)])
    dyj = dy[j]
    dzk = dz[k]
    vol = dxi * dyj * dzk

    il_r = i - 1; ir_r = i
    (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb) = _u_transport_3d(
        u, v, w, rho_field, mu_eff_field, eps_field,
        dx, dy, dz, i, j, k, outlet_u_frac, use_eps)
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

    # Brinkman / Forchheimer drag (linearised)
    umag = _umag_u_3d(u, v, w, i, j, k, Nx, )
    # Extend the existing row convention: average adjacent x cells at u;
    # v/w retain their downstream j/k samples. This is a discrete sampling
    # convention, not a qualification of strongly graded TPMS physics.
    K_u = 0.5 * (K_arr[il_r, j, k] + K_arr[ir_r, j, k])
    cF_u = 0.5 * (cF_arr[il_r, j, k] + cF_arr[ir_r, j, k])
    Sp = _porous_src_df_3d(umag, K_u, cF_u,
                             mu_loc, rho_loc) * vol

    # Pressure gradient source
    p_src = (P[i - 1, j, k] - P[i, j, k]) * dyj * dzk

    aP0 = (De + Dw + Dn + Ds + Dt + Db + Sp
           + max(Fe, 0.0) + max(-Fw, 0.0)
           + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0))
    rhs = (aE * uE + aW * uW + aN * uN + aS * uS
           + aT * uT + aB * uB + p_src)
    # R4: minmod SOU deferred correction (flags mirror 2D _sou_corr_u_x/_y).
    # Added via a guarded += so the use_sou=0 rhs expression tree is unchanged
    # (fastmath would re-associate an inline `+ sou` and break bit-identity).
    if use_sou == 1:
        rhs += (_sou_axis(u[max(i - 2, 0), j, k], u[max(i - 1, 0), j, k],
                          u[i, j, k], u[min(i + 1, Nx), j, k],
                          u[min(i + 2, Nx), j, k],
                          i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1,
                          Fw, Fe, dx, i, True)
                + _sou_axis(u[i, max(j - 2, 0), k], u[i, max(j - 1, 0), k],
                            u[i, j, k], u[i, min(j + 1, Ny - 1), k],
                            u[i, min(j + 2, Ny - 1), k],
                            j > 1, j > 0 and j < Ny - 1, j < Ny - 2,
                            j > 0 and j < Ny - 1, Fs, Fn, dy, j, False)
                + _sou_axis(u[i, j, max(k - 2, 0)], u[i, j, max(k - 1, 0)],
                            u[i, j, k], u[i, j, min(k + 1, Nz - 1)],
                            u[i, j, min(k + 2, Nz - 1)],
                            k > 1, k > 0 and k < Nz - 1, k < Nz - 2,
                            k > 0 and k < Nz - 1, Fb, Ft, dz, k, False))
    # Deferred diagonal compensation stabilizes a mass-deficit iterate.
    # It cancels at the fixed point: this is no physical source.
    compensation = max(-(Fe - Fw + Fn - Fs + Ft - Fb), 0.0)
    if use_sou == 1:
        compensation += (_sou_diagonal_bound(
            u[i - 1, j, k], u[i, j, k], u[i + 1, j, k],
            i > 1, i > 1 and i + 1 < Nx, Fw, Fe, dx, i, True)
            + _sou_diagonal_bound(
            u[i, max(j - 1, 0), k], u[i, j, k], u[i, min(j + 1, Ny - 1), k],
            j > 0 and j < Ny - 1, j > 0 and j < Ny - 1, Fs, Fn, dy, j, False)
            + _sou_diagonal_bound(
            u[i, j, max(k - 1, 0)], u[i, j, k], u[i, j, min(k + 1, Nz - 1)],
            k > 0 and k < Nz - 1, k > 0 and k < Nz - 1, Fb, Ft, dz, k, False))
    aP_predict = aP0 + compensation
    rhs += compensation * u[i, j, k]
    aP = aP_predict / alpha_u
    rhs += (1.0 - alpha_u) / alpha_u * aP_predict * u[i, j, k]

    u[i, j, k] = rhs / aP
    d_u[i, j, k] = dyj * dzk / aP_predict


@njit(cache=True, fastmath=True)
def _sweep_u_jit_df_3d(u, v, w, P, d_u,
                        Nx, Ny, Nz,
                     dx, dy, dz,
                        rho_field, mu_eff_field, mu_field, eps_field,
                        K_arr, cF_arr,
                        outlet_u_frac,
                        alpha_u, n_sweeps, use_sou, use_eps):
    """Solve the x-momentum equation on the u-staggered face.

    u : (Nx+1, Ny, Nz) — updated in place.
    K_arr, cF_arr : (Nx, Ny, Nz) — local interstitial D-F coefficients.
    Internal walls (i=0, i=Nx) are no-slip (u=0).
    Cell body shared with the parallel variant via `_u_cell_df_3d`.
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                for k in range(Nz):
                    _u_cell_df_3d(u, v, w, P, d_u, i, j, k,
                                  Nx, Ny, Nz, dx, dy, dz,
                                  rho_field, mu_eff_field, mu_field, eps_field,
                                  K_arr, cF_arr, outlet_u_frac,
                                  alpha_u, use_sou, use_eps)

    # No-slip BC at x-walls
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0


# Parallel red-black Gauss-Seidel variant of `_sweep_u_jit_df_3d`. Dispatched
# when grid ≥ `_PARALLEL_CELL_THRESHOLD`. Same cell body (`_u_cell_df_3d`);
# the triple loop is split into two colour passes with `(i+j+k) % 2 == color`
# filtering — each pass writes only same-colour cells, reads only
# opposite-colour neighbours, so `prange` on i is race-free.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_u_jit_df_3d_parallel(u, v, w, P, d_u,
                                 Nx, Ny, Nz,
                              dx, dy, dz,
                                 rho_field, mu_eff_field, mu_field, eps_field,
                                 K_arr, cF_arr,
                                 outlet_u_frac,
                                 alpha_u, n_sweeps, use_sou, use_eps):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(1, Nx):
                for j in range(Ny):
                    for k in range(Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        _u_cell_df_3d(u, v, w, P, d_u, i, j, k,
                                      Nx, Ny, Nz, dx, dy, dz,
                                      rho_field, mu_eff_field, mu_field, eps_field,
                                      K_arr, cF_arr, outlet_u_frac, alpha_u, use_sou, use_eps)
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0


# ── SIMPLE Step 2: v-momentum (y-direction) ────────────────────────

@njit(cache=True, fastmath=True, inline='always')
def _v_cell_df_3d(u, v, w, P, d_v, i, j, k,
                  Nx, Ny, Nz, dx, dy, dz,
                  rho_field, mu_eff_field, mu_field, eps_field,
                  K_arr, cF_arr, alpha_u, use_sou,
                  use_eps):
    """One Gauss-Seidel update of the v-face (i, j, k) — shared cell body
    for the serial and parallel sweeps (B6 dedup). M2b: guarded VANS ε-ratio
    factors — see _u_cell_df_3d docstring; v-node on the y-interface, so N/S
    flux faces are cell centres, E/W/T/B the 4-cell corners."""
    jc = min(j, Ny - 1)
    dxi = dx[i]
    dyj = 0.5 * (dy[j - 1] + dy[min(j, Ny - 1)])
    dzk = dz[k]
    vol = dxi * dyj * dzk

    (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb) = _v_transport_3d(
        u, v, w, rho_field, mu_eff_field, eps_field,
        dx, dy, dz, i, j, k, use_eps)
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
    Sp = _porous_src_df_3d(umag, K_arr[i, jc, k], cF_arr[i, jc, k],
                             mu_loc, rho_loc) * vol

    p_src = (P[i, j - 1, k] - P[i, j, k]) * dxi * dzk

    aP0 = (De + Dw + Dn + Ds + Dt + Db + Sp
           + max(Fe, 0.0) + max(-Fw, 0.0)
           + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0))
    rhs = (aE * vE + aW * vW + aN * vN + aS * vS
           + aT * vT + aB * vB + p_src)
    # R4: minmod SOU deferred correction (flags mirror 2D _sou_corr_v_x/_y).
    # Guarded += keeps the use_sou=0 rhs expression tree unchanged (fastmath).
    if use_sou == 1:
        rhs += (_sou_axis(v[max(i - 2, 0), j, k], v[max(i - 1, 0), j, k],
                          v[i, j, k], v[min(i + 1, Nx - 1), j, k],
                          v[min(i + 2, Nx - 1), j, k],
                          i > 1, i > 0 and i < Nx - 1, i < Nx - 2,
                          i > 0 and i < Nx - 1, Fw, Fe, dx, i, False)
                + _sou_axis(v[i, max(j - 2, 0), k], v[i, max(j - 1, 0), k],
                            v[i, j, k], v[i, min(j + 1, Ny), k],
                            v[i, min(j + 2, Ny), k],
                            j > 2, j > 1, j + 2 <= Ny, j > 1,
                            Fs, Fn, dy, j, True)
                + _sou_axis(v[i, j, max(k - 2, 0)], v[i, j, max(k - 1, 0)],
                            v[i, j, k], v[i, j, min(k + 1, Nz - 1)],
                            v[i, j, min(k + 2, Nz - 1)],
                            k > 1, k > 0 and k < Nz - 1, k < Nz - 2,
                            k > 0 and k < Nz - 1, Fb, Ft, dz, k, False))
    # Deferred diagonal compensation stabilizes a mass-deficit iterate.
    # It cancels at the fixed point: this is no physical source.
    compensation = max(-(Fe - Fw + Fn - Fs + Ft - Fb), 0.0)
    if use_sou == 1:
        compensation += (_sou_diagonal_bound(
            v[max(i - 1, 0), j, k], v[i, j, k], v[min(i + 1, Nx - 1), j, k],
            i > 0 and i < Nx - 1, i > 0 and i < Nx - 1, Fw, Fe, dx, i, False)
            + _sou_diagonal_bound(
            v[i, j - 1, k], v[i, j, k], v[i, j + 1, k],
            j > 1, j > 1, Fs, Fn, dy, j, True)
            + _sou_diagonal_bound(
            v[i, j, max(k - 1, 0)], v[i, j, k], v[i, j, min(k + 1, Nz - 1)],
            k > 0 and k < Nz - 1, k > 0 and k < Nz - 1, Fb, Ft, dz, k, False))
    aP_predict = aP0 + compensation
    rhs += compensation * v[i, j, k]
    aP = aP_predict / alpha_u
    rhs += (1.0 - alpha_u) / alpha_u * aP_predict * v[i, j, k]

    v[i, j, k] = rhs / aP
    d_v[i, j, k] = dxi * dzk / aP_predict


@njit(cache=True, fastmath=True, inline='always')
def _v_bc_3d(u, v, w, v_inlet_field, rho_field, eps_field, outlet_mask_ij,
             Nx, Ny, Nz, dx, dy, dz):
    """Close every open outlet CV: Fn = Fs + Fw - Fe + Fb - Ft."""
    j = Ny - 1
    for i in range(Nx):
        for k in range(Nz):
            v[i, 0, k] = v_inlet_field[i, k]
            if outlet_mask_ij[i, k]:
                er = rho_field[i, j, k] * eps_field[i, j, k]
                ers = (.5 * (rho_field[i, j - 1, k] * eps_field[i, j - 1, k] + er)
                       if j > 0 else er)
                erw = (.5 * (rho_field[i - 1, j, k] * eps_field[i - 1, j, k] + er)
                       if i > 0 else er)
                ere = (.5 * (er + rho_field[i + 1, j, k] * eps_field[i + 1, j, k])
                       if i < Nx - 1 else er)
                erb = (.5 * (rho_field[i, j, k - 1] * eps_field[i, j, k - 1] + er)
                       if k > 0 else er)
                ert = (.5 * (er + rho_field[i, j, k + 1] * eps_field[i, j, k + 1])
                       if k < Nz - 1 else er)
                # Divide six-face continuity by the outlet area dx[i]*dz[k].
                cross_x = (ere * u[i + 1, j, k] - erw * u[i, j, k]) * dy[j] / dx[i]
                cross_z = (ert * w[i, j, k + 1] - erb * w[i, j, k]) * dy[j] / dz[k]
                v[i, Ny, k] = (ers * v[i, j, k] - cross_x - cross_z) / er
            else:
                v[i, Ny, k] = 0.0


@njit(cache=True, fastmath=True)
def _sweep_v_jit_df_3d(u, v, w, P, d_v,
                        v_inlet_field,
                        Nx, Ny, Nz,
                     dx, dy, dz,
                        rho_field, eps_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        alpha_u, n_sweeps, use_sou, use_eps, outlet_mask_ij):
    """Solve the y-momentum equation on the v-staggered face.

    Inlet BC applied at j=0 (v[i, 0, k] = v_inlet_field[i, k]) — accepts
    non-uniform inlet profile for manifold mal-distribution modeling (P2).
    Outlet j=Ny closes the reference CV's full rho*eps face balance.
    Cell body shared with the parallel variant via `_v_cell_df_3d`.
    """
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                for k in range(Nz):
                    _v_cell_df_3d(u, v, w, P, d_v, i, j, k,
                                  Nx, Ny, Nz, dx, dy, dz,
                                  rho_field, mu_eff_field, mu_field, eps_field,
                                  K_arr, cF_arr, alpha_u, use_sou, use_eps)

    # Apply BCs
    _v_bc_3d(u, v, w, v_inlet_field, rho_field, eps_field, outlet_mask_ij,
             Nx, Ny, Nz, dx, dy, dz)


# Parallel red-black Gauss-Seidel variant of `_sweep_v_jit_df_3d`.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_v_jit_df_3d_parallel(u, v, w, P, d_v,
                                 v_inlet_field,
                                 Nx, Ny, Nz,
                              dx, dy, dz,
                                 rho_field, eps_field, mu_eff_field, mu_field,
                                 K_arr, cF_arr,
                                 alpha_u, n_sweeps, use_sou, use_eps, outlet_mask_ij):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(Nx):
                for j in range(1, Ny):
                    for k in range(Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        _v_cell_df_3d(u, v, w, P, d_v, i, j, k,
                                      Nx, Ny, Nz, dx, dy, dz,
                                      rho_field, mu_eff_field, mu_field, eps_field,
                                      K_arr, cF_arr, alpha_u, use_sou, use_eps)
    _v_bc_3d(u, v, w, v_inlet_field, rho_field, eps_field, outlet_mask_ij,
             Nx, Ny, Nz, dx, dy, dz)


# ── SIMPLE Step 3: w-momentum (z-direction) — new in 3D ────────────

@njit(cache=True, fastmath=True, inline='always')
def _w_cell_df_3d(u, v, w, P, d_w, i, j, k,
                  Nx, Ny, Nz, dx, dy, dz,
                  rho_field, mu_eff_field, mu_field, eps_field,
                  K_arr, cF_arr, outlet_w_frac, alpha_u, use_sou,
                  use_eps):
    """One Gauss-Seidel update of the w-face (i, j, k) — shared cell body
    for the serial and parallel sweeps (B6 dedup). M2b: guarded VANS ε-ratio
    factors — see _u_cell_df_3d docstring; w-node on the z-interface, so T/B
    flux faces are cell centres, E/W/N/S the 4-cell corners."""
    kc = min(k, Nz - 1)
    dxi = dx[i]
    dyj = dy[j]
    dzk = 0.5 * (dz[k - 1] + dz[min(k, Nz - 1)])
    vol = dxi * dyj * dzk

    (De, Dw, Dn, Ds, Dt, Db, Fe, Fw_, Fn, Fs, Ft, Fb) = _w_transport_3d(
        u, v, w, rho_field, mu_eff_field, eps_field,
        dx, dy, dz, i, j, k, outlet_w_frac, use_eps)
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
    Sp = _porous_src_df_3d(umag, K_arr[i, j, kc], cF_arr[i, j, kc],
                             mu_loc, rho_loc) * vol

    p_src = (P[i, j, k - 1] - P[i, j, k]) * dxi * dyj

    aP0 = (De + Dw + Dn + Ds + Dt + Db + Sp
           + max(Fe, 0.0) + max(-Fw_, 0.0)
           + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0))
    rhs = (aE * wE + aW * wW + aN * wN + aS * wS
           + aT * wT + aB * wB + p_src)
    # R4: minmod SOU deferred correction (cross axes mirror v; parallel = z).
    # Guarded += keeps the use_sou=0 rhs expression tree unchanged (fastmath).
    if use_sou == 1:
        rhs += (_sou_axis(w[max(i - 2, 0), j, k], w[max(i - 1, 0), j, k],
                          w[i, j, k], w[min(i + 1, Nx - 1), j, k],
                          w[min(i + 2, Nx - 1), j, k],
                          i > 1, i > 0 and i < Nx - 1, i < Nx - 2,
                          i > 0 and i < Nx - 1, Fw_, Fe, dx, i, False)
                + _sou_axis(w[i, max(j - 2, 0), k], w[i, max(j - 1, 0), k],
                            w[i, j, k], w[i, min(j + 1, Ny - 1), k],
                            w[i, min(j + 2, Ny - 1), k],
                            j > 1, j > 0 and j < Ny - 1, j < Ny - 2,
                            j > 0 and j < Ny - 1, Fs, Fn, dy, j, False)
                + _sou_axis(w[i, j, max(k - 2, 0)], w[i, j, max(k - 1, 0)],
                            w[i, j, k], w[i, j, min(k + 1, Nz)],
                            w[i, j, min(k + 2, Nz)],
                            k > 2, k > 1, k + 2 <= Nz, k > 1,
                            Fb, Ft, dz, k, True))
    # Deferred diagonal compensation stabilizes a mass-deficit iterate.
    # It cancels at the fixed point: this is no physical source.
    compensation = max(-(Fe - Fw_ + Fn - Fs + Ft - Fb), 0.0)
    if use_sou == 1:
        compensation += (_sou_diagonal_bound(
            w[max(i - 1, 0), j, k], w[i, j, k], w[min(i + 1, Nx - 1), j, k],
            i > 0 and i < Nx - 1, i > 0 and i < Nx - 1, Fw_, Fe, dx, i, False)
            + _sou_diagonal_bound(
            w[i, max(j - 1, 0), k], w[i, j, k], w[i, min(j + 1, Ny - 1), k],
            j > 0 and j < Ny - 1, j > 0 and j < Ny - 1, Fs, Fn, dy, j, False)
            + _sou_diagonal_bound(
            w[i, j, k - 1], w[i, j, k], w[i, j, k + 1],
            k > 1, k > 1, Fb, Ft, dz, k, True))
    aP_predict = aP0 + compensation
    rhs += compensation * w[i, j, k]
    aP = aP_predict / alpha_u
    rhs += (1.0 - alpha_u) / alpha_u * aP_predict * w[i, j, k]

    w[i, j, k] = rhs / aP
    d_w[i, j, k] = dxi * dyj / aP_predict


@njit(cache=True, fastmath=True)
def _sweep_w_jit_df_3d(u, v, w, P, d_w,
                        Nx, Ny, Nz,
                     dx, dy, dz,
                        rho_field, mu_eff_field, mu_field, eps_field,
                        K_arr, cF_arr,
                        outlet_w_frac,
                        alpha_u, n_sweeps, use_sou, use_eps):
    """Solve the z-momentum equation on the w-staggered face.

    Top/bottom z-walls (k=0, k=Nz) are no-slip by default (w=0).
    Cell body shared with the parallel variant via `_w_cell_df_3d`.
    """
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(Ny):
                for k in range(1, Nz):
                    _w_cell_df_3d(u, v, w, P, d_w, i, j, k,
                                  Nx, Ny, Nz, dx, dy, dz,
                                  rho_field, mu_eff_field, mu_field, eps_field,
                                  K_arr, cF_arr, outlet_w_frac,
                                  alpha_u, use_sou, use_eps)

    # No-slip at z-walls
    for i in range(Nx):
        for j in range(Ny):
            w[i, j, 0] = 0.0
            w[i, j, Nz] = 0.0


# Parallel red-black Gauss-Seidel variant of `_sweep_w_jit_df_3d`.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_w_jit_df_3d_parallel(u, v, w, P, d_w,
                                 Nx, Ny, Nz,
                              dx, dy, dz,
                                 rho_field, mu_eff_field, mu_field, eps_field,
                                 K_arr, cF_arr,
                                 outlet_w_frac,
                                 alpha_u, n_sweeps, use_sou, use_eps):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(Nx):
                for j in range(Ny):
                    for k in range(1, Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        _w_cell_df_3d(u, v, w, P, d_w, i, j, k,
                                      Nx, Ny, Nz, dx, dy, dz,
                                      rho_field, mu_eff_field, mu_field, eps_field,
                                      K_arr, cF_arr, outlet_w_frac, alpha_u, use_sou, use_eps)
    for i in range(Nx):
        for j in range(Ny):
            w[i, j, 0] = 0.0
            w[i, j, Nz] = 0.0


# ── SIMPLE Step 4: pressure-Poisson assembly (7-point) ────────────

@njit(cache=True, fastmath=True)
def _assemble_pp_3d(data, rhs, u, v, w, d_u, d_v, d_w,
                     Nx, Ny, Nz,
                     dx, dy, dz,
                     rho_field,
                     cell_base, cell_kind):
    """Build the CSR data and rhs for the 7-point pressure-correction solve.

    cell_kind[k]:
        0 — interior / boundary cell (7-slot row: diag + E/W/N/S/T/B)
        1 — outlet reference (diag=1, Pp=0 pinned)
    cell_base[k] : offset of this cell's data in the CSR array.
    """
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                flat = (i * Ny + j) * Nz + k
                base = cell_base[flat]

                if cell_kind[flat] == 1:
                    data[base] = 1.0
                    rhs[flat] = 0.0
                    continue

                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]

                if i < Nx - 1:
                    rho_e = 0.5 * (rho_field[i, j, k] + rho_field[i + 1, j, k])
                else:
                    rho_e = rho_field[i, j, k]
                if i > 0:
                    rho_w = 0.5 * (rho_field[i - 1, j, k] + rho_field[i, j, k])
                else:
                    rho_w = rho_field[i, j, k]
                if j < Ny - 1:
                    rho_n = 0.5 * (rho_field[i, j, k] + rho_field[i, j + 1, k])
                else:
                    rho_n = rho_field[i, j, k]
                if j > 0:
                    rho_s = 0.5 * (rho_field[i, j - 1, k] + rho_field[i, j, k])
                else:
                    rho_s = rho_field[i, j, k]
                if k < Nz - 1:
                    rho_t = 0.5 * (rho_field[i, j, k] + rho_field[i, j, k + 1])
                else:
                    rho_t = rho_field[i, j, k]
                if k > 0:
                    rho_b = 0.5 * (rho_field[i, j, k - 1] + rho_field[i, j, k])
                else:
                    rho_b = rho_field[i, j, k]

                Ae = dyj * dzk
                Ax = dxi * dzk
                Az = dxi * dyj

                aE = rho_e * d_u[i + 1, j, k] * Ae if i < Nx - 1 else 0.0
                aW = rho_w * d_u[i, j, k] * Ae if i > 0 else 0.0
                aN = rho_n * d_v[i, j + 1, k] * Ax if j < Ny - 1 else 0.0
                aS = rho_s * d_v[i, j, k] * Ax if j > 0 else 0.0
                aT = rho_t * d_w[i, j, k + 1] * Az if k < Nz - 1 else 0.0
                aB = rho_b * d_w[i, j, k] * Az if k > 0 else 0.0
                aP = aE + aW + aN + aS + aT + aB

                if aP < 1e-30:
                    data[base] = 1.0
                    for s in range(1, 7):
                        data[base + s] = 0.0
                    rhs[flat] = 0.0
                    continue

                data[base] = aP
                data[base + 1] = -aE
                data[base + 2] = -aW
                data[base + 3] = -aN
                data[base + 4] = -aS
                data[base + 5] = -aT
                data[base + 6] = -aB

                rhs[flat] = -(
                    (rho_e * u[i + 1, j, k] - rho_w * u[i, j, k]) * Ae
                    + (rho_n * v[i, j + 1, k] - rho_s * v[i, j, k]) * Ax
                    + (rho_t * w[i, j, k + 1] - rho_b * w[i, j, k]) * Az
                )


# ── SIMPLE Step 5: pressure / velocity correction ─────────────────

@njit(cache=True, fastmath=True)
def _correct_jit_3d(u, v, w, P, Pp, d_u, d_v, d_w,
                     v_inlet_field,
                     Nx, Ny, Nz, alpha_p, rho_field, eps_field,
                     outlet_mask_ij, dx, dy, dz):
    """Apply pressure + face-velocity correction and re-enforce BCs."""
    # Pressure correction (skip pinned outlet cells)
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                if j == Ny - 1 and outlet_mask_ij[i, k]:
                    continue
                P[i, j, k] += alpha_p * Pp[i, j, k]

    # u correction
    for i in range(1, Nx):
        for j in range(Ny):
            for k in range(Nz):
                u[i, j, k] += d_u[i, j, k] * (Pp[i - 1, j, k] - Pp[i, j, k])

    # v correction
    for i in range(Nx):
        for j in range(1, Ny):
            for k in range(Nz):
                v[i, j, k] += d_v[i, j, k] * (Pp[i, j - 1, k] - Pp[i, j, k])

    # w correction
    for i in range(Nx):
        for j in range(Ny):
            for k in range(1, Nz):
                w[i, j, k] += d_w[i, j, k] * (Pp[i, j, k - 1] - Pp[i, j, k])

    # Re-apply BCs
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0
    for i in range(Nx):
        for j in range(Ny):
            w[i, j, 0] = 0.0
            w[i, j, Nz] = 0.0
    _v_bc_3d(u, v, w, v_inlet_field, rho_field, eps_field, outlet_mask_ij,
             Nx, Ny, Nz, dx, dy, dz)


# ── SIMPLE Step 6: mass residual ──────────────────────────────────

@njit(cache=True, fastmath=True)
def _mass_res_jit_3d(u, v, w, Nx, Ny, Nz, dx, dy, dz, rho_field):
    """Max PER-CELL divergence |div(rho.u)| over all cells.

    NOT the same quantity as the 2D `_mass_res_jit` (`_kernels_simple_2d.py`),
    which returns a PLANE-INTEGRATED flux defect. This metric includes every
    cell, including pressure-reference CVs locally closed by `_v_bc_3d`.
    It measures the pp subproblem; it is not a momentum certificate and must
    not replace F2. No global outlet rescaling is applied.

    (CORRECTION 2026-07-12, codex review: an earlier revision explained the above
    by saying the 2D rescale "zeroes the 2D metric, which is why 2D's tol fires".
    That mechanism claim is FALSE — the rescale runs only AFTER the exit decision,
    never inside the loop (`simple_solver.py:897` vs `:900`). The real reason 2D
    reaches tol is simply that its metric is weaker. The no-port verdict stands.)
    """
    r_max = 0.0
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]
                if i < Nx - 1:
                    rho_e = 0.5 * (rho_field[i, j, k] + rho_field[i + 1, j, k])
                else:
                    rho_e = rho_field[i, j, k]
                if i > 0:
                    rho_w = 0.5 * (rho_field[i - 1, j, k] + rho_field[i, j, k])
                else:
                    rho_w = rho_field[i, j, k]
                if j < Ny - 1:
                    rho_n = 0.5 * (rho_field[i, j, k] + rho_field[i, j + 1, k])
                else:
                    rho_n = rho_field[i, j, k]
                if j > 0:
                    rho_s = 0.5 * (rho_field[i, j - 1, k] + rho_field[i, j, k])
                else:
                    rho_s = rho_field[i, j, k]
                if k < Nz - 1:
                    rho_t = 0.5 * (rho_field[i, j, k] + rho_field[i, j, k + 1])
                else:
                    rho_t = rho_field[i, j, k]
                if k > 0:
                    rho_b = 0.5 * (rho_field[i, j, k - 1] + rho_field[i, j, k])
                else:
                    rho_b = rho_field[i, j, k]

                div = (
                    (rho_e * u[i + 1, j, k] - rho_w * u[i, j, k]) * dyj * dzk
                    + (rho_n * v[i, j + 1, k] - rho_s * v[i, j, k]) * dxi * dzk
                    + (rho_t * w[i, j, k + 1] - rho_b * w[i, j, k]) * dxi * dyj
                )
                d = abs(div)
                if d > r_max:
                    r_max = d
    return r_max


# ── Honest continuity residuals (ledger C7 / F2) ──────────────────

@njit(cache=True, fastmath=True)
def _mass_res_solved_jit_3d(u, v, w, Nx, Ny, Nz, dx, dy, dz,
                            rho_eps_field, cell_kind):
    """LOCAL continuity residual over the cells the pp equation ACTUALLY SOLVES.

    Two deliberate differences from `_mass_res_jit_3d`, both required for the
    number to mean anything (ledger C6/C7):

      1. `cell_kind` (from `_pp_sparsity`) selects `== 0` cells. The outlet row
         is `cell_kind == 1`: its continuity equation was REPLACED by `Pp = 0`
         (a Dirichlet pressure outlet), so it has no continuity residual to
         converge and must not be counted. Select by cell_kind, NOT by row index
         — a partial / tapered outlet pins only some cells of the row.
      2. The CALLER must pass a rho_eps rebuilt from the CURRENT (post-
         `_update_density`) rho. `_mass_res_jit_3d` is handed the pre-update
         array the pp solve already zeroed itself against, which is why it reads
         ~0 by construction on exactly these cells.

    NORMALISATION is per-cell and grid-scale invariant:

        R_cell = |net flux| / Σ|face fluxes|          (dimensionless, ∈ [0, 1])

    NOT `max|net| / mdot_inlet` — that ratio shrinks as the mesh refines (a
    finer cell simply carries less flux), so a fixed tolerance on it silently
    becomes easier on finer grids. Dividing by the cell's OWN throughput removes
    the mesh-scale dependence, which is what a grid-independent `tol` needs.

    Returns (max_local, n_cells_counted). A cell with no flux at all (Σ|face| =
    0) has no continuity equation to violate and is skipped.
    """
    r_max = 0.0
    n_cnt = 0
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                flat = (i * Ny + j) * Nz + k
                if cell_kind[flat] != 0:
                    continue                       # Dirichlet outlet: not solved
                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]
                Ae = dyj * dzk
                Ax = dxi * dzk
                Az = dxi * dyj

                if i < Nx - 1:
                    re_ = 0.5 * (rho_eps_field[i, j, k]
                                 + rho_eps_field[i + 1, j, k])
                else:
                    re_ = rho_eps_field[i, j, k]
                if i > 0:
                    rw_ = 0.5 * (rho_eps_field[i - 1, j, k]
                                 + rho_eps_field[i, j, k])
                else:
                    rw_ = rho_eps_field[i, j, k]
                if j < Ny - 1:
                    rn_ = 0.5 * (rho_eps_field[i, j, k]
                                 + rho_eps_field[i, j + 1, k])
                else:
                    rn_ = rho_eps_field[i, j, k]
                if j > 0:
                    rs_ = 0.5 * (rho_eps_field[i, j - 1, k]
                                 + rho_eps_field[i, j, k])
                else:
                    rs_ = rho_eps_field[i, j, k]
                if k < Nz - 1:
                    rt_ = 0.5 * (rho_eps_field[i, j, k]
                                 + rho_eps_field[i, j, k + 1])
                else:
                    rt_ = rho_eps_field[i, j, k]
                if k > 0:
                    rb_ = 0.5 * (rho_eps_field[i, j, k - 1]
                                 + rho_eps_field[i, j, k])
                else:
                    rb_ = rho_eps_field[i, j, k]

                fe = re_ * u[i + 1, j, k] * Ae
                fw = rw_ * u[i, j, k] * Ae
                fn = rn_ * v[i, j + 1, k] * Ax
                fs = rs_ * v[i, j, k] * Ax
                ft = rt_ * w[i, j, k + 1] * Az
                fb = rb_ * w[i, j, k] * Az

                net = (fe - fw) + (fn - fs) + (ft - fb)
                thru = (abs(fe) + abs(fw) + abs(fn)
                        + abs(fs) + abs(ft) + abs(fb))
                if thru <= 0.0:
                    continue                       # no flux -> nothing to violate
                n_cnt += 1
                r = abs(net) / thru
                if r > r_max:
                    r_max = r
    return r_max, n_cnt


@njit(cache=True, fastmath=True)
def _mass_global_jit_3d(v, Nx, Ny, Nz, dx, dz, rho_eps_field):
    """GLOBAL boundary mass balance on the streamwise (j) faces.

    Returns (mdot_in, mdot_out, backflow_frac_out).

    Signed, not absolute: `mdot_out` is the NET outflow, so a cell with
    reversed flow subtracts. That is the physically right global balance, but it
    also means positive and negative outlet fluxes can cancel and hide a
    recirculating outlet — so `backflow_frac_out` is reported alongside:

        backflow_frac_out = Σ|negative outlet flux| / Σ|outlet flux|

    A healthy outflow has backflow_frac ≈ 0. A nonzero value means the global
    balance is being satisfied by cancellation and must not be trusted on its
    own. (The solver has no outlet backflow clamp in either dimension — ledger
    C2, still open.)
    """
    mdot_in = 0.0
    mdot_out = 0.0
    out_pos = 0.0
    out_neg = 0.0
    for i in range(Nx):
        for k in range(Nz):
            A = dx[i] * dz[k]
            fin = rho_eps_field[i, 0, k] * v[i, 0, k] * A
            fout = rho_eps_field[i, Ny - 1, k] * v[i, Ny, k] * A
            mdot_in += fin
            mdot_out += fout
            if fout >= 0.0:
                out_pos += fout
            else:
                out_neg += -fout
    tot = out_pos + out_neg
    bf = (out_neg / tot) if tot > 0.0 else 0.0
    return mdot_in, mdot_out, bf


# ── Momentum residual (ledger C6) ─────────────────────────────────
# The F2 monitor uses this residual to gate SIMPLE convergence.

@njit(cache=True, fastmath=True, inline='always')
def _u_coeffs_df_3d(u, v, w, P, i, j, k,
                    Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, outlet_u_frac, use_sou,
                    use_eps):
    """Unrelaxed conservative u-momentum equation for F2 residuals.

    Transport is shared with the sweep, while this assembly excludes its
    under-relaxation and deferred diagonal compensation. The fixed-point
    tests cover equality on every use_sou/use_eps branch.
    """
    # Volume + face areas
    dxi = 0.5 * (dx[i - 1] + dx[min(i, Nx - 1)])
    dyj = dy[j]
    dzk = dz[k]
    vol = dxi * dyj * dzk

    il_r = i - 1; ir_r = i
    (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb) = _u_transport_3d(
        u, v, w, rho_field, mu_eff_field, eps_field,
        dx, dy, dz, i, j, k, outlet_u_frac, use_eps)
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

    # Brinkman / Forchheimer drag (linearised)
    umag = _umag_u_3d(u, v, w, i, j, k, Nx, )
    K_u = 0.5 * (K_arr[il_r, j, k] + K_arr[ir_r, j, k])
    cF_u = 0.5 * (cF_arr[il_r, j, k] + cF_arr[ir_r, j, k])
    Sp = _porous_src_df_3d(umag, K_u, cF_u,
                             mu_loc, rho_loc) * vol

    # Pressure gradient source
    p_src = (P[i - 1, j, k] - P[i, j, k]) * dyj * dzk

    aP0 = (De + Dw + Dn + Ds + Dt + Db + Sp
           + max(Fe, 0.0) + max(-Fw, 0.0)
           + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0))
    rhs = (aE * uE + aW * uW + aN * uN + aS * uS
           + aT * uT + aB * uB + p_src)
    # R4: minmod SOU deferred correction (flags mirror 2D _sou_corr_u_x/_y).
    # Added via a guarded += so the use_sou=0 rhs expression tree is unchanged
    # (fastmath would re-associate an inline `+ sou` and break bit-identity).
    if use_sou == 1:
        rhs += (_sou_axis(u[max(i - 2, 0), j, k], u[max(i - 1, 0), j, k],
                          u[i, j, k], u[min(i + 1, Nx), j, k],
                          u[min(i + 2, Nx), j, k],
                          i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1,
                          Fw, Fe, dx, i, True)
                + _sou_axis(u[i, max(j - 2, 0), k], u[i, max(j - 1, 0), k],
                            u[i, j, k], u[i, min(j + 1, Ny - 1), k],
                            u[i, min(j + 2, Ny - 1), k],
                            j > 1, j > 0 and j < Ny - 1, j < Ny - 2,
                            j > 0 and j < Ny - 1, Fs, Fn, dy, j, False)
                + _sou_axis(u[i, j, max(k - 2, 0)], u[i, j, max(k - 1, 0)],
                            u[i, j, k], u[i, j, min(k + 1, Nz - 1)],
                            u[i, j, min(k + 2, Nz - 1)],
                            k > 1, k > 0 and k < Nz - 1, k < Nz - 2,
                            k > 0 and k < Nz - 1, Fb, Ft, dz, k, False))
    return aP0, rhs


@njit(cache=True, fastmath=True, inline='always')
def _v_coeffs_df_3d(u, v, w, P, i, j, k,
                    Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, use_sou,
                    use_eps):
    """Unrelaxed conservative v-momentum equation for F2 residuals.

    Transport is shared with the sweep, while this assembly excludes its
    under-relaxation and deferred diagonal compensation. The fixed-point
    tests cover equality on every use_sou/use_eps branch.
    """
    jc = min(j, Ny - 1)
    dxi = dx[i]
    dyj = 0.5 * (dy[j - 1] + dy[min(j, Ny - 1)])
    dzk = dz[k]
    vol = dxi * dyj * dzk

    (De, Dw, Dn, Ds, Dt, Db, Fe, Fw, Fn, Fs, Ft, Fb) = _v_transport_3d(
        u, v, w, rho_field, mu_eff_field, eps_field,
        dx, dy, dz, i, j, k, use_eps)
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
    Sp = _porous_src_df_3d(umag, K_arr[i, jc, k], cF_arr[i, jc, k],
                             mu_loc, rho_loc) * vol

    p_src = (P[i, j - 1, k] - P[i, j, k]) * dxi * dzk

    aP0 = (De + Dw + Dn + Ds + Dt + Db + Sp
           + max(Fe, 0.0) + max(-Fw, 0.0)
           + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0))
    rhs = (aE * vE + aW * vW + aN * vN + aS * vS
           + aT * vT + aB * vB + p_src)
    # R4: minmod SOU deferred correction (flags mirror 2D _sou_corr_v_x/_y).
    # Guarded += keeps the use_sou=0 rhs expression tree unchanged (fastmath).
    if use_sou == 1:
        rhs += (_sou_axis(v[max(i - 2, 0), j, k], v[max(i - 1, 0), j, k],
                          v[i, j, k], v[min(i + 1, Nx - 1), j, k],
                          v[min(i + 2, Nx - 1), j, k],
                          i > 1, i > 0 and i < Nx - 1, i < Nx - 2,
                          i > 0 and i < Nx - 1, Fw, Fe, dx, i, False)
                + _sou_axis(v[i, max(j - 2, 0), k], v[i, max(j - 1, 0), k],
                            v[i, j, k], v[i, min(j + 1, Ny), k],
                            v[i, min(j + 2, Ny), k],
                            j > 2, j > 1, j + 2 <= Ny, j > 1,
                            Fs, Fn, dy, j, True)
                + _sou_axis(v[i, j, max(k - 2, 0)], v[i, j, max(k - 1, 0)],
                            v[i, j, k], v[i, j, min(k + 1, Nz - 1)],
                            v[i, j, min(k + 2, Nz - 1)],
                            k > 1, k > 0 and k < Nz - 1, k < Nz - 2,
                            k > 0 and k < Nz - 1, Fb, Ft, dz, k, False))
    return aP0, rhs


@njit(cache=True, fastmath=True, inline='always')
def _w_coeffs_df_3d(u, v, w, P, i, j, k,
                    Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, outlet_w_frac, use_sou,
                    use_eps):
    """Unrelaxed conservative w-momentum equation for F2 residuals.

    Transport is shared with the sweep, while this assembly excludes its
    under-relaxation and deferred diagonal compensation. The fixed-point
    tests cover equality on every use_sou/use_eps branch.
    """
    kc = min(k, Nz - 1)
    dxi = dx[i]
    dyj = dy[j]
    dzk = 0.5 * (dz[k - 1] + dz[min(k, Nz - 1)])
    vol = dxi * dyj * dzk

    (De, Dw, Dn, Ds, Dt, Db, Fe, Fw_, Fn, Fs, Ft, Fb) = _w_transport_3d(
        u, v, w, rho_field, mu_eff_field, eps_field,
        dx, dy, dz, i, j, k, outlet_w_frac, use_eps)
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
    Sp = _porous_src_df_3d(umag, K_arr[i, j, kc], cF_arr[i, j, kc],
                             mu_loc, rho_loc) * vol

    p_src = (P[i, j, k - 1] - P[i, j, k]) * dxi * dyj

    aP0 = (De + Dw + Dn + Ds + Dt + Db + Sp
           + max(Fe, 0.0) + max(-Fw_, 0.0)
           + max(Fn, 0.0) + max(-Fs, 0.0) + max(Ft, 0.0) + max(-Fb, 0.0))
    rhs = (aE * wE + aW * wW + aN * wN + aS * wS
           + aT * wT + aB * wB + p_src)
    # R4: minmod SOU deferred correction (cross axes mirror v; parallel = z).
    # Guarded += keeps the use_sou=0 rhs expression tree unchanged (fastmath).
    if use_sou == 1:
        rhs += (_sou_axis(w[max(i - 2, 0), j, k], w[max(i - 1, 0), j, k],
                          w[i, j, k], w[min(i + 1, Nx - 1), j, k],
                          w[min(i + 2, Nx - 1), j, k],
                          i > 1, i > 0 and i < Nx - 1, i < Nx - 2,
                          i > 0 and i < Nx - 1, Fw_, Fe, dx, i, False)
                + _sou_axis(w[i, max(j - 2, 0), k], w[i, max(j - 1, 0), k],
                            w[i, j, k], w[i, min(j + 1, Ny - 1), k],
                            w[i, min(j + 2, Ny - 1), k],
                            j > 1, j > 0 and j < Ny - 1, j < Ny - 2,
                            j > 0 and j < Ny - 1, Fs, Fn, dy, j, False)
                + _sou_axis(w[i, j, max(k - 2, 0)], w[i, j, max(k - 1, 0)],
                            w[i, j, k], w[i, j, min(k + 1, Nz)],
                            w[i, j, min(k + 2, Nz)],
                            k > 2, k > 1, k + 2 <= Nz, k > 1,
                            Fb, Ft, dz, k, True))
    return aP0, rhs


@njit(cache=True, fastmath=True)
def _mom_res_jit_3d(u, v, w, P,
                    Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, outlet_u_frac, outlet_w_frac,
                    use_sou, use_eps):
    """Momentum-equation residual  R = aP0·φ − (Σ a_nb·φ_nb + p_src [+ SOU]),
    evaluated on the CURRENT (post-correction, post-`_update_density`) fields.

    Why this exists (ledger C6, 2026-07-12) — the mass residual cannot serve as
    a convergence measure on this solver:

      * The pressure-correction equation is solved to the accuracy of the pp
        solve each iteration (direct LU below `_AMG_GATE`; AMG-BiCGStab with an
        adaptive rtol above it) against the very `rho_eps_field` the mass
        residual is then evaluated with. So on the direct-solve path the mass
        residual is ~0 by construction on every cell it solved (measured
        2.9e-17) and the reported number is entirely the outlet row's artifact.
        Above the AMG gate it additionally carries the pp linear-solve error —
        still not a SIMPLE fixed-point residual. (Scope corrected 2026-07-12.)
      * The MOMENTUM equation, by contrast, gets ONE Gauss-Seidel sweep per
        iteration (`n_inner=1`) on a NONLINEAR system (Forchheimer drag +
        convection), using the PREVIOUS pressure — and is then further violated
        by SIMPLE's own velocity correction, which drops the Σ a_nb·u'_nb term.
        The size of what SIMPLE drops is ∝ Pp, so this residual → 0 exactly
        when Pp → 0, i.e. exactly at the SIMPLE fixed point.

    So R is a DIRECT test of "are the equations satisfied", not a proxy for
    "has the field stopped moving" (the historical LowReExit velocity
    criterion, which could not tell convergence from a slow crawl).

    Coefficients come from `_{u,v,w}_coeffs_df_3d`, a deliberate parallel
    assembly of the sweep cell bodies (see `_u_coeffs_df_3d` for why they are
    not literally shared). Sync is GUARDED, not assumed: this residual must
    vanish at the sweeps' own momentum fixed point on every (use_sou, use_eps)
    branch — `tests/test_momentum_residual_3d.py`. The relaxation term is
    deliberately NOT included: aP0 and rhs here are the UNRELAXED equation,
    whose residual vanishes at the fixed point for any alpha_u.

    NORMALISATION — BALANCED denominator (fixed 2026-07-12, codex review).
    Returns (num_c, den_c) per component with

        num_c = Σ |aP0·φ − rhs|                     (the residual)
        den_c = Σ ½·(|aP0·φ| + |rhs|)               (the BALANCED scale)

    The first draft used `den_c = Σ|aP0·φ|` alone. That has a silent false zero:
    a component whose velocity is identically zero but whose pressure source is
    not (φ ≡ 0, rhs ≠ 0) gives den = 0 with num > 0, and the caller's
    `num/den if den > 0 else 0.0` guard reported CONVERGED. Harmless while the
    metric was diagnostic-only; a silent false convergence once it gates.

    The balanced form removes the failure mode structurally, not by a guard:
    the triangle inequality gives num_c ≤ |aP0·φ| + |rhs| summed = 2·den_c, so
        num_c > 0  ⟹  den_c > 0        (a false zero is IMPOSSIBLE)
        R_c = num_c / den_c  ∈  [0, 2]  (bounded — no blow-up on a small den)
    The quiescent-component case now reports R_c = 2 (maximally unconverged),
    which is the right answer. The caller still applies a common-scale floor so a
    physically negligible component cannot gate convergence on its own — see
    `simple_solver_3d.solve()`.

    RAW num/den are returned (not the ratio) so the normalisation can be changed
    post-hoc without re-running: the caller stores both.
    """
    nu_ = 0.0; du_ = 0.0
    for i in range(1, Nx):
        for j in range(Ny):
            for k in range(Nz):
                aP0, rhs = _u_coeffs_df_3d(
                    u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, outlet_u_frac, use_sou, use_eps)
                lhs = aP0 * u[i, j, k]
                nu_ += abs(lhs - rhs)
                du_ += 0.5 * (abs(lhs) + abs(rhs))

    nv_ = 0.0; dv_ = 0.0
    for i in range(Nx):
        for j in range(1, Ny):
            for k in range(Nz):
                aP0, rhs = _v_coeffs_df_3d(
                    u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, use_sou, use_eps)
                lhs = aP0 * v[i, j, k]
                nv_ += abs(lhs - rhs)
                dv_ += 0.5 * (abs(lhs) + abs(rhs))

    nw_ = 0.0; dw_ = 0.0
    for i in range(Nx):
        for j in range(Ny):
            for k in range(1, Nz):
                aP0, rhs = _w_coeffs_df_3d(
                    u, v, w, P, i, j, k, Nx, Ny, Nz, dx, dy, dz,
                    rho_field, mu_eff_field, mu_field, eps_field,
                    K_arr, cF_arr, outlet_w_frac, use_sou, use_eps)
                lhs = aP0 * w[i, j, k]
                nw_ += abs(lhs - rhs)
                dw_ += 0.5 * (abs(lhs) + abs(rhs))

    return nu_, du_, nv_, dv_, nw_, dw_
