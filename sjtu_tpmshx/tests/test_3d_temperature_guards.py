"""Actual 3D guard boundaries with numerical sweeps replaced, not full solves."""

from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
from sjtu_tpmshx.tests.test_3d_model_enthalpy_transport import _pipeline_cfg
from sjtu_tpmshx.domain.run_warnings import warning_scope, range_context
from sjtu_tpmshx.preprocess.thermal_geometry import prepare_thermal_geometry


@pytest.mark.parametrize('co2_side', ['A', 'B'])
@pytest.mark.parametrize('seed', [np.nan, np.inf, -np.inf, None, 325.])
def test_typed_co2_solid_seed_checked_before_thermal_calls(monkeypatch, co2_side, seed):
    from sjtu_tpmshx.pipelines.stages_3d import _parse_inputs_3d_cfg
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg
    from sjtu_tpmshx.solvers import ltne_energy_3d

    cfg = _small_air_cfg()
    fluid = getattr(cfg, f'fluid_{co2_side}')
    fluid.type, fluid.P_in_Pa = 'sco2', 12e6
    cfg.solver.T_s_init_K = seed
    cfg.validate()
    parsed = _parse_inputs_3d_cfg(cfg)
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(parsed)
    hv = stages._build_hv_machinery(prob)
    shape = (prob.Nx, prob.Ny, prob.Nz)
    returned = tuple(np.full(shape, t) for t in (400., 330., 350.))
    invalid = seed is not None and not np.isfinite(seed)
    calls = []

    class ObservedBothThermalEntries(Exception):
        pass

    def temperature(*args, **kwargs):
        assert not invalid, 'invalid config seed reached temperature thermal call'
        calls.append('temperature')
        assert kwargs['max_iter'] == 2
        for key, value in (('Ta_init', prob.T_inA), ('Tb_init', prob.T_inB), ('Ts_init', seed)):
            if seed is None:
                assert kwargs[key] is None
            else:
                np.testing.assert_array_equal(kwargs[key], np.full(shape, value))
        return (*returned, dict(converged=True, iterations=2, residual=0.))

    def enthalpy(*args, **kwargs):
        assert not invalid, 'invalid config seed reached true-h thermal call'
        calls.append('enthalpy')
        for key, value in zip(('Ta_init', 'Tb_init', 'Ts_init'), returned):
            np.testing.assert_array_equal(kwargs[key], value)
        raise ObservedBothThermalEntries

    monkeypatch.setattr(stages, 'solve_full_domain_3d', temperature)
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', enthalpy)
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))
    monkeypatch.setattr(stages, 'run_outer_coupling', lambda *, step, **k: step(0))
    with warning_scope({}):
        if invalid:
            with pytest.raises(ValueError) as error:
                stages._run_outer_coupling_3d(prob, hv)
            assert str(error.value) == (
                f'3D temperature warm start: solid temperature index=(0, 0, 0), '
                f'T={seed:g} K is non-finite')
            assert calls == []
        else:
            with pytest.raises(ObservedBothThermalEntries):
                stages._run_outer_coupling_3d(prob, hv)
            assert calls == ['temperature', 'enthalpy']


@pytest.mark.parametrize('side', range(3))
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_finite_temperature_reports_first_c_index_and_original_value(side, bad):
    fields = [np.full((2, 3, 2), 300., order='F') for _ in range(3)]
    fields[side][0, 2, 1] = bad
    fields[side][1, 0, 0] = np.nan  # earlier in Fortran order, later in C order
    with pytest.raises(ValueError) as error:
        fluid_props.check_finite_temperatures(*fields, where='test real-cell')
    assert type(error.value) is ValueError
    assert str(error.value) == (
        f'test real-cell: {("A", "B", "solid")[side]} temperature '
        f'index=(0, 2, 1), T={bad:g} K is non-finite')
    assert np.isnan(fields[side][0, 2, 1]) if np.isnan(bad) else fields[side][0, 2, 1] == bad


