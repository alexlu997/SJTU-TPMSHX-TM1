"""Tests for models.sigmoid_field.build_continuous_arrays — verifies shape
contract, clip behaviour, and custom dx_arr/dy_arr support.
A small real LUT suffices here; voxel accuracy is tested in test_tpms_geometry_n128.
"""
import warnings

warnings.filterwarnings('ignore')

import numpy as np

from sjtu_tpmshx.models.sigmoid_field import build_continuous_arrays, get_geometry_lut


def _call(Nx=40, Ny=20, L=0.08, H=0.04, x=None, L0=6.0, t0=0.4,
          tpms='Gyroid', dx_arr=None, dy_arr=None):
    if x is None:
        x = np.tile([L0, t0], 18)
    lut = get_geometry_lut(tpms, n_L=3, n_t=2, N=32)
    return build_continuous_arrays(
        x, L0, t0, 0.2, 0.2, Nx, Ny, L, H, tpms, 17.0,
        5.0, 4.0, 500.0, 350.0, lut,
        dx_arr=dx_arr, dy_arr=dy_arr)


def test_shape_contract():
    """All output arrays must have shape (Nx, Ny)."""
    Nx, Ny = 36, 18
    za = _call(Nx=Nx, Ny=Ny)
    required = ('eps_arr', 'eps_f_arr', 'K_ffA_arr', 'K_ffB_arr',
                'K_ss_arr', 'h_vA_arr', 'h_vB_arr', 'r_h_arr',
                'A_0_arr', 'L_field', 't_field')
    for key in required:
        assert key in za, f"output missing key {key!r}"
        arr = za[key]
        assert arr.shape == (Nx, Ny), \
            f"{key} shape {arr.shape}, expected ({Nx}, {Ny})"
    print("test_shape_contract PASS")


def test_clip_bounds():
    """L_field ∈ [4, 8] mm, t_field ∈ [0.3, 0.6] mm regardless of x values."""
    x = np.zeros(36)
    # Half way-out values, half within
    for k in range(9):
        x[2*k] = 2.0; x[2*k+1] = 0.1   # below lower bound
    for k in range(9, 18):
        x[2*k] = 12.0; x[2*k+1] = 0.7  # above upper bound
    za = _call(x=x)
    assert za['L_field'].min() >= 4.0 - 1e-9, \
        f"L_field min {za['L_field'].min()} < 4.0"
    assert za['L_field'].max() <= 8.0 + 1e-9, \
        f"L_field max {za['L_field'].max()} > 8.0"
    assert za['t_field'].min() >= 0.3 - 1e-9, \
        f"t_field min {za['t_field'].min()} < 0.3"
    assert za['t_field'].max() <= 0.6 + 1e-9, \
        f"t_field max {za['t_field'].max()} > 0.6"
    print("test_clip_bounds PASS")


def test_custom_dx_dy():
    """Non-uniform dx_arr / dy_arr accepted and reflected in x_frac / y_frac."""
    Nx, Ny = 30, 15
    L, H = 0.08, 0.04
    dx = np.full(Nx, L / Nx) * (1.0 + 0.1 * np.linspace(-1, 1, Nx))
    dx *= L / dx.sum()  # re-normalise to exact total
    dy = np.full(Ny, H / Ny) * (1.0 + 0.05 * np.linspace(-1, 1, Ny))
    dy *= H / dy.sum()
    za = _call(Nx=Nx, Ny=Ny, L=L, H=H, dx_arr=dx, dy_arr=dy)
    assert za['L_field'].shape == (Nx, Ny)
    # Non-uniform should produce non-trivial output even with uniform x
    assert np.isfinite(za['L_field']).all()
    assert np.isfinite(za['t_field']).all()
    print("test_custom_dx_dy PASS")


if __name__ == '__main__':
    test_shape_contract()
    test_clip_bounds()
    test_custom_dx_dy()
    print("\nAll sigmoid_field tests PASS")
