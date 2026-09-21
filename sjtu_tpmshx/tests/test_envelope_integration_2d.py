"""Actual 2D outlet datum, inlet-pressure matching and final-field validity.

A positive initial anchor is only a startup value. It never certifies the
specified inlet condition, which must match the final physical port face.
"""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
from sjtu_tpmshx.models.envelope import ChokedFlowError, PRESSURE_FLOOR_PA
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
    """The outlet cell datum must agree with the actual solved gauge field."""
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


def test_2d_overloaded_estimate_cannot_certify_unmatched_inlet():
    raw = _run_2d(u=40.0, L=0.7)
    state = raw['convergence_detail']['inlet_pressure']['A']
    assert state['iterations'][0]['method'] == 'inlet-pressure'
    assert not state['passed']
    assert not raw['solver_converged']


@pytest.mark.parametrize('side', ['A', 'B'])
def test_2d_actual_final_pressure_floor_still_raises(monkeypatch, side):
    from sjtu_tpmshx.solvers.backends.python.two_d import coupling
    original = coupling._compute_pressure_2d

    def invalid_final_field(a, b, *args):
        result = original(a, b, *args)
        # Inject at the final verdict boundary, leaving the real gate intact.
        solver = a if side == 'A' else b
        solver.P_ref_abs = PRESSURE_FLOOR_PA - float(solver.P.min())
        return result

    monkeypatch.setattr(coupling, '_compute_pressure_2d', invalid_final_field)
    with pytest.raises(ChokedFlowError, match=f'2D-{side}.*non-physical field'):
        _run_2d(u=5.)


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
