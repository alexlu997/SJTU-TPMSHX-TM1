"""Check the production stage boundary against independent result references."""
from collections.abc import Mapping
from dataclasses import replace
import gc
import os
from pathlib import Path
import warnings
import weakref

import numpy as np
import pytest

from tm1.cpp_interface import _native_result as core, _native_result_stage as stage
from tm1.data_types.metric_spec import MetricSpec
from tm1.data_types.portable_data import mutable_data
from tm1.file_io.result_io import load_result
from tm1.postprocess import api
from tests.python.native.result_reference import api as reference
from tests.python.native.test_result_metrics import quick_result
from tests.python.native_adapters.test_native_result_balance import assert_values, observe, assert_observation
from tests.python.postprocess_tm1.test_conservative_energy_results import result_fixture
from tests.python.postprocess_tm1.test_temperature_face_results import temperature_fixture
from tests.python.postprocess_tm1.test_physical_balance import sample_result
from tests.python.postprocess_tm1.test_qualification import qualified_result, required_metrics


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(row) for key, row in value.items()}
    if isinstance(value, tuple):
        return tuple(plain(row) for row in value)
    if isinstance(value, list):
        return [plain(row) for row in value]
    return value


def performance(value):
    return dict(source_result_id=value.source_result_id,
        metrics={name: dict(value=row.value, spec=row.spec, status=row.status, reason=row.reason)
                 for name, row in value.metrics.items()}, qualification=plain(value.qualification))


def compare(result, query, request=None):
    if query == 'evaluate':
        actual = observe(lambda: performance(api.evaluate(result, request)))
        expected = observe(lambda: performance(reference.evaluate(result, request)))
    elif query == 'qualification':
        metrics = reference.evaluate(result).metrics
        actual = observe(lambda: api.evaluate_qualification(result, metrics))
        expected = observe(lambda: reference.evaluate_qualification(result, metrics))
    else:
        actual = observe(lambda: getattr(api, 'evaluate_' + query)(result))
        expected = observe(lambda: getattr(reference, 'evaluate_' + query)(result))
    assert_observation(actual, expected)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('fixture', [result_fixture, temperature_fixture, sample_result])
@pytest.mark.parametrize('query', ['evaluate', 'applicability', 'physical_balance', 'qualification'])
def test_typed_reports_and_order(dimension, fixture, query):
    compare(fixture(dimension), query)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('query', ['evaluate', 'applicability', 'physical_balance', 'qualification'])
def test_frozen_full_reports(dimension, query):
    root = os.environ.get('TPMSHX_RESULT_STAGE_FROZEN_DIR')
    if not root:
        pytest.skip('set TPMSHX_RESULT_STAGE_FROZEN_DIR to use the frozen full solves')
    compare(load_result(Path(root) / f'air-{dimension}d/results.h5'), query)


@pytest.mark.parametrize('dimension', [2, 3])
def test_selected_metric_defers_unrelated_scalar_failure(dimension):
    result = result_fixture(dimension)
    metadata = mutable_data(result.metadata)
    metadata['solid_density_kg_m3'] = 'not a numeric density'
    request = MetricSpec('Q', 'W/m' if dimension == 2 else 'W', 'native_boundary_v1')
    result = replace(result, metadata=metadata)
    compare(result, 'evaluate', request)
    actual = api.evaluate(result, request)
    assert actual.metrics['Q'].spec is request


def test_applicability_does_not_touch_unrelated_numeric_protocols():
    result = result_fixture(3)
    metadata = mutable_data(result.metadata)
    metadata.update(solid_density_kg_m3=2**1100, diagnostics=None, parameters=None)
    compare(replace(result, metadata=metadata), 'applicability')


