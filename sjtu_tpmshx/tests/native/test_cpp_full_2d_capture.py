"""Portable native 2D fields, diagnostics and metric evidence remain usable."""
from collections.abc import Mapping
from dataclasses import replace
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig, PartialBCConfig, ZoneInputConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import RangeRecord, warning_scope
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import capture_result
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs, run_case as python_run
from sjtu_tpmshx.tests.native.test_full_2d import ROOT, configuration


@pytest.fixture(scope='module')
def driver():
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    name = 'tpmshx_solver_shared.dll' if os.name == 'nt' else 'libtpmshx_solver_shared.dylib'
    path = Path(os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY', ROOT / '.cache/native-deps/build' / ('pilot-' + host) / name))
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(f'native full library unavailable: {path}')
        pytest.skip(f'native full library unavailable: {path}')
    # Full 2D and full 3D load the same library, which fixes one EOS directory.
    return NativeFull2DDriver(path, table_directory=ROOT / '.cache/native-deps/tables')


def compare(actual, expected, path=''):
    if isinstance(expected, Mapping):
        assert actual.keys() == expected.keys(), path
        for key, value in expected.items():
            compare(actual[key], value, path + '/' + str(key))
    elif isinstance(expected, (tuple, list)):
        assert len(actual) == len(expected), path
        for index, value in enumerate(expected):
            compare(actual[index], value, path + '/' + str(index))
    elif isinstance(expected, (np.ndarray, float, np.floating)):
        rtol, atol = 2e-8, 2e-10
        if any(key in path for key in ('/Ta', '/Tb', '/Ts', 'temperature', 'T_out', 'residual_K')):
            rtol, atol = 2e-9, 2e-7
        elif any(key in path for key in ('/P_', '_Pa', 'pressure')):
            atol = 2e-5
        elif any(key in path for key in ('W_per_m', 'h_faces', '/Q', 'denominator', 'solid_abs_sum', 'fluid_abs_sum', 'fluid_cell_max')):
            atol = 2e-7
        np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True, err_msg=path)
    else:
        assert actual == expected, path


def captured(driver, case):
    cfg, prepared = build_execution_inputs(case)
    with patch('sjtu_tpmshx.solvers.backends.python.two_d.runtime.build_runtime',
               side_effect=AssertionError('Python SIMPLE construction called')), \
         patch('sjtu_tpmshx.solvers.backends.python.two_d.coupling._run_solvers',
               side_effect=AssertionError('Python outer driver called')):
        raw = driver.run_prepared(cfg, prepared, RunControl(backend='cpp'))
        return capture_result(case, cfg, prepared, raw), raw


def compare_portable(actual, expected):
    assert actual.backend_id == 'cpp'
    assert actual.backend_version == 'full_2d_v2'
    for key in ('fields', 'field_metadata', 'pressure_evidence', 'run_status'):
        compare(getattr(actual, key), getattr(expected, key), key)
    fluxes = dict(actual.boundary_fluxes)
    if actual.metadata['thermal_mode'] == 'model_h':
        assert expected.metadata['thermal_mode'] == 'model_h'
        fine = dict(fluxes['fine'])
        assert fine.pop('native') == dict(
            abi=2, algorithm='shared_fv_model_h_2d_defect_v1', red_black=False)
        fluxes['fine'] = fine
    compare(fluxes, expected.boundary_fluxes, 'boundary_fluxes')
    for key in ('model_metadata', 'application', 'reporting_reference', 'df_metadata'):
        compare(actual.metadata[key], expected.metadata[key], key)
    actual_metrics, expected_metrics = evaluate(actual).metrics, evaluate(expected).metrics
    for key in ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B', 'mass_flow_A', 'mass_flow_B', 'energy_imbalance_rel'):
        a, e = actual_metrics[key], expected_metrics[key]
        assert a.status == e.status, (key, a, e)
        compare(a.value, e.value, key)
    a, e = actual.metadata['diagnostics'], expected.metadata['diagnostics']
    compare(a['convergence_detail'], e['convergence_detail'], 'convergence_detail')
    compare(a['richardson_info'], e['richardson_info'], 'richardson_info')
    compare(a['model_h_balance'], e['model_h_balance'], 'model_h_balance')
    compare(a['sco2_nu_observations'], e['sco2_nu_observations'], 'sco2_nu_observations')
    for key in ('Q_A', 'Q_B', 'Q_net', 'Q_solid_richardson', 'Q_richardson_warn', 'energy_imbalance_rel',
                'envelope_valid', 'envelope_reasons', 'p_clip_hits'):
        compare(a[key], e[key], key)


