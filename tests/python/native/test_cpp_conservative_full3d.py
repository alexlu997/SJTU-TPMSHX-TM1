"""Full 3D conservative-temperature candidate: native evidence and replay.

The two-sided sCO2 scope uses each fluid's selected energy model. Independent
model/EOS checks and signed boundary m*h checks use rtol=2e-12; this comparison
precision does not change the physical coupled/equation gates (0.001).
"""
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.file_io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers import full_3d
from sjtu_tpmshx.cpp_interface import full_3d_stage
from tests.python.native.shared_library import library_path
from tests.python.native.stage_interception import run_stage
from tests.python.native.test_native_execution import _config


ROOT = Path(__file__).resolve().parents[3]
ALGORITHMS = ('temperature_sou',)
VERSIONS = {'temperature_fou': 1, 'temperature_sou': 2}
FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


@pytest.fixture(scope='module')
def native_path():
    return library_path().resolve()


@pytest.mark.parametrize('version', [1, 99])
def test_full_3d_binding_rejects_incompatible_abi(monkeypatch, tmp_path, version):
    path = tmp_path / 'old-library'
    path.touch()
    case = candidate(ALGORITHMS[0], cap=2)
    library = SimpleNamespace(tpmshx_full_3d_abi_version=lambda: version)
    monkeypatch.setattr(full_3d_stage.ct, 'CDLL', lambda _: library)
    with pytest.raises(ValueError, match=rf'unsupported full 3D ABI {version}; expected 2'):
        full_3d.run_case(case, control(path))


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
    assert result.backend_id == 'cpp' and result.backend_version == 'full_3d_v5'
    assert result.metadata['thermal_mode'] == 'conservative_energy'
    record = result.metadata['execution_record']
    assert record['numerics']['unknown'] == 'T'
    assert record['numerics']['algorithm'] == algorithm
    assert record['numerics']['face_reconstruction'] == 'h_minmod_outlet_v1'
    for side in record['sides'].values():
        assert side['energy']['relation'] == ('eos_h_TP' if side['fluid'] in ('co2', 'sco2') else 'integral_cp_T')
    normalization = record['numerics']['enthalpy_update_normalization']
    assert normalization['definition'] == 'inlet_cp_times_temperature_difference_v1'
    assert normalization['unit'] == 'J/kg'
    assert all(np.isfinite(value) and value >= 1. for value in normalization['sides'].values())
    assert result.run_status['converged'] is True
    diagnostics = result.metadata['diagnostics']
    assert diagnostics['native_full_3d']['entry_version'] == 5
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
        assert settings['effective_settings_source'] == 'native_completed_thermal_call'
        assert balance['energy_algorithm'] == settings['energy_algorithm'] == algorithm
        assert type(balance['energy_algorithm_version']) is int
        assert balance['energy_algorithm_version'] == settings['energy_algorithm_version'] == VERSIONS[algorithm]
        assert settings['driver_abi'] == 5 and settings['nonlinear_state_update'] == 'per_side_energy_relation'
        assert settings['coupled_energy_tol'] == settings['equation_energy_tol'] == .001
        assert settings['temperature_update_tol_K'] == 1e-8
        assert settings['enthalpy_face_reconstruction'] == 'h_minmod_outlet_v1'
        assert settings['sweeps'] == 5 and settings['max_iterations'] == 1500
        assert settings['omega'] == .2
        assert settings['solid_omega'] == 1.
        assert settings['picard_relaxation'] == .6
        assert np.isfinite(balance['temperature_update_K'])
        assert tuple(balance['enthalpy_clip_counts']['total']) == (0, 0)
        if balance['converged']:
            assert balance['exit_reason'] == 'converged'
            assert balance['temperature_update_K'] <= 1e-8
            assert balance['coupled_energy_balance']['ratio'] <= .001
            assert balance['equation_energy_balance']['ratio'] <= .001
    assert diagnostics['true_h_balance']['converged'] is True


