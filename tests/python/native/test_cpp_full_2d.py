"""Saved full-2D stage ownership and packing against independent typed calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gc
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface import full_2d_stage
from sjtu_tpmshx.solvers import full_2d
from sjtu_tpmshx.data_types.portable_data import mutable_data
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.preprocess.api import prepare_case
from tests.python.native import test_full_2d as typed
from tests.python.native.shared_library import library_path
from tests.python.native.stage_interception import run_stage, stage_control
from tests.python.native.test_full_2d_refinement import compare_audit

ROOT = Path(__file__).resolve().parents[3]
native = typed.native


def arrays_equal(a, b):
    np.testing.assert_array_equal(np.asarray(a).ravel(), np.asarray(b).ravel())


def check_thermal(public, reference):
    for name in ('temperature', 'hv', 'conductivity', 'pressure', 'rho_cp', 'mass_x', 'mass_y', 'inlet_capacity'):
        for actual, expected in zip(public[name], reference[name]):
            if actual is None:
                assert len(expected) == 0
            else:
                arrays_equal(actual, expected)
    arrays_equal(public['solid_conductivity'], reference['solid_conductivity'])
    expected_mode = 'conservative_energy' if reference['result']['mode'] == 'true_h' else reference['result']['mode']
    assert public['mode'] == expected_mode
    for key in ('iterations', 'stop', 'residual', 'q_b'):
        arrays_equal(public[key], reference['result'][key])
    if public['mode'] == 'model_h':
        compare_audit(reference['result']['audit'], public['model_h'])
    if public['mode'] in ('true_h', 'conservative_energy'):
        h = public['true_h']['_native_state']
        arrays_equal(h['h_A'], reference['h_a'])
        arrays_equal(h['h_B'], reference['h_b'])
        assert h['h_A'].shape == (*public['shape'], 1)
        for side in ('A', 'B'):
            assert len(h['mass_flux_'+side]) == 3
            assert h['mass_flux_'+side][2].shape == (*public['shape'], 2)
            assert not np.any(h['mass_flux_'+side][2])


def typed_reference(native, case, scalars=()):
    """Run the independent typed bridge on the inputs that the saved stage packs."""
    request = typed.inputs(typed.prepared_record(case))
    request['full'] = True
    for index, value in dict(scalars).items():
        request['scalars'][index] = value
    status, error, reference = native(request)
    assert status == 0, error
    return reference


@pytest.mark.parametrize('mode,directions', [('model_h', (0, 3)), ('model_h', (3, 1)),
                                           ('temperature', (1, 2)), ('true_h', (0, 3))])
def test_prepared_packing_and_public_abi_exact_typed_return(native, mode, directions):
    case = prepare_case(typed.configuration(mode=mode, directions=directions, outer=2), case_id='full2d-public')
    reference = typed_reference(native, case)
    stage = run_stage(case)
    result = stage.native
    assert result['entry_version'] == 6 and stage.result.backend_version == 'full_2d_v6'
    for name in ('iterations', 'converged', 'outer_converged', 'post_after_last_thermal', 'simple_ok',
                 'thermal_ok', 'envelope_ok', 'pair_balance_ok', 'model_balance_ok', 'pressure_drop',
                 'outlet_temperature', 'inlet_mass', 'duty', 'q_total', 'q_solid', 'energy_imbalance'):
        arrays_equal(result[name], reference[name])
    check_thermal(result['main'], reference['thermal'])
    for index, label in enumerate('AB'):
        arrays_equal(stage.result.fields['T' + label.lower()], reference['thermal']['temperature'][index])
    if mode == 'true_h':
        expected = dict(max_iterations=12000, sweeps=5, omega=.2, update_tol=.001,
            coupled_energy_tol=.001, equation_energy_tol=.001, energy_algorithm='temperature_sou',
            effective_settings_source='native_completed_thermal_call', driver_abi=6)
        records = [result['main']['true_h'], *(row['energy_info'] for row in result['outer_history'])]
        for record in records:
            assert {key: record['effective_settings'][key] for key in expected} == expected
    for side, flow, expected in zip('AB', result['flow'], reference['flow']):
        method = result['simple_flow'][side]
        assert method['algorithm'] == ('simple_2d_fixed_density_anderson_v1'
            if expected['result']['fixed_density_acceleration'] else 'simple_2d_v1')
        assert method['iterations'] == expected['result']['iterations']
        assert method['proposal_steps'] == expected['result']['acceleration_attempts']
        assert method['accepted_proposals'] == expected['result']['acceleration_accepted']
        # The saved stage publishes the final pressure and physical velocity views of each flow.
        for name in ('pressure', 'uc', 'vc', 'absolute_pressure', 'reference_pressure', 'taper_flux_scale'):
            arrays_equal(flow[name], expected[name])
        for name in ('iterations', 'converged'):
            assert flow['result'][name] == expected['result'][name]
    if result['fine'] is None:
        assert reference['refined'] is None
    else:
        check_thermal(result['fine'], reference['refined']['thermal'])
        for name in ('dx', 'dy', 'epsilon'):
            arrays_equal(result['fine'][name], reference['refined'][name])
        for name in ('inlet_profile', 'outlet_profile'):
            for value, expected in zip(result['fine'][name], reference['refined'][name]):
                arrays_equal(value, expected)
        for name in ('accepted', 'extrapolated', 'warning', 'duty'):
            arrays_equal(result['fine_'+name], reference['refined'][name])


@pytest.fixture(scope='module')
def prepared_zero_duty():
    cfg = typed.configuration(outer=2)
    cfg = replace(cfg, fluid_A=replace(cfg.fluid_A, type='water', T_in_K=300.),
                  solver=replace(cfg.solver, T_s_init_K=300.))
    return prepare_case(cfg, case_id='full2d-zero-duty')


def saved_arrays(case):
    arrays = [*case.grid.values(), *case.design_fields.values()]
    for side in 'AB':
        arrays += [*case.parameters['flow_inputs'][side].values(), *case.parameters['boundary_openings'][side].values()]
    return [np.array(value) for value in arrays if isinstance(value, np.ndarray)]


def test_views_detached_inputs_readonly_and_repeated_calls(prepared_zero_duty):
    case = prepared_zero_duty
    originals = saved_arrays(case)
    first = run_stage(case)
    for value, before in zip(saved_arrays(case), originals):
        np.testing.assert_array_equal(value, before)
    gc.collect()
    second = run_stage(case)
    assert first.native['converged'] and second.native['converged']
    assert first.native['q_total'] == second.native['q_total']
    assert abs(first.native['q_total']) <= 2e-7  # frozen dimensional power tolerance
    for name in ('Ta', 'Tb', 'Ts'):
        assert not np.shares_memory(first.result.fields[name], second.result.fields[name])
    first.native['main']['temperature'][0] = np.full_like(first.native['main']['temperature'][0], -1.)
    np.testing.assert_allclose(second.native['main']['temperature'][0], 300., rtol=2e-9, atol=2e-7)
    np.testing.assert_allclose(second.result.fields['Ta'], 300., rtol=2e-9, atol=2e-7)


@pytest.mark.parametrize('kind', ['cancel', 'outer', 'residual', 'progress', 'iteration'])
def test_callback_exception_and_recovery(prepared_zero_duty, kind):
    class CallbackError(Exception):
        pass
    def broken(*args):
        raise CallbackError('callback-marker')
    field = dict(cancel='cancel_check', outer='outer_iteration', residual='residual',
                 progress='progress', iteration='iteration')[kind]
    with pytest.raises(CallbackError, match='callback-marker'):
        run_stage(prepared_zero_duty, stage_control(**{field: broken}))
    assert run_stage(prepared_zero_duty).native['converged']


def tracked_entries(monkeypatch, *, complete=None):
    """Wrap the bound saved-run entries; record each released result owner."""
    original, released = full_2d_stage.stage_entries, []

    def entries(library):
        bound = original(library)
        release = bound['release']

        def tracked(pointer):
            assert pointer._obj.owner
            release(pointer)
            released.append(pointer._obj.owner)
        changed = dict(bound, release=tracked)
        if complete is not None:
            changed['complete'] = complete(bound['complete'])
        return changed

    monkeypatch.setattr(full_2d_stage, 'stage_entries', entries)
    return released


def test_interrupt_after_native_return_releases_owner(prepared_zero_duty, monkeypatch):
    def interrupted(complete):
        def call(*args):
            assert complete(*args) == 0
            raise KeyboardInterrupt('native-return')
        return call
    released = tracked_entries(monkeypatch, complete=interrupted)
    with pytest.raises(KeyboardInterrupt, match='native-return'):
        run_stage(prepared_zero_duty)
    assert released == [None]


def test_iteration_and_progress_follow_native_outer_work(prepared_zero_duty):
    progress, iterations, outer = [], [], []
    stage = run_stage(prepared_zero_duty, stage_control(progress=progress.append,
        iteration=iterations.append, outer_iteration=lambda done, total: outer.append((done, total))))
    assert len(outer) == stage.native['iterations']
    # run_case reports completion after the native outer work.
    assert progress == [*(10 + int(80 * done / total) for done, total in outer), 100]
    assert iterations == [f'iter {done + 1}/{total}' for done, total in outer]


def test_cancel_during_native_call_and_recovery(prepared_zero_duty):
    calls = []
    def cancel():
        calls.append(1)
        return len(calls) >= 5
    with pytest.raises(CancelledError):
        run_stage(prepared_zero_duty, stage_control(cancel_check=cancel))
    assert len(calls) >= 5
    assert run_stage(prepared_zero_duty).native['converged']


def test_invalid_array_and_recovery(prepared_zero_duty, monkeypatch):
    parameters = mutable_data(prepared_zero_duty.parameters)
    permeability = np.array(parameters['flow_inputs']['A']['K_m2'])
    permeability[0] = np.nan
    parameters['flow_inputs']['A']['K_m2'] = permeability
    released = tracked_entries(monkeypatch)
    progress = []
    # The saved native stage validates the borrowed array before any flow work.
    with pytest.raises(ValueError, match='invalid prepared flow A K_m2'):
        run_stage(replace(prepared_zero_duty, parameters=parameters), stage_control(progress=progress.append))
    assert not progress and not released
    assert run_stage(prepared_zero_duty).native['converged']


@pytest.mark.parametrize('name', ['in_geom_frac', 'out_geom_frac', 'in_profile_frac', 'out_profile_frac'])
def test_prepared_opening_mismatch_rejected_before_native_call(prepared_zero_duty, name):
    parameters = mutable_data(prepared_zero_duty.parameters)
    parameters['boundary_openings']['A'][name] = np.asarray(parameters['boundary_openings']['A'][name])*.9
    progress = []
    with pytest.raises(ValueError, match='disagrees with its grid and port geometry'):
        run_stage(replace(prepared_zero_duty, parameters=parameters), stage_control(progress=progress.append))
    assert not progress


def test_independent_concurrent_results(prepared_zero_duty):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: full_2d.run_case(prepared_zero_duty, stage_control()), range(2)))
    q_total = [result.metadata['diagnostics']['Q_total'] for result in results]
    assert all(result.run_status['converged'] for result in results)
    assert all(abs(value) <= 2e-7 for value in q_total) and q_total[0] == q_total[1]
    np.testing.assert_array_equal(results[0].fields['Ta'], results[1].fields['Ta'])


@pytest.mark.parametrize('converged', [False, True])
def test_saved_full_case_replay_evaluation_and_storage_without_python_kernels(tmp_path, converged):
    from sjtu_tpmshx.data_types.compute_config import ComputeConfig
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.result_io import load_result
    config = (ComputeConfig.from_json(str(ROOT/'examples/three_module/air_2d.json'))
              if converged else typed.configuration(mode='true_h', outer=2))
    case = prepare_case(config, case_id='full2d-cpp-replay')
    case_path, result_path = tmp_path/'case.h5', tmp_path/'result.h5'
    save_case(case, case_path)
    code = '''
import sys
from sjtu_tpmshx.file_io.result_io import load_result
from sjtu_tpmshx.file_io.metrics_io import load_metrics
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.applications.cli.stages import main
converged = sys.argv[5] == 'True'
exit_code = main(['solve', sys.argv[1], sys.argv[2], '--backend', 'cpp',
    '--native-library', sys.argv[3], '--native-table-directory', sys.argv[4]])
assert exit_code == (0 if converged else 2)
result = load_result(sys.argv[2])
assert result.run_status['execution'] == 'completed' and result.run_status['converged'] == converged
assert evaluate(result).metrics['Q'].status == 'available'
assert main(['postprocess', sys.argv[2], sys.argv[2]+'.json']) == 0
assert load_metrics(sys.argv[2]+'.json').metrics == evaluate(result).metrics
assert sys.argv[3] not in str(result.metadata) and sys.argv[4] not in str(result.metadata)
forbidden = ('numba', 'sjtu_tpmshx.solvers.ltne_', 'sjtu_tpmshx.solvers.simple_',
    'sjtu_tpmshx.solvers._kernels', 'sjtu_tpmshx.solvers.backends.python.two_d.runtime',
    'sjtu_tpmshx.solvers.backends.python.two_d.coupling')
assert not [name for name in sys.modules if name.startswith(forbidden)]
'''
    process = subprocess.run([sys.executable, '-c', code, str(case_path), str(result_path),
        str(library_path()), str(ROOT/'.cache/native-deps/tables/full2d-replay'), str(converged)], cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout+process.stderr
    restored = load_result(result_path)
    assert restored.backend_id == 'cpp' and restored.run_status['converged'] == converged
    if not converged:
        assert len(restored.boundary_fluxes['true_h']['mass_flux_A']) == 3


def test_model_h_budget_reaches_main_refined_and_saved_result(tmp_path):
    from sjtu_tpmshx.file_io.case_io import load_case, save_case
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    cfg = typed.configuration(outer=2)
    cfg = replace(cfg, fluid_A=replace(cfg.fluid_A, type='water', T_in_K=300.),
                  solver=replace(cfg.solver, T_s_init_K=300., model_h_max_iterations=17,
                                 model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8))
    prepared = prepare_case(cfg, case_id='model-h-controls-2d')
    save_case(prepared, tmp_path/'case.h5')
    prepared = load_case(tmp_path/'case.h5')
    stage = run_stage(prepared)
    raw, result = stage.native, stage.result
    assert raw['main']['iterations'] == raw['fine']['iterations'] == 17
    assert not raw['thermal_ok'] and not raw['converged']
    records = raw['model_h_iterations']['records']
    assert len(records) == len(raw['outer_history']) + 1
    assert records[-1]['stage'] == 'refined_thermal'
    expected = dict(max_iterations=17, chunk_iterations=500,
                    temperature_update_tolerance_K=1e-5, q_relative_tolerance=1e-8, total_iteration_budget=17)
    assert all(row['settings'] == expected for row in records)
    assert result.metadata['execution_record']['numerics']['effective_settings'] == expected
    save_result(result, tmp_path/'result.h5')
    restored = load_result(tmp_path/'result.h5')
    assert restored.metadata['model_h_iterations'] == result.metadata['model_h_iterations']
    assert restored.metadata['execution_record'] == result.metadata['execution_record']


@pytest.mark.parametrize('mode', ['model_h', 'temperature'])
def test_model_h_unset_budget_preserves_main_and_refined_defaults(mode):
    cfg = typed.configuration(mode=mode, outer=2)
    cfg = replace(cfg, solver=replace(cfg.solver, model_h_temperature_tol_K=1e-5))
    raw = run_stage(prepare_case(cfg, case_id='model-h-defaults-2d')).native
    records = raw['model_h_iterations']['records']
    assert records and records[-1]['stage'] == 'refined_thermal'
    # Both routes have Fluid B water, so the outer 2D thermal budget is 12000.
    assert all(row['settings']['max_iterations'] == 12000
               for row in records if row['stage'] == 'outer_thermal')
    assert records[-1]['settings']['max_iterations'] == (12000 if mode == 'model_h' else 5000)
    assert records[-1]['settings']['q_relative_tolerance'] == .001
    assert all(row['settings']['temperature_update_tolerance_K'] == 1e-5 for row in records)


@pytest.mark.parametrize('relaxation', [None, .35])
def test_persisted_velocity_relaxation_matches_direct_native_control(native, prepared_zero_duty, relaxation):
    cfg = typed.configuration(outer=2)
    cfg = replace(cfg, fluid_A=replace(cfg.fluid_A, type='water', T_in_K=300.),
                  solver=replace(cfg.solver, T_s_init_K=300., simple_velocity_relaxation=relaxation))
    case = prepare_case(cfg, case_id='full2d-zero-duty')
    # Scalar 33 is the typed bridge SIMPLE velocity relaxation.
    expected = typed_reference(native, prepared_zero_duty, {33: .7 if relaxation is None else relaxation})
    actual = run_stage(case).native
    assert actual['simple_velocity_relaxation'] == (.7 if relaxation is None else relaxation)
    for flow, reference in zip(actual['flow'], expected['flow']):
        for name in ('iterations', 'converged'):
            assert flow['result'][name] == reference['result'][name]
        arrays_equal(flow['pressure'], reference['pressure'])
    for first, second in zip(actual['main']['temperature'], expected['thermal']['temperature']):
        arrays_equal(first, second)


@pytest.mark.parametrize('relaxation', [None, .35])
def test_full2d_velocity_relaxation_record_survives_storage(tmp_path, relaxation):
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    from sjtu_tpmshx.solvers.api import run_case
    cfg = typed.configuration(mode='model_h', outer=2)
    cfg = replace(cfg, solver=replace(cfg.solver, simple_velocity_relaxation=relaxation))
    prepared = prepare_case(cfg, case_id='full2d-velocity-control')
    actual = run_case(prepared, stage_control())
    expected = .7 if relaxation is None else relaxation
    assert actual.metadata['simple_velocity_relaxation'] == expected
    assert actual.metadata['execution_record']['numerics']['simple_velocity_relaxation'] == expected
    path = tmp_path / 'result.h5'
    save_result(actual, path)
    assert load_result(path).metadata['execution_record'] == actual.metadata['execution_record']
