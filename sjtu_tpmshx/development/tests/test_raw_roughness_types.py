"""Roughness arithmetic against fixed independent expressions."""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import nu_reference as reference
from sjtu_tpmshx.shared.models import roughness


def observe(function):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all='warn'):
        warnings.simplefilter('always')
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


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64,
                                  np.int16, np.uint16, np.int32, np.int64])
@pytest.mark.parametrize('layout', ['scalar', 'zero', 'two', 'empty', 'strided'])
@pytest.mark.parametrize('law', ['f_petukhov', 'f_haaland'])
def test_raw_friction_types(dtype, layout, law):
    base = np.array([3000, 4000, 5000, 6000, 7000, 8000], dtype=dtype)
    re = {'scalar': dtype(3000), 'zero': np.array(3000, dtype=dtype),
          'two': base.reshape(2, 3), 'empty': base[:0], 'strided': base[::-2]}[layout]
    ratio_type = dtype if dtype in (float, np.float16, np.float32, np.float64) else np.float32
    args = (re,) if law == 'f_petukhov' else (re, ratio_type(.0125))
    equal(observe(lambda: getattr(roughness, law)(*args)),
          observe(lambda: getattr(reference, law)(*args)))


@pytest.mark.parametrize('function', ['f_enhancement', 'nu_extra_factor'])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64,
                                  np.int16, np.uint16, np.int32, np.int64])
@pytest.mark.parametrize('layout', ['scalar', 'zero', 'one', 'two', 'empty'])
def test_roughness_factors_keep_typed_height_order(function, dtype, layout):
    value = dtype(3000)
    re = {'scalar': value, 'zero': np.array(value), 'one': np.array([value]),
          'two': np.array([value, value]), 'empty': np.array([], dtype=dtype)}[layout]
    eps_type = dtype if dtype in (float, np.float16, np.float32, np.float64) else np.float32
    kwargs = dict(mode='bhatti_shah_1b', eps_um=eps_type(100), D_h_mm=eps_type(3))
    equal(observe(lambda: getattr(roughness, function)(re, **kwargs)),
          observe(lambda: getattr(reference, function)(re, **kwargs)))


@pytest.mark.parametrize('law', ['f_petukhov', 'f_haaland'])
@pytest.mark.parametrize('re,ratio', [
    (0., .01), (-1., .01), (np.nan, .01), (np.inf, .01),
    (3000., -.01), (3000., np.float32(-.01)),
    (np.array([0., -1., np.nan, np.inf]), .01),
    (np.empty(0), -.01), (np.empty(0), np.float16(.01)),
])
def test_raw_friction_nonfinite_and_complex_results(law, re, ratio):
    args = (re,) if law == 'f_petukhov' else (re, ratio)
    equal(observe(lambda: getattr(roughness, law)(*args)),
          observe(lambda: getattr(reference, law)(*args)))


@pytest.mark.parametrize('function', ['f_enhancement', 'nu_extra_factor'])
@pytest.mark.parametrize('mode', ['baseline', 'norris_1a', 'bhatti_shah_1b', 'unknown'])
@pytest.mark.parametrize('arguments', [
    (object(), None, None), (3000., None, 3.),
    (3000., 100., 0.), (3000., np.float16(100.), np.float16(0.)),
    (3000., -100., 3.),
])
def test_roughness_mode_and_failure_priority(function, mode, arguments):
    re, eps, diameter = arguments
    equal(observe(lambda: getattr(roughness, function)(re, mode, eps, diameter)),
          observe(lambda: getattr(reference, function)(re, mode, eps, diameter)))
