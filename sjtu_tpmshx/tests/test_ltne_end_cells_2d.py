"""Every end cell keeps its full exchange volume; inlet T lives on the face."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_energy


@pytest.mark.parametrize('rb', [False, True])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
@pytest.mark.parametrize('opening', [0., .4, 1.])
def test_two_end_cells_match_hand_energy_balance(monkeypatch, rb, direction, opening):
    monkeypatch.setattr(ltne_energy, '_RB_ENERGY_2D', rb)
    monkeypatch.setattr(ltne_energy, '_RB_ENERGY_2D_GATE', 0)
    # Two unequal real cells; solid exchanges with prescribed B=300 K.
    # Eliminating Ts gives hv_eff=2*3/(2+3)=1.2 in BOTH cells.
    widths = np.array([.2, .3])
    if direction % 2:
        widths = widths[::-1].copy()
    dx, dy = (widths, np.ones(1)) if direction < 2 else (np.ones(1), widths)
    shape = len(dx), len(dy)
    flow = np.full(shape, (-1. if direction % 2 else 1.) * opening)
    zero = np.zeros(shape)
    u, v = (flow, zero) if direction < 2 else (zero, flow)
    result = ltne_energy.solve_full_domain(
        dx.sum(), dy.sum(), *shape, 400., 300.,
        .2, 0., 0., 2., 3., 1., 1., 2., u, v, zero, zero,
        direction, direction, dx_arr=dx, dy_arr=dy,
        inlet_mask_A=np.array([opening]), Tb_prescribed=np.full(shape, 300.),
        max_iter=5000, return_info=True)
    Ta, Tb, Ts, info = result
    # Conductive inlet: k*A_open/(dx_first/2). Intercell conductance .2/.25.
    D, Din, F = .8, 2. * opening, opening
    matrix = np.array([[F + D + Din + 1.2*.2, -D],
                       [-F - D, F + D + 1.2*.3]])
    expected = np.linalg.solve(matrix, [(F + Din)*400. + 1.2*.2*300.,
                                        1.2*.3*300.])
    got = Ta.ravel()[::-1] if direction % 2 else Ta.ravel()
    np.testing.assert_allclose(got, expected, atol=1e-7, rtol=0)
    np.testing.assert_allclose(Ts, (2.*Ta + 3.*Tb)/5., atol=1e-7, rtol=0)
    # Complete-core inflow + inlet diffusion balances prescribed-B extraction.
    net_in = F*(400. - got[-1]) + Din*(400. - got[0])
    extraction = np.sum(3.*(Ts - Tb)*dx[:, None]*dy[None, :])
    assert abs(net_in - extraction) < 1e-7
    assert info['converged'] or opening == 0.


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_pipeline_inlet_transport_uses_boundary_velocity_once(direction):
    from types import SimpleNamespace
    from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _inlet_transport_2d

    widths = np.array([.2, .3, .5])
    stream = np.array([.4, .6])
    dx, dy = (stream, widths) if direction < 2 else (widths, stream)
    s = SimpleNamespace(u=np.zeros((4, 2)), v=np.zeros((3, 3)),
                        rho_field=np.full((3, 2), 20.))
    s.rho_field[:, 0] = [2., 3., 4.]
    s.v[:, 0] = [.25, 2., .75]  # Actual face values already contain the taper.
    got = _inlet_transport_2d(s, direction, .4, 5., dx, dy)
    # .4 * [2,3,4] * [.25,2,.75] * [.2,.3,.5] * cp_in=5.
    np.testing.assert_allclose(got, [.2, 3.6, 3.], atol=1e-14, rtol=0)
    s.rho_field[:, 0] *= 2.
    s.v[:, 0] /= 2.  # Mass-pinned inlet: density/velocity change together.
    np.testing.assert_allclose(
        _inlet_transport_2d(s, direction, .4, 5., dx, dy),
        [.2, 3.6, 3.], atol=1e-14, rtol=0)
