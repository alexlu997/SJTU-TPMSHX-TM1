"""Compare raw Quick preparation with the frozen sequence and type contract."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.applications.design.cases import DesignCase
from sjtu_tpmshx.development.tests import quick_prepare_reference as reference
from sjtu_tpmshx.development.tests.native.test_result_metrics import assert_value
from sjtu_tpmshx.preprocess.app_modes import quick_design as production
from sjtu_tpmshx.shared.domain.run_warnings import warning_scope
from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
from sjtu_tpmshx.shared.models import co2_props, sco2_props


def _case(**changes):
    return replace(DesignCase(1, 'air', 480., 9e6, .03,
                              'air', 320., 9e6, .02, 100., .05, .05), **changes)


def _args(**changes):
    arguments = dict(case=_case(), topo='Diamond', l=7., t=.5, s=.084,
                     Lx=.025, arrangement='cross')
    arguments.update(changes)
    return arguments


def _plain(value):
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _failure(error):
    return (type(error), error.args,
            None if error.__cause__ is None else _failure(error.__cause__))


def _observe(function, arguments, *, policy='warn', trace=None):
    records = {}
    with warnings.catch_warnings(record=True) as notices, np.errstate(all=policy), warning_scope(records):
        warnings.simplefilter('always')
        try:
            result = ('value', _plain(function(**arguments)))
        except Exception as error:
            result = ('error', _failure(error))
    return dict(result=result, notices=[(item.category, str(item.message)) for item in notices],
                records=_plain(records), cache=tuple(compute_geometry.cache_info()),
                trace=[] if trace is None else list(trace))


def _functions(pressure):
    if pressure:
        from sjtu_tpmshx.shared.models._native_quick_prepare import pressure_fractions
        return reference.dP_fracs, pressure_fractions
    return reference.prepare_quick_design, production.prepare_quick_design


def _compare(factory, *, pressure=False, policy='warn', setup=None, trace=None):
    observations = []
    for function in _functions(pressure):
        compute_geometry.cache_clear()
        arguments = factory()
        if not pressure:
            arguments.setdefault('case_id', 'raw-quick-reference')
        if setup is not None:
            setup(arguments)
        if trace is not None:
            trace.clear()
        observations.append(_observe(function, arguments, policy=policy, trace=trace))
    assert_value(observations[1], observations[0])
    return observations[1]


def _value(observation):
    assert observation['result'][0] == 'value', observation
    return observation['result'][1]


@pytest.fixture(autouse=True)
def isolated_quick_inputs(monkeypatch):
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    monkeypatch.delenv('TPMSHX_DF_METHOD', raising=False)
    compute_geometry.cache_clear()
    yield
    compute_geometry.cache_clear()


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
@pytest.mark.parametrize('prop_model', ['const', 'mean'])
@pytest.mark.parametrize('height', [None, .042])
def test_complete_preparation_keeps_fixed_grid_controls_and_units(topology, arrangement, prop_model, height):
    actual = _value(_compare(lambda: _args(topo=topology, arrangement=arrangement,
                                          prop_model=prop_model, height=height)))
    shape = (60, 40, 1) if arrangement == 'cross' else (60, 1, 2)
    assert actual['design_fields']['eps'].shape == shape
    assert actual['parameters']['L_cell_m'] == .007
    assert actual['parameters']['t_wall_m'] == .0005
    assert actual['parameters']['height'] == (.084 if height is None else height)
    assert actual['parameters']['controls']['qtol'] == (1e-4 if arrangement == 'cross' else None)
    assert actual['parameters']['controls']['chunk'] == (100 if arrangement == 'cross' else None)


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('hot,cold', [('air', 'water'), ('water', 'air'),
    ('water', 'sco2'), ('sco2', 'water'), ('sco2', 'sco2'), ('co2', 'air')])
def test_preparation_keeps_fluid_property_routes(pressure, hot, cold):
    state = {'air': (480., 9e6), 'water': (350., 2e5), 'sco2': (480., 9e6), 'co2': (480., 9e6)}
    _value(_compare(lambda: _args(case=_case(hot_fluid=hot, cold_fluid=cold,
        T_in_h=state[hot][0], P_in_h=state[hot][1], T_in_c=state[cold][0], P_in_c=state[cold][1])),
        pressure=pressure))


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64])
def test_scalar_precision_and_stored_types(pressure, dtype):
    def inputs():
        arguments = _args(l=dtype(7.), t=dtype(.5), s=dtype(.084), Lx=dtype(.025), height=dtype(.042),
            case=_case(T_in_h=dtype(480.), T_in_c=dtype(320.), mdot_h=dtype(.03), mdot_c=dtype(.02)))
        if not pressure:
            arguments.update(k_s=dtype(16.3), tol=dtype(1e-5))
        return arguments
    _value(_compare(inputs, pressure=pressure))


@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
@pytest.mark.parametrize('dtype', [np.bool_, np.int16, np.float16, np.float32, '>f8'])
@pytest.mark.parametrize('layout', ['tuple', 'list', 'stack', 'reverse'])
def test_warm_inputs_keep_original_container_shape_and_field_dtype(arrangement, dtype, layout):
    shape = (60, 40, 1) if arrangement == 'cross' else (60, 1, 2)
    def inputs():
        warm = tuple(np.full(shape, temperature, dtype=dtype) for temperature in (340., 320., 330.))
        if layout == 'list':
            warm = list(warm)
        elif layout == 'stack':
            warm = np.stack(warm)
        elif layout == 'reverse':
            warm = tuple(value[::-1, ::-1, ::-1] for value in warm)
        return _args(arrangement=arrangement, init=warm)
    _value(_compare(inputs))


@pytest.mark.parametrize('warm', [(), (None, None), (None, None, None),
    (np.nan, None, None), (np.inf, np.nan, None), (np.zeros(2),) * 3,
    (np.asarray('bad'), None, None)])
def test_external_warm_and_arrangement_errors_keep_precedence(warm):
    observation = _compare(lambda: _args(init=warm, arrangement='unknown', l=-1.))
    assert observation['result'][0] == 'error'
    assert observation['cache'][-1] == 0


@pytest.mark.parametrize('warm', [(None, None, None), (np.zeros(2),) * 3,
                                 (np.zeros((60, 40)),) * 3])
def test_warm_shape_failure_follows_positive_input_checks(warm):
    actual = _compare(lambda: _args(init=warm))
    assert actual['result'][1][1] == ('quick-design warm start must match the prepared grid',)
    earlier = _compare(lambda: _args(init=warm, l=-1.))
    assert earlier['result'][1][1] == ('quick-design l must be finite and positive',)


def test_warm_generator_is_consumed_before_its_late_length_error():
    _compare(lambda: _args(init=(np.zeros((60, 40, 1)) for _ in range(3))))


@pytest.mark.parametrize('role,value', [('arrangement', []), ('arrangement', 'cross\0extra'),
    ('prop_model', 'const\0extra'), ('prop_model', '\ud800'), ('topo', 'Diamond\0extra'),
    ('topo', None), ('topo', ['Diamond'])])
def test_original_labels_keep_their_comparison_and_error_contract(role, value):
    _compare(lambda: _args(**{role: value}))


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('label', ['air', 'AIR', ' air ', 'sco2', 'SCO2', 'co2',
                                  'air\0extra', '\ud800', b'air', np.str_('air')])
def test_raw_fluid_labels_keep_property_normalization_separate_from_pressure(pressure, label):
    _compare(lambda: _args(case=_case(hot_fluid=label)), pressure=pressure)


def test_exact_air_and_normalized_air_keep_distinct_pressure_values():
    lower = _value(_compare(lambda: _args(case=_case(hot_fluid='air')), pressure=True))
    upper = _value(_compare(lambda: _args(case=_case(hot_fluid='AIR')), pressure=True))
    assert lower[0] != upper[0]


@pytest.mark.parametrize('arrangement', ['counter', 'unknown', None, [], 'cross\0extra'])
def test_pressure_only_keeps_non_cross_counter_sections(arrangement):
    _value(_compare(lambda: _args(arrangement=arrangement), pressure=True))


@pytest.mark.parametrize('field,value', [('s', 0.), ('s', -.084), ('Lx', 0.), ('Lx', -.025)])
def test_pressure_only_does_not_inherit_complete_preparation_positive_guards(field, value):
    _compare(lambda: _args(**{field: value}), pressure=True)


@pytest.mark.parametrize('field', ['l', 't', 's', 'Lx', 'height', 'k_s', 'tol',
                                  'mdot_h', 'mdot_c', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c'])
@pytest.mark.parametrize('value', [0., np.nan])
def test_ordered_positive_input_failures(field, value):
    def inputs():
        return _args(case=_case(**{field: value})) if hasattr(_case(), field) else _args(**{field: value})
    actual = _compare(inputs)
    assert actual['result'][0] == 'error'
    assert actual['result'][1][1] == (f'quick-design {field} must be finite and positive',)


def test_all_numeric_case_attributes_are_read_before_first_positive_check():
    def inputs():
        case = SimpleNamespace(**vars(_case()))
        del case.P_in_c
        return _args(case=case, l=-1.)
    actual = _compare(inputs)
    assert actual['result'][1][0] is AttributeError
    assert 'P_in_c' in actual['result'][1][1][0]


def test_non_dataclass_case_fails_only_after_both_pressure_sides():
    actual = _compare(lambda: _args(case=SimpleNamespace(**vars(_case()))))
    assert actual['result'][1][0] is TypeError
    assert 'asdict()' in actual['result'][1][1][0]
    assert {key[-1][0] for key in actual['records']} == {'A', 'B'}


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('field', ['l', 'height', 'mdot_h'])
@pytest.mark.parametrize('value', [2**53 + 1, 2**1100, np.array(.03), np.array([.03]), np.ones(2)])
def test_integer_and_array_inputs_keep_original_conversion_points(pressure, field, value):
    def inputs():
        return _args(case=_case(mdot_h=value)) if field == 'mdot_h' else _args(**{field: value})
    _compare(inputs, pressure=pressure)


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_property_floating_events_precede_the_later_unknown_fluid(pressure, policy):
    _compare(lambda: _args(case=_case(T_in_h=np.float16(65504.), cold_fluid='unknown')),
             pressure=pressure, policy=policy)


@pytest.mark.parametrize('side', ['hot', 'cold'])
@pytest.mark.parametrize('pressure', [False, True])
def test_water_state_failure_retains_both_side_order_and_records(side, pressure):
    suffix = 'h' if side == 'hot' else 'c'
    _compare(lambda: _args(case=_case(**{side + '_fluid': 'water', 'T_in_' + suffix: 350.,
        'P_in_' + suffix: 10000.})), pressure=pressure)


@pytest.mark.parametrize('options', [None, {}, {'strict': True}, {'unexpected': 1},
                                  {'method': 'unknown'}, [('method', 'unknown')]])
@pytest.mark.parametrize('fluid', ['air', 'AIR', 'water'])
def test_pressure_options_keep_branch_specific_binding(options, fluid):
    _compare(lambda: _args(case=_case(hot_fluid=fluid, T_in_h=350.), df_options=options), pressure=True)


def test_pressure_options_binding_follows_flow_conversion():
    actual = _compare(lambda: _args(case=_case(mdot_h=2**1100), df_options={'unexpected': 1}), pressure=True)
    assert actual['result'][1][0] is OverflowError


@pytest.mark.parametrize('pressure', [False, True])
def test_invalid_df_environment_retains_its_original_stage(monkeypatch, pressure):
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'unknown')
    _compare(lambda: _args(case=_case(cold_fluid='unknown')), pressure=pressure)


def test_pressure_explicit_method_precedes_environment_selection(monkeypatch):
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'unknown')
    _value(_compare(lambda: _args(df_options={'method': 'cfd_full_core_3cell_fixed_v2'}), pressure=True))


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('first,second', [(np.float16, float), (float, np.float16)])
def test_external_geometry_warming_keeps_equal_key_types(pressure, first, second):
    def warm(arguments):
        compute_geometry(arguments['topo'], first(7.), first(.5), N=128)
    actual = _compare(lambda: _args(l=second(7.), t=second(.5)), pressure=pressure, setup=warm)
    assert actual['cache'] == (1, 1, 32768, 1)


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('cached', [False, True])
def test_invalid_chi_keeps_geometry_publication_before_material_failure(monkeypatch, pressure, cached):
    monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    def warm(arguments):
        compute_geometry(arguments['topo'], arguments['l'], arguments['t'], N=128)
    actual = _compare(_args, pressure=pressure, setup=warm if cached else None)
    assert actual['result'][0] == 'error'
    assert actual['cache'] == (int(cached), 1, 32768, 1)


def test_valid_chi_does_not_change_final_quick_solid_fields(monkeypatch):
    original = _value(_compare(_args))
    monkeypatch.setenv('TPMSHX_CHI_S', '.7')
    changed = _value(_compare(_args))
    assert_value(changed['design_fields'], original['design_fields'])
    assert changed['parameters']['_environment']['TPMSHX_CHI_S'] == '.7'


def test_property_range_records_keep_source_side_and_stage():
    actual = _compare(lambda: _args(case=_case(T_in_h=1200.)))
    _value(actual)
    assert {key[-1][0] for key in actual['records']} == {'A', 'B'}
    assert all(key[-1][1:] == ('design-dp-inlet', 'scalar') for key in actual['records'])
    assert any(row['high'] for row in actual['records'].values())


def test_geometry_cache_clear_reaches_the_preparation_owner():
    outcomes = []
    for function in _functions(False):
        compute_geometry.cache_clear()
        arguments = _args(case_id='cache-clear')
        first = _observe(function, arguments)
        second = _observe(function, arguments)
        compute_geometry.cache_clear()
        third = _observe(function, arguments)
        outcomes.append((first, second, third))
    assert_value(outcomes[1], outcomes[0])
    assert [value['cache'] for value in outcomes[1]] == [(0, 1, 32768, 1), (1, 1, 32768, 1), (0, 1, 32768, 1)]


def test_repeated_case_attribute_reads_keep_snapshots_and_pressure_inputs_distinct():
    trace = []
    class ChangingCase(DesignCase):
        def __getattribute__(self, name):
            value = super().__getattribute__(name)
            if name == 'T_in_h':
                reads = self.__dict__.get('_reads', 0) + 1
                self.__dict__['_reads'] = reads
                trace.append((name, reads))
                return value + reads * .25
            return value
    def inputs():
        return _args(case=ChangingCase(**vars(_case())))
    actual = _value(_compare(inputs, trace=trace))
    assert actual['config_snapshot']['T_in_h'] != actual['parameters']['operating_point']['T_in_h']


def test_arrangement_subclass_keeps_both_dictionary_lookups():
    trace = []
    class Arrangement(str):
        def __hash__(self):
            trace.append('hash')
            return str.__hash__(self)
        def __eq__(self, other):
            trace.append(('eq', other))
            return str.__eq__(self, other)
    actual = _compare(lambda: _args(arrangement=Arrangement('cross')), trace=trace)
    _value(actual)
    assert actual['trace'].count('hash') == 2


@pytest.mark.parametrize('base,value', [(str, 'unknown'), (int, 7), (float, 7.), (bytes, b'unknown')])
def test_property_mode_keeps_portable_primitive_subclass_equality(base, value):
    trace = []
    class Mode(base):
        def __eq__(self, other):
            trace.append(('eq', other))
            return True
    actual = _compare(lambda: _args(prop_model=Mode(value)), trace=trace)
    _value(actual)
    assert actual['trace'] == [('eq', 'const')]


@pytest.mark.parametrize('pressure', [False, True])
def test_fluid_equality_keeps_independent_int_and_truth_operations(pressure):
    trace = []
    class Truth:
        def __bool__(self):
            trace.append('bool')
            return True
        def __int__(self):
            trace.append('int')
            return 1
    class Air(str):
        __hash__ = str.__hash__
        def __eq__(self, other):
            trace.append(('eq', other))
            return Truth()
    observation = _compare(lambda: _args(case=_case(hot_fluid=Air('air'))), pressure=pressure, trace=trace)
    _value(observation)
    assert observation['trace'] == [('eq', 'air'), 'bool', ('eq', 'air'), 'int', 'bool', ('eq', 'air'), 'bool']


def test_late_scalar_division_protocol_is_not_replaced_by_early_float_conversion():
    trace = []
    class Length(float):
        def __truediv__(self, other):
            trace.append(('divide', other))
            return .1234
    actual = _value(_compare(lambda: _args(l=Length(7.)), trace=trace))
    assert actual['parameters']['L_cell_m'] == .1234
    assert trace == [('divide', 1000.)]


def test_original_host_exception_identity_survives_late_unit_conversion():
    failure = RuntimeError('original late unit conversion')
    class Length(float):
        def __truediv__(self, other):
            raise failure
    for function in _functions(False):
        compute_geometry.cache_clear()
        with warning_scope({}), pytest.raises(RuntimeError) as caught:
            function(**_args(l=Length(7.), case_id='late-error'))
        assert caught.value is failure


def test_pressure_options_are_copied_separately_for_each_side():
    trace = []
    class Options(Mapping):
        def __len__(self):
            trace.append('len')
            return 1
        def __iter__(self):
            trace.append('iter')
            return iter(('method',))
        def __getitem__(self, key):
            trace.append(('item', key))
            return 'cfd_full_core_3cell_fixed_v2'
    _value(_compare(lambda: _args(df_options=Options()), pressure=True, trace=trace))
    assert trace.count(('item', 'method')) == 2


@pytest.mark.parametrize('side', ['hot', 'cold'])
@pytest.mark.parametrize('label', ['sco2', ' SCO2 '])
@pytest.mark.parametrize('temperature', [480., 'invalid-temperature'])
def test_sco2_missing_pressure_precedes_temperature_conversion(side, label, temperature):
    suffix = 'h' if side == 'hot' else 'c'
    actual = _compare(lambda: _args(case=_case(**{side + '_fluid': label,
        'T_in_' + suffix: temperature, 'P_in_' + suffix: None})), pressure=True)
    assert actual['result'][1] == (ValueError, (
        'sCO2 properties require pressure P [Pa]; caller passed P=None. '
        'Fix the call site to forward the inlet/local pressure.',), None)


@pytest.mark.parametrize('side', ['hot', 'cold'])
@pytest.mark.parametrize('temperatures,pressures', [([np.nan, 480.], [9e6] * 3),
    ([480.] * 2, [9e6] * 3), ([200., 480.], [9e6] * 3),
    ([480.] * 2, [np.nan, 9e6, 9e6])])
def test_sco2_shape_failures_keep_original_state_precedence(side, temperatures, pressures):
    suffix = 'h' if side == 'hot' else 'c'
    actual = _compare(lambda: _args(case=_case(**{side + '_fluid': 'sco2',
        'T_in_' + suffix: np.asarray(temperatures),
        'P_in_' + suffix: np.asarray(pressures)})), pressure=True)
    assert actual['result'][0] == 'error'


@pytest.mark.parametrize('pressure', [False, True])
@pytest.mark.parametrize('fluid', ['sco2', 'co2'])
@pytest.mark.parametrize('warm', [False, True])
def test_eos_scalar_caches_share_external_warming_and_clear(pressure, fluid, warm):
    owner = sco2_props._prop if fluid == 'sco2' else co2_props._scalar
    external = sco2_props.sco2_prop if fluid == 'sco2' else co2_props.co2_prop
    outcomes = []
    for function in _functions(pressure):
        owner.cache_clear()
        compute_geometry.cache_clear()
        if warm:
            external('D', 480., 9e6)
        arguments = _args(case=_case(hot_fluid=fluid))
        if not pressure:
            arguments['case_id'] = 'eos-cache'
        rows = []
        for clear in (False, False, True):
            if clear:
                owner.cache_clear()
            observed = _observe(function, arguments)
            _value(observed)
            rows.append((observed, tuple(owner.cache_info())))
        outcomes.append(rows)
    assert_value(outcomes[1], outcomes[0])
    assert outcomes[1][-1][1] == ((0, 4, 4096, 4) if fluid == 'sco2' else (3, 1, 4096, 1))
    owner.cache_clear()


@pytest.mark.parametrize('fluid,temperature,pressure_value,expected', [
    ('sco2', 200., 9e6, (0, 1, 4096, 0)),
    ('co2', 480., -1., (0, 0, 4096, 0)),
    ('sco2', np.asarray([480.]), np.asarray([9e6]), (0, 0, 4096, 0)),
    ('co2', np.asarray([480.]), np.asarray([9e6]), (0, 0, 4096, 0)),
])
def test_eos_cache_failures_and_array_queries_do_not_publish(fluid, temperature, pressure_value, expected):
    owner = sco2_props._prop if fluid == 'sco2' else co2_props._scalar
    outcomes = []
    for function in _functions(True):
        owner.cache_clear()
        compute_geometry.cache_clear()
        observed = _observe(function, _args(case=_case(hot_fluid=fluid,
            T_in_h=temperature, P_in_h=pressure_value)))
        outcomes.append((observed, tuple(owner.cache_info())))
    assert_value(outcomes[1], outcomes[0])
    assert outcomes[1][1] == expected
    owner.cache_clear()


def test_co2_failed_scalar_eos_query_counts_a_miss_without_publication():
    import CoolProp.CoolProp as CP
    temperature, pressure = CP.PropsSI('Tcrit', 'CO2'), CP.PropsSI('Pcrit', 'CO2')
    outcomes = []
    for function in _functions(True):
        co2_props._scalar.cache_clear()
        compute_geometry.cache_clear()
        observed = _observe(function, _args(case=_case(hot_fluid='co2',
            T_in_h=temperature, P_in_h=pressure)))
        outcomes.append((observed, tuple(co2_props._scalar.cache_info())))
    assert_value(outcomes[1], outcomes[0])
    assert outcomes[1][0]['result'][1][0] is ValueError
    assert outcomes[1][1] == (0, 1, 4096, 0)
    co2_props._scalar.cache_clear()
