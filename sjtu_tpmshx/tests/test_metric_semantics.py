"""Metric meaning survives object, JSON, display and optimization boundaries."""
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.controllers.module_adapter import to_compute_result
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.io.metrics_io import load_metrics, save_metrics
from sjtu_tpmshx.optimization.multi_condition import aggregate_multi_condition
from sjtu_tpmshx.tests.test_module_result_mapping import _synthetic_3d_results
from sjtu_tpmshx.tests.test_multi_condition import _row


@pytest.mark.parametrize('name,unit', [
    ('dP_A', 'kPa'), ('T_out_A', 'degC'), ('Q_B', 'kW'),
    ('mass_flow_B', 'kg/h'), ('energy_imbalance_rel', '%'),
])
def test_side_metric_units_are_checked_at_construction(name, unit):
    with pytest.raises(ValueError, match='must use'):
        MetricSpec(name, unit)


@pytest.mark.parametrize('key,spec', [
    ('Q_A', MetricSpec('Q_B', 'W')),
    ('dP_A', MetricSpec('T_out', 'K')),
    ('custom', MetricSpec('unrelated', '1')),
])
def test_mapping_key_cannot_change_metric_identity(key, spec):
    with pytest.raises(ValueError, match='metric.*name'):
        PerformanceResult('metrics', 'native', {key: MetricValue(1., spec)})


@pytest.mark.parametrize('name,change', [
    ('dP_A', {'unit': 'kPa'}),
    ('T_out_A', {'unit': 'degC'}),
    ('dP_A', {'name': 'dP_B'}),
])
def test_external_json_cannot_relabel_values_for_gui(tmp_path, name, change):
    native, performance = _synthetic_3d_results()
    path = save_metrics(performance, tmp_path / 'metrics.json')
    data = json.loads(path.read_text())
    data['metrics'][name]['spec'].update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='must use|metric.*name'):
        to_compute_result(native, load_metrics(path))


def test_family_and_side_names_roundtrip_without_changing_fields(tmp_path):
    native, performance = _synthetic_3d_results()
    aliases = {'Q_A': 'Q', 'Q_B': 'Q', 'dP_A': 'dP', 'dP_B': 'dP',
               'T_out_A': 'T_out', 'T_out_B': 'T_out'}
    metrics = {name: replace(metric, spec=replace(metric.spec, name=aliases.get(name, name)))
               for name, metric in performance.metrics.items()}
    metrics['PEC'] = MetricValue(None, MetricSpec('PEC', '1', 'custom_v1'),
                                 'unsupported', 'reference definition absent')
    loaded = load_metrics(save_metrics(replace(performance, metrics=metrics), tmp_path / 'metrics.json'))
    actual, expected = to_compute_result(native, loaded), to_compute_result(native, performance)
    for name in ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K'):
        assert getattr(actual, name) == getattr(expected, name)
    for name in ('L_mm', 't_mm', 'Ta', 'Tb', 'Ts', 'P_fA', 'P_fB'):
        np.testing.assert_array_equal(actual.fields[name], expected.fields[name])
    assert loaded.metrics['PEC'] == metrics['PEC']


def test_existing_mass_flow_unit_spelling_is_preserved(tmp_path):
    metric = MetricValue(1., MetricSpec('mass_flow', 'kg/(m s)'))
    performance = PerformanceResult('metrics', 'native-2d', {'mass_flow_A': metric})
    loaded = load_metrics(save_metrics(performance, tmp_path / 'metrics.json'))
    assert loaded.metrics['mass_flow_A'] == metric


@pytest.mark.parametrize('name', ['T_out_A', 'Q_B'])
def test_historical_definition_is_readable_but_not_current_gui(tmp_path, name):
    native, performance = _synthetic_3d_results()
    metrics = dict(performance.metrics)
    metrics[name] = replace(metrics[name], spec=replace(metrics[name].spec,
                                                       definition_version='three_module_v1'))
    loaded = load_metrics(save_metrics(replace(performance, metrics=metrics), tmp_path / 'old.json'))
    assert loaded.metrics[name] == metrics[name]
    with pytest.raises(ValueError, match='re-evaluate native results'):
        to_compute_result(native, loaded)


def test_gui_cannot_use_per_depth_side_duty_in_total_result():
    native, performance = _synthetic_3d_results()
    metrics = dict(performance.metrics)
    metrics['Q_B'] = replace(metrics['Q_B'], spec=replace(metrics['Q_B'].spec, unit='W/m'))
    with pytest.raises(ValueError, match='unit.*dimension'):
        to_compute_result(native, replace(performance, metrics=metrics))


def test_current_unavailable_temperature_keeps_status_and_reason(tmp_path):
    native, performance = _synthetic_3d_results()
    metrics = dict(performance.metrics)
    metrics['T_out_B'] = replace(metrics['T_out_B'], value=None,
                                status='insufficient_data', reason='outlet mass flux absent')
    loaded = load_metrics(save_metrics(replace(performance, metrics=metrics), tmp_path / 'partial.json'))
    actual = to_compute_result(native, loaded)
    assert np.isnan(actual.T_out_B_K)
    assert actual.metadata['metric_reasons']['T_out_B'] == 'outlet mass flux absent'
    assert any('insufficient_data' in warning for warning in actual.warnings)


@pytest.mark.parametrize('name', ['Q_B', 'dP_A'])
def test_matching_wrong_definitions_cannot_enter_optimization(name):
    condition, field, performance = _row('low')
    metrics = dict(performance.metrics)
    metrics[name] = replace(metrics[name], spec=replace(metrics[name].spec,
                                                       definition_version='three_module_v1'))
    row = (condition, field, replace(performance, metrics=metrics))
    with pytest.raises(ValueError, match='re-evaluate native results'):
        aggregate_multi_condition(['low'], [row], [row])


def test_optimization_accepts_equivalent_family_names():
    condition, field, performance = _row('low')
    metrics = dict(performance.metrics)
    metrics['Q_B'] = replace(metrics['Q_B'], spec=replace(metrics['Q_B'].spec, name='Q'))
    metrics['dP_A'] = replace(metrics['dP_A'], spec=replace(metrics['dP_A'].spec, name='dP_A'))
    actual = aggregate_multi_condition(['low'], [_row('low')],
        [(condition, field, replace(performance, metrics=metrics))])
    assert actual == {'heat_gain_percent': 0., 'pressure_ratio': 1.}


@pytest.mark.parametrize('dimension,unit', [(2, 'W'), (3, 'W/m')])
def test_optimization_checks_duty_unit_against_declared_dimension(dimension, unit):
    condition, field, performance = _row('low')
    field = replace(field, grid={'dimension': dimension})
    metrics = dict(performance.metrics)
    metrics['Q_B'] = replace(metrics['Q_B'], spec=replace(metrics['Q_B'].spec, unit=unit))
    row = (condition, field, replace(performance, metrics=metrics))
    with pytest.raises(ValueError, match='unit.*dimension'):
        aggregate_multi_condition(['low'], [row], [row])
