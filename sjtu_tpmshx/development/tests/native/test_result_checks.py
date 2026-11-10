"""Check the result leaves against the original independent expressions."""
import ctypes as ct
import math
import warnings
from decimal import Decimal

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import result_envelope_reference as original_envelope
from sjtu_tpmshx.development.tests import result_range_reference as original_range
from sjtu_tpmshx.development.tests import result_warning_reference as original_warning
from sjtu_tpmshx.shared import _native_result_checks as checks
from sjtu_tpmshx.shared.domain import range_policy, run_warnings
from sjtu_tpmshx.shared.models import envelope


def observe(function, *args, **kwargs):
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('always')
        try:
            value = function(*args, **kwargs)
        except Exception as error:
            result = ('error', type(error).__name__, error.args)
        else:
            result = ('value', value)
    return result, [(type(item.message).__name__, str(item.message)) for item in emitted]


def assert_observations(actual, expected):
    got, got_warnings = actual
    want, want_warnings = expected
    assert got_warnings == want_warnings
    assert got[0] == want[0]
    if got[0] == 'error':
        assert got == want
    else:
        if isinstance(got[1], tuple) and len(got[1]) == 2 and isinstance(got[1][1], list):
            assert got[1] == want[1]
        else:
            np.testing.assert_array_equal(got[1], want[1])
        if np.isscalar(got[1]) and np.isrealobj(got[1]) and got[1] == 0:
            assert np.signbit(got[1]) == np.signbit(want[1])


def sample(minimum=100., maximum=200., bounds=(100., 200.), **changes):
    result = dict(captured=True, bounds=bounds, shape=(2,), size=2,
                  low=0, high=0, nonfinite=0,
                  minimum=(minimum, (0,)), maximum=(maximum, (1,)))
    result.update(changes)
    return result


@pytest.mark.parametrize('row', [
    sample(), sample(90., 220.), sample(np.nextafter(90., -np.inf), 220.),
    sample(np.nextafter(np.nextafter(90., -np.inf), -np.inf), 220.),
    sample(89., 221.), sample(-1., 1., (-1., 1.)), sample(-2., 1., (-1., 1.)),
    sample(0., 1., (0., 1.)), sample(0., 2., (0., 1.), constraint='hard_bounds'),
    sample(nonfinite=1), dict(sample(), minimum=None),
    sample(size=2**80, shape=(2**80,), nonfinite=2**80),
    sample(1e-320, 1e-319, (1e-320, 1e-319)),
])
def test_range_verdict_matches_original(row):
    assert range_policy.assess_range(row) == original_range.assess_range(row)


@pytest.mark.parametrize('row', [
    sample(captured=1), sample(bounds=(np.nan, 2.)), sample(bounds=(2., 1.)),
    sample(size=0), sample(shape=(3,)), sample(low=-1), sample(high=3),
    sample(constraint='invalid'), sample(np.nan), sample(201., 200.),
])
def test_range_error_type_message_and_order(row):
    assert_observations(observe(range_policy.assess_range, row),
                        observe(original_range.assess_range, row))


@pytest.mark.parametrize('bounds', [(1., 10.), (.1, .25), (1e-320, 1e-319),
                                    (0., 1.), (-1., 1.), (2., 1.), (1., np.inf)])
def test_parameter_bounds_matches_original(bounds):
    assert_observations(observe(range_policy.parameter_bounds, bounds),
                        observe(original_range.parameter_bounds, bounds))


def collect(function, values, bounds):
    with run_warnings.warning_scope({}) as records, run_warnings.range_context(
            side='B', stage='thermal', layout='cell'):
        function(('property', 'sample'), values, bounds, label='sample', quantity='T', unit='K')
        function(('property', 'sample'), values, bounds, label='sample', quantity='T', unit='K')
    return records, run_warnings.range_observations(records), list(run_warnings.warning_messages(records))


@pytest.mark.parametrize('values', [
    np.array(300.), np.array([]), np.array([np.nan, np.inf, -np.inf]),
    np.array([-0., 0., -0., 0.]),
    np.array([[np.nan, 250., 400.], [200., 400., np.inf]]),
    np.asfortranarray([[250., 200., 400.], [200., 400., -np.inf]]),
    np.array([[250., 200., 400.], [200., 400., -np.inf]])[::-1, ::-1],
])
@pytest.mark.parametrize('bounds', [(250., 350.), (np.nan, 350.), (250., np.nan)])
def test_range_collector_keeps_original_records_and_messages(values, bounds):
    actual = collect(run_warnings.record_range, values, bounds)
    expected = collect(original_warning.record_range, values, bounds)
    # The DTOs share ownership; the numerical collectors are independent.
    assert actual == expected
    if values.size and np.all(np.isfinite(values)) and np.all(values == 0):
        got = next(iter(actual[0].values()))
        want = next(iter(expected[0].values()))
        assert np.signbit(got.minimum[0]) == np.signbit(want.minimum[0])
        assert np.signbit(got.maximum[0]) == np.signbit(want.maximum[0])


