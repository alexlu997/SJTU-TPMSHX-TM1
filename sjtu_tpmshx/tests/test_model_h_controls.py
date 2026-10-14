"""Explicit integral-model controls retain their meaning through preparation."""
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.preprocess.three_d.preparation import _parse_geometry_inputs_3d_cfg


STRICT = dict(model_h_max_iterations=24000, model_h_temperature_tol_K=1e-5,
              model_h_q_relative_tol=1e-8)


@pytest.mark.parametrize('dimension', [2, 3])
def test_model_h_controls_survive_config_and_preparation(tmp_path, dimension):
    cfg = ComputeConfig()
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
        parsed = _parse_geometry_inputs_3d_cfg(restored)
        assert {key: parsed[key] for key in STRICT} == STRICT


def test_unset_model_h_controls_preserve_route_resolution():
    cfg = ComputeConfig()
    cfg.geometry.Lz_m = .012
    cfg.solver.Nz = 3
    assert all(getattr(cfg.solver, key) is None for key in STRICT)
    parsed = _parse_geometry_inputs_3d_cfg(cfg)
    assert all(key not in parsed for key in STRICT)


@pytest.mark.parametrize('key,value', [
    ('model_h_max_iterations', 0), ('model_h_max_iterations', True),
    ('model_h_max_iterations', 4.5), ('model_h_temperature_tol_K', 0.),
    ('model_h_temperature_tol_K', float('nan')), ('model_h_temperature_tol_K', True),
    ('model_h_q_relative_tol', -1.), ('model_h_q_relative_tol', float('inf')),
])
def test_invalid_model_h_control_is_rejected_before_preparation(key, value):
    cfg = ComputeConfig()
    setattr(cfg.solver, key, value)
    with pytest.raises(ValueError, match=key):
        cfg.validate_static_inputs()


@pytest.mark.parametrize('dimension,backend,mode', [(2, 'python', 'full'), (3, 'python', 'full'),
                                                   (2, 'cpp', 'quick_design')])
def test_unsupported_backend_is_rejected_before_dispatch(dimension, backend, mode):
    from types import SimpleNamespace
    from sjtu_tpmshx.domain.module_ports import RunControl
    from sjtu_tpmshx.solvers.api import run_case
    settings = dict(STRICT)
    case = SimpleNamespace(grid={'dimension': dimension}, metadata={'mode': mode},
                           parameters={'run_settings': {'solver': settings}} if dimension == 2 else settings)
    with pytest.raises(ValueError, match='model-h controls require full compute with backend=cpp'):
        run_case(case, RunControl(backend=backend))


def test_native_iteration_records_are_owned_and_preserve_call_budgets():
    import ctypes as ct
    from sjtu_tpmshx.solvers.backends.cpp.model_h import (
        _IterationRecord, _IterationRecords, _copy_iteration_records, _iteration_options,
    )
    rows = (_IterationRecord * 2)(
        _IterationRecord(0, 0, 0, 250, 250, 1e-5, 1e-8, 1000),
        _IterationRecord(0, 1, 0, 125, 250, 1e-5, 1e-8, 1000))
    def query(_, out):
        ct.cast(out, ct.POINTER(_IterationRecords))[0] = _IterationRecords(rows, len(rows))
        return 0
    copied = _copy_iteration_records(query, ct.c_int())
    rows[0].temperature_tolerance = 99.
    assert copied['records'][0]['settings']['temperature_update_tolerance_K'] == 1e-5
    assert [row['settings']['max_iterations'] for row in copied['records']] == [250, 125]
    options = _iteration_options(STRICT)
    assert (options.max_iterations, options.temperature_tolerance, options.q_relative_tolerance) == (24000, 1e-5, 1e-8)
    assert _iteration_options({}) is None
    with pytest.raises(ValueError, match='model_h_max_iterations'):
        _iteration_options({'model_h_max_iterations': ct.c_size_t(-1).value + 1})
    rows[0].temperature_tolerance = float('nan')
    with pytest.raises(RuntimeError, match='invalid native model-h iteration record'):
        _copy_iteration_records(query, ct.c_int())
