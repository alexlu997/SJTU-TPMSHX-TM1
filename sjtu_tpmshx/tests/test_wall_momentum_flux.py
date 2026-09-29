"""Wall conductance and independent momentum equations on the actual grids."""
from itertools import product
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.solvers import _kernels_simple_2d as k2
from sjtu_tpmshx.solvers import _kernels_simple_3d as k3


def _call(fn, state):
    return fn(**{key: state[key] for key in inspect.signature(fn).parameters})


def _state(dim):
    widths = [np.array([.10, .15, .20, .25, .20, .10]),
              np.array([.10, .20, .30, .25, .15]),
              np.array([.10, .20, .30, .40])][:dim]
    shape = tuple(map(len, widths))
    a = dict(P=np.zeros(shape), rho_field=np.zeros(shape),
             mu_eff_field=np.ones(shape), mu_field=np.zeros(shape),
             eps_field=np.ones(shape), alpha_u=.7, n_sweeps=1,
             cf_aniso=0., use_sou=0, use_eps=0)
    for axis, c in enumerate('uvw'[:dim]):
        size = list(shape); size[axis] += 1
        a[c] = np.zeros(size)
        a['d_' + c] = np.zeros(size)
        a['N' + 'xyz'[axis]] = shape[axis]
        a['d' + 'xyz'[axis] + ('_arr' if dim == 2 else '')] = widths[axis]
    a['K_arr'] = np.ones(shape)
    a['cF_arr'] = np.zeros_like(a['K_arr'])
    a['outlet_u_frac'] = np.zeros((shape[0] + 1,) + shape[2:])
    if dim == 3:
        a['outlet_w_frac'] = np.zeros((shape[0], shape[2] + 1))
    else:
        a.update(inlet_frac=np.ones(shape[0]), outlet_frac=np.ones(shape[0]),
                 v_inlet_field=np.zeros(shape[0]))
    return a, widths, shape


@pytest.mark.parametrize('dim', [2, 3])
def test_all_tangential_walls_have_half_cell_flux(dim):
    # Constant tangential velocity cancels every interior diffusive flux;
    # only the selected wall remains. rho=mu=0 isolates viscosity from drag.
    for component, axis, end in product(range(dim), range(dim), (0, 1)):
        if axis == component:
            continue
        a, widths, shape = _state(dim)
        c = 'uvw'[component]
        a[c][:] = 1.
        ijk = [2] * dim
        ijk[axis] = shape[axis] - 1 if end else 0
        a.update(zip('ijk', ijk))
        sizes = [widths[d][ijk[d]] for d in range(dim)]
        sizes[component] = .5 * (widths[component][ijk[component] - 1]
                                      + widths[component][ijk[component]])
        area = np.prod(sizes) / sizes[axis]
        expected = 2. * area / sizes[axis]
        coeff = getattr(k2 if dim == 2 else k3, f'_{c}_coeffs_df_{dim}d')
        for fraction in ((0., .5, 1.) if axis == 1 and end else (0.,)):
            if axis == 1 and end:
                a['outlet_' + c + '_frac'][:] = fraction
            ap, rhs = _call(coeff, a)
            assert ap - rhs == pytest.approx(expected * (1. - fraction), abs=1e-13)


@pytest.mark.parametrize('dim', [2, 3])
def test_normal_outlet_neighbour_uses_actual_boundary_value(dim):
    a, widths, shape = _state(dim)
    a.update(i=2, j=shape[1] - 1, k=2)
    coeff = k2._v_coeffs_df_2d if dim == 2 else k3._v_coeffs_df_3d
    ap0, rhs0 = _call(coeff, a)
    a['v'][:, -1] = 2.
    ap, rhs = _call(coeff, a)
    area = widths[0][2] * (widths[2][2] if dim == 3 else 1.)
    assert ap == ap0
    assert rhs - rhs0 == pytest.approx(2. * area / widths[1][-1])


