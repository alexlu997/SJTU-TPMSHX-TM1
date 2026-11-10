"""Native sigmoid precision, warnings and mutable LUT contracts."""
import gc
import itertools
import os
import warnings
import weakref

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import sigmoid_reference as reference
from sjtu_tpmshx.shared.models import _native_geometry as geometry
from sjtu_tpmshx.shared.models import _native_lut, _native_sigmoid, sigmoid_field


_TYPES = (float, np.float16, np.float32, np.float64)
_DTYPES = (np.float16, np.float32, np.float64)


@pytest.fixture
def native():
    try:
        geometry._library_path()
    except (FileNotFoundError, RuntimeError) as error:
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(str(error))
        pytest.skip(str(error))
    geometry._library()
    _native_sigmoid._current()
    return sigmoid_field


def _exact(actual, expected):
    if np.isscalar(expected):
        assert type(actual) is type(expected)
    actual, expected = np.asarray(actual), np.asarray(expected)
    assert actual.shape == expected.shape and actual.dtype == expected.dtype
    np.testing.assert_array_equal(actual, expected)


def _controls(kind=float):
    inlet = [[kind(4.1 + .3 * row + .1 * column) for column in range(3)] for row in range(3)]
    outlet = [[kind(7.8 - .2 * row - .1 * column) for column in range(3)] for row in range(3)]
    return (inlet, outlet) if kind is float else (np.asarray(inlet), np.asarray(outlet))


@pytest.mark.parametrize('current,mode', [
    ('baseline(NEON NEON_FP16 ASIMD)', 0), ('baseline(SSE SSE2 SSE3)', 0),
    ('X86_V3', 1), ('X86_V4', 1), ('FMA3__AVX2', 1), ('AVX512F', 1),
    ('baseline(SSE AVX2 FMA3)', 1),
])
def test_float32_exp_uses_actual_numpy_dispatch_metadata(native, monkeypatch, current, mode):
    monkeypatch.setattr(np.lib.introspect, 'opt_func_info',
                        lambda **kwargs: {'exp': {'ff': {'current': current}}})
    binding = _native_sigmoid._Bindings(geometry._library().path)
    assert binding.exp_mode == mode


def test_numpy_float32_kernel_keeps_recorded_windows_counterexample(native, monkeypatch):
    monkeypatch.setattr(_native_sigmoid._current(), 'exp_mode', 1)
    result = native._sigmoid(np.float32(1.4999998807907104), np.float32(.5), np.float32(-.02))
    assert type(result) is np.float32 and float(result) == 1.9287574664184286e-22


@pytest.mark.parametrize('x_type,center_type,width_type', tuple(itertools.product(_TYPES, repeat=3)))
def test_scalar_sigmoid_keeps_weak_and_narrow_operations(native, x_type, center_type, width_type):
    values = x_type(.21875), center_type(.375), width_type(.03125)
    with np.errstate(all='ignore'):
        _exact(native._sigmoid(*values), reference._sigmoid(*values))


@pytest.mark.parametrize('dtype', _DTYPES)
@pytest.mark.parametrize('width', [.02, 0., -.02])
def test_array_sigmoid_keeps_clip_edges_and_nonfinite_masks(native, dtype, width):
    edge = dtype(.5) + np.array([-50., 0., 50.], dtype=dtype) * dtype(.02)
    x = np.r_[edge, np.nextafter(edge, dtype(-np.inf)), np.nextafter(edge, dtype(np.inf)),
              dtype(-np.inf), dtype(np.inf), dtype(np.nan)]
    with np.errstate(all='ignore'):
        _exact(native._sigmoid(x, dtype(.5), dtype(width)), reference._sigmoid(x, dtype(.5), dtype(width)))


@pytest.mark.parametrize('width_type', _TYPES)
def test_scalar_zero_width_keeps_python_error_and_numpy_nonfinite(native, width_type):
    args = .1, .5, width_type(0.)
    with np.errstate(all='ignore'):
        if width_type is float:
            with pytest.raises(ZeroDivisionError):
                reference._sigmoid(*args)
            with pytest.raises(ZeroDivisionError):
                native._sigmoid(*args)
        else:
            _exact(native._sigmoid(*args), reference._sigmoid(*args))


