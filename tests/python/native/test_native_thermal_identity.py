"""Recipe identity follows the loaded native library and portable result."""
import os
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.cpp_interface.solver_library.model_h import NativeModelHDriver, _model_h_algorithm


def library_path(variable):
    value = os.environ.get(variable)
    if value is None:
        pytest.skip(f'explicit candidate library required: {variable}')
    path = Path(value)
    assert path.is_absolute() and path.is_file(), path
    return path


@pytest.mark.parametrize('dimension', [2, 3])
def test_model_h_missing_or_null_identity_is_explicit(dimension):
    with pytest.raises(ValueError, match='lacks tpmshx_model_h_algorithm_v1'):
        _model_h_algorithm(SimpleNamespace(), dimension)
    def query(value):
        assert value == dimension
        return None
    with pytest.raises(ValueError, match='no model-h algorithm'):
        _model_h_algorithm(SimpleNamespace(tpmshx_model_h_algorithm_v1=query), dimension)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('red_black', [False, True])
def test_model_h_zero_budget_reports_loaded_identity(dimension, red_black):
    from tests.python.native.test_cpp_model_h import arguments
    from tests.python.native import test_model_h_2d, test_model_h_3d
    driver = NativeModelHDriver(library_path('TPMSHX_MODEL_H_PUBLIC_LIBRARY'))
    c = (test_model_h_2d if dimension == 2 else test_model_h_3d).case()
    c.update(maxit=0, rb=red_black)
    info = driver(**arguments(c))[3]
    expected = ('shared_fv_model_h_2d_defect_v1' if dimension == 2
                else 'shared_fv_model_h_3d_compensated_v1')
    assert _model_h_algorithm(driver.library, dimension) == expected
    assert info['native_metadata'] == dict(abi=1, algorithm=expected, red_black=red_black)
    assert info['iterations'] == 0 and not info['converged']
    with pytest.raises(ValueError, match='no model-h algorithm'):
        _model_h_algorithm(driver.library, 0)


def stage_control():
    from sjtu_tpmshx.run_control.module_ports import RunControl
    from tests.python.native.stage_interception import TABLES
    return RunControl(backend='cpp', native_library=str(library_path('TPMSHX_NATIVE_SOLVER_LIBRARY')),
                      native_table_directory=str(TABLES))


@pytest.mark.parametrize('mode', ['model_h', 'temperature'])
def test_full_2d_identity_roundtrip(mode, tmp_path):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.cpp_interface.full_2d_stage import StageDriver
    from tests.python.native.stage_interception import run_stage
    from tests.python.native.test_full_2d import configuration
    from sjtu_tpmshx.file_io.result_io import save_result, load_result
    config = configuration(mode=mode, outer=2, partial=False, simple_max=3000)
    config = replace(config, fluid_A=replace(config.fluid_A, T_in_K=330.),
                     fluid_B=replace(config.fluid_B, T_in_K=330.))
    case = prepare_case(config, case_id='identity-2d')
    control = stage_control()
    stage = run_stage(case, control)
    raw, result = stage.native, stage.result
    assert raw['main']['mode'] == mode
    expected = (_model_h_algorithm(StageDriver(control.native_library).library, 2) if mode == 'model_h'
                else 'model_h_tface_sou_fou_strict_v3')
    assert raw['native_metadata'] == dict(abi=2, algorithm=expected, red_black=False)
    assert dict(result.metadata['native']) == raw['native_metadata']
    path = tmp_path/'identity.h5'
    save_result(result, path)
    assert dict(load_result(path).metadata['native']) == raw['native_metadata']


@pytest.mark.parametrize('route,counts,options', [
    ('model_h', (4, 4, 4), {}),
    ('cc2d', (4, 4, 1), {'variable_rho_cp': False}),
    ('cc3d', (4, 4, 4), {'variable_rho_cp': False, 'conservative_ltne': False, 'force_cc_ltne': True}),
    ('staggered', (4, 4, 4), {'variable_rho_cp': False, 'conservative_ltne': True}),
])
def test_full_3d_identity_uses_executed_route(route, counts, options):
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    from tests.python.native.stage_interception import run_stage
    from tests.python.native.test_cpp_full_3d import saved_case
    prepared = saved_case('air-air', directions=(0, 3), counts=counts, max_iter_simple=1,
                          environment=dict(TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None),
                          prepared_values=dict(max_outer=1, ltne_max_iter=1), **options)
    control = stage_control()
    raw = run_stage(prepared, control).native
    assert raw['mode'] == ('model_h' if route == 'model_h' else 'temperature')
    _, library, _, _ = full_3d_stage.open_library(control.native_library, None)
    expected = (_model_h_algorithm(library, 3) if route == 'model_h' else
                {'cc2d': 'model_h_tface_sou_fou_strict_v3',
                 'cc3d': 'model_h_tface_sou_sou_strict_v3',
                 'staggered': 'shared_fv_staggered_tminmod_picard_v1'}[route])
    assert raw['native_metadata'] == dict(abi=2, algorithm=expected, red_black=False)


def test_full_3d_portable_identity_roundtrip(tmp_path):
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    from tests.python.native.test_cpp_full_3d import case, control
    from sjtu_tpmshx.file_io.result_io import save_result, load_result
    prepared = case('air-air', cap=2)
    params = prepared.parameters
    prepared = replace(prepared, parameters=dict(params, max_iter_simple=1,
        _environment=dict(params['_environment'], TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None),
        prepared=dict(params['prepared'], max_outer=1, ltne_max_iter=1)))
    result = run_case(prepared, control(library_path('TPMSHX_NATIVE_SOLVER_LIBRARY')))
    assert dict(result.metadata['native']) == dict(abi=2, algorithm='shared_fv_model_h_3d_compensated_v1', red_black=False)
    path = tmp_path/'identity-3d.h5'
    save_result(result, path)
    assert load_result(path).metadata['native'] == result.metadata['native']
