"""C8 shooting loop (openspec c8-p-in-shooting) — behavioural contract.

`P_ref_abs` is the OUTLET absolute pressure (ledger C8): the realized inlet
absolute pressure is P_ref_abs + dP_solved. Both pipelines seed the anchor
from the 1D compressible Forchheimer closed form, which only ESTIMATES the
drag. The 3D correction test imposes a known estimate bias, rather than
depending on a particular wall model to produce one. With the knob ON the outer
loop reseeds from the MEASURED drag via the P² update

    P_out²_new = P_in² − (realized_prev² − P_ref_prev²)

whose fixed point is realized == P_in exactly.

These tests pin: (1) the update algebra (fixed point + one-shot landing under
exact-P²-law physics), (2) 3D pipeline ON lands on spec AND beats OFF,
(3) 2D pipeline ON lands on spec (tolerance chosen BELOW the measured OFF
bias, so a silently dead knob fails), (4) incompressible sides stay out
(NaN diagnostics, no crash on mixed-fluid runs).
"""
import numpy as np
import pytest

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.runs._out._golden_3d import _air_air_cfg as _cfg3d_air_air


def _shoot_update(P_in, P_ref, dP):
    """The C8 P² update, verbatim algebra (both dims implement this)."""
    P_out_sq = P_in ** 2 - dP * (dP + 2.0 * P_ref)
    return float(np.sqrt(max(P_out_sq, 1.0e4)))


# ── (1) update algebra ─────────────────────────────────────────────────


def test_p2_update_fixed_point():
    """realized == P_in  ⟹  the anchor does not move (exact fixed point)."""
    P_in, P_ref = 304746.0, 98121.0
    dP = P_in - P_ref                      # realized == spec
    assert _shoot_update(P_in, P_ref, dP) == pytest.approx(P_ref, rel=1e-12)


def test_p2_update_one_shot_under_exact_p2_law():
    """If the solver's drag follows the 1D P² law exactly, ONE shot lands.

    Physics: for fixed G the compressible invariant is P_in² − P_out² =
    2RT̄CL (level-free). Seed the anchor WRONG, evaluate the 'solved' dP from
    the law at that wrong anchor, apply the update — the new anchor must
    reproduce the true P_out* to machine precision (this is why the P² form
    beats the linear fixed point, whose contraction is only ~1−P_out/P_in).
    """
    P_in = 304746.0
    invariant = 2.0 * 287.05 * 400.0 * 180.0 * 0.182      # 2RT·C·L, arbitrary
    P_out_true = np.sqrt(P_in ** 2 - invariant)
    P_ref_wrong = P_out_true * 0.85                       # badly wrong seed
    # "solve" at the wrong anchor: realized inlet obeys the P² law from there
    realized = np.sqrt(P_ref_wrong ** 2 + invariant)
    dP_solved = realized - P_ref_wrong
    P_ref_new = _shoot_update(P_in, P_ref_wrong, dP_solved)
    assert P_ref_new == pytest.approx(P_out_true, rel=1e-12)


def test_p2_update_choke_floors():
    """Measured drag ≥ spec inlet pressure ⇒ P_out² ≤ 0 ⇒ the 1e4 Pa floor
    (2D posture; 3D routes the same quantity through _seed_p_ref's gate)."""
    assert _shoot_update(1.0e5, 5.0e4, 2.0e5) == pytest.approx(100.0)


# ── (2) 3D pipeline: ON lands on spec and beats OFF ────────────────────


_FULL_B_3D = dict(dir=3, in_ctr=0.021, in_w=0.042, out_ctr=0.021, out_w=0.042,
                  in_z_ctr=0.021, in_z_w=0.042, out_z_ctr=0.021, out_z_w=0.042)


@pytest.fixture(scope="module")
def _res3d_pair():
    """Real solves with a known 2% low pressure estimate on side A.

    The no-slip wall model makes the unperturbed estimate too accurate to
    distinguish a dead shooting knob. Bias only the estimated seeds; leave
    the measured-drag shooting update and every acceptance threshold intact.
    """
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages

    original_seed = stages._seed_p_ref

    def biased_estimate(*args, **kwargs):
        value = original_seed(*args, **kwargs)
        context = kwargs['context']
        return .98 * value if context.startswith('fluid A ') and 'shooting' not in context else value

    base = dict(Nx=12, Ny=12, Nz=12, u_A=16.0, u_B=5.0,
                fluid_B_cfg=dict(_FULL_B_3D))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(stages, '_seed_p_ref', biased_estimate)
        r_off = _run_3d_stack(_cfg3d_air_air(**base))
        r_on = _run_3d_stack(_cfg3d_air_air(**base, p_in_shooting=True))
    return r_off, r_on