@pytest.mark.parametrize('dtype,control_type,transition_type', tuple(itertools.product(_DTYPES, _TYPES, _TYPES)))
def test_field_keeps_full_like_cast_and_mixed_control_precision(native, dtype, control_type, transition_type):
    xf = np.array([[0., 1 / 3, .75], [.2, 2 / 3, 1.]], dtype=dtype)
    yf = np.array([[0., .1, .4], [.6, .8, 1.]], dtype=_DTYPES[(_DTYPES.index(dtype) + 1) % 3])
    inlet, outlet = _controls(control_type)
    args = (xf, yf, inlet, outlet, control_type(5.75), transition_type(.2), transition_type(.25),
            transition_type(.05), transition_type(.02))
    with np.errstate(all='ignore'):
        _exact(native.sigmoid_field_2d(*args), reference.sigmoid_field_2d(*args))


@pytest.mark.parametrize('dtype', _DTYPES)
@pytest.mark.parametrize('shape', [(0, 3), (2, 0), (1, 1)])
def test_empty_and_single_cell_field_keeps_shape_dtype(native, dtype, shape):
    xf, yf = np.full(shape, .25, dtype=dtype), np.full(shape, .75, dtype=dtype)
    args = (xf, yf, *_controls(), 5.5, .2, .2, .05, .02)
    with np.errstate(all='ignore'):
        _exact(native.sigmoid_field_2d(*args), reference.sigmoid_field_2d(*args))
        _exact(native._sigmoid(xf, .5, .02), reference._sigmoid(xf, .5, .02))


@pytest.mark.parametrize('dtype', _DTYPES)
def test_field_broadcasts_coordinates_and_returns_independent_writable_data(native, dtype):
    xf = np.array([[.1], [.4]], dtype=dtype)
    yf = np.array([[.05, .5, .95]], dtype=dtype)
    inlet, outlet = _controls()
    args = (xf, yf, inlet, outlet, 5.5, .2, .2, .05, .02)
    with np.errstate(all='ignore'):
        first = native.sigmoid_field_2d(*args)
        second = native.sigmoid_field_2d(*args)
        expected = reference.sigmoid_field_2d(*args)
    _exact(first, expected)
    assert first.flags.c_contiguous and first.flags.writeable
    assert not np.shares_memory(first, second)
    assert all(not np.shares_memory(first, value) for value in (xf, yf, np.asarray(inlet), np.asarray(outlet)))
    first.fill(-1.)
    _exact(second, expected)


@pytest.mark.parametrize('dtype', _DTYPES)
@pytest.mark.parametrize('layer_count', [1, 2, 7])
def test_sequential_blend_keeps_layer_order_and_copy_contract(native, dtype, layer_count):
    x = np.array([[.1, .3, .9], [.2, .6, .8]], dtype=dtype)
    layers = [np.full(x.shape, 4.5 + layer / 8, dtype=dtype) for layer in range(layer_count)]
    bounds = [dtype((i + 1) / layer_count) for i in range(layer_count - 1)]
    with np.errstate(all='ignore'):
        actual = native._blend_1d(x, bounds, layers, dtype(.02))
        expected = reference._blend_1d(x, bounds, layers, dtype(.02))
    _exact(actual, expected)
    assert all(not np.shares_memory(actual, layer) for layer in layers)


def _warnings(function, args):
    with np.errstate(over='warn', divide='ignore', invalid='ignore'):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always', RuntimeWarning)
            result = function(*args)
    return result, [(type(item.message), str(item.message)) for item in captured]


