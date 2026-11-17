"""Current refined-grid and 2D streamwise drag projection contracts."""
from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.shared.models.grid import build_master_refined_grid
from sjtu_tpmshx.shared.models._native_df import project_rows


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


# Row projection is checked separately from complete native preparation.


def test_project_fields_returns_correct_shape():
    """Projected L/t arrays keep the requested row count for both directions."""
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    for direction in (0, 3):
        cells, walls, _ = project_rows(L_field, t_field, 12, direction)
        assert cells.shape == walls.shape == (12,)
        assert cells.dtype == walls.dtype == np.float64


def test_project_fields_uniform_input_returns_uniform_output():
    """Uniform L/t values remain uniform across projected rows."""
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    cells, walls, _ = project_rows(L_field, t_field, 8, 0)
    np.testing.assert_array_equal(cells, np.full(8, 6.))
    np.testing.assert_allclose(walls, np.full(8, .4), rtol=1e-15, atol=0.)


def test_project_fields_invalid_direction_raises():
    Nx, Ny = 20, 10
    L_field = np.full((Nx, Ny), 6.0)
    t_field = np.full((Nx, Ny), 0.4)
    with pytest.raises(ValueError):
        project_rows(L_field, t_field, 8, 4)
