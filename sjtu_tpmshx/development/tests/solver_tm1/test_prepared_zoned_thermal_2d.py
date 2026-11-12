"""Zoned heat transfer follows physical cells through the prepared SI handoff."""
import builtins
import json
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.shared.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, PartialBCConfig,
    ZoneInputConfig, ExtrapPolicy,
)
from sjtu_tpmshx.shared.models.zone_config import Zone, ZoneConfig
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
from sjtu_tpmshx.development.tests import sigmoid_reference


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
def test_new_zoned_preparation_uses_current_chi_s(monkeypatch, mode):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    compute.cache_clear()
    try:
        monkeypatch.setenv('TPMSHX_CHI_S', '.5')
        first = prepare_case(_config(mode), case_id='chi-half')
        monkeypatch.setenv('TPMSHX_CHI_S', '1.0')
        second = prepare_case(_config(mode), case_id='chi-one')
        np.testing.assert_allclose(second.design_fields['K_ss_arr'],
                                   2. * first.design_fields['K_ss_arr'], rtol=1e-14)
        # Later settings must not reinterpret either immutable prepared Case.
        monkeypatch.setenv('TPMSHX_CHI_S', '.25')
        for case in (first, second):
            inputs, _ = build_execution_inputs(case)
            np.testing.assert_array_equal(inputs['za']['K_ss_arr'],
                                          case.design_fields['K_ss_arr'])
    finally:
        compute.cache_clear()


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
def test_discrete_geometry_uses_final_physical_cell_centres(mode):
    from sjtu_tpmshx.shared.models.tpms_props import geometry
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
    from sjtu_tpmshx.shared.models import sigmoid_field
    from sjtu_tpmshx.shared.models.tpms_props import geometry
    from sjtu_tpmshx.shared.df_surrogate.predict import predict_K_cF_vec
    # A small real LUT is sufficient to test coordinate transport, not LUT accuracy.
    lut = sigmoid_field.GeometryLUT('Gyroid', n_L=2, n_t=2, N=16, cache_dir=tmp_path)
    monkeypatch.setitem(sigmoid_field._lut_cache, ('Gyroid',), lut)
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
    expected = sigmoid_reference.sigmoid_field_2d(XF, YF, ctrl[0], ctrl[1], 7., .2, .2, .05, .02)
    np.testing.assert_allclose(case.design_fields['L_field_m'], expected * 1e-3)
    U, V = np.meshgrid((np.arange(len(xf)) + .5) / len(xf),
                       (np.arange(len(yf)) + .5) / len(yf), indexing='ij')
    indexed = sigmoid_reference.sigmoid_field_2d(U, V, ctrl[0], ctrl[1], 7., .2, .2, .05, .02)
    assert np.max(np.abs(expected - indexed)) > .01
    assert case.parameters['thermal_geometry']['fields'] is not None

    # The same physical cells also feed SIMPLE's streamwise drag. Derive the
    # expected rows directly: transverse length-weighted means, then reverse
    # each negative-direction stream. Source and solver cells match,
    # so a second uniform-index resampling must not move these row values.
    t_ctrl = decision[1::2].reshape(2, 3, 3)
    expected_t = sigmoid_reference.sigmoid_field_2d(
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
    from sjtu_tpmshx.shared.io.case_io import save_case, load_case
    from sjtu_tpmshx.shared.models import tpms_props, fluid_props
    from sjtu_tpmshx.shared.models.nu_correlations import NU_LAM_FLOOR
    from sjtu_tpmshx.development.tests.native.prepared_snapshot import native_prepared_state
    case = prepare_case(_config(), case_id='zoned-handoff')
    save_case(case, tmp_path / 'case.yaml')
    loaded = replace(load_case(tmp_path / 'case.yaml'), config_snapshot={})
    cfg, grid = build_execution_inputs(loaded)
    np.testing.assert_allclose(cfg['za']['L_field'], case.design_fields['L_field_m'] * 1e3)
    def forbidden(*args, **kwargs):
        raise AssertionError('execution recomputed fixed geometry')
    monkeypatch.setattr(tpms_props, 'geometry', forbidden)
    _, _, state = native_prepared_state(loaded)
    shape = case.design_fields['eps_arr'].shape
    model = fluid_props.get('air')
    geometry = case.parameters['thermal_geometry']['fields']
    for index, (side, temp, pressure) in enumerate((
            ('A', 450., 2e5), ('B', 300., 1.2e5))):
        speed = np.hypot(*(state[f'state.result.flow.{index}.{axis}'].reshape(shape)
                           for axis in ('uc', 'vc')))
        Re = float(model.rho(temp, pressure)) * (speed + 1e-12) * geometry['D_h'] / float(model.mu(temp, pressure))
        Nu = np.maximum(model.nu('Gyroid', np.maximum(Re, 1.), geometry['epsilon'] / 2.,
                                  cfg['za']['L_field'], geometry['D_h'] * 1e3, None), NU_LAM_FLOOR)
        expected = geometry['A_0'] * Nu * float(model.k(temp, pressure)) / geometry['D_h']
        np.testing.assert_allclose(state[f'state.result.thermal.hv.{index}'].reshape(shape),
                                   expected, rtol=1e-12)


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
    from sjtu_tpmshx.shared.models.input_validation import surrogate_extrap_reasons
    original_import = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == 'sjtu_tpmshx.shared.df_surrogate.surrogate_domain':
            raise ImportError('required surrogate unavailable')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', unavailable)
    with pytest.raises(ImportError, match='required surrogate unavailable'):
        surrogate_extrap_reasons(_config(), allow_extrap=True)


def test_sigmoid_saved_execution_keeps_row_drag(monkeypatch, tmp_path):
    from sjtu_tpmshx.applications.result_adapter import to_compute_result
    from sjtu_tpmshx.postprocess.api import evaluate
    from sjtu_tpmshx.preprocess import api as preparation_api
    from sjtu_tpmshx.shared.domain.module_ports import RunControl
    from sjtu_tpmshx.shared.domain.portable_data import mutable_data
    from sjtu_tpmshx.shared.io.case_io import save_case, load_case
    from sjtu_tpmshx.shared.io.result_io import save_result, load_result
    from sjtu_tpmshx.shared.io.metrics_io import save_metrics
    from sjtu_tpmshx.shared.models import sigmoid_field, tpms_props, _native_preparation_case
    from sjtu_tpmshx.solvers.api import run_case

    # This small real LUT checks saved execution, not LUT accuracy.
    lut = sigmoid_field.GeometryLUT('Gyroid', n_L=2, n_t=2, N=16, cache_dir=tmp_path / 'lut')
    monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *a, **k: lut)
    config = _config('grid')
    config.zones.pareto_x_decision = np.column_stack((
        np.linspace(5., 8., 18), np.linspace(.3, .6, 18))).ravel().tolist()
    config.to_json(tmp_path / 'input.json')
    case = replace(prepare_case(config, case_id='sigmoid-saved-execution'), config_snapshot={})
    save_case(case, tmp_path / 'case.yaml')
    loaded = load_case(tmp_path / 'case.yaml')

    def forbidden(*args, **kwargs):
        raise AssertionError('saved execution must not prepare geometry again')

    monkeypatch.setattr(preparation_api, 'prepare_case', forbidden)
    monkeypatch.setattr(_native_preparation_case, 'operation', forbidden)
    monkeypatch.setattr(tpms_props, 'geometry', forbidden)
    monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', forbidden)
    results, reports = [], []
    for prepared in (case, loaded):
        assert not prepared.config_snapshot
        assert prepared.metadata['design_mode'] == 'continuous'
        assert prepared.parameters['z_axis'] == 'grid'
        assert prepared.parameters['continuous_field'] is None
        cfg, _ = build_execution_inputs(prepared)
        assert not cfg['compute_cfg'].zones.enabled
        assert cfg['z_axis'] == 'grid'
        for side in 'AB':
            flow = cfg['flow_inputs'][side]
            assert 'K_field_m2' not in flow and 'cF_field_per_m' not in flow
            for key in ('K_m2', 'cF_per_m'):
                np.testing.assert_array_equal(flow[key], case.parameters['flow_inputs'][side][key])
        for key, values in case.parameters['thermal_geometry']['fields'].items():
            np.testing.assert_array_equal(cfg['thermal_geometry']['fields'][key], values)
        result = run_case(prepared, RunControl(cpu_threads=1))
        assert result.run_status['execution'] == 'completed'
        assert result.metadata['design_mode'] == 'continuous'
        assert result.metadata['parameters']['z_axis'] == 'grid'
        for key, values in case.design_fields.items():
            np.testing.assert_array_equal(result.metadata['design_fields'][key], values)
        performance = evaluate(result)
        display = to_compute_result(result, performance)
        np.testing.assert_array_equal(display.fields['za']['L_field'],
                                      case.design_fields['L_field_m'] * 1e3)
        assert performance.metrics['Q_B'].spec.unit == 'W/m'
        results.append(result)
        reports.append(performance)
    assert results[0].run_status == results[1].run_status
    assert results[0].fields.keys() == results[1].fields.keys()
    for key in results[0].fields:
        np.testing.assert_array_equal(results[0].fields[key], results[1].fields[key])
    assert reports[0].metrics == reports[1].metrics
    original, restored = (mutable_data(report.qualification) for report in reports)
    for report in (original, restored):
        report.pop('source_result_id')
    assert original == restored
    assert results[0].metadata['diagnostics']['warnings_list'] == results[1].metadata['diagnostics']['warnings_list']
    save_metrics(reports[0], tmp_path / 'original-metrics.json')
    save_metrics(reports[1], tmp_path / 'loaded-metrics.json')
    save_result(results[0], tmp_path / 'original-result.h5')
    save_result(results[1], tmp_path / 'loaded-result.h5')

    completed = subprocess.run([sys.executable, '-m', 'sjtu_tpmshx.applications.cli.stages',
        'solve', str(tmp_path / 'case.yaml'), str(tmp_path / 'cli-result.h5'),
        '--cpu-threads', '1'], capture_output=True, text=True, check=False)
    (tmp_path / 'cli.log').write_text(completed.stdout + completed.stderr)
    assert completed.returncode == (0 if results[1].run_status['converged'] else 2), completed.stderr
    cli = load_result(tmp_path / 'cli-result.h5')
    assert cli.run_status == results[1].run_status
    for key in cli.fields:
        np.testing.assert_array_equal(cli.fields[key], results[1].fields[key])
    (tmp_path / 'verdict.json').write_text(json.dumps(dict(
        execution='completed', original_loaded_cli_fields_exact=True,
        config_snapshot_empty=True, preparation_forbidden=True,
        lut_accuracy_qualified=False, run_status=mutable_data(results[1].run_status),
        qualification=mutable_data(reports[1].qualification)), indent=2) + '\n')
