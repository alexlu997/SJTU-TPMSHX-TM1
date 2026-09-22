"""Zoned heat transfer follows physical cells through the prepared SI handoff."""
import builtins
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, PartialBCConfig,
    ZoneInputConfig, ExtrapPolicy,
)
from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs


def _config(mode='y'):
    cells = [dict(x0=0., x1=1., y0=0., y1=.41, L=7., t=.4),
             dict(x0=0., x1=1., y0=.41, y1=1., L=6., t=.5)]
    zones = ZoneInputConfig(
        enabled=True, axis=mode,
        config=ZoneConfig([Zone('first', 0., .41, 7., .4),
                           Zone('second', .41, 1., 6., .5)], 'Gyroid', 16.),
        grid=dict(cells=cells, tpms_type='Gyroid', k_s=16.))
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=8., T_in_K=450., P_in_Pa=2e5),
        fluid_B=FluidConfig(type='air', u_mps=6., T_in_K=300., P_in_Pa=1.2e5),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.4,
                                k_s_W_mK=16., L_dom_m=.06, H_dom_m=.03),
        solver=SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=2, max_iter_simple=10),
        bc_A=PartialBCConfig(dir=0, in_ctr=.015, in_w=.022,
                            out_ctr=.015, out_w=.022, uniform_inlet_2d=True),
        bc_B=PartialBCConfig(dir=3, in_ctr=.03, in_w=.041,
                            out_ctr=.03, out_w=.041, uniform_inlet_2d=True),
        zones=zones, extrap=ExtrapPolicy(allow=True))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
def test_discrete_geometry_uses_final_physical_cell_centres(mode):
    from sjtu_tpmshx.models.tpms_props import geometry
    case = prepare_case(_config(mode), case_id='zoned-' + mode)
    axis = 'x' if mode == 'x' else 'y'
    widths = case.grid['d' + axis]
    centres = (np.cumsum(widths) - widths / 2.) / widths.sum()
    first = centres < .41
    expected_L = np.broadcast_to((np.where(first, 7., 6.)[:, None]
                                 if axis == 'x' else np.where(first, 7., 6.)[None, :]),
                                (len(case.grid['dx']), len(case.grid['dy'])))
    expected_t = np.where(expected_L == 7., .4, .5)
    np.testing.assert_allclose(case.design_fields['L_field_m'], expected_L * 1e-3)
    np.testing.assert_allclose(case.design_fields['t_field_m'], expected_t * 1e-3)
    assert not np.allclose(widths, widths.mean())
    if axis == 'y':
        # Same shape, different zone assignment: index interpolation cannot pass.
        assert np.any(first != ((np.arange(len(widths)) + .5) / len(widths) < .41))
    for pair in ((7., .4), (6., .5)):
        expected = geometry('Gyroid', *pair, 16.)
        mask = expected_L == pair[0]
        assert np.any(mask)
        for key in ('A_0', 'D_h', 'epsilon'):
            np.testing.assert_array_equal(
                case.parameters['thermal_geometry']['fields'][key][mask],
                np.full(mask.sum(), expected[key]))


@pytest.mark.parametrize('directions', [(0, 3), (1, 2), (2, 1), (3, 0)])
def test_continuous_geometry_is_resampled_on_nonuniform_cells(monkeypatch, tmp_path, directions):
    from sjtu_tpmshx.models import sigmoid_field
    from sjtu_tpmshx.models.tpms_props import geometry
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
    # A small real LUT is sufficient to test coordinate transport, not LUT accuracy.
    lut = sigmoid_field.GeometryLUT('Gyroid', n_L=2, n_t=2, N=16, cache_dir=tmp_path)
    monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *a, **k: lut)
    decision = np.column_stack((np.linspace(5., 8., 18), np.linspace(.3, .6, 18))).ravel()
    config = _config('grid')
    config = replace(config,
        bc_A=replace(config.bc_A, dir=directions[0], in_ctr=.015, in_w=.012,
                     out_ctr=.015, out_w=.012),
        bc_B=replace(config.bc_B, dir=directions[1], in_ctr=.015, in_w=.012,
                     out_ctr=.015, out_w=.012),
        zones=replace(config.zones, pareto_x_decision=decision))
    case = prepare_case(config, case_id='continuous-physical-grid')
    xf = (np.cumsum(case.grid['dx']) - case.grid['dx'] / 2.) / .06
    yf = (np.cumsum(case.grid['dy']) - case.grid['dy'] / 2.) / .03
    XF, YF = np.meshgrid(xf, yf, indexing='ij')
    ctrl = decision[::2].reshape(2, 3, 3)
    expected = sigmoid_field.sigmoid_field_2d(XF, YF, ctrl[0], ctrl[1], 7., .2, .2, .05, .02)
    np.testing.assert_allclose(case.design_fields['L_field_m'], expected * 1e-3)
    U, V = np.meshgrid((np.arange(len(xf)) + .5) / len(xf),
                       (np.arange(len(yf)) + .5) / len(yf), indexing='ij')
    indexed = sigmoid_field.sigmoid_field_2d(U, V, ctrl[0], ctrl[1], 7., .2, .2, .05, .02)
    assert np.max(np.abs(expected - indexed)) > .01
    assert case.parameters['thermal_geometry']['fields'] is not None

    # The same physical cells also feed SIMPLE's streamwise drag. Derive the
    # expected rows directly: transverse length-weighted means, then reverse
    # each negative-direction stream. Source and solver cells match,
    # so a second uniform-index resampling must not move these row values.
    t_ctrl = decision[1::2].reshape(2, 3, 3)
    expected_t = sigmoid_field.sigmoid_field_2d(
        XF, YF, t_ctrl[0], t_ctrl[1], .4, .2, .2, .05, .02)
    np.testing.assert_allclose(case.design_fields['t_field_m'], expected_t * 1e-3)
    for side, direction in zip(('A', 'B'), directions):
        axis = 1 if direction in (0, 1) else 0
        widths = case.grid['dy' if axis == 1 else 'dx']
        row_L = np.average(expected, axis=axis, weights=widths)
        row_t = np.average(expected_t, axis=axis, weights=widths)
        if direction in (1, 3):
            row_L, row_t = row_L[::-1], row_t[::-1]
        row_eps_f = np.array([
            geometry('Gyroid', cell, wall, 16.)['epsilon'] / 2.
            for cell, wall in zip(row_L, row_t)])
        expected_K, expected_cF = predict_K_cF_vec(
            'Gyroid', row_L, row_t, row_eps_f)
        flow = case.parameters['flow_inputs'][side]
        np.testing.assert_allclose(flow['K_m2'], expected_K, rtol=1e-12, atol=0.)
        np.testing.assert_allclose(flow['cF_per_m'], expected_cF, rtol=1e-12, atol=0.)


