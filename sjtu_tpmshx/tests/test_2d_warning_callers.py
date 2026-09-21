"""2D caller contexts at controlled SIMPLE/thermal boundaries, not PDE acceptance."""
import inspect
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.domain.run_warnings import warning_scope
from sjtu_tpmshx.preprocess.two_d.preparation import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d import coupling as solve_2d
from sjtu_tpmshx.models import tpms_calc, tpms_props
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.tests.test_cooperative_cancel import _cfg


def test_prepared_cold_and_cached_inlets_rebind_both_sides():
    cfg = _cfg()
    cfg.extrap.allow = True  # Deliberate 1100 K property-warning probe.
    cfg.fluid_A.T_in_K = cfg.fluid_B.T_in_K = 1100.
    cfg.fluid_A.u_mps = cfg.fluid_B.u_mps = 1.
    tpms_calc.compute.cache_clear()
    previous = None
    for run in range(2):
        before = tpms_calc.compute.cache_info()
        with warning_scope({}) as records:
            prepare_case(cfg, case_id='inlet-warning-probe')
        after = tpms_calc.compute.cache_info()
        assert after.misses - before.misses == (1 if run == 0 else 0)
        assert after.hits - before.hits == (1 if run == 0 else 2)
        for side in ('A', 'B'):
            value = records[('property', 'air_cp', (), (side, 'inlet', 'scalar'))]
            assert value.maximum == (1100., ()) and value.size == 1
        if previous is not None:
            assert records == previous
        previous = records


class ThermalBoundary(Exception):
    pass


def _prepare(monkeypatch, *, legacy=False, pair=('air', 'air'), temperatures=(400., 300.)):
    cfg = _cfg()
    cfg.extrap.allow = True  # Deliberate low-Re warning probe; no physical acceptance.
    cfg.fluid_A.type, cfg.fluid_B.type = pair
    cfg.fluid_A.T_in_K, cfg.fluid_B.T_in_K = temperatures
    for side, fluid in zip(('A', 'B'), (cfg.fluid_A, cfg.fluid_B)):
        fluid.u_mps = .001
        if fluid.type == 'sco2':
            fluid.P_in_Pa = 9e6 if side == 'A' else 16e6
    from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    with warning_scope({}):
        parsed, grid = build_execution_inputs(prepare_case(cfg, case_id='caller-probe'))
        fields = build_runtime(parsed, grid)
    # These controlled kernel tests intentionally mutate private runtime data;
    # they are not portable-Case or application acceptance tests.
    # Mutable per-side test doubles allow injection at an exact execution stage.
    for side in ('A', 'B'):
        parsed['_models']['fluid_' + side] = SimpleNamespace(**vars(parsed['_models']['fluid_' + side]))
    cfg = parsed['compute_cfg']
    parsed['_capture_native'] = False
    pipe = SimpleNamespace(cfg=cfg, _parsed=parsed,
        run_solvers=lambda fields: solve_2d._run_solvers(parsed, fields)[0])
    if legacy:
        # Controlled asymmetric geometry activates the existing temperature path;
        # geometry accuracy itself is outside this caller test.
        cfg.geometry.delta_levelset = .1
        parsed['thermal_geometry'] = {
            **parsed['thermal_geometry'], 'split_A': .6,
            'side_geometry': {'A': (100., .002, 100., .002),
                              'B': (120., .003, 120., .003)}}
    def solved(solver, *args, **kwargs):
        # A completed fake flow needs outward mass for the result's Tout.
        solver.v[:, -1] = .001 * solver.outlet_geom_frac
        return True, 0
    monkeypatch.setattr(SIMPLESolver, 'solve', solved)
    return pipe, fields


def _step_context(step):
    prepare = inspect.getclosurevars(step).nonlocals['_prepare_thermal_inputs']
    context = inspect.getclosurevars(prepare).nonlocals
    return {**context, **vars(context['state'])}


