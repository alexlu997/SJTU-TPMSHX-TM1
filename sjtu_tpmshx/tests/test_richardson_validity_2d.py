"""Refined duty must use physical ports and a converged energy solve."""
from dataclasses import replace
from sjtu_tpmshx.models.fluid_props import get
import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
from sjtu_tpmshx.domain.compute_config import PartialBCConfig
from sjtu_tpmshx.solvers.backends.python.two_d import coupling as solve_2d
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver, _port_fractions_1d
from sjtu_tpmshx.tests.test_port_grid_alignment_2d import _case, _expected_profile, _backend_fields


def _arguments(monkeypatch, directions=(1, 3), full=False):
    cfg = _case(directions)
    if full:
        cfg.bc_A = PartialBCConfig(dir=directions[0])
        cfg.bc_B = PartialBCConfig(dir=directions[1])
        cfg.validate()
    parsed, fields = _backend_fields(cfg)
    captured = []

    class BeforeIteration(Exception):
        pass

    def capture(s, **kwargs):
        captured.append(s)
        raise BeforeIteration

    with monkeypatch.context() as patch:
        patch.setattr(SIMPLESolver, 'solve', capture)
        for side in ('A', 'B'):
            with pytest.raises(BeforeIteration):
                fields['_run_simple'](parsed[f'cfg{side}'], 1., 1e-5,
                                      400., 1., side, fluid_type='incompressible')
    dx, dy = fields['energy_dx'], fields['energy_dy']
    shape = len(dx), len(dy)
    props = replace(get('air'), rho=lambda *a: 1., cp=lambda *a: 1.)
    args = dict(
        Ta=np.full(shape, 400.), Tb=np.full(shape, 300.), Ts=np.full(shape, 350.),
        ucA=np.ones(shape), vcA=np.ones(shape), ucB=np.ones(shape), vcB=np.ones(shape),
        rho_cp_A=1., rho_cp_B=1., simpA=captured[0], simpB=captured[1],
        N_x=shape[0], N_y=shape[1], L=.182, H=.042,
        dir_A=directions[0], dir_B=directions[1], energy_dx=dx, energy_dy=dy,
        _x_breaks=fields['_x_breaks'], _y_breaks=fields['_y_breaks'],
        T_inA=400., T_inB=300., P_inA_val=101325., P_inB_val=101325., eps=.7,
        za=None, coeffs=dict(K_ffA=1., K_ffB=1., K_ss=1.),
        _pA=props, _pB=props, cfgA=parsed['cfgA'], cfgB=parsed['cfgB'],
        u_A=1., u_B=1., warnings_list=[], h_vA_coarse=1., h_vB_coarse=1.)
    return cfg, args


def _finite_refined(args, kwargs, converged):
    shape = args[2], args[3]
    fields = tuple(np.full(shape, t) for t in (390., 310., 350.))
    info = dict(converged=converged, iterations=5000, residual=2.)
    if kwargs.get('model_fluids') is not None:
        # This stub supplies arbitrary finite fields, not a physical solve.
        info['model_h_balance'] = dict(passed=False,
            A={'Q_advective_W_per_m': 10.}, B={'Q_advective_W_per_m': -8.})
    return (*fields, info) if kwargs.get('return_info') else fields


@pytest.mark.parametrize('model', [False, True])
@pytest.mark.parametrize('side,bad', [(0, np.inf), (1, -np.inf), (2, np.nan), ('water', np.nan)])
def test_refined_nonfinite_return_precedes_duty_and_fallback(monkeypatch, model, side, bad):
    from sjtu_tpmshx.models.fluid_props import WaterStateError
    _, args = _arguments(monkeypatch, full=True)
    if side == 'water':
        args['_pB'] = replace(args['_pB'], name='water')
    if model:
        nx, ny = args['Ta'].shape
        mass = (np.ones((nx + 1, ny)), np.zeros((nx, ny + 1)))
        for label in ('A', 'B'):
            args[f'rho_cp_{label}'] = np.ones((nx, ny))
        args['model_inputs'] = dict(
            model_fluids=('air', args['_pB'].name), mass_flux_A=mass, mass_flux_B=mass,
            K_ffA=.1, K_ffB=.2, K_ss=1.)
    returned = []

    def refined(*a, **kw):
        assert (kw.get('model_fluids') is not None) == model
        result = _finite_refined(a, kw, True)
        result[1 if side == 'water' else side][0, 0] = bad
        if side == 'water':
            result[0][0, 0] = np.inf
        returned.extend(result[:3])
        return result

    duties = []
    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', lambda *a, **k: duties.append(a))
    error = WaterStateError if side == 'water' else ValueError
    label = 'B' if side == 'water' else ('A', 'B', 'solid')[side]
    match = 'Richardson return B' if side == 'water' else f'Richardson energy return: {label} temperature index='
    with pytest.raises(error, match=match):
        solve_2d._compute_Q_richardson(**args)
    assert not duties
    assert not np.isfinite(returned[1 if side == 'water' else side][0, 0])


