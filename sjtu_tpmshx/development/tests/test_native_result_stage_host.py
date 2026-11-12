"""Check the production stage boundary against independent result references."""
from collections.abc import Mapping
from dataclasses import replace
import gc
import os
from pathlib import Path
import weakref

import numpy as np
import pytest

from sjtu_tpmshx.shared import _native_result_stage as native
from sjtu_tpmshx.shared.domain.metric_spec import MetricSpec
from sjtu_tpmshx.shared.domain.portable_data import mutable_data
from sjtu_tpmshx.shared.io.result_io import load_result
from sjtu_tpmshx.development.tests.native.result_reference import api as reference
from sjtu_tpmshx.development.tests.native.test_result_metrics import quick_result
from sjtu_tpmshx.development.tests.test_native_result_balance import assert_values, observe, assert_observation
from sjtu_tpmshx.development.tests.test_conservative_energy_results import result_fixture
from sjtu_tpmshx.development.tests.test_temperature_face_results import temperature_fixture
from sjtu_tpmshx.development.tests.postprocess_tm1.test_physical_balance import sample_result
from sjtu_tpmshx.development.tests.postprocess_tm1.test_qualification import qualified_result, required_metrics


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
        actual = observe(lambda: performance(native.evaluate(result, request)))
        expected = observe(lambda: performance(reference.evaluate(result, request)))
    elif query == 'qualification':
        metrics = reference.evaluate(result).metrics
        actual = observe(lambda: native.evaluate_qualification(result, metrics))
        expected = observe(lambda: reference.evaluate_qualification(result, metrics))
    else:
        actual = observe(lambda: getattr(native, 'evaluate_' + query)(result))
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
    actual = native.evaluate(result, request)
    assert actual.metrics['Q'].spec is request


def test_applicability_does_not_touch_unrelated_numeric_protocols():
    result = result_fixture(3)
    metadata = mutable_data(result.metadata)
    metadata.update(solid_density_kg_m3=2**1100, diagnostics=None, parameters=None)
    compare(replace(result, metadata=metadata), 'applicability')


@pytest.mark.parametrize('exception_type', [ValueError, TypeError, IndexError, NotImplementedError, FloatingPointError])
def test_policy_callback_consumption_and_exception_identity(exception_type):
    result = result_fixture(3)
    pressure = mutable_data(result.pressure_evidence)
    pressure['A'].update(P=np.full((2, 2, 2), np.finfo(float).max),
        dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
        inlet_frac=np.ones((2, 2)), outlet_frac=np.ones((2, 2)))
    result = replace(result, pressure_evidence=pressure)
    request = MetricSpec('dP', 'Pa', 'pressure_face_v1')
    exception = exception_type('test policy callback')

    def observed(evaluator):
        calls = []
        def callback(label, flags):
            calls.append((label, flags))
            raise exception
        handler = np.geterrcall()
        try:
            np.seterrcall(callback)
            with np.errstate(all='call'):
                try:
                    return 'value', performance(evaluator(result, request)), calls
                except BaseException as error:
                    assert error is exception
                    return 'error', type(error), error.args, calls
        finally:
            np.seterrcall(handler)

    actual, expected = observed(native.evaluate), observed(reference.evaluate)
    assert expected[-1], 'the independent pressure formula must reach the callback'
    assert_values(actual, expected)


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
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('density_shape', [(), (2, 1), (1, 2), (2, 2)])
def test_full_mass_keeps_density_array_arithmetic(dimension, dtype, density_shape):
    shape = (2,) * dimension
    density_shape = density_shape + ((1,) if dimension == 3 and density_shape else ())
    result = result_fixture(dimension)
    metadata = mutable_data(result.metadata)
    metadata.update(solid_density_kg_m3=np.full(density_shape, 3, dtype=dtype),
                    design_fields=dict(eps_arr=np.full(shape, .25, dtype=np.float32)))
    result = replace(result, metadata=metadata)
    compare(result, 'evaluate', MetricSpec('mass', 'kg/m' if dimension == 2 else 'kg'))


