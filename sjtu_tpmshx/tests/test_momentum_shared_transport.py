"""Independent finite-volume checks on the staggered momentum equations."""
import inspect
from itertools import product

import numpy as np
import pytest

from sjtu_tpmshx.solvers import _kernels_simple_2d as k2
from sjtu_tpmshx.solvers import _kernels_simple_3d as k3


def _state(dim):
    shape = (7,) * dim
    a = dict(P=np.zeros(shape), rho_field=np.ones(shape),
             mu_eff_field=np.ones(shape), mu_field=np.ones(shape),
             eps_field=np.ones(shape), K_arr=np.ones(shape),
             cF_arr=np.zeros(shape), cf_aniso=0., use_sou=0, use_eps=1,
             i=3, j=3, k=3)
    for axis, c in enumerate('uvw'[:dim]):
        n = list(shape)
        n[axis] += 1
        a[c] = np.zeros(n)
        a['N' + 'xyz'[axis]] = 7
        a['d' + 'xyz'[axis] + ('_arr' if dim == 2 else '')] = np.ones(7)
    a['outlet_u_frac'] = np.ones((8,) + shape[2:])
    if dim == 3:
        a['outlet_w_frac'] = np.ones((7, 8))
    return a


def _coeff(dim, c, a):
    fn = getattr(k2 if dim == 2 else k3, f'_{c}_coeffs_df_{dim}d')
    return fn(**{key: a[key] for key in inspect.signature(fn).parameters})


@pytest.mark.parametrize('dim,c', [(2, 'u'), (2, 'v'), (3, 'u'), (3, 'v'), (3, 'w')])
def test_linear_viscosity_and_velocity_have_their_analytic_normal_diffusion(dim, c):
    a = _state(dim)
    axis = 'uvw'.index(c)
    line_shape = [1] * dim
    line_shape[axis] = 8
    a[c][:] = np.arange(8.).reshape(line_shape)
    values = []
    line_shape[axis] = 7
    for mu in (np.ones((7,) * dim),
               np.broadcast_to((1.5 + np.arange(7.)).reshape(line_shape), (7,) * dim).copy()):
        a['mu_eff_field'] = mu
        ap, rhs = _coeff(dim, c, a)
        values.append(rhs - ap * a[c][(3,) * dim])
    # All non-diffusive terms are identical and cancel in the difference.
    # Integral d/dx((1+x)*d(x)/dx) over this unit CV is exactly 1.
    assert values[1] - values[0] == pytest.approx(1., abs=3e-13)


@pytest.mark.parametrize('dim,c', [(2, 'u'), (2, 'v'), (3, 'u'), (3, 'v'), (3, 'w')])
def test_primary_constant_mass_flow_reaches_both_sides_of_a_momentum_face(dim, c):
    a = _state(dim)
    axis = 'uvw'.index(c)
    rho = 1.5 + np.arange(7.)
    rho_face = np.r_[rho[0], .5 * (rho[:-1] + rho[1:]), rho[-1]]
    line_shape = [1] * dim
    line_shape[axis] = 8
    velocity = np.broadcast_to((1. / rho_face).reshape(line_shape), a[c].shape).copy()
    line_shape[axis] = 7
    variable_rho = np.broadcast_to(rho.reshape(line_shape), (7,) * dim).copy()
    # In the conservative stencil, aP has the OUTFLOW coefficient. For the
    # two signs below, that isolates this shared interface. The baseline has
    # rho=1 and its face mass flux is the arithmetic mean of these velocities.
    shared_baseline = .5 * (1. / rho_face[3] + 1. / rho_face[4])
    got = []
    for row, sign in ((3, 1.), (4, -1.)):
        a['ijk'[axis]] = row
        a[c] = sign * velocity
        a['rho_field'] = np.ones((7,) * dim)
        base = _coeff(dim, c, a)[0]
        a['rho_field'] = variable_rho
        actual = _coeff(dim, c, a)[0]
        got.append(actual - base + shared_baseline)
    np.testing.assert_allclose(got, [1., 1.], rtol=0, atol=3e-13)


def _transport(dim, c, a):
    fn = getattr(k2 if dim == 2 else k3, f'_{c}_transport_{dim}d')
    args = dict(a)
    if dim == 2:
        args.update(dx=a['dx_arr'], dy=a['dy_arr'])
    return np.asarray(fn(**{key: args[key] for key in inspect.signature(fn).parameters}))


