"""Compare named native metrics with the independent original expressions."""
from dataclasses import replace
import ctypes as ct
from decimal import Decimal
import math
import subprocess
import sys
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests.native.result_reference import shared_math as original
from sjtu_tpmshx.development.tests.native.result_reference import metrics as original_metrics
from sjtu_tpmshx.development.tests.native.result_reference import quick_design as original_quick
from sjtu_tpmshx.development.tests.postprocess_tm1.test_reduction_reuse import native_result
from sjtu_tpmshx.postprocess import api, metrics, quick_design
from sjtu_tpmshx.shared import result_math
from sjtu_tpmshx.shared import _native_result_metrics as native
from sjtu_tpmshx.shared import _native_result as wire
from sjtu_tpmshx.shared.domain.field_result import FieldResult
from sjtu_tpmshx.shared.domain.metric_spec import MetricSpec


def observe(function, *args, policy='warn', **kwargs):
    with warnings.catch_warnings(record=True) as notices, np.errstate(all=policy):
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
        if expected.dtype.kind in 'fc':
            np.testing.assert_array_equal(np.signbit(actual.real), np.signbit(expected.real))
            if expected.dtype.kind == 'c':
                np.testing.assert_array_equal(np.signbit(actual.imag), np.signbit(expected.imag))
    elif isinstance(expected, (float, np.floating)):
        assert (math.isnan(actual) and math.isnan(expected)) or actual == expected
        if expected == 0:
            assert np.signbit(actual) == np.signbit(expected)
    else:
        assert actual == expected


def assert_observation(actual, expected):
    assert actual[1] == expected[1]
    assert actual[0][0] == expected[0][0]
    if expected[0][0] == 'error':
        assert actual[0][1:] == expected[0][1:]
    else:
        assert_value(actual[0][1], expected[0][1])


@pytest.mark.parametrize('pressure_dtype,width_dtype', [
    ('bool', 'bool'), ('bool', 'int16'), ('int8', 'int8'), ('uint64', 'int16'),
    ('float16', 'float16'), ('float16', 'float64'), ('float32', 'bool'),
    ('float32', 'int16'), ('float32', 'float64'), ('float64', 'float32'),
    ('complex64', 'float32'), ('complex64', 'complex64'), ('complex128', 'complex128'),
    ('>f4', '>f4'), (np.longdouble, np.longdouble),
])
@pytest.mark.parametrize('layout', ['C', 'F', 'reverse', 'step'])
def test_pressure_dtype_precision_and_layout(pressure_dtype, width_dtype, layout):
    pressure = np.arange(24).reshape(3, 4, 2).astype(pressure_dtype)
    widths = np.array([1., 2., 3., 4.]).astype(width_dtype)
    if np.iscomplexobj(pressure):
        pressure.imag[...] = pressure.real
    if layout == 'F':
        pressure = np.asfortranarray(pressure)
    elif layout == 'reverse':
        pressure, widths = pressure[::-1, ::-1], widths[::-1]
    elif layout == 'step':
        storage = np.zeros((6, 8, 4), dtype=pressure.dtype)
        storage[::2, ::2, ::2] = pressure
        pressure = storage[::2, ::2, ::2]
    assert_observation(observe(result_math.pressure_face_values, pressure, widths),
                       observe(original.pressure_face_values, pressure, widths))


def test_pressure_trailing_dimensions_keep_raw_contract():
    pressure = np.arange(48, dtype=np.float32).reshape(2, 3, 2, 4)
    widths = np.array([1., 2., 3.], dtype=np.float32)
    assert_observation(observe(result_math.pressure_face_values, pressure, widths),
                       observe(original.pressure_face_values, pressure, widths))


@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
@pytest.mark.parametrize('case', ['overflow', 'ratio_zero', 'later_broadcast'])
def test_pressure_fp_order_and_terminal_error(policy, case):
    pressure, widths = np.array([[65504., -65504.]], dtype=np.float16), np.ones(2, dtype=np.float16)
    if case == 'ratio_zero':
        pressure = np.array([[1., 2., 3.]])
        widths = np.array([1., -1., 2.])
    elif case == 'later_broadcast':
        pressure = np.ones((2, 3, 4))
        widths = np.array([[0., 0.], [0., 0.], [1., 1.]])
    assert_observation(observe(result_math.pressure_face_values, pressure, widths, policy=policy),
                       observe(original.pressure_face_values, pressure, widths, policy=policy))


