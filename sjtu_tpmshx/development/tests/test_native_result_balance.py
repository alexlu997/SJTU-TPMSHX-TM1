"""Compare native signed balances with the frozen NumPy evidence reductions."""
import ctypes as ct
from dataclasses import replace
import math
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import result_balance_reference as reference
from sjtu_tpmshx.development.tests.postprocess_tm1.test_physical_balance import sample_result
from sjtu_tpmshx.postprocess import physical_balance
from sjtu_tpmshx.shared import _native_result as core
from sjtu_tpmshx.shared import _native_result_balance as native
from sjtu_tpmshx.shared.domain.portable_data import mutable_data


def observe(function, policy='warn'):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all=policy):
        warnings.simplefilter('always')
        try:
            result = ('value', function())
        except Exception as error:
            result = ('error', type(error), error.args)
    return result, [(item.category, str(item.message)) for item in caught]


def assert_values(actual, expected):
    assert type(actual) is type(expected)
    if isinstance(expected, dict):
        assert list(actual) == list(expected)
        for name in expected:
            assert_values(actual[name], expected[name])
    elif isinstance(expected, (tuple, list)):
        assert len(actual) == len(expected)
        for value, old in zip(actual, expected):
            assert_values(value, old)
    elif isinstance(expected, np.ndarray):
        assert actual.dtype == expected.dtype and actual.shape == expected.shape
        np.testing.assert_array_equal(actual, expected)
    elif isinstance(expected, float):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == expected
            if expected == 0.:
                assert math.copysign(1., actual) == math.copysign(1., expected)
    else:
        assert actual == expected


def assert_observation(actual, expected):
    assert actual[1] == expected[1]
    assert actual[0][0] == expected[0][0]
    if expected[0][0] == 'error':
        assert actual[0][1:] == expected[0][1:]
    else:
        assert_values(actual[0][1], expected[0][1])


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.longdouble,
                                   np.int8, np.uint8, np.int16, np.uint16,
                                   np.int32, np.uint32, np.int64, np.uint64])
@pytest.mark.parametrize('layout', ['C', 'F', 'transpose', 'negative', 'step'])
def test_norms_keep_typed_reductions_and_layout(dtype, layout):
    if np.dtype(dtype).kind == 'f':
        values = np.random.default_rng(61024).uniform(-.3, .7, (137, 11)).astype(dtype)
    else:
        values = (np.arange(1507).reshape(137, 11) % 37).astype(dtype)
    if np.dtype(dtype).kind == 'i':
        values[::2] = -values[::2]
    if layout == 'F':
        values = np.asfortranarray(values)
    elif layout == 'transpose':
        values = values.T
    elif layout == 'negative':
        values = values[::-1, ::-1]
    elif layout == 'step':
        values = values[::2, ::2]
    assert_observation(observe(lambda: physical_balance._norms(values)),
                       observe(lambda: reference._norms(values)))


@pytest.mark.parametrize('dtype', ['>i2', '>u8', '>f2', '>f4', '>f8', '<i2', '<u8', '<f4'])
def test_norms_keep_explicit_byte_order(dtype):
    values = (np.arange(1507).reshape(137, 11) % 37).astype(dtype)
    assert_observation(observe(lambda: physical_balance._norms(values)),
                       observe(lambda: reference._norms(values)))


@pytest.mark.parametrize('dtype', [np.int8, np.int16, np.int32, np.int64, np.uint64])
def test_norms_keep_integer_wrap_before_float(dtype):
    info = np.iinfo(dtype)
    values = np.array([info.min, info.max, info.max, 1, 1, 1, 1, 1], dtype=dtype)
    assert_observation(observe(lambda: physical_balance._norms(values)),
                       observe(lambda: reference._norms(values)))


@pytest.mark.parametrize('dtype', [np.int8, np.int16, np.int32, np.int64])
def test_norms_keep_minimum_integer_absolute_value(dtype):
    values = np.array([np.iinfo(dtype).min], dtype=dtype)
    assert_observation(observe(lambda: physical_balance._norms(values)),
                       observe(lambda: reference._norms(values)))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_norms_keep_finite_input_overflow_policy(dtype, policy):
    values = np.full(137, np.finfo(dtype).max, dtype=dtype)
    assert_observation(observe(lambda: physical_balance._norms(values), policy),
                       observe(lambda: reference._norms(values), policy))


def _mass_inputs(dimension, dtype):
    shape = (7, 5, 3)[:dimension]
    faces = []
    for axis in range(dimension):
        extent = tuple(size + (i == axis) for i, size in enumerate(shape))
        if np.dtype(dtype).kind == 'f':
            values = np.random.default_rng(61024 + axis).uniform(.01, .13, extent).astype(dtype)
        else:
            values = (np.arange(math.prod(extent)).reshape(extent) % 13).astype(dtype)
        faces.append(values)
    grid = {'d' + axis: np.ones(size) for axis, size in zip('xyz', shape)}
    return faces, grid


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.longdouble,
                                   np.int8, np.int32, np.int64, np.uint32, np.uint64])
def test_mass_summary_keeps_signed_faces_and_axis_order(dimension, dtype):
    faces, grid = _mass_inputs(dimension, dtype)
    original = [value.copy() for value in faces]
    args = (faces, grid, dimension, 'original units', 'original source')
    assert_observation(observe(lambda: physical_balance._mass_summary(*args)),
                       observe(lambda: reference._mass_summary(*args)))
    for value, old in zip(faces, original):
        np.testing.assert_array_equal(value, old)


@pytest.mark.parametrize('dtypes', [(np.int16, np.float32), (np.float16, np.float32),
                                    (np.int64, np.float32), (np.int8, np.int32, np.float64)])
