"""Compare selected-zone native float64 arithmetic with the frozen Python helper."""
from types import SimpleNamespace

import numpy as np
import pytest

from tests.python import zone_statistics_reference as reference
from tests.python.native_adapters.test_native_result_balance import assert_observation, assert_values, observe
from sjtu_tpmshx.cpp_interface import _native_result as core
from sjtu_tpmshx.cpp_interface import _native_result_balance as native
from sjtu_tpmshx.physical_models.zone_config import compute_zone_statistics


def _inputs(dtype=np.float64, shape=(17, 11), weights=None):
    rng = np.random.default_rng(61024)
    values = rng.uniform(300., 400., shape).astype(dtype)
    if np.dtype(dtype).kind in 'iu':
        values = (np.arange(np.prod(shape)).reshape(shape) % 37).astype(dtype)
    zone_id = (np.arange(np.prod(shape)).reshape(shape) % 3).astype(np.int32)
    zones = [SimpleNamespace(name='first', L_mm=6., t_mm=.4),
             SimpleNamespace(name='second', L_mm=7., t_mm=.5),
             SimpleNamespace(name='third', L_mm=8., t_mm=.6),
             SimpleNamespace(name='empty', L_mm=5., t_mm=.35)]
    data = dict(Ta=values.copy(), Tb=values.copy(), Ts=values.copy(), zone_id=zone_id, zones=zones)
    if weights is not None:
        data['cell_area'] = rng.uniform(.01, .03, shape).astype(weights)
    return data


def _as_float64(data):
    converted = dict(data)
    for key in ('Ta', 'Tb', 'Ts', 'u', 'v', 'P', 'cell_area'):
        if key in converted and converted[key] is not None:
            converted[key] = np.asarray(converted[key], dtype=np.float64)
    return converted


@pytest.mark.parametrize('dtype', [np.float64, np.float32, np.int32, np.int64])
@pytest.mark.parametrize('weights', [None, np.float64, np.float32])
def test_zone_mean_std_and_extrema_match_float64_reference(dtype, weights):
    data = _inputs(dtype, weights=weights)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**_as_float64(data))))


@pytest.mark.parametrize('dtype', ['>f8', '<f8', '>f4'])
@pytest.mark.parametrize('weights', [None, '>f8'])
def test_zone_selection_keeps_explicit_byte_order(dtype, weights):
    data = _inputs(dtype, weights=weights)
    for name in ('Ta', 'Tb', 'Ts'):
        data[name] = data[name].astype(dtype)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**_as_float64(data))))


@pytest.mark.parametrize('layout', ['F', 'transpose', 'negative', 'step'])
@pytest.mark.parametrize('weights', [None, np.float64])
def test_zones_keep_c_order_selection_before_reduction(layout, weights):
    data = _inputs(np.float64, (137, 11), weights)
    for name in ('Ta', 'Tb', 'Ts', 'zone_id', 'cell_area'):
        if name not in data:
            continue
        value = data[name]
        data[name] = (np.asfortranarray(value) if layout == 'F' else value.T if layout == 'transpose'
                      else value[::-1, ::-1] if layout == 'negative' else value[::2, ::2])
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('weights', [None, np.float64])
def test_optional_velocity_and_pressure_match_float64_reference(weights):
    data = _inputs(np.float64, (3, 4), weights)
    values = (np.arange(12).reshape(3, 4) % 4).astype(np.float64)
    data.update(u=values, v=values[::-1], P=values)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('weights', ['negative', 'zero', 'nan'])
def test_weight_protocol_has_no_new_positive_or_finite_guard(weights):
    data = _inputs(np.float64, (2, 3), np.float64)
    data['cell_area'][:] = {'negative': -1., 'zero': 0., 'nan': np.nan}[weights]
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('bad_dtype', [np.bool_, np.complex128, object])
def test_non_real_zone_arrays_raise_type_error(bad_dtype):
    values = np.ones((2, 3), dtype=bad_dtype)
    with pytest.raises(TypeError):
        native.zone_mean(values)
    with pytest.raises(TypeError):
        native.zone_power_two(values)


def test_bad_v_selection_keeps_earlier_power_overflow_warning():
    data = _inputs(np.float64, (2, 3))
    data.update(u=np.full((2, 3), np.finfo(np.float64).max, dtype=np.float64),
                v=np.ones((1, 3), dtype=np.float64))
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


def test_empty_zone_records_need_no_native_call(monkeypatch):
    data = _inputs(np.float64, (2, 3))
    data['zone_id'][:] = 99
    def forbidden(*args, **kwargs):
        pytest.fail('empty zone records called native math')
    monkeypatch.setattr(core, 'call', forbidden)
    assert_values(compute_zone_statistics(**data), reference.compute_zone_statistics(**data))


def test_speed_intermediates_return_float64():
    values = np.array([0., 1., 2., 3.], dtype=np.float64)
    first = native.zone_power_two(values)
    second = native.zone_power_two(values[::-1])
    np.testing.assert_array_equal(first, values ** 2)
    assert first.dtype == np.float64
    actual = native.zone_speed_from_squared(first, second)
    expected = np.sqrt(values ** 2 + values[::-1] ** 2)
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == np.float64


@pytest.mark.parametrize('label_dtype', [np.int32, np.int64, np.uint8])
def test_saved_zone_summary_matches_independent_temperature_statistics(label_dtype):
    from sjtu_tpmshx.cpp_interface._native_result_stage import _zone_temperatures

    data = _inputs(shape=(17, 11))
    data['Tb'] = data['Tb'].T.copy().T + 23.0
    data['Ts'] = data['Ts'][::-1]
    data['zone_id'] = data['zone_id'].astype(label_dtype)
    data['zone_id'][0, :2] = (np.iinfo(np.int32).max if label_dtype != np.uint8 else 255, 42)
    if np.issubdtype(label_dtype, np.signedinteger):
        data['zone_id'][0, 2] = -1
    widths = (np.linspace(.01, .10, 17), np.linspace(.02, .11, 11))
    data['cell_area'] = np.multiply.outer(*widths)
    expected = reference.compute_zone_statistics(**data)
    zones = [(zone.name, zone.L_mm, zone.t_mm) for zone in data['zones']]
    actual, x, y = _zone_temperatures(widths, [data[key] for key in ('Ta', 'Tb', 'Ts')], data['zone_id'],
                                       zones, (2., 3.), ([.75, .125], [.5]))
    assert x == [1.5, .25] and y == [1.5]
    assert_values(actual, expected)


def test_saved_zone_summary_rejects_out_of_range_or_non_integer_labels():
    from sjtu_tpmshx.cpp_interface._native_result_stage import _zone_temperatures

    data = _inputs(shape=(4, 4))
    widths = (np.ones(4), np.ones(4))
    temps = [data[key] for key in ('Ta', 'Tb', 'Ts')]
    zones = [(zone.name, zone.L_mm, zone.t_mm) for zone in data['zones']]
    with pytest.raises(ValueError, match='int32'):
        _zone_temperatures(widths, temps, np.full((4, 4), 2**31, dtype=np.int64), zones, (4., 4.), ((), ()))
    with pytest.raises(TypeError):
        _zone_temperatures(widths, temps, np.zeros((4, 4), dtype=np.float64), zones, (4., 4.), ((), ()))
