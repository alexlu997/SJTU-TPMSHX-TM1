"""The isolated stage retains complete reports from current and stored evidence."""
import ctypes as ct
from dataclasses import replace
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from sjtu_tpmshx.shared import _native_result as core
from sjtu_tpmshx.shared.domain.metric_spec import MetricSpec
from sjtu_tpmshx.shared.domain.portable_data import mutable_data
from sjtu_tpmshx.shared.io.result_io import load_result, save_result
from sjtu_tpmshx.development.tests.result_stage_fixture import native_report, python_report, thaw
from sjtu_tpmshx.development.tests.test_conservative_energy_results import result_fixture
from sjtu_tpmshx.development.tests.test_temperature_face_results import temperature_fixture


@pytest.fixture(scope='module')
def stage_library():
    selected = os.environ.get('TPMSHX_RESULT_STAGE_LIBRARY')
    library = ct.CDLL(selected) if selected else core._library().library
    assert hasattr(library, 'tpmshx_result_stage_evaluate_v1'), 'build the current independent result library'
    return library


def assert_same(result, library, request=None):
    actual = native_report(result, library, request=request)
    expected = python_report(result, request)
    assert actual == expected
    return actual


@pytest.fixture(scope='module', params=[2, 3])
def real_result(request):
    dimension = request.param
    frozen = os.environ.get('TPMSHX_RESULT_STAGE_FROZEN_DIR')
    if frozen:
        return load_result(Path(frozen) / f'air-{dimension}d/results.h5')
    if sys.platform == 'linux':
        pytest.skip('Linux supports stored-result evaluation without a full solver')
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.shared.domain.compute_config import FluidConfig
    from sjtu_tpmshx.development.tests.native.test_native_execution import _config
    from sjtu_tpmshx.development.tests.native.test_cpp_full_3d import control
    from sjtu_tpmshx.development.tests.native.shared_library import library_path
    config = _config(dimension, True)
    config = replace(config, fluid_B=FluidConfig(type='air', u_mps=3., T_in_K=300., P_in_Pa=2e5))
    case = prepare_case(config, case_id=f'result-stage-{dimension}d')
    return run_case(case, replace(control(library_path()), cpu_threads=2))


@pytest.mark.parametrize('query', ['evaluate', 'applicability', 'physical_balance', 'qualification'])
def test_real_2d_3d_all_queries_exact(stage_library, real_result, query, tmp_path):
    from sjtu_tpmshx.postprocess import api
    result = load_result(save_result(real_result, tmp_path / 'result.h5'))
    metrics = api.evaluate(result).metrics
    if query == 'evaluate':
        expected = python_report(result)
    elif query == 'qualification':
        expected = thaw(api.evaluate_qualification(result, metrics))
    else:
        expected = thaw(getattr(api, 'evaluate_' + query)(result))
    assert native_report(result, stage_library, query, metrics=metrics) == expected


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('algorithm,version', [('temperature_fou', 1), ('temperature_sou', 1), ('temperature_sou', 2)])
def test_conservative_reports_exact(stage_library, dimension, algorithm, version):
    assert_same(result_fixture(dimension, algorithm, version), stage_library)


@pytest.mark.parametrize('dimension', [2, 3])
def test_temperature_reports_exact(stage_library, dimension):
    assert_same(temperature_fixture(dimension), stage_library)


@pytest.mark.parametrize('module,name', [
    ('test_core_metrics', 'test_native_metrics_ignore_display_and_reported_scalars'),
    ('test_three_d', 'test_three_d_native_faces_and_pressure'),
    ('test_three_d', 'test_three_d_outlet_ignores_reverse_flow_and_uses_native_enthalpy'),
    ('test_quick_design', 'test_quick_native_duty_pressure_and_unconverged_state'),
])
def test_existing_hand_references_match_complete_stage(stage_library, monkeypatch, module, name):
    import importlib
    module = importlib.import_module('sjtu_tpmshx.development.tests.postprocess_tm1.' + module)
    original = module.evaluate
    def checked(result, metric_spec=None):
        assert_same(result, stage_library, metric_spec)
        return original(result, metric_spec)
    monkeypatch.setattr(module, 'evaluate', checked)
    getattr(module, name)()