@pytest.mark.parametrize('kind', ['values', 'field', 'empty-field', 'empty-blend'])
def test_exp_overflow_warnings_keep_original_ufunc_call_order(native, kind):
    x = np.array([0., .5, 1.], dtype=np.float16)
    if kind == 'values':
        actual, expected = native._sigmoid, reference._sigmoid
        args = x, np.float16(.5), np.float16(.01)
    elif kind == 'empty-blend':
        actual, expected = native._blend_1d, reference._blend_1d
        args = np.array([[0., .5, 1.]], dtype=np.float16), [np.float16(.5)], [np.empty((0, 3)), np.empty((0, 3))], np.float16(.001)
    else:
        actual, expected = native.sigmoid_field_2d, reference.sigmoid_field_2d
        xf, yf = np.meshgrid(x, x, indexing='ij')
        if kind == 'empty-field':
            xf, yf = np.empty((0, 1), dtype=np.float16), x.reshape(1, -1)
        args = xf, yf, *_controls(), 5., np.float16(.2), np.float16(.2), np.float16(.01), np.float16(.001)
    old_result, old_warnings = _warnings(expected, args)
    result, observed = _warnings(actual, args)
    _exact(result, old_result)
    assert observed == old_warnings
    assert any(message == 'overflow encountered in exp' for _, message in old_warnings)


@pytest.mark.parametrize('dtype', _DTYPES)
def test_clip_keeps_narrow_bounds_nonfinite_values_and_ownership(native, dtype):
    edges = np.array([.3, .6], dtype=dtype)
    source = np.r_[dtype(-np.inf), dtype(.2), edges, np.nextafter(edges, dtype(-np.inf)),
                   np.nextafter(edges, dtype(np.inf)), dtype(.7), dtype(np.inf), dtype(np.nan)]
    actual = _native_sigmoid.clip(source, .3, .6)
    _exact(actual, np.clip(source, .3, .6))
    assert actual.flags.c_contiguous and actual.flags.writeable
    assert not np.shares_memory(actual, source)
    empty = np.empty((0, 3), dtype=dtype)
    _exact(_native_sigmoid.clip(empty, .3, .6), np.clip(empty, .3, .6))


def _lut(tmp_path, monkeypatch, *, dtype=np.float64, area_dtype=np.float64,
         shape=(3, 4), descending=False):
    epsilon = np.array([[.7131, .7659, .8317, .8893], [.6877, .7591, .8089, .8713],
                        [.6521, .7193, .7831, .8557]])[:shape[0], :shape[1]].astype(dtype)
    if np.issubdtype(np.dtype(dtype), np.integer):
        epsilon = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    area = np.array([[1534.7, 1629.1, 1735.3, 1811.9], [1477.3, 1599.7, 1689.1, 1793.3],
                     [1391.9, 1511.3, 1637.7, 1743.1]])[:shape[0], :shape[1]].astype(area_dtype)
    def prepared(self):
        self.eps_table, self.A0_table = epsilon, area
    monkeypatch.setattr(sigmoid_field.GeometryLUT, '_precompute', prepared)
    length_range, wall_range = ((8., 4.), (.6, .3)) if descending else ((4., 8.), (.3, .6))
    lut = sigmoid_field.GeometryLUT('Gyroid', L_range=length_range, t_range=wall_range,
                                    n_L=shape[0], n_t=shape[1], N=1, cache_dir=tmp_path)
    old = reference.GeometryLUT(lut.L_vals, lut.t_vals, epsilon, area)
    return lut, old


def _query(lut, old):
    length = np.array([[3., 4., 6.5], [8., 9., np.nan]])
    wall = np.array([.2, .3, .45, .6, .7, .5])
    actual, expected = lut.query(length, wall), old.query(length, wall)
    for actual_values, expected_values in zip(actual, expected):
        assert actual_values.shape == length.shape and actual_values.dtype == np.float64
        np.testing.assert_allclose(actual_values, expected_values, rtol=3e-14, atol=3e-14, equal_nan=True)
        assert actual_values.flags.c_contiguous and actual_values.flags.writeable
    return actual, expected


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.dtype('>f8'), np.int32])
@pytest.mark.parametrize('descending', [False, True])
def test_lut_keeps_each_normalized_table_branch_and_inplace_mutation(native, tmp_path, monkeypatch, dtype, descending):
    lut, old = _lut(tmp_path, monkeypatch, dtype=dtype, descending=descending)
    observed = []
    binding = lut._native_lut.binding
    query = binding.query
    def record(*args):
        observed.append((args[7], args[8]))
        return query(*args)
    monkeypatch.setattr(binding, 'query', record)
    _query(lut, old)
    assert observed[-1] == old.modes()
    lut.eps_table[...] += 1
    lut.A0_table[...] += .125
    _query(lut, old)
    assert observed[-1] == old.modes()
    lut.eps_table.flags.writeable = False
    _query(lut, old)
    assert observed[-1] == old.modes()
    lut.eps_table.flags.writeable = True
    _query(lut, old)
    assert observed[-1] == old.modes()


