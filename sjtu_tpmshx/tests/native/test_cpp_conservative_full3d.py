"""Full 3D conservative-temperature candidate: native evidence and replay.

Only the existing two-sided sCO2 true-h scope is exercised. Independent HEOS
PT checks and signed boundary m*h checks use rtol=2e-12; this comparison
precision does not change the physical coupled/equation gates (0.001).
"""
from collections.abc import Mapping
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.tests.native.test_native_execution import _config


ROOT = Path(__file__).resolve().parents[3]
ALGORITHMS = ('temperature_fou', 'temperature_sou')
VERSIONS = {'temperature_fou': 1, 'temperature_sou': 2}
FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


@pytest.fixture(scope='module')
def native_path():
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    name = 'tpmshx_solver_shared.dll' if os.name == 'nt' else 'libtpmshx_solver_shared.dylib'
    path = Path(os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY',
                               ROOT / '.cache/native-deps/build' / ('pilot-' + host) / name))
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(f'native full library unavailable: {path}')
        pytest.skip(f'native full library unavailable: {path}')
    return path.resolve()


def control(path, **kwargs):
    return RunControl(backend='cpp', native_library=str(path),
                      native_table_directory=str(ROOT / '.cache/native-deps/tables'), **kwargs)


def candidate(algorithm, pair='air-sco2', *, cap=30, port_refined=None):
    config = _config(3, air_sco2=pair == 'air-sco2')
    if port_refined:
        def full_port(port):
            return replace(port, in_ctr=.015, in_w=.03, out_ctr=.015, out_w=.03,
                           in_z_ctr=.015, in_z_w=.03, out_z_ctr=.015, out_z_w=.03)
        counts = (30 if port_refined == 'partial' else 10, 10, 10)
        port_a = full_port(config.bc_A)
        if port_refined == 'partial':
            port_a = replace(port_a, in_w=.015, out_w=.015)
        config = replace(config, flags=replace(config.flags, port_wall_refine=True),
                         solver=replace(config.solver, Nx=counts[0], Ny=counts[1], Nz=counts[2]),
                         bc_A=port_a, bc_B=full_port(config.bc_B))
    prepared = prepare_case(replace(config, solver=replace(config.solver,
        enthalpy_algorithm=algorithm, max_outer_ltne=cap)), case_id='candidate-' + pair + '-' + algorithm)
    if port_refined:
        for axis, count in zip('xyz', counts):
            widths = np.asarray(prepared.grid['d' + axis])
            assert len(widths) == count and np.ptp(widths) > 0.
    return prepared


def assert_preserved(actual, expected):
    """Replay/ownership is lossless, independently of cross-solver tolerances."""
    if isinstance(expected, Mapping):
        assert actual.keys() == expected.keys()
        for key, value in expected.items():
            assert_preserved(actual[key], value)
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            assert_preserved(a, e)
    elif isinstance(expected, np.ndarray):
        np.testing.assert_array_equal(actual, expected)
    elif isinstance(expected, float) and np.isnan(expected):
        assert np.isnan(actual)
    else:
        assert actual == expected


@pytest.fixture(scope='module', params=[
    (a, p, None) for a in ALGORITHMS for p in ('air-sco2', 'sco2-water')
] + [(a, 'sco2-water', mesh) for a in ALGORITHMS for mesh in ('full', 'partial')],
                ids=lambda value: '-'.join(map(str, value)))
def completed(request, native_path):
    algorithm, pair, port_refined = request.param
    prepared = candidate(algorithm, pair, port_refined=port_refined)
    # The public C++ entry must not obtain any numerical answer from Python.
    with patch('sjtu_tpmshx.solvers.backends.python.three_d.runtime.build_problem',
               side_effect=AssertionError('Python numerical driver called')):
        result = run_case(prepared, control(native_path))
    return prepared, result


