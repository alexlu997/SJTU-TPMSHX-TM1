"""Complete conservative energy coupling and the portable 2D face ledger.

These are same-state evidence checks, not parity against a different algorithm.
Frozen gates: model/EOS h rtol=2e-12/atol=2e-7 J/kg; K rtol=2e-12/atol=2e-12;
native/portable signed Q rtol=2e-10/atol=2e-7 W/m. Native acceptance is unchanged.
"""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.case_io import save_case, load_case
from sjtu_tpmshx.io.result_io import save_result, load_result
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import capture_result
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
from sjtu_tpmshx.tests.native.shared_library import library_path

ROOT = Path(__file__).resolve().parents[3]
VERSIONS = {'temperature_fou': 1, 'temperature_sou': 2}


@pytest.fixture(scope='module')
def driver():
    return NativeFull2DDriver(library_path(), table_directory=ROOT / '.cache/native-deps/tables')


def configuration(algorithm, *, outer=2, partial=True, directions=(0, 3)):
    lengths = (.06, .03)
    def port(direction, clipped):
        width = lengths[1 if direction < 2 else 0]
        center, opening = (width * .476, width * .457) if clipped else (width / 2, width)
        return PartialBCConfig(dir=direction, in_ctr=center, in_w=opening,
                               out_ctr=center, out_w=opening)
    return ComputeConfig(
        fluid_A=FluidConfig(type='water', u_mps=.05, T_in_K=350., P_in_Pa=8e6),
        fluid_B=FluidConfig(type='sco2', u_mps=.015, T_in_K=320., P_in_Pa=8e6),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6, k_s_W_mK=16.,
                                L_dom_m=.06, H_dom_m=.03),
        solver=SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=outer, max_iter_simple=3000,
                            enthalpy_algorithm=algorithm, enthalpy_temperature_tol_K=1e-8),
        bc_A=port(directions[0], partial), bc_B=port(directions[1], False),
        extrap=ExtrapPolicy(allow=True))


@pytest.fixture(scope='module', params=[
    (algorithm, directions, partial)
    for algorithm in ('temperature_fou', 'temperature_sou')
    for directions in ((0, 3), (1, 2)) for partial in (False, True)],
    ids=lambda value: f'{value[0]}-directions{value[1][0]}{value[1][1]}-partial{value[2]}')
def capped(driver, request):
    algorithm, directions, partial = request.param
    case = prepare_case(configuration(algorithm, directions=directions, partial=partial),
                        case_id=f'energy2d-{algorithm}-{directions}-{partial}')
    cfg, prepared = build_execution_inputs(case)
    raw = driver.run_prepared(cfg, prepared)
    return case, cfg, prepared, raw, capture_result(case, cfg, prepared, raw)


