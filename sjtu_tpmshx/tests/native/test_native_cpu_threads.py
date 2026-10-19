"""Thread budgets preserve complete numerical results and retained libraries."""
from dataclasses import replace

import pytest

from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs as planar_inputs
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs as spatial_inputs
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.tests.native import test_cpp_full_3d as spatial
from sjtu_tpmshx.tests.native.test_run_recovery import configuration, same_result
from sjtu_tpmshx.workflows.compute import compute

native_path = spatial.native_path


def config(dimension, algorithm):
    value = configuration('2d-' + algorithm if dimension == 2 else '3d-sco2-water')
    return replace(value, solver=replace(value.solver, enthalpy_algorithm=algorithm))


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('algorithm', ['temperature_sou'])
@pytest.mark.parametrize('threads', [2, 8])
def test_complete_serial_and_parallel_results_are_exact(native_path, dimension, algorithm, threads):
    value = config(dimension, algorithm)
    serial = replace(spatial.control(native_path), cpu_threads=1)
    parallel = replace(serial, cpu_threads=threads)
    _, expected, expected_metrics = compute(value, case_id='thread-limits', control=serial)
    _, actual, actual_metrics = compute(value, case_id='thread-limits', control=parallel)
    for result, control in ((expected, serial), (actual, parallel)):
        assert dict(result.metadata['runtime_resources']) == dict(
            cpu_thread_limit=control.native_cpu_threads(), requested_cpu_threads=control.cpu_threads,
            policy='native_cpu_limit_v1')
    actual = replace(actual, metadata={k:v for k,v in actual.metadata.items() if k != 'runtime_resources'})
    expected = replace(expected, metadata={k:v for k,v in expected.metadata.items() if k != 'runtime_resources'})
    same_result(actual, expected, actual_metrics, expected_metrics)


@pytest.mark.parametrize('dimension', [2, 3])
def test_retained_library_rejects_an_explicit_unsupported_budget(native_path, monkeypatch, dimension):
    driver = (NativeFull2DDriver if dimension == 2 else NativeFull3DDriver)(native_path)
    original = driver.library
    symbol = 'tpmshx_solve_full_2d_v6' if dimension == 2 else 'tpmshx_solve_full_3d_v5'
    class RetainedLibrary:
        def __getattr__(self, name):
            if name == symbol:
                raise AttributeError(name)
            return getattr(original, name)
    monkeypatch.setattr(driver, 'library', RetainedLibrary())
    prepared = prepare_case(config(dimension, 'temperature_sou'), case_id='retained-runtime')
    inputs = (planar_inputs if dimension == 2 else spatial_inputs)(prepared)
    with pytest.raises(ValueError, match='retained native library has no CPU thread limit'):
        driver.run_prepared(*inputs, replace(spatial.control(native_path), cpu_threads=1))
