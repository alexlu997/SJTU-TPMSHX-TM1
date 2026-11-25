"""Check float64 Quick preparation and pressure-fraction contracts against pure formulas."""
import ctypes
from dataclasses import replace
from inspect import getsourcelines
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.applications.design.cases import DesignCase
from sjtu_tpmshx.cpp_interface import quick_preparation as wire
from sjtu_tpmshx.preprocess import quick_design as production
from sjtu_tpmshx.physical_models import co2_props, fluid_props, sco2_props
from sjtu_tpmshx.physical_models.tpms_geometry import compute_geometry
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.run_control.run_warnings import range_observations, warning_scope
from tests.python import df_reference, preparation_flow_reference as flow_ref, property_reference as prop_ref


def _case(**changes):
    return replace(DesignCase(1, 'air', 480., 9e6, .03,
                              'air', 320., 9e6, .02, 100., .05, .05), **changes)


def _args(**changes):
    arguments = dict(case=_case(), topo='Diamond', l=7., t=.5, s=.084,
                     Lx=.025, arrangement='cross')
    arguments.update(changes)
    return arguments


@pytest.fixture(autouse=True)
def isolated_quick_inputs(monkeypatch):
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    monkeypatch.delenv('TPMSHX_DF_METHOD', raising=False)
    compute_geometry.cache_clear()
    sco2_props._prop.cache_clear()
    co2_props._scalar.cache_clear()
    yield
    compute_geometry.cache_clear()
    sco2_props._prop.cache_clear()
    co2_props._scalar.cache_clear()


def _oracle_pressure_fraction(case, topo, l, t, s, Lx, arrangement, height, side):
    geom = compute_geometry(topo, float(l), float(t), N=128)
    eps_a = float(geom['epsilon_A'])
    h = float(s if height is None else height)
    a_h, l_h, a_c, l_c = flow_ref.quick_design_sections(
        eps_a, float(s), float(Lx), h, arrangement == 'cross')
    fluid = case.hot_fluid if side == 'A' else case.cold_fluid
    T_in = float(case.T_in_h if side == 'A' else case.T_in_c)
    P_in = float(case.P_in_h if side == 'A' else case.P_in_c)
    mdot = float(case.mdot_h if side == 'A' else case.mdot_c)
    area, path_len = (a_h, l_h) if side == 'A' else (a_c, l_c)
    props = prop_ref.fluid_props(fluid, T_in, P_in)
    if fluid == 'air':
        g_flux, _ = flow_ref.side_flow(mdot, area, props.rho, True)
        dp = df_reference.predict_dP_compressible(
            topo, float(l), float(t), eps_a, g_flux, T_in, P_in, props.mu, path_len)
    else:
        _, vel = flow_ref.side_flow(mdot, area, props.rho, False)
        dp = df_reference.predict_dP(
            topo, float(l), float(t), eps_a, vel, props.rho, props.mu, path_len)
    return float(dp) / P_in


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
@pytest.mark.parametrize('prop_model', ['const', 'mean'])
@pytest.mark.parametrize('height', [None, .042])
def test_complete_preparation_keeps_fixed_grid_controls_and_units(topology, arrangement, prop_model, height):
    actual = production.prepare_quick_design(
        **_args(topo=topology, arrangement=arrangement, prop_model=prop_model, height=height),
        case_id='quick-check')
    shape = (60, 40, 1) if arrangement == 'cross' else (60, 1, 2)
    assert actual.design_fields['eps'].shape == shape
    assert actual.design_fields['eps'].dtype == np.float64
    assert actual.design_fields['K_ss'].dtype == np.float64
    np.testing.assert_allclose(actual.design_fields['eps_A'], .5 * actual.design_fields['eps'])
    assert actual.parameters['L_cell_m'] == pytest.approx(.007)
    assert actual.parameters['t_wall_m'] == pytest.approx(.0005)
    expected_h = .084 if height is None else height
    assert actual.parameters['height'] == pytest.approx(expected_h)
    assert actual.parameters['controls']['qtol'] == (1e-4 if arrangement == 'cross' else None)
    assert actual.parameters['controls']['chunk'] == (100 if arrangement == 'cross' else None)
    for axis, total in zip('xyz', (.025, .084, expected_h)):
        assert actual.grid['d' + axis].sum() == pytest.approx(total, rel=1e-12)
    for side in 'AB':
        expected_dp = _oracle_pressure_fraction(_case(), topology, 7., .5, .084, .025, arrangement, height, side)
        assert actual.parameters['inlet_pressure_fractions'][side] == pytest.approx(expected_dp, rel=1e-12)


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('hot,cold', [('air', 'water'), ('water', 'air'),
    ('water', 'sco2'), ('sco2', 'water'), ('sco2', 'sco2'), ('co2', 'air')])
