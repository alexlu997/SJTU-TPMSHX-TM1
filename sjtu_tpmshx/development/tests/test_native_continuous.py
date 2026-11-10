"""Check field C buffers, captured owners and independent SciPy behavior.

This candidate is unexecuted. Promote it to development/tests with the binding.
The existing continuous-field suites remain the main numerical acceptance.
The reference expressions below come from the pre-port evaluate_axes body.
They do not import a production field evaluator to calculate expected values.
"""

import ctypes as ct
import gc
import os
from types import SimpleNamespace
import weakref

import numpy as np
import pytest
from scipy.interpolate import RectBivariateSpline, make_interp_spline

from sjtu_tpmshx.shared.models import _native_continuous as native
from sjtu_tpmshx.shared.models import _native_geometry


_D = ct.POINTER(ct.c_double)
_S = ct.POINTER(ct.c_size_t)
_A = ct.POINTER(_D)
_H = ct.c_void_p
_HP = ct.POINTER(_H)
_E = ct.POINTER(ct.c_char)
_MAX = np.iinfo(np.uintp).max


@pytest.fixture
def fields():
    try:
        _native_geometry._library_path()
    except (FileNotFoundError, RuntimeError) as error:
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(str(error))
        pytest.skip(str(error))
    native._current()
    return native


def _pointer(values, dtype=ct.c_double):
    return values.ctypes.data_as(ct.POINTER(dtype))


def _misaligned(pointer_type):
    storage = ct.create_string_buffer(64)
    return ct.cast(ct.byref(storage, 1), pointer_type), storage


def _range_overflow(pointer_type):
    # This aligned address plus two double elements exceeds uintptr_t.
    return ct.cast(ct.c_void_p(int(_MAX) - 7), pointer_type)


def _status(function, arguments, expected):
    error = ct.create_string_buffer(32)
    status = function(*arguments, error, len(error))
    assert status == expected, error.value.decode(errors='replace')
    assert b'\0' in error.raw
    if expected:
        assert error.value


@pytest.fixture
def raw(fields):
    # Do not change argtypes on the cached application function objects.
    library = ct.CDLL(fields._current().path)
    create = library.tpmshx_field_xy_create_v1
    create.argtypes = [_D, ct.c_size_t, _D, ct.c_size_t, _D, ct.c_size_t,
                       ct.c_int, ct.c_int, _HP, _E, ct.c_size_t]
    create.restype = ct.c_int
    sample = library.tpmshx_field_xy_sample_v1
    sample.argtypes = [_H, _D, ct.c_size_t, _D, ct.c_size_t, _D, ct.c_size_t,
                       ct.c_double, ct.c_double, _D, ct.c_size_t, _E, ct.c_size_t]
    sample.restype = ct.c_int
    tensor = library.tpmshx_field_tensor_sample_v1
    tensor.argtypes = [ct.c_size_t, _S, _A, _D, ct.c_size_t, ct.c_int, _S, _A,
                       ct.c_double, ct.c_double, _D, ct.c_size_t, _E, ct.c_size_t]
    tensor.restype = ct.c_int
    release = library.tpmshx_field_xy_release_v1
    release.argtypes, release.restype = [_H], None
    yield SimpleNamespace(create=create, sample=sample, tensor=tensor, release=release)


def _data():
    x = np.array([0., .017, .043, .091, .182])
    y = np.array([0., .009, .021, .042])
    values = 5. + np.sin(x[:, None] * 13.) + .3 * np.cos(y[None, :] * 83.)
    return x, y, np.ascontiguousarray(values)


@pytest.fixture
def owner(raw):
    x, y, values = _data()
    handle = _H()
    _status(raw.create, [_pointer(x), x.size, _pointer(y), y.size,
                        _pointer(values), values.size, 3, 3, ct.byref(handle)], 0)
    assert handle.value
    try:
        yield SimpleNamespace(handle=handle, x=x, y=y, values=values)
    finally:
        raw.release(handle)


