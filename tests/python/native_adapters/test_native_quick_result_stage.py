"""Quick stage observations match independent float64 Python expressions."""
from dataclasses import replace
import os
from pathlib import Path

import numpy as np
import pytest

from tests.python.native.result_reference import api as reference
from tests.python.native.test_result_metrics import (
    assert_observation, observe, quick_result,
)
from tests.python.result_stage_fixture import thaw
from tm1.postprocess import api as native
from tm1.data_types.metric_spec import MetricSpec
from tm1.file_io.result_io import load_result


def observed_evaluation(function, result, spec):
    value = function(result, spec)
    return dict(source_result_id=value.source_result_id,
        metrics={name: dict(value=row.value, status=row.status, reason=row.reason,
            spec=vars(row.spec)) for name, row in value.metrics.items()},
        qualification=thaw(value.qualification))


def compare(result, name):
    unit = 'W' if name in ('Q', 'Q_cold') else 'Pa' if name.startswith('dP') else 'K' if name.startswith('T_out') else 'kg/s' if name.startswith('mass_flow') else '1'
    spec = MetricSpec(name, unit, 'three_module_v1', 'selected Quick evidence')
    expected = observe(observed_evaluation, reference.evaluate, result, spec)
    actual = observe(observed_evaluation, native.evaluate, result, spec)
    assert_observation(actual, expected)


@pytest.mark.parametrize('name,changes', [
    ('Q', dict(mass=0.25, cp=1005.0, inlet=450.0)),
    ('Q', dict(mass=0.0, inlet=300.0)),
    ('dP_A', dict(pin=200000.0, pout=185000.0)),
    ('dP_A', dict(pin=1e5, pout=np.nan)),
    ('Re_A', dict(rho=1.1, speed=0.3, diameter=0.005, mu=0.7)),
    ('Re_A', dict(rho=np.float64(1.1), speed=np.float64(0.3), mu=np.float64(0.7))),
    ('Re_A', dict(rho=3, speed=2, diameter=4, mu=3)),
    ('mass_flow_A', dict(mass=3.125)),
])
def test_float64_quick_scalar_metrics_match_reference(name, changes):
    compare(quick_result(**changes), name)


def test_quick_energy_imbalance_matches_reference():
    result = quick_result(mass=0.5, cp=1000.0, inlet=400.0)
    result = replace(result, boundary_fluxes={**result.boundary_fluxes,
        'B': dict(mass_flow_kg_s=0.4, cp_J_kgK=1000.0, inlet_temperature_K=250.0, velocity_m_s=1.0)})
    compare(result, 'energy_imbalance_rel')


@pytest.mark.parametrize('shape', [(), (2,), (2, 2), (0, 2, 1), (1, 0, 1), (1, 1, 0), (1, 2, 1, 2)])
@pytest.mark.parametrize('name', ['T_out_A', 'T_out_B'])
def test_original_outlet_index_and_empty_mean_protocol(shape, name):
    result = quick_result()
    result = replace(result, fields={**result.fields, 'Ta' if name.endswith('A') else 'Tb': np.ones(shape)})
    if shape in ((1, 0, 1), (1, 1, 0)):
        spec = MetricSpec(name, 'K', 'three_module_v1', 'selected Quick evidence')
        expected = observe(observed_evaluation, reference.evaluate, result, spec)
        actual = observe(observed_evaluation, native.evaluate, result, spec)
        assert actual[0] == expected[0]
        assert actual[1] == [(RuntimeWarning, 'invalid value encountered in scalar divide')]
        return
    compare(result, name)


@pytest.mark.parametrize('role,name', [('mass', 'Q'), ('cp', 'Q'), ('inlet', 'Q'),
    ('rho', 'Re_A'), ('speed', 'Re_A'), ('diameter', 'Re_A'), ('mu', 'Re_A'), ('pin', 'dP_A')])
