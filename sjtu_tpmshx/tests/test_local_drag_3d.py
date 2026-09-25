"""Local 3D drag reaches momentum and retains the legacy row convention."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import _kernels_simple_3d as kernels
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _solver(K, cF):
    return SIMPLESolver3D(
        .017, .014, .010, 4, 4, 4, 1.2, 2e-5, 300., .2,
        eps=.7, K_arr=K, cF_arr=cF, fluid_type='incompressible',
        dx_arr=np.array([.002, .003, .005, .007]),
        dy_arr=np.array([.002, .003, .004, .005]),
        dz_arr=np.array([.001, .002, .003, .004]))


def _arguments(s, use_sou=0, use_eps=0):
    return dict(u=s.u, v=s.v, w=s.w, P=s.P, Nx=s.Nx, Ny=s.Ny, Nz=s.Nz,
                dx=s.dx, dy=s.dy, dz=s.dz, rho_field=s.rho_field,
                mu_eff_field=s._mu_eff_field, mu_field=s.mu_field,
                eps_field=s.eps_field, K_arr=s.K_arr, cF_arr=s.cF_arr,
                use_sou=use_sou, use_eps=use_eps)


@pytest.mark.parametrize('parallel,use_sou,use_eps', [
    (False, 0, 0), (False, 0, 1), (False, 1, 0), (False, 1, 1),
    (True, 0, 0), (True, 0, 1),
])
def test_row_input_and_explicit_broadcast_have_identical_sweeps(parallel, use_sou, use_eps):
    # Production keeps SOU serial: distance-two neighbors share a red-black color.
    j, k = np.indices((4, 4))
    K, cF = 1e-7 * (1.0 + .1 * j + .05 * k), 100.0 + 20.0 * j + 5.0 * k
    row = _solver(K, cF)
    full = _solver(np.broadcast_to(K, (4, 4, 4)), np.broadcast_to(cF, (4, 4, 4)))
    rng = np.random.default_rng(32)
    for name in ('u', 'v', 'w', 'P'):
        values = rng.uniform(.1, .3, getattr(row, name).shape)
        getattr(row, name)[:] = values
        getattr(full, name)[:] = values
    if use_eps:
        eps = .5 + .02 * np.indices(row.P.shape).sum(axis=0)
        for solver in (row, full):
            solver.eps_field[:] = eps
            solver._mu_eff_field[:] = solver.mu_field / eps
    for solver in (row, full):
        for component in 'uvw':
            kwargs = _arguments(solver, use_sou, use_eps)
            kwargs.update(alpha_u=.7, n_sweeps=2, **{'d_' + component: getattr(solver, 'd_' + component)})
            if component == 'v':
                kwargs.update(v_inlet_field=solver.v_inlet_field, outlet_mask_ij=solver.outlet_mask_ij)
            else:
                kwargs['outlet_' + component + '_frac'] = getattr(solver, 'outlet_' + component + '_frac')
            name = f'_sweep_{component}_jit_df_3d' + ('_parallel' if parallel else '')
            getattr(kernels, name)(**kwargs)
    for name in ('K_arr', 'cF_arr', 'u', 'v', 'w', 'd_u', 'd_v', 'd_w'):
        np.testing.assert_array_equal(getattr(row, name), getattr(full, name))
    for solver in (row, full):
        assert solver.K_arr.shape == solver.cF_arr.shape == (4, 4, 4)
        assert solver.K_arr.flags.c_contiguous and solver.cF_arr.flags.c_contiguous
    residuals = [kernels._mom_res_jit_3d(**_arguments(s, use_sou, use_eps),
                    outlet_u_frac=s.outlet_u_frac, outlet_w_frac=s.outlet_w_frac)
                 for s in (row, full)]
    np.testing.assert_array_equal(*residuals)


@pytest.mark.parametrize('component', list('uvw'))
def test_transverse_drag_change_reaches_local_face_without_averaging_away(component):
    s = _solver(np.full((4, 4, 4), 1e-7), np.full((4, 4, 4), 100.0))
    s.u[:] = .1
    s.v[:] = .2
    s.w[:] = .3
    s.P[:] = np.indices(s.P.shape).sum(axis=0)
    args = _arguments(s)
    args.update(i=2, j=2, k=2)
    if component != 'v':
        args['outlet_' + component + '_frac'] = getattr(s, 'outlet_' + component + '_frac')
    coefficients = getattr(kernels, f'_{component}_coeffs_df_3d')
    before_ap, before_rhs = coefficients(**args)
    # Only x=2 changes. u averages x=1/2; v/w sample the x=2 cell.
    s.K_arr[2, :, :] = 5e-8
    s.cF_arr[2, :, :] = 200.0
    effective_K = 7.5e-8 if component == 'u' else 5e-8
    effective_cF = 150.0 if component == 'u' else 200.0
    widths = [s.dx[2], s.dy[2], s.dz[2]]
    axis = 'uvw'.index(component)
    widths[axis] = .5 * ((s.dx, s.dy, s.dz)[axis][1] + (s.dx, s.dy, s.dz)[axis][2])
    expected_delta = (2e-5 * (1.0 / effective_K - 1e7)
                      + 1.2 * np.sqrt(.1**2 + .2**2 + .3**2) * (effective_cF - 100.0)) * np.prod(widths)
    after_ap, after_rhs = coefficients(**args)
    assert after_ap - before_ap == pytest.approx(expected_delta, rel=2e-13)
    assert after_rhs == before_rhs
    update = getattr(kernels, f'_{component}_cell_df_3d')
    update(**args, alpha_u=1.0, **{'d_' + component: getattr(s, 'd_' + component)})
    assert getattr(s, component)[2, 2, 2] == pytest.approx(before_rhs / (before_ap + expected_delta))


@pytest.mark.parametrize('K,cF,reason', [
    (None, np.ones((4, 4)), 'both'),
    (np.ones((4, 4)), None, 'both'),
    (np.ones((4, 4, 3)), np.ones((4, 4)), 'shape'),
    (np.ones((4, 4)), np.ones((4, 3)), 'shape'),
    (np.zeros((4, 4)), np.zeros((4, 4)), 'positive'),
    (np.ones((4, 4)), -np.ones((4, 4)), 'nonnegative'),
    (np.full((4, 4), np.nan), np.zeros((4, 4)), 'finite'),
    (np.ones((4, 4)), np.full((4, 4), np.inf), 'finite'),
])
def test_invalid_drag_is_rejected_before_entering_numba(K, cF, reason):
    with pytest.raises(ValueError, match=reason):
        _solver(K, cF)