@pytest.mark.parametrize('values', [
    np.array([], dtype=np.int64), np.array([0, 0], dtype='>i8'),
    np.array([2**63, 2**64 - 1], dtype=np.uint64),
    np.array([2**63 + 1, 0], dtype=np.uint64)[::-1],
    np.array([False, True]), np.array([0., -0.], dtype=np.float16),
    np.array([0., np.inf], dtype=np.float32), np.array([np.nan, 0.]),
    np.array([complex(0., -0.), complex(1., np.inf)]),
    np.array([0, 1], dtype=np.longdouble),
])
def test_finite_and_zero_scans_keep_dtype_and_stride(values):
    expected = bool(np.all(np.isfinite(values))), bool(np.all(values == 0))
    assert checks.array_checks(values) == expected
    assert checks.all_finite(values) is expected[0]
    assert checks.all_zero(values) is expected[1]


def test_finite_scan_does_not_narrow_longdouble():
    if np.finfo(np.longdouble).max <= np.finfo(np.float64).max:
        pytest.skip('This platform has no wider long double.')
    values = np.array([np.finfo(np.longdouble).max], dtype=np.longdouble)
    assert checks.array_checks(values) == (True, False)


@pytest.mark.parametrize('ratio,tolerance', [
    (0., .01), (.01, .01), (np.nextafter(.01, np.inf), .01),
    (-0., 0.), (-.1, .01), (np.nan, .01), (np.inf, .01), (.01, np.nan),
    (np.float16(.01), np.float16(.01)), (np.float32(.01), .01),
    (np.float16(1.), 1e308), (np.float16(0.), 1e-300),
    (float(2**63), 2**63 + 1), (2**63 + 1, float(2**63)),
    (Decimal('.01'), Decimal('.01')), ('bad', .01), (1 + 2j, .01),
])
def test_energy_gate_keeps_original_finite_conversions_and_comparisons(ratio, tolerance):
    def original():
        return bool(math.isfinite(ratio) and math.isfinite(tolerance)
                    and 0. <= ratio <= tolerance and tolerance > 0.)
    assert_observations(observe(checks.energy_ratio, ratio, tolerance), observe(original))


@pytest.mark.parametrize('density,length,height,depth,epsilon', [
    (7800., .1, .2, .03, .6), (2**53 + 1, 3, 5, 7, .6),
    (2**62, 4, 3, 2, .6), (np.int64(7), np.int64(3), np.int64(5), np.int64(2), .6),
    (np.float16(7800), np.float16(.1), np.float16(.2), np.float16(.03), np.float16(.6)),
    (np.float32(7800), .1, np.float32(.2), .03, np.float32(.6)),
    (np.longdouble('7800.1'), .1, .2, .03, np.longdouble('.6')),
    (np.array(7800.), .1, .2, .03, .6),
    (7., np.array(.1), np.array(.2), .03, np.array(.6)),
    (np.array(1. + 2.j, dtype=np.complex64), .1, .2, .03, .6),
    (Decimal('7.5'), Decimal('.1'), Decimal('.2'), Decimal('.03'), Decimal('.6')),
    (1. + 2.j, .1, .2, .03, .6), (np.complex64(1. + 2.j), .1, .2, .03, .6),
])
def test_box_mass_keeps_original_intermediates(density, length, height, depth, epsilon):
    def original():
        return float(density * length * height * depth * (1. - epsilon))

    def actual():
        prefix = checks.box_density_length(density, length)
        bulk = checks.box_bulk_mass(prefix, height, depth)
        return float(checks.box_solid_mass(bulk, epsilon))
    assert_observations(observe(actual), observe(original))


@pytest.mark.parametrize('mode', ['warn', 'raise'])
def test_box_mass_emits_first_stage_fp_before_later_conversion_failure(mode):
    density, length, epsilon = np.float32(np.finfo(np.float32).max), np.float32(2.), object()

    def original():
        return float(density * length * 1. * 1. * (1. - epsilon))

    def actual():
        prefix = checks.box_density_length(density, length)
        bulk = checks.box_bulk_mass(prefix, 1., 1.)
        return float(checks.box_solid_mass(bulk, epsilon))

    with np.errstate(all=mode):
        expected = observe(original)
        actual = observe(actual)
    assert_observations(actual, expected)