@pytest.mark.parametrize('directions', [(1, 3), (3, 1)])
@pytest.mark.parametrize('full', [False, True])
def test_refined_profiles_use_physical_coordinates(monkeypatch, directions, full):
    _, arguments = _arguments(monkeypatch, directions, full)
    arguments.update(rho_cp_A=17., rho_cp_B=23., P_inB_val=202650.)
    for side in ('A', 'B'):
        arguments[f'_p{side}'] = replace(arguments[f'_p{side}'],
                                     cp=lambda T, P: T/100. + P/100000.)
    observed = {}
    balances = []

    def refined(*args, **kwargs):
        observed.update(kwargs)
        return _finite_refined(args, kwargs, True)

    def balance(*args, **kwargs):
        balances.append((args, kwargs))
        return 10.

    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', balance)
    solve_2d._compute_Q_richardson(**arguments)
    assert observed.get('return_info') is True
    assert [kw['T_in'] for _, kw in balances] == [400., 300., 400., 300.]
    for side, direction, (_, duty_kwargs) in zip(('A', 'B'), directions, balances[-2:]):
        widths = observed['dy_arr' if direction in (0, 1) else 'dx_arr']
        bc = arguments[f'cfg{side}']
        lo, hi = bc['in_ctr'] - bc['in_w'] / 2, bc['in_ctr'] + bc['in_w'] / 2
        out_lo = bc['out_ctr'] - bc['out_w'] / 2
        out_hi = bc['out_ctr'] + bc['out_w'] / 2
        expected_in = _expected_profile(widths, lo, hi)
        expected_out = _expected_profile(widths, out_lo, out_hi)
        if full:
            np.testing.assert_allclose(expected_in, 1., atol=1e-13)
        else:
            assert not np.array_equal(widths, widths[::-1])
        raw_in = _port_fractions_1d(widths, lo, hi)[0]
        np.testing.assert_allclose(observed[f'inlet_mask_{side}'], raw_in, atol=1e-13)
        # Formal duty still uses its existing profile; conductive area does not.
        np.testing.assert_allclose(duty_kwargs['inlet_mask'], expected_in, atol=1e-13)
        np.testing.assert_allclose(duty_kwargs['outlet_mask'], expected_out, atol=1e-13)
        simp = arguments[f'simp{side}']
        coarse_width = arguments['energy_dy' if direction < 2 else 'energy_dx']
        coarse_flux = (.5 * arguments['eps'] * simp.rho_field[:, 0]
                       * simp.v[:, 0] * coarse_width
                       * {'A': 5.01325, 'B': 5.0265}[side])  # Physical Tin/Pin above.
        assert observed[f'inlet_flux_{side}'].sum() == pytest.approx(coarse_flux.sum())


@pytest.mark.parametrize('converged', [False, True])
def test_finite_refined_verdict_controls_extrapolation(monkeypatch, converged):
    _, arguments = _arguments(monkeypatch)
    monkeypatch.setattr(solve_2d, 'solve_full_domain',
                        lambda *a, **k: _finite_refined(a, k, converged))
    duties = iter([10., -8., 20., -12.])
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', lambda *a, **k: next(duties))
    result = solve_2d._compute_Q_richardson(**arguments)
    assert result[0] == pytest.approx(70. / 3 if converged else 10.)
    assert result[1:3] == (10., -8.)
    assert result[5]['converged'] is converged
    assert result[5]['extrapolated'] is converged
    assert result[5]['iterations'] == 5000
    if not converged:
        assert any('未外推' in text for text in arguments['warnings_list'])


@pytest.mark.parametrize('directions', [(0, 1), (2, 3)])
def test_refined_initial_fields_preserve_all_physical_cell_coordinates(monkeypatch, directions):
    _, arguments = _arguments(monkeypatch, directions)
    x = np.cumsum(arguments['energy_dx']) - arguments['energy_dx'] / 2
    y = np.cumsum(arguments['energy_dy']) - arguments['energy_dy'] / 2
    seeds = {}
    for name, base in (('Ta', 360.), ('Tb', 320.), ('Ts', 340.)):
        arguments[name] = base + 70. * x[:, None] + 90. * y[None, :]
        seeds[name] = arguments[name].copy()
    observed = {}

    def refined(*args, **kwargs):
        observed.update(kwargs)
        return _finite_refined(args, kwargs, True)

    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    solve_2d._compute_Q_richardson(**arguments)
    xf = np.cumsum(observed['dx_arr']) - observed['dx_arr'] / 2
    yf = np.cumsum(observed['dy_arr']) - observed['dy_arr'] / 2
    for name, base in (('Ta', 360.), ('Tb', 320.), ('Ts', 340.)):
        expected = base + 70. * xf[:, None] + 90. * yf[None, :]
        # No real inlet cells are frozen or overwritten by a face temperature.
        np.testing.assert_allclose(observed[f'{name}_init'], expected, rtol=0, atol=1e-12)
        np.testing.assert_array_equal(arguments[name], seeds[name])


