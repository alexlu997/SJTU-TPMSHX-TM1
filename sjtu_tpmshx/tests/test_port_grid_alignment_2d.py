"""Physical port edges and SIMPLE profiles must use the shared 2D grid."""

import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
from sjtu_tpmshx.domain.compute_config import ComputeConfig, PartialBCConfig
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver, _aligned_grid


@pytest.mark.parametrize('staggered', [False, True])
def test_port_roundoff_does_not_open_an_adjacent_wall(staggered):
    from sjtu_tpmshx.models.grid import _port_overlap_1d

    widths = np.array([.007, .042, .133])
    edges = np.r_[0., np.cumsum(widths)]
    if staggered:
        edges = np.r_[0., edges[1:] - widths / 2, edges[-1]]
    lo, hi = edges[1:3]
    expected = _port_overlap_1d(widths, lo, hi, staggered=staggered) > 0
    for shift in (-1, 0, 1):
        observed = _port_overlap_1d(widths, lo + shift * np.spacing(lo),
                                    hi + shift * np.spacing(hi), staggered=staggered)
        np.testing.assert_array_equal(observed > 0, expected)
    # A real subcell opening, much smaller than 1% of a cell, remains open.
    small = _port_overlap_1d(widths, lo - 1e-8, lo, staggered=staggered)
    assert np.any(small > 0)
    assert np.dot(small, np.diff(edges)) == pytest.approx(1e-8, abs=1e-17)


@pytest.mark.parametrize('depth', [None, np.array([.02, .04])])
def test_cell_average_is_invariant_to_subdividing_one_cell(depth):
    from sjtu_tpmshx.models.grid import cell_average

    field = np.array([[300., 340.], [400., 440.]])
    widths = [np.array([.001, .009]), np.array([.03, .01])]
    if depth is not None:
        field = np.repeat(field[:, :, None], len(depth), axis=2)
        widths.append(depth)
    # Physical average: 90% of the volume is in the warmer x cell;
    # the warmer y cell occupies 25%. Counting cells would give 370 K.
    assert cell_average(field, *widths) == pytest.approx(400.)
    refined = np.concatenate([field[:1], np.repeat(field[1:], 9, axis=0)])
    assert cell_average(refined, np.full(10, .001), *widths[1:]) == pytest.approx(400.)
    assert cell_average(997., *widths) == 997.


@pytest.mark.parametrize('counts', [(84, 24), (92, 14, 10)])
def test_port_wall_grid_prepared_counts_and_nested_port_area(counts):
    from dataclasses import asdict
    from sjtu_tpmshx.models.grid import split_cells, _port_overlap_1d
    from sjtu_tpmshx.preprocess.api import prepare_case

    config = ComputeConfig()
    config.geometry.L_dom_m, config.geometry.H_dom_m = .182, .042
    config.geometry.Lz_m = .042 if len(counts) == 3 else None
    config.solver.Nx, config.solver.Ny = counts[:2]
    config.solver.Nz = counts[2] if len(counts) == 3 else 1
    config.flags.port_wall_refine = True
    config.bc_A = PartialBCConfig(dir=0, in_ctr=.021, in_w=.042, out_ctr=.021, out_w=.042)
    config.bc_B = PartialBCConfig(dir=3, in_ctr=.154, in_w=.042, out_ctr=.028, out_w=.042,
                                 uniform_inlet_2d=True)
    restored = ComputeConfig.from_dict(asdict(config))
    case = prepare_case(restored, case_id='port-wall-grid')
    assert tuple(len(case.grid['d' + axis]) for axis in 'xyz'[:len(counts)]) == counts
    for axis, length in zip('xyz', (.182, .042, .042)):
        if 'd' + axis not in case.grid:
            continue
        widths = case.grid['d' + axis]
        assert np.all(widths > 0)
        assert sum(widths) == pytest.approx(length, abs=1e-15)
        fine = split_cells(widths)
        assert len(fine) == 2 * len(widths)
        np.testing.assert_allclose(np.cumsum(fine)[1::2], np.cumsum(widths), atol=1e-17, rtol=0.)
    for widths in (case.grid['dx'], split_cells(case.grid['dx'])):
        for centre in (.154, .028):
            fractions = _port_overlap_1d(widths, centre - .021, centre + .021)
            assert np.dot(fractions, widths) == pytest.approx(.042, abs=1e-15)
    if len(counts) == 3:
        config.bc_B = PartialBCConfig(dir=3)
        full_face = prepare_case(config, case_id='port-wall-full-face')
        assert tuple(len(full_face.grid['d' + axis]) for axis in 'xyz') == counts