def _mass_deficit(a, dim, component, location):
    """Half the two primary CV balances, divided by momentum CV epsilon."""
    widths = [a['d' + x + ('_arr' if dim == 2 else '')] for x in 'xyz'[:dim]]
    eps = (a['eps_field'] if dim == 2 or a['use_eps']
           else np.ones_like(a['eps_field']))
    er = a['rho_field'] * eps
    previous = list(location)
    previous[component] -= 1
    net = 0.
    for cell in (previous, list(location)):
        for axis, c in enumerate('uvw'[:dim]):
            area = np.prod([widths[q][cell[q]] for q in range(dim) if q != axis])
            for step in (-1, 1):
                face, neighbour = cell.copy(), cell.copy()
                face[axis] += int(step == 1)
                neighbour[axis] += step
                density = er[tuple(cell)]
                if 0 <= neighbour[axis] < er.shape[axis]:
                    density = .5 * (density + er[tuple(neighbour)])
                net += step * density * a[c][tuple(face)] * area
    eps_cv = .5 * (eps[tuple(previous)] + eps[tuple(location)])
    return max(-.5 * net / eps_cv, 0.)


def _sou_compensation(a, dim, component, location):
    """Outgoing primary half-faces and physical-coordinate slope bounds."""
    if dim == 3 and not a['use_sou']:
        return 0.
    widths = [a['d' + x + ('_arr' if dim == 2 else '')] for x in 'xyz'[:dim]]
    eps = (a['eps_field'] if dim == 2 or a['use_eps']
           else np.ones_like(a['eps_field']))
    er = eps * a['rho_field']
    low_cell = list(location)
    low_cell[component] -= 1
    eps_cv = .5 * (eps[tuple(low_cell)] + eps[location])

    def primary_mass(axis, face):
        cells = []
        for offset in (-1, 0):
            cell = face.copy()
            cell[axis] += offset
            if 0 <= cell[axis] < er.shape[axis]:
                cells.append(er[tuple(cell)])
        area = np.prod([widths[q][face[q]] for q in range(dim) if q != axis])
        return np.mean(cells) * a['uvw'[axis]][tuple(face)] * area

    field = a['uvw'[component]]
    bound = 0.
    for axis in range(dim):
        i = location[axis]
        if axis == component:
            lo_enabled = i > 1
            hi_enabled = lo_enabled and (component != 0 or i + 1 < len(widths[axis]))
        else:
            lo_enabled = hi_enabled = 0 < i < len(widths[axis]) - 1
        prev, after = list(location), list(location)
        prev[axis] = max(i - 1, 0)
        after[axis] = min(i + 1, field.shape[axis] - 1)
        if (field[location] - field[tuple(prev)]) * (field[tuple(after)] - field[location]) <= 0.:
            continue
        edges = np.r_[0., np.cumsum(widths[axis])]
        nodes = edges if axis == component else .5 * (edges[:-1] + edges[1:])
        for high, enabled in ((False, lo_enabled), (True, hi_enabled)):
            if not enabled:
                continue
            left, right = list(location), list(location)
            if axis == component:
                left[axis] += 0 if high else -1
                right[axis] += 1 if high else 0
                face_position = .5 * (nodes[i] + nodes[i + (1 if high else -1)])
            else:
                left[component] -= 1
                left[axis] += int(high)
                right[axis] += int(high)
                face_position = edges[i + int(high)]
            flux = .5 * (primary_mass(axis, left) + primary_mass(axis, right)) / eps_cv
            outgoing = max(flux if high else -flux, 0.)
            opposite_distance = nodes[i] - nodes[i-1] if high else nodes[i+1] - nodes[i]
            bound += outgoing * abs(face_position - nodes[i]) / opposite_distance
    return bound


