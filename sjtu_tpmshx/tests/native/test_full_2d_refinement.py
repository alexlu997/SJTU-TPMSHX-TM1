"""Complete 2D physical audits and conservative Richardson transfer checks."""
import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.models.grid import split_cells
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.tests.native import test_full_2d as coarse
from sjtu_tpmshx.tests.native.test_refinement_2d import interpolate, _prolong_mass_faces_2d

native = coarse.native


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


def check_complete(actual, record):
    coarse.audit_coarse(actual, record, full=True)
    assert actual['converged'] == all(actual[key] for key in (
        'outer_converged', 'simple_ok', 'thermal_ok', 'envelope_ok', 'pair_balance_ok', 'model_balance_ok'))
    fine = actual['refined']
    if fine is None:
        assert actual['thermal']['result']['mode'] == 'true_h'
        return
    dx, dy = (record['prepared']['energy_'+axis] for axis in ('dx','dy'))
    fx, fy = np.asarray(fine['dx']), np.asarray(fine['dy'])
    np.testing.assert_array_equal(fx, split_cells(dx))
    np.testing.assert_array_equal(fy, split_cells(dy))
    for key in ('hv','rho_cp','conductivity','pressure'):
        for source, value in zip(actual['thermal'][key], fine['thermal'][key]):
            coarse.compare_array(value, interpolate(dx,dy,fx,fy,np.asarray(source).reshape(len(dx),len(dy))))
    coarse.compare_array(fine['thermal']['solid_conductivity'], interpolate(dx,dy,fx,fy,
        np.asarray(actual['thermal']['solid_conductivity']).reshape(len(dx),len(dy))))
    for side in range(2):
        mass = (np.asarray(actual['thermal']['mass_x'][side]).reshape(len(dx)+1,len(dy)),
                np.asarray(actual['thermal']['mass_y'][side]).reshape(len(dx),len(dy)+1))
        expected = _prolong_mass_faces_2d(mass, dx,dy,fx,fy)
        for key, value in zip(('mass_x','mass_y'),expected):
            coarse.compare_array(fine['thermal'][key][side],value)
    coarse.audit_thermal(fine['thermal'], record,fx,fy,
                         full=True,outer=actual['outer_converged'])
    accepted = fine['thermal']['result']['stop'] == 0
    if actual['thermal']['result']['mode'] == 'model_h':
        accepted &= actual['thermal']['result']['audit']['passed'] and fine['thermal']['result']['audit']['passed']
    assert fine['accepted'] == accepted
    if not accepted:
        assert not fine['extrapolated']
        assert np.isnan(fine['duty']).all()
    expected = ((4*np.abs(fine['duty'])-np.abs(actual['duty']))/3
                if fine['extrapolated'] else np.abs(actual['duty']))
    power(fine['extrapolated_duty'], expected)


def run_pair(native, cfg, *, case_id):
    record = coarse.prepared_record(prepare_case(cfg, case_id=case_id))
    request = coarse.inputs(record) | {'full': True}
    before = [x.copy() for x in request['arrays']]
    code, error, actual = native(request)
    assert code == 0, error
    for value, saved in zip(request['arrays'], before):
        np.testing.assert_array_equal(value, saved)
    check_complete(actual, record)
    return actual, record


@pytest.mark.parametrize('directions', [(0, 3), (1, 2), (2, 0), (3, 1)])
@pytest.mark.parametrize('mode', ['temperature', 'model_h'])
def test_full_refinement_directed_partial_cap_preserves_thermal_inputs(native, directions, mode):
    cfg = coarse.configuration(directions=directions, outer=2, mode=mode)
    actual, record = run_pair(native, cfg, case_id=f'full2d-refine-{mode}-{directions[0]}')
    assert actual['post_after_last_thermal'] and not actual['converged']
    assert any(not np.array_equal(actual['rho_cp'][side], actual['thermal']['rho_cp'][side]) for side in range(2))
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
    assert actual['refined'] is None
    power(actual['q_total'], abs(actual['duty'][0]))
    power(actual['q_solid'], abs(actual['duty'][1]))


def test_water_guard_uses_actual_low_pressure_after_simple(native):
    # 390 K is liquid at 200 kPa. The real completed B flow at 2 m/s drops
    # below its saturation pressure, before the first thermal iteration.
    cfg = coarse.configuration(outer=2, partial=False, mode='temperature')
    cfg.fluid_B.T_in_K = 390.
    cfg.fluid_B.u_mps = 2.
    case = prepare_case(cfg, case_id='water-guard-actual-local-pressure')
    fluid_props.check_water_state('water', 390., 200000.)
    request = coarse.inputs(coarse.prepared_record(case)) | {'full': True}
    code, error, actual = native(request)
    assert code == 1 and actual is None, error
    assert '2D SIMPLE return' in error and 'water' in error and 'B' in error