def expected_boundary_power(enthalpy, inlet_h, mass, widths, *, sou):
    """Boundary oracle: inflow h_in and one-sided linear outlet extrapolation.

    At a physical outflow boundary there is one interior neighbour and no
    exterior inflow value, so the minmod boundary reconstruction retains the
    available interior slope. This oracle never calls a production flux helper.
    """
    planes = {}
    for axis, width in enumerate(widths):
        for high in (False, True):
            sign, index = (1, -1) if high else (-1, 0)
            outward_mass = sign * np.take(mass[axis], index, axis=axis)
            cell_h = np.take(enthalpy, index, axis=axis)
            outlet_h = cell_h.copy()
            if sou and len(width) > 1:
                neighbour = -2 if high else 1
                interior_h = np.take(enthalpy, neighbour, axis=axis)
                outlet_h += (cell_h - interior_h) * width[index] / (width[index] + width[neighbour])
            planes[FACES[2 * axis + high]] = outward_mass * np.where(outward_mass > 0., outlet_h, inlet_h)
    return planes


def test_executed_algorithm_and_original_convergence_gates(completed):
    prepared, result = completed
    algorithm = prepared.parameters['enthalpy_algorithm']
    assert result.backend_id == 'cpp' and result.backend_version == 'full_3d_v2'
    assert result.metadata['thermal_mode'] == 'conservative_energy'
    assert result.run_status['converged'] is True
    diagnostics = result.metadata['diagnostics']
    assert diagnostics['native_full_3d']['entry_version'] == 2
    convergence = diagnostics['convergence_detail']
    for key in ('simple_ok', 'ltne_ok', 'outer_converged', 'fields_finite', 'envelope_ok'):
        assert convergence[key] is True, key
    for side in 'AB':
        simple = convergence['simple_' + side]
        assert simple['exit_reason'] == 'tol'
        assert simple['final_res_mom'] < 1e-4
        assert simple['final_res_mass_local'] < 1e-6
        assert simple['final_res_mass_global'] < 1e-6
        assert simple['outlet_backflow_frac'] <= .01
    histories = [row['true_h_balance'] for row in diagnostics['_ltne_info']]
    assert histories
    for balance in [*histories, diagnostics['true_h_balance']]:
        settings = balance['effective_settings']
        assert balance['energy_algorithm'] == settings['energy_algorithm'] == algorithm
        assert type(balance['energy_algorithm_version']) is int
        assert balance['energy_algorithm_version'] == settings['energy_algorithm_version'] == VERSIONS[algorithm]
        assert settings['driver_abi'] == 2 and settings['nonlinear_state_update'] == 'HEOS_PT'
        assert settings['coupled_energy_tol'] == settings['equation_energy_tol'] == .001
        assert settings['temperature_update_tol_K'] == 1e-8
        assert settings['enthalpy_face_reconstruction'] == ('FOU' if algorithm == ALGORITHMS[0] else 'h_minmod_outlet_v1')
        assert settings['sweeps'] == 5 and settings['max_iterations'] == 1500
        assert settings['omega'] == (.6 if algorithm == ALGORITHMS[0] else .2)
        assert settings['solid_omega'] == (.6 if algorithm == ALGORITHMS[0] else 1.)
        assert settings['picard_relaxation'] == (1. if algorithm == ALGORITHMS[0] else .6)
        assert np.isfinite(balance['temperature_update_K'])
        assert tuple(balance['enthalpy_clip_counts']['total']) == (0, 0)
        if balance['converged']:
            assert balance['exit_reason'] == 'converged'
            assert balance['temperature_update_K'] <= 1e-8
            assert balance['coupled_energy_balance']['ratio'] <= .001
            assert balance['equation_energy_balance']['ratio'] <= .001
    assert diagnostics['true_h_balance']['converged'] is True


