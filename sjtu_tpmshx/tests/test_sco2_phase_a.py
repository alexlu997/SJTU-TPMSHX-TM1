"""Phase A sCO2 enablement (2026-06-26; correlation swapped 2026-07-15).
Covers: SCO2_NU_COEFFS / nu_sco2_topo correlation form (smooth-wall unit-cell
CFD campaign, Diamond + Gyroid, Nu = c·Re^a·Pr^⅓·(Dh/L)^d — replaced the
D-7-6 single-geometry experimental fit), FluidModel('sco2') CoolProp
primitives + (T,P) signature, compute(fluid_type='sco2') routing the sCO2 Nu.

Fit provenance: validation/sco2_cfd/fit_nu_sco2.py (V0b), ledger SCO2-CFD.
"""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.models import fluid_props, tpms_calc
from sjtu_tpmshx.models.nu_correlations import (
    nu_sco2_topo, SCO2_NU_COEFFS, SCO2_NU_RE_RANGE,
)


# ── correlation form ────────────────────────────────────────────────
def test_sco2_nu_form_diamond():
    """Nu = c·Re^a·Pr^(1/3)·(Dh/L)^d, smooth wall (no roughness factor)."""
    Re, Pr, L_mm, Dh_mm = 20000.0, 0.85, 7.0, 2.9
    co = SCO2_NU_COEFFS['Diamond']
    expect = (co['c'] * Re ** co['a'] * Pr ** (1 / 3)
              * (Dh_mm / L_mm) ** co['d'])
    assert nu_sco2_topo('Diamond', Re, Pr, L_mm, Dh_mm) \
        == pytest.approx(expect, rel=1e-12)


def test_sco2_nu_coeffs_locked():
    """2026-07-26 smooth-wall CFD refit (V0b) — refit = edit nu_correlations.
    Gyroid L=8 completion (purely additive upload): 20 Diamond + **20** Gyroid
    geometries L∈[4,8]. G_8_3 went 80→270 cases, G_8_4/5/6 0→270 (previously
    ABSENT). Diamond untouched — unchanged coeffs here are the control.
    Retired 2026-07-23 Gyroid (17 geometries): c=0.201101 a=0.720625
    d=-0.013529. Retired 2026-07-15 coeffs (wrong-Dh + extrapolated 7/0.6):
    Diamond c=0.166714 a=0.705490 d=-0.434198;
    Gyroid c=0.199133 a=0.719463 d=-0.109010."""
    assert SCO2_NU_COEFFS['Diamond'] == {
        'c': 0.184809, 'a': 0.707421, 'd': -0.281792}
    assert SCO2_NU_COEFFS['Gyroid'] == {
        'c': 0.192994, 'a': 0.722221, 'd': -0.044313}
    assert SCO2_NU_RE_RANGE == (2600.0, 128000.0)


def test_sco2_nu_array_safe():
    Re = np.array([3000.0, 20000.0, 60000.0])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        out = nu_sco2_topo('Diamond', Re, 0.85, 7.0, 2.9)
    assert out.shape == Re.shape and np.all(out > 0)


def test_sco2_nu_gyroid_supported():
    """CFD campaign covers Gyroid — unlocked 2026-07-15 (was Diamond-only)."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        nu_g = nu_sco2_topo('Gyroid', 20000.0, 1.5, 5.0, 2.3)
    assert nu_g > 0


def test_sco2_nu_unknown_topology_raises():
    """No silent borrowing of coefficients for unfitted topologies."""
    with pytest.raises(NotImplementedError):
        nu_sco2_topo('Primitive', 20000.0, 0.85, 5.0, 2.0)


# ── FluidModel primitives (CoolProp) ────────────────────────────────
def test_sco2_fluidmodel_incompressible_phase_a():
    m = fluid_props.get('sco2')
    assert m.compressible is False              # Phase A: incompressible
    assert m.embeds_roughness is True           # do not stack the air roughness factor
    assert fluid_props.flow_model('sco2') == 'incompressible'


def test_sco2_props_depend_on_pressure():
    """Real-gas: density at fixed T differs between 8 and 16 MPa (NOT ideal)."""
    m = fluid_props.get('sco2')
    rho_low = m.rho(360.0, 8e6)
    rho_high = m.rho(360.0, 16e6)
    assert rho_high > 1.5 * rho_low             # dense at high P, far from ideal


def test_sco2_props_require_pressure():
    m = fluid_props.get('sco2')
    with pytest.raises(ValueError, match="pressure"):
        m.cp(400.0)                              # missing P must raise clearly


# ── compute() routing ───────────────────────────────────────────────
def test_compute_sco2_routes_sco2_nu():
    T, P = 420.0, 9e6
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        r = tpms_calc.compute('Diamond', 7.0, 0.6, u=1.5,
                              T_in_K=T, P_in_Pa=P, k_s=15.0,
                              fluid_type='sco2')
    m = fluid_props.get('sco2')
    Pr = m.mu(T, P) * m.cp(T, P) / m.k(T, P)
    g = tpms_calc.geometry('Diamond', 7.0, 0.6, 15.0)
    co = tpms_calc.SCO2_NU_COEFFS['Diamond']
    expect = (co['c'] * r['Re'] ** co['a'] * Pr ** (1 / 3)
              * (float(g['D_h']) * 1000.0 / 7.0) ** co['d'])
    assert r['Nu'] == pytest.approx(expect, rel=1e-9)
    assert r['H_sf'] > 0


@pytest.mark.parametrize('T,P', [(279.9, 8e6), (700.1, 8e6),
                                  (300.0, np.nextafter(7.9e6, -np.inf)),
                                  (300.0, np.nextafter(16e6, np.inf))])
def test_sco2_v1_property_envelope(T, P):
    with pytest.raises(ValueError, match='sCO2 V1'):
        fluid_props.get('sco2').rho(T, P)


@pytest.mark.parametrize('pressure', [7.9e6, 7.99e6, 8e6, 12e6, 16e6])
def test_sco2_pressure_domain_matches_direct_eos(pressure):
    from CoolProp.CoolProp import PropsSI

    model = fluid_props.get('sco2')
    temperature = np.array([310., 360.])
    for name, key in [('rho', 'D'), ('cp', 'C'), ('mu', 'V'),
                      ('k', 'L'), ('enthalpy', 'H')]:
        prop = getattr(model, name)
        expected = PropsSI(key, 'T', temperature, 'P', pressure, 'CO2')
        np.testing.assert_array_equal(prop(temperature, pressure), expected)
        assert prop(360., pressure) == expected[1]


@pytest.mark.parametrize('nz', [1, 2])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('other_fluid', ['air', 'water', 'sco2'])
def test_sco2_config_pressure_bounds(nz, side, other_fluid):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig

    cfg = ComputeConfig()
    cfg.solver.Nz = nz
    cfg.geometry.Lz_m = .042
    cfg.fluid_A = FluidConfig(type=other_fluid, T_in_K=330.,
                             P_in_Pa=8e6 if other_fluid == 'sco2' else 2e5)
    cfg.fluid_B = FluidConfig(**vars(cfg.fluid_A))
    fluid = getattr(cfg, 'fluid_' + side)
    fluid.type = 'sco2'
    for pressure in (7.9e6, 8e6, 12e6, 16e6):
        fluid.P_in_Pa = pressure
        cfg.validate()
    for pressure in (np.nextafter(7.9e6, -np.inf), np.nextafter(16e6, np.inf)):
        fluid.P_in_Pa = pressure
        with pytest.raises(ValueError, match='sCO2 fluid ' + side + ' pressure'):
            cfg.validate()