def test_refinement_uses_last_local_exchange_fields_without_resplitting(monkeypatch):
    _, arguments = _arguments(monkeypatch)
    x = np.cumsum(arguments['energy_dx']) - arguments['energy_dx']/2
    y = np.cumsum(arguments['energy_dy']) - arguments['energy_dy']/2
    arguments.update(h_vA_coarse=50.+70.*x[:, None]+90.*y[None, :],
                     h_vB_coarse=80.+40.*x[:, None]+20.*y[None, :], split_A=.3)

    def refined(*args, **kwargs):
        xf = np.cumsum(kwargs['dx_arr']) - kwargs['dx_arr']/2
        yf = np.cumsum(kwargs['dy_arr']) - kwargs['dy_arr']/2
        np.testing.assert_allclose(args[9], 50.+70.*xf[:, None]+90.*yf[None, :],
                                   rtol=0, atol=1e-12)
        np.testing.assert_allclose(args[10], 80.+40.*xf[:, None]+20.*yf[None, :],
                                   rtol=0, atol=1e-12)
        return _finite_refined(args, kwargs, True)

    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    solve_2d._compute_Q_richardson(**arguments)


def test_cap_post_does_not_replace_last_thermal_coefficients(monkeypatch):
    import inspect
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    cfg = ComputeConfig()
    cfg.solver.Nx = cfg.solver.Ny = 8
    cfg.fluid_A.T_in_K = 400.
    captured = {}
    original = solve_2d.solve_full_domain
    signature = inspect.signature(original)

    def energy(*args, **kwargs):
        captured.update(signature.bind(*args, **kwargs).arguments)
        return original(*args, **kwargs)

    def cap(*, step, post, **kwargs):
        _, carry = step(0)
        post(0, carry)
        return 0, False

    def refined(*args, **kwargs):
        # The final post changed next-iteration rho_cp; refinement must instead
        # consume the coefficients paired with the saved main temperature.
        np.testing.assert_array_equal(args[7], captured['rho_cp_fA'])
        np.testing.assert_array_equal(args[8], captured['rho_cp_fB'])
        np.testing.assert_array_equal(kwargs['h_vA_coarse'], captured['h_vA'])
        np.testing.assert_array_equal(kwargs['h_vB_coarse'], captured['h_vB'])
        model = kwargs['model_inputs']
        assert model['mass_flux_A'] is captured['mass_flux_A']
        assert model['mass_flux_B'] is captured['mass_flux_B']
        assert kwargs['model_balance']['post_after_last_thermal']
        assert not kwargs['model_balance']['passed']
        return 10., 10., -10., 10., False, dict(
            converged=True, extrapolated=True, model_h_balance={'passed': False})

    monkeypatch.setattr(solve_2d, 'solve_full_domain', energy)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', cap)
    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', refined)
    result = Pipeline2D(cfg).run()
    assert captured
    assert not result.converged
    assert result.diagnostics['convergence_detail']['outer_hit_cap']


def test_one_invalid_refined_duty_falls_back_both_sides(monkeypatch):
    _, arguments = _arguments(monkeypatch)
    monkeypatch.setattr(solve_2d, 'solve_full_domain',
                        lambda *a, **k: _finite_refined(a, k, True))
    duties = iter([10., -8., float('nan'), -12.])
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', lambda *a, **k: next(duties))
    result = solve_2d._compute_Q_richardson(**arguments)
    assert result[0] == 10.
    assert result[1:3] == (10., -8.)
    assert result[3] == pytest.approx(50. * .182 * .042)
    assert result[5]['extrapolated'] is False
    assert any('主网格值' in text and '未外推' in text for text in arguments['warnings_list'])


def test_failed_refinement_preserves_main_fields_and_rejects_overall(monkeypatch):
    from sjtu_tpmshx.tests.test_cooperative_cancel import _cfg

    original = solve_2d._compute_Q_richardson
    main = {}

    def richardson(*args, **kwargs):
        before = [a.copy() for a in args[:3]]
        with monkeypatch.context() as patch:
            patch.setattr(solve_2d, 'solve_full_domain',
                          lambda *a, **k: _finite_refined(a, k, False))
            result = original(*args, **kwargs)
        for old, actual in zip(before, args[:3]):
            np.testing.assert_array_equal(actual, old)
        main['Q'] = abs(result[1])  # Public Q is the native main-grid A duty.
        return result

    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', richardson)
    result = Pipeline2D(_cfg()).run()
    detail = result.diagnostics['convergence_detail']
    for gate in ('outer_converged', 'simple_ok', 'ltne_ok', 'envelope_ok'):
        assert detail[gate] is True
    assert detail['energy_nan_hit'] is False
    assert detail['richardson_ok'] is False
    assert result.converged is False
    assert result.Q_W == main['Q']
    assert result.diagnostics['richardson_info']['extrapolated'] is False
    assert any('未外推' in text for text in result.warnings)
    for key in ('Ta', 'Tb', 'Ts'):
        assert np.all(np.isfinite(result.fields[key]))
