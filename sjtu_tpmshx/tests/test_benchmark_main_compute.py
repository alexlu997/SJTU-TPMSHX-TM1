"""A successful solve is not a successful end-to-end performance sample."""
from contextlib import nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.runs.tools import benchmark_main_compute as benchmark
from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case


@pytest.mark.parametrize('failure', ['save_result', 'load_result'])
@pytest.mark.parametrize('backend', ['python', 'cpp'])
def test_file_failure_disqualifies_sample_but_preserves_solve_status(tmp_path, monkeypatch, failure, backend):
    from sjtu_tpmshx.preprocess import api as preparation
    from sjtu_tpmshx.solvers import api as solving
    from sjtu_tpmshx.postprocess import api as evaluation
    from sjtu_tpmshx.controllers import module_adapter
    from sjtu_tpmshx.io import result_io

    monkeypatch.setattr(preparation, 'prepare_case',
                        lambda cfg, case_id: replace(sample_case(), case_id=case_id))
    control = RunControl(backend=backend, native_library='/host/solver' if backend == 'cpp' else None)
    def run(case, actual_control):
        assert actual_control is control
        return FieldResult('synthetic-result', case.case_id, backend, grid=case.grid,
                           run_status={'execution': 'completed', 'converged': True})
    monkeypatch.setattr(solving, 'run_case', run)
    metrics = {key: MetricValue(1., MetricSpec(key, unit)) for key, unit in (
        ('Q', 'W/m'), ('dP_A', 'Pa'), ('dP_B', 'Pa'), ('T_out_A', 'K'),
        ('T_out_B', 'K'), ('mass_flow_A', 'kg/(m s)'), ('mass_flow_B', 'kg/(m s)'))}
    monkeypatch.setattr(evaluation, 'evaluate', lambda result:
                        PerformanceResult('metrics', result.result_id, metrics))
    monkeypatch.setattr(module_adapter, 'to_compute_result', lambda *args: SimpleNamespace(
        Q_W=1., dP_A_Pa=1., dP_B_Pa=1., T_out_A_K=1., T_out_B_K=1.,
        diagnostics={'envelope_valid': True}, residuals={}, warnings=[]))
    monkeypatch.setattr(benchmark, 'sample_rss', lambda samples: nullcontext())
    def observe(dimension, calls):
        assert backend == 'python'
        return nullcontext()
    monkeypatch.setattr(benchmark, 'observe_solver', observe)
    def fail(*args):
        raise OSError(f'{failure} denied')
    monkeypatch.setattr(result_io, failure, fail)
    row = benchmark.run_one({'id': 'file-failure', 'config': {}}, tmp_path,
                            sample_kind='synthetic-check', control=control)
    assert row['message'] == f'{failure} denied'
    assert row['software_qualified'] is True
    assert row['execution'] == 'failed'
    saved = json.loads((tmp_path / row['run_id'] / 'measurement.json').read_text())
    assert 'optimizer' not in saved['config']
    assert saved['qualified_for_performance'] is False
    assert saved['backend'] == backend
