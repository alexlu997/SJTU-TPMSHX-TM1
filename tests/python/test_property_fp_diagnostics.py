"""Ordered floating-point diagnostics stay separate from atomic numeric outputs."""
import ctypes as ct
import warnings

import numpy as np
import pytest

from tests.python import float64_oracle as oracle
from tests.python import nu_reference, property_reference
from sjtu_tpmshx.cpp_interface import _native_properties as native
from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library


def observation(function, mode, *, is_reference=False):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all=mode):
        warnings.simplefilter('always')
        warnings.simplefilter('ignore', UserWarning)
        try:
            value = function()
        except Exception as error:
            if is_reference:
                args = tuple(oracle.warning_text(item) if isinstance(item, str) else item for item in error.args)
                result = ('error', type(error), args, oracle.warning_text(str(error)))
            else:
                result = ('error', type(error), error.args, str(error))
        else:
            result = ('value', type(value), value)
    notes = [(item.category, str(item.message)) for item in caught]
    if is_reference:
        notes = [(category, oracle.warning_text(text)) for category, text in notes]
    return result, notes


@pytest.mark.parametrize('mode', ['warn', 'raise', 'ignore'])
def test_float64_nu_zero_division_follows_errstate_policy(mode):
    expected = observation(lambda: oracle.call(
        lambda *values: nu_reference.nu_sco2_topo('Gyroid', *values),
        np.float16(1.), 1e200, 0., 1.), mode, is_reference=True)
    actual = observation(lambda: native.nusselt(
        3, 1, np.float16(1.), 1e200, 0., 1.), mode)
    assert actual == expected


@pytest.mark.parametrize('mode', ['warn', 'raise', 'ignore'])
def test_float64_power_overflow_follows_errstate_policy(mode):
    expected = observation(lambda: oracle.call(property_reference.air_cp, 1e200), mode, is_reference=True)
    actual = observation(lambda: native.empirical(3, 1e200), mode)
    assert actual == expected


def sentinel_result(count):
    result = native._Result(count)
    result.values.fill(101.)
    result.events.fill(0xA1B2C3D4)
    return result


def assert_sentinel(result):
    np.testing.assert_array_equal(result.values, 101.)
    np.testing.assert_array_equal(result.events, 0xA1B2C3D4)


def test_invalid_topology_leaves_result_unchanged():
    _, buffers, inputs = native._inputs((1., 1., 1., 1.))
    result, failure, error = sentinel_result(1), native._Failure(), ct.create_string_buffer(2048)
    status = native._function(preparation_library.get(), 'nu')(
        3, 99, *inputs, 1., result.output, ct.byref(failure), error, len(error))
    assert buffers
    assert status == 1
    assert error.value
    assert_sentinel(result)


def test_error_storage_cannot_write_into_an_input():
    source = np.full(8, 300.125, dtype=np.float64)
    before = source.tobytes()
    argument = native._Input(native._pointer(source), 1)
    result, failure = sentinel_result(1), native._Failure()
    error = ct.cast(source.ctypes.data, ct.POINTER(ct.c_char))
    status = native._function(preparation_library.get(), 'empirical')(
        0, argument, native._Input(), result.output, ct.byref(failure), error, source.nbytes)
    assert status == 1
    assert source.tobytes() == before
    assert_sentinel(result)
