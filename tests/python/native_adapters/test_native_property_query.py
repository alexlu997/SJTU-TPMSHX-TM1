"""Check public float64 scalar inlet-property queries and raw C ABI contracts."""
import ctypes as ct
from contextlib import nullcontext
from dataclasses import replace
import os
import warnings

import numpy as np
import pytest

from tests.python import df_reference, float64_oracle as oracle, property_reference as reference
from tm1.data_types.compute_config import Sco2NuConfig
from tm1.run_control.run_warnings import range_context, warning_scope
from tm1.physical_models import (
    co2_correlations, fluid_props, nu_correlations, tpms_calc, tpms_props,
)
from tm1.physical_models.tpms_geometry import compute_geometry
from tm1.cpp_interface import _native_preparation_case as abi
from tests.python import native_preparation_abi


def _clear():
    tpms_calc.compute.cache_clear()
    compute_geometry.cache_clear()
    reference._range_warnings_emitted.clear()
    tpms_props._range_warnings_emitted.clear()
    for name in ('_EXTRAP_WARNED', '_WATER_NU_WARNED', '_SCO2_NU_WARNED'):
        getattr(nu_correlations, name).clear()


@pytest.fixture(autouse=True)
def isolated_cache_and_warning_state():
    _clear()
    yield
    _clear()


def _oracle_inlet(topology, cell_mm, wall_mm, speed, temperature, pressure, conductivity,
                  fluid='air', *, sco2_nu=None, co2_geometry=False):
    """Independent float64 combination built from pure formula oracles."""
    cell_f, wall_f = float(cell_mm), float(wall_mm)
    speed_f, temp_f, press_f = float(speed), float(temperature), float(pressure)
    if co2_geometry or fluid == 'co2':
        geom = co2_correlations.geometry(topology, cell_f, wall_f)
    else:
        geom = compute_geometry(topology, cell_f, wall_f)
    eps, eps_a, area, dh = float(geom['epsilon']), float(geom['epsilon_A']), float(geom['A_0']), float(geom['D_h'])
    dh_mm = dh * 1000.0
    selected = sco2_nu if fluid == 'sco2' and sco2_nu is not None and sco2_nu.mode == 'experimental' else None
    model = reference.fluid_model(fluid, sco2_nu=selected)
    rho = float(model.rho(temp_f, press_f))
    mu = float(model.mu(temp_f, press_f))
    k_f = float(model.k(temp_f, press_f))
    cp = float(model.cp(temp_f, press_f))
    pr = mu * cp / k_f
    re = rho * speed_f * dh / mu
    nu = float(oracle.call(model.nu, topology, re, eps_a, cell_f, dh_mm, pr))
    h_sf = nu * k_f / dh
    k_df, cf_df = df_reference.predict_K_cF(topology, cell_f, wall_f, eps_a)
    if fluid == 'co2':
        k_df, cf_df, _ = df_reference.apply_prepared_correction(
            k_df, cf_df, {'scale_K': 1. / 2.5, 'scale_F': 2.5})
    dp_per_l = float(df_reference.pressure_gradient(rho, mu, speed_f, k_df, cf_df))
    k_ff = eps_a * k_f
    return dict(
        epsilon=eps, epsilon_A=eps_a, epsilon_B=eps_a, A_0=area, D_h=dh,
        Re=re, Nu=nu, K_df=float(k_df), cF_df=float(cf_df), dP_per_L=dp_per_l,
        H_sf=h_sf, K_ff=k_ff, rho=rho, mu=mu, k_f=k_f, cp=cp, pr=pr,
    )


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2', 'co2'])
@pytest.mark.parametrize('kind', [float, np.float32, np.float64])
@pytest.mark.parametrize('scoped', [False, True])
def test_complete_property_query_matches_float64_formulas(topology, fluid, kind, scoped):
    temperature, pressure = {'air': (380., 160000.), 'water': (320., 200000.),
                             'sco2': (480., 9000000.), 'co2': (300., 4500000.)}[fluid]
    args = (topology, kind(7.), kind(.5), kind(6.), kind(temperature), kind(pressure), kind(16.), fluid)
    with warnings.catch_warnings(), warning_scope({}) if scoped else nullcontext(None):
        warnings.simplefilter('ignore')
        actual = tpms_calc.compute(*args)
        expected = _oracle_inlet(*args)
    for key in ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h', 'Re', 'Nu',
                'K_df', 'cF_df', 'dP_per_L', 'H_sf', 'K_ff', 'rho', 'mu', 'k_f'):
        assert actual[key] == pytest.approx(expected[key], rel=1e-13, abs=1e-15), key
    assert actual['K_ss'] > 0.


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2', 'co2'])
def test_cached_internal_cp_pr_and_source_records_match_formulas(fluid):
    temperature, pressure = (320., 200000.) if fluid == 'water' else (480., 9000000.)
    with warnings.catch_warnings(), warning_scope({}):
        warnings.simplefilter('ignore')
        cached = tpms_calc._compute_cached('Diamond', 7., .5, np.float32(6.), temperature, pressure, fluid)
        expected = _oracle_inlet('Diamond', 7., .5, 6., temperature, pressure, 16., fluid)
    values, records = cached
    assert isinstance(records, dict)
    assert cached.cp == pytest.approx(expected['cp'], rel=1e-13)
    assert cached.pr == pytest.approx(expected['pr'], rel=1e-13)
    assert values['Nu'] == pytest.approx(expected['Nu'], rel=1e-13)