def test_lut_area_mode_is_independent_of_epsilon_mode(native, tmp_path, monkeypatch):
    lut, old = _lut(tmp_path, monkeypatch, area_dtype=np.float32)
    observed = []
    binding = lut._native_lut.binding
    query = binding.query
    def record(*args):
        observed.append((args[7], args[8]))
        return query(*args)
    monkeypatch.setattr(binding, 'query', record)
    _query(lut, old)
    assert observed[-1] == old.modes() == (1, 0)


@pytest.mark.parametrize('shape', [(1, 4), (3, 1), (1, 1)])
@pytest.mark.parametrize('dtype', [np.float32, np.float64])
@pytest.mark.parametrize('descending', [False, True])
def test_lut_singleton_axes_keep_extrapolation_and_nan(native, tmp_path, monkeypatch, shape, dtype, descending):
    lut, old = _lut(tmp_path, monkeypatch, shape=shape, dtype=dtype, descending=descending)
    _query(lut, old)
    actual = lut.query(np.empty((0, 2)), np.empty(0))
    assert all(value.shape == (0, 2) and value.dtype == np.float64 and value.flags.writeable
               for value in actual)


def test_lut_owns_results_and_keeps_captured_tables_after_attribute_rebinding(native, tmp_path, monkeypatch):
    lut, old = _lut(tmp_path, monkeypatch)
    actual, _ = _query(lut, old)
    assert not np.shares_memory(actual[0], actual[1])
    assert all(not np.shares_memory(value, source)
               for value in actual for source in (lut.eps_table, lut.A0_table, lut.L_vals, lut.t_vals))
    area_before = actual[1].copy()
    actual[0].fill(-1.)
    np.testing.assert_array_equal(actual[1], area_before)
    lut.eps_table, lut.A0_table = np.full((3, 4), .1), np.full((3, 4), 1.)
    _query(lut, old)


@pytest.mark.parametrize('dtype', [np.float32, np.float64])
def test_lut_allows_nan_table_mutation_without_rejecting_the_query(native, tmp_path, monkeypatch, dtype):
    lut, old = _lut(tmp_path, monkeypatch, dtype=dtype)
    lut.eps_table[0, 0] = np.nan
    _query(lut, old)


@pytest.mark.parametrize('descending', [False, True])
def test_lut_keeps_axis_reference_and_descending_copy_rules(native, tmp_path, monkeypatch, descending):
    lut, old = _lut(tmp_path, monkeypatch, descending=descending)
    lut.L_vals[1] = 6.25 if not descending else 5.75
    _query(lut, old)


def test_lut_owner_keeps_creating_binding_after_loader_cache_eviction(native, tmp_path, monkeypatch):
    lut, old = _lut(tmp_path, monkeypatch)
    binding_ref = weakref.ref(lut._native_lut.binding)
    _native_lut._bindings.cache_clear()
    geometry._load_library.cache_clear()
    gc.collect()
    assert binding_ref() is lut._native_lut.binding
    def forbidden(*args, **kwargs):
        pytest.fail('existing LUT reloaded a library for its query')
    monkeypatch.setattr(geometry, '_library', forbidden)
    monkeypatch.setattr(_native_lut, '_bindings', forbidden)
    _query(lut, old)


def test_lut_pairs_ravel_counts_and_rejects_mismatched_counts(native, tmp_path, monkeypatch):
    lut, old = _lut(tmp_path, monkeypatch)
    _query(lut, old)
    for owner in (lut, old):
        with pytest.raises(ValueError):
            owner.query(np.ones((2, 3)), np.ones(5))
