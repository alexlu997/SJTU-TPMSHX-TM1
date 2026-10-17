"""Portable native 2D fields, diagnostics and metric evidence remain usable."""
from collections.abc import Mapping
from dataclasses import replace
import os
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig, PartialBCConfig, ZoneInputConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import RangeRecord, warning_scope
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import capture_result
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
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
        if isinstance(expected, np.ndarray):
            assert np.shape(actual) == expected.shape, path
            if expected.dtype.kind in 'biu':
                np.testing.assert_array_equal(actual, expected, err_msg=path)
                return
        rtol, atol = 2e-8, 2e-10
        if any(key in path for key in ('/Ta', '/Tb', '/Ts', 'temperature', 'T_out', 'residual_K')):
            rtol, atol = 2e-9, 2e-7
        elif any(key in path for key in ('/P_', '_Pa', 'pressure')):
            atol = 2e-5
        elif path.rsplit('/', 1)[-1].startswith('Q') or any(key in path for key in (
                'W_per_m', 'h_faces', '/energy/', '/Q', 'denominator', 'solid_abs_sum', 'fluid_abs_sum', 'fluid_cell_max')):
            atol = 2e-7
        elif path.endswith('residual_cellmax_rel'):
            atol = 1e-8  # Near-zero residual ratios; physical gates are separate.
        np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True, err_msg=path)
    else:
        assert actual == expected, path


def test_power_comparison_uses_units_at_root_and_nested_paths():
    for path in ('Q_net', 'diagnostics/Q_net'):
        compare(2.153230187265869, 2.15323, path)
        with pytest.raises(AssertionError):
            compare(2.15324, 2.15323, path)
    with pytest.raises(AssertionError):
        compare(False, True, 'Q_richardson_warn')
    with pytest.raises(AssertionError):
        compare(np.array([100001]), np.array([100000]), 'counts')


def captured(driver, case):
    cfg, prepared = build_execution_inputs(case)
    raw = driver.run_prepared(cfg, prepared, RunControl())
    return capture_result(case, cfg, prepared, raw), raw


def check_portable(actual, raw, case):
    assert actual.backend_id == 'cpp' and actual.backend_version == 'full_2d_v6'
    assert actual.case_id == case.case_id
    compare(actual.grid, case.grid, 'grid')
    compare(actual.metadata['parameters'], case.parameters, 'parameters')
    compare(actual.metadata['design_fields'], case.design_fields, 'design_fields')
    assert actual.run_status['execution'] == 'completed'
    for key, source in (('converged', 'converged'), ('envelope_valid', 'envelope_ok'),
                        ('final_flow_after_last_thermal', 'post_after_last_thermal')):
        assert actual.run_status[key] == raw[source]
    assert actual.run_status['outer_index'] == raw['iterations']-1
    for key, temperature in zip(('Ta','Tb','Ts'), raw['main']['temperature']):
        np.testing.assert_array_equal(actual.fields[key], temperature)
        assert actual.field_metadata[key]['state'] == 'raw last main thermal return'
    for i,side in enumerate('AB'):
        for target, source in (('P_thermal_', 'pressure'), ('h_v', 'hv')):
            np.testing.assert_array_equal(actual.fields[target+side], raw['main'][source][i])
        for target, source in (('P_report_', 'absolute_pressure'), ('uc', 'uc'), ('vc', 'vc')):
            np.testing.assert_array_equal(actual.fields[target+side], raw['flow'][i][source])
        for got, expected in zip(actual.boundary_fluxes['mass_'+side],
                                 (raw['main']['mass_x'][i], raw['main']['mass_y'][i])):
            np.testing.assert_array_equal(got, expected)
    balance = evaluate_physical_balance(actual)
    for name in ('energy','fine_energy'):
        item = balance.get(name)
        if item is not None and item['status'] == 'available':
            assert abs(item['telescoping_error']) < 2e-7
    from sjtu_tpmshx.result_math import pressure_face_values
    pressure_drop = []
    for side, flow in zip('AB', raw['flow']):
        inlet, outlet = pressure_face_values(flow['pressure'],flow['dy'])
        opening = case.parameters['boundary_openings'][side]
        pressure_drop.append(np.average(inlet,weights=flow['dx']*opening['in_geom_frac'])
            - np.average(outlet,weights=flow['dx']*opening['out_geom_frac']))
    metrics = evaluate(actual).metrics
    expected = dict(Q=abs(raw['duty'][0]), Q_A=raw['duty'][0], Q_B=raw['duty'][1],
        dP_A=pressure_drop[0], dP_B=pressure_drop[1],
        T_out_A=raw['outlet_temperature'][0], T_out_B=raw['outlet_temperature'][1],
        mass_flow_A=raw['inlet_mass'][0], mass_flow_B=raw['inlet_mass'][1],
        energy_imbalance_rel=abs(sum(raw['duty'])) / max(*(abs(q) for q in raw['duty']), 1e-30))
    for key,value in expected.items():
        assert metrics[key].status == ('available' if np.isfinite(value) else 'unavailable')
        if np.isfinite(value):
            compare(metrics[key].value, value, key)
    if raw['fine'] is not None:
        fine = actual.boundary_fluxes['fine']
        for key, value in zip(('Ta','Tb','Ts'),raw['fine']['temperature']):
            np.testing.assert_array_equal(fine[key],value)
        info = actual.metadata['diagnostics']['richardson_info']
        assert info['converged'] == (raw['fine']['stop']==0)
        assert info['iterations'] == raw['fine']['iterations']
        assert info['extrapolated'] == raw['fine_extrapolated']


