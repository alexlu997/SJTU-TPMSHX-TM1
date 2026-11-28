"""fluid_props registry primitives must stay byte-identical to the inline
tpms_calc dispatch they replaced (DUP-D shim in run_calculation{,_3d}.py).

Fluid types, roughness ownership, the water Nu formula and the design
adapter also stay unchanged.
"""
import pytest

from tm1.physical_models import fluid_props as fp
from tm1.physical_models import tpms_calc as t
from tm1.physical_models.nu_correlations import (WATER_NU_COEFFS, WATER_NU_RE_RANGE,
                                                         nu_water_topo)

_TEMPS = (300.0, 370.0, 422.0)
_PRESSURES = (101325.0, 192362.0)


@pytest.mark.parametrize("T,P", [(350.0, 120000.0), (450.0, 90000.0)]
                         + [(T, P) for T in _TEMPS for P in _PRESSURES])
def test_air_primitives(T, P):
    m = fp.get('air')
    assert m.name == 'air' and m.compressible is True
    assert m.rho(T, P) == t.air_density(T, P)
    assert m.rho(T) == t.air_density(T)            # default P == 101325
    assert m.cp(T) == t.air_cp(T)
    assert m.mu(T) == t.air_viscosity(T)
    assert m.k(T) == t.air_conductivity(T)


@pytest.mark.parametrize("T,P", [(290.0, 999.0), (330.0, 999.0), (360.0, 999.0)]
                         + [(T, P) for T in _TEMPS for P in _PRESSURES])
def test_water_primitives(T, P):
    m = fp.get('water')
    assert m.name == 'water' and m.compressible is False
    assert m.rho(T, P) == t.water_density(T)       # P ignored (incompressible)
    assert m.rho(T) == t.water_density(T)          # P optional
    assert m.cp(T) == t.water_cp(T)
    assert m.mu(T) == t.water_viscosity(T)
    assert m.k(T) == t.water_conductivity(T)


@pytest.mark.parametrize("tpms,Re,eps,L,Dh", [
    ('Diamond', 2000.0, 0.36, 6.0, 1.2),
    ('Gyroid', 800.0, 0.4, 5.0, 1.0),
])
def test_nu_air_matches_and_ignores_pr(tpms, Re, eps, L, Dh):
    m = fp.get('air')
    expected = t.nu_from_Re(tpms, Re, eps, L, Dh)
    assert m.nu(tpms, Re, eps, L, Dh, None) == expected
    assert m.nu(tpms, Re, eps, L, Dh, 5.0) == expected   # Pr ignored for air


@pytest.mark.parametrize("tpms,Re,eps,L,Dh,Pr", [
    ('Diamond', 2000.0, 0.36, 6.0, 1.2, 4.5),
    ('Gyroid', 800.0, 0.4, 5.0, 1.0, 6.0),
])
def test_nu_water_forwards_pr(tpms, Re, eps, L, Dh, Pr):
    m = fp.get('water')
    assert m.nu(tpms, Re, eps, L, Dh, Pr) == t.nu_water_topo(tpms, Re, Pr)


def test_unknown_fluid_raises():
    with pytest.raises(ValueError):
        fp.get('mercury')


def test_design_nu_re_window_rejects_unknown_fluid():
    from tm1.physical_models.design_fluids import nu_re_window

    with pytest.raises(ValueError, match='helium'):
        nu_re_window('helium')


def test_case_insensitive():
    assert fp.get('AIR') is fp.get('air')
    assert fp.get(' Water ') is fp.get('water')


def test_flow_model_mapping():
    assert fp.flow_model('air') == 'ideal_gas'
    assert fp.flow_model('water') == 'incompressible'
    # Phase A (2026-06-26): sCO2 added as incompressible (D-7-6 ΔP/P<2%);
    # compressible ρ(P_local) is Phase B.
    assert fp.flow_model('sco2') == 'incompressible'
    with pytest.raises(ValueError):
        fp.flow_model('argon')


def test_embeds_roughness_flags():
    assert fp.get('air').embeds_roughness is False
    assert fp.get('water').embeds_roughness is True   # experiment-trained D-F closure; skip air roughness modes


@pytest.mark.parametrize('topo', ('Diamond', 'Gyroid'))
@pytest.mark.parametrize('Re', (0.5, 150.0, 5000.0, 50000.0))
def test_nu_water_topo_matches_retired_formula(topo, Re):
    Pr_w = 5.0
    co = WATER_NU_COEFFS[topo]
    expected = co['c'] * max(Re, 1.0) ** co['a'] * Pr_w ** (1 / 3)
    assert nu_water_topo(topo, Re, Pr_w) == expected


def test_design_fluids_adapter_equivalence():
    from tm1.physical_models.design_fluids import fluid_props as design_props, fluid_nu, nu_re_window
    for f, temperatures in (('air', _TEMPS), ('water', (300.0, 370.0))):
        for T in temperatures:
            p = design_props(f, T, 192362.0)
            m = fp.get(f)
            rho_ref = m.rho(T, 192362.0) if m.compressible else m.rho(T)
            assert p.rho == rho_ref
            assert p.mu == m.mu(T)
            assert p.k == m.k(T)
            assert p.cp == m.cp(T)
            assert p.Pr == p.mu * p.cp / p.k
    with pytest.raises(fp.WaterStateError):
        design_props('water', 422.0, 192362.0)
    assert nu_re_window('water') == WATER_NU_RE_RANGE
    # water fluid_nu: design Pr convention (320 K, 2e5 Pa) preserved
    pw = design_props('water', 320.0, 2e5)
    assert fluid_nu('water', 'Gyroid', 800.0, 0.35, 7.0, 3.4) == \
        nu_water_topo('Gyroid', 800.0, pw.Pr)