def test_port_wall_grid_rejects_insufficient_total_count():
    from sjtu_tpmshx.models.grid import build_port_wall_grid
    with pytest.raises(ValueError, match='at least'):
        build_port_wall_grid((.182, .042), (8, 8),
                             (dict(dir=0, in_ctr=.021, in_w=.042, out_ctr=.021, out_w=.042),))


def _backend_fields(config):
    """Reach the actual runtime closure using the prepared public grid."""
    from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    case = Pipeline2D(config).build_fields()
    parsed, prepared = build_execution_inputs(case)
    return parsed, build_runtime(parsed, prepared)


def _case(directions):
    cfg = ComputeConfig()
    cfg.geometry.L_dom_m = 0.182
    cfg.geometry.H_dom_m = 0.042
    cfg.solver.Nx = cfg.solver.Ny = 40
    cfg.solver.Nz = 1
    for side, direction, bounds in zip(
        ('A', 'B'), directions,
        ((0.17, 0.43, 0.52, 0.83), (0.29, 0.61, 0.11, 0.47)),
    ):
        cross = 0.042 if direction in (0, 1) else 0.182
        lo, hi, out_lo, out_hi = np.asarray(bounds) * cross
        setattr(cfg, f'bc_{side}', PartialBCConfig(
            dir=direction, in_ctr=(lo + hi) / 2, in_w=hi - lo,
            out_ctr=(out_lo + out_hi) / 2, out_w=out_hi - out_lo))
    return cfg.validate()


def _edges(bc):
    return (bc.in_ctr - bc.in_w / 2, bc.in_ctr + bc.in_w / 2,
            bc.out_ctr - bc.out_w / 2, bc.out_ctr + bc.out_w / 2)


def test_aligned_grid_borrows_from_multiple_segments():
    edges = np.cumsum([.15, .15, .15, .15, .10, .10, .08, .07, .05])[:-1]
    widths = _aligned_grid(20, 1.0, edges)
    assert len(widths) == 20
    assert np.all(widths > 0)
    assert widths.sum() == pytest.approx(1.0, abs=1e-13)
    grid_edges = np.r_[0.0, np.cumsum(widths)]
    for edge in edges:
        assert np.min(np.abs(grid_edges - edge)) < 1e-13


def test_aligned_grid_rejects_too_few_cells_for_segments():
    edges = np.cumsum([.15, .15, .15, .15, .10, .10, .08, .07, .05])[:-1]
    with pytest.raises(ValueError):
        _aligned_grid(17, 1.0, edges)