@pytest.mark.parametrize('kind', [float, np.float32])
def test_cache_hits_keep_current_material_and_unpoisoned_copies(monkeypatch, kind):
    args = ('Gyroid', 7., .5, kind(6.), 380., 160000., kind(16.))
    with warning_scope({}):
        monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
        first = tpms_calc.compute(*args)
        first_rho = first['rho']
        first['rho'] = -1.
        monkeypatch.setenv('TPMSHX_CHI_S', '.5')
        second = tpms_calc.compute(*args)
        monkeypatch.setenv('TPMSHX_CHI_S', '.7')
        third = tpms_calc.compute(*args)
    assert second['rho'] == first_rho
    assert third['K_ss'] > second['K_ss'] > 0.
    info = tpms_calc.compute.cache_info()
    assert (info.hits, info.misses, info.currsize) == (2, 1, 1)


def test_equal_scalar_keys_share_float64_cache_entry():
    with warning_scope({}):
        first = tpms_calc.compute('Diamond', 7., .5, np.float32(6.), 380., 160000., 16.)
        second = tpms_calc.compute('Diamond', 7., .5, 6., 380., 160000., 16.)
    assert first == second
    info = tpms_calc.compute.cache_info()
    assert (info.hits, info.misses, info.currsize) == (1, 1, 1)


@pytest.mark.parametrize('co2_geometry', [False, True])
def test_co2_geometry_and_drag_follow_the_registered_fluid(monkeypatch, co2_geometry):
    args = ('Gyroid', 7., .6, 2., 350., 800000., 16.)
    monkeypatch.setitem(fluid_props.FLUIDS, 'carbon dioxide', fluid_props.get('co2'))
    with warning_scope({}):
        expected = tpms_calc.compute(*args, fluid_type='co2', co2_geometry=co2_geometry)
        assert expected['dP_per_L'] == pytest.approx(26285.873924157153, rel=2e-12)
        for spelling in ('CO2', ' Co2 ', 'carbon dioxide'):
            tpms_calc.compute.cache_clear()
            assert tpms_calc.compute(*args, fluid_type=spelling, co2_geometry=co2_geometry) == expected
            assert tpms_calc.compute(*args, fluid_type='co2', co2_geometry=co2_geometry) == expected


def test_inlet_adapter_uses_registered_co2_drag_for_supplied_geometry():
    from tm1.physical_models.tpms_calc import inlet_query

    args = ('Gyroid', 7., .6, 2., 350., 800000.)
    geometry = compute_geometry('Gyroid', 7., .6)
    with warning_scope({}):
        expected = inlet_query(*args, 'co2', None, geometry, {}, lambda *_: None)
        assert inlet_query(*args, ' CO2 ', None, geometry, {}, lambda *_: None) == expected


