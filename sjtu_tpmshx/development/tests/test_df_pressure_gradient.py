"""Compare the native gradient with the frozen tpms_calc expression."""
import ctypes as ct
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests.df_reference import pressure_gradient as reference
from sjtu_tpmshx.shared.models import _native_df as native


_BASE = (1.2501233,1.8e-5,4.71321,4.8841442670242926e-8,239.78171583799818)


def _observe(function,values,policy):
    with warnings.catch_warnings(record=True) as notices, np.errstate(all=policy):
        warnings.simplefilter('always')
        try:
            result = function(*values)
        except Exception as failure:
            observation = ('error',type(failure),failure.args)
        else:
            observation = ('result',type(result),result)
    return observation,[(type(item.message),str(item.message)) for item in notices]


def _compare(values,policy='warn'):
    expected, actual = _observe(reference,values,policy), _observe(native.pressure_gradient,values,policy)
    assert actual[0][:2] == expected[0][:2]
    if actual[0][0] == 'error':
        assert actual[0][2] == expected[0][2]
    else:
        np.testing.assert_array_equal(actual[0][2],expected[0][2])
        assert np.asarray(actual[0][2]).dtype == np.asarray(expected[0][2]).dtype
        assert np.asarray(actual[0][2]).shape == np.asarray(expected[0][2]).shape
    assert actual[1] == expected[1]
    return actual[0][2]


@pytest.mark.parametrize('kind',[float,np.float16,np.float32,np.float64])
@pytest.mark.parametrize('sign',[-1.,0.,1.])
def test_homogeneous_scalar_types_and_signed_speed(kind,sign):
    values = list(_BASE)
    values[2] *= sign
    _compare(tuple(kind(value) for value in values))


@pytest.mark.parametrize('slot',range(5))
@pytest.mark.parametrize('kind',[np.float16,np.float32,np.float64])
def test_single_strong_operand(slot,kind):
    values = list(_BASE)
    values[slot] = kind(values[slot])
    _compare(values)


@pytest.mark.parametrize('dtype',[np.float16,np.float32,np.float64])
@pytest.mark.parametrize('layout',['scalar-array','broadcast','strided','empty','big-endian'])
def test_real_array_shape_dtype_and_ownership(dtype,layout):
    values = [np.asarray(value,dtype=dtype) for value in _BASE]
    if layout == 'broadcast':
        values[2] = np.asarray([[-4.75],[0.],[4.75]],dtype=dtype)
        values[4] = np.asarray([[125.,250.]],dtype=dtype)
    elif layout == 'strided':
        values[2] = np.asarray([-4.75,-2.,0.,2.,4.75,6.],dtype=dtype)[::-2]
    elif layout == 'empty':
        values[4] = np.empty((0,2),dtype=dtype)
    elif layout == 'big-endian':
        values[2] = np.asarray([-4.75,0.,4.75],dtype=dtype).astype(np.dtype(dtype).newbyteorder('>'))
    for value in values:
        value.flags.writeable = False
    before = [value.copy() for value in values]
    result = _compare(values)
    if isinstance(result,np.ndarray):
        assert result.flags.writeable
        assert not any(np.shares_memory(result,value) for value in values)
    for value, original in zip(values,before): np.testing.assert_array_equal(value,original)


@pytest.mark.parametrize('policy',['ignore','warn','raise'])
@pytest.mark.parametrize('values',[
    (1.2,1.8e-5,1e200,1e-8,200.),
    (1.2,np.float16(1.8e-5),1e308,1e-8,200.),
    (np.float16(1.2),1.8e-5,1.,1e-8,1e308),
    (1.2,1.8e-5,1.,0.,200.),
    (1.2,1.8e-5,1.,np.float16(0.),200.),
    (1.2,1.8e-5,np.inf,1e-8,0.),
    (1.2,1.8e-5,np.nan,1e-8,200.),
    (1.2,1.8e-5,-4.75,-1e-8,-200.),
    (np.empty((0,2)),np.float16(1.8e-5),1e308,1e-8,200.),
    (np.empty((0,2)),1.8e-5,1.,0.,200.),
])
def test_original_fp_and_failure_priority(values,policy):
    _compare(values,policy)


def test_gradient_does_not_replace_left_multiplication_with_power():
    # Python float multiplication overflows to Inf; **2 raises OverflowError.
    result = _compare((1.2,1.8e-5,1e200,1e-8,200.),'raise')
    assert type(result) is float and np.isinf(result)


def _raw_gradient(values):
    properties = native._properties
    shape, buffers, inputs = properties._inputs(values)
    output, failure = properties._Result(buffers[0].size), native._FPFailure()
    output.real.fill(-12345.); output.imaginary.fill(-67890.); output.events.fill(0x5a5a5a5a)
    ct.memset(ct.byref(output.kind),0x6b,ct.sizeof(output.kind)); output.category.value = 0x7c7c7c7c
    before = (output.real.copy(),output.imaginary.copy(),output.events.copy(),bytes(output.kind),output.category.value)
    owner = ct.CDLL(native._native_preparation._library().path)
    function = owner.tpmshx_preparation_df_pressure_gradient_v1
    function.argtypes = [*native._SIGNATURES['pressure_gradient'],*native._ERROR]
    function.restype = ct.c_int
    return owner,function,shape,buffers,inputs,output,failure,before


def _unchanged(output,before):
    for value, original in zip((output.real,output.imaginary,output.events),before[:3]):
        np.testing.assert_array_equal(value,original)
    assert bytes(output.kind) == before[3] and output.category.value == before[4]


def test_raw_gradient_zero_division_diagnostic_keeps_all_numeric_outputs():
    owner,function,_shape,buffers,inputs,output,failure,before = _raw_gradient((1.2,1.8e-5,1.,0.,200.))
    error = ct.create_string_buffer(256)
    status = function(*inputs,output.output,ct.byref(failure),error,len(error))
    assert owner is not None and buffers and status == 3 and failure.python_cause == 1 and error.value
    _unchanged(output,before)


def test_raw_gradient_event_extent_rejection_is_atomic():
    owner,function,_shape,buffers,inputs,output,failure,before = _raw_gradient(_BASE)
    output.output.event_count = native._FP_EVENT_COUNT-1
    error = ct.create_string_buffer(256)
    status = function(*inputs,output.output,ct.byref(failure),error,len(error))
    assert owner is not None and buffers and status == 1
    _unchanged(output,before)


def test_raw_gradient_error_storage_cannot_alias_an_input():
    owner,function,_shape,buffers,inputs,output,failure,before = _raw_gradient(_BASE)
    input_before = buffers[0].copy()
    error = ct.cast(buffers[0].ctypes.data,ct.POINTER(ct.c_char))
    status = function(*inputs,output.output,ct.byref(failure),error,buffers[0].nbytes)
    assert owner is not None and status == 1
    _unchanged(output,before)
    np.testing.assert_array_equal(buffers[0],input_before)
