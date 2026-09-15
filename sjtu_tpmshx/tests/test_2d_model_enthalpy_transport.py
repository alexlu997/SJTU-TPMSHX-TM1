"""Approved R2 transport: independent face/row arithmetic and state ownership."""
import inspect

import numpy as np
import pytest
from numba import get_num_threads, set_num_threads

from sjtu_tpmshx.solvers import ltne_energy as energy
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.solvers.simple_solver import _prolong_mass_faces_2d
from sjtu_tpmshx.solvers.backends.python.two_d import coupling as solve_2d


@pytest.mark.parametrize('direction,direction_b', [(0, 0), (1, 1), (2, 2), (3, 3), (3, 0)])
@pytest.mark.parametrize('rb', [False, True])
def test_two_cv_picard_row_and_final_nonlinear_balance(direction, direction_b, rb):
    # cp=2+.02*(T-300), h=2*(T-300)+.01*(T-300)^2. No SOU on two CVs.
    cp = (2., .02, 0., 300., 300.)
    axis, reverse = direction // 2, direction % 2
    shape = (2, 1) if axis == 0 else (1, 2)
    def field(values):
        return np.array(values[::-1] if reverse else values, dtype=float).reshape(shape)
    widths = np.array([3., 2.] if reverse else [2., 3.])
    dx, dy = (widths, np.ones(1)) if axis == 0 else (np.ones(1), widths)
    one, zero = np.ones(shape), np.zeros(shape)
    mass = (np.zeros((shape[0]+1, shape[1])), np.zeros((shape[0], shape[1]+1)))
    mass[axis][:] = -.1 if reverse else .1
    no_mass = tuple(np.zeros_like(f) for f in mass)
    Ta, Tb, Ts = field([310., 305.]), field([290., 295.]), one*300.
    snap_A, snap_B = Ta.copy(), Tb.copy()
    expected_A, expected_B = [310., 305.], [290., 295.]
    expected_S = [300., 300.]
    # Serial follows flow; RB always visits physical even cell then odd cell.
    order = [1, 0] if rb and reverse else [0, 1]
    for cell in order:
        if cell == 0:
            # Half-CV inlet conduction=.5*.4; inlet enthalpy=.1*44.
            rhs = .2*expected_A[1] + .2*320. + 300. + 4.4 + 66.1
            candidate = rhs / (.2+.2+.22+1.)
            expected_A[0] += .2*(candidate-expected_A[0])
        else:
            candidate = (.42*expected_A[0]+300.-3.075) / 1.41
            expected_A[1] += .2*(candidate-expected_A[1])
        expected_S[cell] = .5*(expected_A[cell]+expected_B[cell])
        expected_B[cell] += .2*(expected_S[cell]-expected_B[cell])
    fn = energy._gs_full_chunk_rb if rb else energy._gs_full_chunk
    threads = get_num_threads()
    try:
        set_num_threads(2)
        fn(Ta, Tb, Ts, *shape, dx, dy, one*.5, zero, zero,
           1/field([2., 3.]), 1/field([2., 3.]), one*.5, one*.5, one*2, one*2,
           zero, zero, zero, zero, direction, direction_b,
           np.array([320.]), np.full(shape[1] if direction_b <= 1 else shape[0], 290.),
           np.array([.4]), np.ones(shape[1] if direction_b <= 1 else shape[0]),
           1, 0, 0, mass_A=mass, mass_B=no_mass, cp_A=cp, cp_B=cp,
           last_Ta=snap_A, last_Tb=snap_B)
    finally:
        set_num_threads(threads)
    for actual, expected in zip((Ta, Tb, Ts), (expected_A, expected_B, expected_S)):
        np.testing.assert_allclose(actual, field(expected), atol=1e-12, rtol=0)
    np.testing.assert_array_equal(snap_A, field([310., 305.]))
    balance = energy._model_h_balance(
        Ta, Tb, Ts, one*.5, zero, zero, 1/field([2., 3.]), 1/field([2., 3.]),
        dx, dy, mass, no_mass, cp, cp, direction, direction_b,
        np.array([320.]), np.full(shape[1] if direction_b <= 1 else shape[0], 290.),
        np.array([.4]), np.ones(shape[1] if direction_b <= 1 else shape[0]), False, snap_A, snap_B)
    h_out = 2*(expected_A[1]-300.)+.01*(expected_A[1]-300.)**2
    q = 4.4-.1*h_out
    diffusion = .2*(320.-expected_A[0])
    assert balance['A']['Q_advective_W_per_m'] == pytest.approx(q, abs=1e-12)
    assert balance['A']['inlet_conduction_W_per_m'] == pytest.approx(diffusion)
    assert balance['net_boundary_in_W_per_m'] == pytest.approx(q+diffusion)
    assert balance['residual_sum_W_per_m'] == pytest.approx(q+diffusion, abs=1e-12)
    assert balance['A']['linearization_defect_max_abs_W_per_m'] > 1e-6
    assert balance['area_m2'] == 5.
    assert balance['physical_boundary_complete']