@pytest.mark.parametrize('dtype', [np.int8, np.int64, np.uint64])
@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_pressure_integer_width_scalar_overflow_keeps_original_fp_policy(dtype, policy):
    pressure = np.arange(6, dtype=np.float64).reshape(2, 3)
    widths = np.full(3, np.iinfo(dtype).max, dtype=dtype)
    assert_observation(observe(result_math.pressure_face_values, pressure, widths, policy=policy),
                       observe(original.pressure_face_values, pressure, widths, policy=policy))


def test_singleton_and_object_protocols_do_not_dispatch_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Python object/index protocol reached a native numerical call')
    monkeypatch.setattr(result_math.native, 'pressure_ratio', forbidden)
    singleton = np.array([['text'], ['another']], dtype=object)
    got = result_math.pressure_face_values(singleton, object())
    assert all(np.shares_memory(face, singleton) for face in got)
    assert_observation(observe(result_math.pressure_face_values, singleton, object()),
                       observe(original.pressure_face_values, singleton, object()))
    for pressure, widths in ((np.array([[1., 2., 3.]], dtype=object), [1., 2., 3.]),
                              (np.array([[Decimal('1'), Decimal('2')]], dtype=object), [1., 2.]),
                              (np.array([[1., 2., 3.]], dtype=np.float32), np.array([1., 2., 3.], dtype=object))):
        assert_observation(observe(result_math.pressure_face_values, pressure, widths),
                           observe(original.pressure_face_values, pressure, widths))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_capacity_products_keep_intermediate_precision(dtype, direction):
    temperature = np.linspace(310., 450., 20).reshape(4, 5).astype(dtype)
    u, v = np.full((4, 5), .4, dtype=dtype), np.full((4, 5), .7, dtype=dtype)
    rho_cp = np.full((4, 5), 1200., dtype=dtype)
    dx, dy = np.arange(1, 5, dtype=dtype), np.arange(1, 6, dtype=dtype)
    args = (temperature, u, v, rho_cp, direction, dx, dy)
    mask = np.linspace(.2, 1., 5 if direction < 2 else 4)
    kwargs = dict(inlet_mask=mask, outlet_mask=mask[::-1], eps_side=dtype(.3), T_in=500.)
    assert_observation(observe(result_math._enthalpy_balance_2d, *args, **kwargs),
                       observe(original._enthalpy_balance_2d, *args, **kwargs))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_true_h_duty_keeps_per_face_dtype_and_plain_addition(dtype):
    h = np.linspace(300., 400., 8).reshape(2, 2, 2).astype(dtype)
    faces = tuple(np.full(tuple(2 + (axis == i) for axis in range(3)), .2, dtype=dtype)
                  for i in range(3))
    assert_observation(observe(result_math._boundary_enthalpy_duty, h, 350., faces),
                       observe(original._boundary_enthalpy_duty, h, 350., faces))


@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.int64, np.uint16, np.uint64,
                                   np.float16, np.float32, np.float64])