def legacy_temperature_result(dtype=np.float32):
    result = result_fixture(2)
    fields = dict(Ta=np.array([[390., 380.], [330., 320.]], dtype=dtype),
        Tb=np.array([[300., 310.], [340., 350.]], dtype=dtype), Ts=np.full((2, 2), 350., dtype=dtype),
        ucA=np.ones((2, 2), dtype=dtype), ucB=np.ones((2, 2), dtype=dtype),
        vcA=np.zeros((2, 2), dtype=dtype), vcB=np.zeros((2, 2), dtype=dtype))
    metadata = mutable_data(result.metadata)
    metadata.update(thermal_mode='temperature', split_A=.4, rho_cp_A=np.full((2, 2), 2., dtype=dtype),
                    rho_cp_B=np.full((2, 2), 3., dtype=dtype))
    metadata.pop('temperature_transport', None)
    metadata['parameters'].update(eps=np.full((2, 2), .5, dtype=dtype), T_inA=400., T_inB=300., dir_A=0, dir_B=0)
    flux = mutable_data(result.boundary_fluxes)
    for name in ('true_h', 'temperature', 'energy', 'fine'):
        flux.pop(name, None)
    pressure = {side: dict(inlet_fraction=np.ones(2, dtype=dtype), outlet_fraction=np.ones(2, dtype=dtype),
                          outlet_geom_frac=np.ones(2, dtype=dtype)) for side in 'AB'}
    return replace(result, fields=fields, metadata=metadata, boundary_fluxes=flux, pressure_evidence=pressure)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('split_shape', [(), (2, 2)])
@pytest.mark.parametrize('inlet_shape', [None, (), (2,)])
def test_legacy_temperature_typed_inputs(dtype, split_shape, inlet_shape):
    result = legacy_temperature_result(dtype)
    metadata = mutable_data(result.metadata)
    metadata['split_A'] = np.full(split_shape, .4, dtype=dtype)
    metadata['parameters']['T_inA'] = None if inlet_shape is None else np.full(inlet_shape, 400., dtype=dtype)
    metadata['parameters']['T_inB'] = None if inlet_shape is None else np.full(inlet_shape, 300., dtype=dtype)
    result = replace(result, metadata=metadata)
    compare(result, 'evaluate', MetricSpec('Q_A', 'W/m', 'native_boundary_v1'))
    compare(result, 'evaluate', MetricSpec('Q_B', 'W/m', 'native_boundary_v1'))


@pytest.mark.parametrize('dimension', [None, 2., 3., 7, '2'])
@pytest.mark.parametrize('mode', ['full', None, 1])
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
    from sjtu_tpmshx.development.tests.postprocess_tm1.test_applicability import result_with_evidence
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
        assert_observation(observe(lambda: native.evaluate_qualification(result, {})),
                           observe(lambda: reference.evaluate_qualification(result, {})))
    else:
        compare(result, query)


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
    from sjtu_tpmshx.development.tests.test_native_result_loader import LibraryStub
    from sjtu_tpmshx.shared import _native_result as core
    handle = LibraryStub(tpmshx_result_abi_version_v1=lambda: 2)
    monkeypatch.setattr(core.ct, 'CDLL', lambda _: handle)
    library = core._Library('historical-result-image')
    monkeypatch.setattr(core, '_library', lambda: library)
    function = getattr(native, 'evaluate' if query == 'evaluate' else 'evaluate_' + query)
    arguments = (sample_result(2), {}) if query == 'qualification' else (sample_result(2),)
    version = 3 if query in ('evaluate', 'qualification') else 2
    with pytest.raises(RuntimeError, match=f'lacks tpmshx_result_stage_query_v{version}'):
        function(*arguments)


def test_nested_qualification_error_follows_metric_callback():
    result = result_fixture(3)
    pressure = mutable_data(result.pressure_evidence)
    pressure['A'].update(P=np.full((2, 2, 2), np.finfo(float).max),
        dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
        inlet_frac=np.ones((2, 2)), outlet_frac=np.ones((2, 2)))
    result = replace(result, pressure_evidence=pressure, metadata=dict(result.metadata, diagnostics=None))
    request = MetricSpec('dP', 'Pa', 'pressure_face_v1')

    def run(evaluate):
        events = []
        previous = np.geterrcall()
        np.seterrcall(lambda message, flag: events.append((message, flag)))
        try:
            with np.errstate(over='call', invalid='ignore'):
                try:
                    evaluate(result, request)
                except AttributeError as error:
                    return events, error.args
                pytest.fail('missing diagnostics must keep its original error')
        finally:
            np.seterrcall(previous)

    actual = run(native.evaluate)
    assert actual[0]
    assert actual == run(reference.evaluate)


