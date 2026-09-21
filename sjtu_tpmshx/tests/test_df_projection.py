"""Sanity tests for solvers.df_projection — extract_dP + grid build.

Covers:
  * extract_dP_from_simple from a faked SIMPLE state
  * extract_dP_mass_flux_from_simple weighting + zero-mass fallback
  * build_master_refined_grid returns sensible Nx_refined / Ny_refined
  * project_fields_to_streamwise_K_cF: shape, dtype, monotonicity-in-eps_f

We use a dataclass-style fake `s` instead of building a full SIMPLESolver
because the public interface is just .P, .v, .rho_field, .inlet_frac, .outlet_frac.
"""
from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.solvers.df_projection import extract_dP_from_simple, extract_dP_mass_flux_from_simple
from sjtu_tpmshx.models.grid import build_master_refined_grid
from sjtu_tpmshx.models.df_projection import project_fields_to_streamwise_K_cF


class _FakeSim:
    """Minimal duck-typed SIMPLE-like instance for extract_dP tests."""
    def __init__(self, Nx=8, Ny=10, P_in=1.0e5, P_out=9.5e4):
        self.P = np.empty((Nx, Ny), dtype=np.float64)
        self.P[:, 0] = P_in
        self.P[:, -1] = P_out
        self.P[:, 1:-1] = np.linspace(P_in, P_out, Ny - 2)[None, :]
        self.v = np.full((Nx, Ny + 1), 2.5, dtype=np.float64)
        self.rho_field = np.full((Nx, Ny), 1.0, dtype=np.float64)
        self.inlet_frac = np.ones(Nx, dtype=np.float64)
        self.outlet_frac = np.ones(Nx, dtype=np.float64)


# ─── extract_dP_from_simple ────────────────────────────────────────


def test_extract_dP_uniform_inlet_outlet_returns_difference():
    s = _FakeSim(P_in=1.0e5, P_out=9.5e4)
    dP = extract_dP_from_simple(s)
    assert dP == pytest.approx(5.0e3, rel=1e-6)


def test_extract_dP_partial_inlet_only_uses_inlet_cells():
    s = _FakeSim(Nx=10)
    s.inlet_frac = np.zeros(10)
    s.inlet_frac[2:8] = 1.0
    s.P[0:2, 0] = 1.5e5     # tampered "wall" cells should be excluded
    s.P[8:10, 0] = 1.5e5
    dP = extract_dP_from_simple(s)
    # Should ignore the high-P wall cells and return ~5000 Pa
    assert 4_000.0 < dP < 6_000.0


def test_extract_dP_zero_inlet_returns_zero():
    s = _FakeSim(Nx=8)
    s.inlet_frac = np.zeros(8)
    dP = extract_dP_from_simple(s)
    assert dP == 0.0


# ─── extract_dP_mass_flux_from_simple ──────────────────────────────


def test_extract_dP_mass_flux_falls_back_to_geom_when_v_zero():
    """When v is zero (cold start), should not divide-by-zero."""
    s = _FakeSim()
    s.v = np.zeros_like(s.v)
    dP_mf = extract_dP_mass_flux_from_simple(s)
    dP_geom = extract_dP_from_simple(s)
    assert dP_mf == pytest.approx(dP_geom, rel=1e-6)


def test_extract_dP_mass_flux_matches_geom_for_uniform_v():
    """Uniform v, uniform ρ → mass-flux weighted == geometric weighted."""
    s = _FakeSim()
    dP_mf = extract_dP_mass_flux_from_simple(s)
    dP_geom = extract_dP_from_simple(s)
    assert dP_mf == pytest.approx(dP_geom, rel=1e-6)


def test_extract_dP_mass_flux_skews_toward_high_v_cells():
    """If v is concentrated in some cells, dP_mf weights those cells more.
    Build a P field where high-v cells have a different inlet pressure."""
    s = _FakeSim(Nx=10, P_in=1.0e5, P_out=9.5e4)
    # Put higher pressure at low-v cells; high-v cells stay at P_in baseline
    s.P[0:5, 0] = 1.05e5
    s.P[5:10, 0] = 1.0e5
    s.v[:, 0] = 0.1
    s.v[5:10, 0] = 5.0   # high-flux cells dominate mass weighting
    dP_mf = extract_dP_mass_flux_from_simple(s)
    dP_geom = extract_dP_from_simple(s)
    # Geometric (open-area) average: roughly ((1.05+1.0)/2)e5 - 0.95e5 ≈ 7500
    # Mass-flux weighted: dominated by high-v half: 1.0e5 - 0.95e5 = 5000
    assert dP_mf < dP_geom


# ─── build_master_refined_grid ────────────────────────────────────


def test_build_master_refined_grid_returns_4_tuple():
    res = build_master_refined_grid(0.1, 0.05, 20, 10)
    assert len(res) == 4
    dx, dy, Nxr, Nyr = res
    assert isinstance(Nxr, int) and isinstance(Nyr, int)
    assert dx.ndim == 1 and dy.ndim == 1
    assert Nxr == dx.size and Nyr == dy.size


def test_build_master_refined_grid_sums_to_domain():
    """∑ dx ≈ L_dom, ∑ dy ≈ H_dom (within numeric tolerance)."""
    L_dom, H_dom = 0.182, 0.042
    dx, dy, Nxr, Nyr = build_master_refined_grid(L_dom, H_dom, 20, 10)
    assert dx.sum() == pytest.approx(L_dom, rel=1e-6)
    assert dy.sum() == pytest.approx(H_dom, rel=1e-6)


def test_build_master_refined_grid_bl_smaller_than_bulk():
    """First (BL) cells should be smaller than middle (bulk) cells."""
    dx, dy, _, _ = build_master_refined_grid(0.1, 0.05, 30, 15, n_refine=8)
    assert dx[0] < dx[len(dx) // 2]
    assert dy[0] < dy[len(dy) // 2]


# ─── project_fields_to_streamwise_K_cF ─────────────────────────────


def test_project_fields_returns_correct_shape():
    """K_arr / cF_arr must have shape (Ny_sim,) for both fluid sides."""
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    K_a, cF_a = project_fields_to_streamwise_K_cF(
        L_field, t_field, 'Diamond', 16.0, Nx, Ny, Ny_sim=12, fluid='A')
    K_b, cF_b = project_fields_to_streamwise_K_cF(
        L_field, t_field, 'Diamond', 16.0, Nx, Ny, Ny_sim=12, fluid='B')
    assert K_a.shape == (12,) and cF_a.shape == (12,)
    assert K_b.shape == (12,) and cF_b.shape == (12,)
    assert K_a.dtype == np.float64
    assert cF_a.dtype == np.float64


def test_project_fields_uniform_input_returns_uniform_output():
    """Uniform L and t must give uniform K under the current geometry model."""
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    K_a, _ = project_fields_to_streamwise_K_cF(
        L_field, t_field, 'Diamond', 16.0, Nx, Ny, Ny_sim=8, fluid='A')
    rel_var = (K_a.max() - K_a.min()) / max(abs(K_a.mean()), 1e-30)
    assert rel_var < 0.05, f"K should be ~uniform; got rel_var={rel_var}"


def test_project_fields_invalid_fluid_raises():
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    with pytest.raises(ValueError):
        project_fields_to_streamwise_K_cF(
            L_field, t_field, 'Diamond', 16.0, Nx, Ny,
            Ny_sim=8, fluid='C')
