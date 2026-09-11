"""Outlet reporting contract; controlled fields, no PDE solves."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.python.two_d import coupling as solve_2d
from sjtu_tpmshx.tests.test_2d_warning_callers import _prepare


@pytest.mark.parametrize('direction', range(4))
def test_real_face_mass_partial_nonuniform_outlet(direction):
    cross = np.array([.1, .2, .3, .15, .25])
    stream = np.array([.3, .7])
    fraction = np.array([0., .2, .8, 1., .5])
    # SIMPLE stores +stream faces; velocity includes opening area already.
    solver = SimpleNamespace(u=np.zeros((6, 2)), v=np.zeros((5, 3)),
                             rho_field=np.full((5, 2), 2.))
    solver.v[:, -1] = np.array([99., 3., 4., -2., 0.]) * fraction
    # A deliberate closed-face leak must not enter Tout or be removed in place.
    solver.v[0, -1] = 99.
    T_simple = np.full((5, 2), 290.)
    T_simple[:, -1] = [999., 310., 370., 600., 800.]
    temperature = solve_2d._simple_scalar_to_real_2d(T_simple, direction)
    eps_simple = np.broadcast_to(np.array([.2, .3, .4, .5, .6])[:, None], (5, 2))
    eps = solve_2d._simple_scalar_to_real_2d(eps_simple, direction)
    dx, dy = (stream, cross) if direction < 2 else (cross, stream)
    mass = solve_2d._face_mass_fluxes_2d(solver, direction, eps, dx, dy)
    snapshots = tuple(face.copy() for face in mass)
    # rho * single-side eps * (speed * opening fraction) * transverse width.
    m1, m2 = 2*.3*3*.2*.2, 2*.4*4*.8*.3
    expected = (m1*310. + m2*370.) / (m1+m2)
    assert solve_2d._outlet_temperature_2d(temperature, mass, direction, fraction) == pytest.approx(expected)
    for actual, saved in zip(mass, snapshots):
        np.testing.assert_array_equal(actual, saved)


@pytest.mark.parametrize('outward', [0., -1., np.nan, np.inf])
def test_no_positive_outflow_or_nonfinite_mass_is_an_error(outward):
    mass = (np.full((3, 2), outward), np.zeros((2, 3)))
    with pytest.raises(ValueError, match='finite positive outward mass flow'):
        solve_2d._outlet_temperature_2d(np.full((2, 2), 310.), mass, 0, np.ones(2))


def test_nonfinite_flowing_temperature_is_an_error():
    mass = (np.ones((3, 2)), np.zeros((2, 3)))
    with pytest.raises(ValueError, match='temperature is non-finite'):
        solve_2d._outlet_temperature_2d(np.full((2, 2), np.nan), mass, 0, np.ones(2))


@pytest.mark.parametrize('mode', ['model_h', 'true_h', 'offset', 'zones'])
def test_backend_uses_last_main_raw_and_mass_for_reported_scalars(monkeypatch, mode):
    from sjtu_tpmshx.domain.run_warnings import warning_scope
    from sjtu_tpmshx.solvers import ltne_enthalpy_2d

    pipe, fields = _prepare(monkeypatch, legacy=mode == 'offset',
                            pair=('sco2', 'sco2') if mode == 'true_h' else ('air', 'air'))
    shape = pipe._parsed['N_x'], pipe._parsed['N_y']
    if mode == 'zones':
        eps = .6 + np.arange(np.prod(shape)).reshape(shape) * .001
        pipe._parsed['zone_config'] = object()
        pipe._parsed['za'] = dict(L_mm_arr=np.full(shape, 7.), t_arr=np.full(shape, .6),
            K_ffA_arr=np.ones(shape), K_ffB_arr=np.ones(shape),
            K_ss_arr=np.ones(shape), eps_arr=eps)
        from sjtu_tpmshx.preprocess.thermal_geometry import prepare_thermal_geometry
        parsed = pipe._parsed
        parsed['thermal_geometry'] = prepare_thermal_geometry(
            parsed['tpms_type'], parsed['Lcell'], parsed['t_wall'], parsed['k_s'],
            L_field=parsed['za']['L_mm_arr'], t_field=parsed['za']['t_arr'])
        monkeypatch.setattr(solve_2d, '_zone_statistics_2d', lambda *a: None)
    else:
        eps = pipe._parsed['eps']
    solvers, mass_calls, thermal_calls, reductions = {}, [], [], []
    original_worker = fields['_run_simple']
    original_mass = solve_2d._face_mass_fluxes_2d
    original_reduce = solve_2d._outlet_temperature_2d

    def worker(*args, **kwargs):
        u, v, solver = original_worker(*args, **kwargs)
        side = args[5][-1]
        solver.rho_field[:] = np.arange(solver.rho_field.size).reshape(solver.rho_field.shape) + 1.
        n = solver.v.shape[0]
        solver.outlet_geom_frac[:] = np.linspace(0., 1., n)
        solver.outlet_frac[:] = solver.outlet_geom_frac
        solver.v[:, -1] = np.linspace(-.001, .003, n)
        solver.final_res_mass_global = .2  # Existing failed diagnostic survives reporting.
        solvers[side] = solver
        return u, v, solver

    def mass(solver, direction, eps_side, dx, dy):
        split = (.6 if solver is solvers['A'] else .4) if mode == 'offset' else .5
        np.testing.assert_allclose(eps_side, eps * split)
        result = original_mass(solver, direction, eps_side, dx, dy)
        mass_calls.append(result)
        return result

    def thermal(*args, **kwargs):
        temperatures = tuple(np.full(shape, base + 10*len(thermal_calls))
                             + np.arange(np.prod(shape)).reshape(shape)*.1
                             for base in (330., 310., 320.))
        if mode == 'true_h':
            masses = args[4:6]
        elif mode == 'model_h':
            masses = kwargs['mass_flux_A'], kwargs['mass_flux_B']
        else:
            assert not kwargs.get('model_fluids')
            # The first pair is captured before the legacy inlet helper's pair.
            masses = tuple(mass_calls[-4:-2])
        if mode in ('model_h', 'true_h'):
            assert masses[0] is mass_calls[-2] and masses[1] is mass_calls[-1]
        thermal_calls.append((temperatures, masses))
        info = dict(converged=True, iterations=1, residual=0., Q_A=10., Q_B=-8.)
        if mode == 'model_h':
            info['model_h_balance'] = dict(passed=False, physical_boundary_complete=False,
                A={'mass_in_kg_s_per_m': .01}, B={'mass_in_kg_s_per_m': .01})
        return (*temperatures, info)

    def drive(*, step, post, **kwargs):
        for index in range(2):
            _, carry = step(index)
            post(index, carry)
        # A later SIMPLE state must not be used to reconstruct thermal input mass.
        for solver in solvers.values():
            solver.rho_field[:] = 999.
        return 1, False

    def richardson(*args, **kwargs):
        for actual, raw in zip(args[:3], thermal_calls[-1][0]):
            assert actual is raw
        if mode == 'model_h':
            assert kwargs['model_inputs']['mass_flux_A'] is thermal_calls[-1][1][0]
        return 123., 10., -8., 12., False, dict(converged=True, extrapolated=True,
                                               model_h_balance={'passed': False})

    def reduce(temperature, mass_flux, direction, fraction):
        index = len(reductions)
        assert temperature is thermal_calls[-1][0][index]
        assert mass_flux is thermal_calls[-1][1][index]
        result = original_reduce(temperature, mass_flux, direction, fraction)
        reductions.append(result)
        return result

    fields['_run_simple'] = worker
    monkeypatch.setattr(solve_2d, '_face_mass_fluxes_2d', mass)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(ltne_enthalpy_2d, 'solve_enthalpy_2d', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', richardson)
    monkeypatch.setattr(solve_2d, '_outlet_temperature_2d', reduce)
    with warning_scope({}):
        raw = pipe.run_solvers(fields)
    assert len(thermal_calls) == 2 and len(reductions) == 2
    assert not np.array_equal(raw['Ta'], thermal_calls[-1][0][0])
    assert (raw['T_out_A_K'], raw['T_out_B_K']) == tuple(reductions)
    assert raw['Q_total'] == (10. if mode == 'true_h' else 123.)
    assert not raw['solver_converged']
    assert raw['mass_imbalance_rel_A'] == .2
    assert raw['Q_A'] == 10. and raw['Q_B'] == -8.
    if mode == 'model_h':
        assert not raw['model_h_balance']['main']['physical_boundary_complete']
    # Current application mapping is exercised with real FieldResult snapshots
    # in test_module_result_mapping, including later changes to producer data.
