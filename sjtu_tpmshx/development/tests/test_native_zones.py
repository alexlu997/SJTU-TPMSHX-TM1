"""Check native zones against frozen NumPy and SciPy bodies.

IDs are exact. The Gaussian gate remains rtol=0, atol=1e-13.
No production zone body supplies an expected value.

Keep the connected preparation checks in the existing suites:
test_zone_geometry, test_zone_input_errors, and solver_tm1 tests for
prepared_zoned_coordinates and prepared_zoned_thermal_2d. Include both
topologies, x/y stripes, 2D first/default and 3D last/default rectangles,
nonuniform widths, reverse streams, Case replay and the original physical gates.
Those checks must also cover scalar geometry before 2D scatter and the
distinct 3D float conversion. These kernel tests do not replace them.
"""

import ctypes as ct
import os

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import zone_reference as frozen
from sjtu_tpmshx.shared.models import _native_geometry, _native_zones


_TYPES = (float, np.float16, np.float32, np.float64)
_BOUND_TYPES = (
    pytest.param(float, float, id='python'),
    pytest.param(np.float16, np.float16, id='half'),
    pytest.param(np.float32, np.float32, id='single'),
    pytest.param(np.float64, np.float64, id='double'),
    pytest.param(np.float16, float, id='half-python'),
    pytest.param(float, np.float16, id='python-half'),
    pytest.param(np.float32, np.float64, id='single-double'),
    pytest.param(np.float64, np.float32, id='double-single'),
)


@pytest.fixture
def zones():
    try:
        _native_geometry._library_path()
    except (FileNotFoundError, RuntimeError) as error:
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(str(error))
        pytest.skip(str(error))
    _native_geometry._library()
    return _native_zones


def _check(zones, kind, nx, ny, rows, **options):
    original_widths = {name: np.asarray(options[name]).copy()
                       for name in ('dx', 'dy') if options.get(name) is not None}
    expected = frozen.assign(kind, nx, ny, rows, **options)
    actual = zones.assign(kind, nx, ny, rows, **options)
    np.testing.assert_array_equal(actual, expected)
    assert actual.shape == (nx, ny) and actual.dtype == np.int32
    assert actual.flags.c_contiguous and actual.flags.writeable
    for name in ('dx', 'dy'):
        if options.get(name) is not None:
            assert not np.shares_memory(actual, np.asarray(options[name]))
    again = zones.assign(kind, nx, ny, rows, **options)
    assert not np.shares_memory(actual, again)
    actual.fill(-777)
    np.testing.assert_array_equal(again, expected)
    np.testing.assert_array_equal(zones.assign(kind, nx, ny, rows, **options), expected)
    for name, original in original_widths.items():
        np.testing.assert_array_equal(options[name], original)
    return expected


def _widths_at(q, axis):
    widths = np.array([2. * q, 1. - 2. * q], dtype=np.float64)
    assert np.all(widths > 0.)
    return (widths, np.ones(1)) if axis == 0 else (np.ones(1), widths)


@pytest.mark.parametrize('kind', (1, 2), ids=('first-2d', 'last-3d'))
@pytest.mark.parametrize('axis', (0, 1), ids=('x', 'y'))
@pytest.mark.parametrize('lower_type,upper_type', _BOUND_TYPES)
@pytest.mark.parametrize('edge', ('lower', 'upper'))
@pytest.mark.parametrize('side', (-1, 0, 1), ids=('below', 'exact', 'above'))
def test_rectangle_bounds_keep_each_scalar_kind(
        zones, kind, axis, lower_type, upper_type, edge, side):
    q = .25 if side == 0 else float(np.nextafter(.25, -np.inf if side < 0 else np.inf))
    dx, dy = _widths_at(q, axis)
    row = [0., 1., 0., 1.]
    offset = axis * 2
    row[offset] = lower_type(.25 if edge == 'lower' else 0.)
    row[offset + 1] = upper_type(.25 if edge == 'upper' else 1.)
    rows = [[.875, 1., .875, 1.], row]
    _check(zones, kind, len(dx), len(dy), rows, dx=dx, dy=dy)


