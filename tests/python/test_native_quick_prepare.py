"""Check float64 Quick preparation and pressure-fraction contracts against pure formulas."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.applications.design.cases import DesignCase
from sjtu_tpmshx.cpp_interface import _native_quick_prepare as production
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


def test_prepare_and_pressure_observe_ranges_without_result_or_solver(monkeypatch, tmp_path):
    for name in ('TPMSHX_RESULT_LIBRARY', 'TPMSHX_GEOMETRY_LIBRARY',
                 'TPMSHX_NATIVE_SOLVER_LIBRARY', 'TPMSHX_SOLVER_LIBRARY'):
        monkeypatch.setenv(name, str(tmp_path / name))
    arguments = _args(case=_case(T_in_h=1200.))
    prepared = prepare_quick_design(**arguments, case_id='preparation-only')
    with warning_scope({}) as pressure_records:
        pressure = production.pressure_fractions(**arguments)
    assert pressure == tuple(prepared.parameters['inlet_pressure_fractions'][side] for side in 'AB')
    assert any(row['high'] for row in prepared.metadata['applicability_inputs'])
    assert list(prepared.metadata['applicability_inputs']) == list(range_observations(pressure_records))


def test_geometry_cache_hit_and_clear():
    arguments = _args(case_id='cache-clear')
    production.prepare_quick_design(**arguments)
    assert tuple(compute_geometry.cache_info()) == (0, 1, 32768, 1)
    production.prepare_quick_design(**arguments)
    assert tuple(compute_geometry.cache_info()) == (1, 1, 32768, 1)
    compute_geometry.cache_clear()
    production.prepare_quick_design(**arguments)
    assert tuple(compute_geometry.cache_info()) == (0, 1, 32768, 1)


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('fluid', ['sco2', 'co2'])
def test_eos_scalar_caches_share_external_warming_and_clear(pressure, fluid):
    owner = sco2_props._prop if fluid == 'sco2' else co2_props._scalar
    arguments = _args(case=_case(hot_fluid=fluid))
    if pressure:
        production.pressure_fractions(**arguments)
        first = tuple(owner.cache_info())
        production.pressure_fractions(**arguments)
        second = tuple(owner.cache_info())
    else:
        production.prepare_quick_design(**arguments, case_id='eos-cache')
        first = tuple(owner.cache_info())
        production.prepare_quick_design(**arguments, case_id='eos-cache')
        second = tuple(owner.cache_info())
    assert first[3] > 0 and second[0] > first[0]


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
