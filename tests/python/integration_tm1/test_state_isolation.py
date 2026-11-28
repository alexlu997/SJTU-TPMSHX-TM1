"""Real 2D/3D public solves share a process, but never per-run state."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from threading import Barrier

import numpy as np
import pytest

from tm1.run_control.cancellation import CancelledError
from tm1.run_control.module_ports import RunControl
from tm1.data_types.portable_data import mutable_data
from tm1.run_control.run_warnings import record_warning
from tm1.postprocess.api import evaluate
from tm1.preprocess.api import prepare_case
from tm1.solvers.api import run_case
from tests.python.integration_tm1.integration_support import baseline_config
from tests.python.integration_tm1.test_public_api import assert_slots
from tests.python.cases_3d import small_air_config


@pytest.mark.slow
def test_real_parallel_cases_and_cancelled_peer():
    cases = [prepare_case(config, case_id=f'isolation-{dimension}')
             for dimension, config in ((2, baseline_config()), (3, small_air_config()))]
    snapshots = [{field.name: mutable_data(getattr(case, field.name))
                  for field in fields(case)} for case in cases]
    reference = [run_case(case) for case in cases]
    rendezvous = Barrier(3, timeout=60)
    progress = [[], [], []]

    def solve(index):
        first = True

        def cancel_check():
            nonlocal first
            if first:
                first = False
                # Exercise the run-local warning registry with the same key
                # in all three real executions, including the cancelled one.
                assert record_warning('isolation-probe', f'isolation notice {index}')
                rendezvous.wait()
            return index == 2

        return run_case(cases[index % 2], RunControl(
            cancel_check=cancel_check, progress=progress[index].append))

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(solve, index) for index in range(3)]
        with pytest.raises(CancelledError):
            futures[2].result(timeout=120)
        actual = [future.result(timeout=600) for future in futures[:2]]

    assert progress[2] == []
    for index, (result, expected) in enumerate(zip(actual, reference)):
        assert progress[index] and progress[index][-1] == 100
        assert result.run_status['converged'] is True
        for name in ('fields', 'boundary_fluxes', 'pressure_evidence', 'run_status'):
            assert_slots(getattr(result, name), getattr(expected, name))
        notices = result.metadata['diagnostics']['warnings_list']
        assert f'isolation notice {index}' in notices
        assert all(f'isolation notice {other}' not in notices
                   for other in range(3) if other != index)
        assert tuple(n for n in notices if n != f'isolation notice {index}') == expected.metadata['diagnostics']['warnings_list']
        metrics, baseline = evaluate(result).metrics, evaluate(expected).metrics
        for name in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B'):
            assert metrics[name].spec == baseline[name].spec
            assert metrics[name].status == baseline[name].status == 'available'
            np.testing.assert_allclose(metrics[name].value, baseline[name].value,
                                       rtol=1e-10, atol=1e-10)
        for field in fields(cases[index]):
            assert_slots(getattr(cases[index], field.name), snapshots[index][field.name])
        for name, value in result.fields.items():
            if isinstance(value, np.ndarray) and np.shares_memory(value, expected.fields[name]):
                # Fixed design inputs can share immutable buffers between runs.
                assert any(isinstance(source, np.ndarray) and np.shares_memory(value, source)
                           for source in cases[index].design_fields.values()), name
                assert not value.flags.writeable and not expected.fields[name].flags.writeable
                with pytest.raises(ValueError):
                    value.setflags(write=True)
