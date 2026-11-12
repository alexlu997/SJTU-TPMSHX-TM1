"""Check complete public scalar queries against the frozen pre-N13 sequence."""
import ctypes as ct
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass, replace
import os
import re
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import property_reference as reference
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as abi
from sjtu_tpmshx.shared.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.shared.domain.run_warnings import range_context, warning_scope
from sjtu_tpmshx.shared.models import (
    _native_properties, co2_props, fluid_props, nu_correlations, sco2_props,
    tpms_calc, tpms_props,
)
from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry


def _same(actual, expected):
    if is_dataclass(expected):
        assert type(actual) is type(expected)
        _same(asdict(actual), asdict(expected))
    elif isinstance(expected, dict):
        assert list(actual) == list(expected)
        for name in expected:
            _same(actual[name], expected[name])
    elif isinstance(expected, (list, tuple)):
        assert type(actual) is type(expected) and len(actual) == len(expected)
        for first, second in zip(actual, expected):
            _same(first, second)
    elif isinstance(expected, np.generic):
        assert type(actual) is type(expected)
        assert actual.dtype == expected.dtype and actual.tobytes() == expected.tobytes()
    elif isinstance(expected, np.ndarray):
        assert type(actual) is type(expected) and actual.dtype == expected.dtype
        assert actual.shape == expected.shape and actual.tobytes() == expected.tobytes()
    elif isinstance(expected, float):
        assert type(actual) is type(expected) and actual.hex() == expected.hex()
    elif isinstance(expected, complex):
        assert type(actual) is type(expected)
        assert (actual.real.hex(), actual.imag.hex()) == (expected.real.hex(), expected.imag.hex())
    else:
        assert type(actual) is type(expected) and actual == expected


def _clear(module):
    module.compute.cache_clear()
    compute_geometry.cache_clear()
    reference._range_warnings_emitted.clear()
    reference._query_nu_warned.clear()
    tpms_props._range_warnings_emitted.clear()
    for name in ('_EXTRAP_WARNED', '_WATER_NU_WARNED', '_SCO2_NU_WARNED'):
        getattr(nu_correlations, name).clear()


@pytest.fixture(autouse=True)
def isolated_cache_and_warning_state():
    _clear(reference)
    _clear(tpms_calc)
    yield
    _clear(reference)
    _clear(tpms_calc)


def _observe(module, args, *, scoped=True, raw=False, fp_policy='warn', **kwargs):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all=fp_policy):
        warnings.simplefilter('always')
        with warning_scope({}) if scoped else nullcontext(None) as records:
            try:
                result = getattr(module, '_compute_cached' if raw else 'compute')(*args, **kwargs)
            except Exception as error:
                observed = ('error', type(error), error.args)
            else:
                if raw:
                    result = (result[0], result[1], result.cp, result.pr)
                observed = ('value', result)
    return observed, records, [(item.category, str(item.message)) for item in caught]


def _compare(args, **kwargs):
    _clear(reference)
    expected = _observe(reference, args, **kwargs)
    _clear(tpms_calc)
    actual = _observe(tpms_calc, args, **kwargs)
    _same(actual, expected)
    return actual


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2', 'co2'])
@pytest.mark.parametrize('kind', [float, np.float32, np.float64])
@pytest.mark.parametrize('scoped', [False, True])
def test_complete_property_query_matches_frozen_sequence(topology, fluid, kind, scoped):
    temperature, pressure = {'air': (380., 160000.), 'water': (320., 200000.),
                             'sco2': (480., 9000000.), 'co2': (300., 4500000.)}[fluid]
    args = (topology, kind(7.), kind(.5), kind(6.), kind(temperature), kind(pressure), kind(16.), fluid)
    actual = _compare(args, scoped=scoped)
    assert actual[0][0] == 'value'


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2', 'co2'])
def test_cached_internal_cp_pr_and_source_records_match_frozen_sequence(fluid):
    temperature, pressure = (320., 200000.) if fluid == 'water' else (480., 9000000.)
    actual = _compare(('Diamond', 7., .5, np.float32(6.), temperature, pressure, fluid), raw=True)
    assert actual[0][0] == 'value'