def test_finite_temperature_none_and_finite_values_do_not_query_eos(monkeypatch):
    def forbidden(*args):
        pytest.fail('finite check must not query EOS')
    monkeypatch.setattr(fluid_props.CP, 'AbstractState', forbidden)
    field = np.array([[-1., 0., 1.]])  # finite check is not a new physical range
    original = field.copy()
    fluid_props.check_finite_temperatures(None, None, None, where='cold start')
    fluid_props.check_finite_temperatures(300., field, None, where='warm start')
    np.testing.assert_array_equal(field, original)
    with pytest.raises(ValueError, match=r'A temperature index=\(\), T=inf'):
        fluid_props.check_finite_temperatures(np.inf, np.nan, np.nan, where='scalar')


def _problem(monkeypatch, pair):
    cfg = _pipeline_cfg(pair)
    for side, fluid in zip(('A', 'B'), pair):
        if fluid == 'sco2':
            cfg['P_in' + side] = 12e6
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(cfg)
    return prob, stages._build_hv_machinery(prob)


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
@pytest.mark.parametrize('zoned', [False, True])
def test_local_hv_records_full_raw_field_and_preserves_values(monkeypatch, fluid, zoned):
    prob, hv = _problem(monkeypatch, (fluid, fluid))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    length = np.full(shape, prob.Lcell) if zoned else None
    thickness = np.full(shape, prob.t_wall) if zoned else None
    if zoned:
        length[1:] += .1
        prob.cfg['thermal_geometry'] = prepare_thermal_geometry(
            prob.tpms_type, prob.Lcell, prob.t_wall, prob.k_s,
            L_field=length, t_field=thickness)
    velocity = np.zeros(shape)
    velocity[-1] = .001
    args = (length, thickness, velocity, prob.T_inA, prob.P_inA, fluid)
    with warning_scope({}):
        expected = hv._build_hv_local_3d(*args)
    labels = ('A', 'main', 'real-cell(x,y,z)-hv-stream')
    with warning_scope({}) as records, range_context(side=labels[0], stage=labels[1], layout=labels[2]):
        for _ in range(2):
            actual = hv._build_hv_local_3d(*args)
    np.testing.assert_array_equal(actual, expected)
    raw = records[('nu_raw', fluid, prob.tpms_type, shape, labels)]
    assert raw.size == velocity.size
    assert raw.minimum[1] == (0, 0, 0) and 0 < raw.minimum[0] < 1.
    source_shape = () if zoned else shape
    source_labels = ('A', 'main', 'scalar-zoned-call') if zoned else labels
    source = records[('nu', fluid, prob.tpms_type, source_shape, source_labels)]
    assert source.size == (1 if zoned else velocity.size)
    assert source.minimum[0] == 1.


def test_temperature_warning_states_keep_warm_return_final_and_face_separate(monkeypatch):
    prob, hv = _problem(monkeypatch, ('air', 'air'))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (1150., 1200., 325.)]
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (
        *fields, dict(converged=True, iterations=1, residual=0.)))

    def drive(*, step, **kwargs):
        state = inspect.getclosurevars(step).nonlocals
        state['Ta'][:] = 1100.
        state['Tb'][:] = 1120.
        step(0)
        return 0, True

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with warning_scope({}) as records:
        outer = stages._run_outer_coupling_3d(prob, hv)
        stages._extract_3d_metrics(prob, hv, outer)
    for side, warm, final in (('A', 1100., 1150.), ('B', 1120., 1200.)):
        for stage, layout, value in (
            ('main', 'real-cell(x,y,z)-warm', warm),
            ('main', 'real-cell(x,y,z)-return', final),
            ('final', 'real-cell(x,y,z)', final),
            ('final', 'outlet-cell-face(real-transverse-axes)', final),
        ):
            record_shape = shape[:2] if layout.startswith('outlet') else shape
            record = records[('property_state', 'air_cp', record_shape, (side, stage, layout))]
            assert record.minimum[0] == record.maximum[0] == value
            assert record.size == np.prod(record_shape)
    assert all(key[-1][0] != 'solid' for key in records)


