"""N3 (2026-07-07): the partial-inlet edge taper must not delete throughput.

The 4-cell exponential taper smooths the imposed inlet profile near
wall/open edges; unrenormalised it under-delivered the imposed mass flux
by ~0.914 cell-widths of open area per pipe edge (grid-dependent). The fix
scales v_inlet_field (and the mass-flux target) so the tapered profile
carries exactly the geometric open-area flux.
"""

import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


def _make(inlet_lo, inlet_hi, Nx=30, Ny=20, *, uniform=False):
    return SIMPLESolver(
        W=0.18, H=0.06, Nx=Nx, Ny=Ny,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.85, r_h=1.0e-3,
        rho=1.2, mu=1.8e-5, T_in=350.0,
        inlet_lo=inlet_lo, inlet_hi=inlet_hi, v_inlet=8.0,
        wall_refine=False,
        uniform_inlet=uniform,
    )


def test_partial_inlet_taper_preserves_open_area_flux():
    """Imposed Σ v_field·frac·dx must equal v_inlet × geometric open area."""
    s = _make(inlet_lo=0.06, inlet_hi=0.12)
    assert s._inlet_taper_flux_scale > 1.0, \
        "taper fired but no renormalisation was applied"
    imposed = float(np.sum(s.v_inlet_field * s.inlet_frac * s.dx_arr))
    geometric = 8.0 * (0.12 - 0.06)
    assert imposed == pytest.approx(geometric, rel=1e-12), \
        f"imposed {imposed:.6e} vs geometric {geometric:.6e}"


def test_uniform_partial_inlet_has_no_cell_count_dependent_edge_profile():
    for nx in (24, 48, 96):
        s = _make(.06, .12, Nx=nx, uniform=True)
        np.testing.assert_array_equal(s.inlet_frac, s.inlet_geom_frac)
        assert s._inlet_taper_flux_scale == 1.
        np.testing.assert_array_equal(s.v_inlet_field, 8.)
        assert np.dot(s.v[:, 0], s.dx_arr) == pytest.approx(8. * .06, rel=1e-12)


def test_partial_inlet_taper_grid_independence():
    """The imposed flux must be identical across grid resolutions (the old
    deficit was measured in CELLS, so it drifted with N)."""
    fluxes = []
    for Nx in (24, 48, 96):
        s = _make(inlet_lo=0.06, inlet_hi=0.12, Nx=Nx)
        fluxes.append(float(np.sum(s.v_inlet_field * s.inlet_frac
                                   * s.dx_arr)))
    assert fluxes[0] == pytest.approx(fluxes[1], rel=1e-12)
    assert fluxes[1] == pytest.approx(fluxes[2], rel=1e-12)


def test_full_face_inlet_taper_is_noop():
    """Full-face inlet: taper never fires, scale stays exactly 1.0 and the
    velocity field is untouched (bit-identity guard for the goldens)."""
    s = _make(inlet_lo=0.0, inlet_hi=0.18)
    assert s._inlet_taper_flux_scale == 1.0
    assert np.all(s.v_inlet_field == 8.0)


def test_massflux_target_carries_taper_scale():
    """The mass-flux capture must include the taper factor — the per-cell
    v_inlet_field rebuild would otherwise erase the init-time scaling."""
    s = _make(inlet_lo=0.06, inlet_hi=0.12)
    # The target is captured at solve() entry from the INITIAL inlet
    # density — record it before the density field evolves.
    rho0 = float(s.rho_field[:, 0].mean())
    s.solve(max_iter=2, tol=0.0, verbose=False)
    expected = 8.0 * rho0 * s._inlet_taper_flux_scale
    assert s._massflux_target == pytest.approx(expected, rel=1e-12)