@pytest.mark.parametrize('alpha', [.7, 1.])
@pytest.mark.parametrize('use_eps,use_sou', product((0, 1), repeat=2))
def test_3d_cell_update_matches_independent_equation_at_every_face(use_eps, use_sou, alpha):
    a, _, shape = _state(3)
    rng = np.random.default_rng(82)
    for key in ('u', 'v', 'w', 'P'):
        a[key][:] = rng.normal(0., .1, a[key].shape)
    # Physical normal wall values; outlet/inlet values remain real data.
    a['u'][[0, -1], :, :] = 0.
    a['w'][:, :, [0, -1]] = 0.
    a['rho_field'][:] = rng.uniform(.8, 1.2, shape)
    a['mu_field'][:] = .1
    a['eps_field'][:] = rng.uniform(.4, .8, shape)
    a['outlet_u_frac'][:] = rng.uniform(0., 1., a['outlet_u_frac'].shape)
    a['outlet_w_frac'][:] = rng.uniform(0., 1., a['outlet_w_frac'].shape)
    a.update(use_eps=use_eps, use_sou=use_sou, alpha_u=alpha)
    for axis, c in enumerate('uvw'):
        indices = [range(n) for n in shape]
        indices[axis] = range(1, shape[axis])
        for ijk in product(*indices):
            a.update(zip('ijk', ijk))
            ap, rhs = _call(getattr(k3, f'_{c}_coeffs_df_3d'), a)
            old = a[c][ijk]
            b = _mass_deficit(a, 3, axis, ijk) + _sou_compensation(a, 3, axis, ijk)
            _call(getattr(k3, f'_{c}_cell_df_3d'), a)
            expected = alpha * (rhs + b * old) / (ap + b) + (1. - alpha) * old
            assert a[c][ijk] == pytest.approx(expected, rel=2e-12, abs=1e-14)
            area = np.prod([a['d' + 'xyz'[q]][ijk[q]] for q in range(3) if q != axis])
            assert a['d_' + c][ijk] == pytest.approx(area / (ap + b), rel=2e-12)
            a[c][ijk] = old


@pytest.mark.parametrize('alpha', [.7, 1.])
def test_2d_sweep_matches_independent_equations_on_nonuniform_grid(alpha):
    a, _, shape = _state(2)
    rng = np.random.default_rng(83)
    for key in ('u', 'v', 'P'):
        a[key][:] = rng.normal(0., .1, a[key].shape)
    a['u'][[0, -1], :] = 0.
    a['rho_field'][:] = rng.uniform(.8, 1.2, shape)
    a['mu_field'][:] = .1
    a['eps_field'][:] = rng.uniform(.4, .8, shape)
    a['outlet_u_frac'][:] = rng.uniform(0., 1., a['outlet_u_frac'].shape)
    a['alpha_u'] = alpha
    for axis, c in enumerate('uv'):
        indices = [range(n) for n in shape]
        indices[axis] = range(1, shape[axis])
        coeff = getattr(k2, f'_{c}_coeffs_df_2d')
        # Advance the independent equation in the same GS order as the sweep.
        frozen = a[c].copy()
        for i, j in product(*indices):
            a.update(i=i, j=j)
            ap, rhs = _call(coeff, a)
            old = a[c][i, j]
            b = _mass_deficit(a, 2, axis, (i, j)) + _sou_compensation(a, 2, axis, (i, j))
            a[c][i, j] = alpha * (rhs + b * old) / (ap + b) + (1. - alpha) * old
        expected = a[c].copy()
        a[c][:] = frozen
        _call(getattr(k2, f'_sweep_{c}_jit_df'), a)
        interior = (slice(1, -1), slice(None)) if c == 'u' else (slice(None), slice(1, -1))
        np.testing.assert_allclose(a[c][interior], expected[interior], rtol=2e-12, atol=1e-14)


def test_w_sou_compensation_retains_the_last_internal_high_face():
    a, _, shape = _state(3)
    a['rho_field'].fill(1.)
    a['w'][:] = np.array([0., 1.7, 1.3, 1., 0.])[None, None, :]
    location = (2, 2, shape[2] - 1)
    a.update(zip('ijk', location))
    a['use_sou'] = 1
    ap, rhs = _call(k3._w_coeffs_df_3d, a)
    old = a['w'][location]
    # The decreasing minmod stencil still reconstructs at this high face;
    # w's existing boundary switch differs from u's and must stay enabled.
    sou_bound = _sou_compensation(a, 3, 2, location)
    assert sou_bound > 0.
    b = _mass_deficit(a, 3, 2, location) + sou_bound
    _call(k3._w_cell_df_3d, a)
    expected = .7 * (rhs + b * old) / (ap + b) + .3 * old
    assert a['w'][location] == pytest.approx(expected, rel=2e-12, abs=1e-14)


