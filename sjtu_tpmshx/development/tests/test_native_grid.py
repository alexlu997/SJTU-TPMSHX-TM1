"""Compare native grid routes with frozen independent NumPy functions."""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import grid_centres_reference as centres
from sjtu_tpmshx.development.tests import grid_ports_reference as coordinates
from sjtu_tpmshx.development.tests import grid_source_reference as reference
from sjtu_tpmshx.shared.models import _native_grid as native
from sjtu_tpmshx.shared.models import grid
from sjtu_tpmshx.preprocess.three_d.preparation import _axis_data

KINDS = (float, np.float16, np.float32, np.float64)
INTEGER_KINDS = (np.int8, np.uint8, np.int16, np.uint16,
                 np.int32, np.uint32, np.int64, np.uint64)


@pytest.mark.parametrize('kind', INTEGER_KINDS)
def test_integer_scalar_transport_retains_original_bit_width(kind):
    value = kind(1)
    scalar = native._scalar(value)
    assert scalar.value == 1. and scalar.strong == 2
    assert scalar.precision == value.dtype.itemsize * 8


@pytest.mark.parametrize('length_kind', KINDS)
@pytest.mark.parametrize('diameter_kind', KINDS)
@pytest.mark.parametrize('alpha_kind', KINDS)
def test_adaptive_grid_keeps_gui_counts_and_scalar_rounding(length_kind, diameter_kind, alpha_kind):
    from sjtu_tpmshx.shared.models.tpms_calc import adaptive_grid
    for length, height, diameter, alpha in ((.182, .042, .003, .4),
                                           (41., 21., 1., 2.),
                                           (.01, .002, .003, .4)):
        length, height = length_kind(length), length_kind(height)
        diameter, alpha = diameter_kind(diameter), alpha_kind(alpha)
        expected = (max(20, round(length / (alpha * diameter))),
                    max(10, round(height / (alpha * diameter))))
        assert adaptive_grid(length, height, diameter, alpha) == expected


@pytest.mark.parametrize('length,diameter', ((1e300, 1.), (1e308, 1e-20),
                                           (float('nan'), 1.), (1., 0.)))
def test_adaptive_grid_preserves_integer_conversion_errors(length, diameter):
    from sjtu_tpmshx.shared.models.tpms_calc import adaptive_grid
    try:
        expected = (max(20, round(length / (.4 * diameter))), max(10, round(1. / (.4 * diameter))))
    except (ValueError, OverflowError, ZeroDivisionError) as error:
        with pytest.raises(type(error)):
            adaptive_grid(length, 1., diameter)
    else:
        assert adaptive_grid(length, 1., diameter) == expected


