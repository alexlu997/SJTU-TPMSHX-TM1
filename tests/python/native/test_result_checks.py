"""Check the float64 result check leaves against independent expressions."""
import ctypes as ct
from functools import partial
import math
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from tests.python import result_envelope_reference as original_envelope
from tests.python import result_range_reference as original_range
from sjtu_tpmshx.cpp_interface import _native_result_checks as checks
from sjtu_tpmshx.physical_models import range_policy
from sjtu_tpmshx.run_control import run_warnings
from sjtu_tpmshx.physical_models import envelope


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


def _reference_collect(array, lo, hi):
    flat = np.asarray(array, dtype=np.float64).ravel()
    finite = np.isfinite(flat)
    finite_idx = np.flatnonzero(finite)
    if finite_idx.size:
        finite_vals = flat[finite_idx]
        min_pos = int(np.argmin(finite_vals))
        max_pos = int(np.argmax(finite_vals))
        return SimpleNamespace(
            have_finite=1,
            minimum=float(finite_vals[min_pos]),
            maximum=float(finite_vals[max_pos]),
            minimum_index=int(finite_idx[min_pos]),
            maximum_index=int(finite_idx[max_pos]),
            low=int(np.count_nonzero(finite_vals < lo)),
            high=int(np.count_nonzero(finite_vals > hi)),
            size=int(flat.size),
            nonfinite=int(flat.size - finite_idx.size),
        )
    return SimpleNamespace(
        have_finite=0, minimum=0., maximum=0., minimum_index=0, maximum_index=0,
        low=0, high=0, size=int(flat.size), nonfinite=int(flat.size),
    )


def collect(values, bounds, record):
    with run_warnings.warning_scope({}) as records, run_warnings.range_context(
            side='B', stage='thermal', layout='cell'):
        for _ in range(2):
            record(('property', 'sample'), values, bounds, label='sample', quantity='T', unit='K')
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
    actual = collect(values, bounds, checks.record_range)
    expected = collect(values, bounds, partial(run_warnings.record_range, collect=_reference_collect))
    assert actual == expected
    if values.size and np.all(np.isfinite(values)) and np.all(values == 0):
        got = next(iter(actual[0].values()))
        want = next(iter(expected[0].values()))
        assert np.signbit(got.minimum[0]) == np.signbit(want.minimum[0])
        assert np.signbit(got.maximum[0]) == np.signbit(want.maximum[0])


@pytest.mark.parametrize('values', [
    np.array([], dtype=np.float64), np.array([0., 0.], dtype='>f8'),
    np.array([0, 0], dtype=np.int32), np.array([0., -0.], dtype=np.float64),
    np.array([0., np.inf], dtype=np.float32), np.array([np.nan, 0.]),
    np.array([1., 2., 3.])[::-1],
])
def test_finite_and_zero_scans_keep_float64_and_stride(values):
    expected = bool(np.all(np.isfinite(values))), bool(np.all(values == 0))
    assert checks.array_checks(values) == expected
    assert checks.all_finite(values) is expected[0]
    assert checks.all_zero(values) is expected[1]


@pytest.mark.parametrize('bad', [np.array([True, False]), np.array([1. + 2.j]), np.array(['a']), np.array([1.], dtype=object)])
def test_array_checks_reject_non_real_types(bad):
    with pytest.raises(TypeError):
        checks.array_checks(bad)
    with pytest.raises(TypeError):
        checks.all_finite(bad)
    with pytest.raises(TypeError):
        checks.all_zero(bad)


@pytest.mark.parametrize('ratio,tolerance', [
    (0., .01), (.01, .01), (np.nextafter(.01, np.inf), .01),
    (-0., 0.), (-.1, .01), (np.nan, .01), (np.inf, .01), (.01, np.nan),
    (np.float32(.01), .01), (0, 1),
])
def test_energy_gate_matches_float64_contract(ratio, tolerance):
    expected = bool(math.isfinite(float(ratio)) and math.isfinite(float(tolerance))
                    and 0. <= float(ratio) <= float(tolerance) and float(tolerance) > 0.)
    assert checks.energy_ratio(ratio, tolerance) is expected


@pytest.mark.parametrize('ratio,tolerance', [
    (True, .01), (.01, False), ('bad', .01), (1 + 2j, .01), (None, .01),
])
def test_energy_gate_rejects_non_real_scalars(ratio, tolerance):
    with pytest.raises(TypeError):
        checks.energy_ratio(ratio, tolerance)


