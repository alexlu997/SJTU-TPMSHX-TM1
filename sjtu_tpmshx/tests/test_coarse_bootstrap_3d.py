"""Coarse-grid bootstrap (Phase C) regression tests."""
from __future__ import annotations
import warnings

import numpy as np
import pytest

warnings.filterwarnings('ignore')

from sjtu_tpmshx.solvers.coarse_bootstrap_3d import (
    bootstrap_simple_3d, _block_average_3d,
    _trilinear_zoom)
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _build_solver():
    # All axes ≥ 8 so coarse 2× halving stays ≥ 4 (min_coarse_axis gate).
    Nx, Ny, Nz = 16, 12, 8
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=350.0, v_inlet=3.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)


def _trace_solver(n=26, enabled=True):
    return SIMPLESolver3D(.1, .1, .1, n, n, n, 1., 2e-5, 300., 1.,
                         eps=.78, K_arr=np.full((n, n, n), 1e-7),
                         cF_arr=np.full((n, n, n), 340.),
                         fluid_type='incompressible', use_coarse_bootstrap=enabled)


def test_recursive_trace_keeps_actual_child_iterations_and_separate_caps(monkeypatch):
    original = SIMPLESolver3D.solve
    observed = {}

    def solve(solver, *args, **kwargs):
        returned = original(solver, *args, **kwargs)
        observed[(solver.Nx, solver.Ny, solver.Nz)] = (kwargs['max_iter'], returned[1], solver.exit_reason)
        return returned

    monkeypatch.setattr(SIMPLESolver3D, 'solve', solve)
    fine = _trace_solver()
    summary = bootstrap_simple_3d(fine, max_iter_coarse=3)
    trace = fine._coarse_bootstrap_trace
    assert summary['coarse_iters'] == 3  # Legacy first-level summary stays unchanged.
    assert [row['depth'] for row in trace['levels']] == [1, 2]
    assert [row['coarse_shape'] for row in trace['levels']] == [(13, 13, 13), (6, 6, 6)]
    assert [row['iteration_cap'] for row in trace['levels']] == [3, 200]
    for row in trace['levels']:
        assert (row['iteration_cap'], row['charged_iterations'], row['stop']) == observed[row['coarse_shape']]
        assert row['solve_started'] and row['applied']
    assert trace['actual_levels'] == 2 and trace['started_cap_sum'] == 203
    assert trace['total_charged_iterations'] == sum(value[1] for value in observed.values()) > 3


def test_deep_cancel_trace_does_not_charge_unstarted_parent(monkeypatch):
    from sjtu_tpmshx.domain.cancellation import CancelledError
    from sjtu_tpmshx.solvers import simple_solver_3d
    original = simple_solver_3d._correct_jit_3d
    corrected = []

    def correct(*args):
        original(*args)
        corrected.append(True)

    monkeypatch.setattr(simple_solver_3d, '_correct_jit_3d', correct)
    fine = _trace_solver()
    with pytest.raises(CancelledError):
        bootstrap_simple_3d(fine, max_iter_coarse=7, cancel_check=lambda: bool(corrected))
    trace = fine._coarse_bootstrap_trace
    assert corrected == [True]
    assert trace['decision'] == 'cancelled'
    assert [row['solve_started'] for row in trace['levels']] == [False, True]
    assert [row['charged_iterations'] for row in trace['levels']] == [0, 1]
    assert [row['stop'] for row in trace['levels']] == ['cancelled', 'cancelled']
    assert trace['actual_levels'] == 1 and trace['started_cap_sum'] == 200
    assert trace['total_charged_iterations'] == 1


def test_failed_iteration_trace_counts_work_without_claiming_seed(monkeypatch):
    from sjtu_tpmshx.solvers import simple_solver_3d

    def failed_correction(*args):
        raise RuntimeError('coarse correction failure')

    monkeypatch.setattr(simple_solver_3d, '_correct_jit_3d', failed_correction)
    fine = _trace_solver(8)
    with pytest.raises(RuntimeError, match='coarse correction failure'):
        bootstrap_simple_3d(fine, max_iter_coarse=7)
    trace = fine._coarse_bootstrap_trace
    assert trace['decision'] == 'error'
    assert trace['total_charged_iterations'] == 1 and trace['started_cap_sum'] == 7
    assert trace['levels'][0]['stop'] == 'error'
    assert trace['levels'][0]['solve_started'] and not trace['levels'][0]['applied']