def test_actual_side_models_six_face_powers_and_postprocess(completed, monkeypatch):
    from CoolProp import AbstractState, PT_INPUTS
    from tests.python.native.full_thermal_reference import model_enthalpy

    prepared, result = completed
    native = result.boundary_fluxes['true_h']
    algorithm = prepared.parameters['enthalpy_algorithm']
    assert native['energy_algorithm'] == algorithm
    assert type(native['energy_algorithm_version']) is int
    assert native['energy_algorithm_version'] == VERSIONS[algorithm]
    assert native['boundary_power_units'] == 'W'
    assert native['physical_boundary_complete'] is True
    audit = evaluate_physical_balance(result)['energy']
    assert audit['status'] == 'available' and audit['physical_boundary_complete'] is True
    assert audit['units'] == 'W' and abs(audit['telescoping_error']) < 1e-8
    equations = result.metadata['diagnostics']['true_h_balance']['equation_energy_balance']
    for side, expected in zip(('A', 'B', 'solid'), (*equations['fluid_abs_sum'], equations['solid_abs_sum'])):
        assert audit['phases'][side]['residual']['l1'] == pytest.approx(expected, rel=2e-12, abs=1e-10)
    shape = result.fields['Ta'].shape
    widths = [np.asarray(result.grid['d' + a]) for a in 'xyz']
    differs_from_fou = False
    duties = {}
    for side, temperature in zip('AB', ('Ta', 'Tb')):
        fluid = prepared.parameters['fluid_type_' + side]
        if fluid in ('air', 'water'):
            h = model_enthalpy(result.fields[temperature], fluid)
            inlet_h = model_enthalpy(prepared.parameters['T_in' + side], fluid)
            sampling = [row for row in result.metadata['property_sampling'] if row['side'] == side
                        and row['stage'] == 'thermal' and row['quantity'] == 'conductivity']
            assert sampling[-1]['provider'] == 'outer_property_state'
            assert sampling[-1]['operation'] == 'copy'
            assert np.all(np.isfinite(native['actual_conductivity_' + side]))
            assert np.all(native['actual_conductivity_' + side] >= 0.)
        else:
            state = AbstractState('HEOS', 'CO2')
            state.update(PT_INPUTS, prepared.parameters['P_in' + side], prepared.parameters['T_in' + side])
            inlet_h = state.hmass()
            h, k = np.empty(shape), np.empty(shape)
            for index in np.ndindex(shape):
                state.update(PT_INPUTS, result.fields['P_thermal_' + side][index], result.fields[temperature][index])
                h[index], k[index] = state.hmass(), state.conductivity()
            np.testing.assert_allclose(native['actual_conductivity_' + side],
                prepared.design_fields['eps_' + side] * k, rtol=2e-12, atol=1e-14)
        assert native['h_in_' + side] == pytest.approx(inlet_h, rel=2e-12, abs=1e-10)
        np.testing.assert_allclose(native['h_' + side], h, rtol=2e-12, atol=1e-10)
        mass = native['mass_flux_' + side]
        assert_preserved(mass, result.boundary_fluxes['mass_' + side])
        expected = expected_boundary_power(h, native['h_in_' + side], mass, widths,
                                          sou=True)
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
    assert differs_from_fou

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
from sjtu_tpmshx.file_io.case_io import load_case
from sjtu_tpmshx.file_io.result_io import load_result
from sjtu_tpmshx.file_io.metrics_io import load_metrics
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
case = load_case(sys.argv[1])
old = load_result(sys.argv[2])
assert case.parameters['enthalpy_algorithm'] == 'temperature_sou'
assert case.parameters['enthalpy_temperature_tol_K'] == 1e-8
assert main(['solve', sys.argv[1], sys.argv[3], '--backend', 'cpp',
    '--native-library', sys.argv[4], '--native-table-directory', sys.argv[5]]) == 0