@pytest.mark.parametrize('kind', [float, np.float32])
def test_cache_hits_keep_current_material_and_unpoisoned_copies(monkeypatch, kind):
    def sequence(module):
        _clear(module)
        args = ('Gyroid', 7., .5, kind(6.), 380., 160000., kind(16.))
        with warning_scope({}):
            monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
            first = module.compute(*args)
            first['rho'] = -1.
            monkeypatch.setenv('TPMSHX_CHI_S', '.5')
            second = module.compute(*args)
            monkeypatch.setenv('TPMSHX_CHI_S', '.7')
            third = module.compute(*args)
        return second, third, tuple(module.compute.cache_info()), module.compute.cache_parameters()
    _same(sequence(tpms_calc), sequence(reference))


@pytest.mark.parametrize('first_strong', [False, True])
def test_equal_scalar_keys_keep_first_typed_value(first_strong):
    def sequence(module):
        _clear(module)
        kinds = (np.float32, float) if first_strong else (float, np.float32)
        with warning_scope({}):
            values = [module.compute('Diamond', 7., .5, kind(6.), 380., 160000., 16.) for kind in kinds]
        return values, tuple(module.compute.cache_info())
    _same(sequence(tpms_calc), sequence(reference))


def test_cache_warning_replay_binds_new_run_context():
    args = ('Diamond', 7., .5, .001, 1200., 160000., 16.)
    def sequence(module):
        _clear(module)
        standalone = _observe(module, args, scoped=False)
        scoped = []
        for side in 'AB':
            with range_context(side=side, stage='inlet', layout='scalar'):
                scoped.append(_observe(module, args))
        return standalone, scoped, tuple(module.compute.cache_info())
    _same(sequence(tpms_calc), sequence(reference))


@pytest.mark.parametrize('args', [
    ('Gyroid', 7., .5, .2, -300., 101325., 16., 'air'),
    ('Gyroid', 7., .5, .2, 0., 101325., 16., 'air'),
    ('Gyroid', 7., .5, .2, 400., 101325., 16., 'water'),
    ('Gyroid', 7., .5, .2, 270., 9000000., 16., 'sco2'),
    ('Gyroid', 7., .5, .2, 180., 4500000., 16., 'co2'),
    ('Gyroid', 3., .5, .2, 380., 101325., 16., 'air'),
    ('Gyroid', 7., .5, .2, 380., 101325., 16., 'other'),
])
def test_first_error_and_preceding_events_match_frozen_sequence(args):
    actual = _compare(args, scoped=False)
    assert actual[0][0] == 'error'
    assert tpms_calc.compute.cache_info().currsize == reference.compute.cache_info().currsize == 0


def test_negative_speed_retains_raw_complex_intermediates():
    actual = _compare(('Gyroid', 7., .5, -.2, 300., 101325., 'air'), raw=True, scoped=False)
    assert actual[0][0] == 'value'
    assert np.iscomplexobj(actual[0][1][0]['Nu'])
    assert np.iscomplexobj(actual[0][1][0]['H_sf'])


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_selected_sco2_model_and_co2_geometry_remain_independent(topology):
    settings = replace(Sco2NuConfig(), mode='experimental', alpha_D=1.13, alpha_G=2.27,
                       parameter_version='query-reference', source='regression', applicability='test only')
    actual = _compare((topology, 7., .5, 6., 480., 9000000., 16., 'sco2'),
                      sco2_nu=settings, co2_geometry=True)
    assert actual[0][0] == 'value'


@pytest.mark.parametrize('fluid', ['water', 'sco2'])
def test_nu_notice_uses_floored_re_but_records_raw_re(fluid):
    temperature, pressure = (320., 200000.) if fluid == 'water' else (480., 9000000.)
    args = ('Gyroid', 7., .5, 1.e-6, temperature, pressure, 16., fluid)
    standalone = _compare(args, scoped=False)
    assert any('Re=[1,1]' in message for _, message in standalone[2])
    scoped = _compare(args)
    records = [value for key, value in scoped[1].items() if key[:2] == ('nu', fluid)]
    assert records and records[0].maximum[0] < 1.


