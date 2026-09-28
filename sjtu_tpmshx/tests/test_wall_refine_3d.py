"""wall_refine_3d solve-level coverage (blind-spot audit T5, 2026-07-07).

Until this file, NO test actually solved on the 6-wall refined grid: config
round-trips touched the flag (always False) while the refined momentum /
pressure / LTNE path had zero solve coverage — the N4 diffusion-distance
defect lived exactly there, undetected. Assertions are physical-consistency
checks, not pinned values, so the test is valid both before and after the
N4 kernel fix; the refined-vs-uniform agreement bands are the guard.
"""

import numpy as np
import pytest


def _full_face_cfg(**overrides):
    """Small full-face air-air cross-flow (Shanghai-like), both dirs open."""
    cfg = dict(
        L=0.182, H=0.042, Lz=0.042,
        Nx=8, Ny=6, Nz=6,
        u_A=10.0, u_B=20.0, T_inA=422.0, T_inB=322.0,
        P_inA=192362.0, P_inB=101325.0,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=dict(dir=3, in_ctr=0.091, in_w=0.182,
                         out_ctr=0.091, out_w=0.182,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=True,
    )
    cfg.update(overrides)
    return cfg


@pytest.mark.slow
def test_wall_refine_3d_solves_and_matches_uniform():
    """Refined-grid solve is finite, conservative, and agrees with the
    uniform-grid solution of the same physical case."""
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack

    r = _run_3d_stack(_full_face_cfg())
    for key in ('T_A_out', 'T_B_out', 'dP_A',
                'Q_enthalpy_A', 'Q_enthalpy_B'):
        assert np.isfinite(r[key]), f"{key} not finite on refined grid"
    assert r['dP_A'] > 0.0
    assert np.isfinite(r['mass_imbalance_rel_A'])
    assert r['mass_imbalance_rel_A'] < 0.05

    Qa, Qb = abs(r['Q_enthalpy_A']), abs(r['Q_enthalpy_B'])
    assert Qa > 1.0 and Qb > 1.0, f"degenerate duties: {Qa:.3g}/{Qb:.3g}"
    assert abs(Qa - Qb) / max(Qa, Qb) < 0.15, \
        f"A/B energy imbalance on refined grid: {Qa:.1f} vs {Qb:.1f}"

    # Same case on the uniform grid — refinement must not move the answer
    # far (E1 measured ~0.6% dP shift at Shanghai scale; bands are generous
    # because this grid is much coarser).
    ru = _run_3d_stack(_full_face_cfg(wall_refine_3d=False))
    dP_u, dP_r = ru['dP_A'], r['dP_A']
    assert abs(dP_r - dP_u) / dP_u < 0.15, \
        f"refined dP {dP_r:.0f} vs uniform {dP_u:.0f} (>15%)"
    Qu = abs(ru['Q_enthalpy_A'])
    assert abs(Qa - Qu) / Qu < 0.10, \
        f"refined Q {Qa:.0f} vs uniform {Qu:.0f} (>10%)"


@pytest.mark.parametrize('wall_refine', [False, True])
def test_uniform_grid_when_disabled_or_refinement_rejected(wall_refine, monkeypatch):
    from unittest.mock import Mock
    from sjtu_tpmshx.models import grid, grid_3d

    refine = Mock(side_effect=ValueError('small domain'))
    logger = Mock()
    monkeypatch.setattr(grid, 'build_master_refined_grid_3d', refine)
    monkeypatch.setattr(grid_3d, '_log', logger)
    dx, dy, dz, nx, ny, nz = grid_3d._build_grid_3d(
        wall_refine, .12, .08, .06, 3, 4, 2)
    assert (nx, ny, nz) == (3, 4, 2)
    for actual, n, width in ((dx, 3, .12 / 3), (dy, 4, .08 / 4), (dz, 2, .06 / 2)):
        np.testing.assert_array_equal(actual, np.full(n, width, dtype=np.float64))
        assert actual.dtype == np.float64
    logger.info.assert_not_called()
    if wall_refine:
        refine.assert_called_once_with(.12, .08, .06, 3, 4, 2,
                                       n_refine=8, first_cell=0.02e-3, growth=1.8)
        logger.warning.assert_called_once_with(
            '[3D grid] wall-refine skipped (small domain); using uniform')
    else:
        refine.assert_not_called()
        logger.warning.assert_not_called()


def test_refined_grid_keeps_arrays_without_uniform_allocation(monkeypatch):
    from unittest.mock import Mock
    from sjtu_tpmshx.models import grid, grid_3d

    widths = (np.array([.02, .08, .02]), np.array([.01, .06, .01]),
              np.array([.01, .04, .01]))
    refine = Mock(return_value=(*widths, 3, 3, 3))
    logger = Mock()
    monkeypatch.setattr(grid, 'build_master_refined_grid_3d', refine)
    monkeypatch.setattr(grid_3d, '_log', logger)
    monkeypatch.setattr(grid_3d.np, 'full', Mock(side_effect=AssertionError('uniform allocation')))
    actual = grid_3d._build_grid_3d(True, .12, .08, .06, 3, 4, 2)
    assert actual[3:] == (3, 3, 3)
    assert all(actual[i] is widths[i] for i in range(3))
    refine.assert_called_once_with(.12, .08, .06, 3, 4, 2,
                                   n_refine=8, first_cell=0.02e-3, growth=1.8)
    logger.info.assert_called_once_with('[3D grid] wall-refine: user 3x4x2 -> actual 3x3x3')
    logger.warning.assert_not_called()


@pytest.mark.parametrize('error_type', [RuntimeError, ImportError])
def test_refinement_unexpected_errors_propagate(error_type, monkeypatch):
    from unittest.mock import Mock
    from sjtu_tpmshx.models import grid, grid_3d

    error = error_type('refinement failed')
    monkeypatch.setattr(grid, 'build_master_refined_grid_3d', Mock(side_effect=error))
    logger = Mock()
    monkeypatch.setattr(grid_3d, '_log', logger)
    with pytest.raises(error_type) as caught:
        grid_3d._build_grid_3d(True, .12, .08, .06, 3, 4, 2)
    assert caught.value is error
    logger.warning.assert_not_called()
