"""Compare the native float64 gradient with the frozen tpms_calc expression."""
import ctypes as ct
import warnings

import numpy as np
import pytest

from tests.python import float64_oracle as oracle
from tests.python.df_reference import pressure_gradient as reference
from sjtu_tpmshx.cpp_interface import _native_df as native


_BASE = (1.2501233, 1.8e-5, 4.71321, 4.8841442670242926e-8, 239.78171583799818)


def _observe(function, values, policy, *, is_reference=False):
    with warnings.catch_warnings(record=True) as notices, np.errstate(all=policy):
        warnings.simplefilter('always')
        try:
            result = oracle.call(function, *values) if is_reference else function(*values)
        except Exception as failure:
            error_args = (tuple(oracle.warning_text(item) if isinstance(item, str) else item for item in failure.args)
                          if is_reference else failure.args)
            observation = ('error', type(failure), error_args)
        else:
            observation = ('result', type(result), result)
    notes = [(type(item.message), str(item.message)) for item in notices]
    if is_reference:
        notes = [(category, oracle.warning_text(text)) for category, text in notes]
    return observation, notes


def _compare(values, policy='warn'):
    expected = _observe(reference, values, policy, is_reference=True)
    actual = _observe(native.pressure_gradient, values, policy)
    assert actual[0][:2] == expected[0][:2]
    if actual[0][0] == 'error':
        assert actual[0][2] == expected[0][2]
    else:
        np.testing.assert_array_equal(actual[0][2], expected[0][2])
        assert np.asarray(actual[0][2]).dtype == np.asarray(expected[0][2]).dtype
        assert np.asarray(actual[0][2]).shape == np.asarray(expected[0][2]).shape
    assert actual[1] == expected[1]
    return actual[0][2]


# The native boundary converts each operand to float64. The sign and layout
# matrices run on float64 operands with one narrow-float check.
@pytest.mark.parametrize('kind,sign', [(float, -1.), (float, 0.), (float, 1.), (np.float16, -1.)])
def test_homogeneous_scalar_types_and_signed_speed(kind, sign):
    values = list(_BASE)
    values[2] *= sign
    _compare(tuple(kind(value) for value in values))


@pytest.mark.parametrize('slot,kind', [(0, np.float16), (3, np.float32)])
def test_single_strong_operand(slot, kind):
    values = list(_BASE)
    values[slot] = kind(values[slot])
    _compare(values)


@pytest.mark.parametrize('dtype,layout', [
    *[(np.float64, layout) for layout in ('scalar-array', 'broadcast', 'strided', 'empty', 'big-endian')],
    (np.float16, 'broadcast'),
])
def test_real_array_shape_dtype_and_ownership(dtype, layout):
    values = [np.asarray(value, dtype=dtype) for value in _BASE]
    if layout == 'broadcast':
        values[2] = np.asarray([[-4.75], [0.], [4.75]], dtype=dtype)
        values[4] = np.asarray([[125., 250.]], dtype=dtype)
    elif layout == 'strided':
        values[2] = np.asarray([-4.75, -2., 0., 2., 4.75, 6.], dtype=dtype)[::-2]
    elif layout == 'empty':
        values[4] = np.empty((0, 2), dtype=dtype)
    elif layout == 'big-endian':
        values[2] = np.asarray([-4.75, 0., 4.75], dtype=dtype).astype(np.dtype(dtype).newbyteorder('>'))
    for value in values:
        value.flags.writeable = False
    before = [value.copy() for value in values]
    result = _compare(values)
    if isinstance(result, np.ndarray):
        assert result.flags.writeable
        assert not any(np.shares_memory(result, value) for value in values)
    for value, original in zip(values, before):
        np.testing.assert_array_equal(value, original)


@pytest.mark.parametrize('policy', ['ignore', 'warn', 'raise'])
@pytest.mark.parametrize('values', [
    (1.2, 1.8e-5, 1e200, 1e-8, 200.),
    (1.2, np.float16(1.8e-5), 1e308, 1e-8, 200.),
    (np.float16(1.2), 1.8e-5, 1., 1e-8, 1e308),
    (1.2, 1.8e-5, 1., 0., 200.),
    (1.2, 1.8e-5, 1., np.float16(0.), 200.),
    (1.2, 1.8e-5, np.inf, 1e-8, 0.),
    (1.2, 1.8e-5, np.nan, 1e-8, 200.),
    (1.2, 1.8e-5, -4.75, -1e-8, -200.),
])
def test_float64_fp_policy(values, policy):
    _compare(values, policy)


def test_empty_gradient_produces_no_fp_events():
    with warnings.catch_warnings(record=True) as notices, np.errstate(all='raise'):
        warnings.simplefilter('always')
        result = native.pressure_gradient(np.empty((0, 2)), 1.8e-5, 1e308, 0., 200.)
    assert isinstance(result, np.ndarray) and result.shape == (0, 2) and result.dtype == np.float64
    assert notices == []


def _raw_gradient(values):
    properties = native._properties
    shape, buffers, inputs = properties._inputs(values)
    output, failure = properties._Result(buffers[0].size), native._FPFailure()
    output.values.fill(-12345.)
    output.events.fill(0x5a5a5a5a)
    before = (output.values.copy(), output.events.copy())
    owner = ct.CDLL(native.preparation_library.get().path)
    function = owner.tpmshx_preparation_df_pressure_gradient_v1
    function.argtypes = [*native._SIGNATURES['pressure_gradient'], *native._ERROR]
    function.restype = ct.c_int
    return owner, function, shape, buffers, inputs, output, failure, before


def _unchanged(output, before):
    for value, original in zip((output.values, output.events), before):
        np.testing.assert_array_equal(value, original)


def test_raw_gradient_event_extent_rejection_is_atomic():
    owner, function, _shape, buffers, inputs, output, failure, before = _raw_gradient(_BASE)
    output.output.event_count = None
    error = ct.create_string_buffer(256)
    status = function(*inputs, output.output, ct.byref(failure), error, len(error))
    assert owner is not None and buffers and status == 1
    _unchanged(output, before)


def test_raw_gradient_error_storage_cannot_alias_an_input():
    owner, function, _shape, buffers, inputs, output, failure, before = _raw_gradient(_BASE)
    input_before = buffers[0].copy()
    error = ct.cast(buffers[0].ctypes.data, ct.POINTER(ct.c_char))
    status = function(*inputs, output.output, ct.byref(failure), error, buffers[0].nbytes)
    assert owner is not None and status == 1
    _unchanged(output, before)
    np.testing.assert_array_equal(buffers[0], input_before)