def test_counter_port_endpoints_do_not_create_unknown_fine_inflow():
    from sjtu_tpmshx.solvers.simple_solver import _prolong_mass_faces_2d
    from sjtu_tpmshx.solvers.ltne_energy import _model_h_balance
    from sjtu_tpmshx.solvers.simple_solver import _port_fractions_1d

    # Original counter member: preserve the actual centre/width arithmetic.
    ports = ((0.0126, 0.01092, 0.02835, 0.01302),
             (0.0189, 0.01344, 0.01218, 0.015120000000000001))
    breaks = sorted({ctr + sign * width / 2 for port in ports
                     for ctr, width in (port[:2], port[2:]) for sign in (-1, 1)})
    lo, hi = ports[1][0] - ports[1][1]/2, ports[1][0] + ports[1][1]/2
    coarse, fine = (_aligned_grid(n, 0.042, breaks) for n in (40, 80))
    for widths, n in ((coarse, 40), (fine, 80)):
        assert len(widths) == n and np.all(widths > 0)
        edges = np.r_[0., np.cumsum(widths)]
        assert all(edge in edges for edge in (*breaks, 0.042))
    raw, profile = _port_fractions_1d(coarse, lo, hi)
    raw_fine, _ = _port_fractions_1d(fine, lo, hi)
    assert raw[10] == 0 and np.all(raw_fine[22:24] == 0)
    assert np.dot(raw, coarse) == pytest.approx(hi-lo, rel=1e-14)
    assert np.dot(raw_fine, fine) == pytest.approx(hi-lo, rel=1e-14)

    dx = np.array([0.091, 0.091])
    mass = (np.tile(-profile*coarse, (3, 1)), np.zeros((2, 41)))
    refined = _prolong_mass_faces_2d(mass, dx, coarse, dx, fine)
    assert np.all(refined[0][-1, raw_fine == 0] == 0)
    np.testing.assert_allclose(refined[0].sum(axis=1), mass[0].sum(axis=1),
                               rtol=1e-14, atol=0)
    np.testing.assert_allclose(
        np.diff(refined[0], axis=0) + np.diff(refined[1], axis=1), 0., atol=1e-15)

    # A real negative flow on a closed face must still fail, even this small.
    temperature = np.full((2, 80), 310.)
    zero = np.zeros_like(temperature)
    no_flow = tuple(np.zeros_like(face) for face in refined)
    for injected in (0., -4.4917681889235814e-18):
        refined[0][-1, 22] = injected
        balance = _model_h_balance(
            temperature, temperature, temperature, zero, zero, zero, zero, zero,
            dx, fine, no_flow, refined, (1000., 0., 0., 0., 300.),
            (1000., 0., 0., 0., 300.), 1, 1,
            np.full(80, 310.), np.full(80, 310.), raw_fine, raw_fine, False,
            temperature, temperature)
        assert balance['B']['unknown_inflow_faces'] == int(injected < 0)
        assert balance['physical_boundary_complete'] == (injected == 0)
        if injected < 0:
            assert not balance['passed']


@pytest.mark.parametrize('directions', [(0, 2), (2, 0), (1, 3), (3, 1),
                                         (0, 1), (2, 3)])
def test_ports_align_on_physical_axis(directions):
    cfg = _case(directions)
    parsed, fields = _backend_fields(cfg)
    expected = {'x': set(), 'y': set()}
    for bc in (cfg.bc_A, cfg.bc_B):
        expected['y' if bc.dir in (0, 1) else 'x'].update(_edges(bc))
    for axis, length in (('x', 0.182), ('y', 0.042)):
        widths = fields[f'energy_d{axis}']
        assert len(widths) == parsed[f'N_{axis}'] == 40
        assert np.all(widths > 0)
        assert widths.sum() == pytest.approx(length, rel=1e-13)
        assert fields[f'_{axis}_breaks'] == expected[axis]
        grid_edges = np.r_[0.0, np.cumsum(widths)]
        for edge in expected[axis]:
            assert np.min(np.abs(grid_edges - edge)) < 1e-13


def test_default_direction_partial_grid_is_unchanged():
    cfg = _case((0, 2))
    _, fields = _backend_fields(cfg)
    np.testing.assert_array_equal(fields['energy_dx'],
                                  _aligned_grid(40, 0.182, _edges(cfg.bc_B)))
    np.testing.assert_array_equal(fields['energy_dy'],
                                  _aligned_grid(40, 0.042, _edges(cfg.bc_A)))


@pytest.mark.parametrize('directions', [(0, 2), (2, 0), (0, 1), (2, 3)])
def test_full_faces_keep_wall_refinement(directions):
    from sjtu_tpmshx.models.grid import build_master_refined_grid

    cfg = _case(directions)
    cfg.bc_A = PartialBCConfig(dir=directions[0])
    cfg.bc_B = PartialBCConfig(dir=directions[1])
    cfg.validate()
    _, fields = _backend_fields(cfg)
    dx, dy, _, _ = build_master_refined_grid(
        0.182, 0.042, 40, 40, n_refine=8, first_cell=0.02e-3, growth=1.8)
    assert fields['_x_breaks'] == fields['_y_breaks'] == set()
    np.testing.assert_array_equal(fields['energy_dx'], dx)
    np.testing.assert_array_equal(fields['energy_dy'], dy)