@pytest.mark.parametrize('text', ['property', 'unbound', 'K'])
def test_inlet_range_text_failures_keep_their_original_exception(text, monkeypatch):
    from tm1.cpp_interface import preparation_host

    marker = StopIteration(text)
    read = preparation_host.read_text

    def fail_at(source):
        item = read(source)
        if item == text:
            raise marker
        return item

    monkeypatch.setattr(preparation_host, 'read_text', fail_at)
    error = StopIteration if text == 'K' else RuntimeError
    with warning_scope({}), pytest.raises(error) as caught:
        tpms_calc.inlet_query('Gyroid', 7., .6, 2., 350., 2e5, 'air', None,
                              dict(D_h=.003, epsilon_A=.38), {}, lambda *_: None)
    if text == 'K':
        assert caught.value is marker and marker.__cause__ is None
    else:
        assert str(caught.value) == 'generator raised StopIteration' and caught.value.__cause__ is marker


@pytest.mark.parametrize('mode', ['ignore', 'warn', 'raise', 'print'])
def test_scalar_arithmetic_replays_at_each_query_call_site(mode, capsys):
    from pathlib import Path

    args = ('Gyroid', 7., .6, float(np.finfo(float).smallest_subnormal), 350., 2e5)
    geometry = dict(D_h=.003, epsilon_A=.38)

    def supplied():
        return tpms_calc.inlet_query(*args, 'air', None, geometry, {}, lambda *_: None)

    with warning_scope({}), warnings.catch_warnings(record=True) as captured, np.errstate(all=mode):
        warnings.simplefilter('default')
        for call in (lambda: tpms_calc.compute(*args, 16.), supplied) * 2:
            tpms_calc.compute.cache_clear()
            outcome = pytest.raises(FloatingPointError, match='underflow encountered in multiply') if mode == 'raise' else nullcontext()
            with outcome:
                call()
    messages = [(item.category, str(item.message), Path(item.filename)) for item in captured]
    expected = [(RuntimeWarning, 'underflow encountered in multiply', Path(name))
                for name in (tpms_calc.__file__, __file__)]
    assert messages == (expected if mode == 'warn' else [])
    printed = capsys.readouterr().err.splitlines()
    assert printed == (['Warning: underflow encountered in multiply'] * 20 if mode == 'print' else [])


def test_cache_warning_replay_binds_new_run_context():
    args = ('Diamond', 7., .5, .001, 1200., 160000., 16.)
    with warnings.catch_warnings(record=True) as standalone:
        warnings.simplefilter('always')
        tpms_calc.compute(*args)
    assert standalone
    scoped = {}
    for side in 'AB':
        with warning_scope({}) as records, range_context(side=side, stage='inlet', layout='scalar'):
            tpms_calc.compute(*args)
        scoped[side] = records
    assert any(key[-1][0] == 'A' for key in scoped['A'])
    assert any(key[-1][0] == 'B' for key in scoped['B'])
    assert tpms_calc.compute.cache_info().hits == 2


@pytest.mark.parametrize('args,error_type', [
    (('Gyroid', 7., .5, .2, 400., 101325., 16., 'water'), fluid_props.WaterStateError),
    (('Gyroid', 7., .5, .2, 270., 9000000., 16., 'sco2'), ValueError),
    (('Gyroid', 7., .5, .2, 180., 4500000., 16., 'co2'), ValueError),
    (('Gyroid', 3., .5, .2, 380., 101325., 16., 'air'), ValueError),
    (('Gyroid', 7., .5, .2, 380., 101325., 16., 'other'), ValueError),
])
def test_invalid_inputs_raise_without_caching(args, error_type):
    with pytest.raises(error_type):
        tpms_calc.compute(*args)
    assert tpms_calc.compute.cache_info().currsize == 0


def test_negative_speed_produces_real_float64_nan_without_complex():
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore')
        values, _ = tpms_calc._compute_cached('Gyroid', 7., .5, -.2, 300., 101325., 'air')
    assert type(values['Nu']) is float and np.isnan(values['Nu'])
    assert type(values['H_sf']) is float and np.isnan(values['H_sf'])


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_selected_sco2_model_and_co2_geometry_remain_independent(topology):
    settings = replace(Sco2NuConfig(), mode='experimental', alpha_D=1.13, alpha_G=2.27,
                       parameter_version='query-reference', source='regression', applicability='test only')
    with warning_scope({}):
        actual = tpms_calc.compute(topology, 7., .5, 6., 480., 9000000., 16., 'sco2',
                                   sco2_nu=settings, co2_geometry=True)
        expected = _oracle_inlet(topology, 7., .5, 6., 480., 9000000., 16., 'sco2',
                                 sco2_nu=settings, co2_geometry=True)
    assert actual['Nu'] == pytest.approx(expected['Nu'], rel=1e-13)


