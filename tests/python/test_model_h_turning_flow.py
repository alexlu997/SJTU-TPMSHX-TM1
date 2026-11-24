"""Turning flow must converge independently of the software fluid labels."""
import numpy as np
import pytest

from tests.python.native import test_model_h_2d as plane
from tests.python.native import test_model_h_3d as volume

native_plane = plane.native
native_volume = volume.native


def _case(dimension, swap, red_black):
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
    # Values follow their fluid when software labels are exchanged. Fluid 0 is air and 1 is water.
    a = (430., .012, 2e5, 1400., 3, frac, ma, 0)
    b = (300., .23, 8e5, 4.18e6, 0, np.ones(shape[1:]), mb, 1)
    if swap:
        a, b = b, a
    empty = np.empty(0)
    # Bridge side order: conductivity, exchange, mass faces, profile, opening, then a 3D source.
    sides = [[np.full(shape, s[1]), np.full(shape, s[2]), *(np.ascontiguousarray(f) for f in s[6]),
              empty, np.ascontiguousarray(s[5], dtype=np.float64), *([empty] if dimension == 3 else [])]
             for s in (a, b)]
    c = dict(shape=shape, widths=[dx, dy, np.ones(1)] if dimension == 2 else [dx, dy, dz],
             state=[np.zeros(shape) for _ in range(3)], ks=np.full(shape, 2.), a=sides[0], b=sides[1],
             directions=(a[4], b[4]), fluids=(a[-1], b[-1]), tin=(a[0], b[0]), maxit=5000, chunk=250,
             qtol=1e-10, warm=False, accelerate=True, rb=red_black)
    if dimension == 3:
        c.update(source_s=empty, alpha=(.7, .7, .7))
    return c


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('red_black', [False, True])
def test_turning_flow_converges_and_labels_preserve_the_solution(request, dimension, red_black):
    native = request.getfixturevalue('native_plane' if dimension == 2 else 'native_volume')
    results = []
    for swap in (False, True):
        c = _case(dimension, swap, red_black)
        code, status, metrics, _, error = native(c)
        assert code == 0, error
        assert status[0] == 0, (status, metrics[0])  # converged
        assert metrics[0] < 1e-7
        ta, tb, ts = c['state']
        results.append((tb, ta, ts) if swap else (ta, tb, ts))
    for a, b in zip(*results):
        np.testing.assert_allclose(a, b, atol=1e-5, rtol=0)
