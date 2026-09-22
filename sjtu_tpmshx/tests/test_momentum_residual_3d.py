"""Momentum residual (ledger C6) — correctness + non-interference.

The mass residual cannot measure convergence on this solver: the pressure
correction is solved EXACTLY each iteration against the very rho_eps the
residual is then evaluated with, so it is ~0 by construction on every solved
cell, and the reported number is entirely the pressure-pinned outlet row's
artifact. `_mom_res_jit_3d` is the honest alternative.

THE LOAD-BEARING TEST is `test_residual_vanishes_at_momentum_fixed_point`,
parametrised over every (use_sou, use_eps) branch.

`_{u,v,w}_coeffs_df_3d` is a DELIBERATE PARALLEL ASSEMBLY of the sweep cell
bodies `_{u,v,w}_cell_df_3d` — not a shared helper. (Factoring them out and
having both call one helper was tried; it moved golden-3D by fastmath ULP
re-association at the inline boundary, and a diagnostic must not cost a
re-baseline.) That duplication is a real drift hazard, so it is GUARDED here
rather than trusted: if you edit a sweep cell body and not its coeffs twin, the
residual stops vanishing at the sweep's OWN fixed point and this test fails
loudly. Keep them in lockstep.
"""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers._kernels_simple_3d import (
    _mom_res_jit_3d,
    _sweep_u_jit_df_3d,
    _sweep_v_jit_df_3d,
    _sweep_w_jit_df_3d,
)


def _make_solver(Nx=6, Ny=8, Nz=4, v_inlet=2.0, zoned_eps=False):
    K = np.full((Ny, Nz), 3.0e-8)
    cF = np.full((Ny, Nz), 250.0)
    s = SIMPLESolver3D(
        Lx=0.02, Ly=0.03, Lz=0.01, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.18, mu=1.85e-5, T_in=300.0, v_inlet=v_inlet,
        eps=0.72, K_arr=K, cF_arr=cF,
        fluid_type='ideal_gas',
    )
    if zoned_eps:
        # Non-uniform ε in all three directions so every r_f = ε_f/ε_CV factor
        # in the use_eps=1 branch is exercised (a uniform field leaves them all
        # at 1.0 and the branch would be untested).
        i = np.arange(Nx)[:, None, None]
        j = np.arange(Ny)[None, :, None]
        k = np.arange(Nz)[None, None, :]
        s.eps_field = np.ascontiguousarray(
            0.60 + 0.02 * i + 0.008 * j + 0.015 * k, dtype=np.float64)
        s._mu_eff_field = np.ascontiguousarray(s.mu_field / s.eps_field)
    return s


def _mom_res(s, use_sou=0, use_eps=0):
    """(R_u, R_v, R_w) relative L1 momentum residuals on the solver's state."""
    nu, du, nv, dv, nw, dw = _mom_res_jit_3d(
        s.u, s.v, s.w, s.P,
        s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz,
        s.rho_field, s._mu_eff_field, s.mu_field, s.eps_field,
        s.K_arr, s.cF_arr, s.outlet_u_frac, s.outlet_w_frac, use_sou, use_eps)
    f = lambda n, d: (n / d if d > 1e-300 else 0.0)  # noqa: E731
    return f(nu, du), f(nv, dv), f(nw, dw)


