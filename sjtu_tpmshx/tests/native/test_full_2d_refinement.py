"""Complete prepared 2D coarse -> Richardson -> final physical acceptance.

The oracle executes the existing production outer and _compute_Q_richardson.
No synthetic thermal result, altered budget or weakened gate is substituted.
Frozen tolerances: T 2e-9/2e-7 K, P 2e-8/2e-5 Pa; other fields
2e-8/2e-10, powers/audits 2e-8/2e-7 W/m. Gates/charged counts are exact.
"""
from copy import deepcopy

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.models.grid import split_cells
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d import coupling, execution
from sjtu_tpmshx.tests.native import test_full_2d as coarse
from sjtu_tpmshx.tests.native.test_refinement_2d import interpolate

native = coarse.native  # shared test-only packing/ABI fixture


def power(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=2e-8, atol=2e-7, equal_nan=True)


def compare_audit(actual, expected):
    side_fields = dict(q_advective='Q_advective_W_per_m', inlet_conduction='inlet_conduction_W_per_m',
        exchange='exchange_W_per_m', residual_sum='residual_sum_W_per_m', residual_max='residual_max_abs_W_per_m',
        linearized_sum='linearized_residual_sum_W_per_m', linearized_max='linearized_residual_max_abs_W_per_m',
        defect_sum='linearization_defect_sum_W_per_m', defect_max='linearization_defect_max_abs_W_per_m',
        normalization='strict_normalization_W_per_m')
    mass_fields = dict(mass_net='mass_net_out_kg_s_per_m', mass_local_max='mass_local_max_abs_kg_s_per_m',
        mass_in='mass_in_kg_s_per_m', mass_out='mass_out_kg_s_per_m', cell_ratio='residual_cellmax_rel')
    for side, label in enumerate(('A', 'B')):
        a, e = actual['sides'][side], expected[label]
        for name, key in side_fields.items(): power(a[name], e[key])
        for name, key in mass_fields.items(): coarse.compare_array(a[name], e[key])
        assert a['unknown_inflow_faces'] == e['unknown_inflow_faces']
        for name, key in (('boundary_mass_out', 'boundary_mass_out_kg_s_per_m'),
                          ('boundary_h_out', 'boundary_h_out_W_per_m'), ('h_faces', 'h_faces_W_per_m')):
            for got, target in zip(a[name], e[key]):
                if name == 'boundary_mass_out': coarse.compare_array(got, target)
                else: power(np.asarray(got).reshape(np.shape(target)), target)
        power(a['inlet_conduction_faces'], e['inlet_conduction_faces_W_per_m'])
        coarse.compare_array(a['cp_coefficients'], e['cp_coefficients'])
    for name, key in dict(solid_sum='solid_residual_sum_W_per_m', solid_max='solid_residual_max_abs_W_per_m',
        residual_sum='residual_sum_W_per_m', telescoping_error='telescoping_error_W_per_m',
        net_boundary_in='net_boundary_in_W_per_m', denominator='D2_W_per_m').items():
        power(actual[name], expected[key])
    for name, key in (('solid_cell_ratio', 'solid_residual_cellmax_rel'),
                      ('energy_imbalance', 'energy_imbalance_rel'), ('solid_imbalance', 'solid_imbalance_rel')):
        coarse.compare_array(actual[name], expected[key])
    for name, key in (('boundary_complete', 'physical_boundary_complete'), ('finite', 'finite'),
                      ('energy_ok', 'energy_ok'), ('solid_ok', 'solid_ok'),
                      ('equations_ok', 'equations_ok'), ('passed', 'passed')):
        assert actual[name] == expected[key], (name, actual, expected)