def test_zero_dimensional_box_results_become_numpy_scalars_after_each_operation():
    density, length, height, depth, epsilon = np.array(7.), .1, np.array(.2), .03, np.array(.6)
    prefix = checks.box_density_length(density, length)
    expected_prefix = density * length
    assert type(prefix) is type(expected_prefix)
    bulk = checks.box_bulk_mass(prefix, height, depth)
    expected_bulk = expected_prefix * height * depth
    assert type(bulk) is type(expected_bulk)
    mass = checks.box_solid_mass(bulk, epsilon)
    expected_mass = expected_bulk * (1. - epsilon)
    assert type(mass) is type(expected_mass)
    assert mass == expected_mass


def test_zero_dimensional_box_operation_keeps_array_then_scalar_fp_labels():
    density, length, height = np.array(np.finfo(np.float32).max, dtype=np.float32), np.float32(2.), 0.

    def original():
        return density * length * height * 1. * (1. - .6)

    def actual():
        prefix = checks.box_density_length(density, length)
        bulk = checks.box_bulk_mass(prefix, height, 1.)
        return checks.box_solid_mass(bulk, .6)

    with np.errstate(all='warn'):
        assert_observations(observe(actual), observe(original))


@pytest.mark.parametrize('array', [
    np.array([], dtype=np.float64), np.array([2.]), np.array([[2.]]), np.array([2., 3.]),
    np.array(2. + 1.j, dtype=np.complex64),
    np.array([2.], dtype=np.float16), np.array([2.], dtype=np.float32),
    np.array([2**63 + 1], dtype=np.uint64), np.array([2. + 1.j], dtype=np.complex64),
    np.array([np.finfo(np.float32).max], dtype=np.float32),
    np.array([2., 3., 4.], dtype=np.float32)[::-1],
])
@pytest.mark.parametrize('slot', range(5))
def test_box_array_expression_keeps_final_float_protocol(array, slot):
    values = [7., .1, .2, .03, .6]
    values[slot] = array
    density, length, height, depth, epsilon = values

    def original():
        return float(density * length * height * depth * (1. - epsilon))

    def actual():
        prefix = checks.box_density_length(density, length)
        bulk = checks.box_bulk_mass(prefix, height, depth)
        return float(checks.box_solid_mass(bulk, epsilon))

    assert_observations(observe(actual), observe(original))


@pytest.mark.parametrize('values', [
    (np.array([[7.], [8.]]), np.array([.1, .2, .3]), .2, .03, .6),
    (np.array([np.finfo(np.float32).max], dtype=np.float32), np.float32(2.), np.ones(3), np.ones(2), .6),
    (np.array([np.finfo(np.float32).max], dtype=np.float32), np.float32(2.), 1., 1., np.ones(2)),
])
def test_box_array_intermediates_keep_dtype_shape_and_fp_order(values):
    density, length, height, depth, epsilon = values

    def original():
        return density * length * height * depth * (1. - epsilon)

    def actual():
        prefix = checks.box_density_length(density, length)
        bulk = checks.box_bulk_mass(prefix, height, depth)
        return checks.box_solid_mass(bulk, epsilon)

    got, want = observe(actual), observe(original)
    assert_observations(got, want)
    if got[0][0] == 'value':
        assert got[0][1].dtype == want[0][1].dtype
        assert got[0][1].shape == want[0][1].shape


@pytest.mark.parametrize('target', [
    np.full(2, 123., dtype=np.float32), np.full((1, 2), 123., dtype=np.float64),
])
def test_box_array_output_contract_failure_is_atomic(target):
    density, length = checks.native.array(np.array([2., 3.])), checks.native.array(.1)
    output = checks.native.array(target)
    before = target.copy()
    with pytest.raises(ValueError, match='output dtype or shape'):
        checks._call('box_density_length_array', [checks._Array, checks._Array, ct.POINTER(checks._Array)],
                     density.raw, length.raw, ct.byref(output.raw))
    np.testing.assert_array_equal(target, before)


def test_box_array_rejects_alias_before_mutation():
    values = np.array([2., 3.])
    density, length, output = checks.native.array(values), checks.native.array(.1), checks.native.array(values)
    with pytest.raises(ValueError, match='overlaps'):
        checks._call('box_density_length_array', [checks._Array, checks._Array, ct.POINTER(checks._Array)],
                     density.raw, length.raw, ct.byref(output.raw))
    np.testing.assert_array_equal(values, [2., 3.])