def test_frozen_query_does_not_call_production_combination(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('The expected scalar query called the production combination')
    monkeypatch.setattr(tpms_calc, 'compute', forbidden)
    monkeypatch.setattr(tpms_calc, '_compute_cached', forbidden)
    with warning_scope({}):
        result = reference.compute('Gyroid', 7., .5, 6., 380., 160000., 16.)
    assert result['rho'] > 0 and result['K_df'] > 0


@pytest.mark.parametrize('policy', ['warn', 'raise'])
def test_selected_model_keeps_floating_events_and_failure_cache(policy):
    settings = replace(Sco2NuConfig(), mode='experimental', alpha_D=1.e308, alpha_G=1.e308,
                       parameter_version='query-fp', source='regression', applicability='test only')
    _compare(('Diamond', 7., .5, 6., 480., 9000000., 16., 'sco2'),
             sco2_nu=settings, fp_policy=policy)
    assert tuple(tpms_calc.compute.cache_info()) == tuple(reference.compute.cache_info())


# These layouts test the raw entry independently of the production host adapter.
_GeometryKey = abi._struct('QueryGeometryKey', [('topology', abi._U),
    *abi.v1._doubles('cell_length_mm wall_thickness_mm'),
    ('cell_kind', abi._Kind), ('wall_kind', abi._Kind)])
_InletKey = abi._struct('QueryInletKey', [('geometry', _GeometryKey), ('fluid', abi._U),
    *abi.v1._doubles('velocity_m_s temperature_K pressure_Pa'), ('kinds', abi._InletKinds),
    ('have_sco2_nu', abi._U), ('sco2_nu', abi._Nu), ('co2_geometry', abi._U)])
_QueryInput = abi._struct('QueryInput', [('abi_version', abi._U), ('struct_size', abi._S),
    ('inlet', _InletKey), *abi.v1._doubles('hydraulic_diameter_m epsilon_a'),
    ('diameter_kind', abi._Kind), ('epsilon_kind', abi._Kind), ('exact_co2_drag', abi._U)])
_PropertyScalar = abi._struct('QueryScalar', [*abi.v1._doubles('real imaginary'),
    ('kind', abi._Kind), ('category', abi._U)])
_QueryResult = abi._struct('QueryResult', [('abi_version', abi._U), ('struct_size', abi._S),
    ('values', _PropertyScalar * 12)])
_HostFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, abi._U, abi._U)
_HostCallbacks = abi._struct('QueryHostCallbacks', [('values', abi.v1._Callbacks),
    ('validate_host_input', _HostFunction)])
_RangeFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, abi._U, ct.POINTER(abi.v1._Range),
    abi._U, abi._U, abi._D)
_QueryCallbacks = abi._struct('QueryCallbacks', [('values', _HostCallbacks),
    *[(name, ct.c_void_p) for name in ('geometry_cache', 'inlet_cache', 'observe_range', 'observe_notice')]])


@pytest.fixture(scope='module')
def raw_query():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', abi.v1._library_path()))
    function = library.tpmshx_query_inlet_properties_v1
    function.argtypes = [ct.POINTER(_QueryInput), ct.POINTER(_QueryCallbacks),
        ct.POINTER(_QueryResult), ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S]
    function.restype = ct.c_int
    return function


def _raw_kind(value):
    if isinstance(value, np.generic):
        precision = value.dtype.itemsize * (4 if np.iscomplexobj(value) else 8)
        return abi._Kind(precision, 2 if np.issubdtype(value.dtype, np.integer) else 1, 1)
    return abi._Kind(64, 0, 0)


def _raw_buffers(speed=6.):
    geometry = compute_geometry('Gyroid', 7., .5)
    weak = abi._Kind(64, 0, 0)
    key = _InletKey(_GeometryKey(1, 7., .5, weak, weak), 0, speed, 380., 160000.,
        abi._InletKinds(_raw_kind(speed), weak, weak))
    source = _QueryInput(1, ct.sizeof(_QueryInput), key, geometry['D_h'], geometry['epsilon_A'],
        _raw_kind(geometry['D_h']), _raw_kind(geometry['epsilon_A']), 0)
    result = _QueryResult(1, ct.sizeof(_QueryResult))
    for item in result.values:
        item.real = 123.
    return source, result, abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)