@pytest.mark.parametrize('enabled,decision', [(False, 'disabled'), (None, 'auto-threshold'), (True, 'coarse-too-small')])
def test_skipped_trace_never_invents_work(enabled, decision):
    fine = _trace_solver(4, enabled)
    fine.solve(max_iter=1)
    trace = fine._coarse_bootstrap_trace
    assert trace['decision'] == decision
    assert trace['actual_levels'] == trace['started_cap_sum'] == trace['total_charged_iterations'] == 0
    assert all(not row['solve_started'] and not row['applied'] for row in trace['levels'])
    first = trace.copy()
    fine.solve(max_iter=1)
    assert fine._coarse_bootstrap_trace == first  # Warm starts keep the actual initialization evidence.


def test_block_average_3d_shape():
    arr = np.arange(2 * 4 * 6, dtype=float).reshape(2, 4, 6)
    out = _block_average_3d(arr, 1, 2, 2)
    assert out.shape == (2, 2, 3)


def test_trilinear_zoom_preserves_constant():
    arr = np.full((6, 4, 3), 7.5)
    out = _trilinear_zoom(arr, (12, 8, 6))
    assert out.shape == (12, 8, 6)
    np.testing.assert_allclose(out, 7.5, atol=1e-9)


def test_bootstrap_skips_too_small_grid():
    """Coarse axis < 4 → bootstrap skipped, no exception."""
    Nx, Ny, Nz = 6, 6, 4   # Nz//2=2 < min_coarse_axis=4
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    s = SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=350.0, v_inlet=3.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)
    info = bootstrap_simple_3d(s)
    assert info['applied'] is False
    assert info['reason'] == 'coarse-too-small'


def test_bootstrap_seeds_fine_velocity_field():
    """After bootstrap, fine v[:, 0, :] equals inlet BC and field is
    not all-zero (cold-start would leave it zero outside the inlet)."""
    s = _build_solver()
    info = bootstrap_simple_3d(s, max_iter_coarse=50)
    assert info['applied'] is True
    assert info['coarse_shape'] == (8, 6, 4)
    # Fine v field should not be all zeros after prolongation.
    assert np.any(np.abs(s.v) > 1e-6)
    # Inlet BC re-imposed exactly.
    np.testing.assert_allclose(s.v[:, 0, :], s.v_inlet_field, atol=1e-12)


def test_bootstrap_solver_matches_baseline_converged_state():
    """Bootstrapped solver must reach the same converged state as the
    cold-start baseline (zero precision loss)."""
    s_cold = _build_solver()
    conv_c, it_c = s_cold.solve(max_iter=400)
    assert conv_c, "Cold-start baseline did not converge"

    s_warm = _build_solver()
    s_warm.use_coarse_bootstrap = True
    s_warm.coarse_bootstrap_max_iter = 80
    conv_w, it_w = s_warm.solve(max_iter=400)
    assert conv_w, "Bootstrap-warmed solver did not converge"

    # Coarse bootstrap should at minimum not slow cold-start; ideally faster.
    # Allow some slack since this is a small test grid.
    assert it_w <= it_c + 30, (
        f"Bootstrap slowed solver: warm {it_w} vs cold {it_c} iters")

    # Final fields must agree (Anderson rollback / Phase A both preserve
    # final attractor; bootstrap is only an init perturbation).
    np.testing.assert_allclose(s_cold.u, s_warm.u, rtol=2e-2, atol=1e-3)
    np.testing.assert_allclose(s_cold.v, s_warm.v, rtol=2e-2, atol=1e-3)


@pytest.mark.parametrize('bootstrap', [False, True])
def test_cancel_after_real_iteration_stops_before_next_sweep(monkeypatch, bootstrap):
    from sjtu_tpmshx.domain.cancellation import CancelledError
    from sjtu_tpmshx.solvers import simple_solver_3d, coarse_bootstrap_3d
    solver = _build_solver()
    solver.use_coarse_bootstrap = bootstrap
    original = simple_solver_3d._correct_jit_3d
    corrections = []

    def correct(*args, **kwargs):
        result = original(*args, **kwargs)
        corrections.append(True)
        return result

    def forbidden(*args):
        pytest.fail('cancelled coarse fields were prolonged into the fine solver')

    monkeypatch.setattr(simple_solver_3d, '_correct_jit_3d', correct)
    monkeypatch.setattr(coarse_bootstrap_3d, '_trilinear_zoom', forbidden)
    with pytest.raises(CancelledError):
        solver.solve(cancel_check=lambda: bool(corrections))
    assert corrections == [True]
    assert solver.exit_reason == 'cancelled'
    assert solver.residuals == []  # Cancellation now precedes residual kernels.
    assert solver._iterations_charged == (0 if bootstrap else 1)