new = load_result(sys.argv[3])
assert new.backend_id == 'cpp' and new.backend_version == 'full_3d_v5'
assert new.run_status['converged'] is True
assert new.metadata['thermal_mode'] == 'conservative_energy'
assert new.metadata['diagnostics']['true_h_balance'] == old.metadata['diagnostics']['true_h_balance']
assert evaluate(new).metrics == evaluate(old).metrics
assert evaluate_physical_balance(new) == evaluate_physical_balance(old)
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


def partial_library(monkeypatch, **replacements):
    """Load the real library through full_3d_stage with some symbols replaced or missing."""
    original = full_3d_stage.ct.CDLL

    class PartialLibrary:
        def __init__(self, path):
            self.library = original(path)

        def __getattr__(self, name):
            if name in replacements:
                if replacements[name] is None:
                    raise AttributeError(name)
                return replacements[name]
            return getattr(self.library, name)

    monkeypatch.setattr(full_3d_stage.ct, 'CDLL', PartialLibrary)


def test_unsupported_saved_stage_abi_is_rejected_before_flow(native_path, monkeypatch):
    case = candidate(ALGORITHMS[0], cap=2)
    partial_library(monkeypatch, tpmshx_stage_run_3d_abi_version=lambda: 2)
    progress = []
    with pytest.raises(ValueError, match='unsupported saved 3D stage ABI 2; expected 3'):
        run_case(case, control(native_path, progress=progress.append))
    assert not progress


def test_missing_execution_view_fails_before_flow(native_path, monkeypatch):
    case = candidate(ALGORITHMS[0], cap=2)
    partial_library(monkeypatch, tpmshx_stage_run_3d_execution_view_v1=None)
    progress = []
    with pytest.raises(ValueError, match='lacks tpmshx_stage_run_3d_execution_view_v1'):
        run_case(case, control(native_path, progress=progress.append))
    assert not progress


@pytest.mark.parametrize('algorithm', ALGORITHMS)
def test_zero_sweep_budget_keeps_initial_state_and_energy_gates(native_path, algorithm):
    case = candidate(algorithm, cap=2)
    case = replace(case, parameters=dict(case.parameters, ltne_enthalpy_outer=1, ltne_enthalpy_nsweep=0))
    result = run_case(case, control(native_path, cpu_threads=1))
    assert not result.run_status['converged']
    balance = result.metadata['diagnostics']['true_h_balance']
    assert balance['energy_algorithm'] == algorithm and balance['exit_reason'] == 'iteration_limit'
    assert balance['iterations'] == balance['effective_settings']['max_iterations'] == 1
    assert balance['effective_settings']['sweeps'] == 0
    assert balance['temperature_update_K'] == 0.
    assert balance['equation_energy_balance']['ratio'] > balance['effective_settings']['equation_energy_tol']
    cfg = case.parameters
    tin = (cfg['T_inA'], cfg['T_inB'])
    solid = cfg['T_s_init'] if cfg.get('T_s_init') is not None else .5*sum(tin)
    for key, value in zip(('Ta', 'Tb', 'Ts'), (*tin, solid)):
        np.testing.assert_array_equal(result.fields[key], np.full_like(result.fields[key], value))


def resolved_controls(monkeypatch):
    """Record the native resolved energy controls of each saved 3D run."""
    original, seen = full_3d_stage._detach, []

    def detach(r, shape, settings, *args, **kwargs):
        seen.append((settings.conservative, settings.variable_rho_cp, settings.red_black_energy))
        return original(r, shape, settings, *args, **kwargs)

    monkeypatch.setattr(full_3d_stage, '_detach', detach)
    return seen


