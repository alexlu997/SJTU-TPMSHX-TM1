"""fluid_props registry primitives must stay byte-identical to the inline
tpms_calc dispatch they replaced (DUP-D shim in run_calculation{,_3d}.py)."""
import pytest

from sjtu_tpmshx.models import fluid_props as fp
from sjtu_tpmshx.models import tpms_calc as t


@pytest.mark.parametrize("T,P", [(300.0, 101325.0), (350.0, 120000.0), (450.0, 90000.0)])
def test_air_primitives(T, P):
    m = fp.get('air')
    assert m.name == 'air' and m.compressible is True
    assert m.rho(T, P) == t.air_density(T, P)
    assert m.rho(T) == t.air_density(T)            # default P == 101325
    assert m.cp(T) == t.air_cp(T)
    assert m.mu(T) == t.air_viscosity(T)
    assert m.k(T) == t.air_conductivity(T)


@pytest.mark.parametrize("T", [290.0, 330.0, 360.0])
def test_water_primitives(T):
    m = fp.get('water')
    assert m.name == 'water' and m.compressible is False
    assert m.rho(T, 999.0) == t.water_density(T)   # P ignored (incompressible)
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


def test_case_insensitive():
    assert fp.get('AIR') is fp.get('air')
    assert fp.get(' Water ') is fp.get('water')