def test_fixed_overflow_warning_precedes_delayed_qualification_error():
    result = result_fixture(3)
    pressure = mutable_data(result.pressure_evidence)
    pressure['A'].update(P=np.full((2, 2, 2), np.finfo(float).max),
        dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
        inlet_frac=np.ones((2, 2)), outlet_frac=np.ones((2, 2)))
    result = replace(result, pressure_evidence=pressure, metadata=dict(result.metadata, diagnostics=None))
    request = MetricSpec('dP', 'Pa', 'pressure_face_v1')
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('always')
        with pytest.raises(AttributeError):
            api.evaluate(result, request)
    overflows = [item for item in emitted if 'overflow' in str(item.message) and item.category is RuntimeWarning]
    assert overflows and all(item.filename == api.__file__ for item in overflows)


@pytest.mark.parametrize('query', ['evaluate', 'physical_balance', 'qualification'])
@pytest.mark.parametrize('state', ['missing', 'none', 'empty'])
@pytest.mark.parametrize('dimension', [2, 3])
def test_missing_none_and_empty_mass_are_distinct(query, state, dimension):
    result = sample_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    if state == 'missing':
        flux.pop('mass_A')
    else:
        flux['mass_A'] = None if state == 'none' else ()
    compare(replace(result, boundary_fluxes=flux), query)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('density_shape', [(), (2, 1), (1, 2), (2, 2)])
def test_full_mass_keeps_density_array_arithmetic(dimension, density_shape):
    shape = (2,) * dimension
    density_shape = density_shape + ((1,) if dimension == 3 and density_shape else ())
    result = result_fixture(dimension)
    metadata = mutable_data(result.metadata)
    metadata.update(solid_density_kg_m3=np.full(density_shape, 3., dtype=np.float64),
                    design_fields=dict(eps_arr=np.full(shape, .25, dtype=np.float64)))
    result = replace(result, metadata=metadata)
    compare(result, 'evaluate', MetricSpec('mass', 'kg/m' if dimension == 2 else 'kg'))


def legacy_temperature_result():
    result = result_fixture(2)
    fields = dict(Ta=np.array([[390., 380.], [330., 320.]], dtype=np.float64),
        Tb=np.array([[300., 310.], [340., 350.]], dtype=np.float64), Ts=np.full((2, 2), 350., dtype=np.float64),
        ucA=np.ones((2, 2), dtype=np.float64), ucB=np.ones((2, 2), dtype=np.float64),
        vcA=np.zeros((2, 2), dtype=np.float64), vcB=np.zeros((2, 2), dtype=np.float64))
    metadata = mutable_data(result.metadata)
    metadata.update(thermal_mode='temperature', split_A=.4, rho_cp_A=np.full((2, 2), 2., dtype=np.float64),
                    rho_cp_B=np.full((2, 2), 3., dtype=np.float64))
    metadata.pop('temperature_transport', None)
    metadata['parameters'].update(eps=np.full((2, 2), .5, dtype=np.float64), T_inA=400., T_inB=300., dir_A=0, dir_B=0)
    flux = mutable_data(result.boundary_fluxes)
    for name in ('true_h', 'temperature', 'energy', 'fine'):
        flux.pop(name, None)
    pressure = {side: dict(inlet_fraction=np.ones(2, dtype=np.float64), outlet_fraction=np.ones(2, dtype=np.float64),
                          outlet_geom_frac=np.ones(2, dtype=np.float64)) for side in 'AB'}
    return replace(result, fields=fields, metadata=metadata, boundary_fluxes=flux, pressure_evidence=pressure)


@pytest.mark.parametrize('split_shape', [(), (2, 2)])
@pytest.mark.parametrize('inlet_shape', [None, (), (2,)])
def test_legacy_temperature_typed_inputs(split_shape, inlet_shape):
    result = legacy_temperature_result()
    metadata = mutable_data(result.metadata)
    metadata['split_A'] = np.full(split_shape, .4, dtype=np.float64)
    metadata['parameters']['T_inA'] = None if inlet_shape is None else np.full(inlet_shape, 400., dtype=np.float64)
    metadata['parameters']['T_inB'] = None if inlet_shape is None else np.full(inlet_shape, 300., dtype=np.float64)
    result = replace(result, metadata=metadata)
    compare(result, 'evaluate', MetricSpec('Q_A', 'W/m', 'native_boundary_v1'))
    compare(result, 'evaluate', MetricSpec('Q_B', 'W/m', 'native_boundary_v1'))