# The saved stage resolves red-black energy natively; test_full_3d checks it on the typed bridge.
@pytest.mark.parametrize('algorithm', ALGORITHMS)
@pytest.mark.parametrize('pair', ['air-sco2', 'sco2-water'])
@pytest.mark.parametrize('option', ['conservative_ltne', 'variable_rho_cp', 'combined'])
def test_existing_true_h_controls_keep_qualified_state(native_path, monkeypatch, algorithm, pair, option):
    case = candidate(algorithm, pair=pair)
    baseline = run_case(case, control(native_path, cpu_threads=1))
    parameters = dict(case.parameters)
    for name in ('conservative_ltne', 'variable_rho_cp'):
        if option in (name, 'combined'):
            parameters[name] = False
            if name == 'variable_rho_cp':
                parameters['_environment'] = dict(parameters['_environment'], TPMSHX_VAR_RHOCP=None)
    case = replace(case, parameters=parameters)
    seen = resolved_controls(monkeypatch)
    result = run_case(case, control(native_path, cpu_threads=1))
    assert seen == [(option not in ('conservative_ltne', 'combined'),
                     option not in ('variable_rho_cp', 'combined'), False)]
    test_executed_algorithm_and_original_convergence_gates((case, result))
    test_actual_side_models_six_face_powers_and_postprocess((case, result), monkeypatch)
    for key in ('Ta', 'Tb', 'Ts'):
        np.testing.assert_allclose(result.fields[key], baseline.fields[key], rtol=0., atol=.01)
    for side in 'AB':
        limit = 1e-6 + 1e-5 * case.parameters['u_' + side]
        for component in ('uc', 'vc', 'wc'):
            key = component + side
            np.testing.assert_allclose(result.fields[key], baseline.fields[key], rtol=0., atol=limit)
    metrics, reference = evaluate(result).metrics, evaluate(baseline).metrics
    for key in ('Q', 'dP_A', 'dP_B', 'mass_flow_A', 'mass_flow_B'):
        a, b = metrics[key].value, reference[key].value
        assert abs(a-b) <= .001 * max(abs(a), abs(b)), key
    for key in ('T_out_A', 'T_out_B'):
        assert abs(metrics[key].value-reference[key].value) <= .01, key


@pytest.mark.parametrize('option, value, message', [
    ('mms_S_s_field', 1., 'physical sources'),
])
def test_unsupported_native_physical_scope_fails_explicitly(native_path, option, value, message):
    case = candidate(ALGORITHMS[0])
    case = replace(case, parameters=dict(case.parameters, **{
        option: np.ones((4, 4, 4)) * value if option == 'mms_S_s_field' else value}))
    progress = []
    with pytest.raises(ValueError, match=message):
        run_case(case, control(native_path, progress=progress.append))
    assert not progress


@pytest.mark.parametrize('backend, mode', [('python', 'full')])
def test_candidate_requires_public_full_cpp_route(native_path, backend, mode):
    prepared = candidate(ALGORITHMS[0])
    prepared = replace(prepared, metadata=dict(prepared.metadata, mode=mode))
    message = ('Python numerical backend has been retired' if backend == 'python'
               else 'requires full compute with backend=cpp')
    with pytest.raises(ValueError, match=message):
        run_case(prepared, replace(control(native_path), backend=backend))


def tracked_release(monkeypatch):
    """Record the owner of each released saved 3D result after its release."""
    release, released = full_3d_stage.release_result, []

    def tracked(library, result):
        assert result.owner
        release(library, result)
        released.append(result.owner)

    monkeypatch.setattr(full_3d_stage, 'release_result', tracked)
    return released


@pytest.mark.parametrize('during', [False, True])
def test_cancel_returns_no_field_result_and_releases_owned_state(native_path, monkeypatch, during):
    released, calls = tracked_release(monkeypatch), []

    def cancel():
        calls.append(True)
        return len(calls) >= (100 if during else 1)
    with pytest.raises(CancelledError):
        run_case(candidate(ALGORITHMS[0]), control(native_path, cancel_check=cancel))
    assert len(calls) >= (100 if during else 1)
    assert released == ([None] if during else [])


def test_interrupt_after_candidate_native_return_releases_owner(native_path, monkeypatch):
    released = tracked_release(monkeypatch)
    require_completed = full_3d_stage.require_completed

    def interrupted(result, traces):
        require_completed(result, traces)
        raise KeyboardInterrupt('candidate native-return')
    monkeypatch.setattr(full_3d_stage, 'require_completed', interrupted)
    with pytest.raises(KeyboardInterrupt, match='candidate native-return'):
        run_case(candidate(ALGORITHMS[0], cap=2), control(native_path))
    assert released == [None]