@pytest.mark.parametrize('sign', [-1., 1.])
@pytest.mark.parametrize('sou', [False, True])
def test_nonzero_sou_and_reference_shift(sign, sou):
    T = np.array([300., 310., 325.])[:, None]
    mass = (np.full((4, 1), sign*.1), np.zeros((3, 2)))
    cp = model_h_coefficients('air')
    direction = 0 if sign > 0 else 1
    cap, deferred = energy._model_h_faces(T, mass, cp, direction, np.array([320.]), np.ones(1), sou)
    face_index = 2 if sign > 0 else 1
    up = 310.
    face = up + ((5. if sign > 0 else -5.) if sou else 0.)
    x, x0 = face-cp[3], cp[4]-cp[3]
    expected_h = cp[0]*(x-x0)+cp[1]/2*(x*x-x0*x0)+cp[2]/3*(x**3-x0**3)
    assert cap[0][face_index, 0]*up+deferred[0][face_index, 0] == pytest.approx(sign*.1*expected_h)
    # Constant cp reduces to the same mass-conservative scheme. A reference
    # shift changes the residual by h0*div(m), not zero when mass is imbalanced.
    constant = (2., 0., 0., 300., 300.)
    shifted = (2., 0., 0., 300., 305.)
    mass[0][-1] *= 1.2
    fluxes = []
    for coeff in (constant, shifted):
        c, b = energy._model_h_faces(T, mass, coeff, direction, np.array([320.]), np.ones(1), sou)
        np.testing.assert_allclose(c[0], 2*mass[0])
        fluxes.append(energy._model_face_values(T, mass, c, b, direction, np.array([320.]), np.ones(1)))
    np.testing.assert_allclose(fluxes[1][0]-fluxes[0][0], -10*mass[0], atol=1e-13)
    np.testing.assert_allclose(np.diff(fluxes[1][0]-fluxes[0][0], axis=0),
                               -10*np.diff(mass[0], axis=0), atol=1e-13)


@pytest.mark.parametrize('rb', [False, True])
@pytest.mark.parametrize('sou_B', [False, True])
def test_three_cv_sweep_uses_frozen_sou_for_both_backends(rb, sou_B):
    one = np.ones((3, 1)); zero = one*0
    Ta, Tb, Ts = (np.array(v, dtype=float)[:, None] for v in
                  ([300., 310., 325.], [280., 290., 310.], [295., 300., 315.]))
    expected_A, expected_B, expected_S = (f.ravel().copy() for f in (Ta, Tb, Ts))
    # Hand-integrated face intercepts m*(h(T_up+delta)-cp(T_up)*T_up).
    # Only the middle upwind CV has a two-neighbour slope: A delta=5 K;
    # B delta=5 K when enabled. The two RB colours must share these values.
    cap_A, def_A = [.2, .22, .25], [-60., -64.975, -75.625]
    cap_B, def_B = [.16, .18, .22], [-48.4, -53.175 if sou_B else -54.1, -66.1]
    for i in ([0, 2, 1] if rb else [0, 1, 2]):
        incoming = 4.4 if i == 0 else cap_A[i-1]*expected_A[i-1]+def_A[i-1]
        candidate = (expected_S[i]+incoming-def_A[i])/(1+cap_A[i])
        expected_A[i] += .2*(candidate-expected_A[i])
        expected_S[i] = .5*(expected_A[i]+expected_B[i])
        incoming = 0. if i == 0 else cap_B[i-1]*expected_B[i-1]+def_B[i-1]
        candidate = (expected_S[i]+incoming-def_B[i])/(1+cap_B[i])
        expected_B[i] += .2*(candidate-expected_B[i])
    mass = (np.full((4, 1), .1), np.zeros((3, 2)))
    cp = (2., .02, 0., 300., 300.)
    fn = energy._gs_full_chunk_rb if rb else energy._gs_full_chunk
    threads = get_num_threads()
    try:
        set_num_threads(2)
        fn(Ta, Tb, Ts, 3, 1, np.ones(3), np.ones(1), zero, zero, zero,
           one, one, one, one, one, one, zero, zero, zero, zero, 0, 0,
           np.array([320.]), np.array([300.]), np.ones(1), np.ones(1), 1, 0, int(sou_B),
           mass_A=mass, mass_B=mass, cp_A=cp, cp_B=cp, last_Ta=Ta.copy(), last_Tb=Tb.copy())
    finally:
        set_num_threads(threads)
    for actual, expected in zip((Ta, Tb, Ts), (expected_A, expected_B, expected_S)):
        np.testing.assert_allclose(actual.ravel(), expected, rtol=0, atol=1e-12)


