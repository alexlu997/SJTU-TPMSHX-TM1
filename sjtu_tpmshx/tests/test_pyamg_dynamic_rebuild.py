"""Tests for the dynamic PyAMG rebuild trigger added in phase L-d (audit P4).

The pressure-correction solver caches a PyAMG hierarchy in
`SIMPLESolver3D._ml_cache` and rebuilds it on (a) the first SIMPLE iter,
(b) cadence hits (`it % pyamg_rebuild_every == 0`), or (c) when the
unpinned diagonal-vector change on the assembled `A` exceeds
`pyamg_rebuild_drift_thresh`. These tests cover the bookkeeping and the
trigger-vs-skip decision on an AMG-active grid (`N > 30000`).

Grids small enough to fall under the spsolve branch (`N <= 30000`) are
exercised indirectly by `tests/test_simple_solver_3d.py`; the cache stays
empty on that path so the counters tested here are zero.
"""
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def test_pressure_pins_do_not_hide_coefficient_change(monkeypatch):
    from sjtu_tpmshx.solvers import simple_solver_3d as mod
    monkeypatch.setattr(mod, '_AMG_GATE', 0)
    s = SIMPLESolver3D(Lx=.08, Ly=.08, Lz=.04, Nx=8, Ny=8, Nz=4,
                      rho=1., mu=2e-5, T_in=300., v_inlet=1.,
                      use_coarse_bootstrap=False)
    s._pp_sparsity = mod._build_pp_sparsity_3d(s.Nx, s.Ny, s.Nz, s.outlet_mask_ij)
    for d in (s.d_u, s.d_v, s.d_w):
        d.fill(1e-3)

    def solve():
        return mod._solve_pp_amg(s.Pp, s.u, s.v, s.w, s.d_u, s.d_v, s.d_w,
            s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, s.rho_field,
            s._pp_sparsity, s._ml_cache, False, rtol_dyn=1e-9)

    first, _ = solve()
    solve()
    assert s._ml_cache['rebuild_count'] == 1  # An unchanged matrix is reused.
    for d in (s.d_u, s.d_v, s.d_w):
        d *= .01
    changed, rhs = solve()
    old_norm_drift = abs(np.linalg.norm(changed.diagonal()) / np.linalg.norm(first.diagonal()) - 1.)
    assert old_norm_drift < .05  # Unit outlet pins conceal the real change.
    assert s._ml_cache['rebuild_count'] == 2
    assert s._ml_cache['last_drift'] == pytest.approx(.99)
    assert np.linalg.norm(changed @ s.Pp.ravel() - rhs) <= 1e-9*np.linalg.norm(rhs) + 1e-12


# 60x60x10 = 36 000 cells > 30 000 AMG gate.
_NX, _NY, _NZ = 60, 60, 10


def _make_solver(drift_thresh=0.05, rebuild_every=100,
                 use_coarse_bootstrap=False):
    """Default `use_coarse_bootstrap=False` to keep drift-trigger tests
    isolated from Option B warm-start side effects. Option B auto-enables
    bootstrap on N>30 k by default, but bootstrap shrinks the iter-to-iter
    A drift to ~1e-15 (already steady-state after warm guess) which would
    suppress the drift_thresh=1e-12 trigger this file asserts on."""
    K_arr = np.full((_NY, _NZ), 5e-9, dtype=np.float64)
    cF_arr = np.full((_NY, _NZ), 250.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.06, Ly=0.06, Lz=0.01,
        Nx=_NX, Ny=_NY, Nz=_NZ,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=5.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0,
        pyamg_rebuild_every=rebuild_every,
        pyamg_rebuild_drift_thresh=drift_thresh,
        use_coarse_bootstrap=use_coarse_bootstrap)


@pytest.mark.slow
def test_fixed_drag_rebuilds_during_startup_then_reuses():
    """Fixed K/cF still has evolving momentum coefficients at startup."""
    s = _make_solver(drift_thresh=0.05)
    s.solve(max_iter=20, tol=1e-6)
    c = s._ml_cache
    assert 1 < c['rebuild_count'] < c['bcg_calls']
    assert c.get('skip_count', 0) >= 5, (
        f"expected drift-skip to fire on >=5 iters, "
        f"got {c.get('skip_count')}")
    assert c.get('drift_rebuild_count', 0) > 0
    assert c.get('last_drift', 1.0) < 0.05, (
        f"final drift should be < 5 %, got {c.get('last_drift')}")


@pytest.mark.slow
def test_canonicalized_amg_runs_bicgstab_from_first_iter():
    """Canonicalization fix (2026-06-24): the AMG path canonicalizes the
    assembled CSR (`sort_indices` + `sum_duplicates`) and runs BiCGStab from
    the FIRST iter — the old cold-start direct-LU bypass is removed. On a
    canonical matrix the AMG-preconditioned BiCGStab converges every iter, so
    NO direct-LU fallback fires (this was the real fix: the old divergence was
    a non-canonical-CSR artifact, not zero-velocity diagonal heterogeneity).
    """
    s = _make_solver(drift_thresh=0.05)
    s.solve(max_iter=5, tol=1e-6)
    c = s._ml_cache
    # Cold-start bypass removed → its counters are never set.
    assert c.get('cold_start_count', 0) == 0, (
        f"cold-start bypass should be gone, got {c.get('cold_start_count')}")
    assert c.get('cold_start_done', False) is False
    # Hierarchy built; BiCGStab ran from iter 1 (one call per outer iter).
    assert c.get('rebuild_count', 0) >= 1
    assert 'ml' in c
    assert c.get('bcg_calls', 0) >= 1
    # Canonical A → BiCGStab converges, no direct-LU fallback.
    assert c.get('bcg_fail_count', 0) == 0, (
        f"canonicalized AMG-BiCGStab must converge without direct fallback, "
        f"got {c.get('bcg_fail_count')}")