@pytest.mark.parametrize('failure', (
    'owner-slot', 'x-alignment', 'y-alignment', 'values-alignment',
    'x-range', 'values-range', 'extent', 'count-range',
))
def test_xy_create_checks_all_buffers_before_publishing_an_owner(raw, failure):
    x, y, values = _data()
    slot = _H(0x1234)
    args = [_pointer(x), x.size, _pointer(y), y.size, _pointer(values), values.size,
            3, 3, ct.byref(slot)]
    storage = None
    if failure == 'owner-slot':
        args[8], storage = _misaligned(_HP)
    elif failure.endswith('-alignment'):
        index = {'x-alignment': 0, 'y-alignment': 2, 'values-alignment': 4}[failure]
        args[index], storage = _misaligned(_D)
    elif failure.endswith('-range') and failure != 'count-range':
        args[0 if failure == 'x-range' else 4] = _range_overflow(_D)
    elif failure == 'extent':
        args[5] -= 1
    else:
        args[1] = int(_MAX)
    before = None if storage is None else storage.raw
    _status(raw.create, args, 1)
    assert slot.value == 0x1234
    if storage is not None:
        assert storage.raw == before


@pytest.mark.parametrize('failure', (
    'owner', 'x-alignment', 'y-alignment', 'values-alignment', 'output-alignment',
    'x-range', 'values-range', 'output-range', 'extent',
))
def test_xy_sample_checks_buffers_before_reading_the_owner_or_writing(raw, owner, failure):
    output = np.full((owner.x.size, owner.y.size), -919.)
    args = [owner.handle, _pointer(owner.values), owner.values.size,
            _pointer(owner.x), owner.x.size, _pointer(owner.y), owner.y.size,
            .1, 20., _pointer(output), output.size]
    storage = None
    if failure == 'owner':
        args[0] = _H(1)
    elif failure.endswith('-alignment'):
        index = {'x-alignment': 3, 'y-alignment': 5, 'values-alignment': 1,
                 'output-alignment': 9}[failure]
        args[index], storage = _misaligned(_D)
    elif failure.endswith('-range'):
        args[{'x-range': 3, 'values-range': 1, 'output-range': 9}[failure]] = _range_overflow(_D)
    else:
        args[10] -= 1
    before = None if storage is None else storage.raw
    _status(raw.sample, args, 1)
    np.testing.assert_array_equal(output, np.full(output.shape, -919.))
    if storage is not None:
        assert storage.raw == before


@pytest.mark.parametrize('failure', (
    'counts', 'axes', 'sample-counts', 'points', 'control-axis', 'sample-axis',
    'axis-array-range', 'control-axis-range', 'sample-axis-range',
    'control-count-range', 'sample-count-range', 'output', 'extent',
))
def test_tensor_checks_pointer_arrays_and_element_ranges_before_use(raw, failure):
    axes = (np.array([0., .182]), np.array([.021]), np.array([0., .011, .03]))
    points = (np.array([0., .08, .182]), np.array([0., .042]), np.array([0., .03]))
    counts = (ct.c_size_t * 3)(*(axis.size for axis in axes))
    sample_counts = (ct.c_size_t * 3)(*(point.size for point in points))
    axis_pointers = (_D * 3)(*(_pointer(axis) for axis in axes))
    point_pointers = (_D * 3)(*(_pointer(point) for point in points))
    values = np.arange(6., dtype=np.float64).reshape(2, 1, 3) + 4.
    output = np.full((3, 2, 2), -919.)
    args = [3, counts, axis_pointers, _pointer(values), values.size, 2,
            sample_counts, point_pointers, .1, 20., _pointer(output), output.size]
    storage = None
    if failure in ('counts', 'axes', 'sample-counts', 'points', 'output'):
        index, pointer_type = {'counts': (1, _S), 'axes': (2, _A),
            'sample-counts': (6, _S), 'points': (7, _A), 'output': (10, _D)}[failure]
        args[index], storage = _misaligned(pointer_type)
    elif failure in ('control-axis', 'sample-axis'):
        target = axis_pointers if failure == 'control-axis' else point_pointers
        target[0], storage = _misaligned(_D)
    elif failure == 'axis-array-range':
        args[2] = _range_overflow(_A)
    elif failure in ('control-axis-range', 'sample-axis-range'):
        target = axis_pointers if failure == 'control-axis-range' else point_pointers
        target[0] = _range_overflow(_D)
    elif failure == 'control-count-range':
        counts[0] = int(_MAX)
    elif failure == 'sample-count-range':
        sample_counts[0] = int(_MAX)
    else:
        args[11] -= 1
    before = None if storage is None else storage.raw
    _status(raw.tensor, args, 1)
    np.testing.assert_array_equal(output, np.full(output.shape, -919.))
    if storage is not None:
        assert storage.raw == before


