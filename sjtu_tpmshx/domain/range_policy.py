"""Apply the agreed parameter limits to captured original model bounds."""
from math import inf, isfinite, nextafter, prod


def parameter_bounds(bounds):
    """Return the 10 percent envelope for positive original bounds."""
    lower, upper = map(float, bounds)
    if not (isfinite(lower) and isfinite(upper) and 0. < lower <= upper):
        raise ValueError('relative range limits require positive ordered source bounds')
    return .9 * lower, 1.1 * upper


def assess_range(sample):
    """Return a parameter verdict; this does not grant design qualification."""
    row = dict(sample)
    if type(sample['captured']) is not bool:
        raise ValueError('range evidence requires an explicit capture flag')
    if not sample['captured']:
        return dict(row, status='unavailable', within_limit=None)
    lower, upper = map(float, sample['bounds'])
    if not (isfinite(lower) and isfinite(upper) and lower <= upper):
        raise ValueError('range evidence requires finite ordered source bounds')
    size = sample['size']
    if size <= 0 or size != prod(sample['shape']) or any(
            count < 0 or count > size for count in
            (sample['low'], sample['high'], sample['nonfinite'])):
        raise ValueError('range evidence has inconsistent sample counts')
    constraint = sample.get('constraint', 'parameter')
    if constraint not in ('parameter', 'hard_bounds'):
        raise ValueError('unsupported range constraint')
    hard = constraint == 'hard_bounds'
    positive = lower > 0.
    allowed = (lower, upper) if hard or not positive else parameter_bounds((lower, upper))
    row.update(allowed_bounds=allowed, allowance_fraction=0. if hard else .1 if positive else None)
    if sample['nonfinite'] or sample['minimum'] is None or sample['maximum'] is None:
        return dict(row, status='invalid', within_limit=False, reason='sample contains nonfinite values')
    minimum, maximum = (float(sample[key][0]) for key in ('minimum', 'maximum'))
    if not (isfinite(minimum) and isfinite(maximum) and minimum <= maximum):
        raise ValueError('range evidence requires finite ordered extrema')
    if lower <= minimum <= maximum <= upper:
        return dict(row, status='within_original', within_limit=True, relative_extrapolation=0.)
    if not hard and not positive:
        return dict(row, status='domain_rule_required', within_limit=None,
                    reason='relative extrapolation is undefined for zero or signed source bounds')
    # One float step includes the decimal boundary after multiplication rounds.
    inside = (allowed[0] <= minimum and maximum <= allowed[1]) if hard else (
        nextafter(allowed[0], -inf) <= minimum and maximum <= nextafter(allowed[1], inf))
    fraction = max(0., (lower - minimum) / lower, (maximum - upper) / upper) if positive else None
    return dict(row, status='within_margin' if inside else 'outside_limit', within_limit=inside,
                relative_extrapolation=fraction)
