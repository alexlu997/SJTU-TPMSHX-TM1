"""Pressure-subproblem normalization, failed F2 exits and outer temperature gates."""
import warnings

warnings.filterwarnings('ignore')

import numpy as np

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence
from sjtu_tpmshx.solvers import _solve_common


# ── fixtures ─────────────────────────────────────────────────────────

def _solver_3d(Nx=12, Ny=10, Nz=4, v_inlet=3.0, eps=0.78,
               rho=1.0, mu=2e-5):
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho, mu=mu, T_in=350.0, v_inlet=v_inlet,
        eps=eps, K_arr=K_arr, cF_arr=cF_arr, P_ref_abs=101325.0)


def _solver_2d(v_inlet=3.0, Nx=12, Ny=20):
    return SIMPLESolver(
        W=0.042, H=0.06, Nx=Nx, Ny=Ny,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.6, r_h=1e-3,
        rho=1.2, mu=1.8e-5, T_in=322.0,
        inlet_lo=0.0, inlet_hi=0.042, v_inlet=v_inlet,
        fluid_type='incompressible', wall_refine=False)


# ── 3D residual normalisation ────────────────────────────────────────

def test_res_norm_ref_matches_inlet_flux():
    """res_norm_ref must equal Σ ε·ρ·|v_in|·dA over the j=0 inlet face."""
    s = _solver_3d()
    s.solve(max_iter=15)   # fixed budget before F2 converges
    rho_eps = s.rho_field * s.eps_field
    expected = float(np.sum(rho_eps[:, 0, :] * np.abs(s.v[:, 0, :])
                            * s.dx[:, None] * s.dz[None, :]))
    assert expected > 0.0
    # stored ref is the per-iteration snapshot; the post-solve recompute
    # differs by the density drift of the final iteration (~1e-4 relative)
    assert abs(s.res_norm_ref - expected) / expected < 1e-3, \
        f"res_norm_ref {s.res_norm_ref} != inlet flux {expected}"
    # residual history is dimensionless now — final entry matches final_res
    assert s.final_res == s.residuals[-1]
    print(f"test_res_norm_ref_matches_inlet_flux PASS "
          f"(ref={s.res_norm_ref:.4e} kg/s)")


def test_res_norm_fallback_absolute_on_no_flow():
    """Zero-inlet solve keeps the absolute norm (ref falls back to 1.0)."""
    s = _solver_3d(v_inlet=0.0)
    s.solve(max_iter=5)
    assert s.res_norm_ref == 1.0, s.res_norm_ref
    print("test_res_norm_fallback_absolute_on_no_flow PASS")


def test_residual_scale_invariance(monkeypatch):
    """Scale the same state, not two different Reynolds-number trajectories.

    Also check the real solve's published history, so removing its division
    by inlet flux fails even if the raw kernel's scaling remains correct.
    """
    from sjtu_tpmshx.solvers import simple_solver_3d as module
    raw_kernel = module._mass_res_jit_3d
    expected = []

    def record(u, v, w, Nx, Ny, Nz, dx, dy, dz, rho_eps):
        raw = raw_kernel(u, v, w, Nx, Ny, Nz, dx, dy, dz, rho_eps)
        flux = float(np.sum(rho_eps[:, 0, :] * np.abs(v[:, 0, :])
                            * dx[:, None] * dz[None, :]))
        scaled_raw = raw_kernel(4*u, 4*v, 4*w, Nx, Ny, Nz, dx, dy, dz, rho_eps)
        scaled_flux = float(np.sum(rho_eps[:, 0, :] * np.abs(4*v[:, 0, :])
                                   * dx[:, None] * dz[None, :]))
        assert flux > 0.
        np.testing.assert_allclose(scaled_raw, 4*raw, rtol=1e-12, atol=0.)
        np.testing.assert_allclose(scaled_flux, 4*flux, rtol=1e-12, atol=0.)
        np.testing.assert_allclose(scaled_raw/scaled_flux, raw/flux,
                                   rtol=1e-12, atol=0.)
        expected.append(raw/flux)
        return raw

    monkeypatch.setattr(module, '_mass_res_jit_3d', record)
    s = _solver_3d(v_inlet=1.)
    s.mom_tol = 0.0
    s.solve(max_iter=30)
    assert len(expected) == len(s.residuals) == 30
    assert np.any(np.asarray(expected) > 0.)
    np.testing.assert_allclose(s.residuals, expected, rtol=1e-12, atol=0.)


# ── exit_reason semantics ────────────────────────────────────────────

def test_stall_reports_not_converged_3d(monkeypatch):
    monkeypatch.setattr(_solve_common.F2Monitor, 'submit',
                        lambda self, *args: 'stall')
    s = _solver_3d()
    conv, it = s.solve(max_iter=50)
    assert conv is False and s.exit_reason == 'stall', \
        (conv, s.exit_reason)
    print("test_stall_reports_not_converged_3d PASS")


def test_stall_reports_not_converged_2d(monkeypatch):
    monkeypatch.setattr(_solve_common.F2Monitor, 'submit',
                        lambda self, *args: 'stall')
    s = _solver_2d()
    conv, it = s.solve(max_iter=60)
    assert conv is False and s.exit_reason == 'stall', \
        (conv, s.exit_reason)
    print("test_stall_reports_not_converged_2d PASS")


def test_exit_reason_on_strict_and_max_iter_3d():
    # Default F2 gates must be satisfied.
    s = _solver_3d()
    conv, _ = s.solve(max_iter=500)
    assert conv is True and s.exit_reason == 'tol', \
        (conv, s.exit_reason)
    # Impossible momentum tolerance must not produce success.
    s2 = _solver_3d()
    s2.mom_tol = 0.0
    conv2, it2 = s2.solve(max_iter=12)
    assert conv2 is False and s2.exit_reason == 'max_iter' and it2 == 12, \
        (conv2, s2.exit_reason, it2)
    print("test_exit_reason_on_strict_and_max_iter_3d PASS")


# ── outer-gate wiring contract ───────────────────────────────────────

def test_outer_convergence_gates_all_three_fields():
    oc = OuterConvergence(tol_T=0.5, track=('Ta', 'Tb', 'Ts'))
    Ta = np.full((4, 4), 300.0)
    Tb = np.full((4, 4), 320.0)
    Ts = np.full((4, 4), 310.0)
    conv, d = oc.check({'Ta': Ta, 'Tb': Tb, 'Ts': Ts})
    assert not conv and all(np.isinf(v) for v in d.values())   # first iter
    conv, d = oc.check({'Ta': Ta, 'Tb': Tb, 'Ts': Ts})
    assert conv and max(d.values()) == 0.0                     # all static
    # only the SOLID moves → gate must hold the loop open
    conv, d = oc.check({'Ta': Ta, 'Tb': Tb, 'Ts': Ts + 1.0})
    assert not conv and d['Ts'] == 1.0 and d['Ta'] == 0.0, d
    print("test_outer_convergence_gates_all_three_fields PASS")


if __name__ == '__main__':
    test_res_norm_ref_matches_inlet_flux()
    test_res_norm_fallback_absolute_on_no_flow()
    test_residual_scale_invariance()
    test_exit_reason_on_strict_and_max_iter_3d()
    test_outer_convergence_gates_all_three_fields()
    print("ALL DIRECT-RUN TESTS PASS (monkeypatch tests need pytest)")
