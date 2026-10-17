"""Physical port edges and SIMPLE profiles must use the shared 2D grid."""
from sjtu_tpmshx.controllers.module_adapter import compute_result
from sjtu_tpmshx.preprocess.api import prepare_case

import numpy as np
import pytest


from sjtu_tpmshx.domain.compute_config import ComputeConfig, PartialBCConfig
from sjtu_tpmshx.models.grid import _aligned_grid


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




@pytest.mark.parametrize('directions', [(0, 2), (2, 0), (1, 3), (3, 1),
                                         (0, 1), (2, 3)])
def test_ports_align_on_physical_axis(directions):
    cfg = _case(directions)
    case = prepare_case(cfg, case_id='test-case')
    expected = {'x': set(), 'y': set()}
    for bc in (cfg.bc_A, cfg.bc_B):
        expected['y' if bc.dir in (0, 1) else 'x'].update(_edges(bc))
    for axis, length in (('x', 0.182), ('y', 0.042)):
        widths = case.grid[f'd{axis}']
        assert len(widths) == 40
        assert np.all(widths > 0)
        assert widths.sum() == pytest.approx(length, rel=1e-13)
        assert set(case.grid[f'{axis}_breaks']) == expected[axis]
        grid_edges = np.r_[0.0, np.cumsum(widths)]
        for edge in expected[axis]:
            assert np.min(np.abs(grid_edges - edge)) < 1e-13


def test_default_direction_partial_grid_is_unchanged():
    cfg = _case((0, 2))
    case = prepare_case(cfg, case_id='default-partial-grid')
    np.testing.assert_array_equal(case.grid['dx'],
                                  _aligned_grid(40, 0.182, _edges(cfg.bc_B)))
    np.testing.assert_array_equal(case.grid['dy'],
                                  _aligned_grid(40, 0.042, _edges(cfg.bc_A)))


@pytest.mark.parametrize('directions', [(0, 2), (2, 0), (0, 1), (2, 3)])
def test_full_faces_keep_wall_refinement(directions):
    from sjtu_tpmshx.models.grid import build_master_refined_grid

    cfg = _case(directions)
    cfg.bc_A = PartialBCConfig(dir=directions[0])
    cfg.bc_B = PartialBCConfig(dir=directions[1])
    cfg.validate()
    case = prepare_case(cfg, case_id='test-case')
    dx, dy, _, _ = build_master_refined_grid(
        0.182, 0.042, 40, 40, n_refine=8, first_cell=0.02e-3, growth=1.8)
    assert case.grid['x_breaks'] == case.grid['y_breaks'] == ()
    np.testing.assert_array_equal(case.grid['dx'], dx)
    np.testing.assert_array_equal(case.grid['dy'], dy)


@pytest.mark.parametrize('inset', [0.0005, 0.0015])
def test_near_wall_break_filter_is_preserved(inset):
    cfg = _case((2, 0))
    for bc, length in ((cfg.bc_A, 0.182), (cfg.bc_B, 0.042)):
        bc.in_ctr = bc.out_ctr = length / 2
        bc.in_w = bc.out_w = length * (1 - 2 * inset)
    case = prepare_case(cfg.validate(), case_id='test-case')
    for axis, bc in (('x', cfg.bc_A), ('y', cfg.bc_B)):
        expected = set(_edges(bc)) if inset > 0.001 else set()
        assert set(case.grid[f'{axis}_breaks']) == expected










@pytest.mark.slow
@pytest.mark.parametrize('directions', [(2, 0), (0, 1), (3, 0)])
def test_custom_port_numerical_regression(directions):
    cfg = _case(directions)
    # Same in-domain air/geometry point as the existing 2D workflow smoke.
    cfg.geometry.t_wall_mm = 0.4
    cfg.fluid_A.u_mps = cfg.fluid_B.u_mps = 10.0
    cfg.fluid_A.T_in_K = 600.0
    cfg.fluid_B.T_in_K = 300.0
    result = compute_result(cfg)
    assert result.converged, (result.diagnostics, result.warnings)
    for side in ('A', 'B'):
        assert result.residuals[f'mass_imbalance_rel_{side}'] < 1e-6
    assert np.isfinite(result.Q_W) and result.Q_W > 0
    assert result.dP_A_Pa > 0 and result.dP_B_Pa > 0
    assert 300 < result.T_out_A_K < 600
    assert 300 < result.T_out_B_K < 600
    assert result.residuals['energy_imbalance_rel'] < 0.05
