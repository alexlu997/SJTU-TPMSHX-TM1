"""Compare selected-zone native arithmetic with the frozen Python helper."""
import ctypes as ct
import os
import platform
from pathlib import Path
import subprocess
import sys
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


def _stage_hex(value):
    item = np.asarray(value)[()]
    if np.iscomplexobj(item):
        return f'({float(item.real).hex()}, {float(item.imag).hex()})'
    return float(item).hex()


def _assert_zone_stage(actual, expected, *, stage, zone, indices, values, weights, mean, centered, squared, variance):
    actual, expected = np.asarray(actual), np.asarray(expected)
    point = 0 if actual.size and expected.size else None
    if actual.dtype == expected.dtype and actual.shape == expected.shape:
        same = actual == expected
        if actual.dtype.kind in 'fc':
            for part in ('real', 'imag') if actual.dtype.kind == 'c' else ('real',):
                left, right = getattr(actual, part), getattr(expected, part)
                same &= (right != 0) | (np.signbit(left) == np.signbit(right))
        different = np.flatnonzero(~same)
        if not different.size:
            return
        point = int(different[0])
    location = '' if point is None else (
        f' point={point}, actual={_stage_hex(actual.flat[point])}, expected={_stage_hex(expected.flat[point])}')
    rows = '\n'.join(
        f'  selected={index}, source_flat={int(source)}, value={_stage_hex(value)}, '
        f'weight={_stage_hex(weight)}, centered={_stage_hex(center)}, square={_stage_hex(square)}'
        for index, (source, value, weight, center, square) in enumerate(
            zip(indices, values, weights, centered, squared)))
    pytest.fail(
        f'{stage}, zone={zone}: actual dtype={actual.dtype}, shape={actual.shape}; '
        f'expected dtype={expected.dtype}, shape={expected.shape}.{location}\n'
        f'original mean={_stage_hex(mean)}, variance={_stage_hex(variance)}\n{rows}')


@pytest.mark.parametrize('dtype', [np.complex64, np.complex128])
@pytest.mark.parametrize('zone', [0, 1, 2])
@pytest.mark.parametrize('stage', ['mean', 'centered_square', 'weighted_variance', 'sqrt_variance'])
def test_weighted_complex_std_keeps_each_original_stage(dtype, zone, stage):
    data = _inputs(dtype, weights=np.float16)
    mask = np.ravel(data['zone_id']) == zone
    indices = np.flatnonzero(mask)
    values = np.ravel(data['Ta'])[mask]
    weights = np.ravel(data['cell_area'])[mask]
    mean = np.average(values, weights=weights)
    centered = values - mean
    squared = centered ** 2
    variance = np.average(squared, weights=weights)
    # Each native leaf receives the original preceding stage, without accumulated native error.
    if stage == 'mean':
        actual, expected = native.zone_mean(values, weights), mean
    elif stage == 'centered_square':
        actual, expected = native.zone_power_two(centered), squared
    elif stage == 'weighted_variance':
        actual, expected = native.zone_mean(squared, weights), variance
    else:
        operand = np.asarray([variance])
        actual = native.zone_speed_from_squared(operand, np.zeros_like(operand))
        expected = np.asarray([np.sqrt(variance)])
    _assert_zone_stage(actual, expected, stage=stage, zone=zone, indices=indices, values=values,
                       weights=weights, mean=mean, centered=centered, squared=squared, variance=variance)


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


@pytest.mark.parametrize('dtype', [np.complex64, np.complex128])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
def test_complex_sqrt_keeps_precision_special_values_and_fp(dtype, policy):
    limit = np.finfo(np.empty((), dtype=dtype).real.dtype).max
    cases = {
        'windows_variance': [complex(float.fromhex('0x1.64916476bc7c5p+9'),
                                     float.fromhex('0x1.14508ee3c9075p+1'))],
        'signed_zero': [complex(real, imag) for real in (0., -0.) for imag in (0., -0.)],
        'unit': [complex(real, imag) for real in (1., -1.) for imag in (0., -0.)],
        'infinity': [complex(real, imag) for real in (np.inf, -np.inf)
                     for imag in (0., -0., 1., -1., np.inf, -np.inf)]
                    + [complex(real, imag) for real in (0., -0., 1., -1.)
                       for imag in (np.inf, -np.inf)],
        'nan': [complex(np.nan, imag) for imag in (0., -0., 1., -1., np.inf, -np.inf, np.nan)]
               + [complex(real, np.nan) for real in (0., -0., 1., -1., np.inf, -np.inf)],
        'scale': [complex(real, imag) for real in (limit, -limit) for imag in (limit, -limit)]
                 + [complex(limit, -0.), complex(-limit, -0.), complex(-0., limit), complex(-0., -limit)],
    }
    for case, points in cases.items():
        values = np.asarray(points, dtype=dtype)
        # Negative zero components preserve the input zero signs during addition.
        zero = np.full(values.shape, complex(-0., -0.), dtype=dtype)
        actual = observe(lambda: native.zone_speed_from_squared(values, zero), policy)
        expected = observe(lambda: np.sqrt(values + zero), policy)
        assert_observation(actual, expected)
        if expected[0][0] == 'value':
            for part in ('real', 'imag'):
                left, right = getattr(actual[0][1], part), getattr(expected[0][1], part)
                details = f'{case}, {np.dtype(dtype)}, {policy}, {part}'
                np.testing.assert_array_equal(left, right, err_msg=details)
                mask = right == 0
                np.testing.assert_array_equal(np.signbit(left[mask]), np.signbit(right[mask]), err_msg=details)


