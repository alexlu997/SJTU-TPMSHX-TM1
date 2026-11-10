"""Compare native inlet and design handoffs with frozen independent formulas."""
import ctypes as ct
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.shared.models import _native_flow as native
from sjtu_tpmshx.development.tests import preparation_flow_reference as reference


def _exact(actual, expected):
    assert type(actual) is type(expected)
    np.testing.assert_array_equal(actual, expected, strict=True)
    assert np.signbit(actual) == np.signbit(expected)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('count', [0, 1, 7, 8, 9, 127, 128, 129, 257])
@pytest.mark.parametrize('tapered', [False, True])
def test_2d_capacity_keeps_product_precision_and_pairwise_sum(dtype, count, tapered):
    epsilon = np.linspace(.17, .91, count, dtype=dtype)
    opening = np.linspace(.13, .88, count, dtype=dtype)
    geometric = np.ones(count, dtype=dtype) if tapered else opening.copy()
    widths = np.linspace(.00011, .0037, count * 2, dtype=dtype)[::2]
    originals = [value.copy() for value in (epsilon, opening, geometric, widths)]
    for rho, depth in [(1.27, .031), (np.float32(1.27), np.float16(.031))]:
        with np.errstate(all='ignore'):
            expected = reference.capacity_2d(epsilon, opening, geometric, widths, rho, depth)
            actual = native.capacity_2d(epsilon, opening, geometric, widths, rho, depth)
        _exact(actual, expected)
    for value, original in zip((epsilon, opening, geometric, widths), originals):
        np.testing.assert_array_equal(value, original, strict=True)


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_3d_capacity_uses_physical_face_and_typed_area(direction, dtype):
    shape = (9, 17, 19)
    epsilon = np.linspace(.12, .44, np.prod(shape), dtype=dtype).reshape(shape)
    # The old take() result keeps the order of the other real axes.
    cross = [axis for axis in range(3) if axis != direction // 2]
    widths1 = np.linspace(.0002, .0009, shape[cross[0]], dtype=dtype)
    widths2 = np.linspace(.0001, .0006, shape[cross[1]], dtype=dtype)
    opening = np.linspace(.13, .88, widths1.size * widths2.size, dtype=dtype).reshape(widths1.size, widths2.size)
    for rho in (1.27, np.float32(1.27)):
        expected = reference.capacity_3d(epsilon, direction, widths1, widths2, opening, rho)
        actual = native.capacity_3d(epsilon, direction, widths1, widths2, opening, rho)
        _exact(actual, expected)


@pytest.mark.parametrize('value', [0., -0., np.nan, np.inf])
def test_capacity_leaves_nonfinite_or_zero_for_original_application_guard(value):
    epsilon = np.full(9, value)
    opening = widths = np.ones(9)
    with np.errstate(all='ignore'):
        expected = reference.capacity_2d(epsilon, opening, opening, widths, 1., .1)
        actual = native.capacity_2d(epsilon, opening, opening, widths, 1., .1)
    _exact(actual, expected)


@pytest.mark.parametrize('profile,geometric', [
    (0., 1.), (1e-30, 1.), (np.nextafter(1e-30, 0.), 1.),
    (np.nextafter(1e-30, np.inf), 1.), (1e-20, 0.), (1., 1.),
])
def test_shared_taper_rule_keeps_original_threshold_and_identity(profile, geometric):
    epsilon, widths = np.array([.7]), np.array([1.])
    expected = reference.capacity_2d(epsilon, profile, np.array([geometric]), widths, 1., 1.)
    _exact(native.capacity_2d(epsilon, profile, np.array([geometric]), widths, 1., 1.), expected)


@pytest.mark.parametrize('dtype', [np.int16, np.int32, np.int64])
def test_integer_profile_area_uses_original_integer_sum_before_float_cast(dtype):
    epsilon = np.linspace(.17, .91, 129)
    opening = np.full(129, 2, dtype=dtype)
    geometric = np.full(129, 3, dtype=dtype)
    widths = np.arange(1, 130, dtype=dtype)
    expected = reference.capacity_2d(epsilon, opening, geometric, widths, 1.27, .031)
    _exact(native.capacity_2d(epsilon, opening, geometric, widths, 1.27, .031), expected)


@pytest.mark.parametrize('dtype', [np.int16, np.int32, np.int64])
def test_integer_face_area_keeps_mixed_float32_promotion(dtype):
    epsilon = np.linspace(.12, .44, 9 * 17 * 19, dtype=np.float32).reshape(9, 17, 19)
    widths1, widths2 = np.arange(1, 18, dtype=dtype), np.arange(1, 20, dtype=dtype)
    opening = np.linspace(.13, .88, 17 * 19, dtype=np.float32).reshape(17, 19)
    expected = reference.capacity_3d(epsilon, 1, widths1, widths2, opening, 1.27)
    _exact(native.capacity_3d(epsilon, 1, widths1, widths2, opening, 1.27), expected)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_tapered_area_preserves_weak_python_profile_before_broadcast(dtype):
    epsilon, geometric = np.linspace(.17, .91, 129), np.ones(129, dtype=dtype)
    widths = np.linspace(.00011, .0037, 129, dtype=dtype)
    expected = reference.capacity_2d(epsilon, .73, geometric, widths, 1.27, .031)
    _exact(native.capacity_2d(epsilon, .73, geometric, widths, 1.27, .031), expected)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_physical_face_preserves_weak_scalar_opening_before_broadcast(dtype):
    epsilon = np.linspace(.12, .44, 9 * 17 * 19, dtype=dtype).reshape(9, 17, 19)
    widths1, widths2 = np.linspace(.001, .002, 17, dtype=dtype), np.linspace(.001, .003, 19, dtype=dtype)
    expected = reference.capacity_3d(epsilon, 1, widths1, widths2, .73, 1.27)
    _exact(native.capacity_3d(epsilon, 1, widths1, widths2, .73, 1.27), expected)


@pytest.mark.parametrize('cross', [False, True])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
def test_quick_design_assembly_keeps_height_and_arithmetic(cross, dtype):
    values = [dtype(value) for value in (.31, .084, .05, .047)]
    expected = reference.quick_design_sections(*values, cross)
    actual = native.quick_design_sections(*values, cross)
    for result, wanted in zip(actual, expected):
        _exact(result, wanted)
    mass_flow, density = dtype(.0031), dtype(1.12)
    for air in (False, True):
        expected = reference.side_flow(mass_flow, actual[0], density, air)
        actual_flow = native.quick_design_flow(mass_flow, actual[0], density, air)
        _exact(actual_flow[0], expected[0])
        if air:
            assert actual_flow[1] is None
        else:
            _exact(actual_flow[1], expected[1])


def test_air_side_does_not_divide_by_unused_density():
    assert native.quick_design_flow(.003, .005, 0., True) == (.6, None)


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
def test_targets_proxy_volume_and_speed_keep_original_math(dtype):
    hot, cold, mass_flow, cp = (dtype(value) for value in (400., 310., .31, 1080.))
    for delta in (None, dtype(31.)):
        target = native.temperature_target(hot, delta, dtype(9100.), mass_flow, cp)
        expected = reference.temperature_target(hot, delta, dtype(9100.), mass_flow, cp)
        _exact(target, expected)
        _exact(native.cooling_proxy(hot, cold, target, mass_flow),
               reference.cooling_proxy(hot, cold, target, mass_flow))
    sizes = tuple(dtype(value) for value in (.084, .047, .05))
    _exact(native.volume(*sizes), reference.volume(*sizes))
    targets, capacities = (dtype(.003), dtype(.035)), (dtype(.0008), dtype(.4))
    for actual, expected in zip(native.inlet_speeds(targets, capacities),
                                [target / capacity for target, capacity in zip(targets, capacities)]):
        _exact(actual, expected)


@pytest.mark.parametrize('hot,cold', [(300., 300.), (300., 300.+5e-10), (np.nan, 300.)])
def test_cooling_proxy_skips_target_property_query_for_small_or_nonfinite_span(monkeypatch, hot, cold):
    from sjtu_tpmshx.applications.design import sizing
    def forbidden(*args):
        pytest.fail('the original zero-span branch did not query a target')
    monkeypatch.setattr(sizing, 't_target', forbidden)
    assert sizing._cool_proxy(SimpleNamespace(T_in_h=hot, T_in_c=cold, mdot_h=.3)) == 0.


def test_delta_target_does_not_query_unused_properties(monkeypatch):
    from sjtu_tpmshx.applications.design import sizing
    def forbidden(*args):
        pytest.fail('the delta branch did not query heat capacity')
    monkeypatch.setattr(sizing, 'fluid_props', forbidden)
    assert sizing.t_target(SimpleNamespace(T_in_h=400., dT=30.)) == 370.


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
def test_quick_design_uniform_grid_keeps_original_fill_dtype(dtype):
    length = dtype(.047)
    expected = np.full(17, length / 17)
    np.testing.assert_array_equal(native.uniform_widths(17, length), expected, strict=True)


def test_legacy_air_builder_keeps_its_two_sides_and_floor10(monkeypatch):
    from sjtu_tpmshx.shared.models import sigmoid_field, nu_correlations
    geometry = {
        'r_h_arr': np.linspace(.0002, .0008, 15).reshape(3, 5),
        'A_0_arr': np.linspace(1300., 2300., 15).reshape(3, 5),
        'L_field': np.linspace(4., 8., 15).reshape(3, 5),
        'eps_f_arr': np.linspace(.15, .43, 15).reshape(3, 5),
    }
    monkeypatch.setattr(sigmoid_field, 'air_conductivity', lambda temperature: .031 if temperature == 400. else .024)
    monkeypatch.setattr(sigmoid_field, 'air_viscosity', lambda temperature: 2.1e-5 if temperature == 400. else 1.7e-5)
    monkeypatch.setattr(sigmoid_field, 'air_density', lambda temperature, pressure: .91 if pressure == 1.3e5 else 1.22)
    observed = []
    def fixed_nu(topology, reynolds, cells, diameters):
        observed.append(reynolds.copy())
        return np.full(reynolds.shape, 4.1 if len(observed) == 1 else 5.3)
    monkeypatch.setattr(nu_correlations, 'nu_vec', fixed_nu)
    actual = sigmoid_field._fluid_arrays_from_geometry(
        geometry, 'Diamond', .01, 3., 400., 300., P_in=1.3e5, P_inB=1.6e5, fluid_type='air')
    for index, (speed, rho, mu, conductivity, nu) in enumerate(
            [(.01, .91, 2.1e-5, .031, 4.1), (3., 1.22, 1.7e-5, .024, 5.3)]):
        reynolds, hv, kff = reference.legacy_air_fields(geometry, speed, rho, mu, conductivity, nu)
        np.testing.assert_array_equal(observed[index], reynolds, strict=True)
        np.testing.assert_array_equal(actual['h_v' + 'AB'[index] + '_arr'], hv, strict=True)
        np.testing.assert_array_equal(actual['K_ff' + 'AB'[index] + '_arr'], kff, strict=True)


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('form', ['scalar', 'zero-d', 'array', 'empty', 'noncontiguous'])
def test_closure_ratio_keeps_original_unit_order_and_dtype(dtype, form):
    if form == 'scalar':
        diameter, cell = dtype(.00273451), dtype(7.1345)
    elif form == 'zero-d':
        diameter, cell = np.array(.00273451, dtype=dtype), np.array(7.1345, dtype=dtype)
    elif form == 'empty':
        diameter, cell = np.empty((0, 2), dtype=dtype), np.array([6.1, 7.3], dtype=dtype)
    else:
        diameter = np.linspace(.0017, .0039, 24, dtype=dtype).reshape(4, 6)
        cell = np.linspace(4.3, 7.7, 6, dtype=dtype)
        if form == 'noncontiguous':
            diameter, cell = diameter[:, ::2], cell[::2]
    expected = reference.closure_geometry_ratio(diameter, cell)
    actual = native.closure_geometry_ratio(diameter, cell)
    assert type(actual) is type(expected)
    np.testing.assert_array_equal(actual, expected, strict=True)


@pytest.mark.parametrize('diameter', [.00273451, np.float16(.00273451), np.float64(.00273451)])
def test_closure_ratio_preserves_scalar_step_before_mixed_array(diameter):
    cell = np.array([[6.1], [7.3]], dtype=np.float32)
    expected = reference.closure_geometry_ratio(diameter, cell)
    np.testing.assert_array_equal(native.closure_geometry_ratio(diameter, cell), expected, strict=True)


def test_ratio_boundary_preserves_values_and_kind_after_input_error():
    _packed, values = native._values(np.linspace(.001, .003, 9))
    short = native._Values(values.data, 8, 64, 1)
    output, kind, error = np.full(9, 913.25), native._Scalar(7., 16, 1), ct.create_string_buffer(256)
    before, before_kind = output.tobytes(), bytes(kind)
    status = native._current().closure_geometry_ratio(values, short, output.ctypes.data_as(native._DP),
        output.size, ct.byref(kind), error, len(error))
    assert status == 1 and output.tobytes() == before and bytes(kind) == before_kind


def _sentinel(count):
    return (native._Scalar * count)(*(native._Scalar(913.25, 32, 1) for _ in range(count)))


def test_c_boundary_rejects_mismatch_and_preserves_scalar_output():
    source = np.linspace(.2, .8, 9)
    _packed, values = native._values(source)
    short = native._Values(values.data, 8, 64, 1)
    output, error = _sentinel(1), ct.create_string_buffer(256)
    before = bytes(output)
    status = native._current().inlet_capacity_2d(values, values, short, values,
        native._scalar(1.), native._scalar(.1), output, 1, error, len(error))
    assert status == 1 and bytes(output) == before
    assert b'extents' in error.value


def test_c_boundary_rejects_output_input_overlap_before_writing():
    source = np.linspace(.2, .8, 9)
    packed, values = native._values(source)
    output = ct.cast(values.data, native._SP)
    error, before = ct.create_string_buffer(256), packed.tobytes()
    status = native._current().inlet_capacity_2d(values, values, values, values,
        native._scalar(1.), native._scalar(.1), output, 1, error, len(error))
    assert status == 1 and packed.tobytes() == before
    assert b'overlaps' in error.value


def test_c_boundary_rejects_error_output_overlap_without_writing_either():
    output = _sentinel(2)
    before = bytes(output)
    error = ct.cast(output, ct.POINTER(ct.c_char))
    status = native._current().quick_design_flow(
        native._scalar(.1), native._scalar(.01), native._scalar(1.), 0,
        output, 2, error, ct.sizeof(output))
    assert status == 1 and bytes(output) == before


def test_c_boundary_rejects_error_input_overlap_without_writing_input_or_output():
    packed, values = native._values(np.linspace(.2, .8, 9))
    output = _sentinel(1)
    before, before_output = packed.tobytes(), bytes(output)
    error = ct.cast(values.data, ct.POINTER(ct.c_char))
    status = native._current().inlet_capacity_2d(values, values, values, values,
        native._scalar(1.), native._scalar(.1), output, 1, error, packed.nbytes)
    assert status == 1 and packed.tobytes() == before and bytes(output) == before_output


def test_late_scalar_division_failure_preserves_all_speeds():
    targets = (native._Scalar * 2)(native._scalar(.1), native._scalar(.2))
    capacities = (native._Scalar * 2)(native._scalar(.01), native._scalar(0.))
    output, error = _sentinel(2), ct.create_string_buffer(256)
    before = bytes(output)
    status = native._current().inlet_speeds(targets, capacities, 2, output, 2, error, len(error))
    assert status == 3 and bytes(output) == before
    assert error.value == b'float division by zero'
