"""Pressure-reference outlet cells still need local mass closure."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.solvers._kernels_simple_2d import _correct_jit
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


@pytest.mark.parametrize('east_factor', [-1., 1., 3.])
def test_pressure_outlet_includes_transverse_flux(east_factor):
    # Middle outlet CV: Fs=2.04, Fw=.54, Fe=1.8 kg/s/m.
    # Thus Fn must be .78, giving v_out=.78/(4.8*.3)=13/24.
    rho = np.array([[2., 4.], [4., 6.], [6., 8.]])
    eps = np.array([[.4, .6], [.5, .8], [.7, .9]])
    u = np.zeros((4, 2))
    v = np.zeros((3, 3))
    u[1, -1], u[2, -1] = .25, .5 * east_factor
    v[1, -2] = 2.
    P = np.zeros((3, 2))
    _correct_jit(u, v, P, np.zeros_like(P), np.zeros_like(u), np.zeros_like(v),
                 np.ones(3), np.ones(3), np.array([0., 1., 0.]),
                 3, 2, np.array([.2, .3, .5]), np.array([.4, .6]), .3, rho, eps)
    expected_flux = 2.04 + .54 - 1.8 * east_factor
    assert v[1, -1] == pytest.approx(expected_flux / (4.8 * .3), rel=1e-13)
    assert v[0, -1] == v[2, -1] == 0.

    # Exercise the real solve closeout, not just its preceding kernel.
    # Inlet mass is .8*.2 + 2*.3 + 4.2*.5 = 2.86 kg/s/m, unlike Fn.
    # Scaling Fn to that total would hide the interior defect and undo this CV.
    solver = SimpleNamespace(
        Nx=3, Ny=2, u=u, v=v, rho_field=rho, eps_field=eps,
        dx_arr=np.array([.2, .3, .5]), dy_arr=np.array([.4, .6]),
        outlet_geom_frac=np.array([0., 1., 0.]))
    assert not np.isclose(expected_flux, 2.86)
    SIMPLESolver._enforce_mass_conservation(solver)
    assert solver.v[1, -1] * 4.8 * .3 == pytest.approx(expected_flux, rel=1e-13)
    assert solver.v[0, -1] == solver.v[2, -1] == 0.


@pytest.mark.parametrize('stage', ['sweep', 'correct', 'closeout'])
def test_small_geometric_overlap_owns_pressure_and_normal_flux(stage):
    from sjtu_tpmshx.solvers import _kernels_simple_2d as kernels

    s = SIMPLESolver(1., 1., 3, 2, 'Gyroid', 7., .6, .6, .001,
                     2., .001, 300., 0., 1., .2,
                     fluid_type='incompressible', wall_refine=False)
    s.dx_arr = np.array([.2, .3, .5])
    s.dy_arr = np.array([.4, .6])
    s._refresh_ports(0., 1., .199, .26)
    np.testing.assert_allclose(s.outlet_geom_frac, [.005, .2, 0.], atol=1e-15)
    np.testing.assert_array_equal(s.outlet_mask, [True, True, False])
    sparsity = kernels._build_pp_sparsity_pattern(3, 2, s.outlet_geom_frac)
    np.testing.assert_array_equal(sparsity['cell_kind'].reshape(3, 2)[:, -1], [1, 1, 0])
    s.v[:, -2] = 2.
    s.rho_field[:, -1] = 4.
    s.eps_field[:, -1] = .4
    # South er=.5*(2*.6+4*.4)=1.4; north er=1.6. Neither area nor
    # taper multiplies velocity a second time; both open CVs close locally.
    if stage == 'correct':
        s.Pp[:] = 1.
        kernels._correct_jit(s.u, s.v, s.P, s.Pp, s.d_u, s.d_v,
                             s.inlet_frac, s.v_inlet_field, s.outlet_geom_frac,
                             3, 2, s.dx_arr, s.dy_arr, .3, s.rho_field, s.eps_field)
        np.testing.assert_array_equal(s.P[:, -1], [0., 0., .3])
    elif stage == 'closeout':
        s._enforce_mass_conservation()
    elif stage == 'sweep':
        kernels._sweep_v_jit_df(s.u, s.v, s.P, s.d_v, s.inlet_frac,
                                s.v_inlet_field, s.outlet_geom_frac, 3, 2,
                                s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                                np.ones((3, 2)), np.zeros((3, 2)), s.mu_field,
                                s.eps_field, .5, 0, 0.)
    np.testing.assert_allclose(s.v[:, -1], [2.*1.4/1.6, 2.*1.4/1.6, 0.])