def _thermal(*args, **kwargs):
    shape = args[2], args[3]
    return (*(np.full(shape, t) for t in (1100., 1200., 350.)),
            dict(converged=True, iterations=1, residual=0.))


def _stop(*args, **kwargs):
    raise ThermalBoundary


def test_shared_fluid_model_keeps_each_sides_asymmetric_geometry(monkeypatch):
    from sjtu_tpmshx.models.fluid_props import get
    pipe, fields = _prepare(monkeypatch, legacy=True)
    pipe._parsed['_models']['fluid_A'] = pipe._parsed['_models']['fluid_B'] = get('air')
    pipe._parsed['thermal_geometry']['side_geometry'] = {
        'A': (100., .002, 100., .002),
        'B': (200., .002, 100., .002),
    }

    def drive(*, step, **kwargs):
        state = _step_context(step)
        # Same hydraulic diameter cancels Nu/k; only B doubles its area.
        assert state['_hv_ratio_A_2d'] == pytest.approx(1.)
        assert state['_hv_ratio_B_2d'] == pytest.approx(2.)
        raise ThermalBoundary

    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    with pytest.raises(ThermalBoundary):
        pipe.run_solvers(fields)


@pytest.mark.parametrize('zoned', [False, True])
def test_actual_workers_and_local_re_snapshots(monkeypatch, zoned):
    from sjtu_tpmshx.domain import run_warnings as rw
    pipe, fields = _prepare(monkeypatch)
    seen = []
    original = fields['_run_simple']

    def worker(*args, **kwargs):
        labels = rw._range_context.get()
        seen.append(labels)
        # Real worker's scope, including repeat observations and different sides.
        tpms_props.air_cp(np.full((2, 3), 1100. if labels[0] == 'A' else 1200.))
        return original(*args, **kwargs)

    fields['_run_simple'] = worker
    if zoned:
        shape = pipe._parsed['N_x'], pipe._parsed['N_y']
        pipe._parsed['zone_config'] = object()
        pipe._parsed['za'] = dict(L_mm_arr=np.full(shape, 7.), t_arr=np.full(shape, .6),
            K_ffA_arr=np.ones(shape), K_ffB_arr=np.ones(shape),
            K_ss_arr=np.ones(shape), eps_arr=np.full(shape, .7))
        from sjtu_tpmshx.preprocess.thermal_geometry import prepare_thermal_geometry
        parsed = pipe._parsed
        parsed['thermal_geometry'] = prepare_thermal_geometry(
            parsed['tpms_type'], parsed['Lcell'], parsed['t_wall'], parsed['k_s'],
            L_field=parsed['za']['L_mm_arr'], t_field=parsed['za']['t_arr'])
    monkeypatch.setattr(solve_2d, 'solve_full_domain', _stop)

    def drive(*, step, **kwargs):
        # Repeat the actual first step, catching only the controlled thermal stop.
        for _ in range(2):
            with pytest.raises(ThermalBoundary):
                step(0)
        raise ThermalBoundary

    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    with warning_scope({}) as records, pytest.raises(ThermalBoundary):
        pipe.run_solvers(fields)
    for side, temperature in (('A', 1100.), ('B', 1200.)):
        labels = (side, 'main', 'solver-cell(perp,stream)')
        assert seen.count(labels) == 2
        worker_record = records[('property', 'air_cp', (2, 3), labels)]
        assert worker_record.size == 6 and worker_record.maximum[0] == temperature
        labels = (side, 'main-hv', 'real-cell(x,y)')
        shape = pipe._parsed['N_x'], pipe._parsed['N_y']
        raw = records[('nu_raw', 'air', 'Gyroid', shape, labels)]
        source = records[('nu', 'air', 'Gyroid', () if zoned else shape, labels)]
        assert raw.size == np.prod(shape) and 0 < raw.minimum[0] < 1.
        assert source.size == (1 if zoned else np.prod(shape))
        assert source.minimum[0] == 1.


@pytest.mark.parametrize('pair', [('air', 'water'), ('water', 'air'),
                                ('sco2', 'water'), ('air', 'sco2')])