def test_zoned_si_handoff_feeds_local_thermal_kernel(monkeypatch, tmp_path):
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.models import tpms_props, fluid_props
    from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR
    from sjtu_tpmshx.solvers import simple_solver
    from sjtu_tpmshx.solvers.backends.python.two_d import coupling
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    case = prepare_case(_config(), case_id='zoned-handoff')
    save_case(case, tmp_path / 'case.yaml')
    loaded = replace(load_case(tmp_path / 'case.yaml'), config_snapshot={})
    cfg, grid = build_execution_inputs(loaded)
    np.testing.assert_allclose(cfg['za']['L_field'], case.design_fields['L_field_m'] * 1e3)
    def forbidden(*args, **kwargs):
        raise AssertionError('execution recomputed fixed geometry')
    monkeypatch.setattr(tpms_props, 'geometry', forbidden)
    monkeypatch.setattr(simple_solver.SIMPLESolver, 'solve', lambda *a, **k: (True, 1))
    captured = {}
    class AtThermalKernel(Exception):
        pass
    def capture(*args, **kwargs):
        captured['args'] = args
        raise AtThermalKernel
    monkeypatch.setattr(coupling, 'solve_full_domain', capture)
    with pytest.raises(AtThermalKernel):
        coupling._run_solvers(cfg, build_runtime(cfg, grid))
    args = captured['args']
    model = fluid_props.get('air')
    geometry = case.parameters['thermal_geometry']['fields']
    for side, temp, pressure, hv_index, velocity_index in (
            ('A', 450., 2e5, 9, 14), ('B', 300., 1.2e5, 10, 16)):
        speed = np.hypot(args[velocity_index], args[velocity_index + 1])
        Re = float(model.rho(temp, pressure)) * (speed + 1e-12) * geometry['D_h'] / float(model.mu(temp, pressure))
        Nu = np.maximum(model.nu('Gyroid', np.maximum(Re, 1.), geometry['epsilon'] / 2.,
                                  cfg['za']['L_field'], geometry['D_h'] * 1e3, None), NU_LAM_FLOOR)
        expected = geometry['A_0'] * Nu * float(model.k(temp, pressure)) / geometry['D_h']
        np.testing.assert_allclose(args[hv_index], expected, rtol=1e-12)


@pytest.mark.parametrize('missing', ['L_field_m', 't_field_m', 'thermal_geometry'])
def test_incomplete_prepared_zones_require_repreparation(missing):
    case = prepare_case(_config(), case_id='missing-zoned-geometry')
    if missing == 'thermal_geometry':
        case = replace(case, parameters={**case.parameters, 'thermal_geometry':
                       {**case.parameters['thermal_geometry'], 'fields': None}})
    else:
        design = dict(case.design_fields)
        design.pop(missing)
        case = replace(case, design_fields=design)
    with pytest.raises(ValueError, match='prepare the original configuration again'):
        build_execution_inputs(case)


def test_required_surrogate_import_failure_is_not_an_empty_warning_list(monkeypatch):
    from sjtu_tpmshx.models.input_validation import surrogate_extrap_reasons
    original_import = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == 'sjtu_tpmshx.df_surrogate.surrogate_domain':
            raise ImportError('required surrogate unavailable')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', unavailable)
    with pytest.raises(ImportError, match='required surrogate unavailable'):
        surrogate_extrap_reasons(_config(), allow_extrap=True)
