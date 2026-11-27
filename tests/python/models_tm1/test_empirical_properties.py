"""Float64 empirical values and raw error policy against frozen expressions."""
import warnings

import numpy as np
import pytest

from tests.python import float64_oracle as oracle
from tests.python import property_reference as reference
from sjtu_tpmshx.physical_models import tpms_props


GETTERS = ('air_viscosity', 'air_conductivity', 'air_density', 'air_cp',
           'water_density', 'water_viscosity', 'water_conductivity', 'water_cp')


def observe(module, name, temperature, pressure=None, *, errors='warn', is_reference=False):
    module._range_warnings_emitted.clear()
    function = getattr(module, name)
    with warnings.catch_warnings(record=True) as caught, np.errstate(all=errors):
        warnings.simplefilter('always')
        try:
            if is_reference:
                value = (oracle.call(function, temperature, pressure)
                         if pressure is not None else oracle.call(function, temperature))
            else:
                value = (function(temperature, pressure)
                         if pressure is not None else function(temperature))
        except Exception as error:
            text = oracle.warning_text(str(error)) if is_reference else str(error)
            result = ('error', type(error), text)
        else:
            result = ('value', type(value), np.asarray(value))
    notes = [(item.category, str(item.message)) for item in caught]
    if is_reference:
        notes = [(category, oracle.warning_text(text)) for category, text in notes]
    return result, notes


def equal_observation(actual, expected):
    outcome, notes = actual
    reference_outcome, reference_notes = expected
    assert notes == reference_notes
    assert outcome[:2] == reference_outcome[:2]
    if outcome[0] == 'error':
        assert outcome[2] == reference_outcome[2]
        return
    first, second = outcome[2], reference_outcome[2]
    assert first.shape == second.shape
    assert first.dtype == second.dtype
    np.testing.assert_array_equal(first, second)
    if first.dtype.kind == 'f':
        np.testing.assert_array_equal(np.signbit(first), np.signbit(second))


_SCALAR_TYPES = (float, int, np.float16, np.float32, np.float64, np.int16, np.uint16, np.int32, np.int64)


def _unique(cases):
    return list(dict.fromkeys(cases))


# The native boundary converts each operand to float64 before the getter runs.
# Two getters receive every scalar type. Every getter receives a Python float
# and one narrow float.
@pytest.mark.parametrize('name,dtype', _unique([
    *[(name, dtype) for name in ('air_density', 'water_viscosity') for dtype in _SCALAR_TYPES],
    *[(name, dtype) for name in GETTERS for dtype in (float, np.float16)],
]))
def test_empirical_scalar_type_and_arithmetic(name, dtype):
    temperature = dtype(300 if dtype in (int, np.int16, np.uint16, np.int32, np.int64) else 300.125)
    equal_observation(observe(tpms_props, name, temperature),
                      observe(reference, name, temperature, is_reference=True))


@pytest.mark.parametrize('name,dtype,layout', _unique([
    *[('air_viscosity', dtype, layout) for dtype in (np.float16, np.float64, np.int16)
      for layout in ('zero', 'two', 'empty', 'strided')],
    *[(name, np.float64, 'two') for name in GETTERS],
]))
def test_empirical_array_shape_and_type(name, dtype, layout):
    base = np.array([300.125, 310.25, 290.5, 320.75] * 6, dtype=dtype).reshape(4, 6)
    temperature = {'zero': np.array(300.125, dtype=dtype), 'two': base[:2, :3],
                   'empty': base[:, :0], 'strided': base[::-2, ::2]}[layout]
    equal_observation(observe(tpms_props, name, temperature),
                      observe(reference, name, temperature, is_reference=True))


@pytest.mark.parametrize('temperature,pressure', [
    (300.125, 101325.),
    (300.125, 101325),
    (np.float16(300.125), np.int32(101325)),
    (np.float32(300.125), np.uint32(101325)),
    (np.array([[300.125, 310.25]], dtype=np.float32), np.int64(101325)),
])
def test_air_density_uses_float64_operands(temperature, pressure):
    equal_observation(observe(tpms_props, 'air_density', temperature, pressure),
                      observe(reference, 'air_density', temperature, pressure, is_reference=True))


@pytest.mark.parametrize('direction', [-np.inf, None, np.inf])
def test_water_viscosity_actual_outer_state_and_neighbors(direction):
    point = 300.0624090934865
    temperature = point if direction is None else np.nextafter(point, direction)
    equal_observation(observe(tpms_props, 'water_viscosity', temperature),
                      observe(reference, 'water_viscosity', temperature, is_reference=True))


@pytest.mark.parametrize('name,temperature', [
    *[(name, temperature) for name in GETTERS
      for temperature in (0., -300., float('nan'), [300., 310.])],
    *[('air_viscosity', temperature) for temperature in (
        float('inf'), -float('inf'), np.float16(0), np.float32(-300),
        np.array([0., -300., np.nan, np.inf], dtype=np.float32))],
])
@pytest.mark.parametrize('errors', ['warn', 'raise'])
def test_empirical_raw_warning_and_exception_contract(name, temperature, errors):
    equal_observation(observe(tpms_props, name, temperature, errors=errors),
                      observe(reference, name, temperature, errors=errors, is_reference=True))
