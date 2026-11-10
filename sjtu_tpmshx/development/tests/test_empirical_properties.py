"""Exact empirical values, types and raw error policy against frozen expressions."""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import property_reference as reference
from sjtu_tpmshx.shared.models import tpms_props


GETTERS = ('air_viscosity', 'air_conductivity', 'air_density', 'air_cp',
           'water_density', 'water_viscosity', 'water_conductivity', 'water_cp')


def observe(module, name, temperature, pressure=None, *, errors='warn'):
    module._range_warnings_emitted.clear()
    with warnings.catch_warnings(record=True) as caught, np.errstate(all=errors):
        warnings.simplefilter('always')
        try:
            value = (getattr(module, name)(temperature, pressure)
                     if pressure is not None else getattr(module, name)(temperature))
        except Exception as error:
            result = ('error', type(error), str(error))
        else:
            result = ('value', type(value), np.asarray(value))
    return result, [(item.category, str(item.message)) for item in caught]


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


@pytest.mark.parametrize('name', GETTERS)
@pytest.mark.parametrize('dtype', [float, int, np.float16, np.float32, np.float64,
                                  np.int16, np.uint16, np.int32, np.int64])
def test_empirical_scalar_type_and_arithmetic(name, dtype):
    temperature = dtype(300 if dtype in (int, np.int16, np.uint16, np.int32, np.int64) else 300.125)
    equal_observation(observe(tpms_props, name, temperature), observe(reference, name, temperature))


@pytest.mark.parametrize('name', GETTERS)
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.int16, np.uint16])
@pytest.mark.parametrize('layout', ['zero', 'two', 'empty', 'strided'])
def test_empirical_array_shape_and_type(name, dtype, layout):
    base = np.array([300.125, 310.25, 290.5, 320.75] * 6, dtype=dtype).reshape(4, 6)
    temperature = {'zero': np.array(300.125, dtype=dtype), 'two': base[:2, :3],
                   'empty': base[:, :0], 'strided': base[::-2, ::2]}[layout]
    equal_observation(observe(tpms_props, name, temperature), observe(reference, name, temperature))


@pytest.mark.parametrize('pressure', [101325., 101325, np.float32(101325),
                                      np.int32(101325), np.int64(101325), np.uint32(101325)])
@pytest.mark.parametrize('temperature', [300.125, np.float16(300.125), np.float32(300.125),
                                        np.array([[300.125, 310.25]], dtype=np.float32)])
def test_air_density_preserves_mixed_pressure_order(temperature, pressure):
    equal_observation(observe(tpms_props, 'air_density', temperature, pressure),
                      observe(reference, 'air_density', temperature, pressure))


@pytest.mark.parametrize('direction', [-np.inf, None, np.inf])
def test_water_viscosity_actual_outer_state_and_neighbors(direction):
    point = 300.0624090934865
    temperature = point if direction is None else np.nextafter(point, direction)
    equal_observation(observe(tpms_props, 'water_viscosity', temperature),
                      observe(reference, 'water_viscosity', temperature))


@pytest.mark.parametrize('name', GETTERS)
@pytest.mark.parametrize('temperature', [0., -300., float('nan'), float('inf'), -float('inf'),
                                        np.float16(0), np.float32(-300),
                                        np.array([0., -300., np.nan, np.inf], dtype=np.float32),
                                        [300., 310.]])
@pytest.mark.parametrize('errors', ['warn', 'raise'])
def test_empirical_raw_warning_and_exception_contract(name, temperature, errors):
    equal_observation(observe(tpms_props, name, temperature, errors=errors),
                      observe(reference, name, temperature, errors=errors))