@pytest.mark.parametrize('fluid', ['water', 'sco2'])
def test_nu_notice_uses_floored_re_but_records_raw_re(fluid):
    temperature, pressure = (320., 200000.) if fluid == 'water' else (480., 9000000.)
    args = ('Gyroid', 7., .5, 1.e-6, temperature, pressure, 16., fluid)
    with warnings.catch_warnings(record=True) as standalone:
        warnings.simplefilter('always')
        tpms_calc.compute(*args)
    assert any('Re=[1,1]' in str(item.message) for item in standalone)
    _clear()
    with warning_scope({}) as records:
        tpms_calc.compute(*args)
    nu_records = [value for key, value in records.items() if key[:2] == ('nu', fluid)]
    assert nu_records and nu_records[0].maximum[0] < 1.


@pytest.mark.parametrize('column,value', [
    (3, None), (3, '300'), (3, 1 + 2j), (3, np.complex128(300)),
    (4, None), (4, '300'), (4, 1 + 2j), (4, np.complex128(300)),
    (5, None), (5, '300'), (5, 1 + 2j), (5, np.complex128(300)),
])
def test_non_real_host_inputs_are_rejected_without_caching(column, value):
    args = ['Gyroid', 7., .5, 6., 380., 160000., 16., 'air']
    args[column] = value
    with pytest.raises((TypeError, ValueError)):
        tpms_calc.compute(*args)
    assert tpms_calc.compute.cache_info().currsize == 0


def test_raw_sco2_missing_pressure_keeps_existing_message():
    with pytest.raises(ValueError, match='sCO2 properties require pressure P'):
        tpms_calc._compute_cached('Gyroid', 7., .5, 6., 480., None, 'sco2')
    assert tpms_calc.compute.cache_info().currsize == 0


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


@pytest.fixture(scope='module')
def raw_query():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', native_preparation_abi._library_path()))
    function = library.tpmshx_query_inlet_properties_v2
    function.argtypes = [ct.POINTER(abi._InletQueryInput), ct.POINTER(abi._Callbacks),
        ct.POINTER(abi._InletQueryResult), ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S]
    function.restype = ct.c_int
    return function


@pytest.mark.parametrize('name', ['cached_co2', 'co2_pt'])
def test_co2_cause_offset_requires_a_written_byte(name):
    from tm1.cpp_interface import _native_properties as properties

    temperature, pressure = ct.c_double(300.), ct.c_double(6713078.06290996)
    values, key = (ct.c_double * 5)(), ct.c_uint32(0)
    call = properties._function(properties.preparation_library.get(), name)
    args = ((temperature, pressure, values, 5) if name == 'cached_co2' else
            (ct.byref(temperature), ct.byref(pressure), 1, ct.byref(key), 1, values, 1))

    def query(capacity):
        error, offset = ct.create_string_buffer(capacity), ct.c_size_t()
        assert call(*args, ct.byref(offset), None, error, capacity) == 11
        return error.value, offset.value

    message, start = query(512)
    cause = b'No outputs were able to be calculated'
    assert start < len(message) and message[start:] == cause
    assert query(start + 1) == (message[:start], ct.c_size_t(-1).value)
    assert query(start + 2) == (message[:start + 1], start)


def _raw_buffers(speed=6.):
    geometry = compute_geometry('Gyroid', 7., .5)
    key = abi._InletKey(abi._GeometryKey(1, 7., .5), 0, float(speed), 380., 160000.)
    source = abi._InletQueryInput(1, ct.sizeof(abi._InletQueryInput), key,
                                  float(geometry['D_h']), float(geometry['epsilon_A']), 0)
    result = abi._InletQueryResult(1, ct.sizeof(abi._InletQueryResult))
    for i in range(12):
        result.values[i] = 123.
    return source, result, abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)