# Each invalid dimension runs with a valid mode. Each invalid mode runs with a valid
# dimension. One pair with two invalid values keeps the error order.
@pytest.mark.parametrize('dimension,mode', [
    (None, 'full'), (2., 'full'), (3., 'full'), (7, 'full'), ('2', 'full'), (2., None), (7, 1)])
def test_original_dimension_and_mode_errors(dimension, mode):
    result = sample_result(2)
    metadata = mutable_data(result.metadata)
    metadata.update(dimension=dimension, mode=mode)
    grid = mutable_data(result.grid)
    grid['dimension'] = dimension
    compare(replace(result, metadata=metadata, grid=grid), 'evaluate')


@pytest.mark.parametrize('name,value', [('state', 17), ('outer_index', 2**80)])
def test_physical_provenance_keeps_original_portable_values(name, value):
    result = sample_result(2)
    if name == 'state':
        result = replace(result, boundary_fluxes={**result.boundary_fluxes, name: value})
    else:
        result = replace(result, run_status={**result.run_status, name: value})
    compare(result, 'physical_balance')


@pytest.mark.parametrize('kind', ['captured', 'missing', 'nonfinite', 'bad_counts', 'uncaptured'])
def test_applicability_report_keeps_source_types_and_provenance(kind):
    from tests.python.postprocess_tm1.test_applicability import result_with_evidence
    result = result_with_evidence()
    metadata = mutable_data(result.metadata)
    evidence = metadata['applicability_evidence']
    evidence['inlet'][0]['audit_note'] = ('original', 17)
    evidence['required'][0]['audit_note'] = ('required', 23)
    if kind == 'missing':
        evidence['final'] = []
    elif kind == 'nonfinite':
        evidence['final'][0]['nonfinite'] = 1
    elif kind == 'bad_counts':
        evidence['final'][0]['size'] = 0
    elif kind == 'uncaptured':
        evidence['final'] = [dict(captured=False, side='A', source=('nu_raw', 'water', 'Gyroid'),
            quantity='Re', reason='no state', audit_note=('uncaptured', 31))]
    result = replace(result, metadata=metadata)
    compare(result, 'applicability')
    compare(result, 'qualification')


@pytest.mark.parametrize('query', ['evaluate', 'qualification'])
@pytest.mark.parametrize('value', [None, 'invalid field', (('bad', 'field'),)])
def test_raw_field_finite_protocol_keeps_original_error(query, value):
    result = result_fixture(3)
    fields = dict(result.fields, Ts=value)
    result = replace(result, fields=fields)
    if query == 'qualification':
        assert_observation(observe(lambda: api.evaluate_qualification(result, {})),
                           observe(lambda: reference.evaluate_qualification(result, {})))
    else:
        compare(result, query)


def test_raw_and_display_fields_keep_distinct_errors(monkeypatch):
    import ctypes as ct

    result = qualified_result()
    invalid = 'invalid temperature'
    result = replace(result, fields=dict(result.fields, Ta=invalid, Ta_display=invalid))
    errors = []
    pack_array = stage._Packed.array

    def record_error(packed, value, *, finite_protocol=False):
        pointer = pack_array(packed, value, finite_protocol=finite_protocol)
        if isinstance(value, str) and value == invalid:
            errors.append(packed.array_errors[ct.addressof(pointer.contents)].args)
        return pointer

    monkeypatch.setattr(stage._Packed, 'array', record_error)
    with pytest.raises(TypeError) as finite:
        np.isfinite(np.asarray(invalid))
    with pytest.raises(TypeError) as conversion:
        core.array(invalid)
    with pytest.raises(TypeError) as reported:
        api.evaluate_qualification(result, required_metrics())
    assert reported.value.args == finite.value.args
    assert errors == [finite.value.args, conversion.value.args]


