"""Recipe identity follows the loaded native library and portable result."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.solvers.backends.cpp.model_h import NativeModelHDriver, _model_h_algorithm


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
    from sjtu_tpmshx.tests.native.test_cpp_model_h import arguments
    from sjtu_tpmshx.tests.native import test_model_h_2d, test_model_h_3d
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


@pytest.mark.parametrize('mode', ['model_h', 'temperature'])
def test_full_2d_identity_roundtrip(mode, tmp_path):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver, _pack
    from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import capture_result
    from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
    from sjtu_tpmshx.tests.native.test_full_2d import configuration
    from sjtu_tpmshx.io.result_io import save_result, load_result
    from dataclasses import replace
    config = configuration(mode=mode, outer=2, partial=False, simple_max=3000)
    config = replace(config, fluid_A=replace(config.fluid_A, T_in_K=330.),
                     fluid_B=replace(config.fluid_B, T_in_K=330.))
    case = prepare_case(config, case_id='identity-2d')
    cfg, prepared = build_execution_inputs(case)
    driver = NativeFull2DDriver(library_path('TPMSHX_NATIVE_SOLVER_LIBRARY'))
    shape, arrays, settings = _pack(cfg, prepared, driver.table_directory)
    settings.thermal_iterations = settings.outer_iterations = 1
    settings.pressure_shooting = 0
    raw = driver.solve(shape, arrays, settings)
    assert raw['main']['mode'] == mode
    expected = (_model_h_algorithm(driver.library, 2) if mode == 'model_h'
                else 'model_h_tface_sou_fou_strict_v3')
    assert raw['native_metadata'] == dict(abi=2, algorithm=expected, red_black=False)
    result = capture_result(case, cfg, prepared, raw)
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
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    cfg, p = prepared('air-air', directions=(0, 3), counts=counts, max_iter_simple=1, **options)
    cfg['_environment'] = dict(cfg.get('_environment', {}), TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None)
    p['max_outer'] = p['ltne_max_iter'] = 1
    driver = NativeFull3DDriver(library_path('TPMSHX_NATIVE_SOLVER_LIBRARY'))
    raw = driver.run_prepared(cfg, p)
    assert raw['mode'] == ('model_h' if route == 'model_h' else 'temperature')
    expected = (_model_h_algorithm(driver.library, 3) if route == 'model_h' else
                {'cc2d': 'model_h_tface_sou_fou_strict_v3',
                 'cc3d': 'model_h_tface_sou_sou_strict_v3',
                 'staggered': 'shared_fv_staggered_tminmod_picard_v1'}[route])
    assert raw['native_metadata'] == dict(abi=1, algorithm=expected, red_black=False)


def test_full_3d_portable_identity_roundtrip(monkeypatch, tmp_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver, run_case
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import case, control
    from sjtu_tpmshx.io.result_io import save_result, load_result
    original = NativeFull3DDriver.run_prepared
    def bounded(self, cfg, p, control):
        cfg = dict(cfg, max_iter_simple=1)
        cfg['_environment'] = dict(cfg.get('_environment', {}), TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None)
        p = dict(p, max_outer=1, ltne_max_iter=1)
        return original(self, cfg, p, control)
    monkeypatch.setattr(NativeFull3DDriver, 'run_prepared', bounded)
    result = run_case(case('air-air', cap=2), control(library_path('TPMSHX_NATIVE_SOLVER_LIBRARY')))
    assert dict(result.metadata['native']) == dict(abi=1, algorithm='shared_fv_model_h_3d_compensated_v1', red_black=False)
    path = tmp_path/'identity-3d.h5'
    save_result(result, path)
    assert load_result(path).metadata['native'] == result.metadata['native']
