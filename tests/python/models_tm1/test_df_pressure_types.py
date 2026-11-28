"""Check float64 D-F pressure arithmetic and NumPy error policy."""
import warnings

import numpy as np
import pytest

from tests.python import df_reference as old
from tests.python import float64_oracle as oracle
from tm1.physical_models.df_surrogate import predict


# The native boundary converts each operand to float64. Python floats and one
# narrow float cover that conversion. The physical, strict, and error-policy
# matrices run on float64 operands with one narrow-float check.
_KINDS = (float, np.float16)


def _observe(module, args, *, compressible, strict=False, error='warn', is_reference=False):
    function = getattr(module, 'predict_dP_compressible' if compressible else 'predict_dP')
    with warnings.catch_warnings(record=True) as notices, np.errstate(all=error):
        warnings.simplefilter('always')
        try:
            if is_reference:
                result = oracle.call(
                    lambda *values: function('Gyroid', 6.25, .425, .35, *values,
                                             **({'strict': strict} if compressible else {})),
                    *args)
            else:
                result = function('Gyroid', 6.25, .425, .35, *args,
                                  **({'strict': strict} if compressible else {}))
        except Exception as failure:
            error_args = (tuple(oracle.warning_text(item) if isinstance(item, str) else item for item in failure.args)
                          if is_reference else failure.args)
            value = ('error', type(failure), error_args)
        else:
            value = ('result', type(result), result)
    notes = [(type(item.message), str(item.message)) for item in notices]
    if is_reference:
        notes = [(category, oracle.warning_text(text)) for category, text in notes]
    return value, notes


def _compare(args, *, compressible, strict=False, error='warn'):
    old.reset_choke_warn_registry()
    predict.reset_choke_warn_registry()
    expected = _observe(old, args, compressible=compressible, strict=strict, error=error, is_reference=True)
    actual = _observe(predict, args, compressible=compressible, strict=strict, error=error)
    assert actual[0][:2] == expected[0][:2]
    if actual[0][0] == 'error':
        assert actual[0][2] == expected[0][2]
    else:
        np.testing.assert_array_equal(actual[0][2], expected[0][2])
        assert np.asarray(actual[0][2]).dtype == np.asarray(expected[0][2]).dtype
        assert np.asarray(actual[0][2]).shape == np.asarray(expected[0][2]).shape
    assert actual[1] == expected[1]


@pytest.mark.parametrize('kind', _KINDS)
def test_incompressible_homogeneous_scalar_types(kind):
    _compare(tuple(kind(value) for value in (4.71321, 1.2501233, 1.8e-5, .182)), compressible=False)


@pytest.mark.parametrize('slot,kind', [(0, np.float16), (2, np.float32)])
def test_incompressible_single_strong_scalar(slot, kind):
    values = [4.71321, 1.2501233, 1.8e-5, .182]
    values[slot] = kind(values[slot])
    _compare(tuple(values), compressible=False)


@pytest.mark.parametrize('left,right', [(np.float16, np.float32)])
def test_incompressible_mixed_scalar_promotion(left, right):
    _compare((left(4.71321), right(1.2501233), left(1.8e-5), right(.182)), compressible=False)


_COMPRESSIBLE_CASES = (
    (4.71321, 310., 50000., 1.8e-5, .182),
    (4.71321, 1., 120., 1.8e-5, .001),
    (2500., 310., 50000., 1.8e-5, .182),
    (0., 310., 50000., 1.8e-5, .182),
)


@pytest.mark.parametrize('kind,strict,case', [
    *[(float, strict, case) for strict in (False, True) for case in _COMPRESSIBLE_CASES],
    *[(np.float16, strict, _COMPRESSIBLE_CASES[2]) for strict in (False, True)],
])
def test_compressible_homogeneous_scalar_types(kind, strict, case):
    _compare(tuple(kind(value) for value in case), compressible=True, strict=strict)


@pytest.mark.parametrize('slot,kind,strict', [(1, np.float16, False), (4, np.float32, True)])
def test_compressible_single_strong_scalar(slot, kind, strict):
    values = [4.71321, 310., 50000., 1.8e-5, .182]
    values[slot] = kind(values[slot])
    _compare(tuple(values), compressible=True, strict=strict)


@pytest.mark.parametrize('error,kind,compressible', [
    *[(error, np.float64, compressible) for error in ('ignore', 'warn', 'raise')
      for compressible in (False, True)],
    ('raise', np.float16, True),
])
def test_scalar_floating_events_keep_numpy_policy(error, kind, compressible):
    values = (2500., 310., 50000., 1.8e-5, .182) if compressible else (2500., 1.2501233, 1.8e-5, .182)
    _compare(tuple(kind(value) for value in values), compressible=compressible, error=error)


@pytest.mark.parametrize('error,kind', [
    ('ignore', np.float64), ('warn', np.float64), ('raise', np.float64), ('warn', np.float16)])
def test_underflow_and_invalid_events(error, kind):
    for values in ((1e-15, 1.25, 1.8e-5, .182), (np.inf, 0., 1.8e-5, .182),
                   (np.nan, 1.25, 1.8e-5, .182)):
        with np.errstate(all='ignore'):
            args = tuple(kind(value) for value in values)
        _compare(args, compressible=False, error=error)


@pytest.mark.parametrize('kind', [np.float16, np.float64])
def test_zero_dimensional_real_inputs(kind):
    _compare(tuple(np.asarray(value, dtype=kind) for value in (4.71321, 1.2501233, 1.8e-5, .182)),
             compressible=False)


@pytest.mark.parametrize('kind', _KINDS)
def test_nonpositive_outlet_returns_float64_inlet_pressure(kind):
    pressure = kind(101.)
    old.reset_choke_warn_registry()
    predict.reset_choke_warn_registry()
    args = ('Gyroid', 6.25, .425, .35, 2500., 310., pressure, 1.8e-5, .182)
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore')
        actual = predict.predict_dP_compressible(*args)
    assert type(actual) is float and actual == float(pressure)


def test_fp_raise_does_not_register_pressure_policy_warning():
    pressure = 101.
    arguments = ('Gyroid', 6.25, .425, .35, 1e200, 310., pressure, 1.8e-5, .182)
    predict.reset_choke_warn_registry()
    with np.errstate(over='raise', invalid='ignore'):
        with pytest.raises(FloatingPointError):
            predict.predict_dP_compressible(*arguments)
    assert predict._CHOKE_WARNED == set()
    with np.errstate(all='ignore'), warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always')
        result = predict.predict_dP_compressible(*arguments)
    assert result == pressure and notices