@pytest.mark.parametrize('dimension', [2, 3])
def test_physical_balance_rejects_portable_non_numeric_faces(dimension):
    result = sample_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    shape = flux['mass_A'][0].shape
    flux['mass_A'][0] = np.full(shape, 'bad').tolist()
    compare(replace(result, boundary_fluxes=flux), 'physical_balance')


@pytest.mark.parametrize('name', ['diagnostics', 'parameters'])
def test_nested_record_error_is_read_at_its_original_boundary(name):
    result = result_fixture(3)
    metadata = dict(result.metadata, **{name: None})
    compare(replace(result, metadata=metadata), 'evaluate', MetricSpec('Q', 'W', 'native_boundary_v1'))


@pytest.mark.parametrize('query', ['evaluate', 'applicability', 'physical_balance', 'qualification'])
def test_missing_stage_symbol_is_a_deployment_error(monkeypatch, query):
    from tests.python.native_adapters.test_native_result_loader import LibraryStub
    handle = LibraryStub(tpmshx_result_abi_version_v1=lambda: 3)
    monkeypatch.setattr(core.ct, 'CDLL', lambda _: handle)
    library = core.result_library.open('historical-result-image')
    monkeypatch.setattr(core.result_library, 'get', lambda: library)
    function = getattr(api, 'evaluate' if query == 'evaluate' else 'evaluate_' + query)
    arguments = (sample_result(2), {}) if query == 'qualification' else (sample_result(2),)
    with pytest.raises(RuntimeError, match='lacks tpmshx_result_stage_query_v3'):
        function(*arguments)


@pytest.mark.parametrize('value', [42, [], None])
@pytest.mark.parametrize('query', ['qualification', 'evaluate'])
def test_unrelated_model_certificate_does_not_stop_a_conservative_query(value, query):
    result = result_fixture(2)
    metadata = mutable_data(result.metadata)
    metadata['diagnostics']['model_h_balance'] = value
    result = replace(result, metadata=metadata)
    if query == 'qualification':
        assert_observation(observe(lambda: api.evaluate_qualification(result, {})),
                           observe(lambda: reference.evaluate_qualification(result, {})))
    else:
        compare(result, query, MetricSpec('Q', 'W/m', 'native_boundary_v1'))


# Each raw gate value reaches the comparison. An ambiguous array after each earlier
# false gate must not be evaluated.
@pytest.mark.parametrize('value,earlier_false', [
    *[(value, 'none') for value in ((True, False), (), np.array([True]), np.array([False]),
                                    np.array([True, False]), np.array([], dtype=bool))],
    *[(np.array([True, False]), earlier_false) for earlier_false in ('run', 'field', 'gate')],
])
def test_gate_comparison_keeps_raw_values_and_short_circuit_order(value, earlier_false):
    result = qualified_result()
    metadata = mutable_data(result.metadata)
    detail = metadata['diagnostics']['convergence_detail']
    detail['ltne_ok'] = value
    if earlier_false == 'gate':
        detail['simple_ok'] = False
    result = replace(result, metadata=metadata)
    if earlier_false == 'run':
        result = replace(result, run_status=dict(result.run_status, converged=False))
    elif earlier_false == 'field':
        fields = mutable_data(result.fields)
        fields['Ta'][0, 0, 0] = np.nan
        result = replace(result, fields=fields)
    metrics = required_metrics()
    assert_observation(observe(lambda: api.evaluate_qualification(result, metrics)),
                       observe(lambda: reference.evaluate_qualification(result, metrics)))


@pytest.mark.parametrize('detail,expected', [
    ({'additional_gate': True, 'envelope_ok': False, 'simple_ok': True},
     [('simple_ok', True), ('envelope_ok', False)]),
    ({'additional_gate': False}, []),
])
def test_qualification_uses_present_saved_gates_in_contract_order(detail, expected, monkeypatch):
    result = qualified_result()
    metadata = mutable_data(result.metadata)
    metadata['diagnostics']['convergence_detail'] = detail
    result = replace(result, metadata=metadata)
    sent = []
    sequence = stage._Packed.sequence

    def record_gates(packed, kind, values):
        if kind is stage.Gate:
            sent.append([gate.name.decode('utf-8') for gate in values])
        return sequence(packed, kind, values)

    monkeypatch.setattr(stage._Packed, 'sequence', record_gates)
    convergence = api.evaluate_qualification(result, required_metrics())['convergence']
    assert sent == [[name for name, _ in expected]]
    assert list(convergence['gates'].items()) == expected