def test_actual_heos_state_six_face_powers_and_postprocess(completed, monkeypatch):
    from CoolProp import AbstractState, PT_INPUTS
    from sjtu_tpmshx.postprocess import three_d

    prepared, result = completed
    native = result.boundary_fluxes['true_h']
    algorithm = prepared.parameters['enthalpy_algorithm']
    assert native['energy_algorithm'] == algorithm
    assert type(native['energy_algorithm_version']) is int
    assert native['energy_algorithm_version'] == VERSIONS[algorithm]
    assert native['boundary_power_units'] == 'W'
    assert native['physical_boundary_complete'] is True
    shape = result.fields['Ta'].shape
    widths = [np.asarray(result.grid['d' + a]) for a in 'xyz']
    differs_from_fou = False
    duties = {}
    for side, temperature in zip('AB', ('Ta', 'Tb')):
        state = AbstractState('HEOS', {'air': 'Air', 'water': 'Water', 'sco2': 'CO2'}[prepared.parameters['fluid_type_' + side]])
        state.update(PT_INPUTS, prepared.parameters['P_in' + side], prepared.parameters['T_in' + side])
        assert native['h_in_' + side] == pytest.approx(state.hmass(), rel=2e-12, abs=1e-10)
        h, k = np.empty(shape), np.empty(shape)
        for index in np.ndindex(shape):
            state.update(PT_INPUTS, result.fields['P_thermal_' + side][index], result.fields[temperature][index])
            h[index], k[index] = state.hmass(), state.conductivity()
        np.testing.assert_allclose(native['h_' + side], h, rtol=2e-12, atol=1e-10)
        np.testing.assert_allclose(native['actual_conductivity_' + side],
            prepared.design_fields['eps_' + side] * k, rtol=2e-12, atol=1e-14)
        mass = native['mass_flux_' + side]
        assert_preserved(mass, result.boundary_fluxes['mass_' + side])
        expected = expected_boundary_power(h, native['h_in_' + side], mass, widths,
                                          sou=algorithm == ALGORITHMS[1])
        fou = expected_boundary_power(h, native['h_in_' + side], mass, widths, sou=False)
        powers = native['boundary_power'][side]
        assert set(powers) == set(FACES)
        for axis in range(3):
            face_shape = tuple(size for index, size in enumerate(shape) if index != axis)
            for face in FACES[2 * axis:2 * axis + 2]:
                assert powers[face].shape == face_shape
                np.testing.assert_allclose(powers[face], expected[face], rtol=2e-12, atol=1e-10)
                differs_from_fou |= bool(np.any(np.abs(powers[face] - fou[face]) > 1e-8))
        duties[side] = -sum(float(np.sum(plane)) for plane in powers.values())
        assert duties[side] == pytest.approx(result.metadata['diagnostics']['true_h_balance']['Q_' + side], rel=2e-12, abs=1e-10)
    assert differs_from_fou is (algorithm == ALGORITHMS[1])

    def forbidden(*args, **kwargs):
        pytest.fail('candidate duty reconstructed the legacy FOU boundary')
    monkeypatch.setattr(three_d, '_boundary_enthalpy_duty', forbidden)
    metrics = evaluate(result).metrics
    for side in 'AB':
        assert metrics['Q_' + side].status == 'available'
        assert metrics['Q_' + side].value == pytest.approx(duties[side], rel=2e-12, abs=1e-10)
    assert metrics['Q'].value == pytest.approx(abs(duties['A']), rel=2e-12, abs=1e-10)
    assert metrics['Q'].spec.unit == 'W'
    for key in ('T_out_A', 'T_out_B', 'mass_flow_A', 'mass_flow_B', 'dP_A', 'dP_B'):
        assert metrics[key].status == 'available'


def test_prepared_recipe_and_detached_evidence_save_replay(completed, native_path, tmp_path, monkeypatch):
    prepared, result = completed
    config = prepared.config_snapshot['solver']
    assert config['enthalpy_algorithm'] == prepared.parameters['enthalpy_algorithm']
    assert config['enthalpy_temperature_tol_K'] == prepared.parameters['enthalpy_temperature_tol_K'] == 1e-8
    save_case(prepared, tmp_path / 'case.h5')
    restored_case = load_case(tmp_path / 'case.h5')
    assert_preserved(restored_case.parameters, prepared.parameters)
    assert_preserved(restored_case.config_snapshot, prepared.config_snapshot)
    monkeypatch.setenv('TPMSHX_VAR_RHOCP', '0')
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'invalid-receiver-option')
    replay = run_case(restored_case, control(native_path))
    for name in ('fields', 'boundary_fluxes', 'run_status'):
        assert_preserved(getattr(replay, name), getattr(result, name))
    assert_preserved(replay.metadata['diagnostics']['true_h_balance'], result.metadata['diagnostics']['true_h_balance'])
    saved_result = load_result(save_result(result, tmp_path / 'result.h5'))
    for name in ('fields', 'boundary_fluxes', 'run_status'):
        assert_preserved(getattr(saved_result, name), getattr(result, name))
    assert_preserved(saved_result.metadata['diagnostics']['true_h_balance'], result.metadata['diagnostics']['true_h_balance'])
    for key, metric in evaluate(result).metrics.items():
        restored_metric = evaluate(saved_result).metrics[key]
        assert restored_metric.status == metric.status
        assert_preserved(restored_metric.value, metric.value)