def _widths(dim, a):
    return [a['d' + x + ('_arr' if dim == 2 else '')] for x in 'xyz'[:dim]]


def _stretched_variable_state(dim):
    a = _state(dim)
    coords = np.indices((7,) * dim)
    a['eps_field'] = .4 + sum(.015 * (q + 1) * coords[q] for q in range(dim))
    a['rho_field'] = .8 + sum(.025 * (q + 1) * coords[q] for q in range(dim))
    a['mu_field'] = 1. + sum(.2 * (q + 1) * coords[q] for q in range(dim))
    a['mu_eff_field'] = a['mu_field'] / a['eps_field']
    for q, x in enumerate('xyz'[:dim]):
        a['d' + x + ('_arr' if dim == 2 else '')] = (
            np.array([.1, .3, .2, .6, .4, .8, .7]) * (1 + q * .3))
    for q, c in enumerate('uvw'[:dim]):
        grid = np.indices(a[c].shape)
        a[c][:] = .5 + sum(.01 * (r + 1) * grid[r] for r in range(dim))
        if q != 1:
            sl = [slice(None)] * dim
            sl[q] = [0, -1]
            a[c][tuple(sl)] = 0.
    return a


def _eps_cv(a, component, location):
    previous = list(location)
    previous[component] -= 1
    return .5 * (a['eps_field'][tuple(previous)] + a['eps_field'][tuple(location)])


def _primary_mass_faces(dim, a):
    """Independent integrated primary fluxes used by finite-volume continuity."""
    er = a['eps_field'] * a['rho_field']
    widths = _widths(dim, a)
    flows = []
    for q, c in enumerate('uvw'[:dim]):
        density = np.empty_like(a[c])
        low = [slice(None)] * dim
        high = low.copy()
        mid = low.copy()
        low[q], high[q], mid[q] = slice(None, -1), slice(1, None), slice(1, -1)
        density[tuple(mid)] = .5 * (er[tuple(low)] + er[tuple(high)])
        for end in (0, -1):
            edge = [slice(None)] * dim
            edge[q] = end
            density[tuple(edge)] = er[tuple(edge)]
        flow = density * a[c]
        for transverse in range(dim):
            if transverse != q:
                shape = [1] * dim
                shape[transverse] = 7
                flow *= widths[transverse].reshape(shape)
        flows.append(flow)
    return flows


def _dual_mass_faces(dim, a, component, location):
    primary = _primary_mass_faces(dim, a)
    faces = []
    for q in range(dim):
        for high in (True, False):
            left, right = list(location), list(location)
            if q == component:
                left[q] += 0 if high else -1
                right[q] += 1 if high else 0
            else:
                left[component] -= 1
                left[q] += int(high)
                right[q] += int(high)
            # The dual face contains exactly one half of each primary face.
            faces.append(.5 * (primary[q][tuple(left)] + primary[q][tuple(right)]))
    return np.array(faces)


_COMPONENT_AXES = [(dim, c, q) for dim in (2, 3)
                   for c, q in product('uvw'[:dim], range(dim))]


@pytest.mark.parametrize('dim,c,q', _COMPONENT_AXES)
def test_viscous_face_is_shared_and_matches_series_subface_resistances(dim, c, q):
    a = _stretched_variable_state(dim)
    axis = 'uvw'.index(c)
    location = [3] * dim
    eps_left = _eps_cv(a, axis, location)
    left = _transport(dim, c, a)[2 * q] * eps_left
    widths = _widths(dim, a)
    if q == axis:
        area = np.prod([widths[r][3] for r in range(dim) if r != q])
        expected = a['mu_field'][tuple(location)] * area / widths[q][3]
    else:
        expected = 0.
        for comp_index in (2, 3):
            low, high = location.copy(), location.copy()
            low[axis] = high[axis] = comp_index
            high[q] += 1
            area = .5 * widths[axis][comp_index]
            area *= np.prod([widths[r][3] for r in range(dim) if r not in (axis, q)])
            resistance = (.5 * widths[q][3] / a['mu_field'][tuple(low)]
                          + .5 * widths[q][4] / a['mu_field'][tuple(high)])
            expected += area / resistance
    a['ijk'[q]] += 1
    location[q] += 1
    right = _transport(dim, c, a)[2 * q + 1] * _eps_cv(a, axis, location)
    assert left == pytest.approx(expected, rel=2e-14)
    assert right == pytest.approx(expected, rel=2e-14)


