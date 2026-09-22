"""Physical zone positions and stream order survive preparation and SI handoff."""
from dataclasses import replace

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, GeometryConfig, SolverConfig, PartialBCConfig,
    ZoneInputConfig, FeatureFlags, ExtrapPolicy,
)
from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
from sjtu_tpmshx.models.tpms_props import geometry
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, SCO2_DF_METHOD
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.io.case_io import save_case, load_case


def _centres(widths):
    return (np.cumsum(widths) - .5 * widths) / np.sum(widths)


def _config(mode, direction, nonuniform):
    cells = [dict(x0=0., x1=.41, y0=0., y1=.36, L=4., t=.3),
             dict(x0=.41, x1=1., y0=0., y1=.36, L=6., t=.4),
             dict(x0=0., x1=.41, y0=.36, y1=1., L=7., t=.5),
             dict(x0=.41, x1=1., y0=.36, y1=1., L=8., t=.6)]
    zones = ZoneInputConfig(enabled=True, axis=mode,
        grid=dict(cells=cells, tpms_type='Gyroid', k_s=16.),
        config=ZoneConfig([Zone('first', 0., .41, 4., .3),
                           Zone('second', .41, 1., 8., .6)], 'Gyroid', 16.))
    def port(d):
        width = .03 if d in (0, 1) else .06
        return PartialBCConfig(dir=d, in_ctr=.5 * width, out_ctr=.5 * width,
                               in_w=.63 * width if nonuniform else width,
                               out_w=.63 * width if nonuniform else width)
    return ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.06, H_dom_m=.03, L_cell_mm=6., t_wall_mm=.4),
        solver=SolverConfig(Nx=8, Ny=6), zones=zones,
        bc_A=port(direction), bc_B=port((direction + 2) % 4),
        extrap=ExtrapPolicy(allow=True))


def _physical_fields(case, mode):
    x, y = np.meshgrid(_centres(case.grid['dx']), _centres(case.grid['dy']), indexing='ij')
    if mode == 'grid':
        # Independent explicit quadrant values, not a call back to a builder.
        L = np.where(y < .36, np.where(x < .41, 4., 6.), np.where(x < .41, 7., 8.))
        t = np.where(y < .36, np.where(x < .41, .3, .4), np.where(x < .41, .5, .6))
    else:
        first = (x if mode == 'x' else y) < .41
        L, t = np.where(first, 4., 8.), np.where(first, .3, .6)
    return L, t


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
@pytest.mark.parametrize('nonuniform', [False, True])
def test_prepared_drag_uses_the_same_physical_design_in_all_directions(
        mode, direction, nonuniform, tmp_path, monkeypatch):
    from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
    cfg = _config(mode, direction, nonuniform)
    # Production preparation chooses its fixed model even if a retired
    # standalone-method override is present in the launching environment.
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'rbf')
    case = prepare_case(cfg, case_id=f'{mode}-{direction}-{nonuniform}')
    L, t = _physical_fields(case, mode)
    np.testing.assert_allclose(case.design_fields['L_field_m'], L * 1e-3)
    np.testing.assert_allclose(case.design_fields['t_field_m'], t * 1e-3)
    if nonuniform:
        assert not np.allclose(case.grid['dx'], np.mean(case.grid['dx']))
    for side, d in (('A', direction), ('B', (direction + 2) % 4)):
        cross = 1 if d in (0, 1) else 0
        w = case.grid['dy' if cross == 1 else 'dx']
        row_L, row_t = np.average(L, axis=cross, weights=w), np.average(t, axis=cross, weights=w)
        if d in (1, 3):
            row_L, row_t = row_L[::-1], row_t[::-1]
        expected = np.array([predict_K_cF('Gyroid', cell, wall,
            geometry('Gyroid', cell, wall, 16.)['epsilon'] / 2., method=SCO2_DF_METHOD)
            for cell, wall in zip(row_L, row_t)])
        flow = case.parameters['flow_inputs'][side]
        np.testing.assert_allclose(flow['K_m2'], expected[:, 0], rtol=1e-12)
        np.testing.assert_allclose(flow['cF_per_m'], expected[:, 1], rtol=1e-12)
    # The receiver consumes the prepared data, even without the original config.
    save_case(case, tmp_path / 'case.yaml')
    loaded = replace(load_case(tmp_path / 'case.yaml'), config_snapshot={})
    run_cfg, _ = build_execution_inputs(loaded)
    for side in ('A', 'B'):
        np.testing.assert_array_equal(run_cfg['flow_inputs'][side]['K_m2'],
                                      case.parameters['flow_inputs'][side]['K_m2'])