def test_fresh_cli_case_solve_and_result_replay_without_python_kernels(native_path, tmp_path):
    prepared = candidate('temperature_sou', 'air-sco2')
    reference = run_case(prepared, control(native_path))
    case_path, old_path, new_path = (tmp_path / name for name in ('case.h5', 'old.h5', 'new.h5'))
    save_case(prepared, case_path)
    save_result(reference, old_path)
    code = '''
import sys
import numpy as np
from sjtu_tpmshx.cli import main
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.postprocess.api import evaluate
case = load_case(sys.argv[1])
old = load_result(sys.argv[2])
assert case.parameters['enthalpy_algorithm'] == 'temperature_sou'
assert case.parameters['enthalpy_temperature_tol_K'] == 1e-8
assert main(['solve', sys.argv[1], sys.argv[3], '--backend', 'cpp',
    '--native-library', sys.argv[4], '--native-table-directory', sys.argv[5]]) == 0
new = load_result(sys.argv[3])
assert new.backend_id == 'cpp' and new.backend_version == 'full_3d_v2'
assert new.run_status['converged'] is True
assert new.metadata['thermal_mode'] == 'conservative_energy'
assert new.metadata['diagnostics']['true_h_balance'] == old.metadata['diagnostics']['true_h_balance']
assert evaluate(new).metrics == evaluate(old).metrics
for key, field in old.fields.items():
    np.testing.assert_array_equal(new.fields[key], field)
before, after = old.boundary_fluxes['true_h'], new.boundary_fluxes['true_h']
for key in ('energy_algorithm', 'energy_algorithm_version', 'boundary_power_units', 'physical_boundary_complete'):
    assert after[key] == before[key]
assert after['energy_algorithm'] == 'temperature_sou'
assert after['energy_algorithm_version'] == 2
for side in 'AB':
    for key in ('h_', 'h_in_', 'actual_conductivity_'):
        np.testing.assert_array_equal(after[key + side], before[key + side])
    for actual, expected in zip(after['mass_flux_' + side], before['mass_flux_' + side]):
        np.testing.assert_array_equal(actual, expected)
    for face, power in before['boundary_power'][side].items():
        np.testing.assert_array_equal(after['boundary_power'][side][face], power)
assert main(['postprocess', sys.argv[3], sys.argv[3] + '.json']) == 0
assert load_metrics(sys.argv[3] + '.json').metrics == evaluate(old).metrics
forbidden = ('numba', 'sjtu_tpmshx.solvers.ltne_', 'sjtu_tpmshx.solvers.simple_',
    'sjtu_tpmshx.solvers._kernels', 'sjtu_tpmshx.solvers.backends.python.three_d.runtime')
assert not [name for name in sys.modules if name.startswith(forbidden)]
'''
    process = subprocess.run([sys.executable, '-c', code, str(case_path), str(old_path), str(new_path),
        str(native_path), control(native_path).native_table_directory], cwd=ROOT,
        capture_output=True, text=True, timeout=90)
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize('algorithm', ALGORITHMS)
def test_one_block_budget_keeps_iteration_limit_and_final_evidence(native_path, algorithm):
    # Typed production configs require at least two outer passes. Each pass
    # deliberately receives only one thermal block, retaining its failed exit.
    prepared = candidate(algorithm, cap=2)
    prepared = replace(prepared, parameters=dict(prepared.parameters, ltne_enthalpy_outer=1))
    result = run_case(prepared, control(native_path))
    balance = result.metadata['diagnostics']['true_h_balance']
    assert result.run_status['converged'] is False
    assert balance['converged'] is False and balance['exit_reason'] == 'iteration_limit'
    assert balance['iterations'] == balance['effective_settings']['max_iterations'] == 1
    assert balance['temperature_update_K'] > balance['effective_settings']['temperature_update_tol_K']
    assert balance['post_after_last_thermal'] is True
    assert len(result.metadata['diagnostics']['_ltne_info']) == 2
    assert result.boundary_fluxes['true_h']['energy_algorithm'] == algorithm
    assert result.boundary_fluxes['true_h']['energy_algorithm_version'] == VERSIONS[algorithm]
    assert evaluate(result).metrics['Q'].status == 'available'


