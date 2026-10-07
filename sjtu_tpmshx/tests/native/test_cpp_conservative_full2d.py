"""Complete conservative energy coupling and the portable 2D face ledger.

These are same-state evidence checks, not parity against a different algorithm.
Frozen gates: EOS h rtol=2e-12/atol=2e-7 J/kg; K rtol=2e-12/atol=2e-12;
native/portable signed Q rtol=2e-10/atol=2e-7 W/m. Native acceptance is unchanged.
"""
from dataclasses import replace
import os
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
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import capture_result
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs

ROOT = Path(__file__).resolve().parents[3]
VERSIONS = {'temperature_fou': 1, 'temperature_sou': 2}


@pytest.fixture(scope='module')
def driver():
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    name = 'tpmshx_solver_shared.dll' if os.name == 'nt' else 'libtpmshx_solver_shared.dylib'
    path = Path(os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY',
        ROOT / '.cache/native-deps/build' / ('pilot-' + host) / name))
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(f'native full library unavailable: {path}')
        pytest.skip(f'native full library unavailable: {path}')
    return NativeFull2DDriver(path, table_directory=ROOT / '.cache/native-deps/tables')


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
    case, cfg, _, raw, result = capped
    info, thermal = raw['main']['true_h'], raw['main']
    assert raw['entry_version'] == 3 and raw['fine'] is None
    assert result.backend_version == 'full_2d_v3'
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
    metrics = evaluate(result).metrics
    for side, label, fluid in ((0, 'A', 'Water'), (1, 'B', 'CO2')):
        temperature = thermal['temperature'][side]
        pressure = thermal['pressure'][side]
        h = CP.PropsSI('Hmass', 'T', temperature.ravel(), 'P', pressure.ravel(), 'HEOS::' + fluid)
        k = CP.PropsSI('conductivity', 'T', temperature.ravel(), 'P', pressure.ravel(), 'HEOS::' + fluid)
        np.testing.assert_allclose(state['h_' + label].ravel(), h, rtol=2e-12, atol=2e-7)
        split = cfg['thermal_geometry']['split_A'] if side == 0 else 1 - cfg['thermal_geometry']['split_A']
        np.testing.assert_allclose(state['actual_conductivity_' + label].ravel(),
                                   k * cfg['eps'] * split, rtol=2e-12, atol=2e-12)
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
    assert load_case(case_path).parameters['run_settings']['solver']['enthalpy_algorithm'] == \
        cfg['compute_cfg'].solver.enthalpy_algorithm
    assert evaluate(load_result(result_path)).metrics == evaluate(result).metrics
    code = '''
import sys
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate
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
    completed = subprocess.run([sys.executable, '-c', code, str(case_path), str(result_path),
        str(tmp_path / 'replayed.h5'), str(driver.path), str(ROOT / '.cache/native-deps/tables')],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_candidate_requires_supported_route_and_backend(driver):
    config = configuration('temperature_sou')
    case = prepare_case(config, case_id='energy2d-backend')
    with pytest.raises(ValueError, match='requires full compute with backend=cpp'):
        run_case(case)
    other = replace(config, fluid_B=replace(config.fluid_B, type='water'))
    with pytest.raises(ValueError, match='requires the existing true-h route'):
        driver.run_prepared(*build_execution_inputs(prepare_case(other, case_id='energy2d-route')))


@pytest.mark.parametrize('missing', ['tpmshx_solve_full_2d_v3', 'tpmshx_full_2d_get_energy_evidence_v1'])
def test_old_library_candidate_capability_fails_before_flow(driver, monkeypatch, missing):
    original = driver.library
    class OldAPI:
        def __getattr__(self, name):
            if name == missing:
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
            if name == 'tpmshx_energy_algorithm_version_v1':
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
