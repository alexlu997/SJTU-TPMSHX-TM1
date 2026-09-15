"""Physical inlet pressure: face geometry, P² update and both real pipelines."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.solvers._solve_common import (
    inlet_pressure_state, pressure_shooting_target_sq,
)
from sjtu_tpmshx.tests.cases_3d import air_air_cfg as _cfg3d_air_air


def _shoot_update(P_in, P_ref, dP):
    P_out_sq = pressure_shooting_target_sq(dict(
        specified_Pa=P_in, realized_Pa=P_ref + dP, outlet_Pa=P_ref))
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
    """Measured overload ⇒ P_out² ≤ 0 ⇒ the existing 100 Pa floor
    (2D posture; 3D routes the same quantity through _seed_p_ref's gate)."""
    assert _shoot_update(1.0e5, 5.0e4, 2.0e5) == pytest.approx(100.0)


@pytest.mark.parametrize('dimension', [2, 3])
def test_nonuniform_physical_faces_and_geometric_open_area(dimension):
    """Linear manufactured field has zero outlet cells but a negative face.

    Unequal cell sizes and partial openings distinguish geometric area from
    cell/profile weighting. A pressure state already on target must not move.
    """
    dy = np.array([.2, .3, .5])
    y = np.cumsum(dy) - dy / 2
    p = np.array([10000., 20000.])[:, None] * (y[-1] - y)
    geom = np.array([.5, 1.])
    solver = SimpleNamespace(fluid_type='ideal_gas', P=p, P_ref_abs=100000.,
                             dx=np.array([.01, .03]), dy=dy,
                             dx_arr=np.array([.01, .03]), dy_arr=dy,
                             inlet_geom_frac=geom, outlet_geom_frac=geom,
                             inlet_frac=np.array([1., 0.]), outlet_frac=geom)
    if dimension == 3:
        solver.P = np.repeat(p[:, :, None], 2, axis=2)
        solver.dz = np.array([.02, .04])
        solver.inlet_frac = solver.outlet_frac = np.repeat(geom[:, None], 2, axis=1)
    gradient = (10000. * .005 + 20000. * .03) / .035
    target = 100000. + .75 * gradient
    state = inlet_pressure_state(solver, target)
    assert state['realized_Pa'] == pytest.approx(target)
    assert state['outlet_gauge_Pa'] == pytest.approx(-.25 * gradient)
    assert state['outlet_Pa'] == pytest.approx(100000. - .25 * gradient)
    assert state['passed']
    corrected_anchor = np.sqrt(pressure_shooting_target_sq(state)) - state['outlet_gauge_Pa']
    assert corrected_anchor == pytest.approx(solver.P_ref_abs)


@pytest.mark.parametrize('direction', range(4))
def test_2d_air_thermal_and_report_use_actual_simple_pressure(direction):
    from sjtu_tpmshx.solvers.backends.python.two_d.coupling import (
        _simple_pressure_abs_2d, _compute_pressure_2d,
    )
    gauge = np.arange(12.).reshape(3, 4) * 1000.
    solver = SimpleNamespace(P=gauge, P_ref_abs=100000., fluid_type='ideal_gas',
                             inlet_frac=np.array([0., 1., 1.]), outlet_frac=np.ones(3))
    expected = gauge.T if direction < 2 else gauge
    if direction % 2:
        expected = np.flip(expected, axis=direction // 2)
    expected = expected + 100000.
    actual = _simple_pressure_abs_2d(solver, direction, 130000.)
    np.testing.assert_array_equal(actual, expected)
    a, b, _, _ = _compute_pressure_2d(solver, solver, direction, direction, 130000., 130000.)
    np.testing.assert_array_equal(a, expected)
    np.testing.assert_array_equal(b, expected)


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
        patch.delenv('TPMSHX_P_IN_SHOOT', raising=False)
        r_off = _run_3d_stack(_cfg3d_air_air(**base, p_in_shooting=False))
        r_on = _run_3d_stack(_cfg3d_air_air(**base))
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
    assert abs(resid_on) < 1e-4, (
        f"shooting did not land: realized {r_on['P_in_realized_A']:.0f} vs "
        f"spec, resid {resid_on:.2%}")
    assert abs(resid_on) < abs(resid_off) / 3.0
    assert not r_off['solver_converged']
    assert not r_off['convergence_detail']['outer_converged']
    for side in ('A', 'B'):
        assert r_on['convergence_detail']['inlet_pressure'][side]['passed']


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
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    cfg = _cfg3d_air_air(Nx=12, Ny=12, Nz=12, p_in_shooting=True)
    def overloaded(solver, target):
        state = inlet_pressure_state(solver, target)
        return state | dict(realized_Pa=2.0 * target, outlet_Pa=target, passed=False)
    monkeypatch.setattr(stages, 'inlet_pressure_state', overloaded)
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
        # Large enough pressure drop to expose a dead correction path.
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
    monkeypatch.delenv('TPMSHX_P_IN_SHOOT', raising=False)
    monkeypatch.setenv('TPMSHX_CONV_MODE', 'f2')   # pin criterion (C11 lesson)
    res = Pipeline2D(_cfg2d()).run()
    d = res.diagnostics   # forwarded by the public result adapter
    for side in ('A', 'B'):
        resid = d[f'P_in_shoot_resid_{side}']
        assert np.isfinite(resid)
        assert abs(resid) < 1e-4, (
            f"2D side {side} did not land: realized "
            f"{d[f'P_in_realized_{side}']:.0f}, resid {resid:.2%}")
        assert d['convergence_detail']['inlet_pressure'][side]['passed']


def test_2d_water_side_inert_nan_keys(monkeypatch):
    """Mixed-fluid run with the knob ON: water B must stay out of the
    shooting (frozen-ρ P_ref is level-inert) — NaN diagnostics, no crash —
    while air A still lands."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    monkeypatch.setenv('TPMSHX_P_IN_SHOOT', '1')
    monkeypatch.setenv('TPMSHX_CONV_MODE', 'f2')
    res = Pipeline2D(_cfg2d(fluid_B='water')).run()
    d = res.diagnostics
    assert abs(d['P_in_shoot_resid_A']) < 1e-4
    assert np.isnan(d['P_in_realized_B'])
    assert np.isnan(d['P_in_shoot_resid_B'])