@pytest.mark.parametrize('symbol', ['tpmshx_solve_full_3d_v2', 'tpmshx_full_3d_get_energy_evidence_v1'])
def test_missing_candidate_native_capability_never_falls_back(native_path, monkeypatch, symbol):
    driver = NativeFull3DDriver(native_path)
    library = driver.library

    class OldLibrary:
        def __getattr__(self, name):
            if name == symbol:
                raise AttributeError(name)
            return getattr(library, name)
    monkeypatch.setattr(driver, 'library', OldLibrary())
    def forbidden_fallback(*_):
        pytest.fail('candidate fell back to old entry')
    forbidden_fallback.argtypes = driver.call.argtypes
    monkeypatch.setattr(driver, 'call', forbidden_fallback)
    with pytest.raises(ValueError, match='lacks conservative energy v2'):
        driver.run_prepared(*build_execution_inputs(candidate(ALGORITHMS[0])))


@pytest.mark.parametrize('algorithm', ['legacy_h_fou', *ALGORITHMS])
def test_missing_version_query_blocks_candidate_before_solve_but_allows_legacy(native_path, monkeypatch, algorithm):
    from sjtu_tpmshx.solvers.backends.cpp import full_3d
    original = NativeFull3DDriver(native_path).library
    entered = []

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
            if name == 'tpmshx_solve_full_3d_v1':
                return legacy
            if name in ('tpmshx_solve_full_3d_v2', 'tpmshx_solve_full_3d_v3'):
                return forbidden_candidate
            return getattr(original, name)

    prepared = candidate(algorithm, cap=2)
    monkeypatch.setattr(full_3d.ct, 'CDLL', lambda _: OldLibrary())
    old = NativeFull3DDriver(native_path)
    if algorithm == 'legacy_h_fou':
        with pytest.raises(LegacyEntered):
            old.run_prepared(*build_execution_inputs(prepared))
        assert entered == ['legacy']
    else:
        with pytest.raises(ValueError, match='lacks conservative energy algorithm version query'):
            old.run_prepared(*build_execution_inputs(prepared))
        assert not entered


@pytest.mark.parametrize('option, value, message', [
    ('fluid_type_B', 'water', 'two-sided true-h route'),
    ('fluid_B_cfg', None, 'two-sided true-h route'),
    ('conservative_ltne', False, 'unsupported candidate'),
    ('variable_rho_cp', False, 'unsupported candidate'),
    ('disp_C_A', .01, 'unsupported candidate'),
    ('disp_C_B', .01, 'unsupported candidate'),
    ('mms_S_s_field', 1., 'physical sources'),
    ('ltne_enthalpy_nsweep', 0, 'invalid candidate'),
])
def test_unsupported_native_physical_scope_fails_explicitly(native_path, option, value, message):
    cfg, prepared = build_execution_inputs(candidate(ALGORITHMS[0]))
    cfg[option] = np.ones((4, 4, 4)) * value if option == 'mms_S_s_field' else value
    # This is a native guard test: avoid a receiving process's env override.
    if option == 'variable_rho_cp':
        cfg['_environment']['TPMSHX_VAR_RHOCP'] = None
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    with pytest.raises(ValueError, match=message):
        driver.run_prepared(cfg, prepared)