@pytest.mark.parametrize('where,value', [
    ('converged', (True, False)), ('converged', np.array([False])),
    ('air_solved', np.array([True])), ('air_solved', np.array([True, False])),
    ('sco2_solved', (True, False)), ('sco2_solved', np.array([False]))])
def test_nonboolean_run_and_execution_flags_keep_their_consumption_point(value, where):
    result = qualified_result()
    if where == 'converged':
        result = replace(result, run_status=dict(result.run_status, converged=value))
    else:
        metadata = mutable_data(result.metadata)
        metadata['execution_record']['sides']['A'].update(solved=value,
            fluid='sco2' if where == 'sco2_solved' else 'air')
        result = replace(result, metadata=metadata)
    metrics = required_metrics()
    assert_observation(observe(lambda: api.evaluate_qualification(result, metrics)),
                       observe(lambda: reference.evaluate_qualification(result, metrics)))


def complete_two_dimensional_model_result():
    result = qualified_result(2)
    metadata, flux = mutable_data(result.metadata), mutable_data(result.boundary_fluxes)
    metadata['diagnostics']['model_h_balance'] = {
        level: dict(passed=True, A=dict(physical_boundary_complete=True),
                    B=dict(physical_boundary_complete=True)) for level in ('main', 'fine')}
    metadata['diagnostics']['convergence_detail']['richardson_ok'] = True
    flux['fine'] = dict(energy=mutable_data(flux['energy']),
        dx=result.grid['dx'], dy=result.grid['dy'],
        **{name: result.fields[name] for name in ('Ta', 'Tb', 'Ts')})
    return replace(result, metadata=metadata, boundary_fluxes=flux)


@pytest.mark.parametrize('damage', ['missing', 'none', 'empty', 'passed', 'B', 'boundary',
                                    'passed_none', 'passed_false', 'boundary_none', 'boundary_false'])
def test_model_certificate_absence_does_not_become_a_physical_failure(damage):
    result = complete_two_dimensional_model_result()
    metadata = mutable_data(result.metadata)
    diagnostics = metadata['diagnostics']
    model = diagnostics['model_h_balance']
    if damage == 'missing':
        diagnostics.pop('model_h_balance')
    elif damage in ('none', 'empty'):
        diagnostics['model_h_balance'] = None if damage == 'none' else {}
    elif damage in ('passed', 'B'):
        model['main'].pop(damage)
    elif damage == 'boundary':
        model['main']['B'].pop('physical_boundary_complete')
    elif damage.startswith('passed_'):
        model['main']['passed'] = None if damage.endswith('none') else False
    else:
        model['main']['B']['physical_boundary_complete'] = None if damage.endswith('none') else False
    result = replace(result, metadata=metadata)
    metrics = required_metrics(2)
    assert_observation(observe(lambda: api.evaluate_qualification(result, metrics)),
                       observe(lambda: reference.evaluate_qualification(result, metrics)))


@pytest.mark.parametrize('key', ['enthalpy_clip_counts', 'converged', 'coupled_energy_balance',
                                'equation_energy_balance', 'effective_settings'])
def test_true_h_certificate_preserves_the_first_missing_key(key):
    result = result_fixture(3)
    metadata = mutable_data(result.metadata)
    metadata['diagnostics']['true_h_balance'] = dict(
        enthalpy_clip_counts=dict(total=np.zeros(2)), converged=True,
        coupled_energy_balance=dict(ratio=0.), equation_energy_balance=dict(ratio=0.),
        effective_settings=dict(coupled_energy_tol=.01, equation_energy_tol=.01))
    metadata['diagnostics']['true_h_balance'].pop(key)
    result = replace(result, metadata=metadata)
    assert_observation(observe(lambda: api.evaluate_qualification(result, {})),
                       observe(lambda: reference.evaluate_qualification(result, {})))


