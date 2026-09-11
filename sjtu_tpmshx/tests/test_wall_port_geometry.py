"""Rectangular edges must reach the actual primary and staggered grids."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


@pytest.mark.parametrize('array_inlet', [False, True])
def test_constructor_inlet_velocity_contains_open_fraction_once(array_inlet):
    dx = np.array([.1, .2, .3, .4])
    dz = np.array([.2, .3, .5])
    # Both transverse edges cut cells; the last x/z cells are fully closed.
    fraction = np.outer([.5, 1., 1/6, 0.], [.5, 1., 0.])
    velocity = 2. * fraction
    prescribed = velocity.copy() if array_inlet else 2.
    s = SIMPLESolver3D(1., 1., 1., 4, 2, 3, 3., 1e-3, 300., prescribed,
                      eps=.7, dx_arr=dx, dz_arr=dz,
                      inlet_rect=(.05, .35, .1, .5))
    np.testing.assert_allclose(s.inlet_frac, fraction, rtol=0, atol=1e-15)
    np.testing.assert_allclose(s.v_inlet_field, velocity, rtol=0, atol=1e-15)
    np.testing.assert_array_equal(s.v[:, 0, :], s.v_inlet_field)
    assert np.all(s.v_inlet_field[fraction == 0.] == 0.)
    area = dx[:, None] * dz[None, :]
    assert np.sum(s.eps_field[:, 0, :] * s.rho_field[:, 0, :]
                  * s.v[:, 0, :] * area) == pytest.approx(.7 * 3. * 2. * .3 * .4)
    # Geometry refresh must not multiply a prescribed face average again.
    before = s.v_inlet_field.copy()
    s.set_ports(s.inlet_rect, s.outlet_rect)
    np.testing.assert_array_equal(s.v_inlet_field, before)
    if array_inlet:
        np.testing.assert_array_equal(prescribed, velocity)


@pytest.mark.parametrize('array_inlet', [False, True])
def test_port_reuse_preserves_inlet_ownership(array_inlet):
    prescribed = np.array([[.5], [1.5]]) if array_inlet else 2.
    s = SIMPLESolver3D(1., 1., 1., 2, 2, 1, 3., .001, 300., prescribed)
    if array_inlet:
        s._massflux_target = 3. * prescribed
    full = (0., 1., 0., 1.)
    for rect, fraction in [((.1, .4, 0., 1.), [.6, 0.]),
                           ((.6, .9, 0., 1.), [0., .6]),
                           ((.6, .9, 0., 1.), [0., .6]),
                           (full, [1., 1.])]:
        s.set_ports(rect, full)
        expected = prescribed if array_inlet else 2. * np.array(fraction)[:, None]
        np.testing.assert_allclose(s.v_inlet_field, expected, rtol=0, atol=1e-15)
        np.testing.assert_array_equal(s.v[:, 0, :], s.v_inlet_field)
    if array_inlet:
        np.testing.assert_array_equal(prescribed, [[.5], [1.5]])
        np.testing.assert_array_equal(s._massflux_target, 3. * prescribed)


def test_scalar_port_change_after_massflux_capture_is_atomic():
    s = SIMPLESolver3D(1., 1., 1., 2, 2, 1, 3., .001, 300., 2.)
    s._massflux_target = s.v_inlet_field * s.rho_field[:, 0, :]
    s.rho_field *= 2.
    s._apply_massflux_inlet()
    s.v[:, 0, :] = s.v_inlet_field
    field, target = s.v_inlet_field.copy(), s._massflux_target.copy()
    # Same inlet, including an outlet-only change, preserves the captured state.
    s.set_ports(s.inlet_rect, s.outlet_rect)
    s.set_ports(s.inlet_rect, (0., .5, 0., 1.))
    np.testing.assert_array_equal(s.v_inlet_field, field)
    np.testing.assert_array_equal(s._massflux_target, target)
    before = {key: value.copy() if isinstance(value, np.ndarray) else value
              for key, value in vars(s).items()}
    with pytest.raises(ValueError, match='new solver.*reference state'):
        s.set_ports((.5, 1., 0., 1.), (0., 1., 0., 1.))
    assert vars(s).keys() == before.keys()
    for key, value in before.items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(vars(s)[key], value)
        else:
            assert vars(s)[key] == value


def test_case16_staggered_outlet_is_not_an_average_of_primary_fractions():
    s = SIMPLESolver3D(.182, .042, .042, 20, 10, 3, 1., 1e-3, 300., 1.,
                      inlet_rect=(.007, .049, 0., .042),
                      outlet_rect=(.133, .175, 0., .042))
    np.testing.assert_allclose(s.outlet_u_frac[[14, 15, 19], :],
                               np.tile([[0.], [23/26], [19/26]], (1, 3)),
                               rtol=0, atol=5e-14)
    before = s.outlet_u_frac.copy(), s.outlet_w_frac.copy()
    s.apply_outlet_taper()
    np.testing.assert_array_equal(s.outlet_u_frac, before[0])
    np.testing.assert_array_equal(s.outlet_w_frac, before[1])


def test_equal_primary_fractions_can_have_different_staggered_openings():
    solvers = [SIMPLESolver3D(2., 2., 1., 2, 2, 1, 1., 1., 300., 1.,
                              outlet_rect=(*bounds, 0., 1.))
               for bounds in ((.1, .5), (.5, .9))]
    np.testing.assert_allclose(solvers[0].outlet_frac, solvers[1].outlet_frac)
    assert solvers[0].outlet_u_frac[1, 0] == 0.
    assert solvers[1].outlet_u_frac[1, 0] == pytest.approx(.4)


@pytest.mark.parametrize('direction', range(6))
def test_nonuniform_rectangles_follow_real_direction_mapping(direction):
    from sjtu_tpmshx.models.grid_3d import _resolve_axis_map
    from sjtu_tpmshx.models.field_coordinates_3d import _port_rectangles
    widths = [np.array([.003, .007, .008, .012]),
              np.array([.004, .009, .017]), np.array([.011, .019])]
    f = dict(dir=direction, in_ctr=.009, in_w=.010,
             out_ctr=.019, out_w=.010,
             in_z_ctr=.014, in_z_w=.013, out_z_ctr=.01, out_z_w=.004)
    a = _resolve_axis_map(f, 4, 3, 2, .03, .03, .03, *widths)
    perm = a['solver_to_real_perm']
    # Existing permutations are self-inverse; only the flow axis reverses.
    dx, dy, dz = [widths[i] for i in perm]
    if a['is_reverse']:
        dy = dy[::-1].copy()
    s = SIMPLESolver3D(**a['solver_init'], rho=1., mu=1e-3, T_in=300.,
                      v_inlet=1., dx_arr=dx, dy_arr=dy, dz_arr=dz,
                      **_port_rectangles(f, dz.sum()))
    assert s.inlet_rect == pytest.approx((.004, .014, .0075, .0205))
    assert s.outlet_rect == pytest.approx((.014, .024, .008, .012))
    xc, zc = np.cumsum(dx) - dx/2, np.cumsum(dz) - dz/2
    # Independent per-cell rectangle clipping, including both staggered axes.
    for fractions, xedges, zedges in (
        (s.outlet_frac, np.r_[0., np.cumsum(dx)], np.r_[0., np.cumsum(dz)]),
        (s.outlet_u_frac, np.r_[0., xc, dx.sum()], np.r_[0., np.cumsum(dz)]),
        (s.outlet_w_frac, np.r_[0., np.cumsum(dx)], np.r_[0., zc, dz.sum()]),
    ):
        for i in range(len(xedges)-1):
            for k in range(len(zedges)-1):
                x_overlap = max(0., min(xedges[i+1], .024) - max(xedges[i], .014))
                z_overlap = max(0., min(zedges[k+1], .012) - max(zedges[k], .008))
                area = (xedges[i+1]-xedges[i]) * (zedges[k+1]-zedges[k])
                assert fractions[i, k] == pytest.approx(x_overlap*z_overlap/area, abs=2e-14)


def test_2d_port_refresh_rebuilds_geometry_on_final_grid():
    s = SIMPLESolver(.182, .042, 20, 10, 'Gyroid', 7., .6, .7, .001,
                     1., 1e-3, 300., 0., .182, 1., wall_refine=False)
    s.dx_arr = np.full(20, .0091)
    s._refresh_ports(.007, .049, .133, .175)
    assert s.inlet_geom_frac @ s.dx_arr == pytest.approx(.042)
    assert s.outlet_geom_frac @ s.dx_arr == pytest.approx(.042)
    np.testing.assert_allclose(s.outlet_u_frac[[14, 15, 19]], [0., 23/26, 19/26],
                               rtol=0, atol=5e-14)
    assert np.any(s.inlet_geom_frac != s.inlet_frac)
    assert s.v[:, 0] @ s.dx_arr == pytest.approx(.042)
