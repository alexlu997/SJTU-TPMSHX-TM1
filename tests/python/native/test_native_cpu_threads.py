"""Thread budgets preserve complete numerical results."""
from dataclasses import replace

import pytest

from tests.python.native import test_cpp_full_3d as spatial
from tests.python.native.test_run_recovery import configuration, same_result
from tm1.compute import compute

native_path = spatial.native_path


def config(dimension, algorithm):
    value = configuration('2d-' + algorithm if dimension == 2 else '3d-sco2-water')
    return replace(value, solver=replace(value.solver, enthalpy_algorithm=algorithm))


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('algorithm', ['temperature_sou'])
@pytest.mark.parametrize('threads', [2, 8])
def test_complete_serial_and_parallel_results_are_exact(native_path, dimension, algorithm, threads):
    assert_complete_thread_equivalence(native_path, config(dimension, algorithm), threads)


@pytest.mark.parametrize('pair', ['air-air', 'air-water', 'water-air', 'water-water'])
@pytest.mark.parametrize('threads', [2, 8])
def test_complete_model_h_thread_results_are_exact(native_path, pair, threads):
    assert_complete_thread_equivalence(native_path, configuration('3d-' + pair), threads)


def assert_complete_thread_equivalence(native_path, value, threads):
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
