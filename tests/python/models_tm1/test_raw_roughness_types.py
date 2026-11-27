"""Float64 roughness arithmetic against fixed independent expressions."""
import warnings

import numpy as np
import pytest

from tests.python import float64_oracle as oracle
from tests.python import nu_reference as reference
from sjtu_tpmshx.physical_models import roughness


def observe(function, *, reference=False):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all='warn'):
        warnings.simplefilter('always')
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


# The native boundary converts each operand to float64. Python, narrow, and
# integer operands cover that conversion on one law in each layout. Every law
# then runs on a float64 array.
@pytest.mark.parametrize('dtype,layout,law', [
    *[(dtype, layout, 'f_haaland') for dtype in (float, np.float16, np.int32)
      for layout in ('scalar', 'zero', 'two', 'empty', 'strided')],
    *[(np.float64, 'two', law) for law in ('f_petukhov', 'f_haaland')],
])
def test_raw_friction_uses_float64_operands(dtype, layout, law):
    base = np.array([3000, 4000, 5000, 6000, 7000, 8000], dtype=dtype)
    re = {'scalar': dtype(3000), 'zero': np.array(3000, dtype=dtype),
          'two': base.reshape(2, 3), 'empty': base[:0], 'strided': base[::-2]}[layout]
    ratio_type = dtype if dtype in (float, np.float16, np.float32, np.float64) else np.float32
    args = (re,) if law == 'f_petukhov' else (re, ratio_type(.0125))
    equal(observe(lambda: getattr(roughness, law)(*args)),
          observe(lambda: oracle.call(getattr(reference, law), *args), reference=True))


@pytest.mark.parametrize('function,dtype,layout', [
    *[('f_enhancement', dtype, layout) for dtype in (float, np.float16, np.int32)
      for layout in ('scalar', 'zero', 'one', 'two', 'empty')],
    *[(function, np.float64, 'two') for function in ('f_enhancement', 'nu_extra_factor')],
])
def test_roughness_factors_use_float64_height_order(function, dtype, layout):
    value = dtype(3000)
    re = {'scalar': value, 'zero': np.array(value), 'one': np.array([value]),
          'two': np.array([value, value]), 'empty': np.array([], dtype=dtype)}[layout]
    eps_type = dtype if dtype in (float, np.float16, np.float32, np.float64) else np.float32
    kwargs = dict(mode='bhatti_shah_1b', eps_um=eps_type(100), D_h_mm=eps_type(3))
    equal(observe(lambda: getattr(roughness, function)(re, **kwargs)),
          observe(lambda: oracle.call(getattr(reference, function), re, **kwargs), reference=True))


@pytest.mark.parametrize('law', ['f_petukhov', 'f_haaland'])
@pytest.mark.parametrize('re,ratio', [
    (0., .01), (-1., .01), (np.nan, .01), (np.inf, .01),
    (3000., -.01),
    (np.array([0., -1., np.nan, np.inf]), .01),
    (np.empty(0), -.01), (np.empty(0), np.float16(.01)),
])
def test_raw_friction_nonfinite_and_real_domain_results(law, re, ratio):
    args = (re,) if law == 'f_petukhov' else (re, ratio)
    expected = observe(lambda: oracle.call(getattr(reference, law), *args), reference=True)
    if np.size(re) == 0:
        # The native core evaluates no element of an empty input, so it records no event.
        expected = expected[0], []
    equal(observe(lambda: getattr(roughness, law)(*args)), expected)


@pytest.mark.parametrize('function', ['f_enhancement', 'nu_extra_factor'])
@pytest.mark.parametrize('mode', ['baseline', 'norris_1a', 'bhatti_shah_1b', 'unknown'])
@pytest.mark.parametrize('arguments', [
    (object(), None, None), (3000., None, 3.),
    (3000., 100., 0.),
    (3000., -100., 3.),
])
def test_roughness_mode_and_failure_priority(function, mode, arguments):
    re, eps, diameter = arguments
    equal(observe(lambda: getattr(roughness, function)(re, mode, eps, diameter)),
          observe(lambda: oracle.call(getattr(reference, function), re, mode, eps, diameter),
                  reference=True))
