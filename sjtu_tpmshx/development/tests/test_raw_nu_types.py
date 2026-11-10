"""Raw Nu arithmetic and result types against fixed independent expressions."""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import nu_reference as reference
from sjtu_tpmshx.shared.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.shared.models import co2_correlations, nu_correlations


def observe(function):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all='warn'):
        warnings.simplefilter('always')
        warnings.simplefilter('ignore', UserWarning)
        try:
            value = function()
        except Exception as error:
            result = ('error', type(error), error.args, str(error))
        else:
            result = ('value', type(value), np.asarray(value))
    return result, [(item.category, str(item.message)) for item in caught]


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


@pytest.mark.parametrize('route', ['air', 'vector', 'water', 'sco2', 'selected'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64,
                                  np.int16, np.uint16, np.int32, np.int64])
@pytest.mark.parametrize('layout', ['scalar', 'zero', 'two', 'empty', 'strided'])
def test_raw_nu_types_and_intermediate_rounding(route, topology, dtype, layout):
    base = np.array([0.5, 1., 10., 3000., 5000., 10000.], dtype=dtype)
    re = {'scalar': dtype(3000), 'zero': np.array(3000, dtype=dtype),
          'two': base.reshape(2, 3), 'empty': base[:0], 'strided': base[::-2]}[layout]
    pr_type = dtype if dtype in (float, np.float16, np.float32, np.float64) else np.float32
    pr, cell, diameter = pr_type(1.25), pr_type(7.), pr_type(3.)
    equal(observe(lambda: call(nu_correlations, route, topology, re, pr, cell, diameter)),
          observe(lambda: call(reference, route, topology, re, pr, cell, diameter)))


@pytest.mark.parametrize('route', ['air', 'vector', 'water', 'sco2'])
@pytest.mark.parametrize('inputs', [
    (-300., .72, 7., 3.),
    (-300., np.float16(.72), np.float16(7.), np.float16(3.)),
    (np.float16(-300.), .72, 7., 3.),
    (np.array([-300., 0., np.nan, np.inf], dtype=np.float32), .72, 7., 3.),
    (3000., -.72, 7., 3.),
    (3000., .72, -7., 3.),
    (3000., .72, 0., 3.),
])
def test_raw_nu_keeps_nonfinite_and_scalar_error_contract(route, inputs):
    re, pr, cell, diameter = inputs
    equal(observe(lambda: call(nu_correlations, route, 'Gyroid', re, pr, cell, diameter)),
          observe(lambda: call(reference, route, 'Gyroid', re, pr, cell, diameter)))


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
def test_co2_nu_retains_double_normalization(topology, dtype):
    arguments = (dtype(12000.), dtype(1.4), dtype(7.), dtype(3.))
    equal(observe(lambda: co2_correlations.nusselt(topology, *arguments)),
          observe(lambda: reference.co2_nusselt(topology, *arguments)))


@pytest.mark.parametrize('route', ['air', 'vector', 'water', 'sco2'])
def test_empty_nu_keeps_scalar_factor_complex_type(route):
    arguments = (np.empty(0), -1.25, 7., 3.)
    equal(observe(lambda: call(nu_correlations, route, 'Gyroid', *arguments)),
          observe(lambda: call(reference, route, 'Gyroid', *arguments)))


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
          observe(lambda: reference.nu_vec('Gyroid', re, 7., 3., Re_floor=floor)))


@pytest.mark.parametrize('re,floor', [
    (-0., 0.), (0., -0.),
    (np.array([-0., 0.]), np.array([0., -0.], dtype=np.float32)),
    (np.array([np.nan, -np.inf, np.inf]), np.array([1., 10., np.nan], dtype=np.float16)),
])
def test_re_floor_keeps_maximum_ties_and_nonfinite_values(re, floor):
    from sjtu_tpmshx.shared.models import _native_properties

    expected = np.maximum(np.asarray(re, dtype=np.float64), floor)
    actual, _ = _native_properties.nu_inputs(1, re, re_floor=floor)
    assert type(actual) is type(expected)
    assert np.asarray(actual).dtype == np.asarray(expected).dtype
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(np.signbit(actual), np.signbit(expected))