def test_uniform_hv_keeps_second_pass_property_sampling(monkeypatch, pair):
    from sjtu_tpmshx.domain import run_warnings as rw
    from sjtu_tpmshx.models.grid import cell_average
    from sjtu_tpmshx.solvers import ltne_enthalpy_2d

    pipe, fields = _prepare(monkeypatch, pair=pair, temperatures=(330., 300.))
    cfg = pipe._parsed
    shape = cfg['N_x'], cfg['N_y']
    variation = np.linspace(0., 10., np.prod(shape)).reshape(shape)
    returned = (320. + variation, 300. + variation, 310. + variation)
    original_nu = solve_2d.local_nusselt
    enthalpy = 'sco2' in pair
    epoch, step_call = 0, None
    expected_hv, sampled = {}, []

    def nusselt(model, topology, Re, eps, length, diameter, Pr):
        side = rw._range_context.get()[0]
        state = _step_context(step_call)
        props = state['_p' + side]
        inlet = cfg['T_in' + side]
        pressure = getattr(cfg['compute_cfg'], 'fluid_' + side).P_in_Pa
        speed = solve_2d.local_speed(state['uc' + side], state['vc' + side])
        if enthalpy:
            temperature = state['Ta' if side == 'A' else 'Tb']
            temperature = np.full_like(speed, inlet) if temperature is None else temperature
            rho = cell_average(props.rho(temperature, pressure), fields['energy_dx'], fields['energy_dy'])
            mu = cell_average(props.mu(temperature, pressure), fields['energy_dx'], fields['energy_dy'])
            sample_T = cell_average(temperature, fields['energy_dx'], fields['energy_dy'])
        else:
            rho = cell_average(state['rho_' + side + '_field'], fields['energy_dx'], fields['energy_dy'])
            mu = cell_average(state['mu_' + side], fields['energy_dx'], fields['energy_dy'])
            sample_T = inlet
        geometry = cfg['thermal_geometry']['uniform']
        expected = rho * (np.abs(speed) + 1e-12) * geometry['D_h'] / mu
        np.testing.assert_array_equal(Re, expected)
        expected_Pr = (float(props.mu(sample_T, pressure)) * float(props.cp(sample_T, pressure))
                       / float(props.k(sample_T, pressure))) if model.name == 'water' else None
        assert Pr == expected_Pr
        if epoch == 1:
            inlet_Re = (props.rho(inlet, pressure) * (np.abs(speed) + 1e-12)
                        * geometry['D_h'] / props.mu(inlet, pressure))
            assert not np.array_equal(Re, inlet_Re)
        Nu = original_nu(model, topology, Re, eps, length, diameter, Pr)
        expected_hv[side] = geometry['A_0'] * Nu * float(props.k(sample_T, pressure)) / geometry['D_h']
        sampled.append((epoch, side))
        return Nu

    def thermal(*args, **kwargs):
        for side, value in zip(('A', 'B'), args[6:8] if enthalpy else args[9:11]):
            if pair[0 if side == 'A' else 1] != 'sco2':
                np.testing.assert_array_equal(value, expected_hv[side])
        return (*returned, dict(converged=True, iterations=1, residual=0., Q_A=10., Q_B=-10.))

    def drive(*, step, post, **kwargs):
        nonlocal epoch, step_call
        step_call = step
        _, carry = step(0)
        post(0, carry)
        epoch = 1
        step(1)
        raise ThermalBoundary

    monkeypatch.setattr(solve_2d, 'local_nusselt', nusselt)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(ltne_enthalpy_2d, 'solve_enthalpy_2d', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    with warning_scope({}), pytest.raises(ThermalBoundary):
        pipe.run_solvers(fields)
    assert sampled == [(epoch, side) for epoch in range(2)
                       for side, fluid in zip(('A', 'B'), pair) if fluid != 'sco2']


@pytest.mark.parametrize('cap', [False, True])
def test_last_thermal_capacities_survive_post_for_richardson(monkeypatch, cap):
    pipe, fields = _prepare(monkeypatch, legacy=True, temperatures=(400., 300.))
    shape = pipe._parsed['N_x'], pipe._parsed['N_y']
    wanted = []

    def thermal(*args, **kwargs):
        return (*(np.full(shape, t) for t in (340., 310., 325.)),
                dict(converged=True, iterations=1, residual=0.))

    def drive(*, step, post, **kwargs):
        _, carry = step(0)
        post(0, carry)
        _, carry = step(1)
        state = _step_context(step)
        consumed = state['last_temperature_inputs'][:2]
        wanted.extend(value.copy() for value in consumed)
        if cap:
            post(1, carry)
            state = _step_context(step)
            for side, value in zip(('A', 'B'), consumed):
                working = state['rho_cp_' + side]
                assert not np.shares_memory(value, working)
                working[:] *= 1.1
        return 1, not cap

    def richardson(*args, **kwargs):
        for actual, expected in zip(args[7:9], wanted):
            np.testing.assert_array_equal(actual, expected)
        return 10., 10., -10., 10., False, dict(converged=True, extrapolated=True)

    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', richardson)
    with warning_scope({}):
        pipe.run_solvers(fields)
    assert len(wanted) == 2


@pytest.mark.parametrize('nan', [False, True])
@pytest.mark.parametrize('low', [False, True])
def test_main_warm_return_final_and_outlet_keep_actual_states(monkeypatch, nan, low):
    pipe, fields = _prepare(monkeypatch, legacy=True)
    pipe._parsed['T_s_init'] = 350.

    def thermal(*args, **kwargs):
        result = _thermal(*args, **kwargs)
        if low:
            result[0][:] = 200.
        if nan:
            result[0][0, 0] = np.nan
        return result

    def drive(*, step, **kwargs):
        state = _step_context(step)
        state['Ta'][:] = 220. if low else 1050.
        state['Tb'][:] = 1150.
        step(0)
        return 0, True

    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', lambda *a, **k:
        (10., 10., -10., 10., False, dict(converged=True, extrapolated=True)))
    with warning_scope({}) as records:
        if nan:
            with pytest.raises(ValueError, match='2D energy return: A temperature index='):
                pipe.run_solvers(fields)
            shape = pipe._parsed['N_x'], pipe._parsed['N_y']
            record = records[('property_state', 'air_cp', shape,
                              ('A', 'main-return', 'real-cell(x,y)'))]
            assert record.nonfinite == 1
            assert not any(key[-1] == ('A', 'final', 'real-cell(x,y)') for key in records)
            return
        pipe.run_solvers(fields)
    shape = pipe._parsed['N_x'], pipe._parsed['N_y']
    for side, warm, returned in (('A', 220. if low else 1050., 200. if low else 1100.),
                                  ('B', 1150., 1200.)):
        for stage, value in (('main-warm', warm), ('main-return', returned), ('final', returned)):
            record = records[('property_state', 'air_cp', shape, (side, stage, 'real-cell(x,y)'))]
            assert record.size == np.prod(shape)
            assert record.minimum[0] == value if low and side == 'A' else record.maximum[0] == value
            assert record.nonfinite == int(nan and side == 'A' and stage == 'main-return')
        # Tout transcribes the raw mass-weighted scalar; no display-property call.
        assert not any(key[-1] == (side, 'final-outlet', 'outlet-face') for key in records)
        for layout in ('asym-reference-scalar', 'asym-side-scalar'):
            raw_re = records[('nu_raw', 'air', 'Gyroid', (), (side, 'asym-ratio', layout))]
            source = records[('nu', 'air', 'Gyroid', (), (side, 'asym-ratio', layout))]
            assert raw_re.maximum[0] < 1. and source.minimum[0] == 1.


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('side,bad', [(0, np.inf), (1, -np.inf), (2, np.nan), ('water', np.nan)])
def test_main_nonfinite_return_precedes_refresh_and_q(monkeypatch, legacy, side, bad):
    from sjtu_tpmshx.models.fluid_props import WaterStateError
    pair = ('air', 'water') if side == 'water' else ('air', 'air')
    pipe, fields = _prepare(monkeypatch, legacy=legacy, pair=pair)
    returned = []
    state = {}

    def forbidden(*args, **kwargs):
        pytest.fail('nonfinite return reached property refresh or Q processing')

    def thermal(*args, **kwargs):
        assert (kwargs.get('model_fluids') is None) == legacy
        result = _thermal(*args, **kwargs)
        result[1 if side == 'water' else side][0, 0] = bad
        if side == 'water':
            result[0][0, 0] = np.inf  # Water must win over A's generic failure.
        returned.extend(result[:3])
        for label in ('A', 'B'):
            state[f'_p{label}'].rho = forbidden
        return result

    def drive(*, step, **kwargs):
        state.update(_step_context(step))
        step(0)
        pytest.fail('nonfinite main step returned')

    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', forbidden)
    error = WaterStateError if side == 'water' else ValueError
    label = 'B' if side == 'water' else ('A', 'B', 'solid')[side]
    match = '2D energy return B' if side == 'water' else f'2D energy return: {label} temperature index='
    with warning_scope({}), pytest.raises(error, match=match):
        pipe.run_solvers(fields)
    assert not np.isfinite(returned[1 if side == 'water' else side][0, 0])