def test_actual_thermal_state_and_signed_ledger(capped):
    import CoolProp.CoolProp as CP
    from sjtu_tpmshx.tests.native.full_thermal_reference import model_enthalpy
    case, cfg, _, raw, result = capped
    info, thermal = raw['main']['true_h'], raw['main']
    assert raw['entry_version'] == 6 and raw['fine'] is None
    assert result.backend_version == 'full_2d_v6'
    assert not raw['converged'] and raw['post_after_last_thermal']
    assert result.metadata['thermal_mode'] == 'conservative_energy'
    assert info['energy_algorithm'] == info['effective_settings']['energy_algorithm'] == \
        cfg['compute_cfg'].solver.enthalpy_algorithm
    assert type(info['energy_algorithm_version']) is int
    assert info['energy_algorithm_version'] == info['effective_settings']['energy_algorithm_version'] == \
        VERSIONS[info['energy_algorithm']]
    assert info['effective_settings']['picard_relaxation'] == \
        (.6 if info['energy_algorithm'] == 'temperature_sou' else 1.)
    assert info['temperature_update_K'] <= 1e-8
    assert info['converged'] and raw['thermal_ok']
    assert info['coupled_energy_balance']['ratio'] <= .001
    assert info['equation_energy_balance']['ratio'] <= .001
    assert raw['outer_history'][0]['energy_info']['energy_algorithm'] == info['energy_algorithm']
    for row in raw['outer_history']:
        history = row['energy_info']
        settings = history['effective_settings']
        assert settings['effective_settings_source'] == 'native_completed_thermal_call'
        assert settings['max_iterations'] == 12000 and settings['sweeps'] == 5
        assert settings['update_tol'] == .001
        assert settings['omega'] == (.2 if info['energy_algorithm'] == 'temperature_sou' else .6)
        assert history['energy_algorithm'] == history['effective_settings']['energy_algorithm'] == info['energy_algorithm']
        assert type(history['energy_algorithm_version']) is int
        assert history['energy_algorithm_version'] == history['effective_settings']['energy_algorithm_version'] == \
            VERSIONS[info['energy_algorithm']]
    assert all(row['energy_info']['effective_settings']['picard_relaxation'] ==
               info['effective_settings']['picard_relaxation'] for row in raw['outer_history'])
    state = result.boundary_fluxes['true_h']
    assert state['energy_algorithm'] == info['energy_algorithm']
    assert type(state['energy_algorithm_version']) is int
    assert state['energy_algorithm_version'] == VERSIONS[info['energy_algorithm']]
    assert state['boundary_power_units'] == 'W/m' and state['physical_boundary_complete']
    performance = evaluate(result)
    assert performance.qualification['physical']['passed'] is True
    assert performance.qualification['convergence']['pressure_states'] == {
        side: result.field_metadata['P_report_' + side]['state'] for side in ('A', 'B')}
    metrics = performance.metrics
    for side, label, fluid in ((0, 'A', 'Water'), (1, 'B', 'CO2')):
        temperature = thermal['temperature'][side]
        pressure = thermal['pressure'][side]
        if fluid == 'Water':
            h = model_enthalpy(temperature.ravel(), 'water')
            k = thermal['conductivity'][side].ravel()
            np.testing.assert_allclose(state['h_in_' + label], model_enthalpy(cfg['T_in' + label], 'water'), rtol=2e-12, atol=2e-7)
        else:
            h = CP.PropsSI('Hmass', 'T', temperature.ravel(), 'P', pressure.ravel(), 'HEOS::' + fluid)
            k = CP.PropsSI('conductivity', 'T', temperature.ravel(), 'P', pressure.ravel(), 'HEOS::' + fluid)
            split = cfg['thermal_geometry']['split_A'] if side == 0 else 1 - cfg['thermal_geometry']['split_A']
            k *= cfg['eps'] * split
        np.testing.assert_allclose(state['h_' + label].ravel(), h, rtol=2e-12, atol=2e-7)
        np.testing.assert_allclose(state['actual_conductivity_' + label].ravel(), k, rtol=2e-12, atol=2e-12)
        powers = state['boundary_power'][label]
        assert not np.any(powers['z-']) and not np.any(powers['z+'])
        signed = -sum(np.sum(powers[face]) for face in ('x-', 'x+', 'y-', 'y+', 'z-', 'z+'))
        np.testing.assert_allclose(signed, info['Q_' + label], rtol=2e-10, atol=2e-7)
        assert metrics['Q_' + label].status == 'available'
        np.testing.assert_allclose(metrics['Q_' + label].value, signed, rtol=2e-10, atol=2e-7)
        np.testing.assert_allclose(metrics['T_out_' + label].value, raw['outlet_temperature'][side],
                                   rtol=2e-12, atol=2e-9)
        np.testing.assert_allclose(metrics['mass_flow_' + label].value, raw['inlet_mass'][side],
                                   rtol=2e-12, atol=2e-12)
        for axis in (0, 1):
            np.testing.assert_array_equal(result.boundary_fluxes['mass_' + label][axis],
                                          state['mass_flux_' + label][axis][..., 0])
    assert metrics['Q_richardson_A'].status == metrics['Q_richardson_B'].status == 'unsupported'


