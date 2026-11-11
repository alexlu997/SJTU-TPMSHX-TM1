"""Compare owned native preparation with the independent Python stage."""
import ctypes as ct
from contextlib import contextmanager
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig
from sjtu_tpmshx.shared.models._native_preparation import _library_path


_U = ct.c_uint32
_S = ct.c_size_t
_D = ct.c_double


def _structure(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


def _doubles(names):
    return [(name, _D) for name in names.split()]


_Port = _structure('Port', [('direction', ct.c_int32), *_doubles(
    'inlet_center_m inlet_width_m outlet_center_m outlet_width_m'), ('uniform_inlet', _U)])
_Inlet = _structure('Inlet', [('fluid', _U), *_doubles('velocity_m_s temperature_K pressure_Pa'),
                            ('port', _Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_Input = _structure('Input', [('abi_version', _U), ('struct_size', _S),
    *_doubles('length_m height_m'), ('requested_nx', _S), ('requested_ny', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *_doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('have_physical_depth', _U), ('geometry_mode', _U), ('df_mode', _U),
    ('physical_depth_m', _D)])
_Options = _structure('Options', [('abi_version', _U), ('struct_size', _S),
                                ('have_chi', _U), ('allow_extrapolation', _U), ('chi', _D)])
_Array = _structure('Array', [('data', ct.POINTER(_D)), ('size', _S)])
_Text = _structure('Text', [('data', ct.POINTER(ct.c_char)), ('size', _S)])
_Event = _structure('Event', [('kind', _U), ('logger', _Text), ('message', _Text), ('floating_event', _U)])
_EventFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.POINTER(_Event))
_Callbacks = _structure('Callbacks', [('abi_version', _U), ('struct_size', _S),
                                    ('event', _EventFunction), ('context', ct.c_void_p)])
_Properties = _structure('Properties', _doubles(
    'rho mu k_f cp pr re nu permeability_m2 forchheimer_per_m pressure_gradient_Pa_m '
    'surface_transfer_W_m2K fluid_conductivity_W_mK solid_conductivity_W_mK'))
_DragSummary = _structure('DragSummary', [*_doubles('minimum maximum'), ('scalar', _U)])
_DragEvidence = _structure('DragEvidence', [(name, _DragSummary) for name in
    'base_permeability base_forchheimer applied_permeability applied_forchheimer'.split()] +
    _doubles('scale_permeability scale_forchheimer') + [('campaign', _Text), ('scope', _Text)])
_Side = _structure('Side', [('inlet', _Inlet), ('properties', _Properties),
    *_doubles('seed_permeability_m2 seed_forchheimer_per_m'),
    *((name, _Array) for name in ('cross_widths stream_widths row_permeability row_forchheimer '
        'permeability forchheimer inlet_geometry outlet_geometry inlet_profile outlet_profile outlet_u_fraction').split()),
    ('inlet_bounds', _D * 2), ('outlet_bounds', _D * 2), ('drag_evidence', _DragEvidence)])
_Sample = _structure('Sample', [('have_finite', _U), *_doubles('minimum maximum'),
    *((name, _S) for name in 'minimum_index maximum_index low high size nonfinite'.split())])
_Range = _structure('Range', [('source', ct.POINTER(_Text)), ('source_count', _S),
    *((name, _Text) for name in 'side stage layout label quantity unit'.split()),
    ('bounds', _D * 2), ('shape', ct.POINTER(_S)), ('rank', _S), ('sample', _Sample), ('last', _Sample)])
_Model = _structure('Model', [(name, _Text) for name in 'name version side'.split()])
_Result = _structure('Result', [('abi_version', _U), ('struct_size', _S), ('input', _Input),
    ('options', _Options), ('nx', _S), ('ny', _S),
    *((name, _Array) for name in 'dx dy x_edges y_edges x_breaks y_breaks'.split()),
    *_doubles('epsilon epsilon_a epsilon_b area_density_per_m hydraulic_diameter_m '
              'uniform_solid_conductivity hydraulic_radius_m cell_length_m wall_thickness_m split_a'),
    *((name, _Array) for name in 'cell_length wall_thickness total_porosity solid_conductivity hydraulic_radius'.split()),
    ('sides', _Side * 2), ('models', _Model * 4), ('ranges', ct.POINTER(_Range)), ('range_count', _S),
    ('warnings', ct.POINTER(_Text)), ('warning_count', _S), ('events', ct.POINTER(_Event)),
    ('event_count', _S), ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    # An explicit path keeps the baseline preparation library independent.
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', _library_path()))
    function = library.tpmshx_prepare_case_2d_v1
    function.argtypes = [ct.POINTER(_Input), ct.POINTER(_Options), ct.POINTER(_Callbacks),
                         ct.POINTER(_Result), ct.POINTER(ct.c_char), _S]
    function.restype = ct.c_int
    library.tpmshx_preparation_case_2d_release_v1.argtypes = [ct.POINTER(_Result)]
    library.tpmshx_preparation_case_2d_release_v1.restype = None
    return library


def _text(value):
    return ct.string_at(value.data, value.size).decode()


def _array(value):
    return np.ctypeslib.as_array(value.data, shape=(value.size,)).copy() if value.size else np.array([], dtype=float)


def _same(actual, expected, name):
    actual = np.asarray(actual, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    assert actual.shape == expected.shape, name
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64), err_msg=name)


def _struct_values(value):
    if isinstance(value, ct.Structure):
        return {name: _struct_values(getattr(value, name)) for name, _ in value._fields_}
    if isinstance(value, ct.Array):
        return [_struct_values(item) for item in value]
    return value.hex() if isinstance(value, float) else value


def _input(config):
    geometry = config.geometry
    value = _Input(1, ct.sizeof(_Input), geometry.L_dom_m, geometry.H_dom_m,
        config.solver.Nx, config.solver.Ny, config.flags.port_wall_refine,
        0 if geometry.tpms == 'Diamond' else 1, geometry.L_cell_mm, geometry.t_wall_mm,
        geometry.k_s_W_mK, geometry.delta_levelset)
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        value.sides[index] = _Inlet(0, fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa,
            _Port(port.dir, port.in_ctr, port.in_w, port.out_ctr, port.out_w, port.uniform_inlet_2d),
            fluid.mass_flow_kg_s is not None, fluid.mass_flow_kg_s or 0.)
    value.have_physical_depth = geometry.Lz_m is not None
    value.physical_depth_m = geometry.Lz_m or 0.
    return value


def _configuration(selection):
    config = ComputeConfig()
    config.solver.Nx, config.solver.Ny = 20, 40
    config.fluid_A.T_in_K = 400.
    config.bc_B.dir = 1
    chi = None
    if selection == 'diamond':
        config.geometry.tpms = 'Diamond'
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.25, .42
    elif selection in ('partial', 'uniform-inlet', 'reverse-y', 'port-wall'):
        config.bc_A.in_ctr, config.bc_A.in_w = .012, .012
        config.bc_A.out_ctr, config.bc_A.out_w = .028, .016
        config.bc_B.dir = 3 if selection == 'reverse-y' else 2
        config.bc_B.in_ctr, config.bc_B.in_w = .045, .04
        config.bc_B.out_ctr, config.bc_B.out_w = .13, .06
        config.bc_A.uniform_inlet_2d = selection == 'uniform-inlet'
        if selection == 'port-wall':
            config.flags.port_wall_refine = True
            config.solver.Nx, config.solver.Ny = 80, 80
            config.bc_A.in_ctr = config.bc_A.out_ctr = .021
            config.bc_A.in_w = config.bc_A.out_w = .02
            config.bc_B.in_ctr = config.bc_B.out_ctr = .09
            config.bc_B.in_w = config.bc_B.out_w = .08
    elif selection in ('short-domain', 'single-cell'):
        config.geometry.L_dom_m, config.geometry.H_dom_m = .002, .003
        if selection == 'single-cell':
            config.solver.Nx = config.solver.Ny = 1
    elif selection == 'roundtrip':
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = 5.123456789012345, .4333333333333333
    elif selection == 'chi':
        chi = .65
        config.geometry.Lz_m = .02
    elif selection == 'extrapolation':
        config.extrap.allow = True
        config.fluid_A.u_mps, config.fluid_B.u_mps = 1000., .02
    elif selection == 'temperature-range':
        config.fluid_A.T_in_K, config.fluid_B.T_in_K = 1200., 150.
        config.extrap.allow = True
    return config, chi


def _range(value, *, last=False):
    shape = tuple(value.shape[index] for index in range(value.rank))
    sample = value.last if last else value.sample
    def extreme(name):
        if not sample.have_finite:
            return None
        flat = getattr(sample, name + '_index')
        index = tuple(int(item) for item in np.unravel_index(flat, shape)) if shape else ()
        return getattr(sample, name), index
    return {'source': tuple(_text(value.source[index]) for index in range(value.source_count)),
        **{name: _text(getattr(value, name)) for name in ('side', 'stage', 'layout', 'quantity', 'unit')},
        'shape': shape, 'bounds': tuple(value.bounds), 'captured': True,
        'minimum': extreme('minimum'), 'maximum': extreme('maximum'),
        **{name: getattr(sample, name) for name in ('low', 'high', 'size', 'nonfinite')}}


@pytest.mark.parametrize('selection', ['baseline', 'diamond', 'partial', 'uniform-inlet',
    'reverse-y', 'port-wall', 'short-domain', 'single-cell', 'roundtrip', 'chi', 'extrapolation', 'temperature-range'])
def test_native_preparation_matches_existing_stage(native, monkeypatch, selection):
    config, chi = _configuration(selection)
    if chi is None:
        monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    else:
        monkeypatch.setenv('TPMSHX_CHI_S', str(chi))
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    compute.cache_clear()
    from sjtu_tpmshx.preprocess.two_d import preparation
    expected_events = []
    monkeypatch.setattr(preparation._log, 'info', lambda message: expected_events.append(
        (0, preparation._log.name, message, 0)))
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.shared.domain.run_warnings import RangeRecord, range_observations, warning_scope
    reference_records = {}
    @contextmanager
    def capture_scope(records):
        with warning_scope(records) as current:
            yield current
        reference_records.update(current)
    monkeypatch.setattr(api, 'warning_scope', capture_scope)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        expected = prepare_case(config, case_id='native-preparation-reference')
    expected_warnings = [str(item.message) for item in caught]
    source = _input(config)
    options = _Options(1, ct.sizeof(_Options), chi is not None, config.extrap.allow, chi or 0.)
    result = _Result(1, ct.sizeof(_Result))
    error = ct.create_string_buffer(4096)
    live_events = []
    def event(_context, pointer):
        item = pointer.contents
        live_events.append((item.kind, _text(item.logger), _text(item.message), item.floating_event))
        return 0
    callback = _EventFunction(event)
    callbacks = _Callbacks(1, ct.sizeof(_Callbacks), callback, None)
    assert native.tpmshx_prepare_case_2d_v1(ct.byref(source), ct.byref(options), ct.byref(callbacks),
        ct.byref(result), error, len(error)) == 0, error.value.decode()
    try:
        assert _struct_values(result.input) == _struct_values(source)
        assert _struct_values(result.options) == _struct_values(options)
        assert (result.nx, result.ny) == (len(expected.grid['dx']), len(expected.grid['dy']))
        for name in ('dx', 'dy', 'x_edges', 'y_edges', 'x_breaks', 'y_breaks'):
            _same(_array(getattr(result, name)), expected.grid[name], name)
        for name, key in [('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'),
            ('total_porosity', 'eps_arr'), ('solid_conductivity', 'K_ss_arr'), ('hydraulic_radius', 'r_h_arr')]:
            _same(_array(getattr(result, name)).reshape(result.nx, result.ny), expected.design_fields[key], key)
        params = expected.parameters
        for name, key in [('hydraulic_radius_m', 'r_h'), ('cell_length_m', 'L_cell_m'), ('wall_thickness_m', 't_wall_m')]:
            _same(getattr(result, name), params[key], key)
        geometry = params['static_properties']['geometry']
        for name, key in [('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
            ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'), ('uniform_solid_conductivity', 'K_ss')]:
            _same(getattr(result, name), geometry[key], key)
        _same(result.split_a, .5, 'split_a')
        for index, side in enumerate('AB'):
            actual = result.sides[index]
            flow, ports = params['flow_inputs'][side], params['boundary_openings'][side]
            for name, key in [('cross_widths', 'dx'), ('stream_widths', 'dy'),
                ('row_permeability', 'K_m2'), ('row_forchheimer', 'cF_per_m')]:
                _same(_array(getattr(actual, name)), flow[key], side + key)
            for name, key in [('seed_permeability_m2', 'seed_K_m2'), ('seed_forchheimer_per_m', 'seed_cF_per_m')]:
                _same(getattr(actual, name), flow[key], side + key)
            assert actual.permeability.size == actual.forchheimer.size == 0
            evidence = actual.drag_evidence
            for name, key in [('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
                              ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF')]:
                summary = getattr(evidence, name)
                value = flow['metadata'][key]
                assert bool(summary.scalar) == isinstance(value, float)
                _same(summary.minimum, value if summary.scalar else value['min'], side + key + '.min')
                _same(summary.maximum, value if summary.scalar else value['max'], side + key + '.max')
            _same(evidence.scale_permeability, flow['metadata']['scale_K'], side + 'scale_K')
            _same(evidence.scale_forchheimer, flow['metadata']['scale_F'], side + 'scale_F')
            assert _text(evidence.campaign) == flow['metadata']['campaign']
            assert _text(evidence.scope) == flow['metadata']['scope']
            for name, key in [('inlet_geometry', 'in_geom_frac'), ('inlet_profile', 'in_profile_frac'),
                              ('outlet_geometry', 'out_geom_frac'), ('outlet_profile', 'out_profile_frac')]:
                _same(_array(getattr(actual, name)), ports[key], side + key)
            from sjtu_tpmshx.shared.models.grid import _port_overlap_1d
            port = params['cfg' + side]
            for end in ('inlet', 'outlet'):
                key = 'in' if end == 'inlet' else 'out'
                bounds = [port[key + '_ctr'] - port[key + '_w'] / 2., port[key + '_ctr'] + port[key + '_w'] / 2.]
                _same(getattr(actual, end + '_bounds'), bounds, side + end)
            _same(_array(actual.outlet_u_fraction), _port_overlap_1d(flow['dx'], *actual.outlet_bounds, staggered=True), side + 'u-outlet')
            props = params['static_properties'][side]
            for name, key in [('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
                ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'), ('pressure_gradient_Pa_m', 'dP_per_L'),
                ('surface_transfer_W_m2K', 'H_sf'), ('fluid_conductivity_W_mK', 'K_ff'), ('solid_conductivity_W_mK', 'K_ss')]:
                _same(getattr(actual.properties, name), props[key], side + key)
            from sjtu_tpmshx.shared.models.tpms_props import air_cp
            from sjtu_tpmshx.shared.models._native_properties import prandtl
            with warning_scope({}):
                cp = air_cp(getattr(config, 'fluid_' + side).T_in_K)
            _same(actual.properties.cp, cp, side + 'cp')
            _same(actual.properties.pr, prandtl(props['mu'], cp, props['k_f']), side + 'Pr')
        assert [(_text(model.name), _text(model.version)) for model in result.models] == [
            (model.name, model.version) for model in expected.model_refs]
        assert [_text(model.side) for model in result.models] == ['A', 'B', '', '']
        assert [_range(result.ranges[index]) for index in range(result.range_count)] == list(expected.metadata['applicability_inputs'])
        assert [_range(result.ranges[index], last=True) for index in range(result.range_count)] == range_observations(reference_records, last=True)
        assert [_text(result.ranges[index].label) for index in range(result.range_count)] == [
            value.label for value in reference_records.values() if isinstance(value, RangeRecord)]
        assert [_text(result.warnings[index]) for index in range(result.warning_count)] == list(expected.metadata['warnings'])
        saved_events = [(item.kind, _text(item.logger), _text(item.message), item.floating_event)
                        for item in result.events[:result.event_count]]
        assert saved_events == live_events
        assert saved_events == [(1, '', message, 0) for message in expected_warnings] + expected_events
        assert [item for item in saved_events if item[0] == 0] == expected_events
        assert [item[2] for item in saved_events if item[0] == 1] == expected_warnings
        assert not [item for item in saved_events if item[0] == 2]
    finally:
        native.tpmshx_preparation_case_2d_release_v1(ct.byref(result))


def _invalid_configuration(selection):
    config, _ = _configuration('baseline')
    if selection == 'geometry-before-temperature':
        config.geometry.L_dom_m = -1.
        config.fluid_A.T_in_K = -1.
    elif selection == 'zero-grid':
        config.solver.Nx = 0
    elif selection == 'mixed-port':
        config.bc_A.in_w = .01
    elif selection == 'nonfinite-port':
        config.bc_A.in_w = float('inf')
        config.bc_A.out_w = .01
    elif selection == 'outside-port':
        config.bc_A.in_ctr = config.bc_A.out_ctr = .04
        config.bc_A.in_w = config.bc_A.out_w = .01
    elif selection == 'direction':
        config.bc_A.dir = 4
    elif selection == 'geometry-before-speed':
        config.geometry.L_cell_mm = 9.
        config.fluid_A.u_mps = 0.
    elif selection == 'zero-speed':
        config.fluid_A.u_mps = 0.
    elif selection == 'large-domain':
        config.geometry.L_dom_m = 11.
    elif selection == 'nu-window':
        config.fluid_A.u_mps = 1000.
    elif selection == 'port-wall-short-segment':
        config, _ = _configuration('partial')
        config.flags.port_wall_refine = True
        config.solver.Nx = config.solver.Ny = 80
    return config


@pytest.mark.parametrize('selection', ['geometry-before-temperature', 'zero-grid', 'mixed-port',
    'nonfinite-port', 'outside-port', 'direction', 'geometry-before-speed', 'zero-speed',
    'large-domain', 'nu-window', 'port-wall-short-segment'])
def test_native_preparation_keeps_first_physical_error(native, monkeypatch, selection):
    config = _invalid_configuration(selection)
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    with pytest.raises(ValueError) as expected:
        prepare_case(config, case_id='native-preparation-invalid-reference')
    source, result = _input(config), _Result(1, ct.sizeof(_Result))
    before = bytes(result)
    error = ct.create_string_buffer(4096)
    assert native.tpmshx_prepare_case_2d_v1(ct.byref(source), None, None, ct.byref(result),
                                         error, len(error)) == 1
    assert error.value.decode() == str(expected.value)
    assert bytes(result) == before


@pytest.mark.parametrize('selection,expected', [
    ('geometry_mode', 'uniform geometry'), ('df_mode', "df_mode='cfd_smooth'"),
    ('mass_flow', 'prescribed inlet velocity'), ('delta_levelset', 'symmetric delta_levelset=0'),
    ('co2', 'air/air only')])
def test_native_preparation_rejects_unimplemented_modes(native, selection, expected):
    config, _ = _configuration('baseline')
    source = _input(config)
    if selection in ('geometry_mode', 'df_mode'):
        setattr(source, selection, 1)
    elif selection == 'mass_flow':
        source.sides[0].have_mass_flow, source.sides[0].mass_flow_kg_s = 1, .02
    elif selection == 'delta_levelset':
        source.delta_levelset = .1
    else:
        source.sides[1].fluid = 3
    result = _Result(1, ct.sizeof(_Result))
    before, error = bytes(result), ct.create_string_buffer(4096)
    assert native.tpmshx_prepare_case_2d_v1(ct.byref(source), None, None, ct.byref(result),
                                         error, len(error)) == 1
    assert expected in error.value.decode()
    assert bytes(result) == before