@pytest.mark.parametrize('density,length,height,depth,epsilon', [
    (7800., .1, .2, .03, .6), (7, 3, 5, 2, .6),
    (np.int64(7), np.int64(3), np.int64(5), np.int64(2), .6),
    (np.float32(7800.), .1, np.float32(.2), .03, np.float32(.6)),
    (np.array(7800.), .1, .2, .03, .6),
    (7., np.array(.1), np.array(.2), .03, np.array(.6)),
])
def test_box_mass_matches_float64_intermediates(density, length, height, depth, epsilon):
    d, l, h, p, e = map(float, (density, length, height, depth, epsilon))
    expected = float(d * l * h * p * (1. - e))
    prefix = checks.box_density_length(density, length)
    bulk = checks.box_bulk_mass(prefix, height, depth)
    actual = float(checks.box_solid_mass(bulk, epsilon))
    assert actual == expected


@pytest.mark.parametrize('array', [
    np.array([], dtype=np.float64), np.array([2.]), np.array([[2.]]), np.array([2., 3.]),
    np.array([2., 3., 4.], dtype=np.float64)[::-1],
])
@pytest.mark.parametrize('slot', range(5))
def test_box_array_expression_matches_float64(array, slot):
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


def test_box_array_broadcast_and_overflow_order():
    density, length = np.array([[7.], [8.]]), np.array([.1, .2, .3])
    prefix = checks.box_density_length(density, length)
    bulk = checks.box_bulk_mass(prefix, .2, .03)
    actual = checks.box_solid_mass(bulk, .6)
    expected = density * length * .2 * .03 * (1. - .6)
    assert actual.dtype == np.float64 and actual.shape == expected.shape
    np.testing.assert_array_equal(actual, expected)


def test_box_array_output_contract_failure_is_atomic():
    target = np.full((1, 2), 123., dtype=np.float64)
    density, length = checks.native.array(np.array([2., 3.])), checks.native.array(.1)
    output = checks.native.array(target)
    before = target.copy()
    with pytest.raises(ValueError, match='output shape'):
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
def test_field_envelope_keeps_fixed_warning_events(speed, temperature, kwargs):
    expected = observe(original_envelope.mach_field_max, speed, temperature, **kwargs)
    actual = observe(envelope.mach_field_max, speed, temperature, **kwargs)
    assert_observations(actual, expected)


@pytest.mark.parametrize('pressure,maximum,limit', [
    (150e3, .02, 1.), (1e3, 1., 1.), (np.nan, np.inf, 1.),
    (150e3, np.nan, object()),
])
def test_envelope_keeps_validity_reason_order(pressure, maximum, limit):
    actual = envelope.assess_solution_validity(pressure, object(), object(), ma_max=maximum, mach_limit=limit)
    expected = original_envelope.assess_solution_validity(pressure, object(), object(), ma_max=maximum, mach_limit=limit)
    assert actual == expected


@pytest.mark.parametrize('pressure,maximum,limit', [
    (1. + 2.j, .02, 1.), (150e3, .02, 1. + 2.j), (True, .02, 1.),
])
def test_envelope_rejects_non_real_scalars(pressure, maximum, limit):
    with pytest.raises(TypeError):
        envelope.assess_solution_validity(pressure, 0., 300., ma_max=maximum, mach_limit=limit)


@pytest.mark.parametrize('shape', [(0,), (1,), (2,)])
def test_nonfinite_mach_skips_array_limit_comparison(monkeypatch, shape):
    limit = np.zeros(shape, dtype=np.float64)
    original_output = checks._output

    def guarded(name, signature, arguments, kind):
        if name == 'mach_limit_array_flags':
            pytest.fail('Nonfinite Mach must skip the limit comparison.')
        return original_output(name, signature, arguments, kind)

    monkeypatch.setattr(checks, '_output', guarded)
    assert_observations(
        observe(envelope.assess_solution_validity, 150000., 1., 300., ma_max=np.nan, mach_limit=limit),
        observe(original_envelope.assess_solution_validity, 150000., 1., 300., ma_max=np.nan, mach_limit=limit))


def test_disabled_and_empty_paths_do_not_need_result_image(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('An empty or capture-disabled operation must not call native code.')

    monkeypatch.setattr(checks.native, 'call', forbidden)
    assert checks.record_range(('sample',), object(), object(), label='', quantity='', unit='') is False
    with run_warnings.warning_scope({}) as records:
        assert checks.record_range(('sample',), [], object(), label='', quantity='', unit='') is True
    assert not records
    assert range_policy.assess_range({'captured': False})['status'] == 'unavailable'
    assert checks.all_finite(np.array([])) is True
    assert checks.all_zero(np.array([])) is True
    assert envelope.mach_field_max([], object()) == 0.
