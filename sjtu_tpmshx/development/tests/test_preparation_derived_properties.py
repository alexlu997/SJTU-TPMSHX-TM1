"""Derived inlet values retain the original arithmetic and result types."""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import property_reference as reference
from sjtu_tpmshx.shared.models import _native_properties, design_fluids


def observe(function):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all='warn'):
        warnings.simplefilter('always')
        try:
            value = function()
        except Exception as error:
            result = ('error', type(error), error.args, str(error))
        else:
            result = ('value', type(value), np.asarray(value))
    return result, [(item.category, str(item.message)) for item in caught]


def equal(actual, expected):
    first, notes = actual
    second, expected_notes = expected
    assert notes == expected_notes
    assert first[:2] == second[:2]
    if first[0] == 'error':
        assert first[2:] == second[2:]
    else:
        assert first[2].dtype == second[2].dtype
        assert first[2].shape == second[2].shape
        np.testing.assert_array_equal(first[2], second[2])
        np.testing.assert_array_equal(np.signbit(first[2]), np.signbit(second[2]))


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('layout', ['scalar', 'zero', 'two', 'empty', 'strided'])
@pytest.mark.parametrize('quantity', ['prandtl', 'surface_transfer'])
def test_derived_typed_order(dtype, layout, quantity):
    base = np.array([1., 1.125, 1.25, 1.5] * 3, dtype=dtype).reshape(3, 4)
    first = {'scalar': dtype(1.25), 'zero': np.array(1.25, dtype=dtype),
             'two': base, 'empty': base[:, :0], 'strided': base[::-1, ::2]}[layout]
    second, third = dtype(1.125), dtype(.75)
    function = getattr(_native_properties, quantity)
    equal(observe(lambda: function(first, second, third)),
          observe(lambda: first * second / third))


@pytest.mark.parametrize('quantity', ['prandtl', 'surface_transfer'])
@pytest.mark.parametrize('arguments', [
    (np.float16(.00002), 1000., .03),
    (.00002, np.float16(1000.), .03),
    (.00002, 1000., np.float16(.03)),
    (np.float32(.00002), 1000., .03),
    (np.float64(.00002), np.float16(1000.), np.float32(.03)),
    (1., 1., 0.),
    (np.float16(1.), 1., 0.),
    (np.array([1., 0., np.nan, np.inf], dtype=np.float32), .75, 0.),
])
def test_derived_mixed_precision_and_error_policy(quantity, arguments):
    first, second, third = arguments
    equal(observe(lambda: getattr(_native_properties, quantity)(*arguments)),
          observe(lambda: first * second / third))


@pytest.mark.parametrize('fluid', ['air', 'water'])
@pytest.mark.parametrize('dtype', [float, int, np.float16, np.float32, np.float64,
                                  np.int16, np.uint16, np.int32, np.int64])
def test_design_prandtl_uses_original_properties_and_order(fluid, dtype):
    temperature, pressure = dtype(300), np.float32(200000.)
    actual = design_fluids.fluid_props(fluid, temperature, pressure)
    expected = reference.fluid_props(fluid, temperature, pressure)
    for name in ('rho', 'mu', 'k', 'cp', 'Pr'):
        equal(observe(lambda: getattr(actual, name)), observe(lambda: getattr(expected, name)))
