"""Raw float64 Nu arithmetic against fixed independent expressions."""
import warnings

import numpy as np
import pytest

from tests.python import float64_oracle as oracle
from tests.python import nu_reference as reference
from tm1.data_types.compute_config import Sco2NuConfig
from tm1.physical_models import co2_correlations, nu_correlations


def observe(function, *, reference=False):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all='warn'):
        warnings.simplefilter('always')
        warnings.simplefilter('ignore', UserWarning)
        try:
            value = function()
        except Exception as error:
            result = ('error', type(error), error.args, str(error))
        else:
            result = ('value', type(value), np.asarray(value))
    notes = [(item.category, str(item.message)) for item in caught]
    if reference:
        notes = [(category, oracle.warning_text(text)) for category, text in notes]
    return result, notes


def equal(actual, expected):
    first, notes = actual
    second, expected_notes = expected
    assert notes == expected_notes
    assert first[:2] == second[:2]
    if first[0] == 'error':
        assert first[2:] == second[2:]
    else:
        assert first[2].dtype == second[2].dtype
        assert first[2].shape == second[2].shape
        np.testing.assert_array_equal(first[2], second[2])


def expected(route, topology, *arguments):
    return oracle.call(lambda *values: call(reference, route, topology, *values), *arguments)


def call(module, route, topology, re, pr, cell, diameter):
    if route == 'air':
        return module.nu_from_Re(topology, re, None, cell, diameter, Pr=pr)
    if route == 'vector':
        return module.nu_vec(topology, re, cell, diameter, Pr=pr)
    if route == 'water':
        return module.nu_water_topo(topology, re, pr)
    if route == 'sco2':
        return module.nu_sco2_topo(topology, re, pr, cell, diameter)
    settings = Sco2NuConfig(mode='experimental', alpha_D=np.float32(1.1), alpha_G=np.float16(1.2),
                           parameter_version='reference', source='reference', applicability='reference')
    return module.nu_sco2_selected(topology, re, pr, cell, diameter, settings=settings)


_LAYOUTS = ('scalar', 'zero', 'two', 'empty', 'strided')
_ROUTES = ('air', 'vector', 'water', 'sco2', 'selected')


# The native boundary converts every operand to float64. Narrow, integer, and
# Python operands cover that conversion on one route. Every route and topology
# then runs on float64 operands.
@pytest.mark.parametrize('route,topology,dtype,layout', [
    *[('air', 'Gyroid', dtype, layout) for dtype in (float, np.float16, np.int32) for layout in _LAYOUTS],
    *[(route, topology, np.float64, 'two') for route in _ROUTES for topology in ('Diamond', 'Gyroid')],
])
def test_raw_nu_uses_float64_operands(route, topology, dtype, layout):
    base = np.array([0.5, 1., 10., 3000., 5000., 10000.], dtype=dtype)
    re = {'scalar': dtype(3000), 'zero': np.array(3000, dtype=dtype),
          'two': base.reshape(2, 3), 'empty': base[:0], 'strided': base[::-2]}[layout]
    pr_type = dtype if dtype in (float, np.float16, np.float32, np.float64) else np.float32
    pr, cell, diameter = pr_type(1.25), pr_type(7.), pr_type(3.)
    equal(observe(lambda: call(nu_correlations, route, topology, re, pr, cell, diameter)),
          observe(reference=True, function=lambda: expected(route, topology, re, pr, cell, diameter)))


_DOMAIN_FAILURES = (
    (-300., .72, 7., 3.),
    (np.array([-300., 0., np.nan, np.inf]), .72, 7., 3.),
    (3000., -.72, 7., 3.),
    (3000., .72, -7., 3.),
    (3000., .72, 0., 3.),
)


@pytest.mark.parametrize('route,inputs', [
    *[(route, inputs) for route in ('air', 'vector', 'water', 'sco2') for inputs in _DOMAIN_FAILURES],
    ('air', (-300., np.float16(.72), np.float16(7.), np.float16(3.))),
    ('air', (np.float16(-300.), .72, 7., 3.)),
    ('air', (np.array([-300., 0., np.nan, np.inf], dtype=np.float32), .72, 7., 3.)),
])
def test_raw_nu_keeps_nonfinite_float64_results(route, inputs):
    re, pr, cell, diameter = inputs
    equal(observe(lambda: call(nu_correlations, route, 'Gyroid', re, pr, cell, diameter)),
          observe(reference=True, function=lambda: expected(route, 'Gyroid', re, pr, cell, diameter)))


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('dtype', [float, np.float16])
def test_co2_nu_retains_double_normalization(topology, dtype):
    arguments = (dtype(12000.), dtype(1.4), dtype(7.), dtype(3.))
    equal(observe(lambda: co2_correlations.nusselt(topology, *arguments)),
          observe(reference=True, function=lambda: oracle.call(lambda *values: reference.co2_nusselt(topology, *values), *arguments)))


@pytest.mark.parametrize('route', ['air', 'vector', 'water', 'sco2'])
def test_empty_nu_returns_empty_float64(route):
    actual = call(nu_correlations, route, 'Gyroid', np.empty(0), -1.25, 7., 3.)
    assert isinstance(actual, np.ndarray) and actual.dtype == np.float64 and actual.shape == (0,)


@pytest.mark.parametrize('re,floor', [
    (3000., np.array([10., 5000.], dtype=np.float16)),
    (np.array([[0.], [3000.]]), np.array([[10., 20., 4000.]], dtype=np.float32)),
    (np.array([0., 20., 100.]), np.array([10., np.nan, np.inf])),
    (np.array([0., 20., 100.]), np.array([10., 1., 30., 2., 200., 3.], dtype=np.float32)[::2]),
    (np.empty((2, 0)), np.empty((1, 0), dtype=np.float16)),
    (np.array(3.), np.array(10., dtype=np.float16)),
    (np.array([1., -1.]), np.array([-2., -2.], dtype=np.float32)),
    (np.array([1., 2.]), np.array([10., 20., 30.])),
    ([1., 2.], [10., 20.]),
])
def test_vector_nu_keeps_array_re_floor_contract(re, floor):
    equal(observe(lambda: nu_correlations.nu_vec('Gyroid', re, 7., 3., Re_floor=floor)),
          observe(reference=True, function=lambda: oracle.call(lambda *values, **named: reference.nu_vec('Gyroid', *values, **named),
                                      re, 7., 3., Re_floor=floor)))


@pytest.mark.parametrize('re,floor', [
    (-0., 0.), (0., -0.),
    (np.array([-0., 0.]), np.array([0., -0.], dtype=np.float32)),
    (np.array([np.nan, -np.inf, np.inf]), np.array([1., 10., np.nan], dtype=np.float16)),
])
def test_re_floor_keeps_maximum_ties_and_nonfinite_values(re, floor):
    from tm1.cpp_interface import _native_properties

    expected = oracle.result(np.maximum(np.asarray(re, dtype=np.float64), np.asarray(floor, dtype=np.float64)))
    actual, _ = _native_properties.nu_inputs(1, re, re_floor=floor)
    assert type(actual) is type(expected)
    assert np.asarray(actual).dtype == np.asarray(expected).dtype
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(np.signbit(actual), np.signbit(expected))