def test_single_layer_3d_retains_both_z_walls():
    a, widths, shape = _state(3)
    for key in ('P', 'rho_field', 'mu_eff_field', 'mu_field', 'eps_field', 'u', 'v'):
        a[key] = np.ascontiguousarray(a[key][:, :, :1])
    a['w'] = np.zeros((shape[0], shape[1], 2))
    a['Nz'], a['dz'] = 1, np.array([1.])
    a['K_arr'], a['cF_arr'] = np.ones((shape[0], shape[1], 1)), np.zeros((shape[0], shape[1], 1))
    a['outlet_u_frac'] = np.ones((shape[0] + 1, 1))
    a.update(i=2, j=2, k=0)
    for c in 'uv':
        a[c][:] = 1.
        ap, rhs = _call(getattr(k3, f'_{c}_coeffs_df_3d'), a)
        x = .5 * sum(widths[0][1:3]) if c == 'u' else widths[0][2]
        y = widths[1][2] if c == 'u' else .5 * sum(widths[1][1:3])
        assert ap - rhs == pytest.approx(4. * x * y)
        a[c][:] = 0.


def test_brinkman_square_duct_finer_triplet_keeps_original_order_gate():
    """Actual v coefficients vs the square-duct Brinkman sine series.

    Retain the original 8->16 pre-asymptotic failure (<1.8); the two finer
    refinements have their own unchanged >1.8 gate. This is not HX acceptance.
    """
    from scipy.sparse import lil_matrix
    from scipy.sparse.linalg import spsolve

    errors = []
    for n in (8, 16, 32, 64):
        shape = (n, 3, n)
        a = dict(Nx=n, Ny=3, Nz=n, dx=np.full(n, 1/n),
                 dy=np.full(3, 1/3), dz=np.full(n, 1/n),
                 u=np.zeros((n+1, 3, n)), v=np.zeros((n, 4, n)),
                 w=np.zeros((n, 3, n+1)), P=np.zeros(shape),
                 rho_field=np.zeros(shape), mu_eff_field=np.ones(shape),
                 mu_field=np.ones(shape), eps_field=np.ones(shape),
                 K_arr=np.full(shape, .03), cF_arr=np.zeros(shape),
                 use_sou=0, use_eps=0, j=1)
        a['P'][:] = np.array([2/3, 1/3, 0.])[None, :, None]
        matrix = lil_matrix((n*n, n*n)); b = np.zeros(n*n)
        for i, k in product(range(n), repeat=2):
            row = i*n+k
            a.update(i=i, k=k)
            ap, rhs = _call(k3._v_coeffs_df_3d, a)
            b[row] = rhs
            a['v'][i, :, k] = 1.
            _, r = _call(k3._v_coeffs_df_3d, a)
            a['v'][i, :, k] = 0.
            matrix[row, row] = ap - (r-rhs)
            for ii, kk in ((i-1, k), (i+1, k), (i, k-1), (i, k+1)):
                if 0 <= ii < n and 0 <= kk < n:
                    a['v'][ii, :, kk] = 1.
                    _, r = _call(k3._v_coeffs_df_3d, a)
                    a['v'][ii, :, kk] = 0.
                    matrix[row, ii*n+kk] = -(r-rhs)
        discrete = spsolve(matrix.tocsr(), b).reshape(n, n)
        odd = np.arange(1, 320, 2)
        sine = np.sin(np.pi * ((np.arange(n)+.5)/n)[:, None] * odd[None, :])
        weights = (16. / (np.pi**2 * odd[:, None] * odd[None, :])
                   / (np.pi**2 * (odd[:, None]**2 + odd[None, :]**2) + 1/.03))
        exact = sine @ weights @ sine.T
        errors.append(float(np.linalg.norm(discrete-exact) / np.linalg.norm(exact)))
    orders = np.log2(np.array(errors[:-1]) / errors[1:])
    print({'Brinkman_relative_L2': errors, 'orders': orders.tolist(),
           'coarse_8_to_16_passes_1_8': bool(orders[0] > 1.8)})
    assert np.all(np.diff(errors) < 0.)
    assert np.min(orders[-2:]) > 1.8
    assert errors[-1] < .005