def check_range_records(records, rows):
    groups = {}
    for row in rows:
        source = (row['view'], row['model'], row['topology']) if row['view'].startswith('nu') else (row['view'], row['model'])
        key = (*source, tuple(row['shape']), (row['side'], row['stage'], row['layout']))
        groups.setdefault(key, []).append(row)
        assert row['size'] == int(np.prod(row['shape']))
        for bound in ('minimum','maximum'):
            if row[bound] is not None:
                assert len(row[bound][1]) == len(row['shape'])
                assert all(0 <= index < size for index,size in zip(row[bound][1],row['shape']))
    for key, snapshots in groups.items():
        record = records[key]
        assert isinstance(record, RangeRecord)
        worst = max(snapshots,key=lambda row: row['low']+row['high'])
        for field in ('bounds','size','low','high'):
            assert getattr(record,field) == worst[field]
        assert record.nonfinite == max(row['nonfinite'] for row in snapshots)
        for field,select in (('minimum',min),('maximum',max)):
            candidates = [row[field] for row in snapshots if row[field] is not None]
            expected = select(candidates,key=lambda value:value[0]) if candidates else None
            compare(getattr(record,field),expected,field)


@pytest.mark.parametrize('mode', ['model_h', 'true_h'])
def test_capped_partial_fields_last_inputs_and_recomputed_metrics(driver, mode):
    case = prepare_case(configuration(directions=(1, 2), outer=2, partial=True, mode=mode),
                        case_id='capture-partial-' + mode)
    with warning_scope({}) as actual_records:
        actual, raw = captured(driver, case)
    check_range_records(actual_records, raw['range_observations'])
    check_portable(actual, raw, case)
    for result in (actual,):
        samples = result.metadata['property_sampling']
        for label in 'AB':
            fluid = case.model_refs[case.metadata['model_roles']['fluid_' + label]].parameters['fluid']
            hv = [r for r in samples if r['side'] == label and r['stage'] == 'thermal_hv' and r['quantity'] == 'conductivity']
            assert len(hv) == 1 and hv[0]['outer_index'] == result.run_status['outer_index']
            assert hv[0]['pressure'] == 'inlet'
            operation = 'local_evaluation' if fluid in ('co2', 'sco2') else 'scalar_evaluation'
            assert hv[0]['operation'] == operation
        post = [r for r in samples if r['stage'] == 'property_post']
        assert max(r['outer_index'] for r in post) == result.run_status['outer_index']
        assert any(r['stage'] == 'refined_thermal' for r in samples) == (mode == 'model_h')
    assert actual.metadata['input_resolution']['source'] == 'CaseData.parameters'
    assert actual.run_status['final_flow_after_last_thermal']
    assert not actual.run_status['converged']
    assert not np.array_equal(actual.fields['Ta'], actual.fields['Ta_display'])
    np.testing.assert_array_equal(actual.metadata['rho_cp_A'], None if mode == 'true_h' else raw['main']['rho_cp'][0])
    assert actual.metadata['diagnostics']['native_full_2d']['range_observations']
    assert actual.metadata['enthalpy_update_normalization'] == raw['enthalpy_update_normalization']
    if mode == 'true_h':
        from sjtu_tpmshx.solvers.execution_record import full_execution_record
        scale = full_execution_record(case, actual)['numerics']['enthalpy_update_normalization']
        assert scale['definition'] == 'inlet_cp_times_temperature_difference_v1'
        assert scale['unit'] == 'J/kg' and all(value >= 1 for value in scale['sides'].values())