@pytest.mark.parametrize('container', ['parameters', 'dir_A', 'diagnostics', 'design_fields', 'boundary_openings'])
def test_missing_original_containers_keep_first_reason(stage_library, container):
    result = result_fixture(2)
    metadata = mutable_data(result.metadata)
    metadata.update(solid_density_kg_m3=7800., design_fields={'eps_arr': np.full((2, 3), .7)})
    metadata['parameters']['boundary_openings'] = {side: {'in_geom_frac': np.ones(3), 'out_geom_frac': np.ones(3)} for side in 'AB'}
    fields = dict(result.fields, P_report_A=np.full((2, 3), 1000.), P_report_B=np.full((2, 3), 1000.))
    if container in ('dir_A', 'boundary_openings'):
        del metadata['parameters'][container]
    else:
        del metadata[container]
    assert_same(replace(result, fields=fields, metadata=metadata), stage_library)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('defect', ['missing_complete', 'truthy_complete', 'float_version', 'bool_version',
                                  'missing_power', 'missing_side', 'missing_face', 'nan', 'units'])
def test_invalid_conservative_evidence_retains_status_and_reason(stage_library, dimension, defect):
    result = result_fixture(dimension)
    flux = mutable_data(result.boundary_fluxes)
    evidence = flux['true_h']
    if defect == 'missing_complete': del evidence['physical_boundary_complete']
    elif defect == 'truthy_complete': evidence['physical_boundary_complete'] = 1
    elif defect == 'float_version': evidence['energy_algorithm_version'] = 1.
    elif defect == 'bool_version': evidence['energy_algorithm_version'] = True
    elif defect == 'missing_power': del evidence['boundary_power']
    elif defect == 'missing_side': del evidence['boundary_power']['A']
    elif defect == 'missing_face': del evidence['boundary_power']['A']['x-']
    elif defect == 'nan': evidence['boundary_power']['A']['x-'][0, 0] = np.nan
    else: evidence['boundary_power_units'] = 'invalid'
    assert_same(replace(result, boundary_fluxes=flux), stage_library)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('fine', [None, {}])
@pytest.mark.parametrize('mode', ['true_h', 'conservative_energy', 'model_h'])
def test_qualification_keeps_route_and_empty_fine_evidence(stage_library, dimension, fine, mode):
    from sjtu_tpmshx.development.tests.postprocess_tm1.test_qualification import qualified_result, required_metrics
    from sjtu_tpmshx.postprocess.api import evaluate_qualification
    result = qualified_result(dimension)
    metadata = mutable_data(result.metadata)
    metadata['thermal_mode'] = mode
    diagnostics = metadata['diagnostics']
    diagnostics['true_h_balance'] = dict(converged=True, enthalpy_clip_counts={'total': [0, 0]},
        effective_settings=dict(coupled_energy_tol=.001, equation_energy_tol=.001),
        coupled_energy_balance={'ratio': 0.}, equation_energy_balance={'ratio': 0.})
    if dimension == 2:
        diagnostics['model_h_balance'] = {name: dict(passed=True, A={'physical_boundary_complete': True},
            B={'physical_boundary_complete': True}) for name in ('main', 'fine')}
    diagnostics['convergence_detail']['richardson_ok'] = True
    result = replace(result, metadata=metadata, boundary_fluxes={**result.boundary_fluxes, 'fine': fine})
    metrics = required_metrics(dimension)
    assert native_report(result, stage_library, 'qualification', metrics=metrics) == thaw(evaluate_qualification(result, metrics))


@pytest.mark.parametrize('selection', [MetricSpec('Q', 'W/m'), MetricSpec('dP', 'Pa', 'pressure_face_v1'),
                                     MetricSpec('unknown', '1', 'future')])
def test_metric_selection_retains_versions_and_unknown_reasons(stage_library, selection):
    assert_same(result_fixture(2), stage_library, selection)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('damage', ['complete_type', 'residual_shape', 'source_shape', 'nan', 'missing_mass'])
def test_physical_query_preserves_invalid_or_missing_evidence(stage_library, dimension, damage):
    from sjtu_tpmshx.development.tests.postprocess_tm1.test_physical_balance import sample_result
    from sjtu_tpmshx.postprocess.api import evaluate_physical_balance
    result = sample_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    if damage == 'complete_type': flux['energy']['physical_boundary_complete'] = 1
    elif damage == 'residual_shape': flux['energy']['residual']['A'] = np.zeros((1,))
    elif damage == 'source_shape': flux['energy']['source_integral']['A'] = [1.]
    elif damage == 'nan': flux['mass_A'][0].flat[0] = np.nan
    else: flux['mass_A'] = None
    result = replace(result, boundary_fluxes=flux)
    try:
        expected = thaw(evaluate_physical_balance(result))
    except ValueError as error:
        with pytest.raises(ValueError) as actual:
            native_report(result, stage_library, 'physical_balance')
        assert str(actual.value) == str(error)
    else:
        assert native_report(result, stage_library, 'physical_balance') == expected


