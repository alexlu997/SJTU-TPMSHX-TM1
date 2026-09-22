"""Explicit tiny compilation checks for all supported 3D LTNE kernels."""
import numpy as np
from sjtu_tpmshx.solvers._kernels_ltne_3d import (
    _gs_full_chunk_3d, _gs_full_chunk_3d_stag, _gs_full_chunk_3d_stag_rb,
)


def compile_routes():
    Nx = Ny = Nz = 4
    Ta = np.full((Nx, Ny, Nz), 300.0)
    Tb = np.full((Nx, Ny, Nz), 290.0)
    Ts = np.full((Nx, Ny, Nz), 295.0)
    dx = np.full(Nx, 0.01); dy = np.full(Ny, 0.01); dz = np.full(Nz, 0.01)
    K = np.full((Nx, Ny, Nz), 0.1); hv = np.full((Nx, Ny, Nz), 100.0)
    ef = np.full((Nx, Ny, Nz), 0.5); rcp = np.full((Nx, Ny, Nz), 1000.0)
    uc = np.full((Nx, Ny, Nz), 0.5); v0 = np.zeros((Nx, Ny, Nz))
    TinA = np.full((Ny, Nz), 300.0); TinB = np.full((Nx, Nz), 290.0)
    fA = np.ones((Ny, Nz)); fB = np.ones((Nx, Nz))
    mms = np.zeros((Nx, Ny, Nz))
    # staggered face velocities for the conservative default path
    ufA = np.full((Nx + 1, Ny, Nz), 0.5)
    vfA = np.zeros((Nx, Ny + 1, Nz)); wfA = np.zeros((Nx, Ny, Nz + 1))
    ufB = np.full((Nx + 1, Ny, Nz), 0.5)
    vfB = np.zeros((Nx, Ny + 1, Nz)); wfB = np.zeros((Nx, Ny, Nz + 1))
    # legacy cell-centered kernel (force_cc_ltne fallback path)
    _gs_full_chunk_3d(
        Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz, dx, dy, dz,
        K, K, K, hv, hv, ef, ef, rcp, rcp,
        uc, v0, v0, uc, v0, v0,
        0, 3, TinA, TinB, fA, fB, 1, 0, 0.7, 0.7, 0.7)
    # default-path staggered kernels (serial + red-black), conservative form
    for _stag in (_gs_full_chunk_3d_stag, _gs_full_chunk_3d_stag_rb):
        _stag(
            Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz, dx, dy, dz,
            K, K, K, hv, hv, ef, ef, rcp, rcp,
            ufA, vfA, wfA, ufB, vfB, wfB,
            0, 3, TinA, TinB, fA, fB, 1, 0, 0.7, 0.7, 0.7,
            mms, mms, mms, 1)
