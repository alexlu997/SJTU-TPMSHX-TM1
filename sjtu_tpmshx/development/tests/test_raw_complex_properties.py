"""Derived scalar complex values against the original public expressions."""
import ctypes as ct
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import df_reference, nu_reference, property_reference
from sjtu_tpmshx.development.tests.test_property_fp_diagnostics import assert_sentinel, sentinel_result
from sjtu_tpmshx.shared.models import _native_properties as native
from sjtu_tpmshx.shared.models import design_fluids, nu_correlations, tpms_calc
from sjtu_tpmshx.shared.models._native_preparation import _library


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
        return
    assert first[2].dtype == second[2].dtype
    assert first[2].shape == second[2].shape
    np.testing.assert_array_equal(first[2], second[2])


@pytest.mark.parametrize('temperature', [-300., -100., -300])
def test_design_air_retains_complex_property_intermediates(temperature):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        actual = design_fluids.fluid_props('air', temperature, 101325.)
        expected = property_reference.fluid_props('air', temperature, 101325.)
    for field in ('rho', 'mu', 'k', 'cp', 'Pr'):
        equal(observe(lambda: getattr(actual, field)), observe(lambda: getattr(expected, field)))


@pytest.mark.parametrize('quantity', ['prandtl', 'surface_transfer'])
@pytest.mark.parametrize('arguments', [
    (1.25 - .5j, 1.125, .75),
    (np.complex64(1.25 - .5j), 1.125, .75),
    (np.complex128(1.25 - .5j), 1.125, .75),
    (1.25 - .5j, np.float32(1.125), .75),
    (1.25 - .5j, np.float64(1.125), .75),
    (np.float32(1.25), 1.125 - .5j, .75),
    (np.complex128(1.25 - .5j), np.float64(1.125), np.float64(.75)),
    (1.25 - .5j, .75, 0.),
    (np.complex64(1.25 - .5j), .75, 0.),
    (np.complex64(1.25 - .5j), .75, np.empty(0, dtype=np.float32)),
])
def test_complex_scalar_metadata_and_original_arithmetic(quantity, arguments):
    first, second, third = arguments
    equal(observe(lambda: getattr(native, quantity)(*arguments)),
          observe(lambda: first * second / third))


@pytest.mark.parametrize('quantity', ['prandtl', 'surface_transfer'])
@pytest.mark.parametrize('dtype', [complex, np.complex64, np.complex128])
@pytest.mark.parametrize('denominator', [complex(1.54321098, -.23456789), complex(-.23456789, 1.54321098)])
def test_complex_quotient_both_dominant_components(quantity, dtype, denominator):
    first, second, third = dtype(.123456789 - 1.23456789j), 1.23456789, dtype(denominator)
    equal(observe(lambda: getattr(native, quantity)(first, second, third)),
          observe(lambda: first * second / third))


@pytest.mark.parametrize('diameter', [.002, np.float64(.002)])
def test_negative_raw_re_keeps_complex_nu_to_surface_transfer(diameter):
    def actual():
        nu = nu_correlations.nu_from_Re('Gyroid', -3000., .4, 6., 2.)
        return native.surface_transfer(nu, .03, diameter)

    def expected():
        nu = nu_reference.nu_from_Re('Gyroid', -3000., .4, 6., 2.)
        return nu * .03 / diameter

    equal(observe(actual), observe(expected))


