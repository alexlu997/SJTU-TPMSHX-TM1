"""z-reflection symmetry of the conservative 3D LTNE solver.

A fully z-symmetric cross-flow setup (air +x, water -y, full-face inlets,
uniform geometry) has NO z-direction driver, so the temperature field must be
z-symmetric (mirror-invariant about the z mid-plane). The conservative
(strict-conservation) kernel currently violates this: a realistic SIMPLE
velocity field drives the conservative Gauss-Seidel into a non-converged,
z-asymmetric stalled state (~30% of range), which the Q-based early-exit then
locks in. Root cause + full diagnostic chain: 2026-06-09 systematic-debug.

This test pins the symmetry the physics requires; it is RED until the
conservative-scheme convergence defect is fixed.
"""

import numpy as np
import pytest
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.pipelines.stages_3d import _run_3d_stack


def _z_mirror_asym_pct(field):
    """max |T - flip_z(T)| as a percent of the field's range. 0 = z-symmetric."""
    a = np.asarray(field, dtype=float)
    rng = max(a.max() - a.min(), 1e-12)
    return 100.0 * np.abs(a - np.flip(a, axis=-1)).max() / rng


def _symmetric_crossflow_cfg(u_A):
    """Default-like Shanghai air-water cross-flow, z-symmetric by construction."""
    L, H, Lz = 0.182, 0.042, 0.042
    g = tpms_geometry('Gyroid', 7.0, 0.6, 16.0)
    return dict(
        L=L, H=H, Lz=Lz, Nx=16, Ny=10, Nz=8,
        u_A=u_A, u_B=0.133, T_inA=422.0, T_inB=300.0,
        P_inA=192362.0, P_inB=101973.0, T_s_init=300.0,
        Lcell=7.0, t_wall=0.6, k_s=16.0, tpms_type='Gyroid',
        eps=g['epsilon'], D_h=g['D_h'],
        fluid_A_cfg=dict(dir=0, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H,
                         in_z_ctr=Lz / 2, in_z_w=Lz, out_z_ctr=Lz / 2, out_z_w=Lz),
        fluid_B_cfg=dict(dir=3, in_ctr=L / 2, in_w=L, out_ctr=L / 2, out_w=L,
                         in_z_ctr=Lz / 2, in_z_w=Lz, out_z_ctr=Lz / 2, out_z_w=Lz),
        wall_refine_3d=False, zone_grid_cells=None,
        fluid_type_A='air', fluid_type_B='water',
    )


@pytest.mark.parametrize("u_A", [20.0, 2.0])
def test_conservative_ltne_z_symmetric(u_A):
    """Conservative 3D LTNE must keep T_A/T_s z-symmetric for a z-symmetric case."""
    res = _run_3d_stack(_symmetric_crossflow_cfg(u_A))
    asym_Ta = _z_mirror_asym_pct(res['Ta'])
    asym_Ts = _z_mirror_asym_pct(res['Ts'])
    assert asym_Ta < 2.0, (
        f"T_A z-asymmetry {asym_Ta:.2f}% (u_A={u_A}) — z-symmetric setup must "
        f"yield a z-symmetric field; conservative kernel broke it.")
    assert asym_Ts < 2.0, f"T_s z-asymmetry {asym_Ts:.2f}% (u_A={u_A})"


def test_conservative_kernel_zsym_minimal():
    """Direct-kernel minimal repro: z-even axial-only flow must give z-even T."""
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d

    Nx, Ny, Nz = 16, 10, 8
    L, H, D = 0.182, 0.042, 0.042
    dx = np.full(Nx, L / Nx); dy = np.full(Ny, H / Ny); dz = np.full(Nz, D / Nz)
    one = np.ones((Nx, Ny, Nz))
    # Exactly-z-even axial velocity varying in x (accel) AND z (BL); no v, no w.
    zprof = 1.0 - 0.4 * ((2.0 * np.arange(Nz) / (Nz - 1)) - 1.0) ** 2   # z-even
    xr_c = 1.0 + 0.8 * (np.arange(Nx) / (Nx - 1))
    xr_f = 1.0 + 0.8 * (np.arange(Nx + 1) / Nx)
    u_A = 30.0
    ucA = u_A * xr_c[:, None, None] * zprof[None, None, :] * one
    ufA = u_A * xr_f[:, None, None] * zprof[None, None, :] * np.ones((Nx + 1, Ny, Nz))
    Z = np.zeros((Nx, Ny, Nz))
    out = solve_full_domain_3d(
        L, H, D, Nx, Ny, Nz, 400.0, 300.0,
        0.05 * one, 0.6 * one, 8.0 * one, 1e4 * one, 1e4 * one,
        1.2 * 1005.0 * one, 998.0 * 4182.0 * one, 0.5 * one,
        ucA, Z, Z, Z, Z, Z, 0, 3,
        dx_arr=dx, dy_arr=dy, dz_arr=dz,
        ufA=ufA, vfA=np.zeros((Nx, Ny + 1, Nz)), wfA=np.zeros((Nx, Ny, Nz + 1)),
        ufB=np.zeros((Nx + 1, Ny, Nz)), vfB=np.zeros((Nx, Ny + 1, Nz)),
        wfB=np.zeros((Nx, Ny, Nz + 1)),
        eps_A=0.25 * one, eps_B=0.25 * one,
        Tb_prescribed=None, max_iter=40000, tol=1e-10,
        q_rel_tol=1e-30, conv_chunk=4000,
        conservative_ltne=True, return_info=True)
    Ta = out[0]
    asym = _z_mirror_asym_pct(Ta)
    assert asym < 1.0, (
        f"z-even axial-only flow gave {asym:.2f}% z-asymmetric T_A — the "
        f"conservative kernel must preserve z-symmetry.")
