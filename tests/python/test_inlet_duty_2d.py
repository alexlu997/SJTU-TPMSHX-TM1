"""Duty samples the physical inlet; stored end cells remain unknowns."""
import numpy as np
import pytest

from tests.python.result_primitive_wire import _enthalpy_balance_2d


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_physical_inlet_preserves_existing_partial_port_weights(direction):
    T = np.linspace(330., 450., 20).reshape(4, 5)
    dx, dy = np.array([.01, .02, .03, .04]), np.array([.01, .02, .03, .04, .05])
    u, v = np.full(T.shape, .5), np.full(T.shape, .7)
    rcp = np.linspace(1000., 1200., 20).reshape(T.shape)
    inlet = (0, -1, 0, -1)[direction]
    outlet = (-1, 0, -1, 0)[direction]
    widths = dy if direction < 2 else dx
    mi = np.linspace(.2, 1., len(widths)); mi[-1] = 0.
    mo = mi[::-1].copy()
    Tin, eps = 500., .35
    Tout = T[outlet] if direction < 2 else T[:, outlet]
    velocity = .5 if direction < 2 else .7
    kw = dict(eps_side=eps, inlet_mask=mi, outlet_mask=mo, T_in=Tin)
    ci = rcp[inlet] if direction < 2 else rcp[:, inlet]
    co = rcp[outlet] if direction < 2 else rcp[:, outlet]
    wi, wo = eps*ci*velocity*widths*mi, eps*co*velocity*widths*mo
    expected = wi.sum()*(Tin-np.sum(wo*Tout)/wo.sum())
    duty = _enthalpy_balance_2d
    args = (T, u, v, rcp, direction, dx, dy)
    got = duty(*args, **kw)
    assert got == pytest.approx(expected, rel=1e-13)
    old = duty(*args, **{k: value for k, value in kw.items() if k != 'T_in'})
    assert not np.isclose(old, got, rtol=1e-3)


def test_d1_temperature_duty_retains_capacity_weighting():
    """Temperature-formulation duty retains its independent capacity weighting."""
    rng = np.random.default_rng(0)
    Ta = 300.0 + rng.random((5, 4)) * 50.0
    uc = rng.random((5, 4)) + 0.1
    vc = np.zeros((5, 4))
    rho_cp = np.full((5, 4), 1.2 * 1005.0)
    dx = np.ones(5)
    dy = np.ones(4)
    Q = _enthalpy_balance_2d(Ta, uc, vc, rho_cp, 0, dx, dy)
    # hand-rolled legacy form
    w_in = rho_cp[0, :] * np.abs(uc[0, :]) * dy
    w_out = rho_cp[-1, :] * np.abs(uc[-1, :]) * dy
    Ti = float(np.sum(w_in * Ta[0, :]) / np.sum(w_in))
    To = float(np.sum(w_out * Ta[-1, :]) / np.sum(w_out))
    assert Q == pytest.approx(float(np.sum(w_in)) * (Ti - To), rel=1e-12)
