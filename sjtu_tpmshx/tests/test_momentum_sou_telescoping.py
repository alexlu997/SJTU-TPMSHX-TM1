"""N2 (full-debug audit 2026-06-28): the momentum SOU deferred correction must
scale each face's limiter by THAT face's convective flux (Fw west, Fe east) so it
telescopes — the legacy form used one cell-flux for both faces, injecting a
spurious momentum source where ρ·u varied between neighbours (the defect already
fixed in ltne_energy._sou_corr_x/_y).

Flux-isolation: helper(Fe=1,Fw=0) returns -0.5·φ_e (east limiter only);
helper(Fe=0,Fw=1) returns +0.5·φ_w (west limiter only). Telescoping requires the
east limiter of cell i to equal the west limiter of cell i+1 at the shared face
(φ_e(i) == φ_w(i+1)), so the corrections cancel when the shared-face flux matches.
"""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import (
    _sou_corr_u_x, _sou_corr_u_y, _sou_corr_v_x, _sou_corr_v_y,
)


def _convex_line(n):
    """Monotone-increasing convex profile -> non-zero minmod limiters."""
    return np.array([1.0 + 0.1 * ii + 0.01 * ii * ii for ii in range(n)])


@pytest.mark.parametrize('helper,axis', [(_sou_corr_u_x, 0), (_sou_corr_u_y, 1),
                                       (_sou_corr_v_x, 0), (_sou_corr_v_y, 1)])
def test_sou_shared_face_uses_its_own_flow_direction(helper, axis):
    # The shared face flows forward; the next face flows backward. Its
    # direction must not change the correction on the shared face.
    line = np.array([8., 6., 4., 3., 1., -2., -6., -9., -12.])
    field = np.repeat(line[:, None], len(line), axis=1)
    if axis == 1:
        field = field.T.copy()
    i, j = 3, 3
    ni, nj = i + (axis == 0), j + (axis == 1)
    left = helper(field, i, j, 8, 1., 0.)
    right = (helper(field, ni, nj, 8, -2., 1.)
             - helper(field, ni, nj, 8, -2., 0.))
    assert left != 0.
    assert left + right == pytest.approx(0., abs=1e-14)


def test_sou_corr_u_x_telescopes_at_shared_x_face():
    Nx, Ny = 12, 1
    u = np.zeros((Nx + 1, Ny))
    u[:, 0] = _convex_line(Nx + 1)
    j, i = 0, 5
    east_i = _sou_corr_u_x(u, i, j, Nx, 1.0, 0.0)        # -0.5·φ_e(i)
    west_ip1 = _sou_corr_u_x(u, i + 1, j, Nx, 0.0, 1.0)  # +0.5·φ_w(i+1)
    assert abs(east_i) > 0.0                              # limiter active
    assert east_i == pytest.approx(-west_ip1)            # φ_e(i) == φ_w(i+1)


def test_sou_corr_v_y_telescopes_at_shared_y_face():
    Nx, Ny = 1, 12
    v = np.zeros((Nx, Ny + 1))
    v[0, :] = _convex_line(Ny + 1)
    i, j = 0, 5
    north_j = _sou_corr_v_y(v, i, j, Ny, 1.0, 0.0)        # -0.5·φ_n(j)
    south_jp1 = _sou_corr_v_y(v, i, j + 1, Ny, 0.0, 1.0)  # +0.5·φ_s(j+1)
    assert abs(north_j) > 0.0
    assert north_j == pytest.approx(-south_jp1)


def test_sou_corr_u_x_uniform_flux_reduces_to_legacy():
    """Fe==Fw==F -> 0.5·(F·φ_w − F·φ_e) = 0.5·F·(φ_w − φ_e): the legacy scalar
    form, so a uniform-flux region is unchanged (the golden re-baseline is driven
    only by the variable-flux cells)."""
    Nx, Ny = 12, 1
    u = np.zeros((Nx + 1, Ny))
    u[:, 0] = _convex_line(Nx + 1)
    j, i, F = 0, 5, 2.3
    full = _sou_corr_u_x(u, i, j, Nx, F, F)
    pe = _sou_corr_u_x(u, i, j, Nx, 1.0, 0.0)   # -0.5·φ_e
    pw = _sou_corr_u_x(u, i, j, Nx, 0.0, 1.0)   # +0.5·φ_w
    assert full == pytest.approx(F * (pw + pe))  # = 0.5·F·(φ_w − φ_e)


def test_sou_corr_v_x_and_u_y_accept_two_fluxes():
    """Cross-derivative helpers: bilinear in (Fe, Fw) and non-trivial on a
    convex profile. T6 tightened (2026-07-07): the old assertion only
    checked `isinstance(..., float)` — NaN passed, and a helper returning
    a constant 0.0 passed."""
    Nx, Ny = 12, 12
    a = np.zeros((Nx + 1, Ny + 1))
    a[:, :] = _convex_line(Nx + 1)[:, None] + _convex_line(Ny + 1)[None, :]
    for helper, N in ((_sou_corr_v_x, Nx), (_sou_corr_u_y, Ny)):
        pe = float(helper(a, 5, 5, N, 1.0, 0.0))   # unit hi-face flux
        pw = float(helper(a, 5, 5, N, 0.0, 1.0))   # unit lo-face flux
        full = float(helper(a, 5, 5, N, 1.0, 0.5))
        assert np.isfinite(full) and np.isfinite(pe) and np.isfinite(pw)
        # minmod on a strictly convex profile must produce a correction
        assert pe != 0.0 or pw != 0.0, "SOU correction vanished on convex"
        # same bilinearity identity the streamwise pair is pinned to
        assert full == pytest.approx(1.0 * pe + 0.5 * pw, rel=1e-12)