@pytest.mark.parametrize('failure', ('null', 'empty', 'range'))
def test_error_buffer_is_checked_before_owner_publication(raw, failure):
    x, y, values = _data()
    slot = _H(0x1234)
    error = ct.create_string_buffer(b'unchanged')
    pointer, capacity = error, len(error)
    if failure == 'null':
        pointer = None
    elif failure == 'empty':
        capacity = 0
    else:
        pointer, capacity = ct.cast(_H(int(_MAX) - 3), _E), 8
    status = raw.create(_pointer(x), x.size, _pointer(y), y.size, _pointer(values),
                        values.size, 3, 3, ct.byref(slot), pointer, capacity)
    assert status == 1 and slot.value == 0x1234
    assert error.value == b'unchanged'


def test_void_release_accepts_null_and_does_not_delete_a_misaligned_address(raw):
    raw.release(None)
    raw.release(_H(1))


def _old_xy(x, y, values, coordinates, degree_x, degree_y, bounds):
    fit = RectBivariateSpline(x, y, values, kx=degree_x, ky=degree_y)
    sampled = fit(*coordinates, grid=True)
    np.clip(sampled, *bounds, out=sampled)
    return np.ascontiguousarray(sampled)


def _assert_field(actual, expected):
    np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected))
    np.testing.assert_array_equal(np.isposinf(actual), np.isposinf(expected))
    np.testing.assert_array_equal(np.isneginf(actual), np.isneginf(expected))
    finite = np.isfinite(expected)
    np.testing.assert_allclose(actual[finite], expected[finite], rtol=0., atol=1e-13)
    assert actual.shape == expected.shape and actual.dtype == np.float64
    assert actual.flags.c_contiguous and actual.flags.writeable


@pytest.mark.parametrize('degree_x,degree_y', ((1, 3), (2, 2), (3, 1), (3, 3)))
def test_xy_keeps_the_captured_fit_and_current_constant_branch(fields, degree_x, degree_y):
    x, y, values = _data()
    current = values.copy()
    coordinates = (np.linspace(0., .182, 7), np.linspace(0., .042, 5))
    expected = _old_xy(x, y, values, coordinates, degree_x, degree_y, (.1, 20.))
    fit = fields.XYFit(x, y, values, degree_x, degree_y)
    x.fill(np.nan)
    y.fill(np.nan)
    values.fill(np.nan)
    actual = fit.sample(current, coordinates, (.1, 20.))
    _assert_field(actual, expected)
    repeated = fit.sample(current, coordinates, (.1, 20.))
    np.testing.assert_array_equal(actual, repeated)
    assert not np.shares_memory(actual, repeated) and not np.shares_memory(actual, current)
    np.testing.assert_array_equal(fit.sample(np.full(current.shape, 6.), coordinates, (1., 5.)),
                                  np.full(actual.shape, 5.))


@pytest.mark.parametrize('degree', (1, 2, 3))
@pytest.mark.parametrize('scale', (1e300, 1e308))
def test_xy_finite_extreme_controls_keep_old_derived_nonfinite_behavior(fields, degree, scale):
    x, y, _ = _data()
    values = scale * np.linspace(.25, 1., x.size * y.size).reshape(x.size, y.size)
    assert np.isfinite(values).all()
    coordinates = (np.linspace(0., x[-1], 13), np.linspace(0., y[-1], 11))
    expected = _old_xy(x, y, values, coordinates, degree, degree, (.1, 20.))
    fit = fields.XYFit(x, y, values, degree, degree)
    _assert_field(fit.sample(values, coordinates, (.1, 20.)), expected)


