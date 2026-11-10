"""Shared sCO2 property and inverse-state guards."""

import numpy as np
import pytest

from sjtu_tpmshx.shared.models import sco2_props

@pytest.mark.parametrize('pressure', [7.9e6, 8e6, 16e6])
def test_temperature_field_round_trips_enthalpy_field(pressure):
    """T(h(T)) == T over a field spanning the pseudocritical line."""
    T = np.array([[290.0, 307.0], [312.0, 360.0]])
    h = sco2_props.sco2_prop('H', T, pressure)
    T_back = sco2_props.sco2_temperature_from_enthalpy(h, pressure)
    assert T_back.shape == T.shape
    assert np.allclose(T_back, T, atol=1e-3)


@pytest.mark.parametrize('pressure', [7.9e6, 8e6, 16e6])
def test_temperature_field_matches_scalar(pressure):
    """Field query agrees with the scalar sco2_temperature element-wise."""
    h = np.array([sco2_props.sco2_prop('H', 300.0, pressure),
                  sco2_props.sco2_prop('H', 330.0, pressure)])
    Tf = sco2_props.sco2_temperature_from_enthalpy(h, pressure)
    assert Tf[0] == pytest.approx(sco2_props.sco2_temperature(float(h[0]), pressure), rel=1e-9)
    assert Tf[1] == pytest.approx(sco2_props.sco2_temperature(float(h[1]), pressure), rel=1e-9)


@pytest.mark.parametrize('pressure', [np.nextafter(7.9e6, -np.inf),
                                    np.nextafter(16e6, np.inf)])
def test_property_and_inverse_reject_pressure_before_eos(monkeypatch, pressure):
    from sjtu_tpmshx.shared.models import _native_properties

    def unexpected_eos(*args):
        pytest.fail('out-of-range pressure reached EOS')
    monkeypatch.setattr(_native_properties, 'sco2_pt', unexpected_eos)
    # Invalid h would expose an HP query before its native pressure guard.
    for temperature, enthalpy in ((330., np.nan), (np.array([330.]), np.array([np.nan]))):
        with pytest.raises(ValueError, match=r'pressure must be within 7.9..16 MPa'):
            sco2_props.sco2_prop('H', temperature, pressure)
        with pytest.raises(ValueError, match=r'pressure must be within 7.9..16 MPa'):
            sco2_props.sco2_temperature_from_enthalpy(enthalpy, pressure)


@pytest.mark.parametrize('temperature, message', [(np.nan, 'must be finite'),
                                                (279., 'temperature must be')])
def test_state_error_order_precedes_pressure(temperature, message):
    with pytest.raises(ValueError, match=message + r'.*index=\(1,\)'):
        sco2_props._validate_state([330., temperature], [8e6, 7.9e6 - 1.],
                                   where='paired state')