def test_3d_graded_zone_uses_physical_centres_without_changing_smoothing(tmp_path):
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    cfg = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.06, H_dom_m=.03, Lz_m=.03,
                                L_cell_mm=6., t_wall_mm=.3),
        solver=SolverConfig(Nx=24, Ny=12, Nz=12),
        zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': [
            dict(x0=0., x1=.25, y0=0., y1=1., L=4., t=.3),
            dict(x0=.25, x1=1., y0=0., y1=1., L=8., t=.3)]}),
        flags=FeatureFlags(port_wall_refine=True), extrap=ExtrapPolicy(allow=True))
    case = prepare_case(cfg, case_id='physical-3d-zone')
    nx, ny, nz = (len(case.grid['d' + a]) for a in 'xyz')
    first = _centres(case.grid['dx']) < .25
    assert first.sum() != round(.25 * nx)
    raw = np.broadcast_to(np.where(first, 4., 8.)[:, None], (nx, ny)).copy()
    expected = gaussian_filter(raw, sigma=2.)
    old = np.full((nx, ny), 8.)
    old[:round(.25 * nx)] = 4.
    assert np.max(abs(expected - gaussian_filter(old, sigma=2.))) > 1.
    np.testing.assert_allclose(case.design_fields['L_field_m'],
        np.broadcast_to(expected[:, :, None] * 1e-3, (nx, ny, nz)), rtol=1e-14)
    # All physical products derive from that same smoothed L/t field.
    for i in (0, 5, 8, nx - 1):
        Lmm = expected[i, 0]
        g = geometry('Gyroid', Lmm, .3, 16.)
        expected_K, _ = predict_K_cF('Gyroid', Lmm, .3, .5 * g['epsilon'])
        assert case.design_fields['K_m2'][i, 0, 0] == pytest.approx(expected_K, rel=1e-12)
    save_case(case, tmp_path / 'case.yaml')
    loaded = replace(load_case(tmp_path / 'case.yaml'), config_snapshot={})
    _, prepared = build_execution_inputs(loaded)
    np.testing.assert_array_equal(prepared['design']['L_field_m'], case.design_fields['L_field_m'])


def test_3d_zone_default_overlap_and_index_smoothing_are_preserved():
    from sjtu_tpmshx.models.grid_3d import _build_zone_fields_3d
    dx, dy = np.array([.01, .02, .03]), np.array([.003, .007, .02])
    cells = [dict(x0=0., x1=.5, y0=0., y1=1., L=4., t=.3),
             dict(x0=0., x1=1., y0=0., y1=.2, L=8., t=.5)]
    L, t, _ = _build_zone_fields_3d(cells, dx, dy, 2, 'Gyroid', 16., 6., .4)
    expected_L = gaussian_filter(np.array([[8., 4., 4.], [8., 4., 4.], [8., 6., 6.]]), 2.)
    expected_t = gaussian_filter(np.array([[.5, .3, .3], [.5, .3, .3], [.5, .4, .4]]), 2.)
    np.testing.assert_allclose(L, np.repeat(expected_L[:, :, None], 2, axis=2))
    np.testing.assert_allclose(t, np.repeat(expected_t[:, :, None], 2, axis=2))