@pytest.mark.parametrize('speed', [6., np.float32(6.), np.int32(6.), -.2])
def test_raw_query_preserves_inputs_and_scalar_categories(raw_query, speed):
    source, result, failure, error = _raw_buffers(speed)
    before = bytes(source)
    failure.kind, failure.cause_count = 3, 1
    with warning_scope({}):
        expected = reference._compute_cached('Gyroid', 7., .5, speed, 380., 160000., 'air')
    properties = expected[0]
    values = [properties[name] for name in ('rho', 'mu', 'k_f')] + [expected.cp, expected.pr]
    values += [properties[name] for name in ('Re', 'Nu', 'K_df', 'cF_df', 'dP_per_L', 'H_sf', 'K_ff')]
    assert raw_query(ct.byref(source), None, ct.byref(result), ct.byref(failure), error, len(error)) == 0
    assert bytes(source) == before and not error.value
    assert not failure.kind and not failure.cause_count and not failure.have_property
    for actual, wanted in zip(result.values, values):
        assert actual.category == int(np.iscomplexobj(wanted))
        assert actual.real.hex() == float(np.real(wanted)).hex()
        assert actual.imaginary.hex() == float(np.imag(wanted)).hex()
        assert bytes(actual.kind) == bytes(_raw_kind(wanted))
    if speed < 0:
        assert result.values[6].category == result.values[10].category == 1


def test_raw_query_keeps_result_on_property_failure(raw_query):
    source, result, failure, error = _raw_buffers()
    source.inlet.temperature_K = -300.
    before_source, before_result = bytes(source), bytes(result)
    assert raw_query(ct.byref(source), None, ct.byref(result), ct.byref(failure), error, len(error)) == 3
    assert bytes(source) == before_source and bytes(result) == before_result
    assert failure.have_property and failure.property.fp.python_cause == 4
    assert error.value == b"float() argument must be a string or a real number, not 'complex'"


@pytest.mark.parametrize('field', ['source', 'result', 'failure', 'callbacks'])
@pytest.mark.parametrize('invalid', ['version', 'size'])
def test_raw_query_rejects_bad_metadata_without_output_changes(raw_query, field, invalid):
    source, result, failure, error = _raw_buffers()
    callbacks = _QueryCallbacks()
    callbacks.values.values.abi_version = 3
    callbacks.values.values.struct_size = ct.sizeof(callbacks)
    target = {'source': source, 'result': result, 'failure': failure,
              'callbacks': callbacks.values.values}[field]
    if invalid == 'version':
        target.abi_version = 99
    else:
        target.struct_size -= 1
    snapshots = [bytes(value) for value in (source, result, failure, callbacks)]
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result),
                     ct.byref(failure), error, len(error)) == 1
    assert [bytes(value) for value in (source, result, failure, callbacks)] == snapshots
    assert error.value


@pytest.mark.parametrize('slot', ['geometry_cache', 'inlet_cache'])
def test_raw_query_rejects_cache_hooks(raw_query, slot):
    source, result, failure, error = _raw_buffers()
    callbacks = _QueryCallbacks()
    callbacks.values.values.abi_version = 3
    callbacks.values.values.struct_size = ct.sizeof(callbacks)
    setattr(callbacks, slot, 1)
    before = bytes(result)
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result),
                     ct.byref(failure), error, len(error)) == 1
    assert bytes(result) == before and b'cache hooks' in error.value


@pytest.mark.parametrize('storage', ['source', 'result', 'failure', 'callbacks', 'text'])
def test_raw_query_rejects_diagnostic_and_text_aliases(raw_query, storage):
    source, result, failure, error = _raw_buffers()
    callbacks = _QueryCallbacks()
    callbacks.values.values.abi_version = 3
    callbacks.values.values.struct_size = ct.sizeof(callbacks)
    target = {'source': source, 'result': result, 'failure': failure, 'callbacks': callbacks}
    if storage == 'text':
        source.inlet.sco2_nu.source = abi.v1._Text(ct.cast(ct.byref(result), ct.POINTER(ct.c_char)), 8)
    else:
        error = ct.cast(ct.byref(target[storage]), ct.POINTER(ct.c_char))
    snapshots = [bytes(value) for value in (source, result, failure, callbacks)]
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result), ct.byref(failure),
                     error, 8) == 1
    assert [bytes(value) for value in (source, result, failure, callbacks)] == snapshots


