"""Complete-condition aggregation must preserve physical scores and failures."""
from dataclasses import replace

import pytest

from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.optimization.multi_condition import aggregate_multi_condition
from sjtu_tpmshx.postprocess.api import evaluate_qualification


def _row(condition_id, q=100.0, dp_a=20.0, dp_b=40.0, **run_status):
    from sjtu_tpmshx.tests.postprocess_tm1.test_qualification import qualified_result, required_metrics
    field = replace(qualified_result(), result_id=f'field-{condition_id}',
        case_id=f'design-case-{condition_id}',
        run_status={'execution': 'completed', 'converged': True, **run_status})
    metrics = {
        **required_metrics(),
        'Q': MetricValue(999.0, MetricSpec('Q', 'W', 'native_boundary_v1')),
        'Q_B': MetricValue(-q, MetricSpec('Q_B', 'W', 'native_boundary_v1')),
        'dP_A': MetricValue(dp_a, MetricSpec('dP', 'Pa', 'pressure_face_v1')),
        'dP_B': MetricValue(dp_b, MetricSpec('dP', 'Pa', 'pressure_face_v1')),
    }
    return condition_id, field, PerformanceResult(f'metric-{condition_id}', field.result_id, metrics)


def test_equal_conditions_and_sides_preserve_both_objectives():
    baseline = [_row('low'), _row('high', q=200.0, dp_a=30.0, dp_b=60.0)]
    candidate = [_row('high', q=240.0, dp_a=15.0, dp_b=90.0),
                 _row('low', q=90.0, dp_a=10.0, dp_b=20.0)]
    result = aggregate_multi_condition(('low', 'high'), baseline, candidate)
    assert result == pytest.approx({'heat_gain_percent': 5.0, 'pressure_ratio': 0.75})


@pytest.mark.parametrize('pressure', [0.1, 1e7])
def test_negative_gain_and_pressure_are_not_clamped(pressure):
    result = aggregate_multi_condition(
        ['low'], [_row('low', dp_a=pressure, dp_b=2.0 * pressure)],
        [_row('low', q=75.0, dp_a=0.5 * pressure, dp_b=pressure)])
    assert result == pytest.approx({'heat_gain_percent': -25.0, 'pressure_ratio': 0.5})


def test_signed_water_heat_is_never_made_absolute():
    result = aggregate_multi_condition(['low'], [_row('low')], [_row('low', q=-50.0)])
    assert result['heat_gain_percent'] == pytest.approx(-150.0)


@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
@pytest.mark.parametrize('member', ['baseline', 'candidate'])
def test_sco2_scope_notice_permits_objectives_without_design_approval(sides, member):
    condition, field, performance = _row('low')
    metadata = mutable_data(field.metadata)
    for side in sides:
        metadata['execution_record']['sides'][side]['fluid'] = 'sco2'
    field = replace(field, metadata=metadata)
    quality = evaluate_qualification(field, performance.metrics)
    performance = replace(performance, qualification=quality)
    assert quality['model_scope']['passed'] is quality['design']['eligible'] is None
    assert quality['optimization']['passed'] is True
    assert quality['optimization']['deferred'] == ['model_scope']
    rows = {'baseline': [_row('low')], 'candidate': [_row('low')]}
    rows[member] = [(condition, field, performance)]
    assert aggregate_multi_condition(['low'], **rows) == {
        'heat_gain_percent': 0., 'pressure_ratio': 1.}
    assert performance.qualification['design']['eligible'] is None


@pytest.mark.parametrize('damage,reason', [('range', 'applicability'),
    ('missing_range', 'applicability'), ('energy', 'physical'), ('side', 'model_scope')])
@pytest.mark.parametrize('member', ['baseline', 'candidate'])
def test_sco2_permission_does_not_hide_other_failures_or_missing_evidence(damage, reason, member):
    condition, field, performance = _row('low')
    metadata = mutable_data(field.metadata)
    metadata['execution_record']['sides']['A']['fluid'] = 'sco2'
    if damage == 'range':
        metadata['applicability_evidence']['final'][0]['minimum'][0] = 89.
    elif damage == 'missing_range':
        del metadata['applicability_evidence']
    elif damage == 'energy':
        metadata['diagnostics']['eps_A_strict_cellmax'] = .01001
    else:
        del metadata['execution_record']['sides']['B']['solved']
    field = replace(field, metadata=metadata)
    # The consumer must recompute evidence instead of trusting a stored permission.
    quality = evaluate_qualification(field, performance.metrics)
    quality['optimization']['passed'] = True
    performance = replace(performance, qualification=quality)
    rows = {'baseline': [_row('low')], 'candidate': [_row('low')]}
    rows[member] = [(condition, field, performance)]
    with pytest.raises(ValueError, match=reason):
        aggregate_multi_condition(['low'], **rows)


@pytest.mark.parametrize('bad_rows, message', [
    ([], 'membership mismatch'),
    ([_row('low'), _row('low')], 'duplicate condition'),
    ([_row('low'), _row('other')], 'membership mismatch'),
    ([_row('low', converged=False)], 'completed and converged'),
    ([_row('low', execution='failed')], 'completed and converged'),
])
@pytest.mark.parametrize('side', ['baseline', 'candidate'])
def test_failed_or_incomplete_conditions_never_change_denominator(bad_rows, message, side):
    rows = {'baseline': [_row('low')], 'candidate': [_row('low')]}
    rows[side] = bad_rows
    with pytest.raises(ValueError, match=message):
        aggregate_multi_condition(['low'], **rows)


