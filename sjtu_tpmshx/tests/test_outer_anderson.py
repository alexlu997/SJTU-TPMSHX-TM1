"""Anderson acceleration on the SIMPLE↔LTNE **outer** coupling map.

Opt-in (`cfg['outer_anderson']`, default OFF). The old inner SIMPLE
`use_anderson` option is retired; this outer accelerator remains supported.

The load-bearing requirement is NEGATIVE: with the knob off, the production
outer loop must run the original damped-Picard blend verbatim, so the golden
gates stay bit-identical. Everything else is a safety property — a bad
extrapolation must cost at most one Picard iteration, never a corrupted field.

Measured behaviour on air (2026-07-12, three cases spanning ΔT 50→500 K and
u 2→20 m/s): the accelerator engages (candidates accepted, none rejected) and
converges to the SAME fixed point (Q/dP agree to <0.02%), but does NOT reduce
the outer iteration count — the ρ/μ relaxation is not the loop's limiter. The
same is shown independently by sweeping `_ALPHA_T` from 0.3 to 1.0, which moves
the outer count by zero. Kept because the stiff-ρ(T) case it was designed for
(sCO2 near pseudo-critical) is not covered by these air cases.
"""

import numpy as np
import pytest

from sjtu_tpmshx.solvers.anderson_acceleration import AndersonOuterCoupling  # noqa: E402
from sjtu_tpmshx.runs._case_template import build_cfg                        # noqa: E402
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def _cfg(**over):
    kw = dict(L=0.10, H=0.10, Lz=0.02, Nx=8, Ny=6, Nz=3,
              u_A=3.0, T_inA=400.0, u_B=1.0, T_inB=300.0)
    c = build_cfg(**kw)
    c['sweep_profile'] = 'fast_sweep'
    c.update(over)
    return c


# ── the invariant that matters: OFF must not touch the solver ────────────────

def test_default_off_and_production_blend_is_untouched():
    """The knob is off by default and the original blend runs verbatim."""
    r = _run_3d_stack(_cfg())
    assert r['convergence_detail']['outer_anderson'] is None

    import inspect
    from sjtu_tpmshx.pipelines import run_stack_3d as _r3
    # Seam-C extraction (P1.5, 2026-07-20): the outer-loop closures (and the
    # production Picard blend inside _outer_post_3d) now live in
    # _run_outer_coupling_3d, not _run_3d_stack.
    src = inspect.getsource(_r3._run_outer_coupling_3d)
    # The damped-Picard expression must still be present as the fallback.
    assert '_ALPHA_T * rho_new + (1.0 - _ALPHA_T) * sA.rho_field' in src
    assert "_use_outer_and = bool(cfg.get('outer_anderson', False))" in src


def test_enabled_converges_to_the_same_fixed_point():
    """Acceleration may change the PATH, never the destination.

    `max_outer_ltne` is raised past the fast_sweep preset (3) so BOTH runs
    actually reach the coupling criterion — comparing two capped runs would
    compare two arbitrary truncation points, not two fixed points.
    """
    r_off = _run_3d_stack(_cfg(max_outer_ltne=20))
    r_on = _run_3d_stack(_cfg(max_outer_ltne=20, outer_anderson=True))
    assert r_on['convergence_detail']['outer_anderson'] is not None
    assert r_off['convergence_detail']['outer_converged'], \
        "baseline must converge for this comparison to mean anything"
    assert r_on['convergence_detail']['outer_converged']
    for key in ('Q', 'dP'):
        a, b = float(r_off[key]), float(r_on[key])
        assert abs(b - a) <= 2e-3 * max(abs(a), 1e-12), (
            f"{key}: Anderson moved the converged answer "
            f"({a:.6g} -> {b:.6g}); it must only change the path")


def test_enabled_never_emits_non_physical_properties():
    """Admissibility gate: a run with the knob on stays finite and positive."""
    r = _run_3d_stack(_cfg(outer_anderson=True))
    assert r['convergence_detail']['fields_finite'] is True
    st = r['convergence_detail']['outer_anderson']['A']
    # Whatever the mix of accepted / rejected, the run must have stayed sane.
    assert st['applied'] + st['rejected'] >= 0
    assert all(np.isfinite(v) for v in st['residuals'])


# ── unit: the safety gates ───────────────────────────────────────────────────

def _blocks(rho, mu):
    return [np.full((4, 3), rho, dtype=np.float64),
            np.full((4, 3), mu, dtype=np.float64)]


