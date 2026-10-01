"""Current refined-grid and 2D streamwise drag projection contracts."""
from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.models.grid import build_master_refined_grid
from sjtu_tpmshx.models.df_projection import project_fields_to_streamwise_K_cF


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
    K_a, cF_a = project_fields_to_streamwise_K_cF(L_field, t_field, 'Diamond', 16.0, Ny_sim=12, direction=0)
    K_b, cF_b = project_fields_to_streamwise_K_cF(L_field, t_field, 'Diamond', 16.0, Ny_sim=12, direction=3)
    assert K_a.shape == (12,) and cF_a.shape == (12,)
    assert K_b.shape == (12,) and cF_b.shape == (12,)
    assert K_a.dtype == np.float64
    assert cF_a.dtype == np.float64


def test_project_fields_uniform_input_returns_uniform_output():
    """Uniform L and t must give uniform K under the current geometry model."""
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    K_a, _ = project_fields_to_streamwise_K_cF(L_field, t_field, 'Diamond', 16.0, Ny_sim=8, direction=0)
    rel_var = (K_a.max() - K_a.min()) / max(abs(K_a.mean()), 1e-30)
    assert rel_var < 0.05, f"K should be ~uniform; got rel_var={rel_var}"


def test_project_fields_invalid_direction_raises():
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    with pytest.raises(ValueError):
        project_fields_to_streamwise_K_cF(L_field, t_field, 'Diamond', 16.0, Ny_sim=8, direction=4)
