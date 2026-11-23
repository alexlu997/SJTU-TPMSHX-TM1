"""Compare named native float64 metrics with the independent original expressions."""
from dataclasses import replace
import ctypes as ct
import math
import subprocess
import sys
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from tests.python.native.result_reference import shared_math as original
from tests.python.native.result_reference import metrics as original_metrics
from tests.python.postprocess_tm1.test_reduction_reuse import native_result
from sjtu_tpmshx.postprocess import api
from tests.python import result_primitive_wire as raw
from sjtu_tpmshx.postprocess import result_math
from sjtu_tpmshx.cpp_interface import _native_result_metrics as native
from sjtu_tpmshx.cpp_interface import _native_result as wire
from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.data_types.metric_spec import MetricSpec


def observe(function, *args, **kwargs):
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always')
        try:
            output = ('value', function(*args, **kwargs))
        except Exception as error:
            output = ('error', type(error), error.args)
    return output, [(item.category, str(item.message)) for item in notices]


def assert_value(actual, expected):
    assert type(actual) is type(expected)
    if isinstance(expected, (tuple, list)):
        assert len(actual) == len(expected)
        for value, old in zip(actual, expected):
            assert_value(value, old)
    elif isinstance(expected, dict):
        assert list(actual) == list(expected)
        for key in expected:
            assert_value(actual[key], expected[key])
    elif isinstance(expected, np.ndarray):
        assert actual.dtype == expected.dtype and actual.shape == expected.shape
        np.testing.assert_array_equal(actual, expected)
        if expected.dtype.kind == 'f':
            np.testing.assert_array_equal(np.signbit(actual), np.signbit(expected))
    elif isinstance(expected, (float, np.floating)):
        assert (math.isnan(actual) and math.isnan(expected)) or actual == expected
        if expected == 0:
            assert np.signbit(actual) == np.signbit(expected)
    else:
        assert actual == expected


def _normalize_notices(notices):
    return [(category, message.replace('encountered in scalar ', 'encountered in '))
            for category, message in notices]


def assert_observation(actual, expected):
    assert _normalize_notices(actual[1]) == _normalize_notices(expected[1])
    assert actual[0][0] == expected[0][0]
    if expected[0][0] == 'error':
        assert actual[0][1:] == expected[0][1:]
    else:
        assert_value(actual[0][1], expected[0][1])


@pytest.mark.parametrize('layout', ['C', 'F', 'reverse', 'step'])
def test_pressure_float64_and_layout(layout):
    pressure = np.arange(24, dtype=np.float64).reshape(3, 4, 2)
    widths = np.array([1., 2., 3., 4.], dtype=np.float64)
    if layout == 'F':
        pressure = np.asfortranarray(pressure)
    elif layout == 'reverse':
        pressure, widths = pressure[::-1, ::-1], widths[::-1]
    elif layout == 'step':
        storage = np.zeros((6, 8, 4), dtype=np.float64)
        storage[::2, ::2, ::2] = pressure
        pressure = storage[::2, ::2, ::2]
    assert_observation(observe(result_math.pressure_face_values, pressure, widths),
                       observe(original.pressure_face_values, pressure, widths))


def test_pressure_trailing_dimensions_keep_raw_contract():
    pressure = np.arange(48, dtype=np.float64).reshape(2, 3, 2, 4)
    widths = np.array([1., 2., 3.], dtype=np.float64)
    assert_observation(observe(result_math.pressure_face_values, pressure, widths),
                       observe(original.pressure_face_values, pressure, widths))


@pytest.mark.parametrize('case', ['overflow', 'ratio_zero', 'later_broadcast'])
def test_pressure_fp_order_and_terminal_error(case):
    pressure = np.array([[np.finfo(np.float64).max, -np.finfo(np.float64).max]], dtype=np.float64)
    widths = np.ones(2, dtype=np.float64)
    if case == 'ratio_zero':
        pressure = np.array([[1., 2., 3.]])
        widths = np.array([1., -1., 2.])
    elif case == 'later_broadcast':
        pressure = np.ones((2, 3, 4))
        widths = np.array([[0., 0.], [0., 0.], [1., 1.]])
    assert_observation(observe(result_math.pressure_face_values, pressure, widths),
                       observe(original.pressure_face_values, pressure, widths))