def _exact(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    np.testing.assert_array_equal(actual, expected)
    if actual.dtype.kind == 'f':
        np.testing.assert_array_equal(np.signbit(actual[actual == 0]), np.signbit(expected[expected == 0]))


def _same_scalars(actual, expected):
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        assert type(left) is type(right)
        _exact(left, right)


def _matching(actual, expected):
    try:
        wanted = expected()
    except (ValueError, ZeroDivisionError, OverflowError) as exception:
        with pytest.raises(type(exception)):
            actual()
        return
    _exact(actual(), wanted)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('count', [1, 3, 13, 37])
def test_uniform_and_centres_keep_scalar_intermediates(kind, count):
    length = kind(.182)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        _exact(native.uniform(count, length), np.full(count, length / count, dtype=np.float64))
        _exact(native.continuous_centres(count, length), centres.continuous_centres(count, length, None))
        _exact(native.sigmoid_centres(count, length), centres.sigmoid_centres(count, length, None))


@pytest.mark.parametrize('domain_kind', KINDS)
@pytest.mark.parametrize('point_kind', KINDS)
@pytest.mark.parametrize('count', [12, 37])
def test_aligned_grid_keeps_mixed_scalar_order(domain_kind, point_kind, count):
    length = domain_kind(.182)
    points = [point_kind(.0031), point_kind(.057), point_kind(.133),
              point_kind(.0031), point_kind(.000181), point_kind(.1819)]
    epsilon = length * .001
    bounds = sorted(set([0.] + [value for value in points if epsilon < value < length - epsilon] + [length]))
    _same_scalars(native.aligned_bounds(length, points), bounds)
    _matching(lambda: grid._aligned_grid(count, length, points),
              lambda: reference._aligned_grid(count, length, points))


def test_aligned_mixed_python_sum_prefix_and_first_max_tie():
    # Each sequence crosses from Python-float sum into a strong scalar at a different segment.
    cases = [
        (float(.182), [.012, .039, np.float16(.071), .137], 37),
        (np.float32(.182), [.012, .039, np.float32(.071), np.float16(.137)], 37),
        (1., [.25, .5, .75], 10),
        (1., [np.float16(.25), np.float32(.5), np.float64(.75)], 10),
    ]
    for length, points, count in cases:
        _exact(grid._aligned_grid(count, length, points), reference._aligned_grid(count, length, points))


@pytest.mark.parametrize('length_kind', KINDS)
@pytest.mark.parametrize('count_kind', [np.int8, np.int16, np.int32, np.int64, np.uint8,
                                      np.uint16, np.uint32, np.uint64])
def test_continuous_numpy_integer_count_keeps_quotient_promotion(length_kind, count_kind):
    count, length = count_kind(13), length_kind(.182)
    _exact(native.continuous_centres(count, length), centres.continuous_centres(count, length, None))


@pytest.mark.parametrize('length_kind', INTEGER_KINDS)
@pytest.mark.parametrize('count_kind', [int, np.int8, np.uint16])
def test_continuous_integer_length_and_count_keep_float64_true_division(length_kind, count_kind):
    count, length = count_kind(13), length_kind(2)
    expected = centres.continuous_centres(count, length, None)
    assert expected.dtype == np.float64
    _exact(native.continuous_centres(count, length), expected)


@pytest.mark.parametrize('kind', [np.int8, np.int32, np.int64, np.uint64])
def test_integer_configuration_scalars_keep_float_grid_arithmetic(kind):
    length, height = kind(1), kind(2)
    count = kind(13)
    _exact(native.uniform(count, length), np.full(count, length / count, dtype=np.float64))
    _exact(native.continuous_centres(count, length), centres.continuous_centres(count, length, None))
    ports = [dict(dir=0, in_ctr=height / 2, out_ctr=height / 2, in_w=height, out_w=height),
             dict(dir=3, in_ctr=length / 2, out_ctr=length / 2, in_w=length, out_w=length)]
    actual = grid.build_grid_2d(length, height, 12, 8, ports)
    expected = reference.build_grid_2d(length, height, 12, 8, ports)
    for a, b in zip(actual, expected):
        if isinstance(b, np.ndarray):
            _exact(a, b)
        else:
            assert a == b


@pytest.mark.parametrize('nz', [1, 3])
def test_public_prepare_accepts_numpy_integer_domain_lengths(nz):
    from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig, GeometryConfig, SolverConfig, ExtrapPolicy
    from sjtu_tpmshx.preprocess.api import prepare_case
    cfg = ComputeConfig(geometry=GeometryConfig(L_dom_m=np.int64(1), H_dom_m=np.int32(1), Lz_m=.03),
                        solver=SolverConfig(Nx=8, Ny=6, Nz=nz), extrap=ExtrapPolicy(allow=True))
    case = prepare_case(cfg, case_id='integer-domain')
    assert np.sum(case.grid['dx']) == pytest.approx(1.)
    assert np.sum(case.grid['dy']) == pytest.approx(1.)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('width', [.004, .042, .182])
@pytest.mark.parametrize('layers', [0, 4, 8])
def test_wall_widths_match_original_rounding_and_rejection(kind, width, layers):
    _matching(lambda: grid.build_wall_refined_1d(kind(width), 13, layers),
              lambda: reference.build_wall_refined_1d(kind(width), 13, layers))


@pytest.mark.parametrize('first_kind,growth_kind', [(np.float16, float), (float, np.float32),
                                                  (np.float16, np.float32), (np.float32, np.float16)])
def test_wall_custom_numpy_layer_scalars(first_kind, growth_kind):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        _matching(lambda: grid.build_wall_refined_1d(.182, 11, 4, first_kind(.0002), growth_kind(1.8)),
                  lambda: reference.build_wall_refined_1d(.182, 11, 4, first_kind(.0002), growth_kind(1.8)))


def _port(kind, direction=0):
    return dict(dir=direction, in_ctr=kind(.031), in_w=kind(.017),
                out_ctr=kind(.019), out_w=kind(.011),
                in_z_ctr=kind(.022), in_z_w=kind(.013),
                out_z_ctr=kind(.017), out_z_w=kind(.009))


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('dimensions', [2, 3])
@pytest.mark.parametrize('direction', range(6))
def test_port_wall_edges_counts_and_widths(kind, dimensions, direction):
    if direction // 2 >= dimensions:
        pytest.skip('The port direction is outside this domain.')
    lengths = tuple(kind(value) for value in (.182, .042, .035)[:dimensions])
    ports = (_port(kind, direction), None)
    actual = list(grid._port_wall_axes(lengths, ports))
    expected = list(reference._port_wall_axes(lengths, ports))
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        _same_scalars(left[0], right[0])
        assert left[1:] == right[1:]
    assert grid.port_wall_min_counts(lengths, ports) == reference.port_wall_min_counts(lengths, ports)
    count = (96,) * dimensions
    _matching(lambda: np.stack(grid.build_port_wall_grid(lengths, count, ports)),
              lambda: np.stack(reference.build_port_wall_grid(lengths, count, ports)))


def test_port_wall_failure_keeps_original_axis_and_edges():
    lengths, ports = (.182, .042), (_port(float),)
    with pytest.raises(ValueError) as actual:
        grid.build_port_wall_grid(lengths, (8, 8), ports)
    with pytest.raises(ValueError) as expected:
        reference.build_port_wall_grid(lengths, (8, 8), ports)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('refined', [False, True])
def test_grid_suggestion_uses_total_counts_and_native_port_minima(kind, refined):
    lengths, diameter = tuple(kind(value) for value in (.182, .042, .035)), kind(.0031)
    ports = (_port(kind),)
    for budget in (50_000, 150_000):
        assert grid.suggest_grid_3d(*lengths, diameter, budget, port_wall_refine=refined, ports=ports) == (
            reference.suggest_grid_3d(*lengths, diameter, budget, port_wall_refine=refined, ports=ports))


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('refined', [False, True])
def test_grid_2d_retains_one_sided_breaks_and_error_flow(kind, refined):
    port = dict(dir=0, in_ctr=kind(.021), in_w=kind(.042),
                out_ctr=kind(.019), out_w=kind(.013))
    expected = reference.build_grid_2d(kind(.182), kind(.042), 84, 48, (port,), port_wall_refine=refined)
    actual = grid.build_grid_2d(kind(.182), kind(.042), 84, 48, (port,), port_wall_refine=refined)
    _exact(actual[0], expected[0])
    _exact(actual[1], expected[1])
    _same_scalars(actual[2], expected[2])
    _same_scalars(actual[3], expected[3])
    assert actual[4] == expected[4]


@pytest.mark.parametrize('width_kind', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('lower_kind', KINDS)
@pytest.mark.parametrize('upper_kind', KINDS)
@pytest.mark.parametrize('staggered', [False, True])
def test_raw_width_overlap_keeps_cumsum_and_endpoint_precision(width_kind, lower_kind, upper_kind, staggered):
    samples = ([.007, .042, .133], [2.**-10] * 128, [.013, .007, .031, .011, .017])
    for sample in samples:
        widths = np.asarray(sample, dtype=width_kind)
        edges = np.cumsum(widths)
        limits = [(lower_kind(0.), upper_kind(edges[-1])),
                  (lower_kind(edges[0]), upper_kind(edges[-2])),
                  (lower_kind(.013), upper_kind(.047)),
                  (lower_kind(.031), upper_kind(.031))]
        for lower, upper in limits:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                expected = reference._port_overlap_1d(widths, lower, upper, staggered=staggered)
            actual = grid._port_overlap_1d(widths, lower, upper, staggered=staggered)
            _exact(actual, expected)
            for threshold in (0., .01, .5, .99):
                np.testing.assert_array_equal(actual > threshold, expected > threshold)


def test_roundoff_max_tie_keeps_the_first_numpy16_winner():
    widths, lower, upper = np.full(128, 2.**-10), np.float16(0.), np.float16(.125)
    expected = reference._port_overlap_1d(widths, lower, upper)
    assert np.count_nonzero(expected) == 0
    _exact(grid._port_overlap_1d(widths, lower, upper), expected)


@pytest.mark.parametrize('kind', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('uniform', [False, True])
def test_raw_fraction_profiles_preserve_discrete_taper(kind, uniform):
    widths = np.full(23, .001, dtype=kind)
    lower, upper = np.float16(.004), np.float32(.019)
    actual = grid._port_fractions_1d(widths, lower, upper, uniform=uniform)
    expected = reference._port_fractions_1d(widths, lower, upper, uniform=uniform)
    _exact(actual[0], expected[0])
    np.testing.assert_allclose(actual[1], expected[1], rtol=4e-15, atol=0.)
    for threshold in (0., .01, .5, .99):
        np.testing.assert_array_equal(actual[1] > threshold, expected[1] > threshold)


@pytest.mark.parametrize('width_kind', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('length_kind', KINDS)
def test_raw_sigmoid_centres_keep_array_intermediate_dtype(width_kind, length_kind):
    for sample in ([.007, .042, .133], [2.**-10] * 128):
        widths = np.array(sample, dtype=width_kind)
        length = length_kind(np.sum(widths))
        _exact(native.sigmoid_centres(len(widths), length, widths),
               centres.sigmoid_centres(len(widths), length, widths))


@pytest.mark.parametrize('kind', KINDS)
def test_rectangles_and_partial_masks_keep_physical_edges(kind):
    config = _port(kind, 5)
    _actual = native.rectangles(config, kind(.035))
    _expected = coordinates._port_rectangles(config, kind(.035))
    for key in ('inlet_rect', 'outlet_rect'):
        _same_scalars(_actual[key], _expected[key])
    for width_kind in (np.float16, np.float32, np.float64):
        first = np.full(23, .002, dtype=width_kind)
        second = np.full(19, .002, dtype=width_kind)
        for left, right in zip(native.partial_masks(config, first, second, len(second)),
                               coordinates._build_partial_masks(config, first, second, len(second))):
            _exact(left, right)


@pytest.mark.parametrize('direction,axes,permutation,reverse', [
    (0, (1, 0, 2), (1, 0, 2), False), (1, (1, 0, 2), (1, 0, 2), True),
    (2, (0, 1, 2), (0, 1, 2), False), (3, (0, 1, 2), (0, 1, 2), True),
    (4, (0, 2, 1), (0, 2, 1), False), (5, (0, 2, 1), (0, 2, 1), True),
])
def test_axis_map_borrows_widths_and_keeps_direction(direction, axes, permutation, reverse):
    lengths = (np.float16(.182), np.float32(.042), .035)
    counts = (7, 5, 3)
    widths = tuple(native.uniform(count, length) for count, length in zip(counts, lengths))
    for actual, length, count in zip(widths[:3], lengths, counts):
        _exact(actual, np.full(count, length / count, dtype=np.float64))
    mapping = _axis_data(native.axis_map(direction), widths, lengths)
    assert mapping['solver_to_real_perm'] == permutation
    assert mapping['is_reverse'] is reverse
    for key, axis in zip(('cross1', 'stream', 'cross2'), axes):
        assert mapping[f'{key}_real_axis'] == axis
        assert mapping[f'd{key}'] is widths[axis]
        assert mapping[f'N_{key}'] is counts[axis]
        assert mapping[f'L_{key}'] is lengths[axis]


@pytest.mark.parametrize('operation', ['overlap', 'fractions', 'partial'])
def test_grid_c_boundary_failure_keeps_all_caller_outputs(operation):
    import ctypes as ct

    first, second = np.full(4, -731.25), np.full(4, 918.5)
    first_before, second_before = first.copy(), second.copy()
    widths = np.full(4, .01)
    error = ct.create_string_buffer(512)
    if operation == 'overlap':
        status = native._function('overlap')(
            native._pointer(widths), 4, 24, native._scalar(0.), native._scalar(.04), 0,
            native._pointer(first), first.size, error, len(error))
    elif operation == 'fractions':
        status = native._function('fractions')(
            native._pointer(widths), 4, 24, native._scalar(0.), native._scalar(.04), 0,
            native._pointer(first), native._pointer(second), first.size, error, len(error))
    else:
        widths = np.full(4, .01)
        # The outlet fails after the inlet range has already been calculated.
        config = native._port(dict(in_ctr=.02, in_w=.02, out_ctr=.09, out_w=.01))
        status = native._function('partial')(
            ct.byref(config), native._pointer(widths), 4, 64, native._pointer(np.empty(0)),
            0, 64, 0, 1, native._pointer(first), native._pointer(second), 4, error, len(error))
    assert status == 1
    assert error.value
    _exact(first, first_before)
    _exact(second, second_before)


def test_grid_c_boundary_rejects_invalid_precision_before_writing():
    import ctypes as ct

    output = np.full(4, 291.5)
    original = output.copy()
    error = ct.create_string_buffer(512)
    bad = native._Scalar(.182, 24, 1)
    status = native._function('uniform')(4, bad, native._pointer(output), 4, error, len(error))
    assert status == 1
    assert error.value
    _exact(output, original)


@pytest.mark.parametrize('kind', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('staggered', [False, True])
def test_raw_overlap_keeps_nonfinite_and_nonpositive_numpy_values(kind, staggered):
    samples = ([.01, 0., .02], [.01, -.005, .02], [np.nan, .01, .02],
               [np.inf, .01, .02], [-np.inf, .01, .02], [0., -0., .01])
    for sample in samples:
        widths = np.asarray(sample, dtype=kind)
        for lower, upper in ((0., .025), (-np.inf, np.inf), (np.nan, .025), (0., np.nan)):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                expected = reference._port_overlap_1d(widths, lower, upper, staggered=staggered)
            _exact(grid._port_overlap_1d(widths, lower, upper, staggered=staggered), expected)


@pytest.mark.parametrize('staggered', [False, True])
def test_empty_raw_overlap_keeps_original_index_error(staggered):
    widths = np.empty(0)
    with pytest.raises(IndexError) as expected:
        reference._port_overlap_1d(widths, 0., 1., staggered=staggered)
    with pytest.raises(IndexError) as actual:
        grid._port_overlap_1d(widths, 0., 1., staggered=staggered)
    assert str(actual.value) == str(expected.value)


def test_empty_raw_fraction_keeps_original_index_error():
    widths = np.empty(0)
    with pytest.raises(IndexError) as expected:
        reference._port_fractions_1d(widths, 0., 1.)
    with pytest.raises(IndexError) as actual:
        grid._port_fractions_1d(widths, 0., 1.)
    assert str(actual.value) == str(expected.value)