@pytest.mark.parametrize('where', ['main', 'richardson'])
@pytest.mark.parametrize('failure', [None, 'cp', 'transport'])
def test_inlet_cp_transport_order_and_failure_boundary(monkeypatch, where, failure):
    from sjtu_tpmshx.domain import run_warnings as rw
    events = []
    original = solve_2d._inlet_transport_2d

    def cp(side):
        def evaluate(*args):
            assert rw._range_context.get() == (side, f'{where}-inlet', 'scalar')
            events.append((side, 'cp'))
            if side == 'A' and failure == 'cp':
                raise ThermalBoundary
            return 1000.
        return evaluate

    def transport(*args):
        side, stage, layout = rw._range_context.get()
        assert stage == f'{where}-inlet' and layout == 'scalar'
        events.append((side, 'transport'))
        if side == 'A' and failure == 'transport':
            raise ThermalBoundary
        return original(*args)

    monkeypatch.setattr(solve_2d, '_inlet_transport_2d', transport)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', _stop)
    if where == 'main':
        pipe, fields = _prepare(monkeypatch, legacy=True)
        def drive(*, step, **kwargs):
            state = _step_context(step)
            for side in ('A', 'B'):
                state[f'_p{side}'].cp = cp(side)
            step(0)
        monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
        with warning_scope({}), pytest.raises(ThermalBoundary):
            pipe.run_solvers(fields)
    else:
        from sjtu_tpmshx.tests.test_richardson_validity_2d import _arguments
        _, args = _arguments(monkeypatch, full=True)
        for side in ('A', 'B'):
            args[f'rho_cp_{side}'] = np.ones_like(args['Ta'])
            args[f'_p{side}'] = replace(args[f'_p{side}'], cp=cp(side))
        with warning_scope({}), pytest.raises(ThermalBoundary):
            solve_2d._compute_Q_richardson(**args)
    expected = [('A', 'cp')]
    if failure != 'cp':
        expected.append(('A', 'transport'))
    if failure is None:
        expected += [('B', 'cp'), ('B', 'transport')]
    assert events == expected