def test_host_calls_keep_their_signature_after_an_independent_c_wire_call():
    from tests.python.result_stage_fixture import native_report
    result = result_fixture(3)
    expected = performance(reference.evaluate(result))
    assert_values(performance(api.evaluate(result)), expected)
    native_report(result, core.result_library.get().library)
    assert_values(performance(api.evaluate(result)), expected)


# Every version type runs in full mode. The current version runs with each invalid
# sides record and in quick-design mode.
@pytest.mark.parametrize('mode,version,sides', [
    *[('full', version, None) for version in
      (None, 4, False, (), {'key': 1}, 'historical', 'full_execution_v1')],
    ('full', 'full_execution_v1', ()), ('full', 'full_execution_v1', 4),
    ('quick_design', 'full_execution_v1', ()), ('quick_design', None, 4)])
def test_raw_execution_label_keeps_native_selection(mode, version, sides):
    result = sample_result(2)
    result = replace(result, metadata={**result.metadata, 'mode': mode,
        'execution_record': {'version': version, 'sides': sides}})
    expected = observe(lambda: reference.evaluate_qualification(result, {}))
    actual = observe(lambda: api.evaluate_qualification(result, {}))
    assert_observation(actual, expected)


@pytest.fixture
def without_cyclic_collection():
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


def _lifetime_result(kind):
    return quick_result() if kind == 'quick' else result_fixture(kind)


@pytest.mark.parametrize('kind', [2, 3, 'quick'])
@pytest.mark.parametrize('query', ['evaluate', 'applicability', 'physical_balance', 'qualification'])
def test_query_releases_borrowed_fields_without_collection(without_cyclic_collection, kind, query):
    field = _lifetime_result(kind)
    references = weakref.ref(field), weakref.ref(field.fields['Ta'])
    function = getattr(api, 'evaluate' if query == 'evaluate' else 'evaluate_' + query)
    report = function(field, {}) if query == 'qualification' else function(field)
    del field
    assert report is not None
    assert all(reference() is None for reference in references)


@pytest.mark.parametrize('status', [b'available', b'invalid-status'])
def test_public_report_owns_native_metric_and_text_buffers(monkeypatch, status):
    import ctypes as ct
    from types import SimpleNamespace
    from tm1.cpp_interface._native_result_stage import Metric, Spec

    report = (b'{"qualification":{"definition":"result_qualification_v1","source_result_id":"saved-2d",'
              b'"convergence":{"gates":{}},"execution":{},'
              b'"physical":{},"applicability":{},"label":"original"}}')
    buffers = [ct.create_string_buffer(text) for text in
               (b'dP_A', b'dP', b'Pa', b'pressure_face_v1', b'pressure change', status, b'captured', report)]
    name, kind, unit, version, description, state, reason, encoded = [
        ct.cast(buffer, ct.c_char_p) for buffer in buffers]
    metrics = (Metric * 1)(Metric(name, Spec(kind, unit, version, description), 1, -0.0, state, reason))
    releases = []

    def query(inputs, mode, selected, supplied, count, output, *diagnostics):
        owner = output._obj
        owner.owner, owner.json = 1, encoded
        owner.metrics, owner.metric_count = metrics, 1
        return 0

    def release(output):
        releases.append(output._obj.owner)
        for buffer in buffers:
            buffer.value = b'x'
        metrics[0].value = 42.
        output._obj.owner = None

    functions = {'tpmshx_result_stage_query_v3': query, 'tpmshx_result_stage_release_v1': release}
    library = SimpleNamespace(bind=lambda name, *signature: functions[name])
    monkeypatch.setattr(core.result_library, 'get', lambda: library)
    field = replace(result_fixture(2), result_id='saved-2d')
    if status == b'available':
        performance = api.evaluate(field)
        metric = performance.metrics['dP_A']
        assert metric.spec == MetricSpec('dP', 'Pa', 'pressure_face_v1', 'pressure change')
        assert metric.status == 'available' and metric.reason == 'captured'
        assert metric.value == 0. and np.signbit(metric.value)
        assert performance.qualification['label'] == 'original'
    else:
        with pytest.raises(ValueError, match='unsupported metric status: invalid-status'):
            api.evaluate(field)
    assert releases == [1]


