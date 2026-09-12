"""Headline heat duty Q must be the AIR/A-side enthalpy, not the old
0.5*(Q_A + Q_B) average.

The B/water-side advective enthalpy (Q_enthalpy_B = m_B*cp*dT_B) drops the
boundary-conduction flux, so it over/under-reads by ~8 % even when the scheme
conserves. Averaging it into the headline made the displayed Q drift
non-physically (e.g. it ROSE when the coolant flow FELL). The air-side enthalpy
matches the experiment-validated duty (validation/cases/validate_shanghai_3d_real
computes the same m_air*cp*dT_A; RMSRE ~3 %), so the headline now reports it
directly. Q_enthalpy_B stays in the result dict as a transparent diagnostic.
"""

import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def _air_water_cfg():
    """Air A (+x, full-face) heating cross-flow water B (+y, full-face).
    Two-fluid so Q_enthalpy_B > 0 and the A/B advective-enthalpy gap is real."""
    cc = ComputeConfig(
        fluid_A=FluidConfig(type='air',   u_mps=10.0, T_in_K=420.0, P_in_Pa=190000.0),
        fluid_B=FluidConfig(type='water', u_mps=0.30, T_in_K=300.0, P_in_Pa=120000.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.5,
                                k_s_W_mK=16.0, L_dom_m=0.182, H_dom_m=0.042, Lz_m=0.042),
        solver=SolverConfig(Nx=16, Ny=10, Nz=4),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        bc_B=PartialBCConfig(dir=2, in_ctr=0.091, in_w=0.182,
                             out_ctr=0.091, out_w=0.182),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(wall_refine_3d=False),
    )
    return _parse_inputs_3d_cfg(cc)


def test_headline_q_equals_air_side_enthalpy():
    res = _run_3d_stack(_air_water_cfg())
    Q = res['Q']
    Q_A = res['Q_enthalpy_A']
    Q_B = res['Q_enthalpy_B']

    # Fixture sanity: two-fluid case (Q_enthalpy_B > 0). NOTE: the A/B
    # advective-enthalpy gap shrank from ~8 % to ~0.35 % after the 2026-06-09
    # reverse-conservation fix (PR #17 incompressible mass-balance tightened the
    # water-side accounting). The headline-SELECTION assertions below — Q == Q_A
    # and Q != mean — are the real test, not a gap magnitude, so the gap-size
    # guard was dropped (it broke once conservation improved).
    assert Q_B > 0.0, "fixture must exercise a two-fluid case (Q_enthalpy_B>0)"

    # The fix: headline Q is the air-side duty, NOT 0.5*(Q_A+Q_B).
    assert Q == pytest.approx(Q_A, rel=1e-9), (
        f"headline Q={Q:.3f} must equal air-side Q_enthalpy_A={Q_A:.3f}, "
        f"not the 0.5*(Q_A+Q_B)={0.5*(Q_A+Q_B):.3f} average")
    # Non-vacuous whenever A and B differ at all: the headline must NOT be the
    # mean. (Distinguishes the air-side pick from the old 0.5·(Q_A+Q_B) even for
    # a sub-percent gap; skipped only in the degenerate Q_A==Q_B limit.)
    if abs(Q_B - Q_A) > 1e-6 * Q_A:
        assert Q != pytest.approx(0.5 * (Q_A + Q_B), rel=1e-9), (
            f"headline Q={Q:.3f} must be the air-side duty, not the "
            f"0.5*(Q_A+Q_B)={0.5*(Q_A+Q_B):.3f} average")