@pytest.mark.parametrize('bound_type', (np.float16, np.float32), ids=('half', 'single'))
@pytest.mark.parametrize('axis', (0, 1), ids=('x', 'y'))
@pytest.mark.parametrize('edge', ('lower', 'upper'))
def test_2d_weak_points_and_3d_strong_points_select_different_cells(
        zones, bound_type, axis, edge):
    q = .25 - float(np.spacing(bound_type(.25))) / 4.
    dx, dy = _widths_at(q, axis)
    row = [0., 1., 0., 1.]
    row[2 * axis + (0 if edge == 'lower' else 1)] = bound_type(.25)
    rows = [[.875, 1., .875, 1.], row]
    first = _check(zones, 1, len(dx), len(dy), rows, dx=dx, dy=dy)
    last = _check(zones, 2, len(dx), len(dy), rows, dx=dx, dy=dy)
    # The fixture must reach the weak-conversion branch, not only compare equal data.
    assert first[0, 0] == (1 if edge == 'lower' else 0)
    assert last[0, 0] == (-1 if edge == 'lower' else 1)
    stripe_rows = [[0., bound_type(.25), 0., 0.], [bound_type(.25), 1., 0., 0.]]
    stripe = _check(zones, 0, len(dx), len(dy), stripe_rows, axis=axis,
                    domain=1., dx=dx, dy=dy)
    assert stripe[0, 0] == 0