@pytest.mark.parametrize('fallback', [False, True])
def test_richardson_stages_keep_shapes_and_fallback_sources(monkeypatch, fallback):
    from sjtu_tpmshx.domain import run_warnings as rw
    from sjtu_tpmshx.tests.test_richardson_validity_2d import _arguments
    _, args = _arguments(monkeypatch, full=True)
    args['Ta'][:] = 1050.
    args['Tb'][:] = 1150.
    calls = []
    for side in ('A', 'B'):
        def prop(T, P, side=side):
            calls.append(rw._range_context.get())
            return tpms_props.air_cp(T)
        args[f'_p{side}'] = replace(args[f'_p{side}'], cp=prop)

    def duty(*a, **k):
        calls.append(rw._range_context.get())
        tpms_props.air_cp(a[0])  # Observe the actual duty argument, no PDE claim.
        return float('nan') if fallback else 10.

    monkeypatch.setattr(solve_2d, 'solve_full_domain', _thermal)
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', duty)
    with warning_scope({}) as records:
        solve_2d._compute_Q_richardson(**args)
    coarse = args['Ta'].shape
    fine = tuple(n * 2 for n in coarse)
    for side in ('A', 'B'):
        for stage in ('richardson-warm', 'richardson-return'):
            rec = records[('property_state', 'air_cp', fine, (side, stage, 'real-cell(x,y)'))]
            assert rec.size == np.prod(fine)
        for stage, shape in (('main-duty', coarse), ('richardson-duty', fine)):
            rec = records[('property', 'air_cp', shape, (side, stage, 'duty-source'))]
            assert rec.size == np.prod(shape)
        assert (side, 'richardson-inlet', 'scalar') in calls
        assert ((side, 'fallback-inlet', 'scalar') in calls) is fallback