def test_two_d_mass_metric_keeps_sign_and_literal_rules(dtype):
    result = native_result(2)
    faces = tuple(np.asarray(face, dtype=dtype) for face in result.boundary_fluxes['mass_A'])
    result = replace(result, boundary_fluxes={**result.boundary_fluxes, 'mass_A': faces})
    assert_observation(observe(metrics._mass_flow, result, 'A'),
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


@pytest.mark.parametrize('name,changes', [
    ('Q', dict(mass=2**53 + 1, cp=2**53 + 1)),
    ('Q', dict(mass=2**600, cp=2**600, inlet=300.)),
    ('Q', dict(mass=0, inlet=2**1100)),
    ('dP_A', dict(pin=2**1100 + 1, pout=2**1100)),
    ('Re_A', dict(rho=2**600, speed=2**600, mu=2**1200)),
    ('Re_A', dict(rho=2**53 + 1, speed=2**53 + 1)),
    ('Re_A', dict(rho=2**53 + 1, speed=1, mu=2**53 + 2)),
    ('Re_A', dict(rho=1., speed=-(1 << 63))),
    ('Re_A', dict(rho=np.array(1.1, dtype=np.float16), speed=np.array(.3, dtype=np.float16),
                  diameter=np.array(.1, dtype=np.float16), mu=np.array(.7, dtype=np.float16))),
    ('Re_A', dict(rho=np.int64(3), speed=np.int64(2), diameter=np.int64(4), mu=np.int64(3))),
    ('Re_A', dict(rho=np.float64(1.1), speed=np.float64(.3), mu=np.float64(.7))),
])
def test_qd_scalar_protocols_after_real_freeze(name, changes):
    result = quick_result(**changes)
    assert_observation(observe(quick_design.evaluate_metric, result, name),
                       observe(original_quick.evaluate_metric, result, name))


def test_qd_earlier_arithmetic_precedes_later_missing_field():
    result = quick_result(rho=np.float64(1e308), speed=np.float64(1e308))
    result = replace(result, metadata={**result.metadata, 'parameters': {'arrangement': 'counter'}})
    assert_observation(observe(quick_design.evaluate_metric, result, 'Re_A'),
                       observe(original_quick.evaluate_metric, result, 'Re_A'))


@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.uint64, np.float16,
                                   np.float32, np.float64, '>f4', np.longdouble])
@pytest.mark.parametrize('layout', ['C', 'reverse', 'step', 'empty'])
def test_capture_area_matrix_and_sum_keep_original_typed_outer_product(dtype, layout):
    dx = np.linspace(1., 4., 7).astype(dtype)
    dy = np.linspace(.1, .9, 11).astype(dtype)
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
    assert_observation(observe(native.duty_magnitude, value), observe(abs, value))


@pytest.mark.parametrize('size', [0, 1, 2])
@pytest.mark.parametrize('role,name', [('mass', 'Q'), ('cp', 'Q'), ('inlet', 'Q'),
    ('rho', 'Re_A'), ('speed', 'Re_A'), ('diameter', 'Re_A'), ('mu', 'Re_A'),
    ('pressure', 'dP_A'), ('mass', 'energy_imbalance_rel')])
def test_qd_numeric_array_metadata_uses_original_shape_and_truth_protocol(size, role, name):
    values = np.linspace(1., 2., size, dtype=np.float32)
    changes = dict(pin=values, pout=values) if role == 'pressure' else {role: values}
    result = quick_result(**changes)
    if name == 'energy_imbalance_rel':
        result = replace(result, boundary_fluxes={**result.boundary_fluxes,
            'B': dict(mass_flow_kg_s=1., cp_J_kgK=1., inlet_temperature_K=301., velocity_m_s=1.)})
    assert_observation(observe(quick_design.evaluate_metric, result, name),
                       observe(original_quick.evaluate_metric, result, name))


@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.uint64, np.float16, '>f4'])
@pytest.mark.parametrize('name', ['Q', 'Re_A'])
def test_qd_array_metadata_keeps_exact_staged_dtype(dtype, name):
    values = np.asarray([1, 2], dtype=dtype)
    changes = (dict(mass=values, cp=values) if name == 'Q'
               else dict(rho=values, speed=values, diameter=values, mu=values))
    result = quick_result(**changes)
    assert_observation(observe(quick_design.evaluate_metric, result, name),
                       observe(original_quick.evaluate_metric, result, name))


@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
@pytest.mark.parametrize('name', ['Q', 'Re_A'])
def test_qd_array_fp_stages_precede_later_broadcast(policy, name):
    changes = (dict(inlet=np.full(3, -65504., dtype=np.float16),
                    mass=np.ones(2, dtype=np.float16), cp=np.ones(2, dtype=np.float16))
               if name == 'Q' else dict(rho=np.full(2, 1e308), speed=np.full(2, 1e308),
                                        diameter=np.ones(3)))
    result = quick_result(**changes)
    assert_observation(observe(quick_design.evaluate_metric, result, name, policy=policy),
                       observe(original_quick.evaluate_metric, result, name, policy=policy))