def test_preparation_keeps_fluid_property_routes(pressure, hot, cold):
    state = {'air': (480., 9e6), 'water': (350., 2e5), 'sco2': (480., 9e6), 'co2': (480., 9e6)}
    case = _case(hot_fluid=hot, cold_fluid=cold,
                 T_in_h=state[hot][0], P_in_h=state[hot][1],
                 T_in_c=state[cold][0], P_in_c=state[cold][1])
    if pressure:
        fracs = production.pressure_fractions(**_args(case=case))
        assert len(fracs) == 2 and all(np.isfinite(v) and v >= 0. for v in fracs)
    else:
        prepared = production.prepare_quick_design(**_args(case=case), case_id='fluids')
        assert all(np.isfinite(v) and v >= 0. for v in prepared.parameters['inlet_pressure_fractions'].values())


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
def test_scalar_inputs_normalize_to_float64(pressure, dtype):
    arguments = _args(l=dtype(7.), t=dtype(.5), s=dtype(.084), Lx=dtype(.025), height=dtype(.042),
        case=_case(T_in_h=dtype(480.), T_in_c=dtype(320.), mdot_h=dtype(.03), mdot_c=dtype(.02)))
    if pressure:
        fracs = production.pressure_fractions(**arguments)
        assert all(type(v) is float and np.isfinite(v) for v in fracs)
    else:
        arguments.update(k_s=dtype(16.3), tol=dtype(1e-5))
        prepared = production.prepare_quick_design(**arguments, case_id='dtype-check')
        for field in ('eps', 'eps_A', 'K_ss'):
            assert prepared.design_fields[field].dtype == np.float64


@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
@pytest.mark.parametrize('dtype', [np.int16, np.float16, np.float32, '>f8'])
@pytest.mark.parametrize('layout', ['tuple', 'list', 'stack', 'reverse'])
def test_warm_inputs_normalize_to_float64_and_preserve_shape(arrangement, dtype, layout):
    shape = (60, 40, 1) if arrangement == 'cross' else (60, 1, 2)
    warm = tuple(np.full(shape, temperature, dtype=dtype) for temperature in (340., 320., 330.))
    if layout == 'list':
        warm = list(warm)
    elif layout == 'stack':
        warm = np.stack(warm)
    elif layout == 'reverse':
        warm = tuple(value[::-1, ::-1, ::-1] for value in warm)
    prepared = production.prepare_quick_design(**_args(arrangement=arrangement, init=warm), case_id='warm')
    initial = prepared.parameters['initial_fields']
    assert len(initial) == 3
    for array, expected_val in zip(initial, (340., 320., 330.)):
        assert array.shape == shape
        np.testing.assert_allclose(np.asarray(array, dtype=np.float64), expected_val)


@pytest.mark.parametrize('warm', [(np.zeros(2),) * 3, (np.zeros((60, 40)),) * 3])
def test_warm_shape_failure_follows_positive_input_checks(warm):
    with pytest.raises(ValueError, match='quick-design warm start must match the prepared grid'):
        production.prepare_quick_design(**_args(init=warm), case_id='warm-shape')
    with pytest.raises(ValueError, match='quick-design l must be finite and positive'):
        production.prepare_quick_design(**_args(init=warm, l=-1.), case_id='warm-l')