@pytest.mark.parametrize('value', [42, [], None])
@pytest.mark.parametrize('query', ['qualification', 'evaluate'])
def test_unrelated_model_certificate_does_not_stop_a_conservative_query(value, query):
    result = result_fixture(2)
    metadata = mutable_data(result.metadata)
    metadata['diagnostics']['model_h_balance'] = value
    result = replace(result, metadata=metadata)
    if query == 'qualification':
        assert_observation(observe(lambda: native.evaluate_qualification(result, {})),
                           observe(lambda: reference.evaluate_qualification(result, {})))
    else:
        compare(result, query, MetricSpec('Q', 'W/m', 'native_boundary_v1'))


@pytest.mark.parametrize('value', [(True, False), (), np.array([True]), np.array([False]),
                                  np.array([True, False]), np.array([], dtype=bool)])
@pytest.mark.parametrize('earlier_false', ['none', 'run', 'field', 'gate'])
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
    assert_observation(observe(lambda: native.evaluate_qualification(result, metrics)),
                       observe(lambda: reference.evaluate_qualification(result, metrics)))


@pytest.mark.parametrize('value', [(True, False), np.array([True]), np.array([False]), np.array([True, False])])
@pytest.mark.parametrize('where', ['converged', 'air_solved', 'sco2_solved'])
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
    assert_observation(observe(lambda: native.evaluate_qualification(result, metrics)),
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
    assert_observation(observe(lambda: native.evaluate_qualification(result, metrics)),
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
    assert_observation(observe(lambda: native.evaluate_qualification(result, {})),
                       observe(lambda: reference.evaluate_qualification(result, {})))


@pytest.mark.parametrize('damage', ['model', 'gate'])
def test_metric_callback_precedes_delayed_qualification_inputs(damage):
    result = result_fixture(3)
    metadata = mutable_data(result.metadata)
    if damage == 'model':
        metadata['diagnostics']['model_h_balance'] = 42
    else:
        metadata['diagnostics'].setdefault('convergence_detail', {})['simple_ok'] = np.array([True, False])
    pressure = mutable_data(result.pressure_evidence)
    pressure['A'].update(P=np.full((2, 2, 2), np.finfo(float).max),
        dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
        inlet_frac=np.ones((2, 2)), outlet_frac=np.ones((2, 2)))
    result = replace(result, metadata=metadata, pressure_evidence=pressure)
    request = MetricSpec('dP', 'Pa', 'pressure_face_v1')
    exception = FloatingPointError('metric callback before qualification')
    handler = np.geterrcall()
    try:
        def callback(label, flags):
            raise exception
        np.seterrcall(callback)
        with np.errstate(all='call'):
            for evaluate in (reference.evaluate, native.evaluate):
                with pytest.raises(FloatingPointError) as caught:
                    evaluate(result, request)
                assert caught.value is exception
    finally:
        np.seterrcall(handler)



def test_host_calls_keep_their_signature_after_an_independent_c_wire_call():
    from sjtu_tpmshx.development.tests.result_stage_fixture import native_report
    result = result_fixture(3)
    expected = performance(reference.evaluate(result))
    assert_values(performance(native.evaluate(result)), expected)
    native_report(result, native.core._library().library)
    assert_values(performance(native.evaluate(result)), expected)


@pytest.mark.parametrize('mode', ['full', 'quick_design'])
@pytest.mark.parametrize('version', [None, 4, False, (), {'key': 1}, np.asarray(1),
    np.asarray([1]), np.asarray([]), np.asarray([1, 2]), 'historical', 'full_execution_v1',
    'full_execution_v1\0extra', '\0', '\ud800', 'full_execution_v1\ud800'])
@pytest.mark.parametrize('sides', [None, (), 4])
def test_raw_execution_label_keeps_native_selection_and_host_equality(mode, version, sides):
    result = sample_result(2)
    result = replace(result, metadata={**result.metadata, 'mode': mode,
        'execution_record': {'version': version, 'sides': sides}})
    expected = observe(lambda: reference.evaluate_qualification(result, {}))
    actual = observe(lambda: native.evaluate_qualification(result, {}))
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
    function = getattr(native, 'evaluate' if query == 'evaluate' else 'evaluate_' + query)
    report = function(field, {}) if query == 'qualification' else function(field)
    del field
    assert report is not None
    assert all(reference() is None for reference in references)


@pytest.mark.parametrize('kind', [3, 'quick'])
@pytest.mark.parametrize('missing', ['library', 'query', 'release'])
def test_binding_failure_releases_borrowed_fields(without_cyclic_collection, monkeypatch, kind, missing):
    from sjtu_tpmshx.shared import _native_result as core
    library = core._library()

    class MissingSymbol:
        def bind(self, name, *arguments):
            if missing in name:
                raise RuntimeError('missing ' + missing)
            return library.bind(name, *arguments)

    def load():
        if missing == 'library':
            raise RuntimeError('missing library')
        return MissingSymbol()

    monkeypatch.setattr(core, '_library', load)

    def exercise():
        field = _lifetime_result(kind)
        references = weakref.ref(field), weakref.ref(field.fields['Ta'])
        try:
            native.evaluate(field)
        except RuntimeError as error:
            assert str(error) == 'missing ' + missing
        else:
            pytest.fail('the selected binding must fail')
        return references

    assert all(reference() is None for reference in exercise())


@pytest.mark.parametrize('kind', [3, 'quick'])
@pytest.mark.parametrize('exception_type', [ValueError, RuntimeError])
def test_callback_failure_releases_borrowed_fields(without_cyclic_collection, kind, exception_type):
    def exercise():
        if kind == 'quick':
            class Label(str):
                def __ne__(self, other):
                    raise exception_type('query callback')
            field = quick_result()
            field = replace(field, metadata=dict(field.metadata, model=Label('model')))
            request = MetricSpec('Q', 'W', 'three_module_v1')
        else:
            field = result_fixture(3)
            pressure = mutable_data(field.pressure_evidence)
            pressure['A'].update(P=np.full((2, 2, 2), np.finfo(float).max),
                dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
                inlet_frac=np.ones((2, 2)), outlet_frac=np.ones((2, 2)))
            field = replace(field, pressure_evidence=pressure)
            request = MetricSpec('dP', 'Pa', 'pressure_face_v1')

        def callback(label, flags):
            raise exception_type('query callback')

        references = weakref.ref(field), weakref.ref(field.fields['Ta'])
        previous = np.geterrcall()
        np.seterrcall(callback)
        try:
            with np.errstate(all='call'):
                try:
                    report = native.evaluate(field, request)
                except RuntimeError as error:
                    assert exception_type is RuntimeError
                    assert str(error) == 'query callback'
                else:
                    assert exception_type is ValueError
                    assert 'invalid' in {row.status for row in report.metrics.values()}
        finally:
            np.seterrcall(previous)
        return references

    assert all(reference() is None for reference in exercise())


def test_deferred_callback_error_keeps_identity_and_exception_chain():
    cause = LookupError('original cause')
    context = ValueError('original context')
    failure = OSError(5, 'original callback')
    failure.__cause__, failure.__context__ = cause, context

    class Label(str):
        def __ne__(self, other):
            raise failure

    field = quick_result()
    field = replace(field, metadata=dict(field.metadata, model=Label('model')))
    with pytest.raises(OSError) as caught:
        native.evaluate(field)
    assert caught.value is failure
    assert failure.errno == 5 and failure.args == (5, 'original callback')
    assert failure.__cause__ is cause and failure.__context__ is context


@pytest.mark.parametrize('kind', [3, 'quick'])
def test_native_failure_releases_borrowed_fields(without_cyclic_collection, kind):
    def exercise():
        field = _lifetime_result(kind)
        field = replace(field, metadata=dict(field.metadata, mode='unsupported mode'))
        references = weakref.ref(field), weakref.ref(field.fields['Ta'])
        try:
            native.evaluate(field)
        except ValueError as error:
            assert 'unsupported mode' in str(error)
        else:
            pytest.fail('the native stage must reject the mode')
        return references

    assert all(reference() is None for reference in exercise())


@pytest.mark.parametrize('kind', [2, 3, 'quick'])
@pytest.mark.parametrize('invalid_field', [None, ('bad',)])
@pytest.mark.parametrize('query', ['evaluate', 'qualification'])
@pytest.mark.parametrize('packing_failure', [False, True])
def test_chained_input_error_releases_fields(without_cyclic_collection, kind, invalid_field, query, packing_failure):
    def exercise():
        field = _lifetime_result(kind)
        metadata = dict(field.metadata)
        if packing_failure:
            metadata['diagnostics'] = dict(richardson_info=dict(extrapolated=np.ones(2)))
        field = replace(field, fields=dict(field.fields, Ta=invalid_field), metadata=metadata)
        references = weakref.ref(field), weakref.ref(field.fields['Tb'])
        function = native.evaluate if query == 'evaluate' else native.evaluate_qualification
        arguments = (field,) if query == 'evaluate' else (field, {})
        try:
            function(*arguments)
        except (TypeError, ValueError) as error:
            assert type(error) is (ValueError if packing_failure else TypeError)
        else:
            pytest.fail('invalid input must raise at its original boundary')
        return references

    assert all(reference() is None for reference in exercise())


@pytest.mark.parametrize('kind', [3, 'quick'])
@pytest.mark.parametrize('exception_type', [ValueError, RuntimeError, ExceptionGroup])
def test_chained_callback_error_releases_fields(without_cyclic_collection, kind, exception_type):
    def fail():
        members = []
        try:
            raise OSError(7, 'callback source')
        except OSError as cause:
            if exception_type is ExceptionGroup:
                members.append(cause)
            else:
                raise exception_type('query callback') from cause
        raise ExceptionGroup('query callback', members)

    def exercise():
        if kind == 'quick':
            class Label(str):
                def __ne__(self, other):
                    fail()
            field = quick_result()
            field = replace(field, metadata=dict(field.metadata, model=Label('model')))
            request = MetricSpec('Q', 'W', 'three_module_v1')
        else:
            field = result_fixture(3)
            pressure = mutable_data(field.pressure_evidence)
            pressure['A'].update(P=np.full((2, 2, 2), np.finfo(float).max),
                dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
                inlet_frac=np.ones((2, 2)), outlet_frac=np.ones((2, 2)))
            field = replace(field, pressure_evidence=pressure)
            request = MetricSpec('dP', 'Pa', 'pressure_face_v1')
        references = weakref.ref(field), weakref.ref(field.fields['Ta'])
        previous = np.geterrcall()
        np.seterrcall(lambda label, flags: fail())
        try:
            with np.errstate(all='call'):
                try:
                    report = native.evaluate(field, request)
                except (RuntimeError, ExceptionGroup) as error:
                    assert type(error) is exception_type
                    if isinstance(error, ExceptionGroup):
                        assert error.__cause__ is None and error.__context__ is None
                        assert len(error.exceptions) == 1 and error.exceptions[0].errno == 7
                    else:
                        assert error.__cause__ is error.__context__
                        assert error.__cause__.errno == 7
                else:
                    assert exception_type is ValueError
                    assert 'invalid' in {row.status for row in report.metrics.values()}
        finally:
            np.seterrcall(previous)
        return references

    assert all(reference() is None for reference in exercise())


def test_deferred_exception_relations_keep_cycles_and_group_identity():
    first = OSError(7, 'first')
    second = ValueError('second')
    group = ExceptionGroup('recorded group', [first, second])
    first.__cause__, first.__context__ = second, group
    second.__context__ = first
    packed = native._Packed()
    token = packed.token(group)
    assert packed.exceptions[token] is group
    assert group.exceptions == (first, second)
    assert first.__cause__ is second and first.__context__ is group
    assert second.__context__ is first
    assert first.errno == 7 and first.args == (7, 'first')
    assert second.args == ('second',)


@pytest.mark.parametrize('base', [RuntimeError, ExceptionGroup])
def test_exception_cleanup_does_not_call_subclass_accessors(base):
    lookups = []

    class Failure(base):
        def __getattribute__(self, name):
            if name in ('__cause__', '__context__', 'exceptions'):
                lookups.append(name)
                raise AssertionError('unexpected exception accessor')
            return super().__getattribute__(name)

    cause = OSError(7, 'original cause')
    context = ValueError('original context')
    failure = Failure('original', [cause]) if base is ExceptionGroup else Failure('original')
    failure.__cause__, failure.__context__ = cause, context

    class Label(str):
        def __ne__(self, other):
            raise failure

    field = quick_result()
    field = replace(field, metadata=dict(field.metadata, model=Label('model')))
    with pytest.raises(Failure) as caught:
        native.evaluate(field)
    assert caught.value is failure and lookups == []
    assert BaseException.__cause__.__get__(failure) is cause
    assert BaseException.__context__.__get__(failure) is context
    if base is ExceptionGroup:
        assert BaseExceptionGroup.exceptions.__get__(failure) == (cause,)