@pytest.mark.parametrize('checkpoint', ['host', 'range'])
def test_raw_query_callback_cancellation_keeps_result(raw_query, checkpoint):
    source, result, failure, error = _raw_buffers()
    callbacks = _QueryCallbacks()
    callbacks.values.values.abi_version = 3
    callbacks.values.values.struct_size = ct.sizeof(callbacks)
    observed = []
    def validate(_context, stage, step):
        observed.append((stage, step))
        return int(step == 2)
    def observe(_context, _side, record, _bounds, _cached, _scalar):
        observed.append(abi.v1._text(record.contents.label))
        return 1
    hook = _HostFunction(validate) if checkpoint == 'host' else _RangeFunction(observe)
    if checkpoint == 'host':
        callbacks.values.validate_host_input = hook
    else:
        callbacks.observe_range = ct.cast(hook, ct.c_void_p)
    before_source, before_result = bytes(source), bytes(result)
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result),
                     ct.byref(failure), error, len(error)) == 3
    assert bytes(source) == before_source and bytes(result) == before_result
    assert failure.kind == 3 and error.value
    assert observed == ([(4, 0), (4, 1), (4, 2)] if checkpoint == 'host' else ['air_viscosity'])


@pytest.mark.parametrize('column,value,error_type,message,complex_warning', [
    (4, None, TypeError, "unsupported operand type(s) for /: 'NoneType' and 'float'", False),
    (4, '300', TypeError, "unsupported operand type(s) for /: 'str' and 'float'", False),
    (4, 'bad', ValueError, "could not convert string to float: 'bad'", False),
    (4, 1+2j, TypeError, "float() argument must be a string or a real number, not 'complex'", False),
    (4, np.complex128(300), TypeError, 'property arrays require supported real floating or integer values', True),
    (5, None, TypeError, "unsupported operand type(s) for *: 'NoneType' and 'float'", False),
    (5, '300', TypeError, "can't multiply sequence by non-int of type 'float'", False),
    (5, 1+2j, TypeError, "unsupported operand type(s) for *: 'complex' and 'float'", False),
    *[(3, value, TypeError, 'property arrays require supported real floating or integer values', False)
      for value in (None, '300', 1+2j, np.complex128(300))],
])
def test_host_object_errors_keep_pre_query_behavior(column, value, error_type, message, complex_warning):
    # The pre-query native primitives rejected these objects before arithmetic.
    args = ['Gyroid', 7., .5, 6., 380., 160000., 16., 'air']
    args[column] = value
    observed, _, notices = _observe(tpms_calc, args, scoped=False)
    assert observed == ('error', error_type, (message,))
    assert notices == ([(np.exceptions.ComplexWarning,
                         'Casting complex values to real discards the imaginary part')] if complex_warning else [])
    assert tpms_calc.compute.cache_info().currsize == 0


def test_raw_sco2_missing_pressure_keeps_existing_message():
    observed, _, notices = _observe(tpms_calc, ('Gyroid', 7., .5, 6., 480., None, 'sco2'),
                                   raw=True, scoped=False)
    assert observed == ('error', ValueError, ('sCO2 properties require pressure P [Pa]; caller passed P=None. '
        'Fix the call site to forward the inlet/local pressure.',))
    assert notices == [] and tpms_calc.compute.cache_info().currsize == 0


@pytest.mark.parametrize('temperature,pressure,message,cause', [
    (float('nan'), 4500000., 'CO2 requires finite positive temperature [K] and pressure [Pa(abs)]', None),
    (300., 0., 'CO2 requires finite positive temperature [K] and pressure [Pa(abs)]', None),
    (180., 4500000., 'CO2 at/below its triple-point temperature is outside this fluid model', None),
    (300., 6713078.06290996, 'CO2 requires a stable single-phase PT state; saturation, two-phase and '
     'critical-point states are unsupported. No outputs were able to be calculated',
     'No outputs were able to be calculated'),
])
def test_raw_co2_error_keeps_visible_cause_chain(temperature, pressure, message, cause):
    with pytest.raises(ValueError) as caught:
        tpms_calc._compute_cached('Gyroid', 7., .5, 6., temperature, pressure, 'co2')
    assert str(caught.value) == message and caught.value.__suppress_context__
    if cause is None:
        assert caught.value.__cause__ is None
    else:
        assert type(caught.value.__cause__) is ValueError
        assert str(caught.value.__cause__) == cause
        assert caught.value.__cause__.__cause__ is None
    assert tpms_calc.compute.cache_info().currsize == 0