def test_singleton_keeps_view_and_non_real_pressure_raises_type_error(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('singleton pressure path reached a native numerical call')
    monkeypatch.setattr(result_math.native, 'pressure_ratio', forbidden)
    singleton = np.array([[1.], [2.]], dtype=np.float64)
    got = result_math.pressure_face_values(singleton, object())
    assert all(np.shares_memory(face, singleton) for face in got)
    monkeypatch.undo()
    for pressure, widths in (
        (np.array([[1., 2., 3.]], dtype=object), [1., 2., 3.]),
        (np.array([[1. + 1.j, 2., 3.]]), [1., 2., 3.]),
        (np.array([[True, False, True]]), [1., 2., 3.]),
    ):
        with pytest.raises(TypeError):
            result_math.pressure_face_values(pressure, widths)


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_capacity_products_match_float64_reference(direction):
    temperature = np.linspace(310., 450., 20).reshape(4, 5)
    u, v = np.full((4, 5), .4), np.full((4, 5), .7)
    rho_cp = np.full((4, 5), 1200.)
    dx, dy = np.arange(1., 5.), np.arange(1., 6.)
    args = (temperature, u, v, rho_cp, direction, dx, dy)
    mask = np.linspace(.2, 1., 5 if direction < 2 else 4)
    kwargs = dict(inlet_mask=mask, outlet_mask=mask[::-1], eps_side=.3, T_in=500.)
    assert_observation(observe(raw._enthalpy_balance_2d, *args, **kwargs),
                       observe(original._enthalpy_balance_2d, *args, **kwargs))


def test_true_h_duty_matches_float64_reference():
    h = np.linspace(300., 400., 8).reshape(2, 2, 2)
    faces = tuple(np.full(tuple(2 + (axis == i) for axis in range(3)), .2) for i in range(3))
    assert_observation(observe(raw._boundary_enthalpy_duty, h, 350., faces),
                       observe(original._boundary_enthalpy_duty, h, 350., faces))


def test_two_d_mass_metric_matches_float64_reference():
    result = native_result(2)
    faces = tuple(np.asarray(face, dtype=np.float64) for face in result.boundary_fluxes['mass_A'])
    result = replace(result, boundary_fluxes={**result.boundary_fluxes, 'mass_A': faces})
    planes = (faces[0][0], faces[0][-1], faces[1][:, 0], faces[1][:, -1])
    assert_observation(observe(raw.boundary_mass, planes, 2),
                       observe(original_metrics._mass_flow, result, 'A'))


def quick_result(**changes):
    values = dict(mass=1., cp=1., inlet=301., pin=100., pout=90., rho=1., speed=1., diameter=1., mu=1.)
    values.update(changes)
    return FieldResult(result_id='scalar-protocol', case_id='test', backend_id='fixture',
        fields={'Ta': np.full((1, 1, 1), 300.), 'Tb': np.full((1, 1, 1), 300.)},
        boundary_fluxes={'A': dict(mass_flow_kg_s=values['mass'], cp_J_kgK=values['cp'],
            inlet_temperature_K=values['inlet'], velocity_m_s=values['speed'])},
        pressure_evidence={'A': dict(inlet_absolute_Pa=values['pin'], outlet_absolute_Pa=values['pout'])},
        metadata=dict(mode='quick_design', dimension=3, model='plug_ltne_analytic_dp_v1',
            parameters=dict(arrangement='counter', D_h=values['diameter']),
            properties={'A': dict(rho=values['rho'], mu=values['mu'])}))


@pytest.mark.parametrize('layout', ['C', 'reverse', 'step', 'empty'])
def test_capture_area_matrix_and_sum_match_float64_outer_product(layout):
    dx = np.linspace(1., 4., 7)
    dy = np.linspace(.1, .9, 11)
    if layout == 'reverse':
        dx, dy = dx[::-1], dy[::-1]
    elif layout == 'step':
        dx, dy = dx[::2], dy[::2]
    elif layout == 'empty':
        dx = dx[:0]
    assert_observation(observe(native.capture_area_weights, dx, dy),
                       observe(lambda: dx[:, None] * dy[None, :]))
    assert_observation(observe(native.capture_area, dx, dy),
                       observe(lambda: float(np.sum(dx[:, None] * dy[None, :]))))


@pytest.mark.parametrize('value', [0., -0., 1., -1., float('inf'), -float('inf'), float('nan')])
def test_formal_duty_magnitude_keeps_original_float_contract(value):
    assert_observation(observe(raw.duty_magnitude, value), observe(abs, value))


def test_pressure_array_abi_rejects_input_output_alias_without_mutation():
    first, second = np.array([1., 2.]), np.array([3., 4.])
    source, adjacent, target = wire.array(first), wire.array(second), wire.array(first)
    old = first.copy()
    pointer = ct.POINTER(wire._Array)
    with pytest.raises(ValueError):
        wire.call('tpmshx_result_pressure_ratio_v1', [pointer] * 3,
                  ct.byref(source.raw), ct.byref(adjacent.raw), ct.byref(target.raw))
    np.testing.assert_array_equal(first, old)


def test_port_weights_abi_does_not_publish_first_output_before_second_shape_check():
    inputs = [wire.array(value) for value in (np.array([1., 2.]), np.array([1., 2., 3.]),
                                             np.ones((2, 3)), np.ones((2, 3)))]
    first = np.full((2, 3), 17., dtype=np.float64)
    second = np.full((2, 4), 19., dtype=np.float64)
    outputs = [wire.array(value) for value in (first, second)]
    pointer = ct.POINTER(wire._Array)
    with pytest.raises(ValueError, match='output shape'):
        wire.call('tpmshx_result_port_weights_v1', [pointer] * 6,
                  *(ct.byref(item.raw) for item in inputs + outputs))
    np.testing.assert_array_equal(first, np.full((2, 3), 17.))
    np.testing.assert_array_equal(second, np.full((2, 4), 19.))


def solid_mass_result(layout, *, density=1., epsilon=.5):
    shapes = {'zero_dimensional': (), 'row': (1, 3), 'column': (2, 1),
              'full': (2, 3), 'mismatch': (3, 3)}
    values = epsilon if layout == 'scalar' else np.full(shapes[layout], epsilon, dtype=np.float64)
    return FieldResult(result_id='mass-broadcast', case_id='test', backend_id='fixture',
        grid=dict(dimension=2, dx=np.array([1., 2.]), dy=np.array([1., 2., 3.])),
        metadata=dict(dimension=2, solid_density_kg_m3=density, design_fields=dict(eps_arr=values)))


@pytest.mark.parametrize('layout', ['scalar', 'zero_dimensional', 'row', 'column', 'full', 'mismatch'])
def test_two_d_solid_mass_keeps_original_sequential_width_broadcast(layout):
    result = solid_mass_result(layout, density=1.3)
    arguments = dict(dimension=2, duty=None, mass_flow=None)
    assert_observation(observe(raw.solid_mass, np.asarray(result.metadata['design_fields']['eps_arr']),
                               result.metadata['solid_density_kg_m3'],
                               (np.asarray(result.grid['dx']), np.asarray(result.grid['dy']))),
                       observe(original_metrics._evaluate_metric, result, 'mass', **arguments))


@pytest.mark.parametrize('layout', ['zero_dimensional', 'mismatch'])
def test_two_d_solid_mass_fp_precedes_later_width_broadcast(layout):
    result = solid_mass_result(layout, density=np.finfo(np.float64).max, epsilon=-1.)
    arguments = dict(dimension=2, duty=None, mass_flow=None)
    assert_observation(observe(raw.solid_mass, np.asarray(result.metadata['design_fields']['eps_arr']),
                               result.metadata['solid_density_kg_m3'],
                               (np.asarray(result.grid['dx']), np.asarray(result.grid['dy']))),
                       observe(original_metrics._evaluate_metric, result, 'mass', **arguments))


@pytest.mark.parametrize('layout', ['scalar', 'zero_dimensional', 'row', 'column', 'full', 'mismatch'])
def test_public_evaluate_keeps_broadcastable_mass_evidence_and_original_error(layout):
    result = solid_mass_result(layout)
    expected, notices = observe(original_metrics._evaluate_metric, result, 'mass',
                                dimension=2, duty=None, mass_flow=None)
    assert not notices
    metric = api.evaluate(result, MetricSpec('mass', 'kg/m')).metrics['mass']
    if expected[0] == 'value':
        assert metric.status == 'available'
        assert metric.value == expected[1]
    else:
        assert expected[1] is ValueError
        assert metric.status == 'invalid'
        assert metric.reason == expected[2][0]


def test_two_d_solid_mass_keeps_original_nd_fortran_width_indexing():
    dx = np.asfortranarray([[1., 4.], [2., 8.]])
    dy = np.asfortranarray([[.25, 1.], [.5, 2.]])
    result = SimpleNamespace(grid=dict(dx=dx, dy=dy),
        metadata=dict(solid_density_kg_m3=1., design_fields=dict(eps_arr=np.array(.5))))
    assert_observation(observe(raw.solid_mass, np.array(.5), 1., (dx, dy)),
                       observe(original_metrics._evaluate_metric, result, 'mass',
                               dimension=2, duty=None, mass_flow=None))


def test_solid_mass_scalar_c_abi_returns_without_a_process_crash():
    code = '''
import ctypes as ct
import numpy as np
from sjtu_tpmshx.cpp_interface import _native_result as wire
owners = [wire.array(value) for value in (np.array(.5), 1., np.ones(2), np.ones(3))]
output = ct.c_double(17.)
pointer = ct.POINTER(wire._Array)
wire.call('tpmshx_result_solid_mass_2d_v1', [pointer] * 4 + [ct.POINTER(ct.c_double)],
          *(ct.byref(owner.raw) for owner in owners), ct.byref(output))
assert output.value == 3.
'''
    process = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True)
    assert process.returncode == 0, (process.returncode, process.stdout, process.stderr)
