"""A successful solve is not a successful end-to-end performance sample."""
from contextlib import nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from tm1.data_types.field_result import FieldResult
from tm1.run_control.module_ports import RunControl
from tm1.data_types.metric_spec import MetricSpec
from tm1.data_types.performance_result import MetricValue, PerformanceResult
from tm1.development.runs.tools import benchmark_main_compute as benchmark
from tests.python.io_tm1.io_support import sample_case


@pytest.mark.parametrize('failure', [None, 'save_result', 'load_result'])
@pytest.mark.parametrize('eligible', [True, False, None])
def test_sample_uses_common_verdict_and_keeps_file_failures(tmp_path, monkeypatch, failure, eligible):
    from tm1.preprocess import api as preparation
    from tm1.solvers import api as solving
    from tm1.postprocess import api as evaluation
    from tm1.applications import result_adapter as module_adapter
    from tm1.file_io import result_io

    monkeypatch.setattr(preparation, 'prepare_case',
                        lambda cfg, case_id: replace(sample_case(), case_id=case_id))
    control = RunControl(native_library='/host/solver')
    def run(case, actual_control):
        assert actual_control is control
        return FieldResult('synthetic-result', case.case_id, 'cpp', grid=case.grid,
                           run_status={'execution': 'completed', 'converged': True})
    monkeypatch.setattr(solving, 'run_case', run)
    metrics = {key: MetricValue(1., MetricSpec(key, unit)) for key, unit in (
        ('Q', 'W/m'), ('dP_A', 'Pa'), ('dP_B', 'Pa'), ('T_out_A', 'K'),
        ('T_out_B', 'K'), ('mass_flow_A', 'kg/(m s)'), ('mass_flow_B', 'kg/(m s)'))}
    monkeypatch.setattr(evaluation, 'evaluate', lambda result:
                        PerformanceResult('metrics', result.result_id, metrics,
                            dict(definition='result_qualification_v1', source_result_id=result.result_id,
                                 design=dict(eligible=eligible))))
    monkeypatch.setattr(module_adapter, 'to_compute_result', lambda *args: SimpleNamespace(
        Q_W=1., dP_A_Pa=1., dP_B_Pa=1., T_out_A_K=1., T_out_B_K=1.,
        diagnostics={'envelope_valid': True}, residuals={}, warnings=[]))
    monkeypatch.setattr(benchmark, 'sample_rss', lambda samples: nullcontext())
    def fail(*args):
        raise OSError(f'{failure} denied')
    if failure is not None:
        monkeypatch.setattr(result_io, failure, fail)
    row = benchmark.run_one({'id': 'file-failure', 'config': {}}, tmp_path,
                            sample_kind='synthetic-check', control=control)
    if failure is not None:
        assert row['message'] == f'{failure} denied'
    assert row['qualification']['design']['eligible'] is eligible
    assert row['run_status']['converged'] is True
    assert row['execution'] == ('failed' if failure else 'completed')
    saved = json.loads((tmp_path / row['run_id'] / 'measurement.json').read_text())
    assert 'optimizer' not in saved['config']
    assert saved['qualified_for_performance'] is (failure is None and eligible is True)
    assert saved['qualification']['design']['eligible'] is eligible
    assert saved['backend'] == 'cpp'