@pytest.mark.parametrize('speed', [6., np.float32(6.), np.int32(6)])
def test_raw_query_matches_float64_oracle(raw_query, speed):
    source, result, failure, error = _raw_buffers(speed)
    before = bytes(source)
    failure.kind, failure.cause_count = 3, 1
    expected = _oracle_inlet('Gyroid', 7., .5, float(speed), 380., 160000., 16., 'air')
    wanted = [expected[name] for name in (
        'rho', 'mu', 'k_f', 'cp', 'pr', 'Re', 'Nu', 'K_df', 'cF_df', 'dP_per_L', 'H_sf', 'K_ff')]
    assert raw_query(ct.byref(source), None, ct.byref(result), ct.byref(failure), error, len(error)) == 0
    assert bytes(source) == before and not error.value
    assert not failure.kind and not failure.cause_count and not failure.have_property
    for actual, target in zip(result.values, wanted):
        assert actual == pytest.approx(target, rel=1e-13, abs=1e-15)


@pytest.mark.parametrize('field', ['source', 'result', 'failure', 'callbacks'])
@pytest.mark.parametrize('invalid', ['version', 'size'])
def test_raw_query_rejects_bad_metadata_without_output_changes(raw_query, field, invalid):
    source, result, failure, error = _raw_buffers()
    callbacks = abi._Callbacks(2, ct.sizeof(abi._Callbacks))
    target = {'source': source, 'result': result, 'failure': failure, 'callbacks': callbacks}[field]
    if invalid == 'version':
        target.abi_version = 99
    else:
        target.struct_size -= 1
    snapshots = [bytes(value) for value in (source, result, failure, callbacks)]
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result),
                     ct.byref(failure), error, len(error)) == 1
    assert [bytes(value) for value in (source, result, failure, callbacks)] == snapshots
    assert error.value


@pytest.mark.parametrize('slot', ['inlet_cache', 'inlet_cache_at', 'sigmoid_lut_cache'])
def test_raw_query_rejects_cache_hooks(raw_query, slot):
    source, result, failure, error = _raw_buffers()
    callbacks = abi._Callbacks(2, ct.sizeof(abi._Callbacks))
    factory = {
        'inlet_cache': abi._InletCacheFunction,
        'inlet_cache_at': abi._InletAtFunction,
        'sigmoid_lut_cache': abi._LUTCacheFunction,
    }[slot]
    dummy = factory(lambda *a: 0)
    setattr(callbacks, slot, dummy)
    before = bytes(result)
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result),
                     ct.byref(failure), error, len(error)) == 1
    assert bytes(result) == before and b'cache hooks' in error.value


@pytest.mark.parametrize('storage', ['source', 'result', 'failure', 'callbacks', 'text'])
def test_raw_query_rejects_diagnostic_and_text_aliases(raw_query, storage):
    source, result, failure, error = _raw_buffers()
    callbacks = abi._Callbacks(2, ct.sizeof(abi._Callbacks))
    target = {'source': source, 'result': result, 'failure': failure, 'callbacks': callbacks}
    if storage == 'text':
        source.inlet.sco2_nu.source = abi._Text(ct.cast(ct.byref(result), ct.POINTER(ct.c_char)), 8)
    else:
        error = ct.cast(ct.byref(target[storage]), ct.POINTER(ct.c_char))
    snapshots = [bytes(value) for value in (source, result, failure, callbacks)]
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result), ct.byref(failure),
                     error, 8) == 1
    assert [bytes(value) for value in (source, result, failure, callbacks)] == snapshots


@pytest.mark.parametrize('checkpoint', ['host', 'range'])
def test_raw_query_callback_cancellation_keeps_result(raw_query, checkpoint):
    source, result, failure, error = _raw_buffers()
    callbacks = abi._Callbacks(2, ct.sizeof(abi._Callbacks))
    observed = []

    def validate(_context, stage, step):
        observed.append((stage, step))
        return int(step == 2)

    def observe(_context, _cached, record, _bounds, _have, _scalar):
        observed.append(native_preparation_abi._text(record.contents.label))
        return 1

    host_hook = abi._HostFunction(validate)
    range_hook = abi._RangeFunction(observe)
    if checkpoint == 'host':
        callbacks.validate_host_input = host_hook
    else:
        callbacks.observe_range = range_hook
    before_source, before_result = bytes(source), bytes(result)
    assert raw_query(ct.byref(source), ct.byref(callbacks), ct.byref(result),
                     ct.byref(failure), error, len(error)) == 3
    assert bytes(source) == before_source and bytes(result) == before_result
    assert failure.kind == 3 and error.value
    assert observed == ([(4, 0), (4, 1), (4, 2)] if checkpoint == 'host' else ['air_viscosity'])