@pytest.mark.parametrize('where', ['main', 'richardson'])
def test_model_branch_does_not_evaluate_legacy_inlet_flux(monkeypatch, where):
    monkeypatch.setattr(solve_2d, '_inlet_transport_2d',
                        lambda *a: pytest.fail('model branch called legacy transport'))
    def thermal(*args, **kwargs):
        assert kwargs['inlet_flux_A'] is kwargs['inlet_flux_B'] is None
        assert kwargs['model_fluids'] == ('air', 'air')
        raise ThermalBoundary
    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    if where == 'main':
        pipe, fields = _prepare(monkeypatch)
        def drive(*, step, **kwargs):
            state = _step_context(step)
            for side in ('A', 'B'):
                state[f'_p{side}'].cp = lambda *a: pytest.fail('legacy inlet cp')
            step(0)
        monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
        with warning_scope({}), pytest.raises(ThermalBoundary):
            pipe.run_solvers(fields)
    else:
        from sjtu_tpmshx.tests.test_richardson_validity_2d import _arguments
        _, args = _arguments(monkeypatch, full=True)
        nx, ny = args['Ta'].shape
        mass = (np.ones((nx + 1, ny)), np.zeros((nx, ny + 1)))
        for side in ('A', 'B'):
            args[f'rho_cp_{side}'] = np.ones((nx, ny))
            args[f'_p{side}'] = replace(args[f'_p{side}'], cp=lambda *a: pytest.fail('legacy inlet cp'))
        inputs = dict(model_fluids=('air', 'air'), mass_flux_A=mass, mass_flux_B=mass,
                      K_ffA=.1, K_ffB=.2, K_ss=1.)
        with warning_scope({}), pytest.raises(ThermalBoundary):
            solve_2d._compute_Q_richardson(**args, model_inputs=inputs)


