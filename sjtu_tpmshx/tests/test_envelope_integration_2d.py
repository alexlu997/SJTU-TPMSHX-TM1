"""End-to-end compressible validity gate in the 2D pipeline (_run_solvers).

REWRITTEN 2026-07-12 (ledger C8). The previous version asserted that a
Δp ≈ 3 × P_in operating point produces a VALID result, on the grounds that "the
2D path is inlet-anchored: a large dP raises the inlet absolute pressure instead
... so the solve stays physical".

That was pinning a BUG as a feature.

`P_ref_abs` is the OUTLET absolute pressure — the pp equation pins the outlet row
at `Pp = 0` and never corrects those cells' P, so the outlet's gauge pressure
stays 0 for the whole solve. `stages_2d` was passing `P_ref_abs = P_in`, which
anchors the OUTLET at the INLET pressure and lets the field run from P_in up to
P_in + Δp. Everything stayed positive, so the gate had nothing to catch — but the
density was wrong everywhere, and at Δp ≈ 3 × P_in the operating point is one
whose true outlet pressure would be **−2 atm**.

There is no steady solution there. The physical invariant in
``docs/architecture.md`` says so:

    "valid only while the Forchheimer Δp stays below the inlet absolute pressure
     ... Once Δp ≳ P_in the outlet goes to vacuum, the flow chokes / goes
     supersonic, and NO steady solution exists"

So the correct assertion is the OPPOSITE of the old one: with the datum at the
right end, Δp ≈ 3 × P_in must be REJECTED, exactly as 3D rejects it. The old test
was the very thing the invariant forbids — a ChokedFlowError made to go away by
arranging for the guard never to fire.
"""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
from sjtu_tpmshx.solvers.envelope import ChokedFlowError
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


def _run_2d(u, L=0.182, Nx=20, Ny=20):
    base = ComputeConfig()
    cfg = replace(
        base,
        geometry=replace(base.geometry, t_wall_mm=0.5, L_dom_m=L),
        fluid_A=replace(base.fluid_A, u_mps=u),
        solver=replace(base.solver, Nx=Nx, Ny=Ny, max_outer_ltne=2))
    pipe = Pipeline2D(cfg)
    fields = pipe.build_fields()
    return mutable_data(pipe.run_solvers(fields).metadata['diagnostics'])


def test_2d_in_envelope_reports_valid_with_gate_keys():
    """Inside the envelope the gate stays quiet and carries its keys."""
    raw = _run_2d(u=5.0, L=0.182)
    assert raw['envelope_valid'] is True
    assert raw['p_clip_hits'] == 0
    assert raw['envelope_reasons'] == []


def test_2d_outlet_is_anchored_below_the_inlet():
    """The load-bearing invariant behind everything else here (ledger C8).

    `P_ref_abs` IS the outlet absolute pressure, because the outlet row is the
    pinned gauge-zero reference. A forward-flowing compressible solve must
    therefore end with

        outlet absolute pressure  <  inlet absolute pressure

    and that is only true if `P_ref_abs` is seeded from the predicted OUTLET
    pressure. Seeding it from `P_in` (the old behaviour) inverts the whole thing:
    the outlet lands AT the inlet pressure and the inlet floats to P_in + Δp.
    """
    seen = []
    orig = SIMPLESolver.solve

    def _spy(self, *a, **kw):
        out = orig(self, *a, **kw)
        if self.fluid_type == 'ideal_gas':
            P_abs = self.P_ref_abs + self.P            # gauge -> absolute
            seen.append((float(np.mean(P_abs[:, 0])),    # inlet plane
                         float(np.mean(P_abs[:, -1])),   # outlet plane
                         float(self.P_ref_abs)))
        return out

    SIMPLESolver.solve = _spy
    try:
        _run_2d(u=15.0, L=0.182)
    finally:
        SIMPLESolver.solve = orig

    assert seen, "no compressible solve was captured"
    p_in, p_out, p_ref = seen[-1]
    assert p_out < p_in, (
        f"outlet ({p_out:.0f} Pa) is not below the inlet ({p_in:.0f} Pa) — the "
        "pressure datum is anchored at the wrong end (ledger C8)")
    assert p_out == pytest.approx(p_ref, rel=1e-9), (
        "the outlet absolute pressure must EQUAL P_ref_abs: the pp equation pins "
        "the outlet row and its P is never corrected")
    assert p_out > 0.0, "absolute pressure must stay positive"


def test_2d_choked_operating_point_is_rejected():
    """Δp ≈ 3 × P_in has NO steady solution — 2D must reject it, as 3D does.

    This is the test that used to assert the opposite ("not falsely flagged").
    It passed only because the outlet was anchored at the inlet pressure, so the
    field never approached vacuum and the gate had nothing to catch. With the
    datum at the correct end, this operating point is what it always physically
    was: choked. Rejecting it IS the correct behaviour.

    NEVER "fix" a failure here by widening the guard, clipping harder, or
    reverting the anchor. Move the operating point (lower u, shorter L, higher
    P_in) — see ``docs/architecture.md``.
    """
    with pytest.raises(ChokedFlowError):
        _run_2d(u=40.0, L=0.7)


def test_2d_high_but_subsonic_dp_still_solves():
    """The guard must not be trigger-happy. A large but IN-ENVELOPE Δp still has
    a steady solution and must still be accepted — this is what stops someone
    "fixing" the test above by tightening the envelope until real designs fail.
    """
    raw = _run_2d(u=15.0, L=0.182)
    assert raw['envelope_valid'] is True, raw['envelope_reasons']
    P_in = ComputeConfig().fluid_A.P_in_Pa
    assert 0.0 < raw['dP_A'] < P_in, (
        f"expected a large but sub-choke dP, got {raw['dP_A']:.0f} Pa against "
        f"P_in = {P_in:.0f} Pa")
