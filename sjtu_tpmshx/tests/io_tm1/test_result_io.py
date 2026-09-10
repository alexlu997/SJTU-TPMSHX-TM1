"""Result state and unavailable metrics survive real persistent files."""
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.io.metrics_io import load_metrics, save_metrics
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case


def test_nonconverged_result_is_preserved_and_cancelled_archive_rejected(tmp_path):
    result = FieldResult('result', 'synthetic', 'fixture', grid=sample_case().grid,
        fields={'Ta': np.full((2, 2), 310.)},
        field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw last thermal return')},
        run_status={'execution': 'completed', 'converged': False},
        metadata={'diagnostic': float('nan'), 'warnings': ('not converged',)})
    path = tmp_path / 'results.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert loaded.run_status['converged'] is False
    assert np.isnan(loaded.metadata['diagnostic'])
    np.testing.assert_array_equal(loaded.fields['Ta'], result.fields['Ta'])
    with pytest.raises(ValueError, match='completed'):
        save_result(replace(result, run_status={'execution': 'cancelled', 'converged': False}), path)
    assert load_result(path).run_status['execution'] == 'completed'


def test_metrics_strict_json_and_unknown_version(tmp_path):
    result = PerformanceResult('perf', 'result', {
        'Q': MetricValue(12., MetricSpec('Q', 'W/m')),
        'mass': MetricValue(None, MetricSpec('mass', 'kg/m'), 'insufficient_data', 'solid density absent')})
    path = tmp_path / 'metrics.json'
    save_metrics(result, path)
    assert load_metrics(path) == result
    data = json.loads(path.read_text())
    assert data['metrics']['mass']['value'] is None
    data['schema_version'] = 'future'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='schema'):
        load_metrics(path)