@pytest.mark.parametrize('use_sou', [0, 1])
@pytest.mark.parametrize('use_eps', [0, 1])
def test_residual_vanishes_at_momentum_fixed_point(use_sou, use_eps):
    """THE sync guard, on every branch. Sweep momentum alone (P, rho frozen) to
    its own fixed point; the residual kernel must then read ~0. It can only do
    so if `_{u,v,w}_coeffs_df_3d` assembles exactly the aP0/rhs that
    `_{u,v,w}_cell_df_3d` does — including the guarded SOU and VANS ε-ratio
    blocks. Any coefficient drift between the twins leaves an O(1e-2..1)
    residual here.
    """
    s = _make_solver(zoned_eps=bool(use_eps))
    # A non-trivial frozen pressure field so p_src is not identically zero.
    ii = np.arange(s.Nx)[:, None, None]
    jj = np.arange(s.Ny)[None, :, None]
    s.P[:, :, :] = 50.0 * (s.Ny - 1 - jj) + 3.0 * ii

    kw = dict(Nx=s.Nx, Ny=s.Ny, Nz=s.Nz, dx=s.dx, dy=s.dy, dz=s.dz,
              rho_field=s.rho_field, mu_eff_field=s._mu_eff_field,
              mu_field=s.mu_field, eps_field=s.eps_field,
              K_arr=s.K_arr, cF_arr=s.cF_arr,
              alpha_u=1.0, use_sou=use_sou, use_eps=use_eps)

    # Momentum-only Picard: sweep u/v/w with P frozen until the field stops
    # moving. alpha_u = 1.0 -> the sweep's fixed point IS the unrelaxed
    # equation aP0*phi = rhs, which is exactly what the residual measures.
    for _ in range(600):
        prev = (s.u.copy(), s.v.copy(), s.w.copy())
        _sweep_u_jit_df_3d(s.u, s.v, s.w, s.P, s.d_u, outlet_u_frac=s.outlet_u_frac, n_sweeps=1, **kw)
        _sweep_v_jit_df_3d(s.u, s.v, s.w, s.P, s.d_v,
                           v_inlet_field=s.v_inlet_field, n_sweeps=1,
                           outlet_mask_ij=s.outlet_mask_ij, **kw)
        _sweep_w_jit_df_3d(s.u, s.v, s.w, s.P, s.d_w, outlet_w_frac=s.outlet_w_frac, n_sweeps=1, **kw)
        d = max(np.abs(s.u - prev[0]).max(),
                np.abs(s.v - prev[1]).max(),
                np.abs(s.w - prev[2]).max())
        if d < 1e-14:
            break
    else:
        pytest.fail(f"momentum sweeps did not reach a fixed point (last d={d:.2e})")

    Ru, Rv, Rw = _mom_res(s, use_sou=use_sou, use_eps=use_eps)
    assert Ru < 1e-12, f"u-momentum residual did not vanish: {Ru:.3e}"
    assert Rv < 1e-12, f"v-momentum residual did not vanish: {Rv:.3e}"
    assert Rw < 1e-12, f"w-momentum residual did not vanish: {Rw:.3e}"


def _sweep_to_momentum_fixed_point(s, use_sou=0, use_eps=0, n=600):
    kw = dict(Nx=s.Nx, Ny=s.Ny, Nz=s.Nz, dx=s.dx, dy=s.dy, dz=s.dz,
              rho_field=s.rho_field, mu_eff_field=s._mu_eff_field,
              mu_field=s.mu_field, eps_field=s.eps_field,
              K_arr=s.K_arr, cF_arr=s.cF_arr,
              alpha_u=1.0, use_sou=use_sou, use_eps=use_eps)
    for _ in range(n):
        prev = (s.u.copy(), s.v.copy(), s.w.copy())
        _sweep_u_jit_df_3d(s.u, s.v, s.w, s.P, s.d_u, outlet_u_frac=s.outlet_u_frac, n_sweeps=1, **kw)
        _sweep_v_jit_df_3d(s.u, s.v, s.w, s.P, s.d_v,
                           v_inlet_field=s.v_inlet_field, n_sweeps=1,
                           outlet_mask_ij=s.outlet_mask_ij, **kw)
        _sweep_w_jit_df_3d(s.u, s.v, s.w, s.P, s.d_w, outlet_w_frac=s.outlet_w_frac, n_sweeps=1, **kw)
        d = max(np.abs(s.u - prev[0]).max(), np.abs(s.v - prev[1]).max(),
                np.abs(s.w - prev[2]).max())
        if d < 1e-14:
            return d
    return d


def test_residual_is_nonzero_off_the_fixed_point():
    """Sanity: the metric is not trivially zero. Take a field that IS at the
    momentum fixed point (residual ~0), kick it, and the residual must jump.
    Without this, the vanishing asserted above would prove nothing."""
    s = _make_solver()
    ii = np.arange(s.Nx)[:, None, None]
    jj = np.arange(s.Ny)[None, :, None]
    s.P[:, :, :] = 50.0 * (s.Ny - 1 - jj) + 3.0 * ii
    _sweep_to_momentum_fixed_point(s)

    before = _mom_res(s)
    assert max(before) < 1e-12, f"not at the fixed point: {before}"

    s.u += 0.5          # kick the field off equilibrium
    s.v += 0.3
    after = _mom_res(s)
    assert max(after) > 1e-3, f"residual implausibly small after a 0.5 m/s kick: {after}"