@pytest.mark.parametrize('kind', [3, 'quick'])
@pytest.mark.parametrize('missing', ['library', 'query', 'release'])
def test_binding_failure_releases_borrowed_fields(without_cyclic_collection, monkeypatch, kind, missing):
    library = core.result_library.get()

    class MissingSymbol:
        def bind(self, name, *arguments):
            if missing in name:
                raise RuntimeError('missing ' + missing)
            return library.bind(name, *arguments)

    def load():
        if missing == 'library':
            raise RuntimeError('missing library')
        return MissingSymbol()

    monkeypatch.setattr(core.result_library, 'get', load)

    def exercise():
        field = _lifetime_result(kind)
        references = weakref.ref(field), weakref.ref(field.fields['Ta'])
        try:
            api.evaluate(field)
        except RuntimeError as error:
            assert str(error) == 'missing ' + missing
        else:
            pytest.fail('the selected binding must fail')
        return references

    assert all(reference() is None for reference in exercise())


@pytest.mark.parametrize('kind', [3, 'quick'])
def test_native_failure_releases_borrowed_fields(without_cyclic_collection, kind):
    def exercise():
        field = _lifetime_result(kind)
        field = replace(field, metadata=dict(field.metadata, mode='unsupported mode'))
        references = weakref.ref(field), weakref.ref(field.fields['Ta'])
        try:
            api.evaluate(field)
        except ValueError as error:
            assert 'unsupported mode' in str(error)
        else:
            pytest.fail('the native stage must reject the mode')
        return references

    assert all(reference() is None for reference in exercise())


# Each result kind, invalid field, query, and failure point appears in more than one case.
@pytest.mark.parametrize('kind,invalid_field,query,packing_failure', [
    (2, None, 'evaluate', False), (2, ('bad',), 'qualification', True),
    (3, ('bad',), 'qualification', False), (3, None, 'evaluate', True),
    ('quick', None, 'qualification', True), ('quick', ('bad',), 'evaluate', False)])
def test_chained_input_error_releases_fields(without_cyclic_collection, kind, invalid_field, query, packing_failure):
    def exercise():
        field = _lifetime_result(kind)
        metadata = dict(field.metadata)
        if packing_failure:
            metadata['diagnostics'] = dict(richardson_info=dict(extrapolated=np.ones(2)))
        field = replace(field, fields=dict(field.fields, Ta=invalid_field), metadata=metadata)
        references = weakref.ref(field), weakref.ref(field.fields['Tb'])
        function = api.evaluate if query == 'evaluate' else api.evaluate_qualification
        arguments = (field,) if query == 'evaluate' else (field, {})
        try:
            function(*arguments)
        except (TypeError, ValueError) as error:
            assert type(error) is (ValueError if packing_failure else TypeError)
        else:
            pytest.fail('invalid input must raise at its original boundary')
        return references

    assert all(reference() is None for reference in exercise())


def test_deferred_exception_relations_keep_cycles_and_group_identity():
    first = OSError(7, 'first')
    second = ValueError('second')
    group = ExceptionGroup('recorded group', [first, second])
    first.__cause__, first.__context__ = second, group
    second.__context__ = first
    from tm1.cpp_interface._native_result_stage import _Packed
    packed = _Packed()
    token = packed.token(group)
    assert packed.exceptions[token] is group
    assert group.exceptions == (first, second)
    assert first.__cause__ is second and first.__context__ is group
    assert second.__context__ is first
    assert first.errno == 7 and first.args == (7, 'first')
    assert second.args == ('second',)
