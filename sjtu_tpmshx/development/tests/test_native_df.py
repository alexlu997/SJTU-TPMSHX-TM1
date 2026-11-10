"""Check the preparation D-F core against frozen Python calculations."""
import ctypes as ct
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import df_reference as old
from sjtu_tpmshx.shared.df_surrogate import experimental_correction as correction
from sjtu_tpmshx.shared.df_surrogate import predict
from sjtu_tpmshx.shared.models import _native_df as native
from sjtu_tpmshx.shared.models import _native_preparation


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('compressible', [False, True])
@pytest.mark.parametrize('strict', [False, True])
def test_pressure_matches_frozen_formula(topology, compressible, strict):
    old.reset_choke_warn_registry()
    predict.reset_choke_warn_registry()
    cases = [(6.25, .425, 4.75, 310., 101325., 1.8e-5, .182),
             (7., .6, 2500., 310., 101325., 1.8e-5, .182),
             (4., .3, 0., 290., 101325., 1.7e-5, .042)]
    for length, wall, velocity, temperature, pressure, viscosity, channel in cases:
        with warnings.catch_warnings(record=True) as expected_warnings:
            warnings.simplefilter('always')
            if compressible:
                expected = old.predict_dP_compressible(topology,length,wall,.35,velocity,
                    temperature,pressure,viscosity,channel,strict=strict)
            else:
                expected = old.predict_dP(topology,length,wall,.35,velocity,1.2,viscosity,channel)
        with warnings.catch_warnings(record=True) as actual_warnings:
            warnings.simplefilter('always')
            if compressible:
                actual = predict.predict_dP_compressible(topology,length,wall,.35,velocity,
                    temperature,pressure,viscosity,channel,strict=strict)
            else:
                actual = predict.predict_dP(topology,length,wall,.35,velocity,1.2,viscosity,channel)
        np.testing.assert_array_equal(actual, expected)
        assert [str(x.message) for x in actual_warnings] == [str(x.message) for x in expected_warnings]


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('fluid,velocity,transfer', [
    ('air', 10., False), ('water', .15, False), ('sco2', 1., False),
    ('air', 30., True), ('water', .3, True),
])
def test_hx_factors_and_metadata(topology, fluid, velocity, transfer, monkeypatch):
    if transfer and topology != 'Gyroid':
        return
    expected_records, actual_records = [], []
    monkeypatch.setattr(old, 'record_range', lambda *a, **kw: expected_records.append((a, kw)))
    monkeypatch.setattr(correction, 'record_range', lambda *a, **kw: actual_records.append((a, kw)))
    base_k, base_f = np.array([[1e-8], [2e-8]]), np.array([100., 200., 300.])
    arguments = (topology, fluid, 7., .6, base_k, base_f, np.array([velocity]))
    expected = old.apply_correction(*arguments, allow_hx_extrapolation=transfer)
    actual = correction.apply_correction(*arguments, allow_hx_extrapolation=transfer)
    for result, reference in zip(actual[:2], expected[:2]):
        np.testing.assert_array_equal(result, reference)
        assert result.shape == reference.shape
        assert result.dtype == reference.dtype
        assert result.flags.writeable
    assert actual[2] == expected[2]
    assert len(actual_records) == len(expected_records) == 1
    a, e = actual_records[0], expected_records[0]
    assert a[0][0] == e[0][0] and a[0][2] == e[0][2] and a[1] == e[1]
    np.testing.assert_array_equal(a[0][1], e[0][1])


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_air_specimen_interpolation_and_separate_broadcast(topology):
    lengths = np.array([[6.], [6.125], [7.25], [8.]])
    walls = np.array([.3, .325, .4, .475, .5])
    # Specimen selection ignores u before it can cause a conversion error.
    expected = old.apply_correction(topology, 'air', lengths, walls, 1e-8, 100., object())
    actual = correction.apply_correction(topology, 'air', lengths, walls, 1e-8, 100., object())
    for result, reference in zip(actual[:2], expected[:2]):
        np.testing.assert_array_equal(result, reference)
    assert actual[2] == expected[2]
    np.testing.assert_array_equal(lengths, [[6.], [6.125], [7.25], [8.]])