@pytest.mark.parametrize('sign', [-1., 1.])
@pytest.mark.parametrize('imbalance', [0., .07])
def test_nonnested_mass_prolongation_preserves_overlap_divergence(sign, imbalance):
    dx, dy = np.array([.3, .7]), np.array([.2, .3, .5])
    fx, fy = np.array([.17, .13, .2, .5]), np.array([.2, .13, .17, .21, .29])
    # Open port is y=.2.. .5. A discrete streamfunction closes every coarse
    # CV including nonzero transverse flow. Boundary wall faces stay zero.
    psi = np.array([[0., 0., 1., 1.], [0., .1, .8, 1.], [0., 0., 1., 1.]])
    mx, my = sign*np.diff(psi, axis=1), -sign*np.diff(psi, axis=0)
    mx[1, 1] += imbalance
    fine = _prolong_mass_faces_2d((mx, my), dx, dy, fx, fy)
    coarse_div = mx[1:]-mx[:-1]+my[:, 1:]-my[:, :-1]
    fine_div = fine[0][1:]-fine[0][:-1]+fine[1][:, 1:]-fine[1][:, :-1]
    x, y, xf, yf = [np.r_[0., np.cumsum(w)] for w in (dx, dy, fx, fy)]
    expected = np.zeros_like(fine_div)
    for i in range(len(fx)):
        for j in range(len(fy)):
            for a in range(len(dx)):
                for b in range(len(dy)):
                    area = max(0., min(xf[i+1], x[a+1])-max(xf[i], x[a])) * max(
                        0., min(yf[j+1], y[b+1])-max(yf[j], y[b]))
                    expected[i,j] += area*coarse_div[a,b]/(dx[a]*dy[b])
    np.testing.assert_allclose(fine_div, expected, atol=1e-14, rtol=0)
    # Every coarse face lies in this second requested partition: evaluate
    # the constructed field there rather than reverse-interpolating samples.
    same = _prolong_mass_faces_2d((mx, my), dx, dy, dx, dy)
    np.testing.assert_allclose(same[0], mx, atol=1e-14)
    np.testing.assert_allclose(same[1], my, atol=1e-14)
    for coarse_face, fine_face in ((0, 0), (1, 2), (2, 4)):
        np.testing.assert_allclose([fine[0][fine_face, 0], fine[0][fine_face, 1:3].sum(),
                                   fine[0][fine_face, 3:].sum()], mx[coarse_face], atol=1e-14)
    np.testing.assert_allclose(fine[0][[0, -1]][:, [0, 3, 4]], 0., atol=1e-14)
    np.testing.assert_allclose(fine[1][:, [0, -1]], 0., atol=1e-14)
    assert fx.sum()*fy.sum() == pytest.approx(dx.sum()*dy.sum())


def test_unknown_backflow_invalidates_physical_budget():
    one = np.ones((2, 2)); zero = one*0
    mass = (np.zeros((3, 2)), np.zeros((2, 3)))
    mass[0][-1] = -.1
    cp = model_h_coefficients('water')
    balance = energy._model_h_balance(
        one*310, one*310, one*310, zero, zero, zero, one, one,
        np.ones(2), np.ones(2), mass, tuple(f*0 for f in mass), cp, cp, 0, 0,
        np.full(2, 310.), np.full(2, 310.), np.ones(2), np.ones(2), False, one*310, one*310)
    assert balance['A']['unknown_inflow_faces'] == 2
    assert not balance['physical_boundary_complete']
    assert not balance['passed']


def test_constant_temperature_and_signed_solid_gate_are_separate():
    one = np.ones((2, 2)); zero = one*0
    mass = (np.full((3, 2), .1), np.zeros((2, 3)))
    cp = model_h_coefficients('water')
    for solid_temperature in (310., 311.):
        balance = energy._model_h_balance(
            one*310, one*310, one*solid_temperature, zero, zero, zero, one*.5, one*.5,
            np.ones(2), np.ones(2), mass, mass, cp, cp, 0, 0,
            np.full(2, 310.), np.full(2, 310.), np.ones(2), np.ones(2), False, one*310, one*310)
        assert balance['net_boundary_in_W_per_m'] == pytest.approx(0., abs=1e-12)
        assert balance['energy_ok']
        if solid_temperature == 310.:
            assert balance['D2_W_per_m'] == 1.
            assert balance['passed']
        else:
            assert balance['D2_W_per_m'] == 2.
            assert balance['solid_residual_sum_W_per_m'] == -4.
            assert not balance['solid_ok']
            assert not balance['passed']