@pytest.mark.parametrize('air_sco2', [True, False])
def test_large_grid_packing_keeps_legacy_rb_and_candidate_serial(native_path, air_sco2):
    from sjtu_tpmshx.cpp_interface.solver_library._thermal_abi import _full_enthalpy_defaults

    config = _config(3, air_sco2=True)
    if not air_sco2:
        config.fluid_B.type = 'water'
        config.fluid_B.P_in_Pa = 2e6
    config = replace(config, solver=replace(config.solver, Nx=32, Ny=32, Nz=32,
                                            enthalpy_algorithm='temperature_sou'))
    prepared = prepare_case(config, case_id='large-grid-control-temperature_sou')

    class ControlsCaptured(Exception):
        pass

    def capture(state):
        seen.update(state)
        raise ControlsCaptured

    # Stop at the first saved boundary; the snapshot holds the native resolved controls.
    seen = {}
    with pytest.raises(ControlsCaptured):
        full_3d.run_case(prepared, control(native_path), checkpoint=capture)
    assert tuple(seen['input.geometry.grid.d' + axis].size for axis in 'xyz') == (32, 32, 32)
    assert seen['control.red_black_energy'][0] == (0 if air_sco2 else 1)
    _, library, _, _ = full_3d_stage.open_library(native_path, None)
    defaults = _full_enthalpy_defaults(library, 3, 2, not air_sco2)
    assert (seen['control.enthalpy.max_iterations'][0], seen['control.enthalpy.sweeps'][0]) == (
        defaults.max_iterations, defaults.sweeps)
    assert (seen['control.enthalpy.omega'][0], seen['control.enthalpy.update_tolerance'][0]) == (
        defaults.omega, defaults.update_tolerance)


@pytest.mark.parametrize('algorithm', ALGORITHMS)
def test_mixed_conductivity_copies_the_last_outer_transport(native_path, algorithm):
    prepared = candidate(algorithm, cap=2)
    stage = run_stage(prepared, control(native_path))
    raw = stage.native
    state = raw['true_h']['_native_state']
    for side, label in enumerate('AB'):
        if prepared.parameters['fluid_type_' + label] in ('air', 'water'):
            np.testing.assert_array_equal(state['actual_conductivity_' + label], stage.arrays['conductivity'][side])
    assert raw['enthalpy_update_normalization']['definition'] == 'inlet_cp_times_temperature_difference_v1'


@pytest.mark.parametrize('pair, integral_side', [('air-sco2', 0), ('sco2-water', 1)])
def test_dispersion_retains_shared_transport_and_energy_models(native_path, monkeypatch, pair, integral_side):
    runtime = control(native_path, cpu_threads=1)
    prepared = candidate('temperature_sou', pair)
    dispersed = replace(prepared, parameters=dict(prepared.parameters, disp_C_A=.01, disp_C_B=.02))
    stage = run_stage(dispersed, runtime)
    raw, result = stage.native, stage.result
    assert raw['converged']
    state = raw['true_h']['_native_state']
    side = 'AB'[integral_side]
    conductivity = stage.arrays['conductivity'][integral_side]
    np.testing.assert_array_equal(state['actual_conductivity_' + side], conductivity)
    with monkeypatch.context() as patch:
        test_actual_side_models_six_face_powers_and_postprocess((dispersed, result), patch)
    baseline = run_stage(prepared, runtime)
    assert baseline.native['converged']
    assert np.all(conductivity > baseline.arrays['conductivity'][integral_side])


@pytest.mark.parametrize('algorithm', ['legacy_h_fou', 'temperature_fou'])
def test_retired_algorithm_is_rejected_before_flow(native_path, algorithm):
    progress = []
    with pytest.raises(ValueError, match='energy|enthalpy'):
        run_case(candidate(algorithm), control(native_path, progress=progress.append))
    assert not progress