@pytest.mark.parametrize('backend, mode', [('python', 'full'), ('cpp', 'quick_design')])
def test_candidate_requires_public_full_cpp_route(native_path, backend, mode):
    prepared = candidate(ALGORITHMS[0])
    prepared = replace(prepared, metadata=dict(prepared.metadata, mode=mode))
    with pytest.raises(ValueError, match='requires full compute with backend=cpp'):
        run_case(prepared, replace(control(native_path), backend=backend))


@pytest.mark.parametrize('during', [False, True])
def test_cancel_returns_no_field_result_and_releases_owned_state(native_path, monkeypatch, during):
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    release, released, calls = driver.release, [], []

    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)

    def cancel():
        calls.append(True)
        return len(calls) >= (100 if during else 1)
    monkeypatch.setattr(driver, 'release', tracked)
    with pytest.raises(CancelledError):
        driver.run_prepared(*build_execution_inputs(candidate(ALGORITHMS[1])), control(native_path, cancel_check=cancel))
    assert len(calls) >= (100 if during else 1)
    assert released == ([None] if during else [])


def test_interrupt_after_candidate_native_return_releases_owner(native_path, monkeypatch):
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    library, release, released = driver.library, driver.release, []
    call = library.tpmshx_solve_full_3d_v2

    def interrupted(*args):
        assert call(*args) == 0
        assert args[4]._obj.owner
        raise KeyboardInterrupt('candidate native-return')

    class InterruptedLibrary:
        def __getattr__(self, name):
            return interrupted if name == 'tpmshx_solve_full_3d_v2' else getattr(library, name)

    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)
    monkeypatch.setattr(driver, 'library', InterruptedLibrary())
    monkeypatch.setattr(driver, 'release', tracked)
    prepared = candidate(ALGORITHMS[0], cap=2)
    with pytest.raises(KeyboardInterrupt, match='candidate native-return'):
        driver.run_prepared(*build_execution_inputs(prepared), control(native_path))
    assert released == [None]


@pytest.mark.parametrize('algorithm', ['legacy_h_fou', *ALGORITHMS])
def test_large_grid_packing_keeps_legacy_rb_and_candidate_serial(tmp_path, monkeypatch, algorithm):
    from sjtu_tpmshx.solvers.backends.cpp import full_3d

    config = _config(3, air_sco2=True)
    config = replace(config, solver=replace(config.solver, Nx=32, Ny=32, Nz=32,
                                            enthalpy_algorithm=algorithm))
    prepared = prepare_case(config, case_id='large-grid-control-' + algorithm)
    seen = []

    class EntryCaptured(Exception):
        pass

    def capture(*args):
        data, settings = args[0]._obj, args[1]._obj
        assert tuple(data.shape) == (32, 32, 32)
        seen.append(settings.red_black_energy)
        assert settings.red_black_energy == (1 if algorithm == 'legacy_h_fou' else 0)
        raise EntryCaptured

    # Resolve/pack genuine prepared 32768-cell input, but never load a library
    # or solve a large grid merely to inspect the automatically selected flag.
    library = SimpleNamespace(tpmshx_full_3d_abi_version=lambda: 1,
        tpmshx_solve_full_3d_v1=capture, tpmshx_solve_full_3d_v2=capture,
        tpmshx_full_3d_release_v1=lambda *_: pytest.fail('packing allocated native ownership'),
        tpmshx_full_3d_get_bootstrap_trace_v1=lambda *_: None,
        tpmshx_full_3d_get_energy_evidence_v1=lambda *_: None,
        tpmshx_energy_algorithm_version_v1=lambda algorithm: {1: 1, 2: 2}.get(algorithm, 0))
    monkeypatch.setattr(full_3d.ct, 'CDLL', lambda _: library)
    path = tmp_path / 'packing-only-library'
    path.touch()
    driver = NativeFull3DDriver(path)
    with pytest.raises(EntryCaptured):
        driver.run_prepared(*build_execution_inputs(prepared))
    assert len(seen) == 1
