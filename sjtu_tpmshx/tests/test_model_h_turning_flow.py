"""Turning flow must converge independently of the software fluid labels."""
import numpy as np
import pytest

from sjtu_tpmshx.tests.native.test_cpp_model_h import driver as driver


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
    frac = np.clip(np.diff(inlet) * .04 / dx, 0., 1.)
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
    return dict(widths=(dx, dy, dz)[:dimension],
        conductivity=tuple(np.full(shape, value) for value in (a[1], b[1], 2.)),
        exchange=(np.full(shape, a[2]), np.full(shape, b[2])),
        mass_faces=(a[-2], b[-2]), directions=(a[4], b[4]),
        inlets=(a[0], b[0]), openings=(a[5], b[5]), fluids=(a[-1], b[-1]),
        max_iterations=5000, q_relative_tolerance=1e-10, accelerate=True)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('red_black', [False, True])
def test_turning_flow_converges_and_labels_preserve_the_solution(driver, dimension, red_black):
    results = []
    for swap in (False, True):
        ta, tb, ts, info = driver(**_case(dimension, swap), red_black=red_black)
        assert info['converged'], info
        assert info['residual'] < 1e-7
        results.append((tb, ta, ts) if swap else (ta, tb, ts))
    for a, b in zip(*results):
        np.testing.assert_allclose(a, b, atol=1e-5, rtol=0)
