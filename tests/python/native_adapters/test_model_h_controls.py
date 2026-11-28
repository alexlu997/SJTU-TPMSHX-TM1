"""Explicit integral-model controls retain their meaning through preparation."""
import pytest

from tm1.data_types.compute_config import ComputeConfig
from tm1.preprocess.api import prepare_case


STRICT = dict(model_h_max_iterations=24000, model_h_temperature_tol_K=1e-5,
              model_h_q_relative_tol=1e-8)


@pytest.mark.parametrize('dimension', [2, 3])
def test_model_h_controls_survive_config_and_preparation(tmp_path, dimension):
    cfg = ComputeConfig()
    cfg.solver.Nx, cfg.solver.Ny = 4, 4
    if dimension == 3:
        cfg.geometry.Lz_m = .012
        cfg.solver.Nz = 3
    for key, value in STRICT.items():
        setattr(cfg.solver, key, value)
    cfg.validate_static_inputs()
    path = tmp_path / 'model-h.json'
    cfg.to_json(path)
    restored = ComputeConfig.from_json(path)
    assert {key: getattr(restored.solver, key) for key in STRICT} == STRICT
    if dimension == 3:
        parsed = prepare_case(restored, case_id='controls').parameters
        assert {key: parsed[key] for key in STRICT} == STRICT


def test_unset_model_h_controls_preserve_route_resolution():
    cfg = ComputeConfig()
    cfg.solver.Nx, cfg.solver.Ny = 4, 4
    cfg.geometry.Lz_m = .012
    cfg.solver.Nz = 3
    assert all(getattr(cfg.solver, key) is None for key in STRICT)
    parsed = prepare_case(cfg, case_id='controls').parameters
    assert all(key not in parsed for key in STRICT)


@pytest.mark.parametrize('key,value', [
    ('model_h_max_iterations', 0), ('model_h_max_iterations', True),
    ('model_h_max_iterations', 4.5), ('model_h_temperature_tol_K', 0.),
    ('model_h_temperature_tol_K', float('nan')), ('model_h_temperature_tol_K', True),
    ('model_h_q_relative_tol', -1.), ('model_h_q_relative_tol', float('inf')),
])
def test_invalid_model_h_control_is_rejected_before_preparation(key, value):
    cfg = ComputeConfig()
    cfg.solver.Nx, cfg.solver.Ny = 4, 4
    setattr(cfg.solver, key, value)
    with pytest.raises(ValueError, match=key):
        cfg.validate_static_inputs()


@pytest.mark.parametrize('dimension,backend,mode', [(2, 'python', 'full'), (3, 'python', 'full'),
                                                   (2, 'cpp', 'quick_design')])
def test_unsupported_backend_is_rejected_before_dispatch(dimension, backend, mode):
    from types import SimpleNamespace
    from tm1.run_control.module_ports import RunControl
    from tm1.solvers.api import run_case
    settings = dict(STRICT)
    case = SimpleNamespace(grid={'dimension': dimension}, metadata={'mode': mode},
                           parameters={'run_settings': {'solver': settings}} if dimension == 2 else settings)
    message = ('Python numerical backend has been retired' if backend == 'python' else
               'model-h controls require full compute with backend=cpp')
    with pytest.raises(ValueError, match=message):
        run_case(case, RunControl(backend=backend))


def test_native_iteration_options_preserve_call_budgets():
    import ctypes as ct
    from tm1.cpp_interface.solver_library._thermal_abi import _iteration_options
    options = _iteration_options(STRICT)
    assert (options.max_iterations, options.temperature_tolerance, options.q_relative_tolerance) == (24000, 1e-5, 1e-8)
    assert _iteration_options({}) is None
    with pytest.raises(ValueError, match='model_h_max_iterations'):
        _iteration_options({'model_h_max_iterations': ct.c_size_t(-1).value + 1})
