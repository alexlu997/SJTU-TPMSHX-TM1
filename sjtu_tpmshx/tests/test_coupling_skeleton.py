"""Unit tests for solvers.coupling_skeleton — the shared outer-coupling
convergence tracker (OuterConvergence).

These lock the tracker contract used by the two_d (dual ΔT + Δρ) and
three_d (single ΔT) numerical backends under solvers/backends/python/.
This file pins the tracker and iteration-driver semantics. The separate
_golden_2d.py / _golden_3d.py tools are manual historical diagnostics;
current real-module execution checks live in integration_tm1/.
"""
from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence, run_outer_coupling


def _f(val, shape=(3, 3)):
    return np.full(shape, float(val))


# ── OuterConvergence ────────────────────────────────────────────────


def test_first_call_never_converges_and_reports_inf():
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    converged, deltas = c.check({'Ta': _f(400.0)})
    assert converged is False
    assert deltas['Ta'] == float('inf')


def test_single_field_converges_when_delta_below_tol():
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    c.check({'Ta': _f(400.0)})                      # seed prev
    converged, deltas = c.check({'Ta': _f(400.2)})  # ΔT = 0.2 < 0.5
    assert converged is True
    assert deltas['Ta'] == pytest.approx(0.2)


def test_single_field_not_converged_when_delta_above_tol():
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    c.check({'Ta': _f(400.0)})
    converged, deltas = c.check({'Ta': _f(401.0)})  # ΔT = 1.0 > 0.5
    assert converged is False
    assert deltas['Ta'] == pytest.approx(1.0)


def test_dual_field_requires_both_below_tol():
    c = OuterConvergence(tol_T=1.0, track=('Ta', 'Tb'))
    c.check({'Ta': _f(400.0), 'Tb': _f(300.0)})
    # Ta moves 0.3 (ok), Tb moves 2.0 (not ok) → AND-gate fails.
    converged, deltas = c.check({'Ta': _f(400.3), 'Tb': _f(302.0)})
    assert converged is False
    assert deltas['Ta'] == pytest.approx(0.3)
    assert deltas['Tb'] == pytest.approx(2.0)


def test_extra_criterion_blocks_convergence_even_if_temperature_ok():
    c = OuterConvergence(tol_T=1.0, track=('Ta',))
    c.check({'Ta': _f(400.0)})
    # ΔT = 0.1 < 1.0 but extra (e.g. drho) 0.05 > extra_tol 0.01.
    converged, _ = c.check({'Ta': _f(400.1)},
                           extra=(0.05,), extra_tol=0.01)
    assert converged is False
    # Same temperature step, extra now below tol → converges.
    c2 = OuterConvergence(tol_T=1.0, track=('Ta',))
    c2.check({'Ta': _f(400.0)})
    conv2, _ = c2.check({'Ta': _f(400.1)}, extra=(0.005,), extra_tol=0.01)
    assert conv2 is True


def test_extra_without_tol_raises():
    c = OuterConvergence(tol_T=1.0, track=('Ta',))
    c.check({'Ta': _f(400.0)})
    with pytest.raises(ValueError):
        c.check({'Ta': _f(400.1)}, extra=(0.01,))


def test_prev_is_copied_not_aliased():
    """In-place mutation of the passed field after check() must not corrupt
    the tracker's stored prev (it copies)."""
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    arr = _f(400.0)
    c.check({'Ta': arr})
    arr += 100.0                       # mutate the SAME array in place
    converged, deltas = c.check({'Ta': _f(400.2)})
    # If prev had aliased `arr`, prev would now read 500 and ΔT would be ~100.
    assert deltas['Ta'] == pytest.approx(0.2)
    assert converged is True


# ── run_outer_coupling ──────────────────────────────────────────────


def test_driver_breaks_on_convergence_and_skips_post_that_iter():
    """When step reports converged, the loop breaks BEFORE post — matching
    the legacy `if converged: break` placed before the update block."""
    step_calls, post_calls = [], []

    def step(it):
        step_calls.append(it)
        return (it == 2), ('carry', it)   # converge on iter 2

    def post(it, carry):
        post_calls.append((it, carry))

    last, conv = run_outer_coupling(max_iter=10, step=step, post=post)
    assert conv is True
    assert last == 2
    assert step_calls == [0, 1, 2]
    assert post_calls == [(0, ('carry', 0)), (1, ('carry', 1))]  # NOT iter 2


def test_driver_runs_post_every_noncoverged_iter_including_last():
    """The legacy loop ran its update block on every non-converged iter,
    including the final one when the cap is hit — preserved here."""
    posts = []

    def step(it):
        return False, it                  # never converges

    def post(it, carry):
        posts.append((it, carry))

    last, conv = run_outer_coupling(max_iter=3, step=step, post=post)
    assert conv is False
    assert last == 2
    assert posts == [(0, 0), (1, 1), (2, 2)]   # post ran on the final iter too


def test_driver_carry_threads_step_to_post():
    seen = []

    def step(it):
        return False, {'rho': it * 10}

    def post(it, carry):
        seen.append(carry['rho'])

    run_outer_coupling(max_iter=2, step=step, post=post)
    assert seen == [0, 10]


def test_driver_post_is_optional():
    steps = []

    def step(it):
        steps.append(it)
        return (it == 1), None

    last, conv = run_outer_coupling(max_iter=5, step=step)   # no post
    assert (last, conv) == (1, True)
    assert steps == [0, 1]


def test_driver_step_exception_propagates():
    """A cooperative cancel raised inside step must propagate unchanged,
    matching the inline `raise InterruptedError` in the legacy loop body."""
    def step(it):
        if it == 1:
            raise InterruptedError("cancelled")
        return False, None

    with pytest.raises(InterruptedError):
        run_outer_coupling(max_iter=5, step=step, post=lambda it, c: None)
