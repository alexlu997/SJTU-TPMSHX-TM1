"""Compare native capture scalars with the public 2D result of the same saved stage run."""
import ctypes as ct
from dataclasses import replace
import json
import math

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface import full_2d_stage
from sjtu_tpmshx.file_io.result_io import save_result
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
from tests.python import native_stage_support
from tests.python.native.shared_library import library_path
from tests.python.result_stage_fixture import record

_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Application = record('CaptureApplication', [
    ('area_density_per_m', _D * 2), ('surface_htc_W_m2K', _D * 2)])
_Summary = record('CaptureSummary', [
    ('model_h_available', _U * 2), ('nu_available', _U * 2), ('pressure_available', _U),
    ('model_h_cell_count', _Z * 2),
    *((name, _D * 2) for name in ('model_h_area_m2', 'nu_floor', 'nu_floor_fraction',
        'pressure_min_Pa', 'pressure_max_Pa')),
    ('q_net', _D), ('absolute_duty', _D * 2), ('application_hv', _D * 2),
    ('pressure_clip_hits', _Z), ('have_finite_duty', _U), ('red_black', _U * 2)])


@pytest.fixture(scope='module')
def capture_query():
    # A separate handle keeps these argument types away from the production binding.
    query = ct.CDLL(str(library_path())).tpmshx_stage_run_2d_get_capture_v1
    query.argtypes = [ct.c_void_p, ct.POINTER(_Application), ct.POINTER(_Summary)]
    query.restype = ct.c_int
    return query


def _control():
    return RunControl(cpu_threads=2, native_library=str(library_path()))


def _live_result(monkeypatch, case, inspect):
    """Run the saved v5 stage and inspect its native result before the release."""
    original, results = full_2d_stage.executed_view, []
    def observe(query, result):
        results.append(result)
        inspect(result)
        return original(query, result)
    monkeypatch.setattr(full_2d_stage, 'executed_view', observe)
    public = run_case(case, _control())
    assert len(results) == 1
    return public, results[0]


def _application(case):
    properties = case.parameters['static_properties']
    return _Application((_D * 2)(*(properties[side]['A_0'] for side in 'AB')),
        (_D * 2)(*(properties[side]['H_sf'] for side in 'AB')))


def _bits(actual, expected):
    assert type(actual) is type(expected) is float
    np.testing.assert_array_equal(np.array(actual).view(np.uint64), np.array(expected).view(np.uint64))


def _summary_record(summary):
    return {name: list(value) if isinstance(value := getattr(summary, name), ct.Array) else value
            for name, _ in summary._fields_}


@pytest.mark.parametrize('spatial,pair', [
    (False, ('air', 'water')), (True, ('air', 'water')),
    (False, ('water', 'sco2')), (True, ('water', 'sco2')),
    (False, ('co2', 'air')), (True, ('co2', 'air'))])