def test_true_h_air_return_does_not_use_empirical_temperature_windows(monkeypatch):
    prob, hv = _problem(monkeypatch, ('air', 'sco2'))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (1200., 310., 325.)]
    info = dict(converged=True, iterations=1, residual=0., Q_A=1., Q_B=1.)
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (*fields, info))
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', lambda *a, **k: (*fields, info))
    from sjtu_tpmshx.solvers import ltne_energy_3d
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))

    def drive(*, step, **kwargs):
        step(0)
        return 0, True

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with warning_scope({}) as records:
        stages._run_outer_coupling_3d(prob, hv)
    assert not any(key[0] == 'property_state' for key in records)


def test_zoned_sco2_notice_uses_successful_local_hv_fields(monkeypatch):
    cfg = _pipeline_cfg(('sco2', 'sco2'))
    cfg.pop('T_s_init')  # Only the raw-stage first scalar-temperature refresh.
    cfg.update(P_inA=9e6, P_inB=16e6, zone_grid_cells=[
        dict(x0=0., x1=.5, y0=0., y1=1., L=5., t=.3),
        dict(x0=.5, x1=1., y0=0., y1=1., L=6., t=.4)])
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(cfg)
    hv = stages._build_hv_machinery(prob)
    assert 5. < prob.L_mm_field.min() < prob.L_mm_field.max() < 6.
    assert .3 < prob.t_field_3d.min() < prob.t_field_3d.max() < .4
    original_hv, original_notice = hv._build_hv_local_3d, stages.warn_sco2_nu_evidence
    events = []

    def local(*args, **kwargs):
        assert args[0] is prob.L_mm_field and args[1] is prob.t_field_3d
        assert np.ndim(args[3]) == 0
        value = original_hv(*args, **kwargs)
        events.append(('hv', args[4]))
        return value

    def notice(**kwargs):
        pressure = prob.P_inA if kwargs['side'] == 'A' else prob.P_inB
        assert events[-1] == ('hv', pressure)
        assert kwargs['L_mm'] is prob.L_mm_field and kwargs['t_mm'] is prob.t_field_3d
        assert kwargs['P_in'] == pressure and kwargs['stage'] == '3D h_v property refresh'
        events.append(('notice', kwargs['side']))
        return original_notice(**kwargs)

    class ThermalBoundary(Exception):
        pass

    def stop(*args, **kwargs):
        raise ThermalBoundary

    monkeypatch.setattr(hv, '_build_hv_local_3d', local)
    monkeypatch.setattr(stages, 'warn_sco2_nu_evidence', notice)
    monkeypatch.setattr(stages, 'solve_full_domain_3d', stop)
    monkeypatch.setattr(stages, 'run_outer_coupling', lambda *, step, **k: step(0))
    with warning_scope({}) as records, pytest.raises(ThermalBoundary):
        stages._run_outer_coupling_3d(prob, hv)
    assert events == [('hv', 9e6), ('notice', 'A'), ('hv', 16e6), ('notice', 'B')]
    messages = [value for key, value in records.items() if key[0] == 'nu-evidence']
    assert len(messages) == 2
    geometry = (f'zoned L=[{prob.L_mm_field.min():g},{prob.L_mm_field.max():g}] mm, '
                f't=[{prob.t_field_3d.min():g},{prob.t_field_3d.max():g}] mm')
    assert all(geometry in message and 'L=7 mm, t=0.6 mm' not in message for message in messages)


