"""Duty samples the physical inlet; stored end cells remain unknowns."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _enthalpy_balance_2d
from sjtu_tpmshx.models import fluid_props


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
@pytest.mark.parametrize('true_h', [False, True])
def test_physical_inlet_preserves_existing_partial_port_weights(direction, true_h):
    T = np.linspace(330., 450., 20).reshape(4, 5)
    dx, dy = np.array([.01, .02, .03, .04]), np.array([.01, .02, .03, .04, .05])
    u, v = np.full(T.shape, .5), np.full(T.shape, .7)
    rcp = np.linspace(1000., 1200., 20).reshape(T.shape)
    inlet = (0, -1, 0, -1)[direction]
    outlet = (-1, 0, -1, 0)[direction]
    widths = dy if direction < 2 else dx
    mi = np.linspace(.2, 1., len(widths)); mi[-1] = 0.
    mo = mi[::-1].copy()
    Tin, P, eps = 500., 12e6, .35
    Tout = T[outlet] if direction < 2 else T[:, outlet]
    velocity = .5 if direction < 2 else .7
    kw = dict(eps_side=eps, inlet_mask=mi, outlet_mask=mo, T_in=Tin)
    if true_h:
        # Actual CO2 functions: both inlet h and inlet rho must use physical Tin.
        co2 = fluid_props.get('sco2')
        kw.update(enthalpy_fn=co2.enthalpy, rho_fn=co2.rho, P_ref=P)
        wi = eps*co2.rho(Tin, P)*velocity*widths*mi
        wo = eps*co2.rho(Tout, P)*velocity*widths*mo
        expected = wi.sum()*(co2.enthalpy(Tin, P)
                   - np.sum(wo*co2.enthalpy(Tout, P))/wo.sum())
    else:
        ci = rcp[inlet] if direction < 2 else rcp[:, inlet]
        co = rcp[outlet] if direction < 2 else rcp[:, outlet]
        wi, wo = eps*ci*velocity*widths*mi, eps*co*velocity*widths*mo
        expected = wi.sum()*(Tin-np.sum(wo*Tout)/wo.sum())
    got = _enthalpy_balance_2d(T, u, v, rcp, direction, dx, dy, **kw)
    assert got == pytest.approx(expected, rel=1e-13)
    old = _enthalpy_balance_2d(T, u, v, rcp, direction, dx, dy,
                              **{k: value for k, value in kw.items() if k != 'T_in'})
    assert not np.isclose(old, got, rtol=1e-3)
