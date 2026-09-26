"""
tests/test_sigmoid_field_3d.py — Phase 1 Week 3 sigmoid 3D verification

Four tests:
  1. test_output_shapes      — all returned arrays (Nx, Ny, Nz)
  2. test_clip_bounds        — extreme x → L, t strictly in clip range
  3. test_zone_count         — 108 vector 放出 3×3×3 zones (non-zero ranges)
  4. test_z_uniform_degrade  — 108 with z-invariant values degrades to 2D

A small real LUT suffices here; voxel accuracy is tested in test_tpms_geometry_n128.
"""

import numpy as np

from sjtu_tpmshx.models.sigmoid_field import get_geometry_lut, build_continuous_arrays
from sjtu_tpmshx.solvers.sigmoid_field_3d import build_continuous_arrays_3d


def _common_kwargs():
    return dict(
        y_trans_inlet=0.2, y_trans_outlet=0.2,
        L_domain=0.10, H_domain=0.05, D_domain=0.02,
        tpms_type='Diamond', k_s=17.0,
        u_A=10.0, u_B=10.0, T_inA=400.0, T_inB=300.0,
    )


def test_output_shapes():
    lut = get_geometry_lut('Diamond', n_L=3, n_t=2, N=32)
    Nx, Ny, Nz = 12, 10, 6
    x = np.array([6.0, 0.3] * 54)
    out = build_continuous_arrays_3d(x, 6.0, 0.3,
                                      Nx=Nx, Ny=Ny, Nz=Nz,
                                      lut=lut, **_common_kwargs())
    expected = (Nx, Ny, Nz)
    for key in ('eps_arr', 'eps_f_arr', 'K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
                'h_vA_arr', 'h_vB_arr', 'r_h_arr', 'A_0_arr', 'L_field', 't_field'):
        assert out[key].shape == expected, f"{key} shape {out[key].shape} != {expected}"
    assert out['zone_id'].shape == expected
    assert out['axis'] == 'continuous_3d'
    print("test_output_shapes PASS")


def test_clip_bounds():
    lut = get_geometry_lut('Diamond', n_L=3, n_t=2, N=32)
    Nx, Ny, Nz = 10, 10, 6
    # Extreme: all inlets L=20 (above 8), all outlets L=1 (below 4); t similarly pushed out
    x = np.empty(108, dtype=np.float64)
    for i in range(54):
        if i % 2 == 0:  # L
            x[i] = 20.0
            x[54 + i] = 1.0
        else:  # t
            x[i] = 1.0
            x[54 + i] = 0.05
    out = build_continuous_arrays_3d(x, 6.0, 0.3,
                                      Nx=Nx, Ny=Ny, Nz=Nz,
                                      lut=lut, **_common_kwargs())
    L = out['L_field']; t = out['t_field']
    assert L.min() >= 4.0 - 1e-12, f"L min {L.min()} < 4"
    assert L.max() <= 8.0 + 1e-12, f"L max {L.max()} > 8"
    assert t.min() >= 0.3 - 1e-12, f"t min {t.min()} < 0.3"
    assert t.max() <= 0.6 + 1e-12, f"t max {t.max()} > 0.6"
    print(f"test_clip_bounds PASS (L [{L.min():.3f}, {L.max():.3f}] "
          f"t [{t.min():.3f}, {t.max():.3f}])")


def test_zone_count():
    """108-vec producing a distinguishable inlet vs outlet region."""
    lut = get_geometry_lut('Diamond', n_L=3, n_t=2, N=32)
    Nx, Ny, Nz = 20, 30, 10
    x = np.array([6.0, 0.3] * 54)
    # Inlet all to L=5, t=0.4
    for i in range(27):
        x[2*i] = 5.0; x[2*i + 1] = 0.4
    # Outlet all to L=7, t=0.35
    for i in range(27):
        x[54 + 2*i] = 7.0; x[54 + 2*i + 1] = 0.35

    out = build_continuous_arrays_3d(x, 6.0, 0.3,
                                      Nx=Nx, Ny=Ny, Nz=Nz,
                                      lut=lut, **_common_kwargs())
    L = out['L_field']
    # y=0 (inlet) should have L ~5; y=Ny-1 (outlet) should have L ~7
    L_in = L[:, 0, :].mean()
    L_out = L[:, -1, :].mean()
    print(f"  L inlet mean {L_in:.3f}, outlet mean {L_out:.3f}")
    assert abs(L_in - 5.0) < 0.2, f"inlet L mean {L_in} far from 5"
    assert abs(L_out - 7.0) < 0.2, f"outlet L mean {L_out} far from 7"
    print("test_zone_count PASS")


