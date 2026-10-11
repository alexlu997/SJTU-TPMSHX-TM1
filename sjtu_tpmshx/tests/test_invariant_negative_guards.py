"""Regression guards for three physical invariants.

1. ε is split ONCE — the shared 2D and 3D Python backends must hand the
   energy kernel the FULL porosity on the symmetric path.
2. massflux_inlet defaults ON — both SIMPLE solvers capture the inlet
   mass-flux target without an explicit override.
3. norris_1a is a friction NO-OP (×1.0) — the DF closure already bakes in
   SLM roughness; any friction multiplier double-counts.
"""

import numpy as np
import pytest


# ── 1. ε-once contract: shared Python backend callers ──────────────


class _EpsCaptured(Exception):
    """Sentinel: kernel spy captured its arguments; abort the run."""


def test_stages_3d_passes_full_epsilon(monkeypatch):
    """The scripted 3D entry must hand solve_full_domain_3d
    the FULL ε (kernel halves once) — not a pre-halved ε_A."""
    # Patch the shared runtime where the thermal kernel is resolved.
    import sjtu_tpmshx.solvers.backends.python.three_d.runtime as R
    from sjtu_tpmshx.tests import cases_3d as R_orch

    captured = {}

    def spy(*a, **kw):
        # positional order (mirrors test_eps_contract_3d):
        # ... 15 = epsilon
        eps = a[15] if len(a) > 15 else kw.get("epsilon")
        captured["eps"] = float(np.asarray(eps, dtype=float).max())
        raise _EpsCaptured

    monkeypatch.setattr(R, "solve_full_domain_3d", spy)
    monkeypatch.setattr(R.SIMPLESolver3D, "solve",
                        lambda self, *a, **k: (True, 1))

    from test_partial_bc_ghost_b import _partial_bc_air_air_cfg
    cfg = _partial_bc_air_air_cfg(Nx=6, Ny=6, Nz=6)
    with pytest.raises(_EpsCaptured):
        R_orch.run_research(cfg)

    assert captured["eps"] == pytest.approx(cfg['eps'], rel=1e-6), (
        f"3D Python backend passed epsilon.max()={captured['eps']:.4f}; expected "
        f"FULL ε={cfg['eps']:.4f}. A value near {cfg['eps'] / 2:.4f} means "
        f"the ε double-halving regression is back on the shared 3D path.")


def test_solve_2d_passes_full_epsilon(monkeypatch):
    """The 2D Python coupling loop must hand solve_full_domain the FULL ε with
    eps_A/eps_B None on the symmetric (δ=0) path."""
    import sjtu_tpmshx.solvers.backends.python.two_d.coupling as S2

    captured = {}

    def spy(*a, **kw):
        captured["eps"] = float(np.max(np.asarray(a[13], dtype=float)))
        captured["eps_A"] = kw.get("eps_A")
        captured["eps_B"] = kw.get("eps_B")
        raise _EpsCaptured

    monkeypatch.setattr(S2, "solve_full_domain", spy)

    from sjtu_tpmshx.domain.compute_config import (ComputeConfig, ExtrapPolicy,
                                       FluidConfig, GeometryConfig,
                                       SolverConfig)
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5.0, T_in_K=400.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=310.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.06, H_dom_m=0.03),
        solver=SolverConfig(Nx=8, Ny=8),
        extrap=ExtrapPolicy(allow=True),   # t=0.6 outside ConstDF-v1 window
    )
    try:
        Pipeline2D(cfg).run()
    except Exception:
        pass   # sentinel (or downstream wreckage) — capture is what matters

    assert "eps" in captured, "energy kernel was never reached"
    from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute
    eps_full = tpms_compute('Gyroid', 7.0, 0.6, 5.0, 400.0, 101325.0,
                            16.0)['epsilon']
    assert captured["eps"] == pytest.approx(eps_full, rel=1e-6), (
        f"solve_2d passed ε={captured['eps']:.4f}, expected FULL "
        f"ε={eps_full:.4f}")
    assert captured["eps_A"] is None and captured["eps_B"] is None, (
        "symmetric (δ=0) path must NOT populate the private eps_A/eps_B "
        "hooks — that is the asym-only exception")


# ── 2. massflux_inlet defaults ON ───────────────────────────────────


def test_massflux_inlet_default_on_2d():
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
    s = SIMPLESolver(
        W=0.06, H=0.03, Nx=10, Ny=8,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.85, r_h=1e-3,
        rho=1.2, mu=1.8e-5, T_in=350.0,
        inlet_lo=0.0, inlet_hi=0.06, v_inlet=5.0, wall_refine=False)
    assert not hasattr(s, 'massflux_inlet') or s.massflux_inlet, \
        "massflux_inlet default flipped OFF (hard invariant)"
    s.solve(max_iter=1, verbose=False)
    assert hasattr(s, '_massflux_target'), (
        "2D mass-flux target was never captured — the massflux-inlet "
        "default (velocity-inlet regression, grid-dependent Δp) is off")


def test_massflux_inlet_default_on_3d():
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
    K_arr = np.full((6, 5), 5.0e-8)
    cF_arr = np.full((6, 5), 500.0)
    s = SIMPLESolver3D(Lx=0.04, Ly=0.03, Lz=0.02, Nx=8, Ny=6, Nz=5,
                       rho=1.2, mu=1.8e-5, T_in=350.0, v_inlet=5.0,
                       K_arr=K_arr, cF_arr=cF_arr)
    assert not hasattr(s, 'massflux_inlet') or s.massflux_inlet, \
        "massflux_inlet default flipped OFF (hard invariant)"
    s.solve(max_iter=1, verbose=False)
    assert hasattr(s, '_massflux_target'), (
        "3D mass-flux target was never captured — the massflux-inlet "
        "default is off")


# ── 3. norris_1a friction no-op ─────────────────────────────────────


def test_norris_1a_friction_is_exactly_noop():
    """norris_1a remains a friction no-op. The original ROUGH-X guard prevented
    double-counting roughness in the historical gamma_df calibration; that
    model is now retired, while the no-op contract remains unchanged."""
    from sjtu_tpmshx.models.roughness import f_enhancement, nu_extra_factor
    for Re in (500.0, 2000.0, 8000.0, 16000.0):
        assert f_enhancement(Re, mode='norris_1a') == 1.0
        assert f_enhancement(Re, mode='baseline') == 1.0
        assert nu_extra_factor(Re, mode='norris_1a') == 1.0
