"""Compare native capture scalars with the unchanged public 2D result."""
import ctypes as ct
from dataclasses import replace
import json
import math

import numpy as np
import pytest

from sjtu_tpmshx.compute import compute
from sjtu_tpmshx.development.tests import test_native_stage_state as state
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.io.result_io import save_result

uniform, continuous = state.uniform, state.continuous
preparation_library = state.preparation_library
continuous_library = state.continuous_library
_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Application = uniform.report.record('CaptureApplication', [
    ('area_density_per_m', _D * 2), ('surface_htc_W_m2K', _D * 2)])
_Summary = uniform.report.record('CaptureSummary', [
    ('model_h_available', _U * 2), ('nu_available', _U * 2), ('pressure_available', _U),
    ('model_h_cell_count', _Z * 2),
    *((name, _D * 2) for name in ('model_h_area_m2', 'nu_floor', 'nu_floor_fraction',
        'pressure_min_Pa', 'pressure_max_Pa')),
    ('q_net', _D), ('absolute_duty', _D * 2), ('application_hv', _D * 2),
    ('pressure_clip_hits', _Z), ('have_finite_duty', _U), ('red_black', _U * 2)])


@pytest.fixture(scope='module')
def stage_library():
    library = state.stage_library.__wrapped__()
    query = library.tpmshx_stage_run_2d_get_capture_v1
    query.argtypes = [ct.POINTER(uniform._Result), ct.POINTER(_Application), ct.POINTER(_Summary)]
    query.restype = ct.c_int
    return library


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
def test_capture_matches_public_result(preparation_library, continuous_library, stage_library,
                                       spatial, pair, tmp_path):
    config = continuous._configuration(pair) if spatial else uniform._configuration(pair)
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
    request = state._request(config)
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    (tmp_path / 'control.json').write_text(json.dumps({'cpu_threads': 2,
        'native_library': str(uniform.library_path()), 'request': 'test_native_stage_state._request'}))
    case, expected, _ = compute(config, control=RunControl(cpu_threads=2,
        native_library=str(uniform.library_path())))
    application = _application(case)
    control = uniform._Control(b'capture-stage', None, 2, uniform.abi._Callbacks())
    with state._prepared(preparation_library, continuous_library, config, spatial) as prepared:
        with state._Run(stage_library, prepared, request, control) as run:
            while run.phase != 3:
                assert run.advance() != 4
            result = run.take_result()
    try:
        summary = _Summary()
        assert stage_library.tpmshx_stage_run_2d_get_capture_v1(
            ct.byref(result), ct.byref(application), ct.byref(summary)) == 0
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
        native_fields = {}
        for index in range(result.evidence.field_count):
            field = result.evidence.fields[index]
            value = field.value
            values = np.ctypeslib.as_array(ct.cast(value.data, ct.POINTER(_D)),
                shape=(value.shape[0] * value.shape[1],)).reshape(value.shape[0], value.shape[1])
            np.testing.assert_array_equal(values.view(np.uint64), expected.fields[field.name.decode()].view(np.uint64))
            native_fields[field.name.decode()] = values.copy()
        # Saved application inputs do not replace the solver's thermal geometry.
        changed = _Application.from_buffer_copy(application)
        changed.area_density_per_m[0] *= 1.125
        altered = _Summary()
        assert stage_library.tpmshx_stage_run_2d_get_capture_v1(
            ct.byref(result), ct.byref(changed), ct.byref(altered)) == 0
        _bits(altered.application_hv[0], changed.area_density_per_m[0] * changed.surface_htc_W_m2K[0])
        original_record, changed_record = _summary_record(summary), _summary_record(altered)
        del original_record['application_hv'], changed_record['application_hv']
        assert original_record == changed_record
        np.savez_compressed(tmp_path / 'native-fields.npz', **native_fields)
        save_result(expected, tmp_path / 'reference.h5')
        (tmp_path / 'summary.json').write_text(json.dumps(_summary_record(summary), indent=2))
        (tmp_path / 'verdict.json').write_text(json.dumps({'scalars_exact': True,
            'field_bits_exact': result.evidence.field_count, 'preparation_released': True,
            'independent_application_inputs': True}))
    finally:
        stage_library.tpmshx_stage_run_2d_release_v1(ct.byref(result))
    assert _summary_record(summary) == json.loads((tmp_path / 'summary.json').read_text())


def test_capture_input_failures_and_ieee_values(preparation_library, continuous_library, stage_library):
    config = uniform._configuration(('air', 'air'))
    request = state._request(config)
    control = uniform._Control(b'capture-boundary', None, 1, uniform.abi._Callbacks())
    with state._prepared(preparation_library, continuous_library, config, False) as prepared:
        with state._Run(stage_library, prepared, request, control) as run:
            while run.phase != 3:
                assert run.advance() != 4
            result = run.take_result()
    query = stage_library.tpmshx_stage_run_2d_get_capture_v1
    application = _Application((_D * 2)(2., 3.), (_D * 2)(5., 7.))
    output = _Summary()
    ct.memset(ct.byref(output), 0x5a, ct.sizeof(output))
    before = bytes(output)
    try:
        assert query(None, ct.byref(application), ct.byref(output)) == 1
        assert query(ct.byref(result), None, ct.byref(output)) == 1
        assert query(ct.byref(result), ct.byref(application), None) == 1
        assert bytes(output) == before
        malformed = uniform._Result.from_buffer_copy(result)
        for field, value in [('abi_version', 0), ('struct_size', 0), ('owner', None)]:
            previous = getattr(malformed, field)
            setattr(malformed, field, value)
            assert query(ct.byref(malformed), ct.byref(application), ct.byref(output)) == 1
            assert bytes(output) == before
            setattr(malformed, field, previous)
        result_bytes, application_bytes = bytes(result), bytes(application)
        assert query(ct.byref(result), ct.byref(application), ct.cast(ct.byref(result), ct.POINTER(_Summary))) == 1
        assert query(ct.byref(result), ct.byref(application), ct.cast(ct.byref(application), ct.POINTER(_Summary))) == 1
        assert bytes(result) == result_bytes and bytes(application) == application_bytes
        for field in ('area_density_per_m', 'surface_htc_W_m2K'):
            for side in (0, 1):
                negative = _Application.from_buffer_copy(application)
                getattr(negative, field)[side] = -1.
                assert query(ct.byref(result), ct.byref(negative), ct.byref(output)) == 1
                assert bytes(output) == before
        for area, htc in [(0., 5.), (-0., 5.), (float('inf'), 0.), (float('nan'), 1.), (1e308, 1e308)]:
            application.area_density_per_m[0], application.surface_htc_W_m2K[0] = area, htc
            assert query(ct.byref(result), ct.byref(application), ct.byref(output)) == 0
            wanted = area * htc
            if math.isnan(wanted):
                assert math.isnan(output.application_hv[0])
            else:
                _bits(output.application_hv[0], wanted)
    finally:
        stage_library.tpmshx_stage_run_2d_release_v1(ct.byref(result))
    before = bytes(output)
    assert query(ct.byref(result), ct.byref(application), ct.byref(output)) == 1
    assert bytes(output) == before