def compare_complete(actual, record):
    _, diagnostics = record['raw_return']
    final_record = record
    if diagnostics['model_h_balance'] is not None:
        # The shared coarse capture precedes the caller's outer certificate.
        # For the completed result compare to the actual final main verdict.
        state = deepcopy(record['state'])
        state.e_info['model_h_balance'] = diagnostics['model_h_balance']['main']
        final_record = dict(record, state=state)
    coarse.compare_coarse(actual, final_record)
    detail = diagnostics['convergence_detail']
    for name, key in (('converged', 'solver_converged'),):
        assert actual[name] == diagnostics[key]
    for name, key in (('simple_ok', 'simple_ok'), ('thermal_ok', 'ltne_ok'),
                      ('envelope_ok', 'envelope_ok'), ('pair_balance_ok', 'enthalpy_balance_ok')):
        assert actual[name] == detail[key], (name, actual[name], detail)
    assert actual['model_balance_ok'] == (True if detail['model_h_balance_ok'] is None else detail['model_h_balance_ok'])
    coarse.compare_array(actual['pressure_drop'], [diagnostics['dP_A'], diagnostics['dP_B']], 'pressure')
    coarse.compare_array(actual['outlet_temperature'], [diagnostics['T_out_A_K'], diagnostics['T_out_B_K']], 'temperature')
    coarse.compare_array(actual['inlet_mass'], [diagnostics['mass_flow_A_kg_s_per_m'], diagnostics['mass_flow_B_kg_s_per_m']])
    power(actual['duty'], [diagnostics['Q_A'], diagnostics['Q_B']])
    power(actual['q_total'], diagnostics['Q_total'])
    power(actual['q_solid'], diagnostics['Q_solid_richardson'])
    coarse.compare_array(actual['energy_imbalance'], diagnostics['energy_imbalance_rel'])
    if diagnostics['richardson_info'] is None:
        assert actual['refined'] is None
        return
    fine, evidence = actual['refined'], record['refinement_evidence']
    info, values = diagnostics['richardson_info'], record['thermal_calls'][-1][0]
    args = record['refinement_inputs']
    shape = (len(evidence['dx']), len(evidence['dy']))
    assert fine['thermal']['result']['iterations'] == info['iterations']
    assert (fine['thermal']['result']['stop'] == 0) == info['converged']
    coarse.compare_array(fine['thermal']['result']['residual'], info['residual'], 'temperature')
    assert fine['extrapolated'] == info['extrapolated']
    assert fine['warning'] == diagnostics['Q_richardson_warn']
    accepted = info['converged'] and (diagnostics['model_h_balance'] is None or
        (diagnostics['model_h_balance']['main']['passed'] and diagnostics['model_h_balance']['fine']['passed']))
    assert fine['accepted'] == accepted
    for axis in ('x', 'y'):
        np.testing.assert_array_equal(fine['d'+axis], split_cells(args['energy_d'+axis]))
    coarse.compare_array(fine['epsilon'], np.broadcast_to(evidence['eps'], shape))
    if np.ndim(evidence['eps']) == 0:
        np.testing.assert_array_equal(np.asarray(fine['epsilon']).reshape(shape), np.broadcast_to(evidence['eps'], shape))
    for got, key in zip(fine['thermal']['temperature'], ('Ta', 'Tb', 'Ts')):
        coarse.compare_array(got, evidence[key], 'temperature')
    for side, label in enumerate(('A', 'B')):
        for key in ('uc', 'vc'):
            coarse.compare_array(fine[key][side], evidence[key+label], 'state')
        for key, name in (('inlet_profile', 'inlet_'), ('outlet_profile', 'outlet_')):
            coarse.compare_array(fine[key][side], evidence[name+label])
        for key, name in (('hv', 'h_v'), ('rho_cp', 'rho_cp_f'), ('conductivity', 'K_ff')):
            coarse.compare_array(fine['thermal'][key][side], np.broadcast_to(values[name+label], shape))
        if np.ndim(values['K_ff'+label]) == 0:
            np.testing.assert_array_equal(np.asarray(fine['thermal']['conductivity'][side]).reshape(shape),
                                          np.broadcast_to(values['K_ff'+label], shape))
        pressure = coupling._simple_pressure_abs_2d(args['simp'+label], args['dir_'+label], args['P_in'+label+'_val'])
        coarse.compare_array(fine['thermal']['pressure'][side], interpolate(args['energy_dx'], args['energy_dy'],
            evidence['dx'], evidence['dy'], pressure), 'pressure')
        if values['model_fluids'] is not None:
            for key, target in zip(('mass_x', 'mass_y'), values['mass_flux_'+label]):
                coarse.compare_array(fine['thermal'][key][side], target)
        else:
            coarse.compare_array(fine['thermal']['inlet_capacity'][side], values['inlet_flux_'+label])
    coarse.compare_array(fine['thermal']['solid_conductivity'], np.broadcast_to(values['K_ss'], shape))
    if np.ndim(values['K_ss']) == 0:
        np.testing.assert_array_equal(np.asarray(fine['thermal']['solid_conductivity']).reshape(shape),
                                      np.broadcast_to(values['K_ss'], shape))
    if diagnostics['model_h_balance'] is not None:
        compare_audit(actual['thermal']['result']['audit'], diagnostics['model_h_balance']['main'])
        compare_audit(fine['thermal']['result']['audit'], diagnostics['model_h_balance']['fine'])
        expected_duty = [info['model_h_balance'][s]['Q_advective_W_per_m'] for s in ('A', 'B')]
    else:
        expected_duty = []
        for label, split in (('A', args['split_A']), ('B', 1-args['split_A'])):
            expected_duty.append(coupling._enthalpy_balance_2d(evidence['T'+label.lower()], evidence['uc'+label],
                evidence['vc'+label], evidence['rho_cp_'+label], args['dir_'+label], evidence['dx'], evidence['dy'],
                inlet_mask=evidence['inlet_'+label], outlet_mask=evidence['outlet_'+label],
                eps_side=evidence['eps']*split, T_in=args['T_in'+label]))
    power(fine['duty'], expected_duty if accepted else [np.nan, np.nan])
    expected_ext = ((4*np.abs(expected_duty)-np.abs(actual['duty']))/3 if info['extrapolated'] else np.abs(actual['duty']))
    power(fine['extrapolated_duty'], expected_ext)


