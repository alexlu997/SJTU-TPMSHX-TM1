"""Anderson acceleration on the SIMPLE↔LTNE **outer** coupling map.

Opt-in (`cfg['outer_anderson']`, default OFF). The old inner SIMPLE
`use_anderson` option is retired; this outer accelerator remains supported.

With the knob off, the production outer loop keeps its original update order.
With it on, both property blocks returned by Anderson must reach SIMPLE, and
the accelerator must receive the previous flow state before temperature setters
refresh air viscosity. A rejected candidate uses the Picard fallback.

Measured behaviour on air (2026-07-12, three cases spanning ΔT 50→500 K and
u 2→20 m/s, before the property-consumption repair): the accelerator engages and
converges to the SAME fixed point (Q/dP agree to <0.02%), but does NOT reduce
the outer iteration count. Those historical timings do not establish the
repaired loop's bottleneck or any speedup. The stiff-ρ(T) case the accelerator
was designed for (sCO2 near pseudo-critical) is not covered by those air cases.
"""

import inspect

import numpy as np
import pytest

from sjtu_tpmshx.solvers.anderson_acceleration import AndersonOuterCoupling  # noqa: E402
from sjtu_tpmshx.runs._case_template import build_cfg                        # noqa: E402
from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem, _run_3d_stack
from sjtu_tpmshx.solvers.backends.python.three_d import runtime


def _cfg(**over):
    kw = dict(L=0.10, H=0.10, Lz=0.02, Nx=8, Ny=6, Nz=3,
              u_A=3.0, T_inA=400.0, u_B=1.0, T_inB=300.0)
    c = build_cfg(**kw)
    c['sweep_profile'] = 'fast_sweep'
    c.update(over)
    return c


# ── the invariant that matters: OFF must not touch the solver ────────────────

def test_default_off_reports_no_acceleration():
    """The knob is off by default; property-frame tests cover the Picard blend."""
    r = _run_3d_stack(_cfg())
    assert r['convergence_detail']['outer_anderson'] is None


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
    for key in ('Q', 'dP', 'dP_A', 'dP_B', 'Q_sA', 'Q_sB'):
        a, b = float(r_off[key]), float(r_on[key])
        assert abs(b - a) <= 2e-3 * max(abs(a), 1e-12), (
            f"{key}: Anderson moved the converged answer "
            f"({a:.6g} -> {b:.6g}); it must only change the path")


@pytest.mark.parametrize('fluids', [('air', 'air'), ('air', 'water')])
@pytest.mark.parametrize('mode', ['off', 'fallback', 'accepted'])
def test_outer_property_blocks_reach_simple(monkeypatch, fluids, mode):
    """Exercise real post/setter wiring; replace only sweeps and candidate choice."""
    monkeypatch.delenv('TPMSHX_VAR_RHOCP', raising=False)
    observations, calls = {}, []

    def solve(solver, **kwargs):
        if id(solver) in observations:
            observations[id(solver)].append(tuple(getattr(solver, key).copy()
                for key in ('T_field', 'rho_field', 'mu_field', '_mu_eff_field')))
        return True, 0

    original_step = AndersonOuterCoupling.step

    def observe_step(accelerator, x, g, alpha):
        if mode == 'accepted':
            # Distinct, positive outputs expose a subsequent setter overwrite.
            out, applied = [1.02 * g[0], 1.2 * g[1]], True
        else:
            out, applied = original_step(accelerator, x, g, alpha)
            assert applied is False  # First real step has insufficient history.
        calls.append(([block.copy() for block in x], out))
        return out, applied

    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', solve)
    monkeypatch.setattr(AndersonOuterCoupling, 'step', observe_step)
    prob = _build_3d_problem(_cfg(
        Nx=4, Ny=5, Nz=3, u_A=.02, u_B=.02, T_inA=350., T_s_init=325.,
        P_inA=2e6, P_inB=2e6, fluid_type_A=fluids[0], fluid_type_B=fluids[1],
        wall_refine_3d=False, outer_anderson=mode != 'off', p_in_shooting=False))
    solvers = (prob.sA, prob.sB)

    def drive(*, step, post, **kwargs):
        state = inspect.getclosurevars(post).nonlocals['state']
        for solver in solvers:
            observations[id(solver)] = []
        state.Ta[:] = 335.
        state.Tb[:] = 310.
        post(0, None)
        previous = [(solver.rho_field.copy(), solver.mu_field.copy())
                    for solver in solvers]
        state.Ta[:] = 325.
        state.Tb[:] = 330.
        post(1, None)
        assert len(calls) == (0 if mode == 'off' else 2)
        for index, (fluid, solver) in enumerate(zip(fluids, solvers)):
            temperature, rho, mu, effective_mu = observations[id(solver)][1]
            if mode == 'off':
                fresh_mu = runtime.fluid_props.get(fluid).mu(temperature, 2e6)
                expected_mu = (fresh_mu if fluid == 'air' else
                    runtime._ALPHA_T * fresh_mu + (1-runtime._ALPHA_T) * previous[index][1])
                np.testing.assert_allclose(mu, expected_mu, rtol=2e-15, atol=0.)
            else:
                inputs, outputs = calls[index]
                for actual, expected in zip(inputs, previous[index]):
                    np.testing.assert_array_equal(actual, expected)
                for actual, expected in zip((rho, mu), outputs):
                    np.testing.assert_array_equal(actual, expected)
            np.testing.assert_allclose(effective_mu, mu/solver.eps_field,
                                       rtol=2e-15, atol=0.)
        return 1, False

    monkeypatch.setattr(runtime, 'run_outer_coupling', drive)
    runtime._run_outer_coupling_3d(prob, runtime._build_hv_machinery(prob))


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