@pytest.mark.parametrize('operation', ['std', 'power_two'])
def test_invalid_complex_square_mode_preserves_raw_outputs(operation):
    packed = core.array(np.array([1.25 + .75j, -2.5 + .25j], dtype=np.complex64))
    output = core.scalar(9876.5)
    before = bytes(output)
    array_pointer, scalar_pointer = ct.POINTER(core._Array), ct.POINTER(core._Scalar)
    if operation == 'std':
        with pytest.raises(ValueError, match='zone square flag must be zero or one'):
            core.call('tpmshx_result_zone_std_v1',
                [array_pointer, array_pointer, core._UInt, core._UInt, scalar_pointer],
                ct.byref(packed.raw), None, 0, 2, ct.byref(output))
    else:
        values = (ct.c_ubyte * packed.owner.nbytes)(*[0x5A] * packed.owner.nbytes)
        with pytest.raises(ValueError, match='zone square flag must be zero or one'):
            core.call('tpmshx_result_zone_power_two_v1',
                [array_pointer, core._UInt, ct.POINTER(ct.c_ubyte), core._Size, scalar_pointer],
                ct.byref(packed.raw), 2, values, len(values), ct.byref(output))
        assert bytes(values) == bytes([0x5A] * len(values))
    assert bytes(output) == before


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.int64, np.clongdouble])
def test_non_simd_square_types_do_not_query_complex_dispatch(monkeypatch, dtype):
    def forbidden(*args, **kwargs):
        pytest.fail('this dtype does not use a complex SIMD square loop')
    monkeypatch.setattr(np.lib.introspect, 'opt_func_info', forbidden)
    assert native._square_fused(np.dtype(dtype)) == 0


@pytest.mark.parametrize('dtype', [np.complex64, np.complex128])
def test_baseline_x86_v2_square_descriptor_selects_separate_products(monkeypatch, dtype):
    signature = np.dtype(dtype).char * 2
    info = {'square': {signature: {'current': 'baseline(X86_V2)', 'available': 'X86_V3 baseline(X86_V2)'}}}
    monkeypatch.setattr(np.lib.introspect, 'opt_func_info', lambda **kwargs: info)
    assert native._square_fused(dtype) == 0


_X86_SQUARE_CHILD = r'''
import json, os, sys
import numpy as np
from numpy._core import _multiarray_umath as numpy_core
from sjtu_tpmshx.development.tests.test_native_zone_statistics import (
    test_weighted_complex_std_keeps_each_original_stage,
    test_zone_mean_std_and_extrema_keep_original_types,
)
print(json.dumps(dict(numpy=np.__version__, disabled=os.environ.get('NPY_DISABLE_CPU_FEATURES'),
    baseline=list(numpy_core.__cpu_baseline__), dispatch=list(numpy_core.__cpu_dispatch__),
    square=np.lib.introspect.opt_func_info(func_name='^square$', signature='complex64|complex128'))), flush=True)
dtype = np.dtype(sys.argv[1]).type
for zone in (0, 1, 2):
    for stage in ('mean', 'centered_square', 'weighted_variance', 'sqrt_variance'):
        test_weighted_complex_std_keeps_each_original_stage(dtype, zone, stage)
test_zone_mean_std_and_extrema_keep_original_types(dtype, np.float16)
'''


@pytest.mark.skipif(platform.machine().lower() not in ('amd64', 'x86_64'),
                    reason='this regression checks optional x86 square dispatch')
@pytest.mark.parametrize('dtype', [np.complex64, np.complex128])
@pytest.mark.parametrize('mode', ['normal', 'disabled-v3'])
def test_complex_square_matches_fresh_numpy_cpu_dispatch(dtype, mode):
    environment = os.environ.copy()
    environment['TPMSHX_RESULT_LIBRARY'] = core._library().path
    if mode == 'disabled-v3':
        environment['NPY_DISABLE_CPU_FEATURES'] = 'X86_V3'
    else:
        environment.pop('NPY_DISABLE_CPU_FEATURES', None)
    process = subprocess.run([sys.executable, '-c', _X86_SQUARE_CHILD, np.dtype(dtype).name],
        cwd=Path(__file__).resolve().parents[3], env=environment, text=True,
        capture_output=True, timeout=30)
    assert process.returncode == 0, process.stdout + '\n' + process.stderr
