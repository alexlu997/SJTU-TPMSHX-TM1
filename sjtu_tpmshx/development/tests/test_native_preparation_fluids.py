"""Compare the native uniform-fluid stage with the current preparation API."""
import ctypes as ct
from contextlib import contextmanager
from dataclasses import replace
from itertools import product
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig
from sjtu_tpmshx.shared.domain.run_warnings import RangeRecord, range_observations, warning_scope
from sjtu_tpmshx.shared.models._native_properties import _Failure as _PropertyFailure

_U, _S, _D = v1._U, v1._S, v1._D
_struct, _text, _same, _array = v1._structure, v1._text, v1._same, v1._array
_Kind = _struct('Kind', [(name, _U) for name in ('precision', 'strong', 'layout')])
_InletKinds = _struct('InletKinds', [(name, _Kind) for name in ('velocity', 'temperature', 'pressure')])
_Kinds = _struct('Kinds', [(name, _Kind) for name in ('cell_length', 'wall_thickness', 'solid_conductivity')] + [('sides', _InletKinds * 2)])
_Nu = _struct('Nu', [('mode', _U), ('have_alpha', _U * 2), ('alpha', _D * 2)] + [(name, v1._Text) for name in ('parameter_version', 'source', 'applicability')])
_Input = _struct('InputV2', [('abi_version', _U), ('struct_size', _S), ('values', v1._Input), ('sco2_nu', _Nu), ('kinds', _Kinds)])
_Selection = _struct('Selection', [(name, _U) for name in ('branch', 'campaign', 'scope', 'flags')] + v1._doubles('scale_K scale_F') + [(name, _D * 2) for name in ('application_u', 'calibration_u', 'runtime_u')])
_TextField = _struct('TextField', [('key', v1._Text), ('value', v1._Text)])
_Drag = _struct('Drag', [('have_selection', _U), ('selection', _Selection), ('application_scope', v1._Text), ('fluid', v1._Text), ('calibration', ct.POINTER(_TextField)), ('calibration_count', _S)])
_Co2 = _struct('Co2', [('active', _U), ('sides', _U * 2)] + [(name, v1._Text) for name in ('version', 'application_version', 'pressure_model')] + v1._doubles('pressure_multiplier scale_K scale_F nu_multiplier nu_floor_multiplier') + [(name, v1._Text) for name in ('correction_source', 'property_model', 'common_geometry')] + [('re_range', _D * 2), ('pr_range', _D * 2)])
_Result = _struct('ResultV2', [('abi_version', _U), ('struct_size', _S), ('values', v1._Result), ('input_kinds', _Kinds), ('field_kinds', _Kind * 5), ('property_kinds', (_Kind * 13) * 2), ('sco2_nu', _Nu), ('sco2_nu_model_version', v1._Text), ('sco2_nu_interpretation', v1._Text), ('sco2_nu_coefficients', (_D * 3) * 2), ('drag', _Drag * 2), ('co2', _Co2), ('notices', ct.POINTER(v1._Text)), ('notice_count', _S), ('range_bounds_list', ct.POINTER(_U))])
_Cause = _struct('Cause', [('kind', _U), ('message', ct.c_char * 4096)])
_Failure = _struct('Failure', [('abi_version', _U), ('struct_size', _S)] + [(name, _U) for name in ('kind', 'side', 'have_property', 'cause_count')] + [('property', _PropertyFailure), ('causes', _Cause * 2)])
_FLUIDS = ('air', 'water', 'sco2', 'co2')


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    library.tpmshx_prepare_case_2d_v2.argtypes = [ct.POINTER(_Input), ct.POINTER(v1._Options), ct.POINTER(v1._Callbacks), ct.POINTER(_Result), ct.POINTER(_Failure), ct.POINTER(ct.c_char), _S]
    library.tpmshx_prepare_case_2d_v2.restype = ct.c_int
    library.tpmshx_preparation_case_2d_release_v2.argtypes = [ct.POINTER(_Result)]
    library.tpmshx_preparation_case_2d_release_v2.restype = None
    return library


