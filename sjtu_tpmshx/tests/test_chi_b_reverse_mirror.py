"""Ground-truth: the per-cell χ_B participation field must obey the same
approach-(a) reverse convention as the velocity transforms.

Under approach-(a) the reverse-dir (-stream) velocity field is the spatial
y-mirror of the forward (+stream) field (with the stream component negated).
`_build_chi_B_mass_flux_threshold` derives χ_B from the SOLVER-coord mass-flux
and maps it to real coords. The solver is direction-agnostic, so forward and
reverse produce IDENTICAL solver-coord χ; the real-coord χ for the reverse case
must therefore be the forward χ spatially mirrored along the real stream axis —
otherwise χ would suppress h_vB/K_ffB in the WRONG half of a reverse-dir
partial-B run (mirror of the actual flow corridor).

This isolates the reverse handling in the mass-flux χ_B builder. A unit test on
the helper (no full solve) keeps it fast and deterministic.
"""
from types import SimpleNamespace
import numpy as np

from sjtu_tpmshx.models.field_coordinates_3d import _build_chi_B_mass_flux_threshold


def _fake_solver(Nx, Ny, Nz):
    """Minimal SIMPLE3D-like object with an asymmetric (in y) v-flux so the
    resulting χ field is genuinely non-symmetric along the stream axis."""
    rho = np.ones((Nx, Ny, Nz), dtype=np.float64)
    u = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
    w = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)
    # v staggered on solver y (the stream): strong flux on the first half of
    # the stream, zero on the second half -> χ active only on cells y<Ny//2.
    v = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
    v[:, : Ny // 2 + 1, :] = 10.0
    return SimpleNamespace(
        u=u, v=v, w=w, rho_field=rho,
        dx=np.ones(Nx), dy=np.ones(Ny), dz=np.ones(Nz),
    )


def _axis_map(is_reverse):
    # dir 2/3: solver axes map straight to real (perm identity); stream is y.
    return {
        'solver_to_real_perm': (0, 1, 2),
        'stream_real_axis': 1,
        'cross1_real_axis': 0,
        'cross2_real_axis': 2,
        'is_reverse': is_reverse,
    }


def test_mass_flux_chi_reverse_is_y_mirror_of_forward():
    Nx, Ny, Nz = 4, 6, 4
    shape = (Nx, Ny, Nz)
    sB = _fake_solver(Nx, Ny, Nz)
    # n_dilate=n_smooth=0 keeps the asymmetry crisp (dilation/smoothing are
    # symmetric and would partially mask a missing flip).
    kw = dict(threshold_frac=0.05, n_dilate=0, n_smooth=0, ref_mode='p75')

    chi_fwd = _build_chi_B_mass_flux_threshold(sB, _axis_map(False), shape, **kw)
    chi_rev = _build_chi_B_mass_flux_threshold(sB, _axis_map(True), shape, **kw)

    # Sanity: the field must actually be asymmetric in y, else the test is
    # vacuous (a symmetric field is trivially its own mirror).
    assert not np.allclose(chi_fwd, chi_fwd[:, ::-1, :]), \
        "test fixture degenerate: χ_fwd is y-symmetric, cannot detect a flip"

    assert np.allclose(chi_rev, chi_fwd[:, ::-1, :]), (
        "reverse-dir χ_B is NOT the y-mirror of forward χ_B: the mass-flux "
        "builder transposes solver->real without the approach-(a) stream-axis "
        "flip, so χ marks the mirror of the real flow corridor.\n"
        f"chi_fwd[:,active,:] y-profile = {chi_fwd[0, :, 0]}\n"
        f"chi_rev[:,active,:] y-profile = {chi_rev[0, :, 0]}"
    )
