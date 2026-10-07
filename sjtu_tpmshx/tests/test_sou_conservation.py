"""The 2D SOU deferred correction must be globally conservative.

Audit (2d-sou-not-conservative): _sou_corr_x/_y scaled each face's limiter by
the CELL-LOCAL convective flux Fx = eps_f*rho_cp*|u|*dy. At a shared interior
face the two neighbour cells then applied DIFFERENT flux magnitudes, so the
deferred correction did not telescope when the velocity / rho_cp varied between
neighbours — injecting spurious energy (0.25-2.35% of the interphase duty on a
compressible, non-uniform-velocity field). The fix uses a face-averaged flux
F_face = 0.5*(Fx_P + Fx_neighbour) so both cells apply the identical extra flux
and the sum over all cells telescopes to the (zero, limiter-clamped) boundary.
"""

import numpy as np
import pytest

from sjtu_tpmshx.solvers.ltne_energy import _sou_corr_x, _sou_corr_y


def _smooth_T(n):
    T = np.zeros((n, 1))
    for i in range(n):
        T[i, 0] = i + 0.1 * i * i        # monotone convex -> nonzero limiters
    return T


def test_sou_corr_x_telescopes_with_nonuniform_flux_uplus():
    Nx = 9
    T = _smooth_T(Nx)
    Fx = np.zeros((Nx, 1))
    for i in range(Nx):
        Fx[i, 0] = 1.0 + 0.4 * i          # non-uniform flux field
    total = sum(_sou_corr_x(T, i, 0, Nx, Fx) for i in range(Nx))
    assert abs(total) < 1e-9, f"x-SOU not conservative (sum={total})"


def test_sou_corr_x_telescopes_with_nonuniform_flux_uminus():
    Nx = 9
    T = _smooth_T(Nx)
    Fx = np.zeros((Nx, 1))
    for i in range(Nx):
        Fx[i, 0] = -(2.0 - 0.15 * i)
    total = sum(_sou_corr_x(T, i, 0, Nx, Fx) for i in range(Nx))
    assert abs(total) < 1e-9, f"x-SOU (u<0) not conservative (sum={total})"


def test_sou_corr_y_telescopes_with_nonuniform_flux():
    Ny = 9
    T = _smooth_T(Ny).reshape(1, Ny)
    Fy = np.zeros((1, Ny))
    for j in range(Ny):
        Fy[0, j] = 1.0 + 0.4 * j
    total = sum(_sou_corr_y(T, 0, j, Ny, Fy) for j in range(Ny))
    assert abs(total) < 1e-9, f"y-SOU not conservative (sum={total})"


def test_sou_corr_x_uniform_flux_matches_local_form():
    # With uniform flux the face-averaged form reduces to the legacy cell-local
    # form 0.5*Fx*(phi_w - phi_e) to floating-point rounding (the two differ
    # only by float distributivity, F*a - F*b vs F*(a-b)).
    from sjtu_tpmshx.solvers._kernels_2d import minmod
    Nx = 9
    T = _smooth_T(Nx)
    F = 1.7
    Fx = np.full((Nx, 1), F)
    for i in range(Nx):
        got = _sou_corr_x(T, i, 0, Nx, Fx)
        phi_w = minmod(T[i-1, 0] - T[i-2, 0], T[i, 0] - T[i-1, 0]) if i > 1 else 0.0
        phi_e = (minmod(T[i, 0] - T[i-1, 0], T[i+1, 0] - T[i, 0])
                 if (i < Nx - 1 and i > 0) else 0.0)
        assert got == pytest.approx(0.5 * F * (phi_w - phi_e), abs=1e-12)
