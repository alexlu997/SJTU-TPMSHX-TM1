import importlib
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
    assert length == pytest.approx(.25, abs=TOL)
    assert result.T_out_hot == pytest.approx(500., abs=400. * TOL)
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