def compare_range_records(actual, expected):
    assert actual.keys() == expected.keys()
    for key, e in expected.items():
        a = actual[key]
        if not isinstance(e, RangeRecord):
            assert a == e, key
            continue
        for name in ('label', 'quantity', 'unit', 'bounds', 'low', 'high', 'size', 'nonfinite'):
            assert getattr(a, name) == getattr(e, name), (key, name, a, e)
        for name in ('minimum', 'maximum'):
            v, w = getattr(a, name), getattr(e, name)
            if w is None:
                assert v is None
            else:
                assert v[1] == w[1], (key, name, v, w)
                np.testing.assert_allclose(v[0], w[0], rtol=2e-9 if e.quantity == 'T' else 2e-8,
                    atol=2e-7 if e.quantity == 'T' else 2e-10, err_msg=str((key, name)))


@pytest.mark.parametrize('mode', ['temperature', 'model_h', 'true_h'])
def test_capped_partial_fields_last_inputs_and_recomputed_metrics(driver, mode):
    case = prepare_case(configuration(directions=(1, 2), outer=2, partial=True, mode=mode),
                        case_id='capture-partial-' + mode)
    with warning_scope({}) as expected_records:
        expected = python_run(case)
    with warning_scope({}) as actual_records:
        actual, raw = captured(driver, case)
    compare_range_records(actual_records, expected_records)
    compare_portable(actual, expected)
    assert actual.run_status['final_flow_after_last_thermal']
    assert not actual.run_status['converged']
    assert not np.array_equal(actual.fields['Ta'], actual.fields['Ta_display'])
    np.testing.assert_array_equal(actual.metadata['rho_cp_A'], None if mode == 'true_h' else raw['main']['rho_cp'][0])
    assert actual.metadata['diagnostics']['native_full_2d']['range_observations']


@pytest.mark.parametrize('outer,warm', [(2, False), (2, True)])
def test_range_ledger_keeps_scalar_warm_sources_and_worst_snapshot_counts(driver, outer, warm):
    config = configuration(directions=(2, 1), outer=outer, warm=warm, mode='model_h')
    config = replace(config, fluid_A=replace(config.fluid_A, T_in_K=1150.))
    case = prepare_case(config, case_id=f'range-hot-air-{outer}-{warm}')
    with warning_scope({}) as expected_records:
        python_run(case)
    with warning_scope({}) as actual_records:
        actual, _ = captured(driver, case)
    compare_range_records(actual_records, expected_records)
    assert any(isinstance(value, RangeRecord) and value.high for value in actual_records.values())
    assert any('worst single snapshot:' in message for message in actual.metadata['diagnostics']['warnings_list'])


@pytest.mark.parametrize('fluids,topology,experimental', [
    (('air', 'sco2'), 'Gyroid', False), (('sco2', 'air'), 'Diamond', True),
])
def test_true_h_air_property_sources_and_selected_sco2_nu_are_recorded(driver, fluids, topology, experimental):
    config = configuration(directions=(3, 0), outer=2, mode='true_h')
    sides = [replace(side, type=fluid, u_mps=3. if fluid == 'air' else .015)
             for side, fluid in zip((config.fluid_A, config.fluid_B), fluids)]
    config = replace(config, fluid_A=sides[0], fluid_B=sides[1], geometry=replace(config.geometry, tpms=topology))
    if experimental:
        from sjtu_tpmshx.models.nu_correlations import sco2_effective_nu_config
        config = replace(config, sco2_nu=sco2_effective_nu_config())
    case = prepare_case(config, case_id='range-true-h-' + topology)
    with warning_scope({}) as expected_records:
        expected = python_run(case)
    with warning_scope({}) as actual_records:
        actual, _ = captured(driver, case)
    compare_range_records(actual_records, expected_records)
    compare(actual.metadata['diagnostics']['sco2_nu_observations'],
            expected.metadata['diagnostics']['sco2_nu_observations'], 'sco2_nu_observations')