@pytest.mark.parametrize('topology,fluid,length,wall,velocity,transfer', [
    ('Diamond','air',7.,.6,None,False),
    ('Gyroid','water',6.,.4,None,False),
    ('Gyroid','water',7.,.6,-.1,False),
    ('Gyroid','water',7.,.6,np.nan,False),
    ('Gyroid','air',7.,.6,1.,False),
    ('Diamond','air',6.,.6,10.,False),
    ('Gyroid','air',5.,.4,None,False),
    ('Diamond','air',object(),.4,None,True),
    ('Gyroid','other',object(),.4,None,False),
])
def test_correction_errors_match_frozen_order(topology,fluid,length,wall,velocity,transfer):
    arguments = (topology,fluid,length,wall,velocity)
    with pytest.raises(Exception) as expected:
        old.correction_scale(*arguments,allow_hx_extrapolation=transfer)
    with pytest.raises(type(expected.value)) as actual:
        correction.correction_scale(*arguments,allow_hx_extrapolation=transfer)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize('factor', [0., -1., np.inf, np.nan, np.array(1.)])
def test_prepared_factor_rejection_precedes_empty_fields(factor):
    metadata = {'scale_K': factor, 'scale_F': 2.}
    with pytest.raises(ValueError) as expected:
        old.apply_prepared_correction([],[],metadata)
    with pytest.raises(ValueError) as actual:
        correction.apply_prepared_correction([],[],metadata)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize('dtype', [np.float16,np.float32,np.float64])
@pytest.mark.parametrize('direction', [0,1,2,3])
@pytest.mark.parametrize('weighted', [False,True])
def test_projection_rows_use_frozen_array_order(dtype,direction,weighted,monkeypatch):
    length = np.asarray([[6.,6.25,6.5],[6.5,6.75,7.],[7.,7.25,7.5],[7.5,7.75,8.]],dtype=dtype)
    wall = np.asarray([[.3,.35,.4],[.325,.375,.425],[.35,.4,.45],[.375,.425,.475]],dtype=dtype)
    source = (np.asarray([.125,.25,.375,.5],dtype=dtype),np.asarray([.25,.5,.75],dtype=dtype)) if weighted else None
    target = np.asarray([.125,.25,.375,.5,.625])
    # This reference observes projection rows; epsilon has no fixed-DF effect.
    monkeypatch.setattr(old,'predict_K_cF_vec',lambda _tp,L,t,_eps,**_kw:(L,t))
    expected = old.project_fields_to_streamwise_K_cF(length,wall,'Gyroid',16.,5,direction,target,source_grid=source)
    actual = native.project_rows(length,wall,5,direction,target,source)
    for result, reference in zip(actual[:2],expected):
        np.testing.assert_array_equal(result,reference)
        assert result.dtype == np.float64 and result.flags.writeable
        assert not np.shares_memory(result,length) and not np.shares_memory(result,wall)


def test_row_seed_means_preserve_strided_axis_order():
    rng = np.random.default_rng(61024)
    k, f = rng.uniform(1e-10,1e-7,(137,11)), rng.uniform(1.,1e4,(137,11))
    actual = native.row_means(k,f)
    for result, reference in zip(actual,(k.mean(axis=0),f.mean(axis=0))):
        np.testing.assert_array_equal(result,reference)