@pytest.mark.parametrize('pair,failed_side', [
    (('sco2', 'sco2'), None), (('sco2', 'air'), None),
    (('air', 'sco2'), None), (('sco2', 'sco2'), 'A'), (('sco2', 'sco2'), 'B'),
])
def test_sco2_notice_follows_first_successful_hv_without_extra_eos(monkeypatch, pair, failed_side):
    from sjtu_tpmshx.models import local_heat_transfer
    from sjtu_tpmshx.solvers import ltne_enthalpy_2d
    from sjtu_tpmshx.models import sco2_props, fluid_props
    from sjtu_tpmshx.domain import run_warnings as rw
    pipe, fields = _prepare(monkeypatch, pair=pair)
    original_hv = local_heat_transfer._sco2_hv_local_field
    original_notice = solve_2d.warn_sco2_nu_evidence
    events = []

    def hv(*args, **kwargs):
        side, stage, layout = rw._range_context.get()
        assert (stage, layout) == ('main-hv', 'real-cell(x,y)')
        if side == failed_side:
            raise ThermalBoundary
        value = original_hv(*args, **kwargs)
        events.append(('hv', side))
        return value

    def notice(**kwargs):
        side = kwargs['side']
        assert events[-1] == ('hv', side)
        assert kwargs == dict(side=side, stage='2D main-hv', tpms_type='Gyroid',
                              L_mm=7., t_mm=.6, P_in=9e6 if side == 'A' else 16e6)
        with monkeypatch.context() as patch:
            patch.setattr(sco2_props, '_PropsSI', lambda *a: pytest.fail('notice queried EOS'))
            patch.setattr(fluid_props.CP, 'AbstractState', lambda *a: pytest.fail('notice queried EOS'))
            result = original_notice(**kwargs)
        events.append(('notice', side))
        return result

    def thermal(*args, **kwargs):
        # Intentional high HEOS-Air output probes the empirical-state exclusion.
        shape = args[4][0].shape[0] - 1, args[4][0].shape[1]
        return (*(np.full(shape, 310. if fluid == 'sco2' else 1100.) for fluid in pair),
                np.full(shape, 350.), dict(converged=True, iterations=1, residual=0., Q_A=10., Q_B=-10.))

    def drive(*, step, **kwargs):
        for index in range(2):
            step(index)
        return 1, True

    monkeypatch.setattr(local_heat_transfer, '_sco2_hv_local_field', hv)
    monkeypatch.setattr(solve_2d, 'warn_sco2_nu_evidence', notice)
    monkeypatch.setattr(ltne_enthalpy_2d, 'solve_enthalpy_2d', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    with warning_scope({}) as records:
        if failed_side:
            with pytest.raises(ThermalBoundary):
                pipe.run_solvers(fields)
        else:
            pipe.run_solvers(fields)
    sides = [side for side, fluid in zip(('A', 'B'), pair) if fluid == 'sco2']
    succeeded = sides if failed_side is None else sides[:sides.index(failed_side)]
    assert [event for event in events if event[0] == 'notice'] == [('notice', side) for side in succeeded]
    assert [event for event in events if event[0] == 'hv'] == [('hv', side) for side in succeeded] * (2 if not failed_side else 1)
    assert {key[2] for key in records if key[0] == 'nu-evidence'} == set(succeeded)
    assert not any(key[0] == 'property_state' for key in records)


def _failure_flow(monkeypatch, fields, *, side, invalid):
    original = fields['_run_simple']

    def worker(*args, **kwargs):
        u, v, solver = original(*args, **kwargs)
        solver._test_side = args[5][-1]
        solver.P[:] = 0.
        solver.P_ref_abs = 1000. if invalid and solver._test_side == side else 101325.
        return u, v, solver

    fields['_run_simple'] = worker


@pytest.mark.parametrize('boundary', ['mass', 'thermal'])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('mode', ['raise', 'warn', 'off'])
@pytest.mark.parametrize('invalid', [False, True])
def test_fatal_nonfinite_classifies_only_invalid_flow(monkeypatch, boundary, side, mode, invalid):
    from sjtu_tpmshx.models.envelope import ChokedFlowError
    pipe, fields = _prepare(monkeypatch)
    pipe._parsed['envelope_mode'] = mode
    _failure_flow(monkeypatch, fields, side=side, invalid=invalid)
    if boundary == 'mass':
        original = solve_2d._face_mass_fluxes_2d

        def mass(solver, *args):
            faces = original(solver, *args)
            if solver._test_side == side:
                faces[0][0, 0] = np.nan
            return faces

        monkeypatch.setattr(solve_2d, '_face_mass_fluxes_2d', mass)
    else:
        def thermal(*args, **kwargs):
            result = _thermal(*args, **kwargs)
            result[0 if side == 'A' else 1][0, 0] = np.nan
            return result

        monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    error = ChokedFlowError if invalid and mode == 'raise' else ValueError
    message = (f'2D-{side} solver returned' if error is ChokedFlowError else
               'mass faces must be finite' if boundary == 'mass' else 'temperature index=')
    with warning_scope({}), pytest.raises(error, match=message):
        pipe.run_solvers(fields)


@pytest.mark.parametrize('side', ['A', 'B'])
def test_malformed_mass_keeps_original_error_with_invalid_flow(monkeypatch, side):
    pipe, fields = _prepare(monkeypatch)
    _failure_flow(monkeypatch, fields, side=side, invalid=True)
    original = solve_2d._face_mass_fluxes_2d

    def mass(solver, *args):
        x, y = original(solver, *args)
        if solver._test_side == side:
            x = x[:-1].copy()
            x[:] = np.nan
        return x, y

    monkeypatch.setattr(solve_2d, '_face_mass_fluxes_2d', mass)
    with warning_scope({}), pytest.raises(ValueError, match='mass faces must be finite'):
        pipe.run_solvers(fields)


@pytest.mark.parametrize('water_side', ['A', 'B'])
@pytest.mark.parametrize('boundary', ['SIMPLE', 'energy'])
def test_water_return_precedes_invalid_air_classification(monkeypatch, water_side, boundary):
    from sjtu_tpmshx.models.fluid_props import WaterStateError
    pair = ('water', 'air') if water_side == 'A' else ('air', 'water')
    pipe, fields = _prepare(monkeypatch, pair=pair, temperatures=(300., 300.))
    _failure_flow(monkeypatch, fields, side='B' if water_side == 'A' else 'A', invalid=True)
    original = fields['_run_simple']

    def worker(*args, **kwargs):
        u, v, solver = original(*args, **kwargs)
        if boundary == 'SIMPLE' and solver._test_side == water_side:
            solver.P[:] = np.nan
        return u, v, solver

    fields['_run_simple'] = worker

    def thermal(*args, **kwargs):
        result = _thermal(*args, **kwargs)
        result[0][:] = result[1][:] = np.nan
        return result

    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    with warning_scope({}), pytest.raises(WaterStateError, match=f'2D {boundary} return {water_side}'):
        pipe.run_solvers(fields)


def test_finite_intermediate_off_envelope_still_reaches_thermal(monkeypatch):
    pipe, fields = _prepare(monkeypatch)
    _failure_flow(monkeypatch, fields, side='A', invalid=True)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', _stop)
    with warning_scope({}), pytest.raises(ThermalBoundary):
        pipe.run_solvers(fields)


@pytest.mark.parametrize('iteration,bad_input', [(0, False), (1, False), (1, True)])
def test_failure_mach_uses_current_simple_input_not_nan_return(monkeypatch, iteration, bad_input):
    pipe, fields = _prepare(monkeypatch)
    pipe._parsed['T_s_init'] = 350.
    _failure_flow(monkeypatch, fields, side='A', invalid=bad_input)
    seen = []
    original = solve_2d.mach_field_max

    def mach(speed, temperature):
        seen.append(np.asarray(temperature).copy())
        return original(speed, temperature)

    def thermal(*args, **kwargs):
        result = _thermal(*args, **kwargs)
        result[0][:] = np.nan
        return result

    def drive(*, step, **kwargs):
        state = _step_context(step)
        state['Ta'][:] = np.nan if bad_input else 330.
        state['Tb'][:] = 310.
        step(iteration)

    monkeypatch.setattr(solve_2d, 'mach_field_max', mach)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', thermal)
    monkeypatch.setattr(solve_2d, 'run_outer_coupling', drive)
    with warning_scope({}), pytest.raises(ValueError, match='temperature index='):
        pipe.run_solvers(fields)
    expected_values = (310.,) if bad_input else (400., 300.) if iteration == 0 else (330., 310.)
    assert len(seen) == len(expected_values)
    for actual, expected in zip(seen, expected_values):
        assert np.all(actual == expected)