@pytest.mark.parametrize('dim,c,q', _COMPONENT_AXES)
def test_mass_face_is_shared_after_epsilon_restore_and_matches_primary_fluxes(dim, c, q):
    a = _stretched_variable_state(dim)
    axis = 'uvw'.index(c)
    location = [3] * dim
    left = _transport(dim, c, a)[dim * 2 + 2 * q] * _eps_cv(a, axis, location)
    expected = _dual_mass_faces(dim, a, axis, location)[2 * q]
    a['ijk'[q]] += 1
    location[q] += 1
    right = _transport(dim, c, a)[dim * 2 + 2 * q + 1] * _eps_cv(a, axis, location)
    assert left == pytest.approx(expected, rel=2e-14)
    assert right == pytest.approx(expected, rel=2e-14)


@pytest.mark.parametrize('dim,c', [(2, 'u'), (2, 'v'), (3, 'u'), (3, 'v'), (3, 'w')])
def test_staggered_mass_divergence_is_half_the_adjacent_primary_balances(dim, c):
    a = _stretched_variable_state(dim)
    axis = 'uvw'.index(c)
    primary = _primary_mass_faces(dim, a)
    balance = sum(np.diff(flow, axis=q) for q, flow in enumerate(primary))
    low, high = [3] * dim, [3] * dim
    low[axis] -= 1
    expected = .5 * (balance[tuple(low)] + balance[tuple(high)])
    faces = _transport(dim, c, a)[dim * 2:] * _eps_cv(a, axis, high)
    assert sum(faces[::2] - faces[1::2]) == pytest.approx(expected, abs=2e-15)


@pytest.mark.parametrize('dim,c,sign', [(dim, c, sign) for dim in (2, 3)
                         for c, sign in product('uvw'[:dim], (-1., 1.))])
def test_affine_velocity_conservative_equation_on_stretched_grid(dim, c, sign):
    a = _stretched_variable_state(dim)
    widths = _widths(dim, a)
    edges = [np.r_[0., np.cumsum(w)] for w in widths]
    centres = [.5 * (e[:-1] + e[1:]) for e in edges]
    slopes = np.arange(1, dim + 1) * .2
    for component, name in enumerate('uvw'[:dim]):
        positions = [edges[q] if q == component else centres[q] for q in range(dim)]
        mesh = np.meshgrid(*positions, indexing='ij')
        a[name][:] = sign * (2. + sum(slopes[q] * mesh[q] for q in range(dim)))
        if component != 1:
            wall = [slice(None)] * dim
            wall[component] = [0, -1]
            a[name][tuple(wall)] = 0.
    # Isolate the conservative advection operator without changing its FOU/SOU
    # construction. Zero viscosity/drag is only an algebraic term isolation.
    a['mu_field'].fill(0.)
    a['mu_eff_field'].fill(0.)
    a['use_sou'] = 1
    component = 'uvw'.index(c)
    location = [3] * dim
    fluxes = _dual_mass_faces(dim, a, component, location) / _eps_cv(a, component, location)
    expected = 0.
    for q in range(dim):
        for high in (True, False):
            point = [edges[r][3] if r == component else centres[r][3] for r in range(dim)]
            point[q] = (centres[q][3 if high else 2] if q == component
                        else edges[q][4 if high else 3])
            value = sign * (2. + np.dot(slopes, point))
            expected += (1. if high else -1.) * fluxes[2*q + int(not high)] * value
    ap, rhs = _coeff(dim, c, a)
    assert ap * a[c][tuple(location)] - rhs == pytest.approx(expected, abs=3e-13)