@pytest.mark.parametrize('size', [0, 1, 2])
@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_qd_array_weak_cast_is_checked_before_iteration(size, policy):
    result = quick_result(rho=1e308, speed=np.ones(size, dtype=np.float16))
    assert_observation(observe(quick_design.evaluate_metric, result, 'Re_A', policy=policy),
                       observe(original_quick.evaluate_metric, result, 'Re_A', policy=policy))


def test_qd_python_absolute_integer_can_exceed_the_input_storage():
    result = quick_result(rho=np.ones(2), speed=-(1 << 63))
    assert_observation(observe(quick_design.evaluate_metric, result, 'Re_A'),
                       observe(original_quick.evaluate_metric, result, 'Re_A'))


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
    first = np.full((2, 3), 17.)
    second = np.full((2, 3), 19., dtype=np.float32)
    outputs = [wire.array(value) for value in (first, second)]
    pointer = ct.POINTER(wire._Array)
    with pytest.raises(ValueError, match='output dtype or shape'):
        wire.call('tpmshx_result_port_weights_v1', [pointer] * 6,
                  *(ct.byref(item.raw) for item in inputs + outputs))
    np.testing.assert_array_equal(first, np.full((2, 3), 17.))
    np.testing.assert_array_equal(second, np.full((2, 3), 19., dtype=np.float32))


def solid_mass_result(layout, dtype=np.float64, *, density=1., epsilon=.5):
    shapes = {'zero_dimensional': (), 'row': (1, 3), 'column': (2, 1),
              'full': (2, 3), 'mismatch': (3, 3)}
    values = epsilon if layout == 'scalar' else np.full(shapes[layout], epsilon, dtype=dtype)
    return FieldResult(result_id='mass-broadcast', case_id='test', backend_id='fixture',
        grid=dict(dimension=2, dx=np.array([1., 2.], dtype=dtype),
                  dy=np.array([1., 2., 3.], dtype=dtype)),
        metadata=dict(dimension=2, solid_density_kg_m3=density, design_fields=dict(eps_arr=values)))


@pytest.mark.parametrize('layout', ['scalar', 'zero_dimensional', 'row', 'column', 'full', 'mismatch'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_two_d_solid_mass_keeps_original_sequential_width_broadcast(layout, dtype):
    result = solid_mass_result(layout, dtype, density=1.3)
    arguments = dict(dimension=2, duty=None, mass_flow=None)
    assert_observation(observe(metrics._evaluate_metric, result, 'mass', **arguments),
                       observe(original_metrics._evaluate_metric, result, 'mass', **arguments))


@pytest.mark.parametrize('layout', ['zero_dimensional', 'mismatch'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
def test_two_d_solid_mass_fp_precedes_later_width_broadcast(layout, policy):
    result = solid_mass_result(layout, np.float16, density=65504., epsilon=-1.)
    arguments = dict(dimension=2, duty=None, mass_flow=None)
    assert_observation(observe(metrics._evaluate_metric, result, 'mass', policy=policy, **arguments),
                       observe(original_metrics._evaluate_metric, result, 'mass', policy=policy, **arguments))


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
    assert_observation(observe(native.solid_mass, np.array(.5), 1., (dx, dy)),
                       observe(original_metrics._evaluate_metric, result, 'mass',
                               dimension=2, duty=None, mass_flow=None))


def test_solid_mass_scalar_c_abi_returns_without_a_process_crash():
    code = '''
import ctypes as ct
import numpy as np
from sjtu_tpmshx.shared import _native_result as wire
owners = [wire.array(value) for value in (np.array(.5), 1., np.ones(2), np.ones(3))]
output = ct.c_double(17.)
pointer = ct.POINTER(wire._Array)
wire.call('tpmshx_result_solid_mass_2d_v1', [pointer] * 4 + [ct.POINTER(ct.c_double)],
          *(ct.byref(owner.raw) for owner in owners), ct.byref(output))
assert output.value == 3.
'''
    process = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True)
    assert process.returncode == 0, (process.returncode, process.stdout, process.stderr)