def test_mass_summary_keeps_mixed_axis_promotion(dtypes):
    faces, grid = _mass_inputs(len(dtypes), np.float64)
    faces = [value.astype(dtype) for value, dtype in zip(faces, dtypes)]
    args = (faces, grid, len(dtypes), 'units', 'source')
    assert_observation(observe(lambda: physical_balance._mass_summary(*args)),
                       observe(lambda: reference._mass_summary(*args)))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.longdouble,
                                   np.int16, np.int64, np.uint64])
@pytest.mark.parametrize('dimension', [2, 3])
def test_complete_energy_summary_keeps_typed_source_evidence(dtype, dimension):
    result = sample_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    flux['mass_A'] = flux['mass_B'] = None
    energy = flux['energy']
    for phase in ('A', 'B', 'solid'):
        for key in ('advective_out', 'diffusive_out'):
            energy[key][phase] = {name: value.astype(dtype) for name, value in energy[key][phase].items()}
        values = energy['residual'][phase]
        if np.dtype(dtype).kind == 'u':
            values = np.zeros(values.shape, dtype=dtype)
            values.flat[:2] = [np.iinfo(dtype).max, np.iinfo(dtype).max]
        else:
            values = values.astype(dtype)
        energy['residual'][phase] = values
        energy['source_integral'][phase] = np.asarray(1 if phase == 'A' else 0, dtype=dtype)
    current = replace(result, boundary_fluxes=flux)
    assert_observation(observe(lambda: physical_balance.evaluate_physical_balance(current)),
                       observe(lambda: reference.evaluate_physical_balance(current)))


def test_wider_long_double_remains_finite_before_report_conversion():
    if np.finfo(np.longdouble).maxexp <= np.finfo(np.float64).maxexp:
        pytest.skip('the platform long double has no wider exponent range')
    result = sample_result(2)
    flux = mutable_data(result.boundary_fluxes)
    flux['mass_A'] = flux['mass_B'] = None
    flux['energy']['residual']['A'] = np.full((2, 2), np.longdouble('1e400'), dtype=np.longdouble)
    current = replace(result, boundary_fluxes=flux)
    assert_observation(observe(lambda: physical_balance.evaluate_physical_balance(current)),
                       observe(lambda: reference.evaluate_physical_balance(current)))


@pytest.mark.parametrize('solved', [(), ('A',), ('A', 'solid'), ('A', 'B', 'solid')])
def test_energy_phase_selection_and_empty_integer_zero(solved):
    result = sample_result(2)
    flux = mutable_data(result.boundary_fluxes)
    for phase in ('A', 'B', 'solid'):
        flux['energy']['solved'][phase] = phase in solved
        if phase not in solved:
            for key in ('residual', 'advective_out', 'diffusive_out', 'source_integral'):
                flux['energy'][key][phase] = None
    flux['energy']['prescribed_b_power'] = 6.
    current = replace(result, boundary_fluxes=flux)
    assert_observation(observe(lambda: physical_balance.evaluate_physical_balance(current)),
                       observe(lambda: reference.evaluate_physical_balance(current)))


def test_plane_sum_keeps_python_compensation():
    values = [1e16, 1., -1e16, 0., 0., 0.]
    actual = native.plane_sums([np.array([value]) for value in values])
    assert list(actual.values) == values
    assert actual.total == sum(values) == 1.


def test_finite_check_precedes_residual_shape_error():
    result = sample_result(2)
    flux = mutable_data(result.boundary_fluxes)
    flux['energy']['residual']['A'] = np.array([np.nan])
    current = replace(result, boundary_fluxes=flux)
    assert_observation(observe(lambda: physical_balance.evaluate_physical_balance(current)),
                       observe(lambda: reference.evaluate_physical_balance(current)))


def test_missing_evidence_needs_no_result_call(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('missing evidence invoked native result math')
    monkeypatch.setattr(core, 'call', forbidden)
    current = replace(sample_result(2), boundary_fluxes={})
    assert_values(physical_balance.evaluate_physical_balance(current),
                  reference.evaluate_physical_balance(current))


@pytest.mark.parametrize('damage', ['null', 'dtype', 'reserved', 'output-alias'])
def test_norm_c_boundary_rejects_without_output_writes(damage):
    values = np.array([1., 2., 3., 4.])
    packed = core.array(values)
    output = native._Norms(-123., -456., -789., 912)
    pointer = ct.byref(packed.raw)
    result = ct.byref(output)
    if damage == 'null':
        pointer = None
    elif damage == 'dtype':
        packed.raw.dtype = 999
    elif damage == 'reserved':
        packed.raw.reserved = 1
    else:
        result = ct.cast(packed.raw.data + packed.raw.offset, ct.POINTER(native._Norms))
    original = values.copy()
    with pytest.raises(ValueError):
        core.call('tpmshx_result_balance_norms_v1',
                  [ct.POINTER(core._Array), ct.POINTER(native._Norms)], pointer, result)
    np.testing.assert_array_equal(values, original)
    assert native.norm_record(output) == dict(signed_sum=-123., l1=-456., cell_max=-789., cell_count=912)


def test_zero_weights_keep_raw_scalar_output_unchanged():
    values, weights = core.array(np.array([1., 2.])), core.array(np.array([0., 0.]))
    output = core.scalar(9876.5)
    original = bytes(output)
    with pytest.raises(ZeroDivisionError, match='Weights sum to zero'):
        core.call('tpmshx_result_zone_mean_v1',
                  [ct.POINTER(core._Array), ct.POINTER(core._Array), core._UInt, ct.POINTER(core._Scalar)],
                  ct.byref(values.raw), ct.byref(weights.raw), 1, ct.byref(output))
    assert bytes(output) == original