def test_sco2_evidence_once_per_side_after_first_local_refresh_with_cached_properties(monkeypatch):
    cfg = _pipeline_cfg(('sco2', 'sco2'))
    cfg.update(P_inA=9e6, P_inB=16e6)
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(cfg)
    hv = stages._build_hv_machinery(prob)
    prob.cfg.pop('T_s_init')  # Actual first scalar and subsequent array h_v routes.
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (350., 310., 325.)]
    info = dict(converged=True, iterations=1, residual=0., Q_A=1., Q_B=1.)
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (*fields, info))
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', lambda *a, **k: (*fields, info))
    from sjtu_tpmshx.solvers import ltne_energy_3d
    from sjtu_tpmshx.models import sco2_props
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))
    original_hv, original_notice = hv._build_hv_local_3d, stages.warn_sco2_nu_evidence
    events = []

    def local(*args, **kwargs):
        before = sco2_props._prop.cache_info()
        value = original_hv(*args, **kwargs)
        after = sco2_props._prop.cache_info()
        ndim = np.ndim(args[3])
        if ndim == 0:
            assert after.hits > before.hits and after.misses == before.misses
        events.append(('hv', ndim))
        return value

    def notice(**kwargs):
        events.append(('notice', kwargs['side']))
        assert kwargs == dict(side=kwargs['side'], stage='3D h_v property refresh',
                              tpms_type=prob.tpms_type, L_mm=prob.Lcell,
                              t_mm=prob.t_wall, P_in=prob.P_inA if kwargs['side'] == 'A' else prob.P_inB)
        return original_notice(**kwargs)

    monkeypatch.setattr(hv, '_build_hv_local_3d', local)
    monkeypatch.setattr(stages, 'warn_sco2_nu_evidence', notice)

    def drive(*, step, **kwargs):
        step(0)
        step(1)
        return 1, True

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with warning_scope({}) as records:
        stages._run_outer_coupling_3d(prob, hv)
    assert events == [('hv', 0), ('notice', 'A'), ('hv', 0), ('notice', 'B'),
                      ('hv', 3), ('hv', 3)]
    notices = {key: value for key, value in records.items() if key[0] == 'nu-evidence'}
    assert set(notices) == {('nu-evidence', 'sco2', side, '3D h_v property refresh')
                            for side in ('A', 'B')}


@pytest.mark.parametrize('fluid', ['air', 'water'])
def test_zoned_bulk_re_has_cell_denominator_and_scalar_source(monkeypatch, fluid):
    prob, _ = _problem(monkeypatch, (fluid, fluid))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    prob.L_mm_field = np.full(shape, prob.Lcell)
    prob.L_mm_field[1:] += .1
    prob.t_field_3d = np.full(shape, prob.t_wall)
    prob.cfg['thermal_geometry'] = prepare_thermal_geometry(
        prob.tpms_type, prob.Lcell, prob.t_wall, prob.k_s,
        L_field=prob.L_mm_field, t_field=prob.t_field_3d)
    from sjtu_tpmshx.preprocess.three_d.preparation import _prepare_air_bulk_hv
    with warning_scope({}) as records:
        prob.cfg['thermal_geometry']['air_bulk_hv'] = _prepare_air_bulk_hv(
            prob.cfg, prob.L_mm_field, prob.t_field_3d, shape)
        stages._build_hv_machinery(prob)
    for side in ('A', 'B'):
        raw = records[('nu_raw', fluid, prob.tpms_type, shape,
                       (side, 'inlet', 'real-cell(x,y,z)-bulk-Re'))]
        source = records[('nu', fluid, prob.tpms_type, (),
                          (side, 'inlet', 'scalar-zoned-call'))]
        assert raw.size == np.prod(shape) and source.size == 1