def _kind(value):
    if isinstance(value, np.ndarray):
        return _Kind(value.dtype.itemsize * 8, 1, 2)
    if isinstance(value, np.floating):
        return _Kind(value.dtype.itemsize * 8, 1, 1)
    return _Kind(64, 0, 0)


def _input(config):
    result = _Input(2, ct.sizeof(_Input), v1._input(config))
    result.values.df_mode = int(config.df_mode == 'experimental')
    geometry = config.geometry
    result.kinds = _Kinds(_kind(geometry.L_cell_mm), _kind(geometry.t_wall_mm), _kind(geometry.k_s_W_mK))
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        result.values.sides[index].fluid = _FLUIDS.index(fluid.type)
        result.kinds.sides[index] = _InletKinds(*(_kind(value) for value in (fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa)))
    settings = config.sco2_nu
    result.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        value = getattr(settings, name)
        result.sco2_nu.have_alpha[index] = value is not None
        result.sco2_nu.alpha[index] = value or 0.
    result._buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        buffer = ct.create_string_buffer(getattr(settings, name).encode())
        result._buffers.append(buffer)
        setattr(result.sco2_nu, name, v1._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(buffer.value)))
    return result


def _configuration(topology, pair, mode='cfd_smooth'):
    config = ComputeConfig()
    config.solver.Nx, config.solver.Ny = 6, 8
    config.geometry.tpms = topology
    config.bc_B.dir = 3
    config.extrap.allow = True
    config.df_mode = mode
    states = {'air': (350., 200000., 6.), 'water': (320., 200000., .02), 'sco2': (400., 8e6, .15), 'co2': (400., 8e6, .15)}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        fluid.type = pair[index]
        fluid.T_in_K, fluid.P_in_Pa, fluid.u_mps = states[fluid.type]
    if mode == 'experimental':
        from sjtu_tpmshx.shared.configs.model_parameters import load_preparation_df_parameters
        data = load_preparation_df_parameters()['hx']
        for side in 'AB':
            fluid = getattr(config, 'fluid_' + side)
            if fluid.type != 'co2':
                bounds = data['application_u_mps'][fluid.type][topology]
                fluid.u_mps = sum(bounds) / 2.
    return config


def _capture_reference(config, monkeypatch):
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.preprocess.two_d import preparation
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    records, logs = {}, []
    @contextmanager
    def capture_scope(initial):
        with warning_scope(initial) as current:
            yield current
        records.update(current)
    monkeypatch.setattr(api, 'warning_scope', capture_scope)
    monkeypatch.setattr(preparation._log, 'info', lambda message: logs.append((0, preparation._log.name, message, 0)))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        expected = prepare_case(config, case_id='native-uniform-fluid-reference')
    return expected, records, [(1, '', str(item.message), 0) for item in caught] + logs