def test_continuous_geometry_range_sources_keep_actual_cell_shapes(driver):
    config = configuration(directions=(1, 2), outer=2, mode='model_h')
    config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
        'x_decision': [6.7, 7.2, 7., 7.5, .45, .5, .55, .58],
        'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False, 'spline_order': 1,
        'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    case = prepare_case(config, case_id='range-continuous')
    with warning_scope({}) as expected_records:
        python_run(case)
    with warning_scope({}) as actual_records:
        actual, _ = captured(driver, case)
    compare_range_records(actual_records, expected_records)
    assert np.ptp(actual.metadata['design_fields']['eps_arr']) > 0


@pytest.mark.parametrize('design,air_velocity,water_velocity,outer', [
    ('uniform', 5.2872852724903385, .15147894181163646, None),
    ('graded', 4.3887813213360864, .13535732642734744, None),
    ('capped', 4.406071060408616, .15147894181163646, 2),
    ('capped', 5.2872852724903385, .15147894181163646, 2),
])
def test_partial_optimization_cases_preserve_fine_water_balance(
        driver, design, air_velocity, water_velocity, outer):
    """Real search failures amplify lost inlet/Nu input bits in fine B balances."""
    config = configuration(mode='model_h')
    config = replace(config,
        fluid_A=replace(config.fluid_A, u_mps=air_velocity, T_in_K=380., P_in_Pa=160000.),
        fluid_B=replace(config.fluid_B, u_mps=water_velocity),
        geometry=replace(config.geometry, L_dom_m=.04, H_dom_m=.05, Lz_m=.02),
        solver=replace(config.solver, Nx=12, Ny=12, max_outer_ltne=outer, max_iter_simple=None),
        bc_A=PartialBCConfig(dir=1, in_ctr=.023, in_w=.021, out_ctr=.025, out_w=.019),
        bc_B=PartialBCConfig(dir=3, in_ctr=.018, in_w=.027, out_ctr=.023, out_w=.021))
    if design != 'capped':
        decision = ([7.]*4 + [.6]*4 if design == 'uniform' else [
            7.785843264311552, 7.073380693793297, 4.871927723288536, 4.279493872076273,
            .5242245613597334, .32955440450459716, .4792536654509604, .30094371596351266])
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': decision, 'n_ctrl_x': 2, 'n_ctrl_y': 2,
            'symmetric_y': False, 'spline_order': 1,
            'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    case = prepare_case(config, case_id=f'partial-optimization-{design}-{air_velocity}')
    expected = python_run(case)
    actual, _ = captured(driver, case)
    compare_portable(actual, expected)
    assert actual.run_status['converged'] == (design != 'capped')
    assert actual.metadata['diagnostics']['model_h_balance']['fine']['B']['physical_boundary_complete']


def test_golden_air_prepared_case_retains_accepted_refinement(driver):
    from sjtu_tpmshx.solvers.api import run_case
    case = prepare_case(ComputeConfig.from_json(str(ROOT / 'examples/three_module/air_2d.json')),
                        case_id='capture-golden-air2d')
    expected = python_run(case)
    with patch('sjtu_tpmshx.solvers.backends.python.two_d.runtime.build_runtime',
               side_effect=AssertionError('Python SIMPLE construction called')):
        actual = run_case(case, RunControl(backend='cpp', native_library=str(driver.path),
                                          native_table_directory=os.fsdecode(driver.table_directory)))
    compare_portable(actual, expected)
    assert actual.run_status['converged']
    assert actual.metadata['diagnostics']['richardson_info']['extrapolated']


def test_cancelled_native_return_cannot_be_captured():
    with pytest.raises(CancelledError):
        capture_result(None, None, None, dict(cancelled=True))
