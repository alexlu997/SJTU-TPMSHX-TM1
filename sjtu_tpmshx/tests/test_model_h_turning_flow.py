"""Turning flow must converge independently of the software fluid labels."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_energy as e2, ltne_energy_3d as e3


def _case(dimension, swap):
    nx, ny, nz = 24, 12, 2
    dx = np.full(nx, .18 / nx)
    w = np.geomspace(2e-5, .02, ny // 2)
    dy = np.r_[w, w[::-1]]
    dy *= .04 / dy.sum()
    dz = np.full(nz, .04 / nz)
    x = np.r_[0., np.cumsum(dx)]
    inlet = np.clip((x - .13) / .04, 0, 1)
    outlet = np.clip((x - .01) / .04, 0, 1)
    # A discrete streamfunction specifies exactly conservative face fluxes
    # on this stretched grid. Air enters top-right and exits bottom-left;
    # water flows straight through +x. Neither depends on a data file.
    eta = np.linspace(0, 1, ny + 1)
    psi = .8 * ((1 - eta) * outlet[:, None] + eta * inlet[:, None])
    ma = (np.diff(psi, axis=1), -np.diff(psi, axis=0))
    mb = (np.full((nx + 1, ny), 4 * .04 / ny), np.zeros((nx, ny + 1)))
    frac = np.diff(inlet) * .04 / dx
    shape = (nx, ny)
    if dimension == 3:
        ma = tuple(f[:, :, None] * dz for f in ma) + (np.zeros((nx, ny, nz + 1)),)
        mb = tuple(f[:, :, None] * dz for f in mb) + (np.zeros((nx, ny, nz + 1)),)
        frac = np.broadcast_to(frac[:, None], (nx, nz)).copy()
        shape += (nz,)
    for mass in (ma, mb):
        np.testing.assert_allclose(sum(np.diff(f, axis=a) for a, f in enumerate(mass)), 0, atol=1e-16)
    # Values follow their fluid when software labels are exchanged.
    a = (430., .012, 2e5, 1400., 3, frac, ma, 'air')
    b = (300., .23, 8e5, 4.18e6, 0, np.ones(shape[1:]), mb, 'water')
    if swap:
        a, b = b, a
    zero = np.zeros(shape)
    kwargs = dict(L=.18, H=.04, Nx=nx, Ny=ny, K_ss=2., epsilon=.75,
                  dx_arr=dx, dy_arr=dy, ucA=zero, vcA=zero, ucB=zero, vcB=zero,
                  max_iter=5000, q_rel_tol=1e-10, return_info=True, accelerate=True,
                  model_fluids=(a[-1], b[-1]))
    for side, values in zip(('A', 'B'), (a, b)):
        for prefix, value in zip(('T_in', 'K_ff', 'h_v', 'rho_cp_f', 'dir_', 'inlet_mask_'), values):
            kwargs[prefix + side] = value
        kwargs[('mass_flux_' if dimension == 2 else 'model_mass_') + side] = values[-2]
        if dimension == 3:
            for axis, face in zip('uvw', values[-2]):
                kwargs[axis + 'f' + side] = np.zeros_like(face)
    if dimension == 3:
        kwargs.update(D=.04, Nz=nz, dz_arr=dz, wcA=zero, wcB=zero, conservative_ltne=True)
    return kwargs


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('red_black', [False, True])
def test_turning_flow_converges_and_labels_preserve_the_solution(monkeypatch, dimension, red_black):
    energy = e2 if dimension == 2 else e3
    suffix = '_2D' if dimension == 2 else ''
    monkeypatch.setattr(energy, '_RB_ENERGY' + suffix, red_black)
    monkeypatch.setattr(energy, '_RB_ENERGY' + suffix + '_GATE', 0)
    solve = e2.solve_full_domain if dimension == 2 else e3.solve_full_domain_3d
    results = []
    for swap in (False, True):
        ta, tb, ts, info = solve(**_case(dimension, swap))
        assert info['converged'], info
        assert info['residual'] < 1e-7
        results.append((tb, ta, ts) if swap else (ta, tb, ts))
    for a, b in zip(*results):
        np.testing.assert_allclose(a, b, atol=1e-5, rtol=0)
