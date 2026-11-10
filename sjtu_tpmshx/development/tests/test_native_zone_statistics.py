"""Compare selected-zone native arithmetic with the frozen Python helper."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import zone_statistics_reference as reference
from sjtu_tpmshx.development.tests.test_native_result_balance import assert_observation, assert_values, observe
from sjtu_tpmshx.shared import _native_result as core
from sjtu_tpmshx.shared import _native_result_balance as native
from sjtu_tpmshx.shared.models.zone_config import compute_zone_statistics


def _inputs(dtype=np.float64, shape=(17, 11), weights=None):
    rng = np.random.default_rng(61024)
    values = rng.uniform(300., 400., shape).astype(dtype)
    if np.dtype(dtype).kind == 'c':
        values = values + rng.uniform(-2., 2., shape).astype(dtype) * 1j
    if np.dtype(dtype).kind in 'iu':
        values = (np.arange(np.prod(shape)).reshape(shape) % 37).astype(dtype)
    if np.dtype(dtype).kind == 'b':
        values = np.arange(np.prod(shape)).reshape(shape) % 2 == 0
    zone_id = (np.arange(np.prod(shape)).reshape(shape) % 3).astype(np.int64)
    zones = [SimpleNamespace(name='first', L_mm=6., t_mm=.4),
             SimpleNamespace(name='second', L_mm=7., t_mm=.5),
             SimpleNamespace(name='third', L_mm=8., t_mm=.6),
             SimpleNamespace(name='empty', L_mm=5., t_mm=.35)]
    data = dict(Ta=values.copy(), Tb=values.copy(), Ts=values.copy(), zone_id=zone_id, zones=zones)
    if weights is not None:
        data['cell_area'] = rng.uniform(.01, .03, shape).astype(weights)
    return data


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.longdouble,
                                   np.int8, np.uint8, np.int32, np.uint32, np.int64, np.uint64,
                                   np.complex64, np.complex128])
@pytest.mark.parametrize('weights', [None, np.float16, np.float32, np.float64])
def test_zone_mean_std_and_extrema_keep_original_types(dtype, weights):
    data = _inputs(dtype, weights=weights)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('dtype', ['>i2', '>u8', '>f2', '>f4', '>f8', '>c8', '>c16'])
@pytest.mark.parametrize('weights', [None, '>f4'])
def test_zone_selection_keeps_explicit_byte_order(dtype, weights):
    data = _inputs(dtype, weights=weights)
    for name in ('Ta', 'Tb', 'Ts'):
        data[name] = data[name].astype(dtype)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('layout', ['F', 'transpose', 'negative', 'step'])
@pytest.mark.parametrize('weights', [None, np.float32])
def test_zones_keep_c_order_selection_before_reduction(layout, weights):
    data = _inputs(np.float32, (137, 11), weights)
    for name in ('Ta', 'Tb', 'Ts', 'zone_id', 'cell_area'):
        if name not in data:
            continue
        value = data[name]
        data[name] = (np.asfortranarray(value) if layout == 'F' else value.T if layout == 'transpose'
                      else value[::-1, ::-1] if layout == 'negative' else value[::2, ::2])
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.int16, np.int64,
                                   np.uint64, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('weights', [None, np.float64])
def test_optional_velocity_and_pressure_keep_typed_stages(dtype, weights):
    data = _inputs(np.float64, (3, 4), weights)
    values = (np.arange(12).reshape(3, 4) % 4).astype(dtype)
    data.update(u=values, v=values[::-1], P=values)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.complex64, np.complex128])
@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_zone_fp_and_conversion_positions_remain_independent(dtype, policy):
    data = _inputs(dtype, (137, 11))
    assert_observation(observe(lambda: compute_zone_statistics(**data), policy),
                       observe(lambda: reference.compute_zone_statistics(**data), policy))


@pytest.mark.parametrize('weights', ['negative', 'zero', 'nan'])
def test_weight_protocol_has_no_new_positive_or_finite_guard(weights):
    data = _inputs(np.float32, (2, 3), np.float32)
    data['cell_area'][:] = {'negative': -1., 'zero': 0., 'nan': np.nan}[weights]
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


@pytest.mark.parametrize('object_weights', [False, True])
def test_demonstrated_object_protocols_do_not_dispatch_native(monkeypatch, object_weights):
    data = _inputs(object if not object_weights else np.float64, (2, 3), object if object_weights else None)
    data['P'] = np.ones((2, 3), dtype=data['Ta'].dtype)
    def forbidden(*args, **kwargs):
        pytest.fail('object-only zone protocol called native math')
    monkeypatch.setattr(core, 'call', forbidden)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


def test_object_velocity_preserves_its_original_sqrt_error(monkeypatch):
    data = _inputs(object, (2, 3), np.float64)
    data.update(u=np.ones((2, 3), dtype=object), v=np.ones((2, 3), dtype=object))
    def forbidden(*args, **kwargs):
        pytest.fail('object-only zone protocol called native math')
    monkeypatch.setattr(core, 'call', forbidden)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


def test_bad_v_selection_keeps_earlier_power_overflow_warning():
    data = _inputs(np.float64, (2, 3))
    data.update(u=np.full((2, 3), np.finfo(np.float32).max, dtype=np.float32),
                v=np.ones((1, 3), dtype=np.float32))
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


def test_bad_later_temperature_keeps_earlier_half_std_warning():
    data = _inputs(np.float16, (2, 3))
    data['Ta'][:] = np.finfo(np.float16).max
    data['Tb'] = np.ones((1, 3), dtype=np.float16)
    assert_observation(observe(lambda: compute_zone_statistics(**data)),
                       observe(lambda: reference.compute_zone_statistics(**data)))


def test_empty_zone_records_need_no_native_call(monkeypatch):
    data = _inputs(np.float64, (2, 3))
    data['zone_id'][:] = 99
    def forbidden(*args, **kwargs):
        pytest.fail('empty zone records called native math')
    monkeypatch.setattr(core, 'call', forbidden)
    assert_values(compute_zone_statistics(**data), reference.compute_zone_statistics(**data))


@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.int16, np.int64,
                                   np.uint64, np.float16, np.float32, np.float64])
def test_speed_intermediates_use_exact_compact_dtype(dtype):
    values = np.array([0, 1, 2, 3], dtype=dtype)
    first = native.zone_power_two(values)
    second = native.zone_power_two(values[::-1])
    np.testing.assert_array_equal(first, values ** 2)
    assert first.dtype == (values ** 2).dtype
    actual = native.zone_speed_from_squared(first, second)
    expected = np.sqrt(values ** 2 + values[::-1] ** 2)
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == expected.dtype and actual.nbytes == expected.nbytes
