"""Apply the agreed parameter limits to captured original model bounds."""
from math import prod

from sjtu_tpmshx.shared import _native_result_checks


def parameter_bounds(bounds):
    """Return the 10 percent envelope for positive original bounds."""
    lower, upper = map(float, bounds)
    return _native_result_checks.parameter_bounds(lower, upper)


def assess_range(sample):
    """Return a parameter verdict; this does not grant design qualification."""
    row = dict(sample)
    if type(sample['captured']) is not bool:
        raise ValueError('range evidence requires an explicit capture flag')
    if not sample['captured']:
        return dict(row, status='unavailable', within_limit=None)
    lower, upper = map(float, sample['bounds'])
    allowed, positive, allowance = _native_result_checks.source_bounds(lower, upper)
    size = sample['size']
    if size <= 0 or size != prod(sample['shape']) or any(
            count < 0 or count > size for count in
            (sample['low'], sample['high'], sample['nonfinite'])):
        raise ValueError('range evidence has inconsistent sample counts')
    constraint = sample.get('constraint', 'parameter')
    if constraint not in ('parameter', 'hard_bounds'):
        raise ValueError('unsupported range constraint')
    hard = constraint == 'hard_bounds'
    allowed = (lower, upper) if hard else allowed
    row.update(allowed_bounds=allowed, allowance_fraction=0. if hard else allowance if positive else None)
    if sample['nonfinite'] or sample['minimum'] is None or sample['maximum'] is None:
        return dict(row, status='invalid', within_limit=False, reason='sample contains nonfinite values')
    minimum, maximum = (float(sample[key][0]) for key in ('minimum', 'maximum'))
    decision = _native_result_checks.range_values(lower, upper, minimum, maximum, hard)
    if decision.numerical_case == 1:
        return dict(row, status='within_original', within_limit=True,
                    relative_extrapolation=decision.relative_extrapolation)
    if decision.numerical_case == 2:
        return dict(row, status='domain_rule_required', within_limit=None,
                    reason='relative extrapolation is undefined for zero or signed source bounds')
    inside = decision.numerical_case == 3
    fraction = decision.relative_extrapolation if decision.relative_present else None
    return dict(row, status='within_margin' if inside else 'outside_limit', within_limit=inside,
                relative_extrapolation=fraction)
