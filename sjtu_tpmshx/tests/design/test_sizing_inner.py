import importlib
from dataclasses import replace
import numpy as np
import pytest

from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.sizing import t_target, solve_Lx

def _case():
    return DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                      "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)

def test_t_target_from_Q():
    c = _case()                       # Q 路 (dT=None)
    tt = t_target(c)
    assert tt < c.T_in_h and tt > c.T_in_c

def test_t_target_from_dT():
    c = _case(); c.dT = 40.0          # 温降 ΔT 路 (优先)
    assert abs(t_target(c) - (c.T_in_h - 40.0)) < 1e-9

def test_solve_Lx_hits_target():
    c = _case()
    Lx, r = solve_Lx(c, "Diamond", 7.0, 0.5, s=0.084, arrangement="cross")
    assert Lx is None or (0.001 < Lx <= 0.450 and r is not None)


@pytest.mark.parametrize('prop_model', ['const', 'mean'])
def test_duty_search_meets_actual_heat_duty_after_cold_start(prop_model):
    from sjtu_tpmshx.design.forward import forward
    case = replace(_case(), Q=70000.)
    length, result = solve_Lx(case, 'Diamond', 7., .5, .15, 'cross',
                              prop_model=prop_model)
    assert length is not None and result.Q_hot >= case.Q
    cold = forward(case, 'Diamond', 7., .5, .15, length, 'cross',
                   prop_model=prop_model)
    assert cold.run_status['converged']
    assert cold.Q_hot >= case.Q
    assert cold.dP_hot_frac <= case.dPlim_h
    assert cold.dP_cold_frac <= case.dPlim_c


@pytest.mark.parametrize('dT,target,expected', [
    (None, None, .15), (10., None, .10), (10., 380., .20),
])
def test_length_search_respects_duty_temperature_and_explicit_target(
        monkeypatch, dT, target, expected):
    from sjtu_tpmshx.design import sizing
    from sjtu_tpmshx.design.forward import ForwardResult
    case = DesignCase(1, 'air', 400., 2e5, .01, 'air', 300., 2e5, .01,
                      150., .05, .05, dT=dT)

    def thermal(case, topo, l, t, s, length, arrangement, **kwargs):
        # Controlled response separates actual duty from inlet-cp conversion.
        return ForwardResult(400. - 100. * length, 310., 1000. * length,
                             1000. * length, .001, .001, 1000., 1000.,
                             run_status={'converged': True})

    monkeypatch.setattr(sizing, 'forward', thermal)
    length, result = sizing.solve_Lx(case, 'Diamond', 7., .5, .15, 'cross',
                                     target=target, prop_model='mean')
    assert length == pytest.approx(expected + sizing.TOL, abs=1e-12)
    if dT is None and target is None:
        assert result.Q_hot >= case.Q
    else:
        assert result.T_out_hot <= (target if target is not None else 400. - dT)


@pytest.mark.parametrize('arrangement,floor,cold_boundary,expected', [
    ('cross', .014, .015, .015),
    ('cross', .0155, .015, .0155),
    ('cross', .015 * (1. - 5e-7), .015, .015),
    ('cross', .017, .015, None),
    ('cross', .451, .015, None),
    ('cross', .014, .451, None),
    ('counter', .014, .015, .014),
    ('counter', .016, .015, None),
])
def test_pressure_search_intersects_all_case_limits(
        monkeypatch, arrangement, floor, cold_boundary, expected):
    from sjtu_tpmshx.design import sizing
    cases = [_case(), replace(_case(), case=2)]

    def pressure(case, topo, l, t, s, length, arrangement, height=None):
        assert height == .06
        # Different cases govern the hot upper bound and cold lower bound.
        hot = length / .016 if case.case == 1 else .5
        cold = (cold_boundary / length if arrangement == 'cross'
                else length / cold_boundary) if case.case == 2 else .5
        return hot * case.dPlim_h, cold * case.dPlim_c

    monkeypatch.setattr(sizing, 'dP_fracs', pressure)
    length = sizing._min_Lx_for_dP(cases, 'Diamond', 7., .5, .084,
                                   arrangement, floor, height=.06)
    if expected is None:
        assert length is None
    else:
        assert length == pytest.approx(expected, abs=1e-12, rel=0.)
        assert length >= floor
        for case in cases:
            hot, cold = pressure(case, 'Diamond', 7., .5, .084, length,
                                 arrangement, height=.06)
            assert hot <= case.dPlim_h and cold <= case.dPlim_c


