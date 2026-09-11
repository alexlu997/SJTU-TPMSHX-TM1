"""Property correlation + geometry sanity tests for solvers.tpms_calc.

Covers:
  * air_density ideal gas exact relation
  * air_viscosity Sutherland monotonic
  * air_cp polynomial range
  * water_density / water_viscosity / water_cp at known T
  * nu_water_gyroid_yan6 form
  * geometry returns expected dict keys + epsilon split
  * adaptive_grid returns sane Nx, Ny
  * compute returns superset of geometry keys
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from sjtu_tpmshx.models.tpms_calc import (
    air_density, air_viscosity, air_cp,
    water_density, water_viscosity, water_cp, water_conductivity,
    nu_water_gyroid_yan6,
    geometry, adaptive_grid, compute,
    parse_fluid_type, validate_fluid_type,
)


# ─── Air properties ────────────────────────────────────────────────


def test_air_density_ideal_gas_exact_at_273K():
    """ρ = P·M / (R·T) at 273.15 K, 101325 Pa → ~1.293 kg/m³ (textbook)."""
    rho = air_density(273.15)
    assert 1.28 <= rho <= 1.31, f"ρ_air(273K) = {rho} not in textbook band"


def test_air_density_inverse_T():
    """Higher T → lower density at same P."""
    assert air_density(300.0) > air_density(400.0)
    assert air_density(400.0) > air_density(500.0)


def test_air_density_pressure_scaling():
    """ρ ∝ P at fixed T (ideal gas)."""
    r1 = air_density(300.0, P_Pa=101325.0)
    r2 = air_density(300.0, P_Pa=2 * 101325.0)
    assert abs(r2 / r1 - 2.0) < 1e-6


def test_air_density_array_input():
    """Vectorized over T_K array."""
    Ts = np.array([300.0, 400.0, 500.0])
    rhos = air_density(Ts)
    assert rhos.shape == (3,)
    assert np.all(rhos > 0) and np.all(np.diff(rhos) < 0)


def test_air_viscosity_monotonic_increase_with_T():
    """Sutherland: μ_air increases with T."""
    assert air_viscosity(250.0) < air_viscosity(300.0) < air_viscosity(400.0)


def test_air_viscosity_at_300K_band():
    """μ_air(300K) ≈ 1.85e-5 Pa·s (textbook)."""
    mu = air_viscosity(300.0)
    assert 1.80e-5 <= mu <= 1.90e-5


def test_air_cp_at_300K_band():
    """cp_air(300K) ≈ 1005-1010 J/(kg·K)."""
    cp = air_cp(300.0)
    assert 1000.0 <= cp <= 1020.0


# ─── Water properties ──────────────────────────────────────────────


def test_water_density_at_293K_band():
    """ρ_water(20 °C) ≈ 998 kg/m³."""
    rho = water_density(293.15)
    assert 996.0 <= rho <= 1000.0


def test_water_viscosity_at_293K_band():
    """μ_water(20 °C) ≈ 1.0e-3 Pa·s (Vogel form, NIST < 2 % over 0-90 °C)."""
    mu = water_viscosity(293.15)
    assert 0.95e-3 <= mu <= 1.05e-3


def test_water_viscosity_decreases_with_T():
    """μ_water decreases with T (Vogel)."""
    assert water_viscosity(280.0) > water_viscosity(320.0) > water_viscosity(360.0)


def test_water_cp_constant():
    """cp_water ≈ 4182 over 280-370 K."""
    assert water_cp(290.0) == pytest.approx(4182.0)
    assert water_cp(350.0) == pytest.approx(4182.0)


def test_water_conductivity_increases_with_T():
    """k_water increases linearly with T over 0-90 °C."""
    assert water_conductivity(300.0) < water_conductivity(340.0)


# ─── Nu correlations ───────────────────────────────────────────────


def test_nu_water_gyroid_yan6_form():
    """Nu = 0.471 · Re^0.627 · Pr^(1/3)."""
    Re, Pr = 1000.0, 7.0
    nu = nu_water_gyroid_yan6(Re, Pr)
    expected = 0.471 * Re ** 0.627 * Pr ** (1.0 / 3.0)
    assert nu == pytest.approx(expected, rel=1e-6)


def test_nu_water_gyroid_yan6_monotonic_in_Re():
    """Higher Re → higher Nu at fixed Pr."""
    assert nu_water_gyroid_yan6(500.0, 7.0) < nu_water_gyroid_yan6(2000.0, 7.0)


# ─── Geometry ──────────────────────────────────────────────────────


def test_geometry_diamond_returns_expected_keys():
    """geometry must return these keys for solvers + projection."""
    g = geometry('Diamond', 6.0, 0.4, 16.0)
    expected = {'epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h', 'K_ss'}
    assert expected.issubset(set(g.keys()))


def test_geometry_epsilon_A_B_split_evenly():
    """For sheet HX, epsilon_A == epsilon_B == epsilon / 2."""
    g = geometry('Diamond', 6.0, 0.4, 16.0)
    assert g['epsilon_A'] == pytest.approx(g['epsilon'] / 2.0, rel=1e-6)
    assert g['epsilon_B'] == pytest.approx(g['epsilon'] / 2.0, rel=1e-6)


def test_geometry_thicker_walls_lower_epsilon():
    """Increasing t at fixed L decreases porosity (more solid)."""
    g_thin = geometry('Diamond', 6.0, 0.3, 16.0)
    g_thick = geometry('Diamond', 6.0, 0.5, 16.0)
    assert g_thick['epsilon'] < g_thin['epsilon']


def test_geometry_K_ss_scales_with_k_s():
    """K_ss = chi * (1 - eps) * k_s — proportional to k_s."""
    g1 = geometry('Diamond', 6.0, 0.4, 16.0)
    g2 = geometry('Diamond', 6.0, 0.4, 32.0)
    assert g2['K_ss'] == pytest.approx(2.0 * g1['K_ss'], rel=1e-6)


# ─── Adaptive grid ─────────────────────────────────────────────────


def test_adaptive_grid_returns_tuple_of_two_ints():
    Nx, Ny = adaptive_grid(0.1, 0.05, 0.001, alpha=0.4)
    assert isinstance(Nx, int) and isinstance(Ny, int)
    assert Nx > 0 and Ny > 0


def test_adaptive_grid_finer_alpha_more_cells():
    """Smaller alpha (finer dx/D_h target) → more cells."""
    Nx_coarse, _ = adaptive_grid(0.1, 0.05, 0.001, alpha=0.8)
    Nx_fine, _ = adaptive_grid(0.1, 0.05, 0.001, alpha=0.2)
    assert Nx_fine > Nx_coarse


# ─── compute(): production entrypoint ──────────────────────────────


def test_compute_returns_geometry_keys_plus_more():
    """compute()'s output is a superset of geometry()'s keys."""
    res = compute('Diamond', 6.0, 0.4, 5.0, 350.0, 101325.0, 16.0)
    g_keys = set(geometry('Diamond', 6.0, 0.4, 16.0).keys())
    res_keys = set(res.keys())
    assert g_keys.issubset(res_keys)
    # Production-required keys
    assert {'Re', 'Nu', 'H_sf', 'K_ff'} <= res_keys


def test_compute_caches_repeated_call():
    """Repeated identical calls hit the cache — but return DISTINCT dict
    objects (W7, 2026-07-07: hits return a shallow copy so a caller
    mutating its result cannot poison later hits; the old `a is b`
    identity was exactly that hazard)."""
    compute.cache_clear()
    a = compute('Diamond', 6.0, 0.4, 5.0, 350.0, 101325.0, 16.0)
    misses_after_first = compute.cache_info().misses
    b = compute('Diamond', 6.0, 0.4, 5.0, 350.0, 101325.0, 16.0)
    assert compute.cache_info().misses == misses_after_first  # cache HIT
    assert compute.cache_info().hits >= 1
    assert a is not b          # poison guard: copies, not the same object
    assert a == b              # same values


# ─── N5: compute() Re-range warning must be fluid-aware (audit 2026-06-28) ──
def test_compute_water_in_range_no_air_window_warning():
    """Water at Re=20551 (u=5) is INSIDE the water window (100,50000) but
    OUTSIDE the air window (400,16000). The compute()-level Re warning must use
    the water window, so no spurious 'outside the validated range [400, 16000]'.
    """
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        compute('Diamond', 6.0, 0.4, 5.0, 320.0, 300000.0, 16.0,
                fluid_type='water')
    assert not any('[400, 16000]' in str(x.message) for x in w), \
        'water case mis-warned against the AIR Re window'


def test_compute_air_out_of_range_still_warns():
    """Regression: air at Re=57 (u=0.5) is below the air window (400,16000) and
    must still warn — the fluid-aware fix keeps air behaviour identical."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        compute('Diamond', 6.0, 0.4, 0.5, 355.0, 101325.0, 16.0,
                fluid_type='air')
    assert any('outside the validated range' in str(x.message) for x in w)


# ─── Fluid type parsing ────────────────────────────────────────────


def test_parse_fluid_type_air():
    class FakeCombo:
        def currentText(self): return 'Air'
    assert parse_fluid_type(FakeCombo()) == 'air'


def test_validate_fluid_type_unknown_raises():
    with pytest.raises((NotImplementedError, ValueError)):
        validate_fluid_type('helium', 'A')