def test_bootstrap_rebuilds_rectangles_and_conserves_inlet_mass(monkeypatch):
    # Odd, nonuniform axes deliberately cut the opening in different fine and
    # coarse cells. Mock only solve: all real setup and transfer run normally.
    widths = [np.linspace(.3, 1.7, n) / n for n in (9, 9, 11)]
    fine = SIMPLESolver3D(1., 1., 1., 9, 9, 11, 2., .01, 300., 0.,
                         eps=.6, fluid_type='incompressible',
                         dx_arr=widths[0], dy_arr=widths[1], dz_arr=widths[2],
                         inlet_rect=(.61, .97, .13, .86),
                         outlet_rect=(.08, .42, .23, .93))
    fine.rho_field[:] = np.linspace(1., 3., 9)[:, None, None]
    fine.eps_field[:] = np.linspace(.4, .7, 11)[None, None, :]
    fine.v_inlet_field = fine.inlet_frac * np.linspace(.5, 1.5, 11)[None, :]
    fine._massflux_target = fine.rho_field[:, 0, :] * fine.v_inlet_field
    target = np.sum(fine._massflux_target * fine.eps_field[:, 0, :]
                    * fine.dx[:, None] * fine.dz[None, :])
    seen = []

    def solve(coarse, **kwargs):
        seen.append(coarse)
        assert kwargs['max_iter'] == 37 and coarse.convergence_mode == 'f2'
        assert coarse.inlet_rect == fine.inlet_rect
        assert coarse.outlet_rect == fine.outlet_rect
        area = coarse.dx[:, None] * coarse.dz[None, :]
        np.testing.assert_allclose(np.sum(coarse.rho_field[:, 0, :]
                                   * coarse.eps_field[:, 0, :] * coarse.v_inlet_field * area),
                                   target, rtol=2e-14)
        np.testing.assert_allclose(np.sum(coarse.inlet_frac * area), .36 * .73)
        assert np.all(coarse.v_inlet_field[coarse.inlet_frac == 0.] == 0.)
        assert coarse.outlet_u_frac.shape == (5, 5)
        assert coarse.outlet_w_frac.shape == (4, 6)
        coarse.v[:] = .3
        coarse.residuals = [.01]
        return False, 37

    monkeypatch.setattr(SIMPLESolver3D, 'solve', solve)
    info = bootstrap_simple_3d(fine, max_iter_coarse=37)
    assert len(seen) == 1 and info['applied'] and not info['coarse_converged']
    np.testing.assert_array_equal(fine.v[:, 0, :], fine.v_inlet_field)
    assert np.all(fine.v[:, -1, :][~fine.outlet_mask_ij] == 0.)
    np.testing.assert_allclose(np.sum(fine.rho_field[:, 0, :] * fine.eps_field[:, 0, :]
                               * fine.v[:, 0, :] * fine.dx[:, None] * fine.dz[None, :]), target)


def test_bootstrap_preserves_local_three_dimensional_drag(monkeypatch):
    fine = _build_solver()
    i, j, k = np.indices(fine.P.shape)
    fine.K_arr = np.ascontiguousarray(1e-7 * (1.0 + 0.1 * i + 0.02 * j + 0.03 * k))
    fine.cF_arr = np.ascontiguousarray(100.0 + 10.0 * i + 2.0 * j + 3.0 * k)
    seen = []

    def solve(coarse, **kwargs):
        seen.append(coarse)
        for local in np.ndindex(coarse.P.shape):
            block = tuple(slice(2 * n, 2 * n + 2) for n in local)
            assert coarse.K_arr[local] == pytest.approx(fine.K_arr[block].mean())
            assert coarse.cF_arr[local] == pytest.approx(fine.cF_arr[block].mean())
        assert np.ptp(coarse.K_arr[:, 0, 0]) > 0.0
        coarse.residuals = [0.01]
        return False, 1

    monkeypatch.setattr(SIMPLESolver3D, 'solve', solve)
    info = bootstrap_simple_3d(fine, max_iter_coarse=1)
    assert len(seen) == 1 and info['applied'] and not info['coarse_converged']


def _partial_outlet_solver(shape, stretched, *, fluid_type='incompressible'):
    lengths = (.08, .16, .06)
    widths = {}
    if stretched:
        widths = {name: np.linspace(.3, 1.7, count) * length / count
                  for name, count, length in zip(
                      ('dx_arr', 'dy_arr', 'dz_arr'), shape, lengths)}
    return SIMPLESolver3D(
        *lengths, *shape, rho=1.2, mu=1.85e-5, T_in=300., v_inlet=1., eps=.72,
        K_arr=np.full(shape, 1e-7), cF_arr=np.full(shape, 300.),
        fluid_type=fluid_type, use_coarse_bootstrap=False,
        outlet_rect=(.02, .06, 0., lengths[2]), **widths)