@pytest.mark.parametrize('degree', (1, 2, 3))
def test_xy_accepts_finite_extreme_axes_when_old_fit_propagates_overflow(fields, degree):
    # The saved old reference has an infinite internal degree-2 midpoint knot.
    x = np.array([0., 4e307, 8e307, 1.2e308, 1.6e308])
    values = np.arange(25., dtype=np.float64).reshape(5, 5) / 10. + 4.
    coordinates = (np.array([0., 8e307, 1.6e308]),) * 2
    expected = _old_xy(x, x, values, coordinates, degree, degree, (.1, 20.))
    fit = fields.XYFit(x, x, values, degree, degree)
    _assert_field(fit.sample(values, coordinates, (.1, 20.)), expected)
    if degree == 2:
        assert np.isnan(expected).any()


def test_tensor_retains_the_real_scipy_derived_finite_check(fields):
    x = np.array([0., 4e307, 8e307, 1.2e308, 1.6e308])
    nodes = (x, np.array([0., .042]), np.array([.015]))
    values = np.arange(10., dtype=np.float64).reshape(5, 2, 1) + 4.
    coordinates = (np.array([0., 8e307, 1.6e308]), np.array([0., .042]), np.array([0., .03]))
    with pytest.raises(ValueError):
        make_interp_spline(x, values, k=2, axis=0)(coordinates[0])
    with pytest.raises(ValueError):
        fields.tensor_sample(nodes, values, 2, coordinates, (.1, 20.))


@pytest.mark.parametrize('abi,missing', ((2, None), (1, 'xy_sample')))
def test_field_loader_rejects_wrong_abi_and_missing_symbols(monkeypatch, abi, missing):
    def version():
        return abi
    def unused(*args):
        return 0
    symbols = {'tpmshx_field_abi_version_v1': version, 'tpmshx_field_xy_release_v1': unused}
    symbols.update({f'tpmshx_field_{name}_v1': unused
                    for name in native._SIGNATURES if name != missing})
    monkeypatch.setattr(native._native_geometry, '_load_library',
                        lambda path: SimpleNamespace(library=SimpleNamespace(**symbols)))
    match = 'unsupported native field ABI' if abi != 1 else 'lacks field symbol'
    with pytest.raises(ValueError, match=match):
        native._Bindings('field-test-library')


@pytest.mark.parametrize('status,exception', ((1, ValueError), (2, MemoryError), (3, RuntimeError)))
def test_field_status_two_keeps_its_allocation_meaning(status, exception):
    def failed(error, capacity):
        error.value = b'field boundary failure'
        return status
    with pytest.raises(exception, match='field boundary failure'):
        native._call(failed)


def test_fit_keeps_its_creating_library_after_cache_eviction(fields, monkeypatch):
    fields._bindings.cache_clear()
    released = []
    original_release = fields._release
    def observed(binding, destroy, handle):
        released.append(handle.value)
        original_release(binding, destroy, handle)
    monkeypatch.setattr(fields, '_release', observed)
    x, y, values = _data()
    coordinates = (np.linspace(0., x[-1], 7), np.linspace(0., y[-1], 5))
    expected = _old_xy(x, y, values, coordinates, 3, 3, (.1, 20.))
    fit = fields.XYFit(x, y, values, 3, 3)
    handle, fit_ref = fit.handle.value, weakref.ref(fit)
    binding_ref = weakref.ref(fit.binding)
    fields._bindings.cache_clear()
    _native_geometry._load_library.cache_clear()
    def forbidden():
        pytest.fail('an existing XY owner selected a new runtime library')
    monkeypatch.setattr(fields, '_current', forbidden)
    try:
        gc.collect()
        assert binding_ref() is fit.binding and handle not in released
        _assert_field(fit.sample(values, coordinates, (.1, 20.)), expected)
        del fit
        gc.collect()
        assert fit_ref() is None and binding_ref() is None
        assert released.count(handle) == 1
    finally:
        fields._bindings.cache_clear()
        _native_geometry._load_library.cache_clear()
