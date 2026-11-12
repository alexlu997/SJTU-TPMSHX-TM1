"""Compare native 3D preparation with the frozen Python 3D stage."""
import ctypes as ct
from dataclasses import replace
from itertools import product
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as fluids
from sjtu_tpmshx.development.tests.test_native_preparation_continuous import _host_events
from sjtu_tpmshx.preprocess.api import _finish_metadata
from sjtu_tpmshx.development.tests import preparation_3d_reference as preparation
from sjtu_tpmshx.shared.domain.compute_config import PartialBCConfig
from sjtu_tpmshx.shared.domain.run_warnings import RangeRecord, range_observations, warning_scope
from sjtu_tpmshx.shared.models import _native_grid as grid
from sjtu_tpmshx.shared.models import _native_preparation_case as abi


_U, _S, _D = abi._U, abi._S, abi._D
_struct, _text, _array, _same = abi._structure, abi._text, abi._array, v1._same
_Inlet = _struct('Inlet3D', [('fluid', _U), *abi._doubles('velocity_m_s temperature_K pressure_Pa'),
    ('port', grid._Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_Input = _struct('Input3D', [('abi_version', _U), ('struct_size', _S),
    ('lengths_m', grid._Scalar * 3), ('counts', _S * 3), ('max_cells', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *abi._doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('geometry_mode', _U), ('df_mode', _U),
    ('kinds', abi._Kinds), ('sco2_nu', abi._Nu)])
_Side = _struct('Side3D', [('axes', ct.c_int32 * 7),
    ('inlet_opening', abi._Array), ('outlet_opening', abi._Array),
    *abi._doubles('rho mu cp k_f'), ('have_drag_application', _U),
    ('drag_evidence', abi._DragEvidence), ('drag_selection', abi._Drag)])
_Result = _struct('Result3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('options', abi._Options), ('widths', abi._Array * 3),
    ('edges', abi._Array * 3), ('geometry', abi._GeometryCache),
    ('uniform_solid_conductivity', _D),
    *((name, abi._Array) for name in ('cell_length', 'wall_thickness', 'total_porosity',
        'side_porosity', 'permeability', 'forchheimer', 'solid_conductivity')),
    ('length_kinds', abi._Kind * 2), ('sides', _Side * 2), ('models', abi._Model * 4),
    ('evidence', abi._Evidence), ('sco2_nu_model_version', abi._Text),
    ('sco2_nu_interpretation', abi._Text), ('sco2_nu_coefficients', (_D * 3) * 2),
    ('co2', abi._Co2), ('notices', ct.POINTER(abi._Text)), ('notice_count', _S),
    ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    library.tpmshx_preparation_case_3d_abi_version_v1.argtypes = []
    library.tpmshx_preparation_case_3d_abi_version_v1.restype = _U
    assert library.tpmshx_preparation_case_3d_abi_version_v1() == 1
    library.tpmshx_prepare_case_3d_v1.argtypes = [ct.POINTER(_Input), ct.POINTER(abi._Options),
        ct.POINTER(abi._Callbacks), ct.POINTER(_Result), ct.POINTER(abi._Failure),
        ct.POINTER(ct.c_char), _S]
    library.tpmshx_prepare_case_3d_v1.restype = ct.c_int
    library.tpmshx_preparation_case_3d_release_v1.argtypes = [ct.POINTER(_Result)]
    library.tpmshx_preparation_case_3d_release_v1.restype = None
    return library


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)


def _kind(value):
    if isinstance(value, np.ndarray):
        return abi._Kind(value.dtype.itemsize * 8, 1, 2)
    if isinstance(value, np.floating):
        return abi._Kind(value.dtype.itemsize * 8, 1, 1)
    return abi._Kind(64, 0, 0)


def _input(config):
    geometry = config.geometry
    source = _Input(1, ct.sizeof(_Input))
    source.lengths_m[:] = tuple(grid._scalar(value) for value in
        (geometry.L_dom_m, geometry.H_dom_m, geometry.Lz_m))
    source.counts[:] = (config.solver.Nx, config.solver.Ny, config.solver.Nz)
    source.max_cells, source.port_wall_refine = 2_000_000, config.flags.port_wall_refine
    source.topology = ('Diamond', 'Gyroid').index(geometry.tpms)
    source.cell_length_mm, source.wall_thickness_mm = geometry.L_cell_mm, geometry.t_wall_mm
    source.solid_conductivity_W_mK, source.delta_levelset = geometry.k_s_W_mK, geometry.delta_levelset
    source.geometry_mode, source.df_mode = int(config.zones.enabled), int(config.df_mode == 'experimental')
    source.kinds = abi._Kinds(*map(_kind, (geometry.L_cell_mm, geometry.t_wall_mm, geometry.k_s_W_mK)))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        raw_port = {'dir': port.dir}
        for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w', 'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
            raw_port[name] = getattr(port, name)
        source.sides[index] = _Inlet(abi._FLUIDS.index(fluid.type), fluid.u_mps,
            fluid.T_in_K, fluid.P_in_Pa, grid._port(raw_port),
            fluid.mass_flow_kg_s is not None, fluid.mass_flow_kg_s or 0.)
        source.kinds.sides[index] = abi._InletKinds(*map(_kind,
            (fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa)))
    settings = config.sco2_nu
    source.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        value = getattr(settings, name)
        source.sco2_nu.have_alpha[index], source.sco2_nu.alpha[index] = value is not None, value or 0.
    source._buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        buffer = ct.create_string_buffer(getattr(settings, name).encode('utf-8'))
        source._buffers.append(buffer)
        setattr(source.sco2_nu, name, abi._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(buffer.value)))
    return source


def _configuration(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = fluids._configuration(topology, pair, mode)
    config.geometry.Lz_m = .042
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
    return config


def _reference(config):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    with warnings.catch_warnings(record=True) as caught, warning_scope({}) as records:
        warnings.simplefilter('always')
        case = preparation.prepare_case(config, case_id='native-3d-reference')
        case = _finish_metadata(case, {}, records)
    return case, records, [(1, '', str(item.message), 0) for item in caught]


def _call(native, config, *, source=None, chi=None, reject_event=False):
    source = _input(config) if source is None else source
    result, failure = _Result(1, ct.sizeof(_Result)), abi._Failure(2, ct.sizeof(abi._Failure))
    options = abi._Options(1, ct.sizeof(abi._Options), chi is not None, config.extrap.allow, chi or 0.)
    error, events = ct.create_string_buffer(4096), []
    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, _text(item.logger), _text(item.message), item.floating_event))
        return int(reject_event)
    callback = abi._EventFunction(event)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), callback, None)
    status = native.tpmshx_prepare_case_3d_v1(ct.byref(source), ct.byref(options),
        ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    return status, result, failure, error.value.decode(), events, source


def _check_drag(value, metadata, side):
    assert bool(value.have_drag_application) == (metadata is not None), side
    if metadata is None:
        return
    drag = value.drag_evidence
    for name, key in [('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
                      ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF')]:
        summary, expected = getattr(drag, name), metadata[key]
        assert bool(summary.scalar) == isinstance(expected, float), side + key
        _same(summary.minimum, expected if summary.scalar else expected['min'], side + key + '.min')
        _same(summary.maximum, expected if summary.scalar else expected['max'], side + key + '.max')
    for name, key in [('scale_permeability', 'scale_K'), ('scale_forchheimer', 'scale_F')]:
        _same(getattr(drag, name), metadata[key], side + key)
    for name in ('campaign', 'scope'):
        assert _text(getattr(drag, name)) == metadata[name], side + name
    selected = value.drag_selection
    assert _text(selected.fluid) == metadata.get('fluid', ''), side
    assert _text(selected.application_scope) == metadata.get('application_scope', ''), side
    assert {_text(item.key): _text(item.value) for item in selected.calibration[:selected.calibration_count]} == metadata.get('calibration', {})
    if 'velocity_window_mps' in metadata:
        for name, key in [('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')]:
            _same(getattr(selected.selection, name),
                  [metadata[key]['min'], metadata[key]['max']], side + key)
        assert bool(selected.selection.flags & 2) == metadata['extrapolated']


def _check_values(result, expected, config, *, side_b_porosity=None):
    shape = tuple(len(expected.grid['d' + axis]) for axis in 'xyz')
    assert tuple(result.input.counts) == shape
    for index, axis in enumerate('xyz'):
        _same(_array(result.widths[index]), expected.grid['d' + axis], 'd' + axis)
        _same(_array(result.edges[index]), expected.grid[axis + '_edges'], axis + '_edges')
    for name, key in [('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'),
        ('total_porosity', 'eps_arr'), ('side_porosity', 'eps_A'),
        ('permeability', 'K_m2'), ('forchheimer', 'cF_per_m'), ('solid_conductivity', 'K_ss')]:
        _same(_array(getattr(result, name), shape), expected.design_fields[key], key)
    _same(_array(result.side_porosity if side_b_porosity is None else side_b_porosity, shape),
          expected.design_fields['eps_B'], 'eps_B')
    for index, key in enumerate(('L_field_m', 't_field_m')):
        assert result.length_kinds[index].precision == expected.design_fields[key].dtype.itemsize * 8, key
    params, prepared = expected.parameters, expected.parameters['prepared']
    for name, key in [('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
                      ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h')]:
        _same(getattr(result.geometry, name), prepared['geometry'][key], key)
    _same(result.uniform_solid_conductivity, prepared['geometry']['K_ss'], 'nominal K_ss')
    for index, side in enumerate('AB'):
        actual, axis = result.sides[index], prepared['axes'][side]
        assert tuple(actual.axes) == (axis['cross1_real_axis'], axis['stream_real_axis'],
            axis['cross2_real_axis'], *axis['solver_to_real_perm'], int(axis['is_reverse']))
        cross_shape = (axis['N_cross1'], axis['N_cross2'])
        for end in ('inlet', 'outlet'):
            _same(_array(getattr(actual, end + '_opening'), cross_shape),
                  prepared['openings'][side][end], side + end)
        for name, key in [('rho', 'rho'), ('mu', 'mu'), ('cp', 'cp'), ('k_f', 'k')]:
            _same(getattr(actual, name), prepared['properties'][side][key], side + key)
        metadata = (params['df_application'] or {}).get(side)
        _check_drag(actual, metadata, side)
        assert bool(actual.drag_selection.have_selection) == (config.df_mode == 'experimental'
            and getattr(config, 'fluid_' + side).type != 'co2')
    assert [(_text(item.name), _text(item.version), _text(item.side)) for item in result.models] == [
        (item.name, item.version, 'AB'[index] if index < 2 else '')
        for index, item in enumerate(expected.model_refs)]


def _check_evidence(result, expected, records, events, live, config):
    actual = result.evidence
    assert [v1._range(actual.ranges[i]) for i in range(actual.range_count)] == list(expected.metadata['applicability_inputs'])
    for last in (False, True):
        observations = []
        for index in range(actual.range_count):
            row = v1._range(actual.ranges[index], last=last)
            if actual.range_bounds_list[index]:
                row['bounds'] = list(row['bounds'])
            observations.append(row)
        assert observations == range_observations(records, last=last)
    assert [_text(actual.ranges[i].label) for i in range(actual.range_count)] == [
        value.label for value in records.values() if isinstance(value, RangeRecord)]
    assert [_text(item) for item in actual.warnings[:actual.warning_count]] == list(expected.metadata['warnings'])
    saved = [(item.kind, _text(item.logger), _text(item.message), item.floating_event)
             for item in actual.events[:actual.event_count]]
    assert saved == live
    assert _host_events(saved) == events
    assert [_text(item) for item in result.notices[:result.notice_count]] == list(expected.metadata['notices'])
    selected = config.sco2_nu
    assert result.input.sco2_nu.mode == (selected.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        value = getattr(selected, name)
        assert bool(result.input.sco2_nu.have_alpha[index]) == (value is not None)
        if value is not None:
            _same(result.input.sco2_nu.alpha[index], value, name)
    for name in ('parameter_version', 'source', 'applicability'):
        assert _text(getattr(result.input.sco2_nu, name)) == getattr(selected, name)
    model = expected.metadata['model_metadata']['sco2_nu']
    assert _text(result.sco2_nu_model_version) == model['model_version']
    if selected.mode == 'experimental':
        assert _text(result.sco2_nu_interpretation) == model['interpretation']
    else:
        for index, topology in enumerate(('Diamond', 'Gyroid')):
            _same(result.sco2_nu_coefficients[index],
                  [model['coefficients'][topology][key] for key in ('c', 'a', 'd')], topology)
    model = expected.metadata['model_metadata'].get('co2')
    assert bool(result.co2.active) == (model is not None)
    if model is not None:
        assert ['AB'[i] for i, flag in enumerate(result.co2.sides) if flag] == list(model['sides'])
        for name in ('version', 'application_version', 'pressure_model', 'correction_source', 'property_model', 'common_geometry'):
            assert _text(getattr(result.co2, name)) == model[name]
        for name in ('pressure_multiplier', 'scale_K', 'scale_F', 'nu_multiplier', 'nu_floor_multiplier'):
            _same(getattr(result.co2, name), model[name], name)
        _same(result.co2.re_range, model['Re_range'], 'CO2 Re range')
        _same(result.co2.pr_range, model['Pr_range'], 'CO2 Pr range')


def _compare(native, config, *, chi=None, source=None):
    expected, records, events = _reference(config)
    status, result, failure, error, live, source = _call(native, config, chi=chi, source=source)
    assert status == 0, error
    try:
        assert not failure.kind
        assert bytes(result.input.kinds) == bytes(source.kinds)
        _check_values(result, expected, config)
        _check_evidence(result, expected, records, events, live, config)
    finally:
        native.tpmshx_preparation_case_3d_release_v1(ct.byref(result))
    assert not result.owner
    native.tpmshx_preparation_case_3d_release_v1(ct.byref(result))


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(abi._FLUIDS, repeat=2)))
@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_native_3d_ordered_fluid_pairs(native, topology, pair, mode):
    _compare(native, _configuration(topology, pair, mode))


def _partial_ports(config, direction, cross2=True):
    lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
    for side, selected in (('A', direction), ('B', (direction + 3) % 6)):
        cross1, _, second, *_ = grid.axis_map(selected)
        span, depth = lengths[cross1], lengths[second]
        port = PartialBCConfig(dir=selected, in_ctr=.43 * span, in_w=.57 * span,
            out_ctr=.59 * span, out_w=.49 * span)
        if cross2:
            port.in_z_ctr, port.in_z_w = .44 * depth, .63 * depth
            port.out_z_ctr, port.out_z_w = .62 * depth, .45 * depth
        setattr(config, 'bc_' + side, port)


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('ports', ['full', 'partial', 'cross2', 'port-wall'])
def test_native_3d_physical_axes_and_ports(native, direction, ports):
    config = _configuration()
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .081, .063, .047
    config.bc_A.dir, config.bc_B.dir = direction, (direction + 3) % 6
    if ports != 'full':
        _partial_ports(config, direction, cross2=ports != 'partial')
    if ports == 'port-wall':
        lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
        for side in 'AB':
            port = getattr(config, 'bc_' + side)
            depth = lengths[grid.axis_map(port.dir)[2]]
            port.in_z_ctr, port.in_z_w = .43 * depth, .57 * depth
            port.out_z_ctr, port.out_z_w = .59 * depth, .49 * depth
        config.flags.port_wall_refine = True
        config.solver.Nx, config.solver.Ny, config.solver.Nz = 52, 54, 56
    _compare(native, config)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('selection', ['geometry', 'material', 'material-array', 'inlet', 'grid-port'])
def test_native_3d_scalar_precision(native, dtype, selection):
    config = _configuration('Diamond', ('air', 'water'))
    if selection == 'geometry':
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = dtype(6.125), dtype(.42)
    elif selection.startswith('material'):
        value = dtype(1.337)
        config.geometry.k_s_W_mK = np.asarray(value) if selection.endswith('array') else value
    elif selection == 'inlet':
        config.fluid_A.u_mps, config.fluid_A.T_in_K = dtype(6.12), dtype(351.13)
        config.fluid_A.P_in_Pa = dtype(30000. if dtype is np.float16 else 201234.5)
        config.fluid_B.T_in_K = dtype(321.13)
    else:
        config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
        _partial_ports(config, 5)
        for side in 'AB':
            port = getattr(config, 'bc_' + side)
            for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w', 'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
                setattr(port, name, dtype(getattr(port, name)))
    _compare(native, config)


def test_native_3d_mixed_integer_grid_scalars(native):
    config = _configuration()
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = np.int16(1), np.int32(2), np.int64(3)
    _partial_ports(config, 4)
    _compare(native, config)


@pytest.mark.parametrize('selection', ['chi', 'co2-typed', 'saved-nu', 'inactive-nu', 'smooth-provenance'])
def test_native_3d_model_selection_and_owned_text(native, monkeypatch, selection):
    config = _configuration('Gyroid', ('sco2', 'water'))
    chi = None
    if selection == 'chi':
        chi = .65
        monkeypatch.setenv('TPMSHX_CHI_S', str(chi))
    elif selection == 'co2-typed':
        config.fluid_A.type = 'co2'
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = np.float32(6.125), np.float32(.42)
        config.geometry.k_s_W_mK = np.float16(1.337)
    else:
        config.sco2_nu = replace(config.sco2_nu,
            mode='cfd_smooth' if selection == 'smooth-provenance' else 'experimental',
            alpha_D=1.13, alpha_G=2.27, parameter_version='saved-test-version',
            source='\u00a0保留实验来源\u3000', applicability='保留适用范围')
        if selection == 'inactive-nu':
            config.fluid_A.type = 'co2'
    expected, records, events = _reference(config)
    status, result, failure, error, live, source = _call(native, config, chi=chi)
    assert status == 0, error
    try:
        assert not failure.kind
        source.cell_length_mm = 4.
        for buffer in source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        assert result.input.cell_length_mm == config.geometry.L_cell_mm
        _check_values(result, expected, config)
        _check_evidence(result, expected, records, events, live, config)
    finally:
        native.tpmshx_preparation_case_3d_release_v1(ct.byref(result))


def test_native_3d_missing_first_axis_values_use_full_faces(native):
    config = _configuration()
    source = _input(config)
    for side in source.sides:
        for end in side.port.present:
            end[0] = end[1] = 0
    expected, records, events = _reference(config)
    status, result, _, error, live, _ = _call(native, config, source=source)
    assert status == 0, error
    try:
        _check_values(result, expected, config)
        _check_evidence(result, expected, records, events, live, config)
    finally:
        native.tpmshx_preparation_case_3d_release_v1(ct.byref(result))


@pytest.mark.parametrize('selection', ['water-vapor', 'water-ice', 'water-before-co2',
    'co2-triple', 'co2-critical', 'sco2-temperature', 'sco2-before-water',
    'nu-alpha', 'nu-source', 'geometry-before-state', 'experimental-speed',
    'experimental-geometry', 'experimental-domain', 'experimental-before-water', 'reject-extrapolation'])
def test_native_3d_first_failure_and_cause(native, selection):
    config = fluids._invalid_configuration(selection)
    config.geometry.Lz_m, config.solver.Nz = .042, 4
    failure, _ = _compare_failure(native, config)
    if selection.startswith(('water-', 'co2-')):
        assert failure.have_property and failure.property.reason


def _compare_failure(native, config):
    with warnings.catch_warnings(record=True) as caught, warning_scope({}), pytest.raises(ValueError) as raised:
        warnings.simplefilter('always')
        preparation.prepare_case(config, case_id='native-3d-invalid-reference')
    expected = raised.value
    status, result, failure, error, live, _ = _call(native, config)
    assert status != 0
    assert bytes(result) == bytes(_Result(1, ct.sizeof(_Result)))
    assert error == str(expected)
    assert failure.kind == fluids._error_kind(expected)
    causes, cause = [], expected.__cause__
    while cause is not None:
        causes.append((fluids._error_kind(cause), str(cause)))
        cause = cause.__cause__
    assert [(item.kind, item.message.decode()) for item in failure.causes[:failure.cause_count]] == causes
    assert _host_events(live) == [(1, '', str(item.message), 0) for item in caught]
    return failure, live


@pytest.mark.parametrize('selection', ['spatial', 'asymmetric', 'mass-flow', 'inactive',
    'direction', 'zero-depth', 'zero-count', 'two-dimensional', 'cap', 'flag', 'kind', 'df-mode'])
def test_native_3d_rejects_invalid_raw_scope(native, selection):
    config = _configuration()
    source = _input(config)
    if selection == 'spatial':
        source.geometry_mode = 1
    elif selection == 'asymmetric':
        source.delta_levelset = .1
    elif selection == 'mass-flow':
        source.sides[0].have_mass_flow, source.sides[0].mass_flow_kg_s = 1, .02
    elif selection == 'inactive':
        source.sides[1].port.active = 0
    elif selection == 'direction':
        source.sides[0].port.direction = 6
    elif selection == 'zero-depth':
        source.lengths_m[2].value = 0.
    elif selection == 'zero-count':
        source.counts[0] = 0
    elif selection == 'two-dimensional':
        source.counts[2] = 1
    elif selection == 'cap':
        source.max_cells = 119
    elif selection == 'flag':
        source.port_wall_refine = 2
    elif selection == 'kind':
        source.lengths_m[0].precision = 80
    else:
        source.df_mode = 2
    status, result, failure, error, _, _ = _call(native, config, source=source)
    assert status != 0, selection
    assert error, selection
    assert bytes(result) == bytes(_Result(1, ct.sizeof(_Result))), selection
    assert failure.kind in (0, 1), (selection, failure.kind)
    if selection == 'cap':
        assert '6x5x4' in error and '119' in error


def test_native_3d_cell_cap_is_explicit(native, monkeypatch):
    config = _configuration()
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '1')
    source = _input(config)
    source.max_cells = 120
    status, result, _, error, _, _ = _call(native, config, source=source)
    assert status == 0, error
    try:
        assert result.total_porosity.size == 120
    finally:
        native.tpmshx_preparation_case_3d_release_v1(ct.byref(result))


def test_native_3d_callback_failure_does_not_publish(native):
    config = _configuration()
    config.fluid_A.u_mps = 1000.
    status, result, failure, error, events, _ = _call(native, config, reject_event=True)
    assert status != 0 and error
    assert len(events) == 1
    assert failure.kind == 3
    assert bytes(result) == bytes(_Result(1, ct.sizeof(_Result)))


@pytest.mark.parametrize('selection', ['input-error', 'result-error', 'failure-error',
    'input-result', 'input-failure', 'result-failure', 'text-result'])
def test_native_3d_overlapping_storage_is_unchanged(native, selection):
    source, result = _input(_configuration()), _Result(1, ct.sizeof(_Result))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(b'unchanged', 4096)
    source_pointer, result_pointer = ct.pointer(source), ct.pointer(result)
    failure_pointer, error_pointer, capacity = ct.pointer(failure), error, len(error)
    backing = None
    if selection.endswith('-error'):
        target = {'input-error': source, 'result-error': result, 'failure-error': failure}[selection]
        error_pointer, capacity = ct.cast(ct.byref(target, 8), ct.POINTER(ct.c_char)), 16
    elif selection == 'text-result':
        source.sco2_nu.parameter_version = abi._Text(ct.cast(ct.pointer(result), ct.POINTER(ct.c_char)), 16)
    else:
        backing = ct.create_string_buffer(max(ct.sizeof(_Input), ct.sizeof(_Result), ct.sizeof(abi._Failure)) + 8)
        if selection.startswith('input-'):
            ct.memmove(backing, ct.byref(source), ct.sizeof(source))
            source_pointer = ct.cast(backing, ct.POINTER(_Input))
            if selection == 'input-result':
                result_pointer = ct.cast(ct.byref(backing, 8), ct.POINTER(_Result))
            else:
                failure_pointer = ct.cast(ct.byref(backing, 8), ct.POINTER(abi._Failure))
        else:
            ct.memmove(backing, ct.byref(result), ct.sizeof(result))
            result_pointer = ct.cast(backing, ct.POINTER(_Result))
            failure_pointer = ct.cast(ct.byref(backing, 8), ct.POINTER(abi._Failure))
    objects = [source, result, failure, error] + ([] if backing is None else [backing])
    before = [bytes(value) for value in objects]
    assert native.tpmshx_prepare_case_3d_v1(source_pointer, None, None,
        result_pointer, failure_pointer, error_pointer, capacity) != 0
    assert [bytes(value) for value in objects] == before


@pytest.mark.parametrize('record', ['input', 'options', 'callbacks', 'result', 'failure'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_native_3d_rejects_incompatible_records(native, record, field):
    source, result = _input(_configuration()), _Result(1, ct.sizeof(_Result))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks))
    selected = {'input': source, 'options': options, 'callbacks': callbacks,
                'result': result, 'failure': failure}[record]
    setattr(selected, field, 99 if field == 'abi_version' else 1)
    before = bytes(result)
    assert native.tpmshx_prepare_case_3d_v1(ct.byref(source), ct.byref(options),
        ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error)) != 0
    assert error.value
    assert bytes(result) == before


def test_native_3d_rejects_reuse_before_release(native):
    config = _configuration()
    status, result, failure, error, _, source = _call(native, config)
    assert status == 0, error
    before = bytes(result)
    values = _array(result.permeability)
    error = ct.create_string_buffer(4096)
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    try:
        assert native.tpmshx_prepare_case_3d_v1(ct.byref(source), ct.byref(options), None,
            ct.byref(result), ct.byref(failure), error, len(error)) != 0
        assert 'release' in error.value.decode()
        assert bytes(result) == before
        _same(_array(result.permeability), values, 'retained result')
    finally:
        native.tpmshx_preparation_case_3d_release_v1(ct.byref(result))
    native.tpmshx_preparation_case_3d_release_v1(None)


@pytest.mark.parametrize('topology,pair,cell_type,wall_type', [
    ('Diamond', ('air', 'water'), float, np.float16),
    ('Diamond', ('air', 'water'), np.float16, float),
    ('Gyroid', ('air', 'water'), np.float16, np.float32),
    ('Gyroid', ('co2', 'water'), np.float32, np.float16),
])
def test_native_3d_mixed_geometry_precision(native, topology, pair, cell_type, wall_type):
    config = _configuration(topology, pair)
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = cell_type(6.125), wall_type(.42)
    _compare(native, config)


@pytest.mark.parametrize('selection', ['negative-full-face', 'edge-touching'])
def test_native_3d_port_normalization_preserves_second_axis(native, selection):
    config = _configuration()
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .125, .0625, .03125
    lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
    for side, direction in (('A', 1), ('B', 5)):
        first, _, second, *_ = grid.axis_map(direction)
        span, depth = lengths[first], lengths[second]
        port = PartialBCConfig(dir=direction, in_z_ctr=depth / 4., in_z_w=depth / 2.,
            out_z_ctr=depth * .75, out_z_w=depth / 2.)
        if selection == 'negative-full-face':
            port.in_ctr, port.out_ctr = np.nan, np.inf
            port.in_w, port.out_w = -.01, 0.
        else:
            port.in_ctr, port.in_w = span / 4., span / 2.
            port.out_ctr, port.out_w = span * .75, span / 2.
        setattr(config, 'bc_' + side, port)
    _compare(native, config)


@pytest.mark.parametrize('selection', ['negative-domain-before-state', 'nan-wall-before-port',
    'infinite-depth', 'negative-pressure-before-count', 'zero-speed-before-state',
    'mixed-widths', 'nonfinite-full-width', 'nan-port-centre', 'incomplete-cross2',
    'zero-cross2-width', 'nonfinite-cross2', 'outside-both-cross-axes-z',
    'outside-both-cross-axes-y'])
def test_native_3d_boundary_failure_order(native, selection):
    config = _configuration()
    if selection == 'negative-domain-before-state':
        config.geometry.L_dom_m, config.fluid_B.T_in_K = -.01, 450.
    elif selection == 'nan-wall-before-port':
        config.geometry.t_wall_mm = np.nan
        config.bc_A.in_w, config.bc_A.out_w = 0., .01
    elif selection == 'infinite-depth':
        config.geometry.Lz_m = np.inf
    elif selection == 'negative-pressure-before-count':
        config.fluid_A.P_in_Pa, config.solver.Nx = -1., 0
    elif selection == 'zero-speed-before-state':
        config.fluid_A.u_mps, config.fluid_B.T_in_K = 0., 450.
    elif selection == 'mixed-widths':
        config.bc_A.in_w, config.bc_A.out_w = 0., .01
    elif selection == 'nonfinite-full-width':
        config.bc_A.in_w = config.bc_A.out_w = -np.inf
    else:
        _partial_ports(config, 0 if selection == 'outside-both-cross-axes-z' else 5)
        port = config.bc_A
        if selection == 'nan-port-centre':
            port.in_ctr, config.fluid_A.u_mps = np.nan, 0.
        elif selection == 'incomplete-cross2':
            port.in_z_w, port.out_z_ctr = None, None
        elif selection == 'zero-cross2-width':
            port.in_z_w = 0.
        elif selection == 'nonfinite-cross2':
            port.in_z_ctr, port.out_z_w = np.inf, np.nan
        else:
            lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
            first, _, second, *_ = grid.axis_map(port.dir)
            port.in_ctr, port.out_ctr = -.01, lengths[first] + .01
            port.in_z_ctr, port.out_z_ctr = -.01, lengths[second] + .01
    _compare_failure(native, config)


def test_native_3d_keeps_events_before_later_side_failure(native):
    config = _configuration(pair=('air', 'co2'))
    config.fluid_A.u_mps, config.fluid_B.T_in_K = 1000., 200.
    failure, live = _compare_failure(native, config)
    assert live and live[0][0] == 1
    assert failure.side == 1 and failure.have_property


@pytest.mark.parametrize('missing', ['input', 'result', 'failure'])
def test_native_3d_requires_nonnull_records(native, missing):
    source, result = _input(_configuration()), _Result(1, ct.sizeof(_Result))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    before = bytes(result), bytes(failure)
    assert native.tpmshx_prepare_case_3d_v1(None if missing == 'input' else ct.byref(source),
        None, None, None if missing == 'result' else ct.byref(result),
        None if missing == 'failure' else ct.byref(failure), error, len(error)) != 0
    assert error.value
    assert (bytes(result), bytes(failure)) == before


def test_native_3d_empty_optional_text_has_no_storage(native):
    config = _configuration()
    source = _input(config)
    for name in ('parameter_version', 'source', 'applicability'):
        setattr(source.sco2_nu, name, abi._Text())
    _compare(native, config, source=source)


def test_native_3d_nonempty_text_requires_storage(native):
    source, result = _input(_configuration()), _Result(1, ct.sizeof(_Result))
    source.sco2_nu.source = abi._Text(None, 1)
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(b'unchanged', 4096)
    before = bytes(result), bytes(failure), bytes(error)
    assert native.tpmshx_prepare_case_3d_v1(ct.byref(source), None, None,
        ct.byref(result), ct.byref(failure), error, len(error)) != 0
    assert (bytes(result), bytes(failure), bytes(error)) == before


@pytest.mark.parametrize('field,value', [
    ('L_cell_mm', np.nan), ('t_wall_mm', np.nan), ('k_s_W_mK', -1.),
])
def test_native_3d_geometry_failure_precedes_depth(native, field, value):
    config = _configuration()
    setattr(config.geometry, field, value)
    config.geometry.Lz_m = np.inf
    _compare_failure(native, config)