def test_capture_matches_public_result(capture_query, monkeypatch, spatial, pair, tmp_path):
    config = (native_stage_support.continuous_plane_configuration(pair) if spatial
              else native_stage_support.plane_configuration(pair))
    native_stage_support.bound_plane_controls(config)
    if pair == ('air', 'water'):
        config.solver.Nx = config.solver.Ny = 12
        config.bc_A.dir, config.bc_B.dir = 1, 2
        config.bc_A.in_ctr, config.bc_A.in_w = .012, .012
        config.bc_A.out_ctr, config.bc_A.out_w = .028, .016
        config.bc_B.in_ctr, config.bc_B.in_w = .045, .04
        config.bc_B.out_ctr, config.bc_B.out_w = .13, .06
    if pair == ('water', 'sco2'):
        config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
            parameter_version='capture-comparison', source='existing experimental selection',
            applicability='existing geometry')
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    case = prepare_case(config, case_id='capture-stage')
    application = _application(case)
    changed = _Application.from_buffer_copy(application)
    changed.area_density_per_m[0] *= 1.125
    summary, altered, native_fields = _Summary(), _Summary(), {}

    def inspect(result):
        assert capture_query(ct.addressof(result), ct.byref(application), ct.byref(summary)) == 0
        # Saved application inputs do not replace the solver's thermal geometry.
        assert capture_query(ct.addressof(result), ct.byref(changed), ct.byref(altered)) == 0
        for index in range(result.evidence.field_count):
            field = result.evidence.fields[index]
            value = field.value
            values = np.ctypeslib.as_array(ct.cast(value.data, ct.POINTER(_D)),
                shape=(value.shape[0] * value.shape[1],)).reshape(value.shape[0], value.shape[1])
            native_fields[field.name.decode()] = values.copy()

    expected, _ = _live_result(monkeypatch, case, inspect)
    diagnostics = expected.metadata['diagnostics']
    for name, wanted in [('q_net', diagnostics['Q_net']),
                         ('pressure_clip_hits', diagnostics['p_clip_hits'])]:
        actual = getattr(summary, name)
        if isinstance(wanted, float):
            _bits(actual, wanted)
        else:
            assert actual == wanted
    assert bool(summary.have_finite_duty) == any(math.isfinite(diagnostics['Q_' + side]) for side in 'AB')
    assert list(summary.red_black) == [0, 0]
    model = diagnostics['model_h_balance']
    for level, label in enumerate(('main', 'fine')):
        assert bool(summary.model_h_available[level]) == (model is not None and model[label] is not None)
        if summary.model_h_available[level]:
            assert summary.model_h_cell_count[level] == model[label]['cell_count']
            _bits(summary.model_h_area_m2[level], model[label]['area_m2'])
    true_h = diagnostics['true_h_balance']
    assert bool(summary.pressure_available) == (true_h is not None)
    for side, label in enumerate('AB'):
        nu = diagnostics['sco2_nu_observations'][label]
        assert bool(summary.nu_available[side]) == bool(nu)
        if nu:
            _bits(summary.nu_floor[side], nu['floor'])
            _bits(summary.nu_floor_fraction[side], nu['floor_fraction'])
        if true_h is not None:
            low, high = true_h['P_' + label + '_range_Pa']
            _bits(summary.pressure_min_Pa[side], low)
            _bits(summary.pressure_max_Pa[side], high)
        _bits(summary.absolute_duty[side], diagnostics['Q_enthalpy_' + label])
        _bits(summary.application_hv[side], expected.metadata['application']['coeffs']['h_v' + label])
    assert native_fields
    for name, values in native_fields.items():
        np.testing.assert_array_equal(values.view(np.uint64), expected.fields[name].view(np.uint64))
    _bits(altered.application_hv[0], changed.area_density_per_m[0] * changed.surface_htc_W_m2K[0])
    original_record, changed_record = _summary_record(summary), _summary_record(altered)
    del original_record['application_hv'], changed_record['application_hv']
    assert original_record == changed_record
    np.savez_compressed(tmp_path / 'native-fields.npz', **native_fields)
    save_result(expected, tmp_path / 'reference.h5')
    (tmp_path / 'summary.json').write_text(json.dumps(_summary_record(summary), indent=2))
    (tmp_path / 'verdict.json').write_text(json.dumps({'scalars_exact': True,
        'field_bits_exact': len(native_fields), 'independent_application_inputs': True}))
    assert _summary_record(summary) == json.loads((tmp_path / 'summary.json').read_text())


def test_capture_input_failures_and_ieee_values(capture_query, monkeypatch):
    config = native_stage_support.plane_configuration(('air', 'air'))
    native_stage_support.bound_plane_controls(config)
    case = prepare_case(config, case_id='capture-boundary')
    query = capture_query
    application = _Application((_D * 2)(2., 3.), (_D * 2)(5., 7.))
    output = _Summary()
    ct.memset(ct.byref(output), 0x5a, ct.sizeof(output))
    before = bytes(output)

    def inspect(result):
        assert query(None, ct.byref(application), ct.byref(output)) == 1
        assert query(ct.addressof(result), None, ct.byref(output)) == 1
        assert query(ct.addressof(result), ct.byref(application), None) == 1
        assert bytes(output) == before
        malformed = type(result).from_buffer_copy(result)
        for field, value in [('abi_version', 0), ('struct_size', 0), ('owner', None)]:
            previous = getattr(malformed, field)
            setattr(malformed, field, value)
            assert query(ct.addressof(malformed), ct.byref(application), ct.byref(output)) == 1
            assert bytes(output) == before
            setattr(malformed, field, previous)
        result_bytes, application_bytes = bytes(result), bytes(application)
        assert query(ct.addressof(result), ct.byref(application), ct.cast(ct.byref(result), ct.POINTER(_Summary))) == 1
        assert query(ct.addressof(result), ct.byref(application), ct.cast(ct.byref(application), ct.POINTER(_Summary))) == 1
        assert bytes(result) == result_bytes and bytes(application) == application_bytes
        for field in ('area_density_per_m', 'surface_htc_W_m2K'):
            for side in (0, 1):
                negative = _Application.from_buffer_copy(application)
                getattr(negative, field)[side] = -1.
                assert query(ct.addressof(result), ct.byref(negative), ct.byref(output)) == 1
                assert bytes(output) == before
        for area, htc in [(0., 5.), (-0., 5.), (float('inf'), 0.), (float('nan'), 1.), (1e308, 1e308)]:
            application.area_density_per_m[0], application.surface_htc_W_m2K[0] = area, htc
            assert query(ct.addressof(result), ct.byref(application), ct.byref(output)) == 0
            wanted = area * htc
            if math.isnan(wanted):
                assert math.isnan(output.application_hv[0])
            else:
                _bits(output.application_hv[0], wanted)

    _, result = _live_result(monkeypatch, case, inspect)
    # The production stage released this result. The query must reject it.
    before = bytes(output)
    assert query(ct.addressof(result), ct.byref(application), ct.byref(output)) == 1
    assert bytes(output) == before
