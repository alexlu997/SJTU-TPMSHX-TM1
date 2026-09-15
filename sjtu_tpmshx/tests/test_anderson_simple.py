"""Shared Anderson algebra and energy-step budget/rollback regressions."""
from __future__ import annotations
import numpy as np
import pytest

from sjtu_tpmshx.solvers.anderson_acceleration import AndersonSIMPLE


@pytest.mark.parametrize('bad_candidate', [False, True])
def test_energy_acceleration_budget_and_rollback(monkeypatch, bad_candidate):
    from sjtu_tpmshx.solvers.anderson_acceleration import advance_energy
    fields = [np.full((2, 3), 300.) for _ in range(3)]
    snapshots = [fields[0].copy()]
    calls = 0

    def step(count):
        nonlocal calls
        calls += count
        for _ in range(count):
            snapshots[0][:] = fields[0]
            residual = 0.
            for field in fields:
                update = .03 * (350. - field)
                residual = max(residual, float(np.max(np.abs(update))))
                field += update
        return residual

    if bad_candidate:
        monkeypatch.setattr(AndersonSIMPLE, 'candidate',
                            lambda self, x: (np.full_like(x, 1e6), True))
    residual = advance_energy(step, fields, 100, snapshots)
    assert calls == 100
    assert np.isfinite(residual)
    if bad_candidate:
        # Rejected trials consume budget without altering the accepted state.
        accepted_sweeps = 97
        expected = 350. - 50. * .97 ** accepted_sweeps
        np.testing.assert_allclose(fields[0], expected)
        np.testing.assert_allclose(snapshots[0], 350. - 50. * .97 ** (accepted_sweeps - 1))
    else:
        np.testing.assert_allclose(fields, 350., atol=1e-9, rtol=0.)


def test_anderson_accelerates_linear_fixed_point():
    """On a contracting linear map G(x) = A x + b with ρ(A) ~ 0.9, Anderson
    must reach |F| < 1e-8 in fewer Picard steps than vanilla iteration.
    """
    rng = np.random.default_rng(42)
    n = 50
    A = 0.9 * np.eye(n) + 0.05 * rng.standard_normal((n, n)) / np.sqrt(n)
    b = rng.standard_normal(n)

    def G(x):
        return A @ x + b

    # Vanilla Picard
    x = np.zeros(n)
    pic_iters = 0
    for k in range(2000):
        x_new = G(x)
        if np.linalg.norm(x_new - x) < 1e-8:
            pic_iters = k + 1
            break
        x = x_new
    else:
        pic_iters = 2000

    # Anderson
    acc = AndersonSIMPLE(m=5, K=1)
    x = np.zeros(n)
    and_iters = 0
    for k in range(2000):
        gx = G(x)
        acc.push(x, gx)
        if k >= 2:
            cand, applied = acc.candidate(gx)
            if applied:
                gx = cand
        if np.linalg.norm(gx - x) < 1e-8:
            and_iters = k + 1
            break
        x = gx
    else:
        and_iters = 2000

    # Anderson must converge faster (ratio ≥ 1.5 on this benchmark)
    assert and_iters < pic_iters, (
        f"Anderson did not accelerate: {and_iters} vs Picard {pic_iters}")
    assert and_iters * 1.5 <= pic_iters, (
        f"Anderson speedup < 1.5x: {pic_iters / and_iters:.2f}x")


def test_anderson_skips_rank_deficient():
    """When ΔR is rank-deficient the cond gate must skip Anderson cleanly."""
    acc = AndersonSIMPLE(m=3, K=1, cond_max=1e10)
    n = 10
    # Push identical (x, gx) pairs so all residuals are equal → ΔR = 0.
    x = np.zeros(n)
    gx = np.ones(n)
    acc.push(x, gx)
    acc.push(x, gx)
    acc.push(x, gx)
    cand, applied = acc.candidate(gx)
    # Should fall through to gx_picard (rank-deficient ΔR rejected).
    assert not applied
    assert np.allclose(cand, gx)
    assert acc.skipped_count >= 1