def test_raw_compute_negative_speed_keeps_complex_outputs(monkeypatch):
    diameter = np.float64(.002)
    geometry = dict(epsilon=.8, epsilon_A=.4, epsilon_B=.4, A_0=np.float64(1200.), D_h=diameter)
    monkeypatch.setattr(tpms_calc, '_tpms_geom', lambda *args: dict(geometry))
    tpms_calc.compute.cache_clear()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            actual, _ = tpms_calc._compute_cached('Gyroid', 6., .4, -.2, 300., 101325.)
        mu = float(property_reference.air_viscosity(300.))
        k = float(property_reference.air_conductivity(300.))
        rho = float(property_reference.air_density(300., 101325.))
        re = rho * -.2 * diameter / mu
        nu = nu_reference.nu_from_Re('Gyroid', re, .4, 6., diameter * 1000.)
        permeability, forchheimer = df_reference.predict_K_cF('Gyroid', 6., .4, .4)
        for actual_value, expected_value in ((actual['Re'], re), (actual['Nu'], nu),
                                             (actual['H_sf'], nu * k / diameter),
                                             (actual['K_df'], permeability),
                                             (actual['cF_df'], forchheimer)):
            equal(observe(lambda: actual_value), observe(lambda: expected_value))
    finally:
        tpms_calc.compute.cache_clear()


@pytest.mark.parametrize('temperature', [-300., -100.])
def test_raw_compute_negative_temperature_still_fails_at_float_mu(monkeypatch, temperature):
    geometry = dict(epsilon=.8, epsilon_A=.4, epsilon_B=.4, A_0=np.float64(1200.), D_h=np.float64(.002))
    monkeypatch.setattr(tpms_calc, '_tpms_geom', lambda *args: dict(geometry))
    tpms_calc.compute.cache_clear()
    try:
        equal(observe(lambda: tpms_calc._compute_cached('Gyroid', 6., .4, .2, temperature, 101325.)),
              observe(lambda: float(property_reference.air_viscosity(temperature))))
    finally:
        tpms_calc.compute.cache_clear()


def operands():
    _, buffers, inputs = native._inputs((1.25, 1.125, .75))
    return buffers, [native._Operand(value, -.5 if index == 0 else 0., int(index == 0))
                     for index, value in enumerate(inputs)]


@pytest.mark.parametrize('quantity', ['prandtl', 'surface_transfer'])
@pytest.mark.parametrize('invalid', ['category', 'array', 'zero', 'half', 'integer', 'count'])
def test_operand_boundary_rejects_bad_metadata_without_partial_output(quantity, invalid):
    buffers, inputs = operands()
    if invalid == 'category':
        inputs[0].category = 2
    elif invalid in ('array', 'zero'):
        inputs[0].real.layout = 3 if invalid == 'array' else 2
        inputs[0].real.kind = native._Scalar(1.25, 64, 1)
    elif invalid == 'half':
        inputs[0].real.kind = native._Scalar(1.25, 16, 1)
        inputs[0].real.layout = 1
    elif invalid == 'integer':
        inputs[0].real.kind = native._Scalar(1., 16, 2)
        inputs[0].real.layout = 1
    else:
        inputs[1].real.count = 0
    result, failure, error = sentinel_result(1), native._Failure(), ct.create_string_buffer(2048)
    status = native._function(_library(), quantity)(*inputs, result.output, ct.byref(failure), error, len(error))
    assert buffers
    assert status == 1
    assert_sentinel(result)


@pytest.mark.parametrize('quantity', ['prandtl', 'surface_transfer'])
@pytest.mark.parametrize('overlap', ['output', 'error'])
def test_operand_boundary_preserves_aliased_input(quantity, overlap):
    source = np.full(512, 1.25, dtype=np.float64)
    before = source.tobytes()
    buffers, inputs = operands()
    inputs[0].real.values = native._pointer(source)
    result, failure, error = sentinel_result(1), native._Failure(), ct.create_string_buffer(2048)
    if overlap == 'output':
        result.output.values = native._pointer(source)
    else:
        error = ct.cast(source.ctypes.data, ct.POINTER(ct.c_char))
    capacity = source.nbytes if overlap == 'error' else len(error)
    status = native._function(_library(), quantity)(*inputs, result.output, ct.byref(failure), error, capacity)
    assert buffers
    assert status == 1
    assert source.tobytes() == before
    assert_sentinel(result)
