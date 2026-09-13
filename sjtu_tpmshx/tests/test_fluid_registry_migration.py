"""B1 1.1 — fluid_props registry migration equivalence guards.

The 2026-06-12 migration replaced per-site ``if fluid == 'water'``
property ladders with registry dispatch. These tests pin:

  1. registry primitives == the direct tpms_calc functions they wrap
     (exact float equality — the migration must be value-preserving);
  2. flow_model() mapping (SIMPLE fluid_type strings);
  3. embeds_roughness flags (roughness double-count guard, see the
     _apply_roughness_* helpers in solvers/backends/python/three_d/flux.py);
  4. nu_water_topo == the retired design/fluids.py inline formula;
  5. design.fluids thin-adapter outputs == registry primitives.
"""
import numpy as np
import pytest

from sjtu_tpmshx.models import fluid_props, tpms_calc
from sjtu_tpmshx.models.nu_correlations import (WATER_NU_COEFFS, WATER_NU_RE_RANGE,
                                     nu_water_topo)

_TEMPS = (300.0, 370.0, 422.0)
_PRESSURES = (101325.0, 192362.0)


@pytest.mark.parametrize('T', _TEMPS)
@pytest.mark.parametrize('P', _PRESSURES)
def test_air_primitives_exact(T, P):
    m = fluid_props.get('air')
    assert float(m.rho(T, P)) == float(tpms_calc.air_density(T, P))
    assert float(m.cp(T)) == float(tpms_calc.air_cp(T))
    assert float(m.mu(T)) == float(tpms_calc.air_viscosity(T))
    assert float(m.k(T)) == float(tpms_calc.air_conductivity(T))


@pytest.mark.parametrize('T', _TEMPS)
@pytest.mark.parametrize('P', _PRESSURES)
def test_water_primitives_exact_and_P_ignored(T, P):
    m = fluid_props.get('water')
    assert float(m.rho(T, P)) == float(tpms_calc.water_density(T))
    assert float(m.rho(T)) == float(tpms_calc.water_density(T))   # P optional
    assert float(m.cp(T)) == float(tpms_calc.water_cp(T))
    assert float(m.mu(T)) == float(tpms_calc.water_viscosity(T))
    assert float(m.k(T)) == float(tpms_calc.water_conductivity(T))


def test_flow_model_mapping():
    assert fluid_props.flow_model('air') == 'ideal_gas'
    assert fluid_props.flow_model('water') == 'incompressible'
    # Phase A (2026-06-26): sCO2 added as incompressible (D-7-6 ΔP/P<2%);
    # compressible ρ(P_local) is Phase B.
    assert fluid_props.flow_model('sco2') == 'incompressible'
    with pytest.raises(ValueError):
        fluid_props.flow_model('argon')


def test_embeds_roughness_flags():
    assert fluid_props.get('air').embeds_roughness is False
    assert fluid_props.get('water').embeds_roughness is True   # experiment-trained D-F closure; skip air roughness modes


def test_roughness_skip_uses_flag():
    """_apply_roughness_* must no-op for roughness-embedding fluids even
    under a non-baseline mode (the old string check, now via registry)."""
    from sjtu_tpmshx.solvers.backends.python.three_d.flux import _apply_roughness_KcF, _apply_roughness_h_v
    K = np.full((4, 4), 1e-8)
    cF = np.full((4, 4), 500.0)
    hv = np.full((4, 4), 1e6)
    K2, cF2 = _apply_roughness_KcF(K, cF, 'water', 998.0, 1e-3, 0.5, 0.003)
    assert K2 is K and cF2 is cF
    assert _apply_roughness_h_v(hv, 'water', 998.0, 1e-3, 0.5, 0.003) is hv


@pytest.mark.parametrize('topo', ('Diamond', 'Gyroid'))
@pytest.mark.parametrize('Re', (0.5, 150.0, 5000.0, 50000.0))
def test_nu_water_topo_matches_retired_formula(topo, Re):
    Pr_w = 5.0
    co = WATER_NU_COEFFS[topo]
    expected = co['c'] * max(Re, 1.0) ** co['a'] * Pr_w ** (1 / 3)
    assert nu_water_topo(topo, Re, Pr_w) == expected


def test_design_fluids_adapter_equivalence():
    from sjtu_tpmshx.models.design_fluids import fluid_props as design_props, fluid_nu, nu_re_window
    for f in ('air', 'water'):
        for T in _TEMPS:
            p = design_props(f, T, 192362.0)
            m = fluid_props.get(f)
            rho_ref = m.rho(T, 192362.0) if m.compressible else m.rho(T)
            assert p.rho == rho_ref
            assert p.mu == m.mu(T)
            assert p.k == m.k(T)
            assert p.cp == m.cp(T)
            assert p.Pr == p.mu * p.cp / p.k
    assert nu_re_window('water') == WATER_NU_RE_RANGE
    # water fluid_nu: design Pr convention (320 K, 2e5 Pa) preserved
    pw = design_props('water', 320.0, 2e5)
    assert fluid_nu('water', 'Gyroid', 800.0, 0.35, 7.0, 3.4) == \
        nu_water_topo('Gyroid', 800.0, pw.Pr)