@pytest.mark.slow
def test_aggressive_thresh_triggers_drift_rebuilds():
    """Very tight drift threshold (1e-12) → any movement triggers extra
    rebuild on iters where the drift check ran. Asserts the drift branch
    can fire, not exact counts (depends on how many SIMPLE iters converge).
    """
    s = _make_solver(drift_thresh=1e-12)
    s.solve(max_iter=10, tol=1e-6)
    c = s._ml_cache
    assert c.get('rebuild_count', 0) >= 2, (
        f"expected cold + drift rebuilds (>=2), "
        f"got {c.get('rebuild_count')}")
    # Either drift_rebuild_count > 0 OR skip_count > 0 (drift check ran).
    assert (c.get('drift_rebuild_count', 0) + c.get('skip_count', 0)) >= 1


@pytest.mark.slow
def test_legacy_mode_disable_drift_check():
    """drift_thresh=0 → drift check disabled → cadence-only behaviour.

    With max_iter=20 < pyamg_rebuild_every=100, no cadence hits after
    it=1 → exactly 1 rebuild, 0 skips (drift check did not run, so
    skip_count never gets set).
    """
    s = _make_solver(drift_thresh=0.0)
    s.solve(max_iter=20, tol=1e-6)
    c = s._ml_cache
    assert c.get('rebuild_count', 0) == 1
    assert c.get('skip_count', 0) == 0
    assert c.get('drift_rebuild_count', 0) == 0
    # Drift-check internal key never written
    assert 'diag_norm_now' not in c


@pytest.mark.slow
def test_instrumentation_keys_populated():
    """Verify the _ml_cache contains the documented diagnostic keys."""
    s = _make_solver(drift_thresh=0.05)
    s.solve(max_iter=5, tol=1e-6)
    c = s._ml_cache
    for key in ('rebuild_count', 'rebuild_time', 'bcg_time', 'bcg_calls'):
        assert key in c, f"missing instrumentation key {key!r}"
    assert c['rebuild_time'] > 0.0
    assert c['bcg_time'] > 0.0
    assert c['bcg_calls'] >= 1


@pytest.mark.slow
def test_warm_restart_reuses_cached_hierarchy():
    """E2 (audit 2026-06-28): solve() is warm-restarted up to _MAX_OUTER times in
    the 3D outer SIMPLE-LTNE loop, keeping self._ml_cache across calls. The
    unconditional rebuild=(it==1) force discarded the still-valid hierarchy on
    the first inner iter of EVERY solve() — even though the matrix only drifted
    by the alpha_T under-relaxed rho/mu change (sub-threshold). With the it==1
    force gated to a cold cache, a warm restart whose drift is below the 5 %
    threshold must NOT rebuild."""
    s = _make_solver(drift_thresh=0.05)        # static K -> sub-threshold drift
    s.solve(max_iter=5, tol=1e-6)
    first = s._ml_cache.get('rebuild_count', 0)
    assert 'ml' in s._ml_cache and first >= 1   # cold build happened
    s.solve(max_iter=5, tol=1e-6)              # WARM restart (cache persists)
    second = s._ml_cache.get('rebuild_count', 0)
    assert second == first, (
        f"warm restart force-rebuilt the still-valid AMG hierarchy "
        f"({first} -> {second}); the it==1 force should be gated to a cold cache "
        f"so the drift check (sub-threshold here) decides")


def test_constructor_accepts_drift_kwarg():
    """Smoke: new kwarg accepted + persisted as float on the instance."""
    s = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0,
        pyamg_rebuild_drift_thresh=0.07)
    assert s.pyamg_rebuild_drift_thresh == pytest.approx(0.07)


def test_coarse_bootstrap_init_param_passthrough():
    """Option B: `use_coarse_bootstrap` constructor kwarg persists on the
    instance, None is the default sentinel (auto-resolve in solve())."""
    # Default: None (auto-resolve in solve based on N)
    s = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0)
    assert s.use_coarse_bootstrap is None
    # Explicit True/False honoured
    s2 = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0,
        use_coarse_bootstrap=True)
    assert s2.use_coarse_bootstrap is True
    s3 = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0,
        use_coarse_bootstrap=False)
    assert s3.use_coarse_bootstrap is False


@pytest.mark.slow
def test_coarse_bootstrap_auto_enables_on_large_grid():
    """Option B: Default `use_coarse_bootstrap=None` triggers bootstrap on
    N>30 k grids. Asserts `_coarse_bootstrap_info['applied']` True after solve."""
    # 36 k cells: above AMG gate, auto-enable expected
    s = _make_solver(use_coarse_bootstrap=None)  # None → auto
    s.solve(max_iter=5, tol=1e-6)
    bs_info = getattr(s, '_coarse_bootstrap_info', {})
    assert bs_info.get('applied', False) is True, (
        f"bootstrap should auto-enable on 36 k grid, info={bs_info}")


@pytest.mark.slow
def test_coarse_bootstrap_explicit_false_disables_auto():
    """Option B: Explicit `use_coarse_bootstrap=False` overrides auto-enable
    even on large grids."""
    s = _make_solver(use_coarse_bootstrap=False)
    s.solve(max_iter=5, tol=1e-6)
    # _coarse_bootstrap_info either missing or applied=False
    bs_info = getattr(s, '_coarse_bootstrap_info', {})
    assert bs_info.get('applied', False) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
