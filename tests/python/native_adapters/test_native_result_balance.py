"""Compare native float64 signed balances with the frozen NumPy evidence reductions."""
import ctypes as ct
from dataclasses import replace
import math
import warnings

import numpy as np
import pytest

from tests.python import result_balance_reference as reference
from tests.python.postprocess_tm1.test_physical_balance import sample_result
from tm1.postprocess import api as physical_balance
from tm1.data_types.field_result import FieldResult
from tm1.cpp_interface import _native_result as core
from tests.python import result_primitive_wire as native
from tm1.data_types.portable_data import mutable_data


def observe(function):
    with warnings.catch_warnings(record=True) as caught:
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


@pytest.mark.parametrize('layout', ['C', 'F', 'transpose', 'negative', 'step'])
def test_norms_keep_float64_reductions_and_layout(layout):
    values = np.random.default_rng(61024).uniform(-.3, .7, (137, 11)).astype(np.float64)
    if layout == 'F':
        values = np.asfortranarray(values)
    elif layout == 'transpose':
        values = values.T
    elif layout == 'negative':
        values = values[::-1, ::-1]
    elif layout == 'step':
        values = values[::2, ::2]
    assert_observation(observe(lambda: native.norms(values)),
                       observe(lambda: reference._norms(values)))


@pytest.mark.parametrize('dtype', ['>f8', '<f8', '>f4', np.int32])
def test_norms_normalize_real_inputs_to_float64(dtype):
    values = (np.arange(1507).reshape(137, 11) % 37).astype(dtype)
    assert_observation(observe(lambda: native.norms(values)),
                       observe(lambda: reference._norms(values.astype(np.float64))))


def test_norms_emit_fixed_overflow_warning():
    values = np.full(137, np.finfo(np.float64).max, dtype=np.float64)
    assert_observation(observe(lambda: native.norms(values)),
                       observe(lambda: reference._norms(values)))


def _mass_inputs(dimension):
    shape = (7, 5, 3)[:dimension]
    faces = []
    for axis in range(dimension):
        extent = tuple(size + (i == axis) for i, size in enumerate(shape))
        values = np.random.default_rng(61024 + axis).uniform(.01, .13, extent).astype(np.float64)
        faces.append(values)
    grid = {'d' + axis: np.ones(size) for axis, size in zip('xyz', shape)}
    return faces, grid


@pytest.mark.parametrize('dimension', [2, 3])
def test_mass_summary_keeps_signed_faces_and_axis_order(dimension):
    faces, grid = _mass_inputs(dimension)
    original = [value.copy() for value in faces]
    args = (faces, grid, dimension, 'kg/(s m)' if dimension == 2 else 'kg/s', 'boundary_fluxes.mass_A')
    assert_observation(observe(lambda: physical_balance.evaluate_physical_balance(FieldResult('mass', 'case', 'fixture',
        grid=dict(grid, dimension=args[2]), metadata={'dimension': args[2]},
        boundary_fluxes={'mass_A': faces}))['mass']['A']),
                       observe(lambda: reference._mass_summary(*args)))
    for value, old in zip(faces, original):
        np.testing.assert_array_equal(value, old)


@pytest.mark.parametrize('dimension', [2, 3])
def test_complete_energy_summary_keeps_float64_source_evidence(dimension):
    result = sample_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    flux['mass_A'] = flux['mass_B'] = None
    energy = flux['energy']
    for phase in ('A', 'B', 'solid'):
        for key in ('advective_out', 'diffusive_out'):
            energy[key][phase] = {name: value.astype(np.float64) for name, value in energy[key][phase].items()}
        energy['residual'][phase] = energy['residual'][phase].astype(np.float64)
        energy['source_integral'][phase] = np.asarray(1. if phase == 'A' else 0., dtype=np.float64)
    current = replace(result, boundary_fluxes=flux)
    assert_observation(observe(lambda: physical_balance.evaluate_physical_balance(current)),
                       observe(lambda: reference.evaluate_physical_balance(current)))


@pytest.mark.parametrize('solved', [(), ('A',), ('A', 'solid'), ('A', 'B', 'solid')])
def test_energy_phase_selection_and_empty_zero(solved):
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


@pytest.mark.parametrize('bad', [np.array([True, False]), np.array([1. + 2.j]), np.array([1.], dtype=object)])
def test_norms_reject_non_real_arrays(bad):
    with pytest.raises(TypeError):
        native.norms(bad)


@pytest.mark.parametrize('damage', ['null', 'null-data', 'null-shape', 'output-alias'])
def test_norm_c_boundary_rejects_without_output_writes(damage):
    values = np.array([1., 2., 3., 4.], dtype=np.float64)
    packed = core.array(values)
    output = native._Norms(-123., -456., -789., 912)
    pointer = ct.byref(packed.raw)
    result = ct.byref(output)
    if damage == 'null':
        pointer = None
    elif damage == 'null-data':
        packed.raw.data = None
    elif damage == 'null-shape':
        packed.raw.shape = None
    else:
        result = ct.cast(packed.raw.data, ct.POINTER(native._Norms))
    original = values.copy()
    with pytest.raises(ValueError):
        core.call('tpmshx_result_balance_norms_v1',
                  [ct.POINTER(core._Array), ct.POINTER(native._Norms)], pointer, result)
    np.testing.assert_array_equal(values, original)
    assert native.norm_record(output) == dict(signed_sum=-123., l1=-456., cell_max=-789., cell_count=912)


def test_zero_weights_keep_raw_scalar_output_unchanged():
    values, weights = core.array(np.array([1., 2.])), core.array(np.array([0., 0.]))
    output = ct.c_double(9876.5)
    with pytest.raises(ZeroDivisionError, match='Weights sum to zero'):
        core.call('tpmshx_result_zone_mean_v1',
                  [ct.POINTER(core._Array), ct.POINTER(core._Array), core._UInt, ct.POINTER(ct.c_double)],
                  ct.byref(values.raw), ct.byref(weights.raw), 1, ct.byref(output))
    assert output.value == 9876.5
