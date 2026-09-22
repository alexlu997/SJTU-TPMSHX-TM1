"""F2 gates must reject a small mass-only diagnostic and certify returned fields."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers._kernels_simple_2d import (
    _mom_res_jit_2d,
    _sweep_u_jit_df,
    _sweep_v_jit_df,
)


def _make(Nx=20, Ny=20, v_inlet=8.0, **kw):
    s = SIMPLESolver(0.05, 0.10, Nx, Ny, 'Gyroid', 6.0, 0.4, 0.7, 1.7e-3,
                     1.18, 1.85e-5, 400.0, 0.0, 0.05, v_inlet,
                     outlet_lo=0.0, outlet_hi=0.05,
                     P_ref_abs=101325.0, wall_refine=False)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _K2d(s):
    return (s._K_field2d if s._K_field2d is not None
            else np.ascontiguousarray(np.repeat(s._K_arr[None, :], s.Nx, axis=0)))


def _cF2d(s):
    return (s._cF_field2d if s._cF_field2d is not None
            else np.ascontiguousarray(np.repeat(s._cF_arr[None, :], s.Nx, axis=0)))


def _mom(s):
    """(num_u, den_u, num_v, den_v) on the solver's current state."""
    return _mom_res_jit_2d(
        s.u, s.v, s.P, s.Nx, s.Ny, s.dx_arr, s.dy_arr,
        s.rho_field, s._mu_eff_field, _K2d(s), _cF2d(s), s.mu_field,
        s.eps_field, s.outlet_u_frac, s.cf_aniso)


# ─────────────────────────────────────────────────────────────────────────
#  The defect (pin it, so nobody "restores" it)
# ─────────────────────────────────────────────────────────────────────────

def test_small_mass_diagnostic_does_not_certify_momentum():
    s = _make()
    conv, n = s.solve(max_iter=20, verbose=False)
    assert not conv and n == 20 and s.exit_reason == 'max_iter'
    assert s.residuals[-1] < 1e-12
    assert s.final_res_mom > 1e-4