@pytest.mark.parametrize('shape,stretched', [((8, 16, 8), False), ((9, 17, 9), True)])
@pytest.mark.parametrize('pin', [0., 17.])
@pytest.mark.parametrize('fluid_type', ['ideal_gas', 'incompressible'])
def test_bootstrap_restores_fine_pressure_pins_before_density(
        monkeypatch, shape, stretched, pin, fluid_type):
    fine = _partial_outlet_solver(shape, stretched, fluid_type=fluid_type)
    mask = fine.outlet_mask_ij
    fine.P[:, -1, :][mask] = pin
    expected = fine.P[:, -1, :][mask].copy()

    def coarse_solve(coarse, **kwargs):
        i, j, k = np.indices(coarse.P.shape)
        coarse.P[:] = 100. + 3. * i + j + 2. * k
        coarse.P[:, -1, :][coarse.outlet_mask_ij] = 0.
        coarse.residuals.append(.01)
        return False, kwargs['max_iter']

    density_calls = []
    update_density = fine._update_density

    def check_density():
        np.testing.assert_array_equal(fine.P[:, -1, :][mask], expected)
        density_calls.append(True)
        update_density()

    monkeypatch.setattr(SIMPLESolver3D, 'solve', coarse_solve)
    monkeypatch.setattr(fine, '_update_density', check_density)
    info = bootstrap_simple_3d(fine, max_iter_coarse=1)
    assert info['applied'] and not info['coarse_converged']
    assert density_calls == ([True] if fluid_type == 'ideal_gas' else [])
    np.testing.assert_array_equal(fine.P[:, -1, :][mask], expected)
    assert np.any(fine.P[:, :-1, :] > 0.), 'the interior must still receive the seed'


@pytest.mark.parametrize('bad', [np.nan, np.inf])
@pytest.mark.parametrize('fluid_type', ['ideal_gas', 'incompressible'])
def test_bootstrap_does_not_hide_nonfinite_pressure_at_fine_pin(monkeypatch, bad, fluid_type):
    from sjtu_tpmshx.solvers import coarse_bootstrap_3d

    fine = _partial_outlet_solver((8, 16, 8), False, fluid_type=fluid_type)
    fine.use_coarse_bootstrap = True
    i, k = np.argwhere(fine.outlet_mask_ij)[0]
    solve = SIMPLESolver3D.solve
    coarse_pressure = []

    def coarse_solve(coarse, **kwargs):
        coarse_pressure.append(coarse.P)
        coarse.residuals.append(0.)
        return True, 1

    def prolongate(arr, shape):
        result = _trilinear_zoom(arr, shape)
        if arr is coarse_pressure[0]:
            result[i, -1, k] = bad
        return result

    def forbidden():
        pytest.fail('density update must not consume an invalid pressure seed')

    monkeypatch.setattr(SIMPLESolver3D, 'solve', coarse_solve)
    monkeypatch.setattr(coarse_bootstrap_3d, '_trilinear_zoom', prolongate)
    monkeypatch.setattr(fine, '_update_density', forbidden)
    assert solve(fine, max_iter=1) == (False, 0)
    assert fine.exit_reason == 'nonfinite'
    np.testing.assert_equal(fine.P[i, -1, k], bad)


@pytest.mark.parametrize('shape,stretched', [((8, 16, 8), False), ((9, 17, 9), True)])
def test_bootstrap_partial_outlet_converges_to_cold_boundary_problem(shape, stretched):
    cold = _partial_outlet_solver(shape, stretched)
    warm = _partial_outlet_solver(shape, stretched)
    warm.use_coarse_bootstrap = True
    for solver in (cold, warm):
        converged, _ = solver.solve(max_iter=400)
        assert converged and solver.exit_reason == 'tol'
        assert solver.f2_cert_post_rescale_ok
        np.testing.assert_array_equal(solver.P[:, -1, :][solver.outlet_mask_ij], 0.)
    dp_cold, dp_warm = (SIMPLESolver3D.extract_dP_face_extrap(s) for s in (cold, warm))
    assert dp_warm == pytest.approx(dp_cold, rel=1e-4)
    velocity_error = sum(np.sum((a - b)**2) for a, b in zip(
        (cold.u, cold.v, cold.w), (warm.u, warm.v, warm.w)))
    velocity_scale = sum(np.sum(a**2) for a in (cold.u, cold.v, cold.w))
    assert np.sqrt(velocity_error / velocity_scale) < 1e-4