def test_z_uniform_degrade():
    """108-vec with same values across z axis → field equal to 2D result."""
    lut = get_geometry_lut('Diamond', n_L=3, n_t=2, N=32)
    Nx, Ny, Nz = 15, 12, 5

    # Build 2D 36-vec: uniform random-ish values
    rng = np.random.default_rng(42)
    x2d = np.empty(36, dtype=np.float64)
    for zone in range(18):
        x2d[2*zone] = 4.5 + rng.random() * 3.0   # L in [4.5, 7.5]
        x2d[2*zone + 1] = 0.32 + rng.random() * 0.15  # t in [0.32, 0.47]

    # Build 108-vec with SAME 36-values replicated across iz
    # 2D layout: idx = (iy * 3 + ix) * 2 + (0/1)  inlet
    #            idx = 18 + (iy * 3 + ix) * 2 + (0/1)  outlet
    # 3D layout: flat = 9*iy + 3*ix + iz; inlet offset=0, outlet=54
    x3d = np.empty(108, dtype=np.float64)
    for iy in range(3):
        for ix in range(3):
            idx2_in = (iy * 3 + ix) * 2
            idx2_out = 18 + (iy * 3 + ix) * 2
            for iz in range(3):
                flat = 9*iy + 3*ix + iz
                x3d[2*flat]       = x2d[idx2_in]       # L inlet
                x3d[2*flat + 1]   = x2d[idx2_in + 1]   # t inlet
                x3d[54 + 2*flat]     = x2d[idx2_out]
                x3d[54 + 2*flat + 1] = x2d[idx2_out + 1]

    out3 = build_continuous_arrays_3d(x3d, 6.0, 0.3,
                                       Nx=Nx, Ny=Ny, Nz=Nz,
                                       lut=lut, **_common_kwargs())
    ck = {k: v for k, v in _common_kwargs().items() if k != 'D_domain'}
    out2 = build_continuous_arrays(x2d, 6.0, 0.3, 0.2, 0.2,
                                    Nx=Nx, Ny=Ny,
                                    L_domain=ck['L_domain'], H_domain=ck['H_domain'],
                                    tpms_type=ck['tpms_type'], k_s=ck['k_s'],
                                    u_A=ck['u_A'], u_B=ck['u_B'],
                                    T_inA=ck['T_inA'], T_inB=ck['T_inB'],
                                    lut=lut)

    # Compare 3D mean-over-z vs 2D (should be close; tensor-product blend introduces
    # small z-direction smoothing where iz=0 and iz=2 control points differ — but
    # here they're all equal across iz, so z-variation within a zone should be ≈ 0).
    L3 = out3['L_field']; L2 = out2['L_field']
    max_z_var = np.max(np.std(L3, axis=2))
    print(f"  max z-std of L_field: {max_z_var:.4e}")
    assert max_z_var < 5e-2, f"z-direction L drift {max_z_var}"
    L3_avg = L3.mean(axis=2)
    diff = np.max(np.abs(L3_avg - L2))
    print(f"  max |L3_avg - L2|: {diff:.4e}")
    assert diff < 5e-2, f"L3_avg vs L2 diff {diff}"
    print("test_z_uniform_degrade PASS")


if __name__ == '__main__':
    test_output_shapes()
    test_clip_bounds()
    test_zone_count()
    test_z_uniform_degrade()
    print("\nAll sigmoid_field_3d tests PASS")