def run_pair(native, cfg, *, case_id):
    reference = coarse.capture_python(prepare_case(cfg, case_id=case_id), full=True)
    request = coarse.inputs(reference) | {'full': True}
    before = [x.copy() for x in request['arrays']]
    code, error, actual = native(request)
    assert code == 0, error
    for value, saved in zip(request['arrays'], before): np.testing.assert_array_equal(value, saved)
    compare_complete(actual, reference)
    return actual, reference


@pytest.mark.parametrize('directions', [(0, 3), (1, 2), (2, 0), (3, 1)])
@pytest.mark.parametrize('mode', ['temperature', 'model_h'])
def test_full_refinement_directed_partial_cap_preserves_thermal_inputs(native, directions, mode):
    cfg = coarse.configuration(directions=directions, outer=2, mode=mode)
    actual, record = run_pair(native, cfg, case_id=f'full2d-refine-{mode}-{directions[0]}')
    assert actual['post_after_last_thermal'] and not actual['converged']
    args, values = record['refinement_inputs'], record['thermal_calls'][-1][0]
    dx, dy = args['energy_dx'], args['energy_dy']
    fx, fy = np.asarray(actual['refined']['dx']), np.asarray(actual['refined']['dy'])
    assert any(not np.array_equal(actual['rho_cp'][side], actual['thermal']['rho_cp'][side]) for side in range(2))
    for side, label in enumerate(('A', 'B')):
        saved = record['coarse_thermal_calls'][-1][0]['rho_cp_f'+label]
        np.testing.assert_array_equal(args['rho_cp_'+label], saved)
        coarse.compare_array(actual['refined']['thermal']['rho_cp'][side], interpolate(dx, dy, fx, fy,
            np.broadcast_to(saved, (len(dx), len(dy)))))
        for key in ('h_v'+label,):
            source = record['coarse_thermal_calls'][-1][0][key]
            coarse.compare_array(values[key], interpolate(dx, dy, fx, fy, np.broadcast_to(source, (len(dx), len(dy)))))
    if mode == 'model_h':
        assert not actual['refined']['accepted'] and not actual['refined']['extrapolated']
        assert not actual['model_balance_ok'] and actual['refined']['warning']
        # A failed physical model-h certificate keeps original coarse duties;
        # it cannot be replaced by a finite-temperature mean estimate.
        power(actual['q_total'], max(abs(q) for q in actual['duty']))
        assert np.isnan(actual['refined']['duty']).all()


@pytest.mark.parametrize('mode', ['temperature', 'model_h'])
def test_full_refinement_completed_outer_warm_start(native, mode):
    cfg = coarse.configuration(directions=(3, 1), outer=8, mode=mode, warm=True)
    actual, _ = run_pair(native, cfg, case_id='full2d-completed-'+mode)
    assert actual['outer_converged']
    assert not actual['post_after_last_thermal']


def test_existing_air_2d_golden_complete_pair(native):
    cfg = ComputeConfig.from_json(coarse.ROOT / 'examples/three_module/air_2d.json')
    actual, _ = run_pair(native, cfg, case_id='native-existing-air-2d-golden')
    assert actual['converged']
    assert actual['refined']['accepted'] and actual['refined']['extrapolated']


def test_true_h_final_keeps_recorded_advective_duty_without_richardson(native):
    cfg = coarse.configuration(directions=(0, 3), outer=2, mode='true_h')
    actual, record = run_pair(native, cfg, case_id='native-full2d-true-h-final')
    assert actual['refined'] is None and 'refinement_inputs' not in record
    power(actual['q_total'], abs(actual['duty'][0]))
    power(actual['q_solid'], abs(actual['duty'][1]))


def test_water_guard_uses_actual_low_pressure_after_simple(native):
    # 390 K is liquid at 200 kPa. The real completed B flow at 2 m/s drops
    # below its saturation pressure, before the first thermal iteration.
    cfg = coarse.configuration(outer=2, partial=False, mode='temperature')
    safe = coarse.capture_python(prepare_case(cfg, case_id='water-guard-controls'))
    cfg.fluid_B.T_in_K = 390.
    cfg.fluid_B.u_mps = 2.
    case = prepare_case(cfg, case_id='water-guard-actual-local-pressure')
    fluid_props.check_water_state('water', 390., 200000.)
    with pytest.raises(fluid_props.WaterStateError, match='2D SIMPLE return B.*P_abs='):
        coarse.capture_python(case, full=True)
    # Borrow only unchanged solver control settings from the safe run; every
    # physical prepared input is rebuilt from this failing case.
    parsed, prepared = execution.build_execution_inputs(case)
    parsed['p_in_shooting'] = True
    request = coarse.inputs(dict(safe, cfg=parsed, prepared=prepared)) | {'full': True}
    code, error, actual = native(request)
    assert code == 1 and actual is None, error
    assert '2D SIMPLE return' in error and 'water' in error and 'B' in error
