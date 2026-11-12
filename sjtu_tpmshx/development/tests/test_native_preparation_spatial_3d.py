"""Compare raw grid and offset preparation with the unchanged Python 3D path."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import os

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_flow_3d as flow
from sjtu_tpmshx.shared.domain.compute_config import ZoneInputConfig

three, abi, v1, mass = flow.three, flow.abi, flow.v1, flow.flow
_U, _S, _D, _struct = abi._U, abi._S, abi._D, abi._structure
_Cell = _struct('GridCell3D', [('bounds', three.grid._Scalar * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D)])
_Input = _struct('SpatialInput3D', [('abi_version', _U), ('struct_size', _S),
    ('values', flow._Input), ('cells', ct.POINTER(_Cell)), ('cell_count', _S)])
_Flow = _struct('SpatialFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', flow._Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S),
    ('owner', ct.c_void_p)])
_Result = _struct('SpatialCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', three._Result), ('flow', flow._Flow),
    ('cells', ct.POINTER(_Cell)), ('cell_count', _S), ('side_b_porosity', abi._Array),
    ('area_density_per_m', abi._Array), ('hydraulic_diameter_m', abi._Array),
    ('thermal_porosity', abi._Array), ('split_a', _D), ('have_side_geometry', _U),
    ('side_geometry', (_D * 4) * 2), ('owner', ct.c_void_p)])
_OPERATIONS = ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case')


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    version = library.tpmshx_preparation_spatial_3d_abi_version_v4
    version.argtypes, version.restype = [], _U
    assert version() == 4
    for operation in _OPERATIONS:
        result = _Result if operation == 'prepare_flow_case' else _Flow
        function = getattr(library, 'tpmshx_' + operation + '_3d_v4')
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(abi._Options),
            ct.POINTER(abi._Callbacks), ct.POINTER(result), ct.POINTER(abi._Failure),
            ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    for name, result in (('flow', _Flow), ('case', _Result)):
        release = getattr(library, 'tpmshx_preparation_spatial_' + name + '_3d_release_v4')
        release.argtypes, release.restype = [ct.POINTER(result)], None
    return library


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)


def _configuration(topology='Gyroid', pair=('air', 'water'), *, spatial=True, delta=.12,
                   mode='cfd_smooth'):
    config = three._configuration(topology, pair, mode)
    config.geometry.delta_levelset = delta
    if spatial:
        config.zones = ZoneInputConfig(enabled=True, axis='grid', grid={'cells': [
            dict(x0=0., x1=.65, y0=0., y1=.55, L=4.25, t=.33),
            dict(x0=.35, x1=.85, y0=.2, y1=.9, L=7.5, t=.54),
            dict(x0=0., x1=1., y0=.4, y1=.6, L=5.5, t=.42)]})
    return config


def _input(config, targets=None):
    values = flow._input(config, targets)
    values.input.geometry_mode = 2 if config.zones.enabled else 0
    rows = config.zones.grid['cells'] if config.zones.enabled else []
    cells = (_Cell * len(rows))()
    for index, row in enumerate(rows):
        cells[index].bounds[:] = [three.grid._scalar(row[key]) for key in ('x0', 'x1', 'y0', 'y1')]
        cells[index].cell_length_mm, cells[index].wall_thickness_mm = float(row['L']), float(row['t'])
    source = _Input(4, ct.sizeof(_Input), values, cells, len(cells))
    source._values, source._cells = values, cells
    return source


def _call(native, operation, config, targets=None, *, source=None, chi=None, reject_event=False):
    source = _input(config, targets) if source is None else source
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(4, ct.sizeof(result_type))
    failure = abi._Failure(2, ct.sizeof(abi._Failure))
    options = abi._Options(1, ct.sizeof(abi._Options), chi is not None, config.extrap.allow, chi or 0.)
    error, events = ct.create_string_buffer(4096), []

    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, abi._text(item.logger), abi._text(item.message), item.floating_event))
        return int(reject_event)

    callback = abi._EventFunction(event)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), callback, None)
    buffers = source._values._source._buffers
    before = bytes(source), bytes(source._cells), [bytes(buffer) for buffer in buffers]
    status = getattr(native, 'tpmshx_' + operation + '_3d_v4')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert (bytes(source), bytes(source._cells), [bytes(buffer) for buffer in buffers]) == before
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = 'case' if isinstance(result, _Result) else 'flow'
    release = getattr(native, 'tpmshx_preparation_spatial_' + name + '_3d_release_v4')
    release(ct.byref(result))
    assert not result.owner
    release(ct.byref(result))


def _snapshot(result, config):
    rows = config.zones.grid['cells'] if config.zones.enabled else []
    assert result.cell_count == len(rows)
    for index, row in enumerate(rows):
        actual = result.cells[index]
        for bound, key in zip(actual.bounds, ('x0', 'x1', 'y0', 'y1')):
            assert v1._struct_values(bound) == v1._struct_values(three.grid._scalar(row[key]))
        v1._same([actual.cell_length_mm, actual.wall_thickness_mm],
            [float(row['L']), float(row['t'])], 'owned rectangle ' + str(index))


def _full(native, monkeypatch, config, targets=None, *, chi=None):
    before = deepcopy(asdict(config))
    with monkeypatch.context() as patch:
        if chi is not None:
            patch.setenv('TPMSHX_CHI_S', str(chi))
        expected, state = flow._reference(monkeypatch, 'prepare_flow_case', config, targets)
    status, result, failure, error, live, source = _call(
        native, 'prepare_flow_case', config, targets, chi=chi)
    assert status == 0, error
    try:
        assert result.owner and not result.prepared.owner and not result.flow.owner and not failure.kind
        assert state['geometry_calls'] == 1
        _snapshot(result, config)
        if source.cell_count:
            source._cells[0].cell_length_mm = -1.
            source._cells[0].bounds[0].value = -1.
        source.values.input.cell_length_mm = -1.
        for buffer in source._values._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        _snapshot(result, config)
        assert result.prepared.input.cell_length_mm == config.geometry.L_cell_mm
        for name in ('cell_length', 'wall_thickness', 'solid_conductivity'):
            assert v1._struct_values(getattr(result.prepared.input.kinds, name)) == v1._struct_values(
                getattr(source.values.input.kinds, name))
        three._check_values(result.prepared, expected, state['resolved'],
            side_b_porosity=result.side_b_porosity)
        three._check_evidence(result.prepared, expected, state['records'],
            state['events'], live, state['resolved'])
        have_targets = targets is not None or any(
            getattr(config, 'fluid_' + side).mass_flow_kg_s is not None for side in 'AB')
        assert bool(result.flow.have_capacities) == have_targets
        if have_targets:
            flow._resolved(result.flow, state['resolved'])
            flow._evidence(result.flow.evidence, state['capacity_records'])
            assert three._host_events(mass._events(result.flow.evidence)) == state['capacity_events']
        else:
            assert result.flow.evidence.range_count == result.flow.evidence.event_count == 0
        thermal = expected.parameters['thermal_geometry']
        v1._same(result.split_a, thermal['split_A'], 'global thermal split')
        assert bool(result.have_side_geometry) == (thermal['side_geometry'] is not None)
        if result.have_side_geometry:
            for index, side in enumerate('AB'):
                v1._same(result.side_geometry[index], thermal['side_geometry'][side], side + ' thermal surfaces')
        for name, key in (('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'),
                          ('thermal_porosity', 'epsilon')):
            if thermal['fields'] is None:
                assert getattr(result, name).size == 0
            else:
                shape = expected.design_fields['eps_arr'].shape
                v1._same(abi._array(getattr(result, name), shape), thermal['fields'][key], key)
        address_a = ct.cast(result.prepared.side_porosity.data, ct.c_void_p).value
        address_b = ct.cast(result.side_b_porosity.data, ct.c_void_p).value
        assert (address_a == address_b) == (config.geometry.delta_levelset == 0.)
        assert result.side_b_porosity.size == result.prepared.side_porosity.size
    finally:
        _release(native, result)
    assert asdict(config) == before
    return expected, state


def _query(native, monkeypatch, operation, config, targets=None):
    before = deepcopy(asdict(config))
    expected, state = flow._reference(monkeypatch, operation, config, targets, scoped=True)
    status, result, failure, error, live, source = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        assert result.owner and not result.flow.owner and not failure.kind
        _snapshot(result, config)
        if source.cell_count:
            source._cells[0].cell_length_mm = -1.
        _snapshot(result, config)
        flow._evidence(result.flow.evidence, state['records'])
        assert three._host_events(live) == state['events']
        assert mass._events(result.flow.evidence) == live
        if operation == 'prepare_inlet_mass_capacities':
            assert result.flow.have_capacities and state['geometry_calls'] == 1
            for index, side in enumerate('AB'):
                mass._scalar(result.flow.capacities[index], expected[side])
        else:
            flow._resolved(result.flow, expected)
    finally:
        _release(native, result)
    assert asdict(config) == before
    return expected, state


def _failure(native, monkeypatch, operation, config, targets=None, *, source=None):
    state = {}
    with pytest.raises((ValueError, ZeroDivisionError)) as reference:
        flow._reference(monkeypatch, operation, config, targets, scoped=True, state=state)
    status, result, failure, error, live, _ = _call(native, operation, config, targets, source=source)
    assert status != 0 and error == str(reference.value)
    assert failure.kind == three.fluids._error_kind(reference.value)
    assert bytes(result) == bytes(type(result)(4, ct.sizeof(result)))
    assert three._host_events(live) == state['events']
    causes, cause = [], reference.value.__cause__
    while cause is not None:
        causes.append((three.fluids._error_kind(cause), str(cause)))
        cause = cause.__cause__
    assert [(item.kind, item.message.decode()) for item in failure.causes[:failure.cause_count]] == causes
    _release(native, result)
    return error


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water'), repeat=2)))
@pytest.mark.parametrize('spatial', [False, True], ids=['uniform', 'grid'])
@pytest.mark.parametrize('delta', [0., .12])
def test_spatial_3d_fields_match_original(native, monkeypatch, topology, pair, spatial, delta):
    expected, _ = _full(native, monkeypatch, _configuration(topology, pair, spatial=spatial, delta=delta))
    assert expected.metadata['design_mode'] == ('xy_extruded' if spatial else 'uniform')


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('spatial', [False, True])
def test_spatial_3d_negative_offset_keeps_both_global_surfaces(native, monkeypatch, topology, spatial):
    config = _configuration(topology, spatial=spatial, delta=-.12)
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.25, .45
    expected, _ = _full(native, monkeypatch, config)
    assert expected.parameters['thermal_geometry']['split_A'] < .5
    assert np.all(expected.design_fields['eps_A'] < expected.design_fields['eps_B'])


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('delta', [-.12, .12])
def test_spatial_3d_explicit_capacity_resolve_and_full(native, monkeypatch, topology, spatial, delta):
    config = _configuration(topology, spatial=spatial, delta=delta)
    capacities, _ = _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    stale = replace(config, fluid_A=replace(config.fluid_A, u_mps=-99., mass_flow_kg_s=.9),
        fluid_B=replace(config.fluid_B, u_mps=-88., mass_flow_kg_s=.8))
    _query(native, monkeypatch, 'resolve_inlet_flow', stale, targets)
    expected, _ = _full(native, monkeypatch, stale, targets)
    assert 'inlet_inputs' not in expected.parameters


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
def test_spatial_3d_configured_and_mixed_flow_ports(native, monkeypatch, direction, sides):
    config = _configuration(delta=.12 if direction % 2 else -.12)
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .081, .063, .047
    three._partial_ports(config, direction)
    capacities, _ = _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config)
    for side in sides:
        fluid = getattr(config, 'fluid_' + side)
        setattr(config, 'fluid_' + side, replace(fluid,
            u_mps=-99., mass_flow_kg_s=float(capacities[side] * fluid.u_mps)))
    _query(native, monkeypatch, 'resolve_inlet_flow', config)
    expected, state = _full(native, monkeypatch, config)
    assert set(expected.parameters['inlet_inputs']) == {'A', 'B'}
    for side in set('AB') - set(sides):
        assert getattr(state['resolved'], 'fluid_' + side).u_mps == getattr(config, 'fluid_' + side).u_mps


@pytest.mark.parametrize('direction,delta', [(0, 0.), (5, .12)])
def test_spatial_3d_uses_actual_refined_xy_centres(native, monkeypatch, direction, delta):
    config = _configuration(delta=delta)
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .081, .063, .047
    three._partial_ports(config, direction)
    lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
    for side in 'AB':
        port = getattr(config, 'bc_' + side)
        depth = lengths[three.grid.axis_map(port.dir)[2]]
        port.in_z_ctr, port.in_z_w = .43 * depth, .57 * depth
        port.out_z_ctr, port.out_z_w = .59 * depth, .49 * depth
    config.flags.port_wall_refine = True
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 52, 54, 56
    expected, _ = _full(native, monkeypatch, config)
    assert any(np.ptp(expected.grid['d' + axis]) > 0 for axis in 'xyz')
    for key in ('L_field_m', 't_field_m', 'eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m'):
        values = expected.design_fields[key]
        v1._same(values, np.repeat(values[:, :, :1], values.shape[2], axis=2), key + ' extrusion')


@pytest.mark.parametrize('selection', ['gaps', 'reverse-overlap', 'no-hit', 'overwritten-nan', 'overwritten-domain'])
def test_spatial_3d_rectangle_defaults_and_late_overwrite(native, monkeypatch, selection):
    config = _configuration(delta=0.)
    rows = config.zones.grid['cells']
    if selection == 'gaps':
        del rows[1:]
    elif selection == 'reverse-overlap':
        rows.reverse()
    elif selection == 'no-hit':
        rows.append(dict(x0=0., x1=.001, y0=0., y1=1., L=float('nan'), t=float('nan')))
    else:
        value = float('nan') if selection == 'overwritten-nan' else 9.
        rows[:] = [dict(x0=0., x1=1., y0=0., y1=1., L=value, t=.4),
                   dict(x0=0., x1=1., y0=0., y1=1., L=6.25, t=.45)]
    _full(native, monkeypatch, config)


def test_spatial_3d_only_smoothed_local_values_enter_the_cfd_table(native, monkeypatch):
    config = _configuration(delta=0.)
    config.zones.grid['cells'] = [dict(x0=0., x1=1., y0=0., y1=1., L=6., t=.4),
        dict(x0=0., x1=.1, y0=0., y1=.11, L=9., t=.4)]
    expected, _ = _full(native, monkeypatch, config)
    assert np.all((expected.design_fields['L_field_m'] >= .004) &
                  (expected.design_fields['L_field_m'] <= .008))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_spatial_3d_retains_typed_rectangle_bounds(native, monkeypatch, dtype):
    config = _configuration(delta=0.)
    for row in config.zones.grid['cells']:
        for key in ('x0', 'x1', 'y0', 'y1'):
            row[key] = dtype(row[key])
        row['L'], row['t'] = dtype(row['L']), dtype(row['t'])
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('selection', ['geometry', 'material-array', 'inlet', 'grid-port'])
def test_spatial_3d_nominal_and_grid_scalar_precision(native, monkeypatch, dtype, selection):
    config = _configuration('Diamond')
    if selection == 'geometry':
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = dtype(6.125), dtype(.42)
    elif selection == 'material-array':
        config.geometry.k_s_W_mK = np.asarray(dtype(1.337))
    elif selection == 'inlet':
        config.fluid_A.u_mps, config.fluid_A.T_in_K = dtype(5.125), dtype(351.13)
        config.fluid_B.u_mps, config.fluid_B.T_in_K = dtype(.03125), dtype(321.13)
    else:
        config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
        three._partial_ports(config, 5)
        for side in 'AB':
            port = getattr(config, 'bc_' + side)
            for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w', 'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
                setattr(port, name, dtype(getattr(port, name)))
    _full(native, monkeypatch, config, chi=.73)


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_spatial_3d_target_types(native, monkeypatch, dtype, array):
    config = _configuration(spatial=False)
    values = (1, 2) if dtype is np.int16 else (.003, .03)
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value) for value in values)
    _query(native, monkeypatch, 'resolve_inlet_flow', config, targets)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_spatial_3d_uniform_core_air_experiment_keeps_nonzero_offset(native, monkeypatch, topology):
    config = _configuration(topology, ('air', 'air'), spatial=False, mode='experimental')
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.5, .4
    _full(native, monkeypatch, config)
    capacities, _ = _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _full(native, monkeypatch, config, targets)


def test_spatial_3d_hx_capacity_precedes_delta_application_rejection(native, monkeypatch):
    config = _configuration(spatial=False, mode='experimental')
    speeds = config.fluid_A.u_mps, config.fluid_B.u_mps
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., float('nan')
    capacities, _ = _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config, (-1., float('nan')))
    targets = tuple(capacities[side] * speed for side, speed in zip('AB', speeds))
    for operation in ('resolve_inlet_flow', 'prepare_flow_case'):
        assert 'requires delta=0' in _failure(native, monkeypatch, operation, config, targets)


@pytest.mark.parametrize('delta', [-0., 0.])
def test_spatial_3d_zero_offset_keeps_original_alias_and_no_side_geometry(native, monkeypatch, delta):
    original = three.preparation._prepare_geometry_data
    aliases = []

    def geometry(*args, **kwargs):
        prepared = original(*args, **kwargs)
        aliases.append(prepared['design']['eps_A'] is prepared['design']['eps_B'])
        return prepared

    monkeypatch.setattr(three.preparation, '_prepare_geometry_data', geometry)
    expected, _ = _full(native, monkeypatch, _configuration(delta=delta))
    assert aliases == [True]
    assert expected.parameters['thermal_geometry']['side_geometry'] is None


def test_spatial_3d_raw_and_thermal_fields_keep_the_si_round_trip(native, monkeypatch):
    from sjtu_tpmshx.preprocess import thermal_geometry
    from sjtu_tpmshx.shared.models import tpms_props
    calls = []
    original = tpms_props.geometry_fields

    def geometry(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append((np.array(args[1], copy=True), np.array(args[2], copy=True), result))
        return result

    monkeypatch.setattr(tpms_props, 'geometry_fields', geometry)
    monkeypatch.setattr(thermal_geometry, 'geometry_fields', geometry)
    expected, _ = _full(native, monkeypatch, _configuration(delta=0.))
    assert len(calls) == 2
    raw, thermal = calls
    nz = expected.design_fields['eps_arr'].shape[2]
    for index, name in enumerate(('L', 't')):
        original_volume = np.repeat(raw[index][:, :, None], nz, axis=2)
        v1._same(thermal[index], original_volume * 1e-3 * 1e3, name + ' thermal input')
    assert any(np.any(np.repeat(raw[index][:, :, None], nz, axis=2) != thermal[index]) for index in (0, 1))


@pytest.mark.parametrize('operation', ['prepare_inlet_mass_capacities', 'resolve_inlet_flow'])
def test_spatial_3d_query_scope_keeps_range_and_notice_order(native, monkeypatch, operation):
    from sjtu_tpmshx.shared.models import tpms_props
    config = _configuration(delta=0.)
    config.fluid_A.T_in_K = min(tpms_props._AIR_T_RANGE[0], tpms_props._AIR_CP_RANGE[0]) - 10.
    monkeypatch.setattr(tpms_props, '_range_warnings_emitted', set())
    targets = (.003, .03) if operation == 'resolve_inlet_flow' else None
    _, standalone = flow._reference(monkeypatch, operation, config, targets)
    _, scoped = _query(native, monkeypatch, operation, config, targets)
    assert any('outside fitted range' in event[2] for event in standalone['events'])
    assert standalone['events'] != scoped['events']


def test_spatial_3d_no_target_resolution_keeps_unvalidated_owned_input(native, monkeypatch):
    config = _configuration()
    config.fluid_A.T_in_K = -1.
    config.zones.grid['cells'][0]['x1'] = -1.
    config.sco2_nu = replace(config.sco2_nu, source='retained spatial source')
    expected, state = flow._reference(monkeypatch, 'resolve_inlet_flow', config)
    assert expected is config and state['geometry_calls'] == 0
    status, result, failure, error, live, source = _call(native, 'resolve_inlet_flow', config)
    assert status == 0, error
    try:
        assert not failure.kind and not result.flow.have_capacities and not live
        assert result.flow.evidence.range_count == result.flow.evidence.warning_count == result.flow.evidence.event_count == 0
        for name, _ in three._Input._fields_:
            if name != 'sco2_nu':
                assert v1._struct_values(getattr(result.flow.input, name)) == v1._struct_values(getattr(source.values.input, name))
        source._cells[0].bounds[0].value = -5.
        source._cells[0].cell_length_mm = -1.
        _snapshot(result, config)
        for buffer in source._values._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        assert abi._text(result.flow.input.sco2_nu.source) == config.sco2_nu.source
    finally:
        _release(native, result)


def _entry(config, entry):
    if entry == 'capacity':
        return 'prepare_inlet_mass_capacities', None
    if entry == 'prescribed':
        return 'prepare_flow_case', None
    if entry == 'configured':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .003, .03
        return 'prepare_flow_case', None
    return ('resolve_inlet_flow' if entry == 'resolve' else 'prepare_flow_case'), (.003, .03)


@pytest.mark.parametrize('entry', ['prescribed', 'capacity', 'resolve', 'fixed', 'configured'])
@pytest.mark.parametrize('selection', ['empty', 'rectangle-x', 'rectangle-y-before-next-x',
    'nominal', 'local-nan', 'local-length', 'local-wall', 'local-pore', 'local-df',
    'water-before-local', 'experimental-grid', 'experimental-water', 'experimental-speed',
    'sco2-grid', 'sco2-temperature', 'sco2-delta', 'co2-grid', 'co2-delta',
    'sco2-before-co2', 'local-before-delta', 'delta-before-df'])
def test_spatial_3d_first_failure_matches_original(native, monkeypatch, entry, selection):
    config = _configuration()
    operation, targets = _entry(config, entry)
    rows = config.zones.grid['cells']
    if selection == 'empty': rows.clear()
    elif selection == 'rectangle-x':
        rows[0]['x1'], config.geometry.L_cell_mm, config.fluid_B.T_in_K = -1., -1., 500.
    elif selection == 'rectangle-y-before-next-x': rows[0]['y1'], rows[1]['x1'] = -1., -1.
    elif selection == 'nominal': config.geometry.L_cell_mm = 3.
    elif selection.startswith('local-') or selection == 'delta-before-df':
        length, wall = {
            'local-nan': (float('nan'), -.4), 'local-length': (-1., .4),
            'local-wall': (6., -.4), 'local-pore': (.5, .3), 'local-df': (9., .4),
            'local-before-delta': (float('nan'), .4), 'delta-before-df': (9., .4),
        }[selection]
        rows[:] = [dict(x0=0., x1=1., y0=0., y1=1., L=length, t=wall)]
        if selection in ('local-before-delta', 'delta-before-df'):
            config.geometry.delta_levelset = float('nan')
    elif selection == 'water-before-local':
        config.fluid_B.T_in_K, rows[0]['L'] = 500., float('nan')
    elif selection.startswith('experimental-'):
        config.df_mode = 'experimental'
        if selection == 'experimental-water': config.fluid_B.T_in_K = 500.
        if selection == 'experimental-speed': config.fluid_A.u_mps = -1.
    else:
        config.fluid_A.type, config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = (
            'sco2' if selection.startswith('sco2') else 'co2', 400., 8e6)
        if selection.endswith('-delta'): config.zones.enabled = False
        if selection == 'sco2-temperature': config.fluid_A.T_in_K = 250.
        if selection == 'sco2-before-co2':
            config.fluid_A.type = 'co2'
            config.fluid_B.type, config.fluid_B.T_in_K, config.fluid_B.P_in_Pa = 'sco2', 250., 8e6
    _failure(native, monkeypatch, operation, config, targets)


@pytest.mark.parametrize('entry', ['resolve', 'fixed', 'configured'])
def test_spatial_3d_target_and_rectangle_failure_priority(native, monkeypatch, entry):
    config = _configuration()
    operation, targets = _entry(config, entry)
    config.zones.grid['cells'][0]['x1'] = -1.
    if entry == 'configured':
        config.fluid_A.mass_flow_kg_s = -1.
    else:
        targets = (float('nan'), .03)
    _failure(native, monkeypatch, operation, config, targets)


@pytest.mark.parametrize('entry', ['prescribed', 'capacity', 'resolve', 'fixed'])
def test_spatial_3d_nominal_preflight_and_local_df_failure_priority(native, monkeypatch, entry):
    config = _configuration(delta=0.)
    config.extrap.allow, config.fluid_A.u_mps = False, 1e-20
    config.zones.grid['cells'] = [dict(x0=0., x1=1., y0=0., y1=1., L=9., t=.4)]
    operation, targets = _entry(config, entry)
    _failure(native, monkeypatch, operation, config, targets)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('fluid', ['sco2', 'co2'])
def test_spatial_3d_discrete_fluid_rejection_on_each_side(native, monkeypatch, side, fluid):
    config = _configuration()
    inlet = getattr(config, 'fluid_' + side)
    inlet.type, inlet.T_in_K, inlet.P_in_Pa = fluid, 400., 8e6
    _failure(native, monkeypatch, 'prepare_flow_case', config)


@pytest.mark.parametrize('delta', [-100., 100.])
def test_spatial_3d_closed_side_reaches_capacity_boundary(native, monkeypatch, delta):
    config = _configuration(delta=delta)
    expected, _ = _full(native, monkeypatch, config)
    assert expected.parameters['thermal_geometry']['split_A'] == (1. if delta > 0 else 0.)
    error = _failure(native, monkeypatch, 'prepare_inlet_mass_capacities', config)
    assert 'inlet density times open pore area' in error


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_spatial_3d_callback_failure_keeps_output(native, operation):
    config = _configuration(delta=0.)
    config.fluid_A.T_in_K = np.float64(1e308)
    status, result, failure, error, events, _ = _call(
        native, operation, config, (.003, .03), reject_event=True)
    assert status != 0 and error and failure.kind == 3
    assert len(events) == 1
    assert bytes(result) == bytes(type(result)(4, ct.sizeof(result)))


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('selection', ['cells-output', 'cells-failure', 'cells-error',
    'source-output', 'source-error', 'output-error', 'failure-error', 'text-output'])
def test_spatial_3d_overlapping_storage_is_unchanged(native, operation, selection):
    source = _input(_configuration(delta=0.), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(4, ct.sizeof(result_type)), abi._Failure(2, ct.sizeof(abi._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    result_pointer, error_pointer, capacity = ct.pointer(result), error, len(error)
    if selection.startswith('cells-'):
        target = {'cells-output': result, 'cells-failure': failure, 'cells-error': error}[selection]
        source.cells, source.cell_count = ct.cast(ct.pointer(target), ct.POINTER(_Cell)), 1
    elif selection.endswith('-error'):
        target = {'source-error': source, 'output-error': result, 'failure-error': failure}[selection]
        error_pointer, capacity = ct.cast(ct.byref(target, 8), ct.POINTER(ct.c_char)), 16
    elif selection == 'source-output':
        result_pointer = ct.cast(ct.pointer(source), ct.POINTER(result_type))
    else:
        source.values.input.sco2_nu.source = abi._Text(ct.cast(ct.pointer(result), ct.POINTER(ct.c_char)), 16)
    objects = (source, result, failure, error)
    before = [bytes(value) for value in objects]
    assert getattr(native, 'tpmshx_' + operation + '_3d_v4')(
        ct.byref(source), None, None, result_pointer, ct.byref(failure), error_pointer, capacity) != 0
    assert [bytes(value) for value in objects] == before


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_spatial_3d_owned_result_requires_release(native, operation):
    config = _configuration(delta=0.)
    status, result, failure, error, _, source = _call(native, operation, config, (.003, .03))
    assert status == 0, error
    before = bytes(result)
    error = ct.create_string_buffer(4096)
    try:
        assert getattr(native, 'tpmshx_' + operation + '_3d_v4')(
            ct.byref(source), None, None, ct.byref(result), ct.byref(failure), error, len(error)) != 0
        assert 'release' in error.value.decode() and bytes(result) == before
        _snapshot(result, config)
    finally:
        _release(native, result)


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('record', ['input', 'values', 'case', 'result', 'options', 'callbacks', 'failure'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_spatial_3d_rejects_incompatible_records(native, operation, record, field):
    source = _input(_configuration(delta=0.), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(4, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks))
    selected = {'input': source, 'values': source.values, 'case': source.values.input,
        'result': result, 'options': options, 'callbacks': callbacks, 'failure': failure}[record]
    setattr(selected, field, 99 if field == 'abi_version' else 1)
    before = bytes(result)
    assert getattr(native, 'tpmshx_' + operation + '_3d_v4')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error)) != 0
    assert error.value and bytes(result) == before


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('spatial', [False, True])
def test_spatial_3d_typed_grid_keeps_exact_width_coverage(native, monkeypatch, dtype, spatial):
    config = _configuration(spatial=spatial, delta=0.)
    config.solver.Nx = config.solver.Ny = config.solver.Nz = 4
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('entry', ['prescribed', 'capacity', 'resolve', 'fixed'])
@pytest.mark.parametrize('selection', ['local-nan', 'delta-nan'])
def test_spatial_3d_grid_cap_precedes_local_geometry_and_offset(native, monkeypatch, entry, selection):
    config = _configuration()
    if selection == 'local-nan':
        config.zones.grid['cells'][0]['L'] = float('nan')
    else:
        config.geometry.delta_levelset = float('nan')
    operation, targets = _entry(config, entry)
    source = _input(config, targets)
    source.values.input.max_cells = 119
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '119')
    error = _failure(native, monkeypatch, operation, config, targets, source=source)
    assert error == '3D grid 6x5x4 exceeds the 119-cell cap'


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('selection', ['missing-cells', 'uniform-cells', 'continuous-mode',
    'invalid-bound-precision', 'invalid-bound-kind'])
def test_spatial_3d_rejects_invalid_raw_transport(native, operation, selection):
    config = _configuration(delta=0.)
    source = _input(config, (.003, .03))
    if selection == 'missing-cells':
        source.cells = ct.POINTER(_Cell)()
    elif selection == 'uniform-cells':
        source.values.input.geometry_mode = 0
    elif selection == 'continuous-mode':
        source.values.input.geometry_mode = 1
    elif selection == 'invalid-bound-precision':
        source._cells[0].bounds[0].precision = 80
    else:
        source._cells[0].bounds[0].strong = 99
    status, result, failure, error, events, _ = _call(native, operation, config,
        (.003, .03), source=source)
    assert status != 0 and not events
    if selection == 'missing-cells':
        assert not error and not failure.kind
    else:
        assert error and failure.kind == 1
    assert bytes(result) == bytes(type(result)(4, ct.sizeof(result)))
    _release(native, result)