@pytest.mark.parametrize('phase', ['warm', 'temperature', 'enthalpy'])
@pytest.mark.parametrize('side', range(3))
def test_wired_nonfinite_boundaries_precede_post_and_result(monkeypatch, phase, side):
    prob, hv = _problem(monkeypatch, ('air', 'sco2') if phase == 'enthalpy' else ('air', 'air'))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (350., 300., 325.)]
    fields[side][1, 2, 1] = np.inf

    def thermal(*args, **kwargs):
        output = fields if phase == 'temperature' else [np.full(shape, t) for t in (350., 300., 325.)]
        return (*output, dict(converged=True, iterations=1, residual=0.))

    monkeypatch.setattr(stages, 'solve_full_domain_3d', thermal)
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', lambda *a, **k: (*fields, {}))
    # Projection is unrelated to the return guard; keep this a no-sweep test.
    from sjtu_tpmshx.solvers import ltne_energy_3d
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))

    def drive(*, step, **kwargs):
        if phase == 'warm':
            state = inspect.getclosurevars(step).nonlocals
            state[('Ta', 'Tb', 'Ts')[side]][:] = fields[side]
        step(0)
        pytest.fail('invalid temperature reached normal outer return')

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    where = '3D temperature warm start' if phase == 'warm' else f'3D {phase} return'
    with pytest.raises(ValueError) as error:
        stages._run_outer_coupling_3d(prob, hv)
    assert type(error.value) is ValueError
    assert str(error.value) == (
        f'{where}: {("A", "B", "solid")[side]} temperature '
        'index=(1, 2, 1), T=inf K is non-finite')


@pytest.mark.parametrize('warm', [False, True])
def test_water_error_still_precedes_generic_finite_error(monkeypatch, warm):
    prob, hv = _problem(monkeypatch, ('air', 'water'))
    fields = [np.full((prob.Nx, prob.Ny, prob.Nz), t) for t in (350., 300., 325.)]
    fields[0][0, 0, 0] = np.inf
    fields[1][1, 2, 1] = np.nan
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (*fields, {}))

    def drive(*, step, **kwargs):
        if warm:
            state = inspect.getclosurevars(step).nonlocals
            state['Ta'][:] = fields[0]
            state['Tb'][:] = fields[1]
        step(0)
        pytest.fail('invalid water was accepted')

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with pytest.raises(fluid_props.WaterStateError, match='3D temperature .* B: water index='):
        stages._run_outer_coupling_3d(prob, hv)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('converged', [False, True])
@pytest.mark.parametrize('invalid', [False, True])
def test_final_co2_guard_uses_report_pressure_after_either_exit(monkeypatch, side, converged, invalid):
    prob, hv = _problem(monkeypatch, ('sco2', 'sco2'))
    original_outer = stages.run_outer_coupling
    checked = []
    validate = stages.sco2_props._validate_state
    expected = None

    def check(t, p, *, where=None):
        if where and where.startswith('3D final report state'):
            checked.append(where)
            if where.endswith(side):
                np.testing.assert_array_equal(p, expected)
        return validate(t, p, where=where)

    def drive(**kwargs):
        nonlocal expected
        solver = prob.sA if side == 'A' else prob.sB
        solver.P_ref_abs = 11e6  # deliberately different from kernel's inlet anchor
        solver.P[:] = 0.
        def inject():
            if invalid:
                solver.P[1, 2, 1] = -4e6  # interior report P=7 MPa; outlet stays valid
        def step(_):
            if converged:
                inject()
            return converged, None
        def post(*_):
            inject()
        terminal = original_outer(max_iter=1, step=step, post=post)
        # _pipeline_cfg uses real +y for A and -y for B.
        expected = (11e6 + solver.P).copy()
        if side == 'B':
            expected = expected[:, ::-1, :].copy()
        def forbidden(*a, **k):
            pytest.fail('final range check must not query EOS')
        monkeypatch.setattr(stages.sco2_props, '_PropsSI', forbidden)
        return terminal

    monkeypatch.setattr(stages.sco2_props, '_validate_state', check)
    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    if invalid:
        with pytest.raises(ValueError) as error:
            stages._run_outer_coupling_3d(prob, hv)
        index = '(1, 2, 1)' if side == 'A' else '(1, 1, 1)'
        assert f'3D final report state {side}, index={index}' in str(error.value)
        assert 'P=7000000.0 Pa' in str(error.value)
    else:
        result = stages._run_outer_coupling_3d(prob, hv)
        np.testing.assert_array_equal(result.Ta, np.full_like(result.Ta, 350.))
        np.testing.assert_array_equal(result.Tb, np.full_like(result.Tb, 300.))
    assert checked.count(f'3D final report state {side}') == 1