@pytest.mark.parametrize('dtype', ['<f8', '>f8'])
def test_box_array_typed_output_keeps_byte_order_and_negative_stride(dtype):
    values = np.array([2., 3.], dtype=dtype)
    target = np.full(2, 123., dtype=dtype)[::-1]
    density, length, output = checks.native.array(values), checks.native.array(.1), checks.native.array(target)
    checks._call('box_density_length_array', [checks._Array, checks._Array, ct.POINTER(checks._Array)],
                 density.raw, length.raw, ct.byref(output.raw))
    np.testing.assert_array_equal(target, values * .1)
    assert target.dtype == np.dtype(dtype)


@pytest.mark.parametrize('name,args,kwargs', [
    ('predict_outlet_p_sq', (2e5, 300., 8000., .1), {}),
    ('predict_outlet_p_sq', (1e308, object(), object(), object()), {}),
    ('predict_outlet_p_sq', (np.inf, 300., 8000., .1), {}),
    ('mach', (300., 300.), {}), ('mach', (300., 0.), {}),
    ('mach', (object(), -1.), {}), ('mach', (0., np.nan), {}),
    ('mach', (1., 300.), {'gamma': -1.}),
])
def test_scalar_envelope_keeps_results_exceptions_and_conversion_order(name, args, kwargs):
    assert_observations(observe(getattr(envelope, name), *args, **kwargs),
                        observe(getattr(original_envelope, name), *args, **kwargs))


@pytest.mark.parametrize('speed,temperature,kwargs', [
    (np.empty((0, 3)), object(), {}),
    (np.array([300., 100.]), np.array([300., 1.]), {}),
    (np.array([[300.], [100.]]), np.array([300., 1.]), {}),
    (np.asfortranarray([[0., -0.], [-0., 0.]]), 300., {}),
    (np.array([1., np.inf, np.nan]), np.array([-1., 0., np.inf]), {}),
    (np.array([1., 2.]), np.array([300., 400., 500.]), {}),
    (np.array([[1.], [2.]]), np.empty((1, 0)), {}),
    (np.array([1., 2.]), 300., {'gamma': -1.}),
    (np.array([1e308]), 1e308, {'gamma': 1e308}),
    (np.array([1., 0.]), 300., {'gamma': 0.}),
])
@pytest.mark.parametrize('mode', ['warn', 'raise'])
def test_field_envelope_keeps_original_ufunc_events(speed, temperature, kwargs, mode):
    with np.errstate(all=mode):
        expected = observe(original_envelope.mach_field_max, speed, temperature, **kwargs)
        actual = observe(envelope.mach_field_max, speed, temperature, **kwargs)
    assert_observations(actual, expected)


@pytest.mark.parametrize('pressure,maximum,limit', [
    (150e3, .02, 1.), (1e3, 1., 1.), (np.nan, np.inf, 1.),
    (np.float16(1000.), .02, np.float16(1.)),
    (150e3, float(2**63), 2**63 + 1), (150e3, np.nan, object()),
])
def test_envelope_keeps_validity_reason_order_and_limit_types(pressure, maximum, limit):
    actual = envelope.assess_solution_validity(pressure, object(), object(), ma_max=maximum, mach_limit=limit)
    expected = original_envelope.assess_solution_validity(pressure, object(), object(), ma_max=maximum, mach_limit=limit)
    assert actual == expected


@pytest.mark.parametrize('pressure,maximum,limit', [
    (1. + 2.j, .02, 1.), (complex(np.nan, 1.), .02, 1.),
    (150e3, .02, 1. + 2.j), (150e3, np.nan, 1. + 2.j),
    (np.complex64(1. + 2.j), .02, 1.),
])
def test_envelope_keeps_complex_type_protocol_errors(pressure, maximum, limit):
    assert_observations(
        observe(envelope.assess_solution_validity, pressure, 0., 300., ma_max=maximum, mach_limit=limit),
        observe(original_envelope.assess_solution_validity, pressure, 0., 300., ma_max=maximum, mach_limit=limit))


@pytest.mark.parametrize('value', [
    np.array(500.), np.array([], dtype=float), np.array([500.]), np.array([[500.]]),
    np.array([150000.]), np.array([500., 150000.]), np.array([np.nan]),
    np.array([-.25]), np.array([500. + 1.j], dtype=np.complex64),
    np.array([-.25 + 1.j], dtype=np.complex64), np.array([], dtype=object),
    np.array([500.], dtype=object),
])
@pytest.mark.parametrize('slot', ['pressure', 'mach_limit', 'ma_max'])
def test_envelope_scalar_array_truth_and_original_float_protocol(value, slot):
    args, kwargs = [150000., 1., 300.], dict(ma_max=.5)
    if slot == 'pressure':
        args[0] = value
    else:
        kwargs[slot] = value
    assert_observations(observe(envelope.assess_solution_validity, *args, **kwargs),
                        observe(original_envelope.assess_solution_validity, *args, **kwargs))