@pytest.mark.parametrize('field', ['l', 't', 's', 'Lx', 'height', 'k_s', 'tol',
                                  'mdot_h', 'mdot_c', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c'])
@pytest.mark.parametrize('value', [0., np.nan, -1.])
def test_ordered_positive_input_failures(field, value):
    arguments = _args(case=_case(**{field: value})) if hasattr(_case(), field) else _args(**{field: value})
    with pytest.raises(ValueError):
        production.prepare_quick_design(**arguments, case_id='invalid-positive')


@pytest.mark.parametrize('side', ['hot', 'cold'])
@pytest.mark.parametrize('pressure', [False, True])
def test_water_state_failure_raises_water_state_error(side, pressure):
    suffix = 'h' if side == 'hot' else 'c'
    case = _case(**{side + '_fluid': 'water', 'T_in_' + suffix: 350., 'P_in_' + suffix: 10000.})
    with pytest.raises(fluid_props.WaterStateError):
        if pressure:
            production.pressure_fractions(**_args(case=case))
        else:
            production.prepare_quick_design(**_args(case=case), case_id='water-err')


def test_non_dataclass_case_fails_with_type_error():
    case = SimpleNamespace(**vars(_case()))
    with pytest.raises(TypeError, match='asdict'):
        production.prepare_quick_design(**_args(case=case), case_id='non-dc')


def test_geometry_cache_hit_and_clear():
    arguments = _args(case_id='cache-clear')
    prepared = production.prepare_quick_design(**arguments)
    assert tuple(compute_geometry.cache_info()) == (0, 1, 32768, 1)
    geometry = compute_geometry(arguments['topo'], arguments['l'], arguments['t'])
    assert (prepared.parameters['A_0'], prepared.parameters['D_h']) == (geometry['A_0'], geometry['D_h'])
    assert tuple(compute_geometry.cache_info()) == (1, 1, 32768, 1)
    production.prepare_quick_design(**arguments)
    assert tuple(compute_geometry.cache_info()) == (2, 1, 32768, 1)
    compute_geometry.cache_clear()
    production.prepare_quick_design(**arguments)
    assert tuple(compute_geometry.cache_info()) == (0, 1, 32768, 1)


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('fluid', ['sco2', 'co2'])
def test_eos_scalar_caches_share_external_warming_and_clear(pressure, fluid):
    get, owner = ((sco2_props.sco2_prop, sco2_props._prop) if fluid == 'sco2'
                  else (co2_props.co2_prop, co2_props._scalar))
    case = _case(hot_fluid=fluid)
    arguments = _args(case=case)
    if pressure:
        prepare = production.pressure_fractions
    else:
        prepare = production.prepare_quick_design
        arguments['case_id'] = 'eos-cache'
    keys = ('D', 'V', 'L', 'C')
    expected = tuple(get(key, case.T_in_h, case.P_in_h) for key in keys)
    warm = owner.cache_info()
    assert warm.currsize == (4 if fluid == 'sco2' else 1)
    prepare(**arguments)
    assert (owner.cache_info().hits, owner.cache_info().misses) == (warm.hits + 4, warm.misses)
    owner.cache_clear()
    prepare(**arguments)
    cold = owner.cache_info()
    assert (cold.currsize, cold.misses) == (warm.currsize, warm.misses)
    assert tuple(get(key, case.T_in_h, case.P_in_h) for key in keys) == expected
    assert owner.cache_info().hits == cold.hits + 4


def test_sco2_missing_pressure_raises_value_error():
    with pytest.raises(ValueError, match='sCO2 properties require pressure P'):
        production.pressure_fractions(**_args(case=_case(hot_fluid='sco2', P_in_h=None)))


def test_valid_chi_does_not_change_final_quick_solid_fields(monkeypatch):
    original = production.prepare_quick_design(**_args(), case_id='chi-orig')
    monkeypatch.setenv('TPMSHX_CHI_S', '.7')
    changed = production.prepare_quick_design(**_args(), case_id='chi-changed')
    for key in original.design_fields:
        np.testing.assert_array_equal(changed.design_fields[key], original.design_fields[key])
    assert changed.parameters['_environment']['TPMSHX_CHI_S'] == '.7'


def test_property_range_records_keep_source_side_and_stage():
    with warning_scope({}) as records:
        production.prepare_quick_design(**_args(case=_case(T_in_h=1200.)), case_id='ranges')
    assert {key[-1][0] for key in records} == {'A', 'B'}
    assert all(key[-1][1:] == ('design-dp-inlet', 'scalar') for key in records)
    assert any(row['high'] for row in range_observations(records))


def test_prepared_values_survive_release_and_a_second_preparation(monkeypatch):
    bindings = wire._bindings(wire.preparation_library.path())
    release = bindings.release
    snapshots = []

    def overwrite_then_release(pointer):
        output = ctypes.cast(pointer, ctypes.POINTER(wire._Prepared)).contents
        buffers = (*output.widths, *output.edges, output.epsilon, output.epsilon_a, output.solid_conductivity)
        values = []
        for buffer in buffers:
            array = np.ctypeslib.as_array(buffer.data, shape=(buffer.size,))
            values.append(array.tobytes())
            array.fill(np.nan)
        snapshots.append((values, output.geometry.area_density_per_m, tuple(output.fractions), output.controls.alpha))
        output.geometry.area_density_per_m = output.controls.alpha = np.nan
        output.fractions[:] = (np.nan, np.nan)
        release(pointer)
        assert output.owner is None

    monkeypatch.setattr(bindings, 'release', overwrite_then_release)
    first = production.prepare_values(**_args())
    second = production.prepare_values(**_args(topo='Gyroid', height=.042), k_s=21.)
    assert len(snapshots) == 2
    for (state, grid, fields, controls, fractions), (values, area, pressure, alpha) in zip((first, second), snapshots):
        arrays = [*(grid['d' + axis] for axis in 'xyz'), *(grid[axis + '_edges'] for axis in 'xyz'),
                  fields['eps'], fields['eps_A'], fields['K_ss']]
        assert [array.tobytes() for array in arrays] == values
        assert state.geometry['A_0'] == area
        assert fractions == pressure
        assert controls['alpha'] == alpha
    assert not np.array_equal(first[2]['K_ss'], second[2]['K_ss'])
    assert all(not np.shares_memory(first[2][key], second[2][key]) for key in first[2])


def test_axis_copy_stop_iteration_preserves_exception_and_releases_owner(monkeypatch):
    bindings = wire._bindings(wire.preparation_library.path())
    release, copy_array = bindings.release, wire.copy_array
    released = []
    failure = StopIteration('axis copy interrupted')

    def interrupt_axis(value, shape=None):
        if shape is None:
            raise failure
        return copy_array(value, shape)

    def record_release(pointer):
        released.append(bool(ctypes.cast(pointer, ctypes.POINTER(wire._Prepared)).contents.owner))
        release(pointer)

    monkeypatch.setattr(wire, 'copy_array', interrupt_axis)
    monkeypatch.setattr(bindings, 'release', record_release)
    with pytest.raises(StopIteration) as caught:
        prepare_quick_design(**_args(), case_id='axis-copy')
    assert caught.value is failure
    assert caught.value.__cause__ is None
    assert released == [True]


@pytest.mark.parametrize('cache', ['geometry', 'sco2'])
def test_cache_callback_failure_preserves_the_exception_and_release_count(monkeypatch, cache):
    from sjtu_tpmshx.physical_models import tpms_geometry

    arguments = _args(case=_case(hot_fluid='sco2'))
    bindings = wire._bindings(wire.preparation_library.path())
    release = bindings.release
    releases = []

    def counted(pointer):
        release(pointer)
        releases.append(True)

    failure = LookupError(cache)
    def fail_lookup(*args):
        raise failure

    monkeypatch.setattr(bindings, 'release', counted)
    pressure = production.pressure_fractions(**arguments)
    assert len(pressure) == 2 and not releases
    owner = tpms_geometry._compute_geometry_cached if cache == 'geometry' else sco2_props._prop
    monkeypatch.setattr(owner, 'lookup', fail_lookup)
    with pytest.raises(LookupError) as full_error:
        prepare_quick_design(**arguments, case_id='callback')
    assert full_error.value is failure and len(releases) == 1
    with pytest.raises(LookupError) as pressure_error:
        production.pressure_fractions(**arguments)
    assert pressure_error.value is failure and len(releases) == 1


@pytest.mark.parametrize('pressure', [False, True], ids=['full', 'sizing'])
@pytest.mark.parametrize('source', ['geometry lookup', 'cache key', 'overflow warning'])
def test_stop_iteration_from_preparation_preserves_cause_and_release(monkeypatch, pressure, source):
    from sjtu_tpmshx.applications.design.sizing import dP_fracs
    from sjtu_tpmshx.physical_models import tpms_geometry

    bindings = wire._bindings(wire.preparation_library.path())
    release = bindings.release
    released = []

    def record_release(pointer):
        released.append(bool(ctypes.cast(pointer, ctypes.POINTER(wire._Prepared)).contents.owner))
        release(pointer)

    failure = StopIteration(source)
    def stop_lookup(key):
        raise failure

    class InterruptedLength(float):
        def __hash__(self):
            raise failure

    def stop_warning(message, category, *args, **kwargs):
        assert category is RuntimeWarning and str(message) == 'overflow encountered in power'
        raise failure

    monkeypatch.setattr(bindings, 'release', record_release)
    arguments = _args()
    with warnings.catch_warnings(), np.errstate(over='warn'):
        if source == 'geometry lookup':
            monkeypatch.setattr(tpms_geometry._compute_geometry_cached, 'lookup', stop_lookup)
        elif source == 'cache key':
            arguments['l'] = InterruptedLength(arguments['l'])
        else:
            arguments['case'] = _case(mdot_h=1e180)
            warnings.simplefilter('always', RuntimeWarning)
            monkeypatch.setattr(warnings, 'showwarning', stop_warning)
        with pytest.raises(RuntimeError, match='^generator raised StopIteration$') as caught:
            if pressure:
                dP_fracs(**arguments)
            else:
                prepare_quick_design(**arguments, case_id='interrupted')
    assert type(caught.value) is RuntimeError and caught.value.__cause__ is failure
    assert released == ([] if pressure else [source == 'overflow warning'])


def _host_site(function, statement):
    lines, first = getsourcelines(function)
    offset, = (i for i, line in enumerate(lines) if statement in line)
    return Path(production.__file__).resolve(), first + offset


@pytest.mark.parametrize('kind', ['range', 'pressure-limit'])
@pytest.mark.parametrize('pressure_first', [False, True])
def test_direct_warning_sites_and_repeat_counts(monkeypatch, kind, pressure_first):
    from sjtu_tpmshx.applications.design.sizing import dP_fracs
    from sjtu_tpmshx.physical_models import tpms_props
    from sjtu_tpmshx.physical_models.df_surrogate import predict

    monkeypatch.setattr(tpms_props, '_range_warnings_emitted', set())
    monkeypatch.setattr(predict, '_CHOKE_WARNED', set())
    args = (_args(case=_case(T_in_h=1200.)) if kind == 'range' else
            _args(case=_case(mdot_h=20., P_in_h=1e5), Lx=20.))
    routes = (lambda: production.prepare_quick_design(**args, case_id='mixed'), lambda: dP_fracs(**args))
    if pressure_first:
        routes = routes[::-1]
    counts = []
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('default')
        for step, run in enumerate(routes * 3):
            if step >= 2:
                tpms_props._range_warnings_emitted.clear()
                predict.reset_choke_warn_registry()
            run()
            counts.append(len(notices))
        prepared = prepare_quick_design(**args, case_id='scoped')
        assert len(notices) == counts[-1]
    assert prepared.metadata['warnings']
    assert all(item.category is UserWarning for item in notices)
    sites = [(Path(item.filename).resolve(), item.lineno) for item in notices]
    if kind == 'range':
        assert counts == [3, 3, 3, 6, 6, 6]
        assert [str(item.message).split(':', 1)[0] for item in notices] == [
            'air_viscosity', 'air_conductivity', 'air_cp'] * 2
        lines = [_host_site(production.prepare_values, '_operation(state,'),
                 _host_site(production.pressure_fractions, '_operation(state,')]
        if pressure_first:
            lines.reverse()
        assert sites == [line for line in lines for _ in range(3)]
    else:
        assert counts == [1] * 6
        assert 'no positive outlet pressure solution' in str(notices[0].message)
        assert sites == [_host_site(production._observe, '_record_inlet(')]


_PRESSURE_LIMIT = ('[D-F approximation] 1D isothermal air pressure model has no positive outlet pressure solution '
                   '(P_out^2=-inf <= 0); returning P_in as a fallback dP (strict=False). This is not a physical '
                   'choking diagnosis. Check mass flux, channel length and inlet pressure.')


@pytest.mark.parametrize('mode', ['ignore', 'warn', 'raise', 'print'])
def test_floating_point_events_keep_modes_order_and_metadata(monkeypatch, capsys, mode):
    from sjtu_tpmshx.applications.design.sizing import dP_fracs
    from sjtu_tpmshx.physical_models.df_surrogate import predict

    args = _args(case=_case(mdot_h=1e180, mdot_c=1e-185))
    overflow, underflow = 'overflow encountered in power', 'underflow encountered in power'
    monkeypatch.setattr(predict, '_CHOKE_WARNED', set())
    for route, run in (('public', lambda: prepare_quick_design(**args, case_id='floating')),
                       ('pressure', lambda: dP_fracs(**args))):
        with np.errstate(all=mode), warnings.catch_warnings(record=True) as notices:
            warnings.simplefilter('always')
            if mode == 'raise':
                with pytest.raises(FloatingPointError, match='^overflow encountered in power$'):
                    run()
                assert not notices and not capsys.readouterr().err
                continue
            result = run()
        if route == 'public':
            assert result.metadata['warnings'] == (_PRESSURE_LIMIT,)
            assert [(r['source'], r['side'], r['stage']) for r in result.metadata['applicability_inputs']] == [
                (('property', name), side, 'design-dp-inlet')
                for side in 'AB' for name in ('air_viscosity', 'air_conductivity', 'air_cp')]
            assert tuple(result.parameters['inlet_pressure_fractions'].values()) == (1., 0.)
        else:
            assert result == (1., 0.)
        expected = [(UserWarning, _PRESSURE_LIMIT)] if route == 'pressure' else []
        if mode == 'warn':
            expected = [(RuntimeWarning, overflow), *expected, (RuntimeWarning, underflow)]
            function = production.prepare_values if route == 'public' else production.pressure_fractions
            assert [(Path(w.filename).resolve(), w.lineno) for w in notices if w.category is RuntimeWarning] == [
                _host_site(function, '_operation(state,')] * 2
        assert [(w.category, str(w.message)) for w in notices] == expected
        printed = [f'Warning: {overflow}', f'Warning: {underflow}'] if mode == 'print' else []
        assert capsys.readouterr().err.splitlines() == printed


@pytest.mark.parametrize('rearm, expected_counts', [
    (False, [1, 2, 2, 2]), (True, [1, 2, 3, 4]),
], ids=['stable-registry', 'rearmed-registry'])
def test_public_and_pressure_floating_warnings_keep_their_repeat_counts(monkeypatch, rearm, expected_counts):
    from sjtu_tpmshx.applications.design.sizing import dP_fracs
    from sjtu_tpmshx.physical_models.df_surrogate import predict
    from sjtu_tpmshx.preprocess import _metadata

    # A Git subprocess can reset Python's warning filters during provenance collection.
    monkeypatch.setattr(_metadata, 'source_context', lambda: {})
    monkeypatch.setattr(predict, '_CHOKE_WARNED', set())
    registry = {}
    monkeypatch.setattr(production, '__warningregistry__', registry, raising=False)
    args = _args(case=_case(mdot_h=1e180))
    routes = (lambda: prepare_quick_design(**args, case_id='mixed'), lambda: dP_fracs(**args))
    counts = []
    with np.errstate(over='warn'), warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('default')
        for step, run in enumerate(routes * 2):
            if rearm and step == 2:
                registry.clear()
            run()
            counts.append(sum(item.category is RuntimeWarning for item in notices))
    assert counts == expected_counts
    overflow = (RuntimeWarning, 'overflow encountered in power')
    expected = [overflow, overflow, (UserWarning, _PRESSURE_LIMIT)]
    if rearm:
        expected.extend([overflow, overflow])
    assert [(item.category, str(item.message)) for item in notices] == expected


def test_prepare_and_pressure_observe_ranges_without_result_or_solver(monkeypatch, tmp_path):
    for name in ('RESULT', 'GEOMETRY', 'NATIVE_SOLVER', 'SOLVER'):
        monkeypatch.setenv(f'TPMSHX_{name}_LIBRARY', str(tmp_path / 'absent'))
    code = '''
from pathlib import Path
import sys
images = []
def capture(event, args):
    if event == 'ctypes.dlopen' and args[0] and 'tpmshx_' in Path(args[0]).name.lower():
        images.append(Path(args[0]).resolve())
sys.addaudithook(capture)
from sjtu_tpmshx.applications.design.sizing import dP_fracs
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.run_control.run_warnings import range_observations, warning_scope
from tests.python.test_native_quick_prepare import _args, _case
for fluid in (_case(T_in_h=1200.), _case(hot_fluid='sco2', T_in_c=1200.)):
    args = _args(case=fluid)
    case = prepare_quick_design(**args, case_id='one-image')
    with warning_scope({}) as records:
        pressure = dP_fracs(**args)
    if pressure != tuple(case.parameters['inlet_pressure_fractions'][side] for side in 'AB'):
        raise SystemExit('pressure fractions differ')
    rows = case.metadata['applicability_inputs']
    if list(rows) != list(range_observations(records)) or not any(row['high'] for row in rows):
        raise SystemExit('range observations differ')
if set(images) != {Path(sys.argv[1]).resolve()}:
    raise SystemExit(str(images))
'''
    subprocess.run([sys.executable, '-c', code, wire.preparation_library.path()], check=True, timeout=60)
