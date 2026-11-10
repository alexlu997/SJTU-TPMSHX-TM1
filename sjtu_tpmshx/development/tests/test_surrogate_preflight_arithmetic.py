"""Preflight values retain the original expressions and query order."""
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.shared.df_surrogate import surrogate_domain
from sjtu_tpmshx.shared.domain import run_warnings
from sjtu_tpmshx.shared.models import co2_correlations, fluid_props


def _observe(function):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all='warn'):
        warnings.simplefilter('always')
        try:
            value = function()
        except Exception as error:
            result = ('error', type(error), error.args)
        else:
            result = ('value', type(value), np.asarray(value))
    notes = [(item.category, str(item.message)) for item in caught
             if issubclass(item.category, RuntimeWarning)]
    return result, notes


def _assert_observation(actual, expected):
    first, notes = actual
    second, expected_notes = expected
    assert notes == expected_notes
    assert first[:2] == second[:2]
    if first[0] == 'error':
        assert first[2] == second[2]
        return
    assert first[2].dtype == second[2].dtype
    assert first[2].shape == second[2].shape
    np.testing.assert_array_equal(first[2], second[2])
    np.testing.assert_array_equal(np.signbit(first[2]), np.signbit(second[2]))


def _inputs(monkeypatch, *, fluid='air', diameter=.012345, mu=.003125,
            cp=1010.125, conductivity=.075, fail=None):
    calls, captured, geometry_args = [], [], []
    values = dict(rho=np.float32(1.2345), mu=mu, cp=cp, k=conductivity)
    failure = LookupError('original ' + str(fail) + ' failure')

    def query(name):
        def get(_temperature, _pressure):
            calls.append(name)
            if fail == name:
                raise failure
            return values[name]
        return get

    model = SimpleNamespace(name=fluid, **{name: query(name) for name in values})
    monkeypatch.setattr(fluid_props, 'get', lambda _fluid: model)

    def geometry(*arguments):
        calls.append('geometry')
        geometry_args.append(arguments)
        if fail == 'geometry':
            raise failure
        return {'D_h': diameter}

    monkeypatch.setattr(surrogate_domain, '_geom', geometry)
    monkeypatch.setattr(co2_correlations, 'geometry', geometry)
    monkeypatch.setattr(co2_correlations, 'coefficients',
                        lambda: {'bounds': {'Pr': (.1, 10.)}})

    def record(source, value, bounds, **labels):
        calls.append('range-' + labels['quantity'])
        captured.append((source, value, bounds, labels))
        return False

    monkeypatch.setattr(run_warnings, 'record_range', record)
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    return values, calls, captured, geometry_args, failure


@pytest.mark.parametrize('speed_type', [float, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('geometry_type', [float, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('sign', [-1., 0., 1.])
def test_preflight_reynolds_keeps_ordered_scalar_expression(
        monkeypatch, speed_type, geometry_type, sign):
    speed, diameter = speed_type(sign * 2.125), geometry_type(.012345)
    values, calls, captured, geometry_args, _ = _inputs(
        monkeypatch, diameter=diameter, mu=np.float16(.003125))
    cell, wall = geometry_type(6.), geometry_type(.4)

    def actual():
        surrogate_domain.check_surrogate_domain_at_point(
            'Gyroid', cell, wall, 16., speed, 300., allow_extrap=True)
        return captured[0][1]

    # These are the original preflight operations, independent of native code.
    expected = _observe(lambda: float(values['rho']) * speed * diameter / float(values['mu']))
    _assert_observation(_observe(actual), expected)
    assert calls == ['rho', 'mu', 'geometry', 'range-Re']
    assert geometry_args[0][1] is cell
    assert geometry_args[0][2] is wall
    assert captured[0][0] == ('nu', 'air', 'Gyroid')
    assert captured[0][3] == dict(label='air inlet Nu', quantity='Re', unit='-')


@pytest.mark.parametrize('speed_type', [float, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('zero', [0., -0.])
def test_preflight_reynolds_zero_divisor_keeps_scalar_policy(monkeypatch, speed_type, zero):
    speed, diameter = speed_type(2.125), .012345
    values, _, captured, _, _ = _inputs(monkeypatch, diameter=diameter, mu=zero)

    def actual():
        surrogate_domain.check_surrogate_domain_at_point(
            'Gyroid', 6., .4, 16., speed, 300., allow_extrap=True)
        return captured[0][1]

    _assert_observation(_observe(actual), _observe(
        lambda: float(values['rho']) * speed * diameter / float(values['mu'])))


@pytest.mark.parametrize('property_type', [float, np.float16, np.float32, np.float64])
@pytest.mark.parametrize('cp,conductivity', [(1010.125, .075), (-3.5, .5), (0., .75), (1., 0.)])
def test_preflight_co2_prandtl_keeps_float_boundaries_and_query_order(
        monkeypatch, property_type, cp, conductivity):
    values, calls, captured, _, _ = _inputs(
        monkeypatch, fluid='co2', mu=property_type(.003125),
        cp=property_type(cp), conductivity=property_type(conductivity))

    def actual():
        surrogate_domain.check_surrogate_domain_at_point(
            'Gyroid', 6., .4, 16., 2.125, 300., 12e6,
            fluid='co2', allow_extrap=True)
        return captured[1][1]

    expected = _observe(lambda: float(values['cp']) * float(values['mu']) / float(values['k']))
    _assert_observation(_observe(actual), expected)
    assert calls[:6] == ['rho', 'mu', 'geometry', 'range-Re', 'cp', 'k']
    if expected[0][0] == 'value':
        assert calls[-1] == 'range-Pr'
        assert captured[1][0] == ('nu_pr', 'co2', 'Gyroid')
        assert captured[1][3] == dict(label='CO2 inlet Nu', quantity='Pr', unit='-')
    else:
        assert len(captured) == 1


@pytest.mark.parametrize('failed', ['rho', 'mu', 'geometry', 'cp', 'k'])
def test_preflight_co2_property_failure_precedes_collected_domain_reasons(monkeypatch, failed):
    _, calls, _, _, failure = _inputs(monkeypatch, fluid='co2', fail=failed)
    with pytest.raises(LookupError) as actual:
        surrogate_domain.check_surrogate_domain_at_point(
            'Gyroid', 9., .7, 16., .001, 300., 12e6, fluid='co2')
    assert actual.value is failure
    order = ['rho', 'mu', 'geometry', 'range-Re', 'cp', 'k']
    assert calls == order[:order.index(failed) + 1]