@pytest.mark.parametrize('algorithm', ['temperature_fou', 'temperature_sou'])
@pytest.mark.parametrize('partial', [False, True])
def test_complete_original_native_acceptance(driver, algorithm, partial):
    case = prepare_case(configuration(algorithm, outer=32, partial=partial), case_id='energy2d-complete')
    raw = driver.run_prepared(*build_execution_inputs(case))
    assert raw['converged'], {key: raw[key] for key in ('iterations', 'outer_converged', 'simple_ok',
        'thermal_ok', 'envelope_ok', 'pair_balance_ok', 'model_balance_ok')}
    assert not raw['post_after_last_thermal']
    assert all(row['energy_info']['energy_algorithm'] == algorithm for row in raw['outer_history'])
    assert all(row['energy_info']['energy_algorithm_version'] == VERSIONS[algorithm]
               for row in raw['outer_history'])


def test_saved_case_result_new_process_replay(driver, capped, tmp_path):
    case, cfg, _, raw, result = capped
    case_path, result_path = tmp_path / 'case.h5', tmp_path / 'result.h5'
    save_case(case, case_path)
    save_result(result, result_path)
    audit = evaluate_physical_balance(result)['energy']
    assert audit['status'] == 'available' and audit['units'] == 'W/m'
    assert abs(audit['telescoping_error']) < 2e-7
    assert evaluate_physical_balance(load_result(result_path))['energy'] == audit
    assert load_case(case_path).parameters['run_settings']['solver']['enthalpy_algorithm'] == \
        cfg['compute_cfg'].solver.enthalpy_algorithm
    assert evaluate(load_result(result_path)).metrics == evaluate(result).metrics
    code = '''
import sys
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
from sjtu_tpmshx.workflows.cli import main
old = load_result(sys.argv[2])
assert main(['solve',sys.argv[1],sys.argv[3],'--backend','cpp','--native-library',sys.argv[4],
             '--native-table-directory',sys.argv[5]]) == 2
new = load_result(sys.argv[3])
assert new.metadata['thermal_mode'] == 'conservative_energy'
before, after = old.boundary_fluxes['true_h'], new.boundary_fluxes['true_h']
assert after['energy_algorithm'] == before['energy_algorithm']
assert after['energy_algorithm_version'] == before['energy_algorithm_version'] == \
    {'temperature_fou': 1, 'temperature_sou': 2}[after['energy_algorithm']]
assert evaluate(new).metrics == evaluate(old).metrics
assert not any(name.startswith(('numba','sjtu_tpmshx.solvers.ltne_',
    'sjtu_tpmshx.solvers.simple_', 'sjtu_tpmshx.solvers.backends.python.two_d.runtime',
    'sjtu_tpmshx.solvers.backends.python.two_d.coupling')) for name in sys.modules)
'''
    # The same SOU solve took 134 s in-process on Windows qualification runners.
    completed = subprocess.run([sys.executable, '-c', code, str(case_path), str(result_path),
        str(tmp_path / 'replayed.h5'), str(driver.path), str(ROOT / '.cache/native-deps/tables')],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr



@pytest.mark.parametrize('algorithm', ['temperature_fou', 'temperature_sou'])
def test_zero_sweep_budget_retains_initial_fields(driver, algorithm):
    config = configuration(algorithm)
    config = replace(config, solver=replace(config.solver, ltne_enthalpy_nsweep=0, ltne_enthalpy_outer=1))
    case = prepare_case(config, case_id='energy2d-zero-sweep')
    cfg, prepared = build_execution_inputs(case)
    actual = driver.run_prepared(cfg, prepared)
    info = actual['main']['true_h']
    assert not actual['converged'] and not actual['thermal_ok']
    assert info['energy_algorithm'] == algorithm and info['exit_reason'] == 'iteration_limit'
    assert info['iterations'] == info['effective_settings']['max_iterations'] == 1
    assert info['effective_settings']['sweeps'] == 0 and info['temperature_update_K'] == 0.
    assert info['equation_energy_balance']['ratio'] > info['effective_settings']['equation_energy_tol']
    for field, value in zip(actual['main']['temperature'], (cfg['T_inA'], cfg['T_inB'],
                                                          .5*(cfg['T_inA']+cfg['T_inB']))):
        np.testing.assert_array_equal(field, np.full(field.shape, value))


@pytest.mark.parametrize('algorithm', ['temperature_fou', 'temperature_sou'])
@pytest.mark.parametrize('partial', [False, True])
def test_true_h_red_black_control_preserves_actual_state(driver, monkeypatch, algorithm, partial):
    from sjtu_tpmshx.solvers.backends.cpp import full_2d
    case = prepare_case(configuration(algorithm, partial=partial), case_id='energy2d-red-black')
    cfg, prepared = build_execution_inputs(case)
    expected = driver.run_prepared(cfg, prepared)
    pack = full_2d._pack

    def with_red_black(*args):
        shape, arrays, control = pack(*args)
        control.red_black = 1
        return shape, arrays, control

    monkeypatch.setattr(full_2d, '_pack', with_red_black)
    actual = driver.run_prepared(cfg, prepared)
    for key in ('converged', 'iterations', 'outer_history', 'duty', 'pressure_drop',
                'outlet_temperature', 'inlet_mass'):
        assert actual[key] == expected[key]
    np.testing.assert_equal(actual['main'], expected['main'])
    result = capture_result(case, cfg, prepared, actual)
    test_actual_thermal_state_and_signed_ledger((case, cfg, prepared, actual, result))


def test_candidate_requires_supported_route_and_backend(driver):
    config = configuration('temperature_sou')
    case = prepare_case(config, case_id='energy2d-backend')
    with pytest.raises(ValueError, match='Python numerical backend has been retired'):
        run_case(case, RunControl(backend='python'))
    other = replace(config, fluid_B=replace(config.fluid_B, type='water'))
    with pytest.raises(ValueError, match='requires the existing true-h route'):
        driver.run_prepared(*build_execution_inputs(prepare_case(other, case_id='energy2d-route')))


@pytest.mark.parametrize('missing', ['tpmshx_solve_full_2d_v3', 'tpmshx_full_2d_get_energy_evidence_v1'])
def test_old_library_candidate_capability_fails_before_flow(driver, monkeypatch, missing):
    original = driver.library
    class OldAPI:
        def __getattr__(self, name):
            if name in (missing, 'tpmshx_solve_full_2d_v6'):
                raise AttributeError(name)
            return getattr(original, name)
    case = prepare_case(configuration('temperature_fou'), case_id='energy2d-old-library')
    monkeypatch.setattr(driver, 'library', OldAPI())
    with pytest.raises(ValueError, match='lacks conservative energy v3'):
        driver.run_prepared(*build_execution_inputs(case))


@pytest.mark.parametrize('algorithm', ['legacy_h_fou', *VERSIONS])
def test_missing_version_query_blocks_candidate_before_solve_but_allows_legacy(driver, monkeypatch, algorithm):
    from sjtu_tpmshx.solvers.backends.cpp import full_2d
    original, entered = driver.library, []

    class LegacyEntered(Exception):
        pass

    def legacy(*args):
        entered.append('legacy')
        raise LegacyEntered

    def forbidden_candidate(*args):
        pytest.fail('native candidate solve ran before its version capability check')

    class OldLibrary:
        def __getattr__(self, name):
            if name in ('tpmshx_solve_full_2d_v6', 'tpmshx_energy_algorithm_version_v1'):
                raise AttributeError(name)
            if name == 'tpmshx_solve_full_2d_v2':
                return legacy
            if name == 'tpmshx_solve_full_2d_v3':
                return forbidden_candidate
            return getattr(original, name)

    case = prepare_case(configuration(algorithm), case_id='energy2d-missing-version')
    monkeypatch.setattr(full_2d.ct, 'CDLL', lambda _: OldLibrary())
    old = NativeFull2DDriver(driver.path)
    if algorithm == 'legacy_h_fou':
        with pytest.raises(LegacyEntered):
            old.run_prepared(*build_execution_inputs(case))
        assert entered == ['legacy']
    else:
        with pytest.raises(ValueError, match='lacks conservative energy algorithm version query'):
            old.run_prepared(*build_execution_inputs(case))
        assert not entered


@pytest.mark.parametrize('executed,version', [(1, 1), (2, 1), (2, 2)])
def test_energy_decoder_queries_executed_algorithm(executed, version):
    from sjtu_tpmshx.solvers.backends.cpp.enthalpy import _EnergyResult, _energy_options, _energy_result_info

    requested = _energy_options('temperature_sou' if executed == 1 else 'temperature_fou', 1e-8)
    assert requested.algorithm != executed
    info = dict(energy_algorithm='requested-placeholder', energy_algorithm_version=99,
                effective_settings=dict(omega=.2, energy_algorithm='requested-placeholder', energy_algorithm_version=99))
    queried = []

    def query(algorithm):
        queried.append(algorithm)
        return version

    actual = _EnergyResult(executed, 1, 1e-9, 1. if executed == 1 else .6)
    _energy_result_info(info, actual, temperature_tol=requested.temperature_update_tolerance,
                        abi=3, version_query=query)
    name = 'temperature_fou' if executed == 1 else 'temperature_sou'
    assert queried == [executed]
    assert info['energy_algorithm'] == info['effective_settings']['energy_algorithm'] == name
    assert type(info['energy_algorithm_version']) is int
    assert info['energy_algorithm_version'] == info['effective_settings']['energy_algorithm_version'] == version


@pytest.mark.parametrize('executed,version', [(1, 2), (2, 0), (2, 3), (2, True), (2, 1.)])
def test_energy_decoder_rejects_unsupported_native_version(executed, version):
    from sjtu_tpmshx.solvers.backends.cpp.enthalpy import _EnergyResult, _energy_result_info

    info = dict(effective_settings=dict(omega=.2))
    actual = _EnergyResult(executed, 1, 1e-9, 1. if executed == 1 else .6)
    with pytest.raises(RuntimeError, match='version'):
        _energy_result_info(info, actual, temperature_tol=1e-8, abi=3,
                            version_query=lambda algorithm: version)


@pytest.mark.parametrize('kind', ['cancel', 'callback', 'decode'])
def test_candidate_exception_releases_and_recovers(driver, monkeypatch, kind):
    import sjtu_tpmshx.solvers.backends.cpp.full_2d as binding
    cfg, prepared = build_execution_inputs(prepare_case(configuration('temperature_sou'), case_id='energy2d-owner'))
    original, released = driver.release, []
    def release(pointer):
        assert pointer._obj.owner
        original(pointer)
        released.append(pointer._obj.owner)
    calls = []
    def cancel():
        calls.append(1)
        return len(calls) >= 5
    def broken(*args, **kwargs):
        raise RuntimeError('candidate-owner-marker')
    with monkeypatch.context() as patcher:
        patcher.setattr(driver, 'release', release)
        control = RunControl()
        if kind == 'decode':
            patcher.setattr(binding, '_energy_native_state', broken)
        elif kind == 'callback':
            control = RunControl(outer_iteration=broken)
        else:
            control = RunControl(cancel_check=cancel)
        with pytest.raises(CancelledError if kind == 'cancel' else RuntimeError):
            driver.run_prepared(cfg, prepared, control)
    assert released == [None]
    assert driver.run_prepared(cfg, prepared)['main']['true_h']['converged']


@pytest.mark.parametrize('algorithm,tolerance', [('unknown', 1e-8), ('temperature_fou', 0.),
    ('temperature_sou', float('nan')), ('temperature_sou', True)])
def test_invalid_persisted_options_rejected(algorithm, tolerance):
    cfg = configuration(algorithm)
    cfg = replace(cfg, solver=replace(cfg.solver, enthalpy_temperature_tol_K=tolerance))
    with pytest.raises(ValueError, match='enthalpy_'):
        prepare_case(cfg, case_id='invalid-energy-options')


@pytest.mark.parametrize('algorithm', ['legacy_h_fou', 'temperature_fou', 'temperature_sou'])
def test_explicit_controls_reach_complete_thermal_calls_and_saved_replay(driver, tmp_path, algorithm):
    config = configuration(algorithm)
    config.solver = replace(config.solver, ltne_enthalpy_outer=12000,
        ltne_enthalpy_nsweep=5, ltne_enthalpy_omega=.2 if algorithm == 'temperature_sou' else .6,
        ltne_enthalpy_tol=1e-8, ltne_enthalpy_coupled_energy_tol=1e-7,
        ltne_enthalpy_equation_energy_tol=1e-7, require_enthalpy_update_on_temperature=True)
    case = prepare_case(config, case_id='explicit-energy2d-' + algorithm)
    save_case(case, tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    result = run_case(restored, RunControl(backend='cpp', native_library=str(driver.path),
                                         native_table_directory=str(ROOT / '.cache/native-deps/tables')))
    assert result.backend_version == 'full_2d_v6'
    detail = result.metadata['diagnostics']['convergence_detail']
    assert detail['ltne_ok'] and not detail['outer_converged']
    info = result.metadata['diagnostics']['true_h_balance']
    assert info['converged']
    assert info['coupled_energy_balance']['ratio'] <= 1e-7
    assert info['equation_energy_balance']['ratio'] <= 1e-7
    expected = dict(max_iterations=12000, sweeps=5,
        omega=config.solver.ltne_enthalpy_omega, update_tol=1e-8,
        coupled_energy_tol=1e-7, equation_energy_tol=1e-7,
        require_enthalpy_update_on_temperature=True)
    for actual in (info['effective_settings'], *(row['effective_settings'] for row in
            result.metadata['diagnostics']['native_full_2d']['energy_history'])):
        assert {key: actual[key] for key in expected} == expected
        assert actual['driver_abi'] == 6 and actual['energy_algorithm'] == algorithm
    save_result(result, tmp_path / 'result.h5')
    saved = load_result(tmp_path / 'result.h5')
    assert saved.metadata['execution_record'] == result.metadata['execution_record']
    assert evaluate(saved).metrics == evaluate(result).metrics



@pytest.mark.parametrize('algorithm', ['legacy_h_fou', 'temperature_fou', 'temperature_sou'])
def test_one_explicit_control_preserves_other_route_defaults(driver, algorithm):
    config = configuration(algorithm)
    config.solver = replace(config.solver, ltne_enthalpy_coupled_energy_tol=1e-7)
    case = prepare_case(config, case_id='one-explicit-control-' + algorithm)
    raw = driver.run_prepared(*build_execution_inputs(case))
    expected = dict(max_iterations=12000, sweeps=3 if algorithm == 'legacy_h_fou' else 5,
        omega=.2 if algorithm == 'temperature_sou' else .6, update_tol=.001,
        coupled_energy_tol=1e-7, equation_energy_tol=.001,
        require_enthalpy_update_on_temperature=False, driver_abi=6)
    actual = raw['main']['true_h']['effective_settings']
    assert {key: actual[key] for key in expected} == expected
    assert actual['energy_algorithm'] == algorithm


def test_explicit_thermal_controls_reject_unavailable_routes_before_flow(driver, monkeypatch):
    config = configuration('legacy_h_fou')
    config.solver = replace(config.solver, ltne_enthalpy_nsweep=4)
    case = prepare_case(config, case_id='explicit-energy2d-backend')
    with pytest.raises(ValueError, match='Python numerical backend has been retired'):
        run_case(case, RunControl(backend='python'))
    other = replace(config, fluid_B=replace(config.fluid_B, type='water'))
    with pytest.raises(ValueError, match='existing true-h route'):
        driver.run_prepared(*build_execution_inputs(prepare_case(other, case_id='explicit-energy2d-model-h')))
    original = driver.library
    class OldLibrary:
        def __getattr__(self, name):
            if name in ('tpmshx_solve_full_2d_v4', 'tpmshx_solve_full_2d_v6'):
                raise AttributeError(name)
            return getattr(original, name)
    monkeypatch.setattr(driver, 'library', OldLibrary())
    with pytest.raises(ValueError, match='lacks explicit energy controls v4'):
        driver.run_prepared(*build_execution_inputs(case))