def _layout_fields(layout, dtype):
    rng = np.random.default_rng(61024)
    length = rng.uniform(6., 8., (137, 11)).astype(dtype)
    wall = rng.uniform(.3, .5, (137, 11)).astype(dtype)
    if layout == 'F':
        return np.asfortranarray(length), np.asfortranarray(wall)
    if layout == 'T':
        return length.T, wall.T
    if layout == 'negative':
        return length[::-1, ::-1], wall[::-1, ::-1]
    if layout == 'negative-F':
        return length[::-1, ::-1].T, wall[::-1, ::-1].T
    if layout == 'step':
        return length[::2, ::2], wall[::2, ::2]
    if layout == 'mixed':
        return np.asfortranarray(length), wall
    if layout == 'single-column':
        return length[:, :1], wall[:, :1]
    if layout == 'single-row':
        return length[:, :1].T, wall[:, :1].T
    if layout == 'zero0':
        return (np.broadcast_to(value[:1], value.shape) for value in (length, wall))
    if layout == 'zero1':
        return (np.broadcast_to(value[:, :1], value.shape) for value in (length, wall))
    return length, wall


@pytest.mark.parametrize('layout', ['C', 'F', 'T', 'negative', 'negative-F', 'step', 'mixed',
                                   'zero0', 'zero1', 'single-column', 'single-row'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
@pytest.mark.parametrize('weighted', [False, True])
def test_projection_preserves_input_layout(layout, dtype, direction, weighted, monkeypatch):
    length, wall = _layout_fields(layout, dtype)
    rng = np.random.default_rng(41024)
    source = tuple(rng.uniform(.01, .03, n).astype(dtype) for n in length.shape) if weighted else None
    monkeypatch.setattr(old, 'predict_K_cF_vec', lambda _tp, L, t, _eps, **_kw: (L, t))
    expected = old.project_fields_to_streamwise_K_cF(length, wall, 'Gyroid', 16., 17, direction, source_grid=source)
    actual = native.project_rows(length, wall, 17, direction, source_grid=source)
    for result, reference in zip(actual[:2], expected):
        np.testing.assert_array_equal(result, reference)


@pytest.mark.parametrize('layout', ['C', 'F', 'T', 'negative', 'negative-F', 'step', 'mixed',
                                   'zero0', 'zero1', 'single-column', 'single-row'])
def test_row_means_preserve_input_layout(layout):
    k, f = _layout_fields(layout, np.float64)
    for result, reference in zip(native.row_means(k, f), (k.mean(axis=0), f.mean(axis=0))):
        np.testing.assert_array_equal(result, reference)


@pytest.mark.parametrize('api', ['project_rows', 'row_means'])
@pytest.mark.parametrize('operand', [0, 1])
def test_raw_reduction_layout_flags_are_checked_before_output(api, operand):
    owner = ct.CDLL(_native_preparation._library().path)
    function = getattr(owner, f'tpmshx_preparation_df_{api}_v1')
    function.argtypes = [*native._SIGNATURES[api], *native._ERROR]
    function.restype = ct.c_int
    field = np.full((3, 2), 6.)
    first, second, indices = np.full(2, -123.), np.full(2, -456.), np.full(2, -789, dtype=np.int64)
    flags = [0, 0]
    flags[operand] = 2
    error = ct.create_string_buffer(256)
    arguments = [3, 2, native._ptr(field), native._ptr(field), field.size]
    if api == 'project_rows':
        arguments.extend([64, 64, *flags, 2, 2, None, 0, 64, None, 0, 64, None, 0,
                          native._ptr(first), 2, native._ptr(second), 2,
                          indices.ctypes.data_as(native._IP), 2])
    else:
        arguments.extend([*flags, native._ptr(first), 2, native._ptr(second), 2])
    assert function(*arguments, error, len(error)) == 1
    np.testing.assert_array_equal(first, [-123., -123.])
    np.testing.assert_array_equal(second, [-456., -456.])
    np.testing.assert_array_equal(indices, [-789, -789])
    assert b'flag must be zero or one' in error.value


def _raw_fixed():
    library = ct.CDLL(_native_preparation._library().path)
    function = library.tpmshx_preparation_df_fixed_v1
    function.argtypes = [*native._SIGNATURES['fixed'], *native._ERROR]
    function.restype = ct.c_int
    return library, function


@pytest.mark.parametrize('failure', ['extent','null','misaligned','overlap','error-overlap','outside','overflow'])
def test_raw_fixed_rejects_without_partial_output(failure):
    owner, function = _raw_fixed()
    lengths, walls = np.array([6.,6.5]), np.array([.4,.45])
    k, f = np.full(2,-12345.), np.full(2,-67890.)
    error = ct.create_string_buffer(256)
    lp, tp, kp, fp = map(native._ptr,(lengths,walls,k,f))
    count, k_count, error_ptr = 2, 2, error
    if failure == 'extent': k_count = 1
    elif failure == 'null': lp = None
    elif failure == 'misaligned': lp = ct.cast(lengths.ctypes.data+1,native._DP)
    elif failure == 'overlap': kp = lp
    elif failure == 'error-overlap': error_ptr = ct.cast(kp,ct.POINTER(ct.c_char))
    elif failure == 'outside': lengths[1] = 9.
    elif failure == 'overflow': count = ct.c_size_t(-1).value
    status = function(1,lp,tp,count,kp,k_count,fp,2,error_ptr,16 if failure == 'error-overlap' else len(error))
    assert owner is not None and status == 1
    np.testing.assert_array_equal(k,[-12345.,-12345.])
    np.testing.assert_array_equal(f,[-67890.,-67890.])
    np.testing.assert_array_equal(lengths,[6.,9. if failure == 'outside' else 6.5])


def test_summary_nan_and_shape_contract():
    for value in (np.array(3.),np.array([3.]),np.array([2.,3.,1.]),np.array([2.,np.nan])):
        expected, actual = old._summary(value), native.summary(value)
        if isinstance(expected,dict):
            for key in expected: np.testing.assert_array_equal(actual[key],expected[key])
        else: np.testing.assert_array_equal(actual,expected)


@pytest.mark.parametrize('length,wall', [('bad',.4),(6.,'bad'),(9.,.4)])
def test_scalar_geometry_error_text(length,wall):
    for function, reference, extra in (
        (predict.predict_K_cF,old.predict_K_cF,()),
        (predict.predict_dP,old.predict_dP,(1.,1.2,1.8e-5,.182)),
    ):
        with pytest.raises(ValueError) as expected:
            reference('Gyroid',length,wall,.35,*extra)
        with pytest.raises(ValueError) as actual:
            function('Gyroid',length,wall,.35,*extra)
        assert str(actual.value) == str(expected.value)


def test_scalar_power_overflow_keeps_python_error():
    args = ('Gyroid',6.,.4,.35,1e200,1.2,1.8e-5,.182)
    with pytest.raises(OverflowError) as expected:
        old.predict_dP(*args)
    with pytest.raises(OverflowError) as actual:
        predict.predict_dP(*args)
    assert actual.value.args == expected.value.args


@pytest.mark.parametrize('shape', [(),(2,3)])
def test_co2_drag_uses_one_fixed_factor(shape):
    from sjtu_tpmshx.shared.models import co2_correlations
    k, f = np.full(shape,2e-8), np.full(shape,125.)
    expected = old.apply_prepared_correction(k,f,dict(
        scale_K=1./2.5,scale_F=2.5,campaign='co2-fixed-factors-20261009-v1',
        scope='CO2-user-fixed',fluid='co2'))
    actual = co2_correlations.apply_drag(k,f)
    for value, reference in zip(actual[:2],expected[:2]):
        np.testing.assert_array_equal(value,reference)
        assert type(value) is type(reference)
    assert actual[2] == expected[2]


def test_raw_pressure_error_keeps_numeric_result_atomic():
    owner = ct.CDLL(_native_preparation._library().path)
    function = owner.tpmshx_preparation_df_incompressible_v1
    function.argtypes = [*native._SIGNATURES['incompressible'],*native._ERROR]
    function.restype = ct.c_int
    output, failure, error = native._Pressure(), native._FPFailure(), ct.create_string_buffer(256)
    ct.memset(ct.byref(output),0x5a,ct.sizeof(output))
    original = bytes(output)
    values = [native._native_grid._scalar(value) for value in (1e200,1.2,1.8e-5,.182)]
    status = function(1,6.,.4,*values,ct.byref(output),ct.byref(failure),error,len(error))
    assert status == 3
    assert failure.python_cause == 2
    assert 0 <= failure.event_count <= native._FP_EVENT_COUNT
    assert error.value
    assert bytes(output) == original


def test_raw_pressure_error_storage_cannot_overlap_result():
    owner = ct.CDLL(_native_preparation._library().path)
    function = owner.tpmshx_preparation_df_incompressible_v1
    function.argtypes = [*native._SIGNATURES['incompressible'],*native._ERROR]
    function.restype = ct.c_int
    output = native._Pressure()
    failure = native._FPFailure()
    ct.memset(ct.byref(output),0x5a,ct.sizeof(output))
    original = bytes(output)
    values = [native._native_grid._scalar(value) for value in (4.7,1.2,1.8e-5,.182)]
    status = function(1,6.,.4,*values,ct.byref(output),ct.byref(failure),
                      ct.cast(ct.byref(output),ct.POINTER(ct.c_char)),ct.sizeof(output))
    assert status == 1
    assert bytes(output) == original


def test_raw_pressure_failure_retains_prior_cast_events():
    owner = ct.CDLL(_native_preparation._library().path)
    function = owner.tpmshx_preparation_df_incompressible_v1
    function.argtypes = [*native._SIGNATURES['incompressible'],*native._ERROR]
    function.restype = ct.c_int
    output, failure, error = native._Pressure(), native._FPFailure(), ct.create_string_buffer(256)
    ct.memset(ct.byref(output),0x5a,ct.sizeof(output))
    original = bytes(output)
    values = [native._native_grid._scalar(value) for value in (1e200,1.2,np.float16(1.8e-5),.182)]
    status = function(1,6.,.4,*values,ct.byref(output),ct.byref(failure),error,len(error))
    assert status == 3 and failure.python_cause == 2
    assert 0 < failure.event_count <= native._FP_EVENT_COUNT
    events = [int(value) for value in failure.events[:failure.event_count] if value]
    assert events and (events[0] >> 8) & 255 == 8 and events[0] & 4
    assert error.value and bytes(output) == original


@pytest.mark.parametrize('malformed',['null','misaligned','range','result-overlap','error-overlap'])
def test_raw_pressure_failure_pod_preflight(malformed):
    owner = ct.CDLL(_native_preparation._library().path)
    function = owner.tpmshx_preparation_df_incompressible_v1
    function.argtypes = [*native._SIGNATURES['incompressible'],*native._ERROR]
    function.restype = ct.c_int
    output, failure, error = native._Pressure(), native._FPFailure(), ct.create_string_buffer(256)
    ct.memset(ct.byref(output),0x5a,ct.sizeof(output))
    ct.memset(ct.byref(failure),0x6b,ct.sizeof(failure))
    original, original_failure = bytes(output), bytes(failure)
    pointer, error_pointer, capacity = ct.byref(failure), error, len(error)
    storage = ct.create_string_buffer(ct.sizeof(failure)+8)
    if malformed == 'null': pointer = None
    elif malformed == 'misaligned': pointer = ct.cast(ct.addressof(storage)+1,ct.POINTER(native._FPFailure))
    elif malformed == 'range': pointer = ct.cast(ct.c_void_p(-8),ct.POINTER(native._FPFailure))
    elif malformed == 'result-overlap': pointer = ct.cast(ct.byref(output),ct.POINTER(native._FPFailure))
    else:
        error_pointer = ct.cast(ct.byref(failure),ct.POINTER(ct.c_char))
        capacity = ct.sizeof(failure)
    values = [native._native_grid._scalar(value) for value in (4.7,1.2,1.8e-5,.182)]
    status = function(1,6.,.4,*values,ct.byref(output),pointer,error_pointer,capacity)
    assert status == 1
    assert bytes(output) == original and bytes(failure) == original_failure

