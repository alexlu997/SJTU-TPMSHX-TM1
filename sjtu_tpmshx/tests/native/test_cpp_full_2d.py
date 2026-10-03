"""Stable full-2D ABI ownership and packing against independent typed calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import gc
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver, _pack
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
from sjtu_tpmshx.tests.native import test_full_2d as typed
from sjtu_tpmshx.tests.native.test_full_2d_refinement import compare_audit

ROOT = Path(__file__).resolve().parents[3]
native = typed.native


@pytest.fixture(scope='module')
def driver():
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    suffix = '.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'
    path = ROOT/'.cache/native-deps/build'/('pilot-'+host)/(('' if os.name == 'nt' else 'lib')+'tpmshx_full_2d_shared'+suffix)
    if not path.is_file():
        message = f'full 2D public library not built: {path}'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    return NativeFull2DDriver(path, table_directory=ROOT/'.cache/native-deps/tables')


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
    for key in ('iterations', 'stop', 'mode', 'residual', 'q_b'):
        arrays_equal(public[key], reference['result'][key])
    if public['mode'] == 'model_h':
        compare_audit(reference['result']['audit'], public['model_h'])
    if public['mode'] == 'true_h':
        h = public['true_h']['_native_state']
        arrays_equal(h['h_A'], reference['h_a'])
        arrays_equal(h['h_B'], reference['h_b'])
        assert h['h_A'].shape == (*public['shape'], 1)
        for side in ('A', 'B'):
            assert len(h['mass_flux_'+side]) == 3
            assert h['mass_flux_'+side][2].shape == (*public['shape'], 2)
            assert not np.any(h['mass_flux_'+side][2])


@pytest.mark.parametrize('mode,directions', [('model_h', (0, 3)), ('model_h', (3, 1)),
                                           ('temperature', (1, 2)), ('true_h', (0, 3))])
def test_prepared_packing_and_public_abi_exact_typed_return(driver, native, mode, directions):
    case = prepare_case(typed.configuration(mode=mode, directions=directions, outer=2), case_id='full2d-public')
    record = typed.capture_python(case, full=True)
    request = typed.inputs(record)
    request['full'] = True
    status, error, reference = native(request)
    assert status == 0, error
    cfg, prepared = build_execution_inputs(case)
    shape, arrays, _ = _pack(cfg, prepared, driver.table_directory)
    assert shape == request['shape']
    for value, expected in zip(arrays, request['arrays']):
        np.testing.assert_array_equal(value, expected)
        value.setflags(write=False)
    result = driver.run_prepared(cfg, prepared)
    for name in ('iterations', 'converged', 'outer_converged', 'post_after_last_thermal', 'simple_ok',
                 'thermal_ok', 'envelope_ok', 'pair_balance_ok', 'model_balance_ok', 'pressure_drop',
                 'outlet_temperature', 'inlet_mass', 'duty', 'q_total', 'q_solid', 'energy_imbalance'):
        arrays_equal(result[name], reference[name])
    check_thermal(result['main'], reference['thermal'])
    for flow, expected in zip(result['flow'], reference['flow']):
        for name in ('dx', 'dy', 'u', 'v', 'pressure', 'pressure_correction', 'density', 'uc', 'vc',
                     'absolute_pressure', 'mass_x', 'mass_y', 'reference_pressure', 'taper_flux_scale'):
            arrays_equal(flow[name], expected[name])
        for name in ('iterations', 'converged', 'post_closure_certified', 'pressure_clip_hits'):
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
    return build_execution_inputs(prepare_case(cfg, case_id='full2d-zero-duty'))


def test_views_detached_inputs_readonly_and_repeated_calls(driver, prepared_zero_duty):
    cfg, prepared = prepared_zero_duty
    shape, arrays, config = _pack(cfg, prepared, driver.table_directory)
    originals = [x.copy() for x in arrays]
    for x in arrays:
        x.setflags(write=False)
    first = driver.solve(shape, arrays, config)
    for x, before in zip(arrays, originals):
        np.testing.assert_array_equal(x, before)
    del arrays
    gc.collect()
    second = driver.run_prepared(cfg, prepared)
    assert first['converged'] and second['converged']
    assert first['q_total'] == second['q_total']
    assert abs(first['q_total']) <= 2e-7  # frozen dimensional power tolerance
    first['main']['temperature'][0][0, 0] = -1.
    np.testing.assert_allclose(second['main']['temperature'][0], 300., rtol=2e-9, atol=2e-7)


@pytest.mark.parametrize('kind', ['cancel', 'outer', 'residual', 'progress', 'iteration'])
def test_callback_exception_and_recovery(driver, prepared_zero_duty, kind):
    class CallbackError(Exception):
        pass
    def broken(*args):
        raise CallbackError('callback-marker')
    field = dict(cancel='cancel_check', outer='outer_iteration', residual='residual',
                 progress='progress', iteration='iteration')[kind]
    with pytest.raises(CallbackError, match='callback-marker'):
        driver.run_prepared(*prepared_zero_duty, RunControl(**{field: broken}))
    assert driver.run_prepared(*prepared_zero_duty)['converged']


def test_interrupt_after_native_return_releases_owner(driver, prepared_zero_duty, monkeypatch):
    call, release, released = driver.call, driver.release, []
    def interrupted(*args):
        assert call(*args) == 0
        raise KeyboardInterrupt('native-return')
    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)
    monkeypatch.setattr(driver, 'call', interrupted)
    monkeypatch.setattr(driver, 'release', tracked)
    with pytest.raises(KeyboardInterrupt, match='native-return'):
        driver.run_prepared(*prepared_zero_duty)
    assert released == [None]


def test_iteration_and_progress_follow_native_outer_work(driver, prepared_zero_duty):
    progress, iterations, outer = [], [], []
    result = driver.run_prepared(*prepared_zero_duty, RunControl(progress=progress.append,
        iteration=iterations.append, outer_iteration=lambda done, total: outer.append((done, total))))
    assert len(outer) == result['iterations']
    assert progress == [10 + int(80 * done / total) for done, total in outer]
    assert iterations == [f'iter {done + 1}/{total}' for done, total in outer]


def test_cancel_during_native_call_and_recovery(driver, prepared_zero_duty):
    calls = []
    def cancel():
        calls.append(1)
        return len(calls) >= 5
    with pytest.raises(CancelledError):
        driver.run_prepared(*prepared_zero_duty, RunControl(cancel_check=cancel))
    assert len(calls) >= 5
    assert driver.run_prepared(*prepared_zero_duty)['converged']


def test_invalid_array_and_recovery(driver, prepared_zero_duty):
    shape, arrays, config = _pack(*prepared_zero_duty, driver.table_directory)
    arrays[3] = np.empty(1)
    with pytest.raises(ValueError):
        driver.solve(shape, arrays, config)
    assert driver.run_prepared(*prepared_zero_duty)['converged']


@pytest.mark.parametrize('name', ['in_geom_frac', 'out_geom_frac', 'in_profile_frac', 'out_profile_frac'])
def test_prepared_opening_mismatch_rejected_before_native_call(driver, prepared_zero_duty, monkeypatch, name):
    cfg, prepared = deepcopy(prepared_zero_duty)
    cfg['boundary_openings']['A'][name] = np.asarray(cfg['boundary_openings']['A'][name])*.9
    def unexpected(*args):
        pytest.fail('inconsistent prepared opening reached native call')
    monkeypatch.setattr(driver, 'call', unexpected)
    with pytest.raises(ValueError, match='disagrees with its grid and port geometry'):
        driver.run_prepared(cfg, prepared)


def test_independent_concurrent_results(driver, prepared_zero_duty):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: driver.run_prepared(*prepared_zero_duty), range(2)))
    assert all(r['converged'] and abs(r['q_total']) <= 2e-7 for r in results)
    assert results[0]['q_total'] == results[1]['q_total']
    np.testing.assert_array_equal(results[0]['main']['temperature'][0], results[1]['main']['temperature'][0])


@pytest.mark.parametrize('converged', [False, True])
def test_saved_full_case_replay_evaluation_and_storage_without_python_kernels(driver, tmp_path, converged):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.result_io import load_result
    config = (ComputeConfig.from_json(str(ROOT/'examples/three_module/air_2d.json'))
              if converged else typed.configuration(mode='true_h', outer=2))
    case = prepare_case(config, case_id='full2d-cpp-replay')
    case_path, result_path = tmp_path/'case.h5', tmp_path/'result.h5'
    save_case(case, case_path)
    code = '''
import sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.workflows.cli import main
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
        str(driver.path), str(ROOT/'.cache/native-deps/tables/full2d-replay'), str(converged)], cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout+process.stderr
    restored = load_result(result_path)
    assert restored.backend_id == 'cpp' and restored.run_status['converged'] == converged
    if not converged:
        assert len(restored.boundary_fluxes['true_h']['mass_flux_A']) == 3
