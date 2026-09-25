"""Pressure-reference outlet CVs must close all six rho*eps face fluxes."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import (
    _v_bc_3d, _correct_jit_3d, _sweep_v_jit_df_3d, _sweep_v_jit_df_3d_parallel,
)


@pytest.mark.parametrize('cross_factor', [-1., 1., 5.])
@pytest.mark.parametrize('Ny', [1, 2])
@pytest.mark.parametrize('stage', ['v_bc', 'correct', 'serial', 'parallel'])
def test_correct_reference_cell_closes_both_transverse_fluxes(cross_factor, Ny, stage):
    Nx, Nz = 3, 3
    rho = 1. + np.arange(Nx * Ny * Nz).reshape(Nx, Ny, Nz) / 10.
    eps = .4 + np.arange(Nx * Ny * Nz).reshape(Nx, Ny, Nz) / 100.
    u = np.zeros((Nx + 1, Ny, Nz))
    v = np.zeros((Nx, Ny + 1, Nz))
    w = np.zeros((Nx, Ny, Nz + 1))
    u[1, -1, 1], u[2, -1, 1] = .2, .7 * cross_factor
    w[1, -1, 1], w[1, -1, 2] = .3, .9 * cross_factor
    v[1, -2, 1] = 2.
    vin = v[:, 0, :].copy()
    dx, dy, dz = np.array([.2, .3, .5]), np.linspace(.4, .6, Ny), np.array([.3, .5, .7])
    j = Ny - 1
    er = rho * eps
    south = .5 * (er[1, max(j - 1, 0), 1] + er[1, j, 1]) * 2. * dx[1] * dz[1]
    cross_x = (.5 * (er[1, j, 1] + er[2, j, 1]) * u[2, j, 1]
               - .5 * (er[0, j, 1] + er[1, j, 1]) * u[1, j, 1]) * dy[j] * dz[1]
    cross_z = (.5 * (er[1, j, 1] + er[1, j, 2]) * w[1, j, 2]
               - .5 * (er[1, j, 0] + er[1, j, 1]) * w[1, j, 1]) * dx[1] * dy[j]
    mask = np.zeros((Nx, Nz), dtype=bool)
    mask[1, 1] = True
    P = np.zeros_like(rho)
    if stage == 'correct':
        _correct_jit_3d(u, v, w, P, np.zeros_like(P), np.zeros_like(u),
                        np.zeros_like(v), np.zeros_like(w), vin,
                        Nx, Ny, Nz, .5, rho, eps, mask, dx, dy, dz)
    elif stage == 'v_bc':
        _v_bc_3d(u, v, w, vin, rho, eps, mask, Nx, Ny, Nz, dx, dy, dz)
    else:
        sweep = _sweep_v_jit_df_3d if stage == 'serial' else _sweep_v_jit_df_3d_parallel
        # Zero momentum sweeps isolates the real shared BC tail in both callers.
        sweep(u, v, w, P, np.zeros_like(v), vin, Nx, Ny, Nz, dx, dy, dz,
              rho, eps, np.ones_like(rho), np.ones_like(rho),
              np.ones((Nx, Ny, Nz)), np.ones((Nx, Ny, Nz)), .5, 0, 0, 1, mask)
    assert er[1, -1, 1] * v[1, -1, 1] * dx[1] * dz[1] == pytest.approx(
        south - cross_x - cross_z, rel=1e-13)
    assert np.all(v[:, -1, :][~mask] == 0.)


def test_v_bc_outlet_uses_eps_rho_ratio_when_zoned():
    Nx, Ny, Nz = 1, 3, 1
    v = np.zeros((Nx, Ny + 1, Nz))
    v[0, Ny - 1, 0] = 2.0
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); rho[0, 1, 0] = 1.2; rho[0, 2, 0] = 1.0
    eps = np.ones((Nx, Ny, Nz)); eps[0, 1, 0] = 0.6; eps[0, 2, 0] = 0.4  # zoned y
    of = np.ones((Nx, Nz))
    _v_bc_3d(np.zeros((Nx + 1, Ny, Nz)), v, np.zeros((Nx, Ny, Nz + 1)),
             vin, rho, eps, of, Nx, Ny, Nz, np.ones(Nx), np.ones(Ny), np.ones(Nz))
    er_in = 0.5 * (eps[0, 1, 0] * rho[0, 1, 0] + eps[0, 2, 0] * rho[0, 2, 0])
    er_out = eps[0, 2, 0] * rho[0, 2, 0]
    assert v[0, Ny, 0] == pytest.approx(2.0 * er_in / er_out)


def test_v_bc_outlet_uniform_eps_reduces_to_rho_ratio():
    """Without transverse flow uniform ε cancels from the density ratio."""
    Nx, Ny, Nz = 1, 3, 1
    v = np.zeros((Nx, Ny + 1, Nz)); v[0, Ny - 1, 0] = 2.0
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); rho[0, 1, 0] = 1.2; rho[0, 2, 0] = 1.0
    eps = np.full((Nx, Ny, Nz), 0.5)             # uniform
    of = np.ones((Nx, Nz))
    _v_bc_3d(np.zeros((Nx + 1, Ny, Nz)), v, np.zeros((Nx, Ny, Nz + 1)),
             vin, rho, eps, of, Nx, Ny, Nz, np.ones(Nx), np.ones(Ny), np.ones(Nz))
    rho_in = 0.5 * (rho[0, 1, 0] + rho[0, 2, 0]); rho_out = rho[0, 2, 0]
    assert v[0, Ny, 0] == pytest.approx(2.0 * rho_in / rho_out)


def test_v_bc_outlet_wall_cell_pins_zero():
    Nx, Ny, Nz = 1, 3, 1
    v = np.zeros((Nx, Ny + 1, Nz)); v[0, Ny - 1, 0] = 2.0
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); eps = np.full((Nx, Ny, Nz), 0.5)
    of = np.zeros((Nx, Nz))                       # wall (closed)
    _v_bc_3d(np.zeros((Nx + 1, Ny, Nz)), v, np.zeros((Nx, Ny, Nz + 1)),
             vin, rho, eps, of, Nx, Ny, Nz, np.ones(Nx), np.ones(Ny), np.ones(Nz))
    assert v[0, Ny, 0] == 0.0


def test_correct_outlet_uses_eps_rho_ratio_when_zoned():
    """Pressure correction uses the same outlet closure as the v-sweeps."""
    Nx, Ny, Nz = 1, 3, 1
    # All transverse faces here are walls; correction must zero them before
    # using transverse fluxes in the outlet closure.
    u = np.ones((Nx + 1, Ny, Nz)); w = np.ones((Nx, Ny, Nz + 1))
    v = np.zeros((Nx, Ny + 1, Nz)); v[0, Ny - 1, 0] = 2.0
    P = np.zeros((Nx, Ny, Nz)); Pp = np.zeros((Nx, Ny, Nz))
    d_u = np.zeros((Nx + 1, Ny, Nz)); d_v = np.zeros((Nx, Ny + 1, Nz))
    d_w = np.zeros((Nx, Ny, Nz + 1))
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); rho[0, 1, 0] = 1.2; rho[0, 2, 0] = 1.0
    eps = np.ones((Nx, Ny, Nz)); eps[0, 1, 0] = 0.6; eps[0, 2, 0] = 0.4
    omask = np.ones((Nx, Nz), dtype=np.bool_)
    _correct_jit_3d(u, v, w, P, Pp, d_u, d_v, d_w, vin, Nx, Ny, Nz, 0.5,
                    rho, eps, omask, np.ones(Nx), np.ones(Ny), np.ones(Nz))
    er_in = 0.5 * (eps[0, 1, 0] * rho[0, 1, 0] + eps[0, 2, 0] * rho[0, 2, 0])
    er_out = eps[0, 2, 0] * rho[0, 2, 0]
    assert v[0, Ny, 0] == pytest.approx(2.0 * er_in / er_out)