@pytest.mark.parametrize('ids', [[], ['low', 'low'], [''], [None]])
def test_invalid_fixed_condition_list_is_rejected(ids):
    with pytest.raises(ValueError, match='condition_ids'):
        aggregate_multi_condition(ids, [_row('low')], [_row('low')])


@pytest.mark.parametrize('metric_name', ['Q_B', 'dP_A', 'dP_B'])
@pytest.mark.parametrize('value', [0.0, -1.0])
def test_nonpositive_baseline_denominators_are_rejected(metric_name, value):
    condition, field, performance = _row('low')
    metrics = dict(performance.metrics)
    metrics[metric_name] = replace(metrics[metric_name], value=-value if metric_name == 'Q_B' else value)
    baseline = [(condition, field, replace(performance, metrics=metrics))]
    with pytest.raises(ValueError, match=f'{metric_name} must be positive'):
        aggregate_multi_condition(['low'], baseline, [_row('low')])


@pytest.mark.parametrize('status', ['invalid', 'insufficient_data', 'unsupported', 'missing'])
def test_unavailable_metric_cannot_enter_the_average(status):
    condition, field, performance = _row('low')
    metrics = dict(performance.metrics)
    original = metrics.pop('Q_B')
    if status != 'missing':
        metrics['Q_B'] = replace(original, value=None, status=status, reason='nonfinite native evidence')
    candidate = [(condition, field, replace(performance, metrics=metrics))]
    with pytest.raises(ValueError, match='Q_B unavailable'):
        aggregate_multi_condition(['low'], [_row('low')], candidate)


@pytest.mark.parametrize('change', [{'unit': 'W/m'}, {'definition_version': 'screening_v1'}])
def test_mixed_metric_definitions_are_not_compared(change):
    condition, field, performance = _row('low')
    metrics = dict(performance.metrics)
    metrics['Q_B'] = replace(metrics['Q_B'], spec=replace(metrics['Q_B'].spec, **change))
    message = 'unit disagrees' if 'unit' in change else 'metric definitions differ'
    with pytest.raises(ValueError, match=message):
        aggregate_multi_condition(['low'], [_row('low')],
                                  [(condition, field, replace(performance, metrics=metrics))])


def test_mismatched_native_source_is_rejected():
    condition, field, performance = _row('low')
    with pytest.raises(ValueError, match='source does not match'):
        aggregate_multi_condition(['low'], [_row('low')],
                                  [(condition, field, replace(performance, source_result_id='other'))])


def test_ratio_overflow_is_not_reported_as_a_score():
    with pytest.raises(ValueError, match='ratio is not finite'):
        aggregate_multi_condition(['low'], [_row('low', q=1e-300)], [_row('low', q=1e300)])


def test_percent_overflow_is_not_reported_as_a_score():
    with pytest.raises(ValueError, match='objectives must be finite'):
        aggregate_multi_condition(['low'], [_row('low', q=1.0)], [_row('low', q=1e307)])


@pytest.mark.parametrize('damage', [None, 'property', 'hard', 'nonfinite', 'negative',
                                   'missing', 'energy', 'scope', 'mixed'])
def test_nu_re_acceptance_keeps_all_other_gates(damage):
    from sjtu_tpmshx.optimization.multi_condition import _condition_metrics
    name, field, performance = _row('low')
    metadata = mutable_data(field.metadata)
    sample = metadata['applicability_evidence']['final'][0]
    sample['minimum'][0] = .001
    if damage == 'property':
        sample['source'] = ['property', 'water', 'temperature']
    elif damage == 'hard':
        sample['constraint'] = 'hard_bounds'
    elif damage == 'nonfinite':
        sample['nonfinite'] = 1
    elif damage == 'negative':
        sample['minimum'][0] = -1.
    elif damage == 'missing':
        metadata['applicability_evidence']['inlet_recorded'] = False
    elif damage == 'energy':
        metadata['diagnostics']['eps_A_strict_cellmax'] = .01001
    elif damage == 'scope':
        metadata['execution_record']['sides']['A']['fluid'] = 'sco2'
    elif damage == 'mixed':
        extra = dict(sample, quantity='Pr')
        metadata['applicability_evidence']['final'].append(extra)
    field = replace(field, metadata=metadata)
    rows = [(name, field, performance)]
    with pytest.raises(ValueError, match='qualification failed'):
        _condition_metrics(rows, (name,), 'strict')
    if damage is not None:
        with pytest.raises(ValueError, match='qualification failed'):
            _condition_metrics(rows, (name,), 'study', allow_nu_re_extrapolation=True)
    else:
        accepted = {}
        assert _condition_metrics(rows, (name,), 'study', allow_nu_re_extrapolation=True,
                                  acceptances=accepted)[name] is performance
        assert accepted[name]['passed'] and not accepted[name]['strict_passed']
        assert accepted[name]['nu_re_extrapolated']
        observed, = accepted[name]['extrapolation_checks']
        assert observed['minimum'][0] == .001 and observed['bounds'] == [100., 200.]
        assert evaluate_qualification(field, performance.metrics)['optimization']['passed'] is False