def test_capped_temperature_capture_uses_current_full_cc_enthalpy(driver):
    """Check exported fullCC powers from the signed boundary ledger."""

    case = prepare_case(configuration(directions=(1, 2), outer=2, mode='temperature'),
                        case_id='capture-partial-temperature')
    with warning_scope({}) as actual_records:
        actual, raw = captured(driver, case)
    check_range_records(actual_records, raw['range_observations'])
    check_portable(actual, raw, case)
    assert actual.run_status['final_flow_after_last_thermal'] and not actual.run_status['converged']
    assert not np.array_equal(actual.fields['Ta'], actual.fields['Ta_display'])
    np.testing.assert_array_equal(actual.metadata['rho_cp_A'], raw['main']['rho_cp'][0])
    for stage in ('main', 'fine'):
        evidence = actual.boundary_fluxes if stage == 'main' else actual.boundary_fluxes['fine']
        ledger = evidence['temperature']
        assert ledger['definition'] == 'model_enthalpy_temperature_v1'
        assert ledger['physical_dimension'] == 2 and ledger['power_units'] == 'W/m'
        assert ledger['physical_boundary_complete'] and raw[stage]['stop'] == 0
        for phase in ('A', 'B', 'solid'):
            compare(ledger['residual'][phase], raw[stage]['temperature_evidence']['residual'][phase])
            for kind in ('advective_out', 'diffusive_out'):
                compare(ledger[kind][phase], raw[stage]['temperature_evidence'][kind][phase])
        powers = [-sum(np.sum(face) for face in ledger['advective_out'][side].values()) for side in 'AB']
        compare(powers, raw['duty'] if stage == 'main' else raw['fine_duty'], stage + '/Q')
        thermal = raw[stage]
        area = thermal['dx'][:,None] * thermal['dy'][None,:]
        temperatures = thermal['temperature']
        scale = max(1., *(abs(np.sum(thermal['hv'][i]*(temperatures[i]-temperatures[2])*area)) for i in range(2)))
        boundary = sum(np.sum(face) for kind in ('advective_out','diffusive_out')
                       for phase in ('A','B','solid') for face in ledger[kind][phase].values())
        error = max(abs(boundary-sum(ledger['source_integral'].values())-ledger['prescribed_b_power']),
                    *(np.abs(value).sum() for value in ledger['residual'].values()))
        assert error / scale <= 1e-7
    fine = actual.boundary_fluxes['fine']
    assert fine['native'] == dict(abi=2, algorithm='model_h_tface_sou_fou_strict_v3', red_black=False)
    assert fine['mass_unit'] == 'kg/(s m)'
    for index, side in enumerate('AB'):
        compare(fine['mass_' + side], (raw['fine']['mass_x'][index], raw['fine']['mass_y'][index]))
    metrics = evaluate(actual).metrics
    powers = raw['duty']
    for side, power in zip('AB', powers):
        assert metrics['Q_' + side].status == 'available'
        compare(metrics['Q_' + side].value, power, 'Q_' + side)
    assert metrics['Q'].status == metrics['energy_imbalance_rel'].status == 'available'
    compare(metrics['Q'].value, abs(powers[0]), 'Q')
    compare(metrics['energy_imbalance_rel'].value, abs(sum(powers)) / max(map(abs, powers)))


@pytest.mark.parametrize('outer,warm', [(2, False), (2, True)])
def test_range_ledger_keeps_scalar_warm_sources_and_worst_snapshot_counts(driver, outer, warm):
    config = configuration(directions=(2, 1), outer=outer, warm=warm, mode='model_h')
    config = replace(config, fluid_A=replace(config.fluid_A, T_in_K=1150.))
    case = prepare_case(config, case_id=f'range-hot-air-{outer}-{warm}')
    with warning_scope({}) as actual_records:
        actual, raw = captured(driver, case)
    check_range_records(actual_records, raw['range_observations'])
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
    with warning_scope({}) as actual_records:
        actual, raw = captured(driver, case)
    check_range_records(actual_records, raw['range_observations'])
    compare(actual.metadata['diagnostics']['sco2_nu_observations'],
            raw['sco2_nu_observations'], 'sco2_nu_observations')


def test_continuous_geometry_range_sources_keep_actual_cell_shapes(driver):
    config = configuration(directions=(1, 2), outer=2, mode='model_h')
    config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
        'x_decision': [6.7, 7.2, 7., 7.5, .45, .5, .55, .58],
        'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False, 'spline_order': 1,
        'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    case = prepare_case(config, case_id='range-continuous')
    with warning_scope({}) as actual_records:
        actual, raw = captured(driver, case)
    check_range_records(actual_records, raw['range_observations'])
    assert np.ptp(actual.metadata['design_fields']['eps_arr']) > 0
    assert any(tuple(row['shape']) == actual.fields['Ta'].shape for row in raw['range_observations'])


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
    actual, raw = captured(driver, case)
    check_portable(actual, raw, case)
    assert actual.run_status['converged'] == (design != 'capped')
    assert actual.metadata['diagnostics']['model_h_balance']['fine']['B']['physical_boundary_complete']


def test_golden_air_prepared_case_retains_accepted_refinement(driver):
    from sjtu_tpmshx.solvers.api import run_case
    case = prepare_case(ComputeConfig.from_json(str(ROOT / 'examples/three_module/air_2d.json')),
                        case_id='capture-golden-air2d')
    actual = run_case(case, RunControl(native_library=str(driver.path),
                                      native_table_directory=os.fsdecode(driver.table_directory)))
    balance = evaluate_physical_balance(actual)
    for name in ('energy', 'fine_energy'):
        assert balance[name]['status'] == 'available'
        assert abs(balance[name]['telescoping_error']) < 2e-7
    assert actual.run_status['converged']
    assert actual.metadata['diagnostics']['richardson_info']['extrapolated']


def test_cancelled_native_return_cannot_be_captured():
    with pytest.raises(CancelledError):
        capture_result(None, None, None, dict(cancelled=True))