def test_f2_improves_momentum_beyond_the_old_iteration_floor():
    """F2 must improve the equation residual beyond the legacy false exit."""
    s_leg = _make()
    s_leg.solve(max_iter=20, verbose=False)
    dP_leg = float(np.mean(s_leg.P[:, 0]) - np.mean(s_leg.P[:, -1]))

    s_f2 = _make(convergence_mode='f2', mom_tol=1e-4,
                 mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv, n = s_f2.solve(max_iter=3000, verbose=False)
    dP_f2 = float(np.mean(s_f2.P[:, 0]) - np.mean(s_f2.P[:, -1]))

    assert conv is True and s_f2.exit_reason == 'tol'
    assert n > 20, "F2 must not stop at the legacy min-iter floor"
    legacy_mom = max(_mom(s_leg)[0] / _mom(s_leg)[1],
                     _mom(s_leg)[2] / _mom(s_leg)[3])
    f2_mom = max(_mom(s_f2)[0] / _mom(s_f2)[1],
                 _mom(s_f2)[2] / _mom(s_f2)[3])
    assert f2_mom < legacy_mom / 3.0
    assert abs(dP_leg - dP_f2) / dP_f2 > 0.003


# ─────────────────────────────────────────────────────────────────────────
#  The sync guard for the deliberate parallel assembly
# ─────────────────────────────────────────────────────────────────────────

def test_momentum_residual_vanishes_at_the_sweep_fixed_point():
    """THE sync guard. `_{u,v}_coeffs_df_2d` is a deliberate PARALLEL ASSEMBLY of
    `_sweep_{u,v}_jit_df`'s coefficient block, not a shared helper. Sweep the
    momentum equations alone (P, rho frozen, alpha_u = 1) to their own fixed
    point; the residual kernel must then read ~0. It can only do so if it
    assembles exactly the aP0/rhs the sweeps do — including the ALWAYS-ON SOU
    correction and the ALWAYS-ON VANS eps ratios (2D has no use_sou / use_eps
    flags, unlike 3D). Edit a sweep and not its twin, and this fails loudly.
    """
    s = _make()
    ii = np.arange(s.Nx)[:, None]
    jj = np.arange(s.Ny)[None, :]
    s.P[:, :] = 40.0 * (s.Ny - 1 - jj) + 2.0 * ii     # non-trivial p_src

    K2, cF2 = _K2d(s), _cF2d(s)
    kw = dict(Nx=s.Nx, Ny=s.Ny, dx_arr=s.dx_arr, dy_arr=s.dy_arr,
              rho_field=s.rho_field, mu_eff_field=s._mu_eff_field,
              K_arr=K2, cF_arr=cF2, mu_field=s.mu_field,
              eps_field=s.eps_field, alpha_u=1.0, n_sweeps=1,
              cf_aniso=s.cf_aniso)

    for _ in range(3000):
        pu, pv = s.u.copy(), s.v.copy()
        _sweep_u_jit_df(s.u, s.v, s.P, s.d_u, s.outlet_u_frac, **kw)
        _sweep_v_jit_df(s.u, s.v, s.P, s.d_v, s.inlet_frac, s.v_inlet_field,
                        s.outlet_frac, **kw)
        d = max(np.abs(s.u - pu).max(), np.abs(s.v - pv).max())
        if d < 1e-14:
            break
    # The iterate can oscillate by a few ULPs (~1.15e-14 at 8 m/s).
    # Stagnation only saves work; the independent equation below is the gate.
    nu, du, nv, dv = _mom(s)
    Ru = nu / du if du > 0 else 0.0
    Rv = nv / dv if dv > 0 else 0.0
    assert Ru < 1e-12, f"u-momentum residual did not vanish: {Ru:.3e}"
    assert Rv < 1e-12, f"v-momentum residual did not vanish: {Rv:.3e}"


def test_balanced_denominator_has_no_false_zero():
    """A component with zero velocity but a live pressure source is maximally
    unconverged. The naive Patankar denominator `sum|aP0*phi|` is 0 there, and a
    `num/den if den > 0 else 0.0` guard would report CONVERGED — a silent false
    convergence once the metric gates the exit.

    The balanced denominator `sum(0.5*(|lhs| + |rhs|))` removes the failure mode
    STRUCTURALLY: |lhs-rhs| <= |lhs|+|rhs| gives num <= 2*den, so num > 0 implies
    den > 0. The ratio is also bounded by 2.
    """
    s = _make()
    s.u[:] = 0.0
    s.v[:] = 0.0
    ii = np.arange(s.Nx)[:, None]
    s.P[:, :] = 1000.0 * ii            # gradient along x -> u-momentum p_src != 0

    nu, du, nv, dv = _mom(s)
    assert nu > 0.0, "u-momentum numerator must be nonzero (p_src != 0)"
    assert du > 0.0, (
        "BALANCED denominator must be nonzero whenever the numerator is — this "
        "is the false zero the old sum|aP0*phi| denominator produced")
    assert nu <= 2.0 * du + 1e-9, "triangle inequality num <= 2*den violated"
    Ru = nu / du
    assert Ru > 1.0, f"a quiescent component with a live source must read badly " \
                     f"unconverged, got {Ru:.3e}"
    assert Ru <= 2.0 + 1e-9, f"the balanced ratio must be bounded by 2, got {Ru}"

    rmax, rec = s._momentum_residual(s.Nx, s.Ny, s.dx_arr, s.dy_arr,
                                     _K2d(s), _cF2d(s))
    assert rmax > 0.0, "solver-level momentum residual reported a false zero"
    assert rec['num'][0] == nu and rec['den'][0] == du, \
        "raw num/den must be preserved for post-hoc re-normalisation"


# ─────────────────────────────────────────────────────────────────────────
#  Wiring
# ─────────────────────────────────────────────────────────────────────────

def test_f2_is_the_default():
    s = _make()
    conv, n = s.solve(max_iter=3000, verbose=False)
    assert conv and s.convergence_mode == 'f2'
    assert len(s.mass_local_residuals) == n
    assert s.final_res_mom < 1e-4


def test_f2_exits_on_tol_with_all_three_gates_met():
    s = _make(convergence_mode='f2', mom_tol=1e-4,
              mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv, n = s.solve(max_iter=3000, verbose=False)
    assert conv is True and s.exit_reason == 'tol'
    assert s.final_res_mom < 1e-4
    assert s.final_res_mass_local < 1e-6
    assert s.final_res_mass_global < 1e-6
    assert 0.0 <= s.outlet_backflow_frac <= 1.0
    assert len(s.mass_local_residuals) == n


def test_each_gate_can_hold_the_exit_open():
    """All three gates are required. 0.0 is strictly unreachable (all three
    residuals are non-negative), unlike a tiny positive number — the global mass
    residual reaches EXACTLY zero at convergence."""
    base = dict(convergence_mode='f2', mom_tol=1e-4,
                mass_local_tol=1e-6, mass_global_tol=1e-6)
    s = _make(**base)
    s.solve(max_iter=3000, verbose=False)
    assert s.exit_reason == 'tol', "precondition: the base config converges"

    for gate in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        cfg = dict(base)
        cfg[gate] = 0.0
        s = _make(**cfg)
        conv, n = s.solve(max_iter=300, verbose=False)
        assert conv is False, f"{gate} did not hold the exit open"
        assert s.exit_reason in ('max_iter', 'stall')

    # Fourth gate (2026-07-13): outlet backflow. backflow_frac >= 0 always,
    # so -1.0 is strictly unreachable — mirrors the 0.0 tolerances above.
    # (The default 0.01 is inert on every measured baseline: backflow == 0.)
    cfg = dict(base)
    cfg['f2_backflow_max'] = -1.0
    s = _make(**cfg)
    conv, n = s.solve(max_iter=300, verbose=False)
    assert conv is False, "f2_backflow_max did not hold the exit open"
    assert s.exit_reason in ('max_iter', 'stall')


@pytest.mark.parametrize('mode', ['legacy', 'f2'])
def test_retired_coupling_option_is_rejected(mode):
    s = _make(convergence_mode=mode)
    with pytest.raises(TypeError, match="coupling"):
        s.solve(max_iter=10, coupling='simpler', verbose=False)


@pytest.mark.parametrize('mode', ['legacy', 'momentum'])
def test_f2_rejects_retired_or_unknown_mode(mode):
    s = _make(convergence_mode=mode)
    with pytest.raises(ValueError, match="convergence_mode"):
        s.solve(max_iter=10, verbose=False)


@pytest.mark.parametrize('closeout', [True, False])
def test_max_iter_closes_outlet_with_fresh_density(monkeypatch, closeout):
    s = _make(Nx=4, Ny=4, fluid_type='ideal_gas',
              enforce_outlet_mass_balance=closeout)
    s.eps_field[:] = np.linspace(.5, .8, 16).reshape(4, 4)
    s.T_field[:] = np.linspace(300., 500., 16).reshape(4, 4)
    update = s._update_density
    snapshot = {}

    def capture_density_update():
        old_rho = s.rho_field.copy()
        update()
        snapshot['rho_changed'] = not np.array_equal(old_rho, s.rho_field)
        snapshot['v'] = s.v[:, -1].copy()

    monkeypatch.setattr(s, '_update_density', capture_density_update)
    conv, n = s.solve(max_iter=1, verbose=False)
    assert not conv and n == 1 and s.exit_reason == 'max_iter'
    assert snapshot['rho_changed']
    re = s.rho_field * s.eps_field
    fs = .5 * (re[:, -2] + re[:, -1]) * s.v[:, -2] * s.dx_arr
    lateral = .5 * (re[:-1, -1] + re[1:, -1]) * s.u[1:-1, -1] * s.dy_arr[-1]
    fw = np.r_[0., lateral]
    fe = np.r_[lateral, 0.]
    expected = (fs + fw - fe) / (re[:, -1] * s.dx_arr)
    assert not np.allclose(snapshot['v'], expected, rtol=1e-8, atol=1e-12)
    np.testing.assert_allclose(s.v[:, -1], expected if closeout else snapshot['v'],
                               rtol=1e-13, atol=1e-13)
    assert s._last_outlet_mass_scale == 1.0


@pytest.mark.parametrize('reason,post_ok,expected', [
    ('stall', True, False), ('tol', False, False), ('tol', True, True),
])
def test_f2_return_requires_pre_and_post_gates(monkeypatch, reason, post_ok, expected):
    from sjtu_tpmshx.solvers import simple_solver as module

    s = _make(Nx=4, Ny=4, convergence_mode='f2')
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: reason)
    # Control only the gate observations; run the real iteration and closeout.
    residuals = iter([0., 0. if post_ok else 1.])
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (next(residuals), {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_2d', lambda *a: (0., 0.))
    monkeypatch.setattr(module, '_mass_global_jit_2d', lambda *a: (1., 1., 0.))
    conv, n = s.solve(max_iter=1, verbose=False)
    assert conv is expected and n == 1
    assert s.exit_reason == reason
    assert s.f2_cert_post_rescale_ok is post_ok