@pytest.mark.parametrize('domain_type', _TYPES, ids=('python', 'half', 'single', 'double'))
@pytest.mark.parametrize('axis', (0, 1), ids=('x', 'y'))
@pytest.mark.parametrize('nonuniform', (False, True), ids=('uniform', 'widths'))
@pytest.mark.parametrize('domain_value', (.03, .182, .042))
def test_stripes_keep_domain_dtype_and_strong_point_comparisons(
        zones, domain_type, axis, nonuniform, domain_value):
    nx, ny = 13, 7
    domain = domain_type(domain_value)
    options = dict(axis=axis, domain=domain)
    if nonuniform:
        dx, dy = np.arange(1., nx + 1), np.arange(1., ny + 1)
        options.update(dx=dx * float(domain) / dx.sum(),
                       dy=dy * float(domain) / dy.sum())
    # A cut near an actual point makes the retained point dtype observable in IDs.
    count = nx if axis == 0 else ny
    if nonuniform:
        widths = options['dx' if axis == 0 else 'dy']
        points = (np.cumsum(widths) - .5 * widths) / domain
    else:
        spacing = domain / count
        points = np.array([(k + .5) * spacing / domain for k in range(count)])
    cut = np.float16(points[count // 3])
    rows = [[0., cut, 0., 0.], [cut, np.float32(.75), 0., 0.],
            [np.float32(.75), np.float64(1.), 0., 0.]]
    _check(zones, 0, nx, ny, rows, **options)


@pytest.mark.parametrize('axis', (0, 1), ids=('x', 'y'))
def test_stripes_keep_first_hit_and_last_row_gap_value(zones, axis):
    # Configuration validation permits these sub-1e-9 gaps and overlaps.
    rows = [[0., .5 - 2e-10, 0., 0.], [.5 + 2e-10, .75, 0., 0.],
            [.75, 1., 0., 0.]]
    ids = _check(zones, 0, 3, 3, rows, axis=axis, domain=.06)
    assert np.all((ids[:, 1] if axis == 1 else ids[1, :]) == 2)
    overlap = [[0., .5 + 2e-10, 0., 0.], [.5 - 2e-10, 1., 0., 0.]]
    ids = _check(zones, 0, 3, 3, overlap, axis=axis, domain=.06)
    assert np.all((ids[:, 1] if axis == 1 else ids[1, :]) == 0)


def test_python_configuration_keeps_sort_and_weak_wall_limit(zones):
    from sjtu_tpmshx.shared.models.zone_config import Zone, ZoneConfig

    config = ZoneConfig([Zone('last', .5, 1., 8., np.float16(.1)),
                         Zone('first', 0., .5, 4., np.float16(.1))], 'Diamond', 16.)
    config.validate()
    assert [zone.name for zone in config.zones] == ['first', 'last']
    assert all(type(zone.t_mm) is np.float16 for zone in config.zones)
    rows = [[zone.y_frac_start, zone.y_frac_end, 0., 0.] for zone in config.zones]
    _check(zones, 0, 3, 3, rows, axis=1, domain=.03)


@pytest.mark.parametrize('kind', (1, 2), ids=('first-2d', 'last-3d'))
def test_rectangles_keep_overlap_and_uncovered_values(zones, kind):
    rows = [[0., .5, 0., 1.], [0., 1., 0., .2]]
    ids = _check(zones, kind, 3, 3, rows, dx=np.array([.01, .02, .03]),
                 dy=np.array([.003, .007, .02]))
    expected = ([[0, 0, 0], [0, 0, 0], [1, 0, 0]] if kind == 1
                else [[1, 0, 0], [1, 0, 0], [1, -1, -1]])
    np.testing.assert_array_equal(ids, expected)


def test_3d_empty_rows_keep_default_ids(zones):
    ids = _check(zones, 2, 1, 2, [], dx=np.array([.06]), dy=np.array([.01, .02]))
    np.testing.assert_array_equal(ids, [[-1, -1]])


@pytest.mark.parametrize('kind', (1, 2), ids=('first-2d', 'last-3d'))
def test_assignment_does_not_change_strided_readonly_widths(zones, kind):
    dx = np.arange(1., 11., dtype=np.float64)[::2]
    dy = np.arange(1., 9., dtype=np.float64)[::2]
    dx.flags.writeable = False
    dy.flags.writeable = False
    _check(zones, kind, len(dx), len(dy), [[0., .4, 0., 1.], [.3, 1., .25, .9]],
           dx=dx, dy=dy)


@pytest.mark.parametrize('kind', (1, 2), ids=('first-2d', 'last-3d'))
@pytest.mark.parametrize('nan_index', range(4), ids=('x0', 'x1', 'y0', 'y1'))
def test_raw_comparison_with_nan_does_not_select_a_rectangle(zones, kind, nan_index):
    # Formal configuration rejects NaN. The low-level comparator still uses <=, not !<.
    row = [0., 1., 0., 1.]
    row[nan_index] = np.nan
    rows = [[.875, 1., .875, 1.], row]
    ids = _check(zones, kind, 2, 2, rows, dx=np.ones(2), dy=np.ones(2))
    np.testing.assert_array_equal(ids, np.full((2, 2), 0 if kind == 1 else -1, dtype=np.int32))


@pytest.mark.parametrize('shape', ((1, 1), (1, 2), (2, 1), (2, 3), (7, 5), (17, 19), (33, 21)))
@pytest.mark.parametrize('pattern', ('constant', 'impulse', 'asymmetric'))
def test_fixed_gaussian_keeps_short_axes_and_both_filter_passes(zones, shape, pattern):
    rng = np.random.default_rng(20261110)
    if pattern == 'constant':
        values = np.full(shape, .37)
    elif pattern == 'impulse':
        values = np.zeros(shape)
        values[0, -1] = 1.
    else:
        values = rng.normal(size=shape) + np.arange(shape[0])[:, None] * .17
    before = values.copy()
    expected = frozen.gaussian(values)
    actual = zones.gaussian(values)
    np.testing.assert_allclose(actual, expected, rtol=0., atol=1e-13)
    np.testing.assert_array_equal(values, before)
    assert actual.shape == shape and actual.dtype == np.float64
    assert actual.flags.c_contiguous and actual.flags.writeable
    assert not np.shares_memory(actual, values)
    again = zones.gaussian(values)
    np.testing.assert_array_equal(actual, again)
    assert not np.shares_memory(actual, again)


@pytest.mark.parametrize('layout', ('fortran', 'strided', 'readonly'))
def test_gaussian_owns_outputs_for_nonstandard_input_storage(zones, layout):
    values = np.arange(63., dtype=np.float64).reshape(9, 7)
    if layout == 'fortran':
        values = np.asfortranarray(values)
    elif layout == 'strided':
        values = values[::2, ::2]
    else:
        values.flags.writeable = False
    expected = frozen.gaussian(values)
    actual = zones.gaussian(values)
    np.testing.assert_allclose(actual, expected, rtol=0., atol=1e-13)
    assert actual.flags.c_contiguous and actual.flags.writeable
    assert not np.shares_memory(actual, values)


def test_3d_assignment_smooths_L_and_t_before_z_extrusion(zones):
    dx, dy = np.array([.01, .02, .03]), np.array([.003, .007, .02])
    rows = [[0., .5, 0., 1., np.float32(4.), np.float16(.3)],
            [0., 1., 0., .2, np.float16(8.), np.float32(.5)]]
    bounds = [row[:4] for row in rows]
    ids = _check(zones, 2, 3, 3, bounds, dx=dx, dy=dy)
    raw_length, raw_wall = np.full((3, 3), 6.), np.full((3, 3), .4)
    for index, row in enumerate(rows):
        raw_length[ids == index] = float(row[4])
        raw_wall[ids == index] = float(row[5])
    expected = frozen.rectangle_fields_3d(rows, dx, dy, 6., .4)
    actual = zones.gaussian(raw_length), zones.gaussian(raw_wall)
    for field, reference in zip(actual, expected):
        np.testing.assert_allclose(field, reference, rtol=0., atol=1e-13)
        np.testing.assert_allclose(np.repeat(field[:, :, None], 3, axis=2),
                                   np.repeat(reference[:, :, None], 3, axis=2),
                                   rtol=0., atol=1e-13)


class _Scalar(ct.Structure):
    _fields_ = [('value', ct.c_double), ('precision', ct.c_uint32), ('strong', ct.c_uint32)]


def _pointer(values, dtype):
    return values.ctypes.data_as(ct.POINTER(dtype))


@pytest.fixture
def raw_api(zones):
    # Keep test argtypes separate from the cached application function objects.
    library = ct.CDLL(_native_geometry._library().path)
    size, doublep = ct.c_size_t, ct.POINTER(ct.c_double)
    intp, scalarp, errorp = ct.POINTER(ct.c_int32), ct.POINTER(_Scalar), ct.POINTER(ct.c_char)
    assign = library.tpmshx_geometry_zone_ids_v1
    assign.argtypes = [ct.c_uint32, size, size, ct.c_int, _Scalar, scalarp, size,
                       doublep, size, doublep, size, intp, size, errorp, size]
    assign.restype = ct.c_int
    gaussian = library.tpmshx_geometry_zone_gaussian_v1
    gaussian.argtypes = [size, size, doublep, size, doublep, size, errorp, size]
    gaussian.restype = ct.c_int
    yield assign, gaussian


@pytest.mark.parametrize('failure', ('extent', 'null-rows', 'row-overflow', 'misaligned-rows'))
def test_zone_c_boundary_rejects_bad_buffers_before_output_write(raw_api, failure):
    assign, _ = raw_api
    rows = (_Scalar * 4)(*(_Scalar(value, 64, 0) for value in (0., 1., 0., 1.)))
    row_pointer, row_count = ct.cast(rows, ct.POINTER(_Scalar)), 1
    ids = np.full((2, 2), 919, dtype=np.int32)
    output_count = ids.size
    if failure == 'extent':
        output_count -= 1
    elif failure == 'null-rows':
        row_pointer = None
    elif failure == 'row-overflow':
        row_count = np.iinfo(np.uintp).max // 4 + 1
    else:
        unaligned = ct.create_string_buffer(ct.sizeof(rows) + 1)
        row_pointer = ct.cast(ct.byref(unaligned, 1), ct.POINTER(_Scalar))
    error = ct.create_string_buffer(8)
    status = assign(1, 2, 2, 1, _Scalar(1., 64, 0), row_pointer, row_count,
                    None, 0, None, 0, _pointer(ids, ct.c_int32), output_count, error, len(error))
    assert status == 1
    assert error.value and b'\0' in error.raw
    np.testing.assert_array_equal(ids, np.full((2, 2), 919, dtype=np.int32))


@pytest.mark.parametrize('failure', ('input-extent', 'output-extent', 'shape-overflow', 'null-input'))
def test_gaussian_c_boundary_keeps_outputs_on_invalid_input(raw_api, failure):
    _, gaussian = raw_api
    values = np.arange(6., dtype=np.float64).reshape(2, 3)
    output = np.full((2, 3), 919., dtype=np.float64)
    nx, ny, input_count, output_count = 2, 3, values.size, output.size
    input_pointer = _pointer(values, ct.c_double)
    if failure == 'input-extent':
        input_count -= 1
    elif failure == 'output-extent':
        output_count -= 1
    elif failure == 'shape-overflow':
        nx = np.iinfo(np.uintp).max
    else:
        input_pointer = None
    error = ct.create_string_buffer(8)
    status = gaussian(nx, ny, input_pointer, input_count, _pointer(output, ct.c_double),
                      output_count, error, len(error))
    assert status == 1
    assert error.value and b'\0' in error.raw
    np.testing.assert_array_equal(output, np.full((2, 3), 919.))