@pytest.mark.parametrize('dim', [2, 3])
def test_stationary_interior_with_finite_inlet_reaches_a_conservative_solution(dim):
    """A deficient initial iterate must not turn finite inlet flow into NaN.

    This starts with zero internal transport, the state in which the physical
    outgoing-flow diagonal is small. Iteration compensation must disappear
    from the certified steady momentum equation.
    """
    if dim == 2:
        from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
        s = SIMPLESolver(
            W=.02, H=.03, Nx=6, Ny=10, tpms_type='Gyroid',
            L_cell_mm=7., t_mm=.6, eps=.72, r_h=1e-3,
            rho=1.18, mu=1.85e-5, T_in=300., inlet_lo=0.,
            inlet_hi=.02, v_inlet=2., fluid_type='incompressible',
            wall_refine=False)
    else:
        from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
        s = SIMPLESolver3D(
            Lx=.02, Ly=.03, Lz=.01, Nx=6, Ny=10, Nz=4,
            rho=1.18, mu=1.85e-5, T_in=300., v_inlet=2., eps=.72,
            K_arr=np.full((10, 4), 3e-8), cF_arr=np.full((10, 4), 250.),
            fluid_type='incompressible')
    s.mom_tol = 1e-4
    s.mass_local_tol = s.mass_global_tol = 1e-6
    s.v[:, 1:, ...] = 0.
    converged, _ = s.solve(max_iter=500, verbose=False)
    assert converged
    assert s.exit_reason == 'tol'
    assert s.f2_cert_post_rescale_ok
    assert np.isfinite(s.v).all()
    assert s.final_res_mom < s.mom_tol
    assert s.final_res_mass_local < s.mass_local_tol
    assert s.final_res_mass_global < s.mass_global_tol


@pytest.mark.parametrize('staggered,sign,outgoing_high', product((False, True), (-1., 1.), (False, True)))
def test_sou_diagonal_bounds_actual_fixed_flux_source_derivative(staggered, sign, outgoing_high):
    widths = np.array([.2, .7, .3, .5, .4])
    i = 2
    edges = np.r_[0., np.cumsum(widths)]
    nodes = edges if staggered else .5 * (edges[:-1] + edges[1:])
    dm, dp = nodes[i] - nodes[i-1], nodes[i+1] - nodes[i]
    distance = (.5 * (dp if outgoing_high else dm) if staggered else .5 * widths[i])
    lo, hi = (0., 2.) if outgoing_high else (-2., 0.)
    expected_bound = 2. * distance / (dm if outgoing_high else dp)
    # Test each smooth minmod branch, both sides of its switch, and a strict
    # extremum. The bound is local to a monotone stencil, not a global Jacobian.
    for gm, gp in ((1., 2.), (2., 1.), (1., 1.001), (1.001, 1.), (1., -2.)):
        pm, pc, pp = -sign * gm * dm, 0., sign * gp * dp
        def source(value):
            return k2._sou_axis(pm-1., pm, value, pp, pp+1.,
                                True, True, True, True, lo, hi, widths, i, staggered)
        h = 1e-7
        derivative = (source(pc+h) - source(pc-h)) / (2*h)
        bound = k2._sou_diagonal_bound(pm, pc, pp, True, True, lo, hi, widths, i, staggered)
        # Numba prange can supply uint64 even though neighbouring indices need
        # subtraction. This must compile to integer array indices as well.
        unsigned_bound = k2._sou_diagonal_bound(
            pm, pc, pp, True, True, lo, hi, widths, np.uint64(i), staggered)
        assert unsigned_bound == bound
        assert bound == pytest.approx(expected_bound if gm * gp > 0. else 0., abs=1e-14)
        assert bound >= -derivative - 1e-8
        negative_branch = gm < gp if outgoing_high else gp < gm
        if gm * gp > 0. and negative_branch:
            assert bound == pytest.approx(-derivative, abs=1e-8)
        assert k2._sou_diagonal_bound(pm, pc, pp, False, False, lo, hi, widths, i, staggered) == 0.


def test_wall_refined_air_case_all_simple_solves_pass_original_gates(monkeypatch):
    """Two inner SOU sweeps must not conceal the observed alternating cycle."""
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
    from sjtu_tpmshx.tests.test_cooperative_cancel import _cfg

    original = SIMPLESolver.solve
    certificates = []
    def observe(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        certificates.append((result[0], self.exit_reason, self.final_res_mom,
                             self.mom_tol, self.final_res_mass_local, self.mass_local_tol,
                             self.final_res_mass_global, self.mass_global_tol))
        return result
    monkeypatch.setattr(SIMPLESolver, 'solve', observe)
    result = run_case(prepare_case(_cfg(), case_id='sou-wall-refined-regression'))
    assert result.run_status['converged']
    assert len(certificates) >= 4  # Initial A/B plus at least one outer refresh.
    for ok, reason, momentum, mom_tol, local, local_tol, global_mass, global_tol in certificates:
        assert ok and reason == 'tol'
        assert momentum < mom_tol
        assert local < local_tol
        assert global_mass < global_tol
