"""Strict JSON metrics with explicit unavailable values and definitions."""
from dataclasses import asdict
import json
from pathlib import Path

from sjtu_tpmshx.domain.case_data import SCHEMA_VERSION
from .text_file import write_text
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult


def save_metrics(result, path):
    payload = dict(schema_version=SCHEMA_VERSION, record_kind='PerformanceResult',
                   result_id=result.result_id, source_result_id=result.source_result_id,
                   metrics={key: asdict(value) for key, value in result.metrics.items()})
    return write_text(path, json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + '\n')


def load_metrics(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if set(payload) != {'schema_version', 'record_kind', 'result_id', 'source_result_id', 'metrics'}:
        raise ValueError('invalid metrics record fields')
    if payload['schema_version'] != SCHEMA_VERSION or payload['record_kind'] != 'PerformanceResult':
        raise ValueError('unsupported metrics schema')
    metrics = {}
    for key, value in payload['metrics'].items():
        value = dict(value)
        value['spec'] = MetricSpec(**value['spec'])
        metrics[key] = MetricValue(**value)
    return PerformanceResult(payload['result_id'], payload['source_result_id'], metrics)