@pytest.mark.parametrize('inset', [0.0005, 0.0015])
def test_near_wall_break_filter_is_preserved(inset):
    cfg = _case((2, 0))
    for bc, length in ((cfg.bc_A, 0.182), (cfg.bc_B, 0.042)):
        bc.in_ctr = bc.out_ctr = length / 2
        bc.in_w = bc.out_w = length * (1 - 2 * inset)
    _, fields = _backend_fields(cfg.validate())
    for axis, bc in (('x', cfg.bc_A), ('y', cfg.bc_B)):
        expected = set(_edges(bc)) if inset > 0.001 else set()
        assert fields[f'_{axis}_breaks'] == expected


def _expected_profile(widths, lo, hi):
    edges = np.r_[0.0, np.cumsum(widths)]
    raw = np.clip((np.minimum(edges[1:], hi) - np.maximum(edges[:-1], lo))
                  / widths, 0, 1)
    profile = raw.copy()
    walls = np.flatnonzero(raw < 0.01)
    for i in np.flatnonzero(raw > 0.99):
        if walls.size:
            distance = np.min(np.abs(walls - i))
            if distance <= 4:
                profile[i] = 1 - 0.8 * np.exp(-distance)
    return profile


@pytest.mark.parametrize('directions', [(0, 1), (2, 3), (1, 3), (3, 1)])
def test_simple_profiles_follow_final_shared_coordinates(monkeypatch, directions):
    # Real constructor and pipeline wiring; stop precisely before iteration.
    class BeforeIteration(Exception):
        pass

    captured = []

    def capture(solver, **kwargs):
        captured.append(solver)
        raise BeforeIteration

    monkeypatch.setattr(SIMPLESolver, 'solve', capture)
    cfg = _case(directions)
    parsed, fields = _backend_fields(cfg)
    x = np.cumsum(fields['energy_dx']) - fields['energy_dx'] / 2
    y = np.cumsum(fields['energy_dy']) - fields['energy_dy'] / 2
    rho = 1000. + 10. * x[:, None] + y[None, :]
    mu = .001 + .0001 * x[:, None] + .0002 * y[None, :]
    temperature = 300. + 100. * x[:, None] + 200. * y[None, :]
    for side in ('A', 'B'):
        bc = getattr(cfg, f'bc_{side}')
        with pytest.raises(BeforeIteration):
            fields['_run_simple'](parsed[f'cfg{side}'], rho, mu,
                                  300.0, 0.2, side, fluid_type='incompressible',
                                  T_field_real=temperature)
        solver = captured[-1]
        widths = fields['energy_dy' if bc.dir in (0, 1) else 'energy_dx']
        np.testing.assert_array_equal(solver.dx_arr, widths)
        stream = fields['energy_dx' if bc.dir in (0, 1) else 'energy_dy']
        if directions in ((1, 3), (3, 1)):
            assert not np.array_equal(stream, stream[::-1])
        negative = bc.dir in (1, 3)
        np.testing.assert_array_equal(solver.dy_arr, stream[::-1] if negative else stream)
        for physical, actual in ((rho, solver.rho_field), (mu, solver.mu_field),
                                 (temperature, solver.T_field)):
            expected = physical.T if bc.dir in (0, 1) else physical
            np.testing.assert_array_equal(actual, expected[:, ::-1] if negative else expected)
        assert len(solver.inlet_frac) == len(widths) == 40
        lo, hi, out_lo, out_hi = _edges(bc)
        inlet = _expected_profile(widths, lo, hi)
        outlet = _expected_profile(widths, out_lo, out_hi)
        np.testing.assert_allclose(solver.inlet_frac, inlet, atol=1e-13, rtol=0)
        np.testing.assert_allclose(solver.outlet_frac, outlet, atol=1e-13, rtol=0)
        np.testing.assert_array_equal(solver.inlet_mask, inlet > 0.01)
        np.testing.assert_array_equal(solver.outlet_mask, outlet > 0.01)
        np.testing.assert_allclose(solver.v[:, 0], solver.v_inlet_field * inlet,
                                   atol=1e-13, rtol=0)
        assert np.sum(solver.v_inlet_field * solver.inlet_frac * widths) == (
            pytest.approx(0.2 * bc.in_w, rel=1e-12))


