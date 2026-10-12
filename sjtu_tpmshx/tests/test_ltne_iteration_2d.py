"""A converged LTNE chunk must not hide alternating single-sweep updates."""
from sjtu_tpmshx.controllers.module_adapter import compute_result

import inspect

import numpy as np
import pytest


from sjtu_tpmshx.solvers import ltne_energy
from sjtu_tpmshx.tests.test_port_grid_alignment_2d import _case


@pytest.mark.parametrize('directions', [(3, 0), (3, 3), (0, 0)])
@pytest.mark.parametrize('mode', ['solved', 'prescribed', 'asymmetric'])
def test_serial_sweep_consumes_updated_upstream_cell(directions, mode):
    # Two real CVs: no SOU slope or conduction. Independently integrate the
    # inlet and outlet rows, retaining A relaxation and A -> solid -> B order.
    dir_a, dir_b = directions
    vertical = dir_a == 3
    shape = (1, 2) if vertical else (2, 1)
    widths = np.array([0.4, 0.6])
    dx, dy = (np.ones(1), widths) if vertical else (widths, np.ones(1))
    one, zero = np.ones(shape), np.zeros(shape)
    ea, eb = (0.3, 0.5) if mode == 'asymmetric' else (0.4, 0.4)
    expected_a, expected_b = np.full(2, 300.), np.full(2, 300.)
    expected_s = np.full(2, 350.)
    upstream_a, upstream_b = 400., 300.
    for step, cell in enumerate([1, 0] if vertical else [0, 1]):
        volume = widths[cell]
        candidate = (ea * upstream_a + 2 * volume * 350.) / (ea + 2 * volume)
        expected_a[cell] += (0.7 if step == 0 else 1.) * (candidate - 300.)
        expected_s[cell] = (2 * expected_a[cell] + 3 * 300.) / 5
        if mode != 'prescribed':
            flux_b = eb * volume if directions == (3, 0) else eb
            expected_b[cell] = (flux_b * upstream_b + 3 * volume * expected_s[cell]) / (flux_b + 3 * volume)
            if directions != (3, 0):
                upstream_b = expected_b[cell]
        upstream_a = expected_a[cell]
    actual = ltne_energy.solve_full_domain(
        1., 1., *shape, 400., 300., 0., 0., 0., 2., 3., 1., 1., 0.8,
        zero if vertical else one, -one if vertical else zero,
        one if dir_b == 0 else zero, -one if dir_b == 3 else zero,
        dir_a, dir_b, dx_arr=dx, dy_arr=dy,
        Ta_init=one*300., Tb_init=one*300., Ts_init=one*350.,
        Tb_prescribed=one*300. if mode == 'prescribed' else None,
        eps_A=ea if mode == 'asymmetric' else None,
        eps_B=eb if mode == 'asymmetric' else None,
        max_iter=1, conv_chunk=1)
    for field, expected in zip(actual, (expected_a, expected_b, expected_s)):
        np.testing.assert_allclose(field, expected.reshape(shape), atol=1e-12, rtol=0)


@pytest.mark.parametrize('kernel_name', ['_gs_full_chunk', '_gs_full_chunk_rb'])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_outlet_solid_consumes_unrelaxed_a_candidate(kernel_name, direction):
    # No transport: A's outlet equation gives old Ts=350. The solid consumes
    # that value, so Ts_out=(2*350+300)/3. The real outlet retains its solution.
    n = 4
    zero = np.zeros((n, n))
    one = np.ones((n, n))
    Ta, Tb, Ts = (np.full((n, n), value) for value in (400.0, 300.0, 350.0))
    getattr(ltne_energy, kernel_name)(
        Ta, Tb, Ts, n, n, np.ones(n), np.ones(n),
        zero, zero, zero, 2 * one, one, one, one, one, one,
        zero, zero, zero, zero, direction, 0,
        np.full(n, 400.0), np.full(n, 300.0), np.ones(n), np.ones(n),
        1, 1, 0)
    outlet = ((-1, slice(None)), (0, slice(None)),
              (slice(None), -1), (slice(None), 0))[direction]
    np.testing.assert_allclose(Ts[outlet], (2 * 350.0 + 300.0) / 3, atol=1e-12, rtol=0)
    # The approved physical-face BC replaces the former whole-layer copy.
    np.testing.assert_allclose(Ta[outlet], 350.0, atol=1e-12, rtol=0)
    np.testing.assert_array_equal(Tb, np.full((n, n), 300.0))


@pytest.mark.slow
def test_swapped_port_ltne_settles_between_consecutive_sweeps(monkeypatch):
    kernel = ltne_energy._gs_full_chunk
    signature = inspect.signature(kernel.py_func)
    final_main = {}

    def capture(*args, **kwargs):
        result = kernel(*args, **kwargs)
        bound = signature.bind(*args, **kwargs).arguments
        if (bound['Nx'], bound['Ny']) == (40, 40):
            final_main.update({key: value.copy() if isinstance(value, np.ndarray) else value
                               for key, value in bound.items()})
        return result

    monkeypatch.setattr(ltne_energy, '_gs_full_chunk', capture)
    cfg = _case((2, 0))
    cfg.geometry.t_wall_mm = 0.4
    cfg.fluid_A.u_mps = cfg.fluid_B.u_mps = 10.0
    cfg.fluid_A.T_in_K = 600.0
    cfg.fluid_B.T_in_K = 300.0
    result = compute_result(cfg)
    assert final_main

    # Observe detached fields every sweep, not only at the even 500-step gate.
    final_main['n_iters'] = 1
    for step in range(20):
        previous = [final_main[key].copy() for key in ('Ta', 'Tb', 'Ts')]
        kernel(*final_main.values())
        changes = [float(np.max(np.abs(final_main[key] - old)))
                   for key, old in zip(('Ta', 'Tb', 'Ts'), previous)]
        assert max(changes) < 0.01, (step, changes)
    assert result.converged, result.diagnostics['convergence_detail']