@pytest.mark.parametrize('shape', [(), (0,), (1,), (2,)])
@pytest.mark.parametrize('mode', ['warn', 'raise'])
def test_mach_limit_array_cast_precedes_truth_and_original_float(shape, mode):
    limit = np.zeros(shape, dtype=np.float16)
    with np.errstate(all=mode):
        expected = observe(original_envelope.assess_solution_validity, 150000., 1., 300.,
                           ma_max=1e308, mach_limit=limit)
        actual = observe(envelope.assess_solution_validity, 150000., 1., 300.,
                         ma_max=1e308, mach_limit=limit)
    assert_observations(actual, expected)
    if mode == 'raise':
        assert actual == (('error', 'FloatingPointError', ('overflow encountered in cast',)), [])
    else:
        assert actual[1] == [('RuntimeWarning', 'overflow encountered in cast')]
        if shape == ():
            assert actual[0][0] == 'value' and actual[0][1][0] is False
        elif shape == (1,):
            assert actual[0] == ('error', 'TypeError', (
                'only 0-dimensional arrays can be converted to Python scalars',))
        elif shape == (0,):
            assert actual[0] == ('error', 'ValueError', (
                'The truth value of an empty array is ambiguous. Use `array.size > 0` to check that an array is not empty.',))
        else:
            assert actual[0] == ('error', 'ValueError', (
                'The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()',))


@pytest.mark.parametrize('shape', [(0,), (1,), (2,)])
def test_nonfinite_mach_skips_array_limit_cast_and_truth(monkeypatch, shape):
    limit = np.zeros(shape, dtype=np.float16)
    original_output = checks._output

    def guarded(name, signature, arguments, kind):
        if name == 'mach_limit_array_flags':
            pytest.fail('Nonfinite Mach must skip the limit comparison.')
        return original_output(name, signature, arguments, kind)

    monkeypatch.setattr(checks, '_output', guarded)
    with np.errstate(all='raise'):
        assert_observations(
            observe(envelope.assess_solution_validity, 150000., 1., 300., ma_max=np.nan, mach_limit=limit),
            observe(original_envelope.assess_solution_validity, 150000., 1., 300., ma_max=np.nan, mach_limit=limit))


def test_disabled_and_empty_paths_do_not_need_result_image(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('An empty or capture-disabled operation must not call native code.')

    monkeypatch.setattr(checks.native, 'call', forbidden)
    assert run_warnings.record_range(('sample',), object(), object(), label='', quantity='', unit='') is False
    with run_warnings.warning_scope({}) as records:
        assert run_warnings.record_range(('sample',), [], object(), label='', quantity='', unit='') is True
    assert not records
    assert range_policy.assess_range({'captured': False})['status'] == 'unavailable'
    assert checks.all_finite(np.array([])) is True
    assert checks.all_zero(np.array([])) is True
    assert envelope.mach_field_max([], object()) == 0.


def test_original_property_and_df_references_remain_native_free_under_capture(monkeypatch):
    from sjtu_tpmshx.development.tests import df_reference, property_reference

    def forbidden(*args, **kwargs):
        pytest.fail('The independent numerical reference must not call the production result library.')

    monkeypatch.setattr(checks.native, 'call', forbidden)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('always')
        with run_warnings.warning_scope({}) as records:
            heat_capacity = property_reference.air_cp(np.array([200., 1200.]))
            permeability, drag, metadata = df_reference.apply_correction(
                'Gyroid', 'water', 7., .6, 1e-8, 100., .02)
    assert np.all(np.isfinite(heat_capacity)) and permeability > 0 and drag > 0
    assert metadata['extrapolated'] is True
    assert not emitted
    observations = run_warnings.range_observations(records)
    assert [row['source'] for row in observations] == [
        ('property', 'air_cp'), ('df-experimental', 'water', 'Gyroid')]
    assert observations[0]['low'] == observations[0]['high'] == 1
    assert observations[1]['low'] == 1
    messages = list(run_warnings.warning_messages(records))
    assert len(messages) == 2
    assert 'air_cp:' in messages[0] and '[D-F extrap]' in messages[1]