def test_3d_shooting_lands_on_spec(_res3d_pair):
    r_off, r_on = _res3d_pair
    resid_off = r_off['P_in_shoot_resid_A']
    resid_on = r_on['P_in_shoot_resid_A']
    # OFF: the legacy bias must be visible (this is what C8 is about) —
    # otherwise the ON assertion below has no teeth at this operating point.
    assert abs(resid_off) > 5e-3, (
        f"controlled estimate bias not visible: legacy resid {resid_off:.2%}")
    # ON: realized inlet lands on the specified P_in.
    assert abs(resid_on) < 2e-3, (
        f"shooting did not land: realized {r_on['P_in_realized_A']:.0f} vs "
        f"spec, resid {resid_on:.2%}")
    assert abs(resid_on) < abs(resid_off) / 3.0


def test_3d_diagnostic_keys_present_and_finite(_res3d_pair):
    r_off, _ = _res3d_pair
    for k in ('P_in_realized_A', 'P_in_shoot_resid_A',
              'P_in_realized_B', 'P_in_shoot_resid_B'):
        assert k in r_off, f"missing diagnostic key {k}"
        assert np.isfinite(r_off[k]), f"{k} not finite on an air-air run"


def test_3d_shooting_rejects_overloaded_measured_drag(monkeypatch):
    """A known overloading pressure measurement must reach the choke guard.

    The original partial-port point no longer necessarily chokes with the
    no-slip walls. Inject the measurement, not a new physical operating point;
    keep the real shooting P² update and its original envelope check.
    """
    from sjtu_tpmshx.solvers.envelope import ChokedFlowError
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
    cfg = _cfg3d_air_air(Nx=12, Ny=12, Nz=12, p_in_shooting=True)
    monkeypatch.setattr(SIMPLESolver3D, 'extract_dP_face_extrap',
                        staticmethod(lambda solver: 2.0 * cfg['P_inA']))
    with pytest.raises(ChokedFlowError, match='shooting reseed'):
        _run_3d_stack(cfg)


# ── (3)/(4) 2D pipeline ────────────────────────────────────────────────


def _cfg2d(fluid_B='air'):
    from sjtu_tpmshx.domain.compute_config import (
        ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
        PartialBCConfig, ExtrapPolicy, FeatureFlags,
    )
    fB = (FluidConfig(type='air', u_mps=20.0, T_in_K=322.0, P_in_Pa=101325.0)
          if fluid_B == 'air' else
          FluidConfig(type='water', u_mps=0.15, T_in_K=300.0,
                      P_in_Pa=101325.0))
    return ComputeConfig(
        # u_A 10 → 15 m/s vs the golden cfg: pushes the legacy seed bias
        # well above the 2e-3 assertion tolerance (dead-knob teeth).
        fluid_A=FluidConfig(type='air', u_mps=15.0, T_in_K=422.0,
                            P_in_Pa=192362.0),
        fluid_B=fB,
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.182, H_dom_m=0.042),
        solver=SolverConfig(Nx=20, Ny=20),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )


def test_2d_shooting_lands_on_spec(monkeypatch):
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    monkeypatch.setenv('TPMSHX_P_IN_SHOOT', '1')
    monkeypatch.setenv('TPMSHX_CONV_MODE', 'f2')   # pin criterion (C11 lesson)
    res = Pipeline2D(_cfg2d()).run()
    d = res.diagnostics   # forwarded by the public result adapter
    for side in ('A', 'B'):
        resid = d[f'P_in_shoot_resid_{side}']
        assert np.isfinite(resid)
        assert abs(resid) < 2e-3, (
            f"2D side {side} did not land: realized "
            f"{d[f'P_in_realized_{side}']:.0f}, resid {resid:.2%}")


def test_2d_water_side_inert_nan_keys(monkeypatch):
    """Mixed-fluid run with the knob ON: water B must stay out of the
    shooting (frozen-ρ P_ref is level-inert) — NaN diagnostics, no crash —
    while air A still lands."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    monkeypatch.setenv('TPMSHX_P_IN_SHOOT', '1')
    monkeypatch.setenv('TPMSHX_CONV_MODE', 'f2')
    res = Pipeline2D(_cfg2d(fluid_B='water')).run()
    d = res.diagnostics
    assert abs(d['P_in_shoot_resid_A']) < 2e-3
    assert np.isnan(d['P_in_realized_B'])
    assert np.isnan(d['P_in_shoot_resid_B'])