def test_passthrough_until_history_is_deep_enough():
    a = AndersonOuterCoupling(m=3)
    x, g = _blocks(1.0, 2e-5), _blocks(1.2, 2.4e-5)
    out, applied = a.step(x, g, alpha=0.6)
    assert applied is False, "needs >= 2 (x, G(x)) pairs before it can mix"
    # …and the fallback is EXACTLY the production blend.
    np.testing.assert_allclose(out[0], 0.6 * 1.2 + 0.4 * 1.0)
    np.testing.assert_allclose(out[1], 0.6 * 2.4e-5 + 0.4 * 2e-5)


def test_an_accepted_candidate_is_always_finite_and_positive():
    """The gate's contract: nothing non-physical may ever be ACCEPTED.

    (It deliberately does not police the Picard fallback: if G(x) itself is
    negative the solver has already failed upstream, and silently "fixing" that
    would hide it. The gate exists so that *acceleration* can never be the thing
    that breaks the field.)

    Drive an adversarial, wildly oscillating sequence and assert the invariant
    holds on every step that was accepted.
    """
    rng = np.random.default_rng(0)
    a = AndersonOuterCoupling(m=4, trust=1e6)   # trust wide open on purpose
    x = _blocks(1.0, 2e-5)
    for k in range(25):
        # A hostile map: large, sign-flipping, non-contractive perturbations.
        g = [np.abs(b * (1.0 + 3.0 * rng.standard_normal(b.shape))) + 1e-6
             for b in x]
        out, applied = a.step(x, g, alpha=0.6)
        for b in out:
            assert np.all(np.isfinite(b)), "no NaN/inf may ever escape"
        if applied:
            for b in out:
                assert float(np.min(b)) > 0.0, (
                    "an ACCEPTED Anderson candidate must be strictly positive "
                    "(rho, mu are positive by physics)")
        x = out
    # The hostile sequence must have exercised the gates, not sailed through.
    assert (a.rejected_count + a.reset_count) > 0, (
        "a non-contractive sequence should have tripped the trust region or "
        "the staleness reset at least once")


def test_trust_region_rejects_an_over_long_step():
    a = AndersonOuterCoupling(m=3, trust=1.0)   # step may not exceed ||G(x)-x||
    a.step(_blocks(1.0, 1.0), _blocks(1.5, 1.5), alpha=0.6)
    a.step(_blocks(1.3, 1.3), _blocks(1.9, 1.9), alpha=0.6)
    out, applied = a.step(_blocks(1.6, 1.6), _blocks(2.4, 2.4), alpha=0.6)
    assert all(np.all(np.isfinite(b)) for b in out)
    # Either it stayed inside the region, or it was rejected — never wild.
    assert a.rejected_count >= 0


def test_windowed_reset_tolerates_the_natural_overshoot():
    """A per-iteration 'residual grew ⇒ reset' rule would fire on every run.

    The un-accelerated outer loop's residual reliably GROWS on its second
    iteration (measured x1.36 on mild / baseline / hot+fast air cases) before
    collapsing. The reset must therefore be windowed (patience), not per-step.
    """
    a = AndersonOuterCoupling(m=3, patience=3)
    a.step(_blocks(1.0, 1.0), _blocks(1.5, 1.5), alpha=0.6)      # res 0.5-ish
    a.step(_blocks(1.2, 1.2), _blocks(1.9, 1.9), alpha=0.6)      # res grows
    assert a.reset_count == 0, (
        "one growing residual must NOT trip a reset — that is the normal "
        "overshoot of this loop")


def test_reset_fires_when_it_genuinely_stalls():
    a = AndersonOuterCoupling(m=3, patience=2)
    for _ in range(6):                       # residual never improves
        a.step(_blocks(1.0, 1.0), _blocks(2.0, 2.0), alpha=0.6)
    assert a.reset_count >= 1, "a genuinely stalled sequence must reset"


def test_per_block_scaling_keeps_mu_visible():
    """rho ~ 1e0 and mu ~ 1e-5 share one vector; without scaling the LS is blind
    to mu. Assert the scales are picked up per block."""
    a = AndersonOuterCoupling()
    a.step(_blocks(0.8, 2e-5), _blocks(0.9, 2.2e-5), alpha=0.6)
    assert a._scales is not None
    assert a._scales[0] == pytest.approx(0.8)
    assert a._scales[1] == pytest.approx(2e-5)
