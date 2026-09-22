"""Supported fluid identifiers and independent material-property checks."""
from sjtu_tpmshx.models.tpms_calc import (
    validate_fluid_type, _SUPPORTED_FLUIDS,
)












def test_validate_air_passes():
    validate_fluid_type('air', 'A')
    validate_fluid_type('air', 'B')


def test_validate_water_passes():
    """Water has registered physical properties and a water-CFD Nu fit."""
    validate_fluid_type('water', 'A')
    validate_fluid_type('water', 'B')


def test_validate_sco2_passes():
    """sCO2 has registered properties and the current CFD Nu model."""
    validate_fluid_type('sco2', 'A')
    validate_fluid_type('sco2', 'B')


def test_supported_fluids_air_water_sco2():
    assert _SUPPORTED_FLUIDS == {'air', 'water', 'sco2'}


def test_water_compute_returns_water_density():
    """compute(fluid_type='water') uses water properties, not air."""
    from sjtu_tpmshx.models.tpms_calc import compute
    # u_air=10 m/s & u_water=1 m/s lands both Re in the air-fit window
    # [600, 30000] at the same Gyroid 7×0.4 geometry, 320 K, 200 kPa.
    r_air = compute('Gyroid', 7.0, 0.4, 10.0, 320.0, 200000.0, 16.0,
                    fluid_type='air')
    r_w   = compute('Gyroid', 7.0, 0.4, 1.0,  320.0, 200000.0, 16.0,
                    fluid_type='water')
    # ρ_water(320 K) ~ 989 kg/m³, ρ_air(320 K, 200 kPa) ~ 2.18 kg/m³
    assert 980 < r_w['rho'] < 1000
    assert 1.9 < r_air['rho'] < 2.4
    # μ_water(320 K) ~ 5.7e-4, μ_air(320 K) ~ 1.94e-5
    assert r_w['mu']  > 20 * r_air['mu']
    # k_f_water ~ 0.65, k_f_air ~ 0.027
    assert r_w['k_f'] > 10 * r_air['k_f']


def test_fluid_specific_nu_closures_are_positive():
    """Air and water use their own fitted closures in this in-domain example."""
    from sjtu_tpmshx.models.tpms_calc import compute
    r_air = compute('Gyroid', 7.0, 0.4, 10.0, 320.0, 200000.0, 16.0,
                    fluid_type='air')
    r_w   = compute('Gyroid', 7.0, 0.4, 1.0,  320.0, 200000.0, 16.0,
                    fluid_type='water')
    # Both Re inside fit window
    assert 600 < r_air['Re'] < 30000
    assert 600 < r_w['Re']   < 30000
    # The independent closure forms are checked in test_nu_correlations;
    # this compute-level check only requires finite positive heat transfer.
    assert r_air['Nu'] > 0 and r_w['Nu'] > 0