@pytest.mark.parametrize('height', [None, .06])
def test_pressure_search_finds_real_df_narrow_interval(height):
    from sjtu_tpmshx.design.sizing import _min_Lx_for_dP
    from sjtu_tpmshx.models.quick_design import dP_fracs
    case = _case()
    # Use actual geometry, fluid properties and D-F; only the limits are chosen.
    hot_limit = dP_fracs(case, 'Diamond', 7., .5, .084, .016, height=height)[0]
    cold_limit = dP_fracs(case, 'Diamond', 7., .5, .084, .015, height=height)[1]
    case = replace(case, dPlim_h=float(hot_limit), dPlim_c=float(cold_limit))
    length = _min_Lx_for_dP([case], 'Diamond', 7., .5, .084, 'cross', .014,
                            height=height)
    assert length is not None and .014 <= length <= .016
    assert length == pytest.approx(.015, abs=1e-12, rel=0.)
    hot, cold = dP_fracs(case, 'Diamond', 7., .5, .084, length, height=height)
    assert hot <= case.dPlim_h and cold <= case.dPlim_c


def _controlled_forward(monkeypatch, mode):
    """Real forward/brentq, with controlled thermal responses, not PDE solves."""
    module = importlib.import_module('sjtu_tpmshx.models.quick_design')
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.python.quick_design.execution')
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **k: {
        'epsilon': .6, 'epsilon_A': .3, 'A_0': 1000., 'D_h': .002})
    events = []
    property_error = ValueError('injected actual forward property failure')
    original_props = module.fluid_props
    property_calls = 0

    def props(*args):
        nonlocal property_calls
        property_calls += 1
        # Each complete const forward uses two _hvol and two dP properties.
        # Call 9 is the first property in real brentq's first callback.
        if mode == 'property' and property_calls == 9:
            raise property_error
        return original_props(*args)

    def thermal(*args, **kwargs):
        length = args[0]
        hot = 520. if mode == 'drift' and len(events) in (2, 3) else 600. - 400. * length
        shape = (args[3], args[4], args[5])
        fields = tuple(np.full(shape, t) for t in (hot, 350., 450.))
        seed = tuple(kwargs[k] for k in ('Ta_init', 'Tb_init', 'Ts_init'))
        if events:
            for actual, previous in zip(seed, events[-1][2]):
                np.testing.assert_array_equal(actual, previous)
                assert not np.shares_memory(actual, previous)
        else:
            assert seed == (None, None, None)
        events.append((length, kwargs['tol'], fields))
        if mode == 'thermal' and len(events) == 3:
            fields[2][0, 0, 0] = np.nan
        return (*fields, {'converged': True})

    monkeypatch.setattr(module, 'fluid_props', props)
    monkeypatch.setattr(execution, 'solve_full_domain_3d', thermal)
    case = DesignCase(1, 'air', 600., 4e5, .05, 'air', 300., 4e5, .05,
                      None, .08, .08, dT=100.)
    return case, events, property_error


@pytest.mark.parametrize('mode', ['thermal', 'property'])
def test_brentq_propagates_forward_value_error(monkeypatch, mode):
    case, events, property_error = _controlled_forward(monkeypatch, mode)
    # Neither solve_Lx, forward nor scipy.brentq is mocked.
    with pytest.raises(ValueError) as caught:
        solve_Lx(case, 'Diamond', 7., .5, .084, 'cross', target=500.)
    if mode == 'property':
        assert caught.value is property_error
        assert len(events) == 2  # failed before the callback's thermal solve
    else:
        assert 'design thermal return' in str(caught.value)
        assert len(events) == 3  # no fallback or final-tightening solve


@pytest.mark.parametrize('mode', ['normal', 'drift'])
def test_brentq_finite_response_preserves_seed_chain_and_fallback(monkeypatch, mode):
    from sjtu_tpmshx.design.sizing import LX_MAX, SIZING_TOL, LTNE_TOL, TOL
    case, events, _ = _controlled_forward(monkeypatch, mode)
    length, result = solve_Lx(case, 'Diamond', 7., .5, .084, 'cross', target=500.)
    # Pick the cooling side of the existing length resolution, then tighten.
    assert length == pytest.approx(.25 + TOL, abs=1e-8)
    assert result.T_out_hot == pytest.approx(500. - 400. * TOL, abs=4e-6)
    assert result.T_out_hot <= 500.
    assert events[0][0] == LX_MAX
    assert events[1][0] == .014
    # Actual brentq re-evaluates both endpoints, including in drift mode.
    assert [e[0] for e in events[2:4]] == [.014, LX_MAX]
    if mode == 'drift':
        assert events[4][0] == (.014 + LX_MAX) / 2  # original bisection
    else:
        assert events[4][0] == pytest.approx(.25)  # original brentq step
    assert all(e[1] == SIZING_TOL for e in events[:-1])
    assert events[-1][1] == LTNE_TOL
    for actual, last in zip(result.fields, events[-1][2]):
        np.testing.assert_array_equal(actual, last)
