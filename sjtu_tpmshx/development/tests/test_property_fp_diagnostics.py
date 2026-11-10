"""Ordered floating-point diagnostics stay separate from atomic numeric outputs."""
import ctypes as ct
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import nu_reference, property_reference
from sjtu_tpmshx.shared.models import _native_properties as native
from sjtu_tpmshx.shared.models._native_preparation import _library


def observation(function, mode):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all=mode):
        warnings.simplefilter('always')
        warnings.simplefilter('ignore', UserWarning)
        try:
            value = function()
        except Exception as error:
            result = ('error', type(error), error.args, str(error))
        else:
            result = ('value', type(value), value)
    return result, [(value.category, str(value.message)) for value in caught]


@pytest.mark.parametrize('mode', ['warn', 'raise', 'ignore'])
def test_prior_cast_event_precedes_later_python_division_error(mode):
    expected = observation(lambda: nu_reference.nu_sco2_topo(
        'Gyroid', np.float16(1.), 1e200, 0., 1.), mode)
    actual = observation(lambda: native.nusselt(
        3, 1, np.float16(1.), 1e200, 0., 1.), mode)
    assert actual == expected


def test_python_power_overflow_keeps_original_exception_arguments():
    expected = observation(lambda: property_reference.air_cp(1e200), 'ignore')
    actual = observation(lambda: native.empirical(3, 1e200), 'ignore')
    assert actual == expected


def sentinel_result(count):
    result = native._Result(count)
    result.real.fill(101.)
    result.imaginary.fill(102.)
    result.kind = native._Scalar(103., 17, 19)
    result.category.value = 23
    result.events.fill(0xA1B2C3D4)
    result.output.kind = ct.pointer(result.kind)
    return result


def assert_sentinel(result):
    np.testing.assert_array_equal(result.real, 101.)
    np.testing.assert_array_equal(result.imaginary, 102.)
    assert (result.kind.value, result.kind.precision, result.kind.strong) == (103., 17, 19)
    assert result.category.value == 23
    np.testing.assert_array_equal(result.events, 0xA1B2C3D4)


def test_terminal_failure_publishes_only_error_diagnostics():
    _, buffers, inputs = native._inputs((np.float16(1.), 1e200, 0., 1.))
    result, failure, error = sentinel_result(1), native._Failure(), ct.create_string_buffer(2048)
    status = native._function(_library(), 'nu')(
        3, 1, *inputs, native._scalar(1.), result.output, ct.byref(failure), error, len(error))
    assert buffers
    assert status == 3
    assert failure.fp.python_cause == 1
    assert failure.fp.event_count <= native._EVENTS
    events = list(failure.fp.events)[:failure.fp.event_count]
    assert any((event >> 8) & 255 == 8 and event & 4 for event in events)
    assert_sentinel(result)


def test_error_storage_cannot_write_into_an_input():
    source = np.full(8, 300.125, dtype=np.float64)
    before = source.tobytes()
    argument = native._Input(native._pointer(source), 1, native._Scalar(0., 64, 0), 0)
    result, failure = sentinel_result(1), native._Failure()
    error = ct.cast(source.ctypes.data, ct.POINTER(ct.c_char))
    status = native._function(_library(), 'empirical')(
        0, argument, native._Input(), result.output, ct.byref(failure), error, source.nbytes)
    assert status == 1
    assert source.tobytes() == before
    assert_sentinel(result)