def _call(native, config):
    source, result, failure = _input(config), _Result(2, ct.sizeof(_Result)), _Failure(2, ct.sizeof(_Failure))
    options = v1._Options(1, ct.sizeof(v1._Options), 0, config.extrap.allow, 0.)
    error, events = ct.create_string_buffer(4096), []
    def event(_context, pointer):
        value = pointer.contents
        events.append((value.kind, _text(value.logger), _text(value.message), value.floating_event))
        return 0
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    status = native.tpmshx_prepare_case_2d_v2(ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    return status, result, failure, error.value.decode(), events, source


def _check_values(result, expected, config):
    actual = result.values
    assert (actual.nx, actual.ny) == (len(expected.grid['dx']), len(expected.grid['dy']))
    for name in ('dx', 'dy', 'x_edges', 'y_edges', 'x_breaks', 'y_breaks'):
        _same(_array(getattr(actual, name)), expected.grid[name], name)
    for index, (name, key) in enumerate([('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'), ('total_porosity', 'eps_arr'), ('solid_conductivity', 'K_ss_arr'), ('hydraulic_radius', 'r_h_arr')]):
        array = expected.design_fields[key]
        _same(_array(getattr(actual, name)).reshape(array.shape), array, key)
        assert result.field_kinds[index].precision == array.dtype.itemsize * 8, key
    params = expected.parameters
    for name, key in [('hydraulic_radius_m', 'r_h'), ('cell_length_m', 'L_cell_m'), ('wall_thickness_m', 't_wall_m')]:
        _same(getattr(actual, name), params[key], key)
    for name, key in [('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'), ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'), ('uniform_solid_conductivity', 'K_ss')]:
        _same(getattr(actual, name), params['static_properties']['geometry'][key], key)
    for index, side in enumerate('AB'):
        value, flow = actual.sides[index], params['flow_inputs'][side]
        from sjtu_tpmshx.shared.models.tpms_calc import compute
        fluid, geometry = getattr(config, 'fluid_' + side), config.geometry
        with warning_scope({}):
            raw_properties = compute(geometry.tpms, geometry.L_cell_mm, geometry.t_wall_mm,
                fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa, geometry.k_s_W_mK, fluid.type,
                sco2_nu=config.sco2_nu, co2_geometry='co2' in (config.fluid_A.type, config.fluid_B.type))
        for name, key in [('cross_widths', 'dx'), ('stream_widths', 'dy'), ('row_permeability', 'K_m2'), ('row_forchheimer', 'cF_per_m')]:
            _same(_array(getattr(value, name)), flow[key], side + key)
        for name, key in [('seed_permeability_m2', 'seed_K_m2'), ('seed_forchheimer_per_m', 'seed_cF_per_m')]:
            _same(getattr(value, name), flow[key], side + key)
        assert value.permeability.size == value.forchheimer.size == 0
        for name, key in [('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'), ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac')]:
            _same(_array(getattr(value, name)), params['boundary_openings'][side][key], side + key)
        for name, key in [('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'), ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'), ('pressure_gradient_Pa_m', 'dP_per_L'), ('surface_transfer_W_m2K', 'H_sf'), ('fluid_conductivity_W_mK', 'K_ff'), ('solid_conductivity_W_mK', 'K_ss')]:
            reference = params['static_properties'][side][key]
            _same(getattr(value.properties, name), reference, side + key)
            property_index = [item[0] for item in v1._Properties._fields_].index(name)
            assert v1._struct_values(result.property_kinds[index][property_index]) == v1._struct_values(_kind(raw_properties[key])), side + key
        from sjtu_tpmshx.shared.models import fluid_props
        from sjtu_tpmshx.shared.models._native_properties import prandtl
        fluid = getattr(config, 'fluid_' + side)
        with warning_scope({}):
            cp = float(fluid_props.get(fluid.type).cp(fluid.T_in_K, fluid.P_in_Pa))
        _same(value.properties.cp, cp, side + 'cp')
        _same(value.properties.pr, prandtl(value.properties.mu, cp, value.properties.k_f), side + 'Pr')
        metadata = flow['metadata']
        drag = value.drag_evidence
        for name, key in [('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'), ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF')]:
            summary, reference = getattr(drag, name), metadata[key]
            assert bool(summary.scalar) == isinstance(reference, float), side + key
            _same(summary.minimum, reference if summary.scalar else reference['min'], side + key)
            _same(summary.maximum, reference if summary.scalar else reference['max'], side + key)
        for name, key in [('scale_permeability', 'scale_K'), ('scale_forchheimer', 'scale_F')]:
            _same(getattr(drag, name), metadata[key], side + key)
        assert _text(drag.campaign) == metadata['campaign']
        assert _text(drag.scope) == metadata['scope']
        extended = result.drag[index]
        assert bool(extended.have_selection) == (config.df_mode == 'experimental' and fluid.type != 'co2')
        assert _text(extended.fluid) == metadata.get('fluid', '')
        assert _text(extended.application_scope) == metadata.get('application_scope', '')
        assert {_text(item.key): _text(item.value) for item in extended.calibration[:extended.calibration_count]} == metadata.get('calibration', {})
        if 'velocity_window_mps' in metadata:
            for name, key in [('application_u', 'velocity_window_mps'), ('calibration_u', 'calibration_velocity_window_mps'), ('runtime_u', 'calibration_runtime_velocity_window_mps')]:
                _same(getattr(extended.selection, name), [metadata[key]['min'], metadata[key]['max']], side + key)
            assert bool(extended.selection.flags & 2) == metadata['extrapolated']
    assert [(_text(model.name), _text(model.version), _text(model.side)) for model in actual.models] == [(model.name, model.version, 'AB'[index] if index < 2 else '') for index, model in enumerate(expected.model_refs)]


def _check_evidence(result, expected, records, events, live, config):
    actual = result.values
    assert [v1._range(actual.ranges[i]) for i in range(actual.range_count)] == list(expected.metadata['applicability_inputs'])
    for last in (False, True):
        observations = []
        for index in range(actual.range_count):
            row = v1._range(actual.ranges[index], last=last)
            if result.range_bounds_list[index]:
                row['bounds'] = list(row['bounds'])
            observations.append(row)
        assert observations == range_observations(records, last=last)
    assert [_text(actual.ranges[i].label) for i in range(actual.range_count)] == [value.label for value in records.values() if isinstance(value, RangeRecord)]
    assert [_text(item) for item in actual.warnings[:actual.warning_count]] == list(expected.metadata['warnings'])
    saved = [(item.kind, _text(item.logger), _text(item.message), item.floating_event) for item in actual.events[:actual.event_count]]
    assert saved == live == events
    assert [_text(item) for item in result.notices[:result.notice_count]] == list(expected.metadata.get('notices', ()))
    settings = config.sco2_nu
    assert result.sco2_nu.mode == (settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        assert bool(result.sco2_nu.have_alpha[index]) == (getattr(settings, name) is not None)
        if getattr(settings, name) is not None:
            _same(result.sco2_nu.alpha[index], getattr(settings, name), name)
    for name in ('parameter_version', 'source', 'applicability'):
        assert _text(getattr(result.sco2_nu, name)) == getattr(settings, name)
    model = expected.metadata['model_metadata']['sco2_nu']
    assert _text(result.sco2_nu_model_version) == model['model_version']
    if settings.mode == 'experimental':
        assert _text(result.sco2_nu_interpretation) == model['interpretation']
    else:
        for index, topology in enumerate(('Diamond', 'Gyroid')):
            _same(result.sco2_nu_coefficients[index], [model['coefficients'][topology][key] for key in ('c', 'a', 'd')], topology)
    model = expected.metadata['model_metadata'].get('co2')
    assert bool(result.co2.active) == (model is not None)
    if model is not None:
        assert ['AB'[i] for i, flag in enumerate(result.co2.sides) if flag] == list(model['sides'])
        for name in ('version', 'application_version', 'pressure_model', 'correction_source', 'property_model', 'common_geometry'):
            assert _text(getattr(result.co2, name)) == model[name]
        for name in ('pressure_multiplier', 'scale_K', 'scale_F', 'nu_multiplier', 'nu_floor_multiplier'):
            _same(getattr(result.co2, name), model[name], name)
        _same(result.co2.re_range, model['Re_range'], 'Re range')
        _same(result.co2.pr_range, model['Pr_range'], 'Pr range')


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(_FLUIDS, repeat=2)))
@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_native_uniform_fluid_pairs(native, monkeypatch, topology, pair, mode):
    config = _configuration(topology, pair, mode)
    expected, records, events = _capture_reference(config, monkeypatch)
    status, result, failure, error, live, source = _call(native, config)
    assert status == 0, error
    try:
        assert not failure.kind
        assert v1._struct_values(result.values.input) == v1._struct_values(source.values)
        assert v1._struct_values(result.input_kinds) == v1._struct_values(source.kinds)
        _check_values(result, expected, config)
        _check_evidence(result, expected, records, events, live, config)
    finally:
        native.tpmshx_preparation_case_2d_release_v2(ct.byref(result))


@pytest.mark.parametrize('selection', ['saved-nu', 'saved-nu-unicode', 'inactive-nu', 'smooth-provenance', 'specimen', 'hx-extrapolation', 'typed-material-16', 'typed-material-32', 'typed-material-64', 'typed-material-array-16', 'typed-material-array-32', 'typed-material-array-64', 'typed-material-co2-array-32', 'typed-inlet-32', 'typed-cell-32', 'typed-co2-32', 'typed-inlet-16', 'typed-cell-16', 'typed-extrapolation'])
def test_native_uniform_saved_selection_and_precision(native, monkeypatch, selection):
    config = _configuration('Gyroid', ('sco2', 'water'))
    if selection in ('saved-nu', 'saved-nu-unicode', 'inactive-nu', 'smooth-provenance'):
        config.sco2_nu = replace(config.sco2_nu,
            mode='cfd_smooth' if selection == 'smooth-provenance' else 'experimental',
            alpha_D=1.13, alpha_G=2.27, parameter_version='saved-test-version',
            source='retained source', applicability='retained scope')
        if selection == 'saved-nu-unicode':
            config.sco2_nu = replace(config.sco2_nu, parameter_version='保留版本',
                source='\u00a0实验测量来源\u3000', applicability='保留适用范围')
        if selection == 'inactive-nu':
            config.fluid_A.type = 'co2'
    elif selection == 'specimen':
        config = _configuration('Diamond', ('air', 'co2'), 'experimental')
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = 7.125, .42
    elif selection == 'hx-extrapolation':
        config = _configuration('Gyroid', ('air', 'water'), 'experimental')
        config.fluid_A.u_mps, config.fluid_B.u_mps = 4., .02
    else:
        config = _configuration('Diamond', ('air', 'water'))
        if selection.startswith('typed-material'):
            dtype = getattr(np, 'float' + selection.rsplit('-', 1)[1])
            config.geometry.k_s_W_mK = np.array(1.337, dtype=dtype) if '-array-' in selection else dtype(1.337)
            if '-co2-' in selection:
                config.fluid_A.type, config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 'co2', 400., 8e6
        elif selection in ('typed-inlet-32', 'typed-extrapolation'):
            config.fluid_A.u_mps = np.float32(1000.12 if selection == 'typed-extrapolation' else 6.12)
            config.fluid_A.T_in_K = np.float32(351.13)
            config.fluid_B.T_in_K = np.float32(321.13)
            config.fluid_A.P_in_Pa = np.float32(201234.5)
        elif selection == 'typed-inlet-16':
            config.fluid_A.u_mps = np.float16(6.12)
            config.fluid_B.T_in_K = np.float16(321.13)
        elif selection == 'typed-cell-16':
            config.geometry.L_cell_mm, config.geometry.t_wall_mm = np.float16(7.), np.float16(.5)
        else:
            config.geometry.L_cell_mm = np.float32(6.125)
            config.geometry.t_wall_mm = np.float32(.42)
            if selection == 'typed-co2-32':
                config.fluid_A.type, config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 'co2', 400., 8e6
    expected, records, events = _capture_reference(config, monkeypatch)
    status, result, failure, error, live, source = _call(native, config)
    assert status == 0, error
    try:
        assert not failure.kind
        _check_values(result, expected, config)
        _check_evidence(result, expected, records, events, live, config)
        source.values.cell_length_mm = 4.
        for buffer in source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        assert result.values.input.cell_length_mm == config.geometry.L_cell_mm
        assert _text(result.sco2_nu.parameter_version) == config.sco2_nu.parameter_version
    finally:
        native.tpmshx_preparation_case_2d_release_v2(ct.byref(result))
    assert not result.values.owner
    native.tpmshx_preparation_case_2d_release_v2(ct.byref(result))


def _invalid_configuration(selection):
    config = _configuration('Gyroid', ('air', 'water'))
    if selection in ('water-vapor', 'water-ice', 'water-before-co2'):
        config.fluid_B.T_in_K = 450. if selection != 'water-ice' else 250.
        if selection == 'water-before-co2':
            config.fluid_A.type, config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 'co2', 200., 8e6
    elif selection.startswith('co2-'):
        config.fluid_A.type = 'co2'
        config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 200., 8e6
        if selection == 'co2-critical':
            config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 304.1282, 7377298.373
    elif selection.startswith('sco2-'):
        config.fluid_A.type, config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 'sco2', 400., 8e6
        if selection == 'sco2-temperature':
            config.fluid_A.T_in_K = 701.
        else:
            config.fluid_A.P_in_Pa = 7.8e6
            config.fluid_B.T_in_K = 450.
    elif selection.startswith('nu-'):
        config.sco2_nu = replace(config.sco2_nu, mode='experimental',
            alpha_D=-1. if selection == 'nu-alpha' else 1.1, alpha_G=1.2,
            parameter_version='saved', source='source' if selection == 'nu-alpha' else ' \t ',
            applicability='scope')
    elif selection == 'geometry-before-state':
        config.geometry.L_cell_mm = 9.
        config.fluid_B.T_in_K = 450.
    elif selection.startswith('experimental-'):
        config = _configuration('Gyroid', ('air', 'water'), 'experimental')
        if selection == 'experimental-speed':
            config.fluid_A.u_mps = 100.
        elif selection == 'experimental-geometry':
            config.geometry.t_wall_mm = .5
        elif selection == 'experimental-domain':
            config.geometry.H_dom_m = .05
        else:
            config.fluid_A.u_mps = 100.
            config.fluid_B.T_in_K = 450.
    elif selection == 'reject-extrapolation':
        config.extrap.allow = False
        config.fluid_A.u_mps = 1000.
    return config


def _error_kind(error):
    if type(error).__name__ == 'WaterStateError':
        return 2
    return 1 if isinstance(error, ValueError) else 3


@pytest.mark.parametrize('selection', ['water-vapor', 'water-ice', 'water-before-co2', 'co2-triple', 'co2-critical', 'sco2-temperature', 'sco2-before-water', 'nu-alpha', 'nu-source', 'geometry-before-state', 'experimental-speed', 'experimental-geometry', 'experimental-domain', 'experimental-before-water', 'reject-extrapolation'])
def test_native_uniform_first_error_and_cause(native, monkeypatch, selection):
    config = _invalid_configuration(selection)
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    with pytest.raises(ValueError) as caught:
        prepare_case(config, case_id='native-uniform-invalid-reference')
    expected = caught.value
    status, result, failure, error, _, _ = _call(native, config)
    assert status != 0
    assert not result.values.owner
    assert bytes(result) == bytes(_Result(2, ct.sizeof(_Result)))
    assert error == str(expected)
    assert failure.kind == _error_kind(expected)
    causes = []
    cause = expected.__cause__
    while cause is not None:
        causes.append((_error_kind(cause), str(cause)))
        cause = cause.__cause__
    assert [(item.kind, item.message.decode()) for item in failure.causes[:failure.cause_count]] == causes
    if selection.startswith('water-') or selection.startswith('co2-'):
        assert failure.have_property
        assert failure.property.reason


@pytest.mark.parametrize('field', ['parameter_version', 'source', 'applicability'])
@pytest.mark.parametrize('blank', [' \t\n\r\f\v', '\x1c\x1d\x1e\x1f'] + [chr(code) for code in (
    0x85, 0xa0, 0x1680, *range(0x2000, 0x200b), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000)])
def test_native_uniform_nu_rejects_blank_provenance(native, field, blank):
    config = _configuration('Gyroid', ('sco2', 'water'))
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
        parameter_version='saved version', source='retained source', applicability='retained scope')
    config.sco2_nu = replace(config.sco2_nu, **{field: blank})
    with pytest.raises(ValueError) as expected:
        prepare_case(config, case_id='native-uniform-nu-provenance-reference')
    status, result, failure, error, events, _ = _call(native, config)
    assert status == 1
    assert error == str(expected.value)
    assert failure.kind == 1
    assert not events
    assert bytes(result) == bytes(_Result(2, ct.sizeof(_Result)))


def test_python_preparation_keeps_unhashable_velocity_failure(monkeypatch):
    config = _configuration('Diamond', ('air', 'water'))
    config.fluid_A.u_mps = np.array(6.12, dtype=np.float32)
    from sjtu_tpmshx.preprocess.two_d import preparation
    logs = []
    monkeypatch.setattr(preparation._log, 'info', logs.append)
    with pytest.raises(TypeError, match="unhashable type: 'numpy.ndarray'"):
        prepare_case(config, case_id='native-uniform-host-type-reference')
    assert logs == ['[run_calculation] Wall-refined grid: 22×24 cells (4-wall BL resolved)']