@pytest.mark.parametrize('value', [None, '3', True, (1.0, 2.0), np.array([1.0, 2.0])])
def test_quick_non_real_scalars_report_insufficient_data(role, name, value):
    unit = 'W' if name == 'Q' else 'Pa' if name.startswith('dP') else '1'
    spec = MetricSpec(name, unit, 'three_module_v1', 'selected Quick evidence')
    evaluated = native.evaluate(quick_result(**{role: value}), spec)
    metric = evaluated.metrics[name]
    assert metric.status == 'insufficient_data' and metric.value is None


def test_quick_huge_int_raises_overflow_error():
    spec = MetricSpec('mass_flow_A', 'kg/s', 'three_module_v1', 'selected Quick evidence')
    with pytest.raises(OverflowError):
        native.evaluate(quick_result(mass=2**1100), spec)


@pytest.mark.parametrize('key,value,name', [
    ('model', None, 'Q'), ('model', 3, 'Re_A'), ('model', 'unknown', 'Q'),
    ('parameters', None, 'T_out_B'), ('parameters', (), 'Re_A'),
    ('properties', None, 'Re_A'), ('properties', (), 'Re_A'),
])
def test_malformed_records_keep_the_first_consumed_error(key, value, name):
    result = quick_result()
    compare(replace(result, metadata={**result.metadata, key: value}), name)


def test_selected_spec_identity_and_missing_qualification_are_retained():
    result = quick_result()
    spec = MetricSpec('dP_A', 'Pa', 'three_module_v1', 'caller-owned definition')
    value = native.evaluate(result, spec)
    assert value.metrics['dP_A'].spec is spec
    assert value.source_result_id == result.result_id
    assert value.qualification['physical']['status'] == 'unverified'
    assert value.qualification['optimization']['status'] != 'passed'


@pytest.mark.parametrize('case', ['cross-const', 'cross-mean', 'counter-const'])
def test_frozen_quick_public_reports(case):
    root = os.environ.get('TPMSHX_RESULT_STAGE_FROZEN_DIR')
    if not root:
        pytest.skip('set TPMSHX_RESULT_STAGE_FROZEN_DIR to use the frozen Quick solves')
    result = load_result(Path(root) / f'quick-design-{case}/results.h5')
    expected = observe(observed_evaluation, reference.evaluate, result, None)
    actual = observe(observed_evaluation, native.evaluate, result, None)
    assert_observation(actual, expected)
    metrics = reference.evaluate(result).metrics
    for name, args in [('evaluate_applicability', (result,)),
                       ('evaluate_physical_balance', (result,)),
                       ('evaluate_qualification', (result, metrics))]:
        expected = observe(lambda: thaw(getattr(reference, name)(*args)))
        actual = observe(lambda: thaw(getattr(native, name)(*args)))
        assert_observation(actual, expected)


@pytest.mark.parametrize('execution', [None, (), {'version': 'historical', 'sides': None},
    {'version': 9, 'sides': ()}, {'version': 'full_execution_v1', 'sides': None},
    {'version': 'full_execution_v1', 'sides': ()}])
def test_execution_metadata_keeps_its_original_consumption_point(execution):
    result = quick_result()
    result = replace(result, metadata={**result.metadata, 'execution_record': execution})
    compare(result, 'Q')


@pytest.mark.parametrize('label', [None, 4, False, (), {'key': 1}, 'unknown', '\0', 'cross\0extra', '交叉'])
@pytest.mark.parametrize('field,name', [('model', 'Q'), ('arrangement', 'T_out_B'), ('arrangement', 'Q')])
def test_raw_quick_labels_keep_native_policy(label, field, name):
    result = quick_result()
    metadata = dict(result.metadata)
    if field == 'model':
        metadata[field] = label
    else:
        metadata['parameters'] = {**metadata['parameters'], field: label}
    fields = {**result.fields, 'Tb': np.asarray([[[1.], [2.]], [[3.], [4.]]])}
    compare(replace(result, metadata=metadata, fields=fields), name)
