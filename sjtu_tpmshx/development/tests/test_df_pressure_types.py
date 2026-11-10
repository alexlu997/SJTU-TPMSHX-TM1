"""Keep the frozen D-F pressure scalar types and NumPy error policy."""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import df_reference as old
from sjtu_tpmshx.shared.df_surrogate import predict


_KINDS = (float,np.float16,np.float32,np.float64)


def _observe(function, args, *, compressible, strict=False, error='warn'):
    if compressible:
        function = getattr(function,'predict_dP_compressible')
    else:
        function = getattr(function,'predict_dP')
    with warnings.catch_warnings(record=True) as notices, np.errstate(all=error):
        warnings.simplefilter('always')
        try:
            result = function('Gyroid',6.25,.425,.35,*args,
                              **({'strict':strict} if compressible else {}))
        except Exception as failure:
            value = ('error',type(failure),failure.args)
        else:
            value = ('result',type(result),result)
    return value,[(type(item.message),str(item.message)) for item in notices]


def _compare(args, *, compressible, strict=False, error='warn'):
    old.reset_choke_warn_registry()
    predict.reset_choke_warn_registry()
    expected = _observe(old,args,compressible=compressible,strict=strict,error=error)
    actual = _observe(predict,args,compressible=compressible,strict=strict,error=error)
    assert actual[0][:2] == expected[0][:2]
    if actual[0][0] == 'error':
        assert actual[0][2] == expected[0][2]
    else:
        np.testing.assert_array_equal(actual[0][2],expected[0][2])
        assert np.asarray(actual[0][2]).dtype == np.asarray(expected[0][2]).dtype
        assert np.asarray(actual[0][2]).shape == np.asarray(expected[0][2]).shape
    assert actual[1] == expected[1]


@pytest.mark.parametrize('kind',_KINDS)
def test_incompressible_homogeneous_scalar_types(kind):
    _compare(tuple(kind(value) for value in (4.71321,1.2501233,1.8e-5,.182)),compressible=False)


@pytest.mark.parametrize('slot',range(4))
@pytest.mark.parametrize('kind',_KINDS[1:])
def test_incompressible_single_strong_scalar(slot,kind):
    values = [4.71321,1.2501233,1.8e-5,.182]
    values[slot] = kind(values[slot])
    _compare(tuple(values),compressible=False)


@pytest.mark.parametrize('left',_KINDS[1:])
@pytest.mark.parametrize('right',_KINDS[1:])
def test_incompressible_mixed_scalar_promotion(left,right):
    _compare((left(4.71321),right(1.2501233),left(1.8e-5),right(.182)),compressible=False)


@pytest.mark.parametrize('kind',_KINDS)
@pytest.mark.parametrize('strict',[False,True])
@pytest.mark.parametrize('case',[
    (4.71321,310.,50000.,1.8e-5,.182),
    (4.71321,1.,120.,1.8e-5,.001),
    (2500.,310.,50000.,1.8e-5,.182),
    (0.,310.,50000.,1.8e-5,.182),
])
def test_compressible_homogeneous_scalar_types(kind,strict,case):
    _compare(tuple(kind(value) for value in case),compressible=True,strict=strict)


@pytest.mark.parametrize('slot',range(5))
@pytest.mark.parametrize('kind',_KINDS[1:])
@pytest.mark.parametrize('strict',[False,True])
def test_compressible_single_strong_scalar(slot,kind,strict):
    values = [4.71321,310.,50000.,1.8e-5,.182]
    values[slot] = kind(values[slot])
    _compare(tuple(values),compressible=True,strict=strict)


@pytest.mark.parametrize('slot',range(5))
@pytest.mark.parametrize('strict',[False,True])
@pytest.mark.parametrize('error',['ignore','raise'])
def test_half_weak_cast_error_policy(slot,strict,error):
    values = [4.71321,310.,50000.,1.8e-5,.182]
    values[slot] = np.float16(values[slot])
    _compare(tuple(values),compressible=True,strict=strict,error=error)


@pytest.mark.parametrize('error',['ignore','warn','raise'])
@pytest.mark.parametrize('kind',_KINDS[1:])
@pytest.mark.parametrize('compressible',[False,True])
def test_scalar_floating_events_keep_numpy_policy(error,kind,compressible):
    values = (2500.,310.,50000.,1.8e-5,.182) if compressible else (2500.,1.2501233,1.8e-5,.182)
    _compare(tuple(kind(value) for value in values),compressible=compressible,error=error)


@pytest.mark.parametrize('error',['ignore','warn','raise'])
@pytest.mark.parametrize('kind',_KINDS[1:])
def test_underflow_and_invalid_events(error,kind):
    for values in ((1e-15,1.25,1.8e-5,.182),(np.inf,0.,1.8e-5,.182),
                   (np.nan,1.25,1.8e-5,.182)):
        # Input conversion is outside the original pressure expression.
        with np.errstate(all='ignore'):
            args = tuple(kind(value) for value in values)
        _compare(args,compressible=False,error=error)


@pytest.mark.parametrize('kind',_KINDS[1:])
def test_zero_dimensional_real_inputs(kind):
    _compare(tuple(np.asarray(value,dtype=kind) for value in (4.71321,1.2501233,1.8e-5,.182)),
             compressible=False)


@pytest.mark.parametrize('kind',_KINDS)
def test_nonpositive_outlet_keeps_original_pressure_object(kind):
    pressure = kind(101.)
    old.reset_choke_warn_registry()
    predict.reset_choke_warn_registry()
    args = ('Gyroid',6.25,.425,.35,2500.,310.,pressure,1.8e-5,.182)
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore')
        assert old.predict_dP_compressible(*args) is pressure
        assert predict.predict_dP_compressible(*args) is pressure


@pytest.mark.parametrize('kind',_KINDS[1:])
@pytest.mark.parametrize('speed',[1e200,1e308])
@pytest.mark.parametrize('compressible',[False,True])
@pytest.mark.parametrize('error',['ignore','warn','raise'])
def test_prior_numpy_event_precedes_later_weak_power_error(kind,speed,compressible,error):
    viscosity = kind(1.8e-5)
    values = (speed,310.,50000.,viscosity,.182) if compressible else (speed,1.2501233,viscosity,.182)
    _compare(values,compressible=compressible,error=error)


def test_fp_raise_does_not_register_pressure_policy_warning():
    pressure = np.float16(101.)
    arguments = ('Gyroid',6.25,.425,.35,100.,310.,pressure,1.8e-5,.182)
    observations = []
    for module in (old,predict):
        module.reset_choke_warn_registry()
        with np.errstate(over='raise',invalid='ignore'):
            with pytest.raises(FloatingPointError) as failure:
                module.predict_dP_compressible(*arguments)
        assert module._CHOKE_WARNED == set()
        with np.errstate(all='ignore'), warnings.catch_warnings(record=True) as notices:
            warnings.simplefilter('always')
            result = module.predict_dP_compressible(*arguments)
        assert result is pressure
        observations.append((failure.value.args,[(type(item.message),str(item.message)) for item in notices]))
    assert observations[0] == observations[1]