def test_balanced_denominator_has_no_false_zero():
    """THE P0 this normalisation exists to kill (codex review, 2026-07-12).

    A component whose velocity is identically zero but whose pressure source is
    NOT (phi == 0, rhs != 0) is maximally unconverged. The first draft normalised
    by `sum|aP0*phi|` alone, which is 0 here, and the caller's
    `num/den if den > 0 else 0.0` guard then reported the component CONVERGED —
    a silent false zero, and a silent false convergence the moment the metric
    gates the exit.

    The balanced denominator `sum(0.5*(|lhs| + |rhs|))` removes the failure mode
    structurally rather than by a guard: |lhs - rhs| <= |lhs| + |rhs| gives
    num <= 2*den, so num > 0 IMPLIES den > 0. The ratio is also bounded by 2.
    """
    s = _make_solver()
    # w == 0 everywhere (no z-flow was ever imposed), but put a pressure
    # gradient along z so the w-momentum p_src is nonzero.
    s.u[:] = 0.0
    s.v[:] = 0.0
    s.w[:] = 0.0
    kk = np.arange(s.Nz)[None, None, :]
    s.P[:, :, :] = 1000.0 * kk

    nu, du, nv, dv, nw, dw = _mom_res_jit_3d(
        s.u, s.v, s.w, s.P, s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz,
        s.rho_field, s._mu_eff_field, s.mu_field, s.eps_field,
        s.K_arr, s.cF_arr, s.outlet_u_frac, s.outlet_w_frac, 0, 0)

    assert nw > 0.0, "w-momentum numerator must be nonzero (p_src != 0)"
    assert dw > 0.0, (
        "BALANCED denominator must be nonzero whenever the numerator is — "
        "this is the false-zero the old sum|aP0*phi| denominator produced")
    assert nw <= 2.0 * dw + 1e-9, "triangle inequality num <= 2*den violated"

    Rw = nw / dw
    assert Rw > 1.0, f"a quiescent component with a live source must read as " \
                     f"badly unconverged, got {Rw:.3e}"
    assert Rw <= 2.0 + 1e-9, f"the balanced ratio must be bounded by 2, got {Rw}"

    # And the solver-level combination must not launder it back to zero.
    Rmax, rec = s._momentum_residual(s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, 0, 0)
    assert Rmax > 0.0, "solver-level momentum residual reported a false zero"
    assert rec['num'][2] == nw and rec['den'][2] == dw, \
        "raw num/den must be preserved in the record for post-hoc re-normalisation"


def test_f2_does_not_evaluate_momentum_before_its_iteration_floor():
    s = _make_solver()
    s.solve(max_iter=5)
    assert s.mom_residuals == [] and s.final_res_mom is None


def test_tracking_records_a_history_and_does_not_change_the_result():
    """Enabling the diagnostic must not perturb ANY solver output — it is
    recorded after the fields are final and never gates the exit."""
    s0 = _make_solver()
    c0, n0 = s0.solve(max_iter=60)

    s1 = _make_solver()
    s1.track_momentum_residual = True
    c1, n1 = s1.solve(max_iter=60)

    assert (c0, n0) == (c1, n1)
    assert s0.exit_reason == s1.exit_reason
    np.testing.assert_array_equal(s0.u, s1.u)
    np.testing.assert_array_equal(s0.v, s1.v)
    np.testing.assert_array_equal(s0.w, s1.w)
    np.testing.assert_array_equal(s0.P, s1.P)
    np.testing.assert_array_equal(s0.rho_field, s1.rho_field)

    assert len(s1.mom_residuals) == n1
    for r in s1.mom_residuals:
        assert set(r) == {'u', 'v', 'w', 'max', 'num', 'den', 'iter'}
        assert r['max'] == max(r['u'], r['v'], r['w'])
        assert np.isfinite(r['max'])
        # raw num/den are kept so the normalisation can be revisited without
        # re-running (codex review).
        assert len(r['num']) == 3 and len(r['den']) == 3


def test_momentum_residual_decays_over_a_solve():
    """The metric must actually converge: it rises as the momentum sweeps
    develop the flow, then falls by orders of magnitude. Use production F2 so
    local outlet closure cannot cut this momentum test short on legacy mass tol.
    """
    s = _make_solver(Nx=8, Ny=12, Nz=4, v_inlet=3.0)
    s.track_momentum_residual = True
    s.convergence_mode = 'f2'
    s.mom_tol = 1e-4
    converged, n = s.solve(max_iter=400)

    mom = [r['max'] for r in s.mom_residuals]
    assert converged and s.exit_reason == 'tol'
    assert s.final_res_mom < s.mom_tol
    assert len(mom) == len(s.residuals) == n

    peak = max(mom)
    tail = min(mom[-10:])
    assert tail < peak / 10.0, \
        f"momentum residual did not decay: peak={peak:.2e} tail={tail:.2e}"
    assert all(np.isfinite(m) for m in mom)