def test_refreshed_taper_sets_first_massflux_target():
    solver = SIMPLESolver(
        0.182, 0.042, 40, 20, 'Gyroid', 7.0, 0.6, 0.85, 1e-3,
        1000.0, 0.001, 300.0, 0.03, 0.08, 0.2,
        outlet_lo=0.10, outlet_hi=0.15, fluid_type='incompressible',
        rho_inlet_ref=1000.0, wall_refine=False)
    original = solver.dx_arr.copy()
    solver.dx_arr = _aligned_grid(40, 0.182, [0.03, 0.05, 0.08, 0.10, 0.12, 0.15])
    assert len(original) == len(solver.dx_arr)
    assert not np.array_equal(original, solver.dx_arr)
    for _ in range(2):
        solver._refresh_ports(0.03, 0.08, 0.10, 0.15)
        assert np.sum(solver.v_inlet_field * solver.inlet_frac * solver.dx_arr) == (
            pytest.approx(0.2 * 0.05, rel=1e-12))
    scale = solver._inlet_taper_flux_scale
    assert not hasattr(solver, '_massflux_target')
    solver.solve(max_iter=2, verbose=False)
    assert solver._massflux_target == pytest.approx(0.2 * 1000.0 * scale, rel=1e-12)


@pytest.mark.parametrize('direction', [1, 3])
def test_negative_pressure_and_staggered_faces_return_to_physical_cells(direction):
    from types import SimpleNamespace
    from sjtu_tpmshx.solvers.backends.python.two_d.coupling import (
        _simple_scalar_to_real_2d, _simple_staggered_to_real_2d,
    )

    pressure = np.arange(12., dtype=float).reshape(4, 3)
    ux = np.arange(15., dtype=float).reshape(5, 3) + 1.
    uy = np.arange(16., dtype=float).reshape(4, 4) + 20.
    if direction == 1:
        solver = SimpleNamespace(P=pressure[::-1, :].T,
                                 u=uy[::-1, :].T, v=-ux[::-1, :].T)
    else:
        solver = SimpleNamespace(P=pressure[:, ::-1],
                                 u=ux[:, ::-1], v=-uy[:, ::-1])
    np.testing.assert_array_equal(_simple_scalar_to_real_2d(solver.P, direction), pressure)
    actual_x, actual_y = _simple_staggered_to_real_2d(solver, direction)
    np.testing.assert_array_equal(actual_x, ux)
    np.testing.assert_array_equal(actual_y, uy)


@pytest.mark.slow
@pytest.mark.parametrize('directions', [(2, 0), (0, 1), (3, 0)])
def test_custom_port_numerical_regression(directions):
    cfg = _case(directions)
    # Same in-domain air/geometry point as the existing Pipeline2D smoke.
    cfg.geometry.t_wall_mm = 0.4
    cfg.fluid_A.u_mps = cfg.fluid_B.u_mps = 10.0
    cfg.fluid_A.T_in_K = 600.0
    cfg.fluid_B.T_in_K = 300.0
    result = Pipeline2D(cfg).run()
    assert result.converged, (result.diagnostics, result.warnings)
    for side in ('A', 'B'):
        assert result.residuals[f'mass_imbalance_rel_{side}'] < 1e-6
    assert np.isfinite(result.Q_W) and result.Q_W > 0
    assert result.dP_A_Pa > 0 and result.dP_B_Pa > 0
    assert 300 < result.T_out_A_K < 600
    assert 300 < result.T_out_B_K < 600
    assert result.residuals['energy_imbalance_rel'] < 0.05
