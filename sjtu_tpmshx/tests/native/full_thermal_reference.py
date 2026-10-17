"""Independent selected enthalpy checks for full native runs."""
import numpy as np


def model_enthalpy(temperature, fluid):
    """Integrate the existing polynomial with NumPy for independent evidence checks."""
    from sjtu_tpmshx.models.tpms_props import model_h_coefficients
    a, b, c, origin, reference = model_h_coefficients(fluid)
    integral = np.polynomial.Polynomial((a, b, c)).integ()
    return integral(np.asarray(temperature) - origin) - integral(reference - origin)


def assert_selected_enthalpy(result):
    """Check returned mixed enthalpy with the independent polynomial integral."""
    record = result.metadata['execution_record']
    native = result.boundary_fluxes['true_h']
    scale = record['numerics']['enthalpy_update_normalization']
    assert scale['definition'] == 'inlet_cp_times_temperature_difference_v1'
    assert scale['unit'] == 'J/kg'
    from CoolProp.CoolProp import PropsSI
    for side in 'AB':
        model = record['sides'][side]
        fluid = model['fluid']
        temperature = result.fields['Ta' if side == 'A' else 'Tb']
        h = native['h_' + side]
        assert np.isfinite(h).all() and scale['sides'][side] >= 1.
        if fluid in ('air', 'water'):
            assert model['energy']['relation'] == 'integral_cp_T'
            expected = model_enthalpy(temperature, fluid)
        else:
            assert model['energy']['relation'] == 'eos_h_TP'
            pressure = result.fields['P_thermal_' + side]
            expected = np.array([PropsSI('H', 'T', t, 'P', p, 'CO2')
                                 for t, p in zip(temperature.flat, pressure.flat)]).reshape(temperature.shape)
        if temperature.ndim == 2:
            expected = expected[..., None]
        np.testing.assert_allclose(h, expected, rtol=1e-10, atol=1e-6)