_CONVERSION_OWNERS = (fluid_props, tpms_props, _native_properties, co2_props, sco2_props)


def _conversion_error(error):
    cause = error.__cause__
    return (type(error), error.args, error.__suppress_context__,
            None if cause is None else _conversion_error(cause))


def _conversion_registries():
    return {owner.__name__: {key: value for key, value in
            owner.__dict__.get('__warningregistry__', {}).items() if key != 'version'}
            for owner in _CONVERSION_OWNERS}


def _observe_conversions(call, policy, warning_owner):
    with warnings.catch_warnings(record=True) as caught, warning_scope({}):
        warnings.simplefilter('always')
        if policy.endswith('error') and policy != 'error':
            warnings.filterwarnings('error', category=np.exceptions.ComplexWarning,
                                    module=re.escape(warning_owner.__name__) + '$')
        else:
            warnings.simplefilter(policy, np.exceptions.ComplexWarning)
        try:
            result = ('value', call())
        except Exception as error:
            result = ('error', _conversion_error(error))
        notices = [(item.category, str(item.message), item.filename, item.lineno)
                   for item in caught]
        registries = _conversion_registries()
    return result, notices, registries


@pytest.mark.parametrize('fluid,policy', [
    (fluid, policy) for fluid in ('air', 'water', 'co2', 'sco2')
    for policy in ('always', 'default', 'error', 'source-error')
] + [('water', 'water-state-error'), ('water', 'water-native-error')])
@pytest.mark.parametrize('case', [
    'numpy-T', 'numpy-P', 'bad-T-complex-P', 'complex-T-complex-P',
    'bad-T-no-P', 'complex-T-no-P',
])
def test_compound_inputs_keep_conversion_warnings_and_first_error(monkeypatch, fluid, policy, case):
    temperature, pressure = {'air': (300., 101325.), 'water': (320., 200000.),
                             'co2': (300., 4500000.), 'sco2': (480., 9000000.)}[fluid]
    temperature, pressure = {
        'numpy-T': (np.complex128(temperature), pressure),
        'numpy-P': (temperature, np.complex128(pressure)),
        'bad-T-complex-P': ('bad', np.complex128(pressure)),
        'complex-T-complex-P': (1+2j, np.complex128(pressure)),
        'bad-T-no-P': ('bad', None),
        'complex-T-no-P': (1+2j, None),
    }[case]
    warning_owner = {'air': tpms_props, 'water': tpms_props,
                     'co2': co2_props, 'sco2': sco2_props}[fluid]
    if policy == 'water-state-error':
        warning_owner = fluid_props
    elif policy == 'water-native-error':
        warning_owner = _native_properties
    entered_cache = []

    def expected_call():
        fluid_props.check_water_state(fluid, temperature, pressure, where='compute inlet')
        entered_cache.append(True)
        model = fluid_props.get(fluid)
        mu, conductivity, density, _cp = (float(function(temperature, pressure))
            for function in (model.mu, model.k, model.rho, model.cp))
        return mu, conductivity, density

    def actual_call():
        result = tpms_calc.compute('Gyroid', 7., .5, 6., temperature, pressure, 16., fluid)
        return tuple(result[name] for name in ('mu', 'k_f', 'rho'))

    def reset():
        _clear(tpms_calc)
        co2_props._scalar.cache_clear()
        sco2_props._prop.cache_clear()
        for owner in _CONVERSION_OWNERS:
            monkeypatch.setattr(owner, '__warningregistry__', {}, raising=False)

    reset()
    expected = _observe_conversions(expected_call, policy, warning_owner)
    reset()
    actual = _observe_conversions(actual_call, policy, warning_owner)
    _same(actual[:2], expected[:2])
    assert actual[2] == expected[2]
    success = actual[0][0] == 'value'
    info = tpms_calc.compute.cache_info()
    assert (info.hits, info.misses, info.currsize) == (0, len(entered_cache), int(success))

    if success and fluid in ('co2', 'sco2'):
        with warnings.catch_warnings(record=True) as caught, warning_scope({}):
            warnings.simplefilter('always')
            _same(actual_call(), actual[0][1])
        assert not caught
        assert _conversion_registries() == actual[2]
        info = tpms_calc.compute.cache_info()
        assert (info.hits, info.misses, info.currsize) == (1, 1, 1)