@pytest.mark.parametrize('pair', [('air', 'air'), ('air', 'water'), ('water', 'air'), ('water', 'water')])
@pytest.mark.parametrize('variable', [False, True])
def test_production_r2_passes_actual_mass_without_new_variable_cp_switch(monkeypatch, pair, variable):
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    from sjtu_tpmshx.tests.test_cooperative_cancel import _cfg
    cfg = _cfg()
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
    monkeypatch.setattr(SIMPLESolver, 'solve', lambda *a, **kw: (True, 0))
    cfg.fluid_A.type, cfg.fluid_B.type = pair
    cfg.fluid_A.T_in_K, cfg.fluid_B.T_in_K = 330., 300.
    for fluid in (cfg.fluid_A, cfg.fluid_B):
        fluid.u_mps = .03 if fluid.type == 'water' else 5.
    cfg.flags.variable_rho_cp = variable
    observed = []
    original = solve_2d._face_mass_fluxes_2d
    def mass(*args):
        result = original(*args)
        observed.append(result)
        return result
    class Captured(Exception):
        pass
    def thermal(*args, **kwargs):
        assert kwargs['model_fluids'] == pair
        assert len(observed) == 2
        assert kwargs['mass_flux_A'] is observed[0]
        assert kwargs['mass_flux_B'] is observed[1]
        assert kwargs['inlet_flux_A'] is kwargs['inlet_flux_B'] is None
        raise Captured
    monkeypatch.setattr(solve_2d, '_face_mass_fluxes_2d', mass)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    with pytest.raises(Captured):
        Pipeline2D(cfg).run()


def test_driver_reports_last_sweep_defect_without_resolving(monkeypatch):
    one = np.ones((2, 2)); zero = one*0
    mass = (np.full((3, 2), .01), np.zeros((2, 3)))
    calls = []
    signature = inspect.signature(energy._gs_full_chunk.py_func)
    def chunk(*args, **kwargs):
        bound = signature.bind(*args, **kwargs).arguments
        calls.append(True)
        bound['last_Ta'][:] = bound['Ta']
        bound['last_Tb'][:] = bound['Tb']
        bound['Ta'][:] = 315.
        return 0.
    monkeypatch.setattr(energy, '_gs_full_chunk', chunk)
    _, _, _, info = energy.solve_full_domain(
        2., 2., 2, 2, 320., 300., 0., 0., 0., 1., 1., 1., 1., 1.,
        zero, zero, zero, zero, 0, 0, max_iter=1, return_info=True,
        model_fluids=('air', 'water'), mass_flux_A=mass, mass_flux_B=tuple(f*0 for f in mass))
    assert calls == [True]
    assert not info['converged']
    assert info['model_h_balance']['A']['linearization_defect_max_abs_W_per_m'] > 0


@pytest.mark.parametrize('energy_ok', [False, True])
def test_richardson_uses_model_faces_duty_and_energy_gate(monkeypatch, energy_ok):
    from sjtu_tpmshx.tests.test_richardson_validity_2d import _arguments
    _, args = _arguments(monkeypatch, full=True)
    dx, dy = args['energy_dx'], args['energy_dy']
    mass = (np.ones((len(dx)+1, len(dy))), np.zeros((len(dx), len(dy)+1)))
    inputs = dict(model_fluids=('air', 'air'), mass_flux_A=mass, mass_flux_B=mass,
                  K_ffA=.1, K_ffB=.2, K_ss=1., outer_index=3)
    main = dict(passed=True, outer_converged=True, post_after_last_thermal=False,
                A={'Q_advective_W_per_m': 10.}, B={'Q_advective_W_per_m': -8.})
    seen = []
    def thermal(*a, **kw):
        seen.append(True)
        expected = _prolong_mass_faces_2d(mass, dx, dy, kw['dx_arr'], kw['dy_arr'])
        for got, want in zip(kw['mass_flux_A'], expected):
            np.testing.assert_array_equal(got, want)
        assert kw['inlet_flux_A'] is kw['inlet_flux_B'] is None
        assert a[6:9] == (.1, .2, 1.)
        shape = a[2:4]
        balance = dict(passed=energy_ok,
                       A={'Q_advective_W_per_m': 12.}, B={'Q_advective_W_per_m': -11.})
        return (*(np.full(shape, t) for t in (390., 310., 350.)),
                dict(converged=True, iterations=500, residual=0., model_h_balance=balance))
    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d',
                        lambda *a, **kw: pytest.fail('model h used legacy duty'))
    result = solve_2d._compute_Q_richardson(**args, model_inputs=inputs, model_balance=main)
    assert seen == [True]
    assert result[1:3] == (10., -8.)
    assert result[0] == pytest.approx(38./3 if energy_ok else 10.)
    assert result[5]['extrapolated'] is energy_ok
    assert result[5]['model_h_balance']['outer_index'] == 3
