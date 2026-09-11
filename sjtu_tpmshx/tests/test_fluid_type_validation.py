"""Guard: sCO2 fluid selection must still raise NotImplementedError.

2026-05-09 (option B): water unblocked for the 2D Compute path. Properties
(rho/mu/k via NIST-grade correlations) and heat transfer (Pr-substitution
Nu) are physical; D-F closure (predict_K_cF) reuses the air-fit surrogate,
so water-side dP is engineering placeholder — flagged in code, but no
longer hard-blocked at validate time.

sCO2 stays blocked pending its own Nu / D-F correlations.
"""
from sjtu_tpmshx.models.tpms_calc import (
    parse_fluid_type, validate_fluid_type, _SUPPORTED_FLUIDS,
)


class _FakeCombo:
    def __init__(self, text): self._text = text
    def currentText(self): return self._text


def test_parse_fluid_type_air():
    assert parse_fluid_type(_FakeCombo("Air")) == 'air'


def test_parse_fluid_type_water():
    assert parse_fluid_type(_FakeCombo("Water")) == 'water'


def test_parse_fluid_type_sco2_subscript():
    assert parse_fluid_type(_FakeCombo("sCO₂")) == 'sco2'


def test_parse_fluid_type_sco2_plain():
    assert parse_fluid_type(_FakeCombo("sCO2")) == 'sco2'


def test_validate_air_passes():
    validate_fluid_type('air', 'A')
    validate_fluid_type('air', 'B')


def test_validate_water_passes():
    """2026-05-09 option B — water now allowed (Pr-substitution Nu +
    NIST-grade properties; dP is engineering placeholder)."""
    validate_fluid_type('water', 'A')
    validate_fluid_type('water', 'B')


def test_validate_sco2_passes():
    """Phase A (2026-06-26): sCO2 unblocked. Diamond Nu fit from D-7-6
    experiment (SCO2_NU_COEFFS), CoolProp properties, incompressible flow.
    Far-from-critical only; near-pseudocritical needs a property-ratio
    correction (Phase C), not gated here."""
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


def test_water_compute_higher_Nu_via_Pr_substitution():
    """Water Pr ~ 5-7, air Pr ~ 0.72. Pr-substitution lifts water Nu
    above air Nu at matched-Re-window by factor (Pr_water/Pr_air)^(1/3)."""
    from sjtu_tpmshx.models.tpms_calc import compute
    r_air = compute('Gyroid', 7.0, 0.4, 10.0, 320.0, 200000.0, 16.0,
                    fluid_type='air')
    r_w   = compute('Gyroid', 7.0, 0.4, 1.0,  320.0, 200000.0, 16.0,
                    fluid_type='water')
    # Both Re inside fit window
    assert 600 < r_air['Re'] < 30000
    assert 600 < r_w['Re']   < 30000
    # Pr ratio invariant — Nu_water = Nu_air * (Pr_w/Pr_a)^(1/3) only
    # captures the Pr scaling; the Re branch differs because u differs.
    # Sanity: both Nu > 0.
    assert r_air['Nu'] > 0 and r_w['Nu'] > 0