@pytest.mark.parametrize('damage', ['missing', 'captured_type', 'nonfinite', 'counts', 'hard_bounds'])
def test_independent_applicability_and_qualification_share_original_policy(stage_library, damage):
    from sjtu_tpmshx.development.tests.postprocess_tm1.test_applicability import result_with_evidence
    from sjtu_tpmshx.postprocess.api import evaluate_applicability
    result = result_with_evidence()
    metadata = mutable_data(result.metadata)
    if damage == 'missing':
        del metadata['applicability_evidence']
    else:
        sample = metadata['applicability_evidence']['final'][0]
        if damage == 'captured_type': sample['captured'] = 1
        elif damage == 'nonfinite': sample['nonfinite'] = 1
        elif damage == 'counts': sample['size'] = 0
        else: sample['constraint'] = 'hard_bounds'; sample['minimum'][0] = 99.
    result = replace(result, metadata=metadata)
    try:
        expected = thaw(evaluate_applicability(result))
    except ValueError as error:
        with pytest.raises(ValueError) as actual:
            native_report(result, stage_library, 'applicability')
        assert str(actual.value) == str(error)
    else:
        assert native_report(result, stage_library, 'applicability') == expected
    assert_same(result, stage_library)


def test_stored_result_stage_imports_no_solver_eos_or_qt(stage_library, tmp_path):
    import subprocess
    path = save_result(result_fixture(3), tmp_path / 'independent-result.h5')
    code = '''
import ctypes as ct, sys
from sjtu_tpmshx.shared.io.result_io import load_result
from sjtu_tpmshx.development.tests.result_stage_fixture import native_report
value = native_report(load_result(sys.argv[1]), ct.CDLL(sys.argv[2]))
assert value['metrics']['Q_A']['value'] == float(sys.argv[3])
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'CoolProp', 'numba', 'PySide6'):
    assert not any(key == prefix or key.startswith(prefix + '.') for key in sys.modules), prefix
'''
    expected = python_report(load_result(path))['metrics']['Q_A']['value']
    run = subprocess.run([sys.executable, '-c', code, str(path), stage_library._name, repr(expected)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize('value', [None, False, True, 0, 1, 2, 0.0, 1.0, '', 'recorded'])
@pytest.mark.parametrize('field', ['converged', 'simple_ok', 'ltne_ok', 'true_h_converged', 'solved_air', 'solved_sco2'])
def test_qualification_preserves_boolean_identity_and_false_equality(stage_library, field, value):
    from sjtu_tpmshx.development.tests.postprocess_tm1.test_qualification import qualified_result, required_metrics
    from sjtu_tpmshx.postprocess.api import evaluate_qualification
    result = qualified_result(3)
    metadata, status = mutable_data(result.metadata), mutable_data(result.run_status)
    if field == 'converged':
        status['converged'] = value
    elif field == 'simple_ok':
        metadata['diagnostics']['convergence_detail']['simple_ok'] = value
    elif field == 'ltne_ok':
        metadata['thermal_mode'] = 'temperature'
        metadata['temperature_transport'] = 'model_enthalpy_temperature_v1'
        metadata['diagnostics']['convergence_detail']['ltne_ok'] = value
    elif field == 'true_h_converged':
        metadata['thermal_mode'] = 'true_h'
        metadata['diagnostics']['true_h_balance'] = dict(converged=value,
            enthalpy_clip_counts={'total': [0, 0]}, effective_settings=dict(coupled_energy_tol=.001, equation_energy_tol=.001),
            coupled_energy_balance={'ratio': 0.}, equation_energy_balance={'ratio': 0.})
    else:
        metadata['execution_record']['sides']['A'].update(fluid=field.removeprefix('solved_'), solved=value)
    result = replace(result, metadata=metadata, run_status=status)
    metrics = required_metrics(3)
    expected = thaw(evaluate_qualification(result, metrics))
    actual = native_report(result, stage_library, 'qualification', metrics=metrics)
    assert actual == expected
    if field in ('simple_ok', 'ltne_ok'):
        assert type(actual['convergence']['gates'][field]) is type(value)
