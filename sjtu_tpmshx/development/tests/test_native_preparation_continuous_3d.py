"""Compare raw XY and XYZ preparation with the unchanged Python 3D path."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import os

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_continuous as two
from sjtu_tpmshx.development.tests import test_native_preparation_flow_3d as flow
from sjtu_tpmshx.shared.domain.compute_config import ZoneInputConfig

three, abi, v1, mass = flow.three, flow.abi, flow.v1, flow.flow
_U, _S, _D, _struct = abi._U, abi._S, abi._D, abi._structure
_Controls = _struct('ContinuousControls3D', [
    ('n_ctrl_x', _S), ('n_ctrl_y', _S), ('n_ctrl_z', _S),
    ('have_ctrl_z', _U), ('spline_order', _U), ('symmetric_y', _U),
    ('L_bounds_mm', _D * 2), ('t_bounds_mm', _D * 2), ('decision_mm', abi._Array)])
_Input = _struct('ContinuousInput3D', [('abi_version', _U), ('struct_size', _S),
    ('values', flow._Input), ('controls', _Controls)])
_Flow = _struct('ContinuousFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', flow._Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_Result = _struct('ContinuousCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', three._Result), ('flow', flow._Flow), ('controls', _Controls),
    ('area_density_per_m', abi._Array), ('hydraulic_diameter_m', abi._Array),
    ('thermal_porosity', abi._Array), ('drag', two._Drag * 2), ('owner', ct.c_void_p)])
_OPERATIONS = ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case')


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    version = library.tpmshx_preparation_continuous_3d_abi_version_v3
    version.argtypes, version.restype = [], _U
    assert version() == 3
    for operation in _OPERATIONS:
        result = _Result if operation == 'prepare_flow_case' else _Flow
        function = getattr(library, 'tpmshx_' + operation + '_3d_v3')
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(abi._Options),
            ct.POINTER(abi._Callbacks), ct.POINTER(result), ct.POINTER(abi._Failure),
            ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    for name, result in (('flow', _Flow), ('case', _Result)):
        release = getattr(library, 'tpmshx_preparation_continuous_' + name + '_3d_release_v3')
        release.argtypes, release.restype = [ct.POINTER(result)], None
    return library


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)


def _configuration(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth', *,
                   nx=4, ny=5, nz=None, mirror=True, order=3):
    config = three._configuration(topology, pair, mode)
    count = nx * ((ny + 1) // 2 if mirror else ny) * (1 if nz is None else nz)
    spec = dict(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=mirror, spline_order=order,
        L_bounds=[4., 8.], t_bounds=[.3, .6],
        x_decision=[float(value) for value in np.r_[
            np.linspace(4.2, 7.8, count), np.linspace(.57, .32, count)]])
    if nz is not None:
        spec['n_ctrl_z'] = nz
    config.zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec)
    return config


def _input(config, targets=None):
    values = flow._input(config, targets)
    values.input.geometry_mode = 1
    spec = config.zones.config
    decision = np.asarray(spec['x_decision'], dtype=np.float64)
    controls = _Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec.get('n_ctrl_z', 1),
        'n_ctrl_z' in spec, spec['spline_order'], spec['symmetric_y'],
        (_D * 2)(*spec['L_bounds']), (_D * 2)(*spec['t_bounds']),
        abi._Array(decision.ctypes.data_as(ct.POINTER(_D)), decision.size))
    source = _Input(3, ct.sizeof(_Input), values, controls)
    source._values, source._decision = values, decision
    return source


def _call(native, operation, config, targets=None, *, source=None, chi=None, reject_event=False):
    source = _input(config, targets) if source is None else source
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(3, ct.sizeof(result_type))
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
    before, decisions = (bytes(source), [bytes(buffer) for buffer in buffers]), source._decision.copy()
    status = getattr(native, 'tpmshx_' + operation + '_3d_v3')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert (bytes(source), [bytes(buffer) for buffer in buffers]) == before
    v1._same(source._decision, decisions, 'unchanged control input')
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = 'case' if isinstance(result, _Result) else 'flow'
    release = getattr(native, 'tpmshx_preparation_continuous_' + name + '_3d_release_v3')
    release(ct.byref(result))
    assert not result.owner
    release(ct.byref(result))


def _snapshot(controls, config):
    spec = config.zones.config
    assert (controls.n_ctrl_x, controls.n_ctrl_y, controls.n_ctrl_z,
            bool(controls.have_ctrl_z), controls.spline_order, bool(controls.symmetric_y)) == (
        spec['n_ctrl_x'], spec['n_ctrl_y'], spec.get('n_ctrl_z', 1),
        'n_ctrl_z' in spec, spec['spline_order'], spec['symmetric_y'])
    v1._same(controls.L_bounds_mm, spec['L_bounds'], 'L bounds')
    v1._same(controls.t_bounds_mm, spec['t_bounds'], 't bounds')
    v1._same(abi._array(controls.decision_mm), spec['x_decision'], 'owned controls')


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
        _snapshot(result.controls, config)
        source._decision[:] = -1.
        source.values.input.cell_length_mm = -1.
        for buffer in source._values._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        _snapshot(result.controls, config)
        assert result.prepared.input.cell_length_mm == config.geometry.L_cell_mm
        for name in ('cell_length', 'wall_thickness', 'solid_conductivity'):
            assert v1._struct_values(getattr(result.prepared.input.kinds, name)) == v1._struct_values(
                getattr(source.values.input.kinds, name))
        three._check_values(result.prepared, expected, state['resolved'])
        three._check_evidence(result.prepared, expected, state['records'],
            state['events'], live, state['resolved'])
        have_targets = targets is not None or any(
            getattr(config, 'fluid_' + side).mass_flow_kg_s is not None for side in 'AB')
        assert bool(result.flow.have_capacities) == have_targets
        if have_targets:
            flow._resolved(result.flow, state['resolved'])
            flow._evidence(result.flow.evidence, state['capacity_records'])
            assert two._host_events(mass._events(result.flow.evidence)) == state['capacity_events']
        else:
            assert result.flow.evidence.range_count == result.flow.evidence.event_count == 0
        shape = expected.design_fields['L_field_m'].shape
        for name, key in (('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'),
                          ('thermal_porosity', 'epsilon')):
            v1._same(abi._array(getattr(result, name), shape),
                expected.parameters['thermal_geometry']['fields'][key], key)
        for index, side in enumerate('AB'):
            metadata = (expected.parameters['df_application'] or {}).get(side, {})
            drag = result.drag[index]
            for name in ('transfer_policy', 'geometry_application'):
                assert abi._text(getattr(drag, name)) == metadata.get(name, ''), side + name
            assert bool(drag.have_reference_geometry) == ('reference_geometry_mm' in metadata)
            if drag.have_reference_geometry:
                v1._same(drag.reference_geometry_mm,
                    [metadata['reference_geometry_mm'][key] for key in ('L', 't')], side + ' reference')
    finally:
        _release(native, result)
    assert asdict(config) == before
    return expected, state


def _query(native, monkeypatch, operation, config, targets=None):
    expected, state = flow._reference(monkeypatch, operation, config, targets, scoped=True)
    status, result, failure, error, live, source = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        assert result.owner and not result.flow.owner and not failure.kind
        _snapshot(result.controls, config)
        source._decision[:] = -1.
        _snapshot(result.controls, config)
        flow._evidence(result.flow.evidence, state['records'])
        assert two._host_events(live) == state['events']
        assert mass._events(result.flow.evidence) == live
        if operation == 'prepare_inlet_mass_capacities':
            assert result.flow.have_capacities and state['geometry_calls'] == 1
            for index, side in enumerate('AB'):
                mass._scalar(result.flow.capacities[index], expected[side])
        else:
            flow._resolved(result.flow, expected)
    finally:
        _release(native, result)
    return expected, state


@pytest.mark.parametrize('nz', [None, 3], ids=['xy', 'xyz'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(abi._FLUIDS, repeat=2)))
def test_continuous_3d_pair_capacity_resolve_and_full(native, monkeypatch, topology, pair, nz):
    config = _configuration(topology, pair, nz=nz)
    capacities, _ = _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    stale = replace(config, fluid_A=replace(config.fluid_A, u_mps=-99., mass_flow_kg_s=.9),
        fluid_B=replace(config.fluid_B, u_mps=-88., mass_flow_kg_s=.8))
    _query(native, monkeypatch, 'resolve_inlet_flow', stale, targets)
    expected, _ = _full(native, monkeypatch, stale, targets)
    assert 'inlet_inputs' not in expected.parameters
    assert expected.metadata['design_mode'] == ('continuous_xy_extruded' if nz is None else 'continuous_xyz')


@pytest.mark.parametrize('layout', [
    (1, 1, None, False, 1), (1, 5, None, True, 3), (4, 1, None, False, 2),
    (4, 4, None, True, 2), (4, 5, None, False, 3),
    (4, 5, 1, True, 3), (1, 4, 3, False, 3), (4, 1, 3, True, 2),
    (1, 1, 1, True, 3), (4, 4, 2, True, 1), (4, 5, 3, False, 2),
])
def test_continuous_3d_control_layouts_and_orders(native, monkeypatch, layout):
    nx, ny, nz, mirror, order = layout
    config = _configuration(nx=nx, ny=ny, nz=nz, mirror=mirror, order=order)
    expected, _ = _full(native, monkeypatch, config)
    if nz is None:
        values = expected.design_fields['L_field_m']
        v1._same(values, np.repeat(values[:, :, :1], values.shape[2], axis=2), 'XY extrusion')


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
def test_continuous_3d_configured_and_mixed_flow_ports(native, monkeypatch, direction, sides):
    config = _configuration(nz=None if direction % 2 else 3)
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


@pytest.mark.parametrize('nz,direction', [(None, 0), (3, 5)])
def test_continuous_3d_samples_refined_physical_centres(native, monkeypatch, nz, direction):
    config = _configuration(nz=nz)
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


@pytest.mark.parametrize('nz', [None, 3])
@pytest.mark.parametrize('topology,pair', [
    ('Gyroid', ('air', 'water')), ('Gyroid', ('co2', 'co2')), ('Diamond', ('co2', 'co2'))])
def test_continuous_3d_existing_experimental_scope(native, monkeypatch, topology, pair, nz):
    config = _configuration(topology, pair, 'experimental', nz=nz)
    capacities, _ = _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _full(native, monkeypatch, config)
    _full(native, monkeypatch, config, targets)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('selection', ['geometry', 'material-array', 'inlet', 'grid-port'])
def test_continuous_3d_scalar_precision(native, monkeypatch, dtype, selection):
    config = _configuration('Diamond', ('co2', 'water'), nz=3)
    if selection == 'geometry':
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = dtype(6.125), dtype(.42)
    elif selection == 'material-array':
        config.geometry.k_s_W_mK = np.asarray(dtype(1.337))
    elif selection == 'inlet':
        config.fluid_A.u_mps, config.fluid_A.T_in_K = dtype(.125), dtype(401.13)
        config.fluid_B.u_mps, config.fluid_B.T_in_K = dtype(.03125), dtype(321.13)
    else:
        config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
        three._partial_ports(config, 5)
        for side in 'AB':
            port = getattr(config, 'bc_' + side)
            for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w', 'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
                setattr(port, name, dtype(getattr(port, name)))
    if selection == 'grid-port' and dtype in (np.float16, np.float32):
        with pytest.raises(ValueError) as reference:
            flow._reference(monkeypatch, 'prepare_flow_case', config)
        status, result, failure, error, _, _ = _call(native, 'prepare_flow_case', config)
        assert status == 1 and failure.kind == 1 and error == str(reference.value)
        assert bytes(result) == bytes(_Result(3, ct.sizeof(_Result)))
    else:
        _full(native, monkeypatch, config, chi=.73)


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_continuous_3d_target_types(native, monkeypatch, dtype, array):
    config = _configuration(nz=1)
    values = (1, 2) if dtype is np.int16 else (.003, .03)
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value) for value in values)
    _query(native, monkeypatch, 'resolve_inlet_flow', config, targets)
    _full(native, monkeypatch, config, targets)


@pytest.mark.parametrize('nz', [None, 3])
def test_continuous_3d_owned_provenance_and_nu_selection(native, monkeypatch, nz):
    config = _configuration(pair=('sco2', 'co2'), nz=nz)
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
        parameter_version='saved continuous version', source='保留来源', applicability='保留范围')
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('operation', ['prepare_inlet_mass_capacities', 'resolve_inlet_flow'])
def test_continuous_3d_query_ranges_and_warning_scope(native, monkeypatch, operation):
    from sjtu_tpmshx.shared.models import tpms_props
    config = _configuration(nz=3)
    config.fluid_A.T_in_K = min(tpms_props._AIR_T_RANGE[0], tpms_props._AIR_CP_RANGE[0]) - 10.
    monkeypatch.setattr(tpms_props, '_range_warnings_emitted', set())
    targets = (.003, .03) if operation == 'resolve_inlet_flow' else None
    _, standalone = flow._reference(monkeypatch, operation, config, targets)
    _, scoped = _query(native, monkeypatch, operation, config, targets)
    assert any('outside fitted range' in event[2] for event in standalone['events'])
    assert standalone['events'] != scoped['events']


def test_continuous_3d_capacity_ignores_speeds_and_explicit_targets(native, monkeypatch):
    config = _configuration(mode='experimental', nz=3)
    config.fluid_A.u_mps, config.fluid_B.u_mps, config.extrap.allow = -99., float('nan'), False
    _query(native, monkeypatch, 'prepare_inlet_mass_capacities', config, (-1., float('nan')))


def test_continuous_3d_no_target_resolution_keeps_unvalidated_owned_input(native, monkeypatch):
    config = _configuration(nz=1)
    config.fluid_A.T_in_K = -1.
    config.zones.config['spline_order'] = 0
    config.sco2_nu = replace(config.sco2_nu, source='retained source')
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
        source._decision[:] = -1.
        _snapshot(result.controls, config)
        for buffer in source._values._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        assert abi._text(result.flow.input.sco2_nu.source) == config.sco2_nu.source
    finally:
        _release(native, result)


@pytest.mark.parametrize('operation,selection', [
    (operation, selection)
    for operation in _OPERATIONS
    for selection in ('order', 'counts', 'z-count', 'L-bounds', 't-bounds',
        'decision-length', 'control-domain', 'control-nan', 'nan-before-bounds', 'bounds-nan',
        'delta', 'experimental-pair', 'experimental-nominal', 'experimental-domain',
        'depth-before-controls', 'target-before-controls', 'water-before-grid', 'co2-critical')
    if operation != 'prepare_inlet_mass_capacities' or not selection.startswith('experimental-')
])
def test_continuous_3d_first_error_and_failure_atomicity(native, monkeypatch, operation, selection):
    config, targets = _configuration(nz=3), (.003, .03)
    spec = config.zones.config
    if selection == 'order': spec['spline_order'] = 0
    elif selection == 'counts': spec['n_ctrl_x'] = 0
    elif selection == 'z-count': spec['n_ctrl_z'] = 0
    elif selection == 'L-bounds': spec['L_bounds'] = [3., 9.]
    elif selection == 't-bounds': spec['t_bounds'] = [.2, .7]
    elif selection == 'decision-length': spec['x_decision'].pop()
    elif selection == 'control-domain': spec['x_decision'][0] = 3.
    elif selection == 'control-nan': spec['x_decision'][0] = float('nan')
    elif selection == 'nan-before-bounds': spec['x_decision'][0], spec['L_bounds'] = float('nan'), [3., 9.]
    elif selection == 'bounds-nan': spec['L_bounds'][0] = float('nan')
    elif selection == 'delta': config.geometry.delta_levelset = .1
    elif selection == 'experimental-pair': config.df_mode, config.fluid_A.type = 'experimental', 'water'
    elif selection == 'experimental-nominal': config.df_mode, config.geometry.L_cell_mm = 'experimental', 6.
    elif selection == 'experimental-domain': config.df_mode, config.geometry.L_dom_m = 'experimental', .18
    elif selection == 'depth-before-controls': config.geometry.Lz_m, spec['spline_order'] = 0., 0
    elif selection == 'target-before-controls': spec['spline_order'], targets = 0, (float('nan'), .03)
    elif selection == 'water-before-grid': config.fluid_B.T_in_K, config.solver.Nx = 500., 0
    else:
        config.fluid_A.type = 'co2'
        config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 304.1282, 7377298.373
    state = {}
    with pytest.raises(ValueError) as reference:
        flow._reference(monkeypatch, operation, config, targets, scoped=True, state=state)
    status, result, failure, error, live, _ = _call(native, operation, config, targets)
    assert status != 0 and error == str(reference.value)
    assert failure.kind == three.fluids._error_kind(reference.value)
    assert bytes(result) == bytes(type(result)(3, ct.sizeof(result)))
    assert two._host_events(live) == state['events']
    causes, cause = [], reference.value.__cause__
    while cause is not None:
        causes.append((three.fluids._error_kind(cause), str(cause)))
        cause = cause.__cause__
    assert [(item.kind, item.message.decode()) for item in failure.causes[:failure.cause_count]] == causes
    _release(native, result)


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_continuous_3d_callback_failure_keeps_output(native, operation):
    config = _configuration(nz=3)
    config.fluid_A.T_in_K = np.float64(1e308)
    status, result, failure, error, events, _ = _call(
        native, operation, config, (.003, .03), reject_event=True)
    assert status != 0 and error and failure.kind == 3
    assert len(events) == 1
    assert bytes(result) == bytes(type(result)(3, ct.sizeof(result)))


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('selection', ['decision-output', 'decision-failure', 'decision-error',
    'source-output', 'source-error', 'output-error', 'failure-error', 'text-output'])
def test_continuous_3d_overlapping_storage_is_unchanged(native, operation, selection):
    source = _input(_configuration(nz=3), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(3, ct.sizeof(result_type)), abi._Failure(2, ct.sizeof(abi._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    result_pointer, error_pointer, capacity = ct.pointer(result), error, len(error)
    if selection.startswith('decision-'):
        target = {'decision-output': result, 'decision-failure': failure, 'decision-error': error}[selection]
        source.controls.decision_mm = abi._Array(ct.cast(ct.pointer(target), ct.POINTER(_D)), 1)
    elif selection.endswith('-error'):
        target = {'source-error': source, 'output-error': result, 'failure-error': failure}[selection]
        error_pointer, capacity = ct.cast(ct.byref(target, 8), ct.POINTER(ct.c_char)), 16
    elif selection == 'source-output':
        result_pointer = ct.cast(ct.pointer(source), ct.POINTER(result_type))
    else:
        source.values.input.sco2_nu.source = abi._Text(ct.cast(ct.pointer(result), ct.POINTER(ct.c_char)), 16)
    objects = (source, result, failure, error)
    before = [bytes(value) for value in objects]
    assert getattr(native, 'tpmshx_' + operation + '_3d_v3')(
        ct.byref(source), None, None, result_pointer, ct.byref(failure), error_pointer, capacity) != 0
    assert [bytes(value) for value in objects] == before


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_continuous_3d_owned_result_requires_release(native, operation):
    status, result, failure, error, _, source = _call(native, operation, _configuration(), (.003, .03))
    assert status == 0, error
    before, decisions = bytes(result), abi._array(result.controls.decision_mm)
    error = ct.create_string_buffer(4096)
    try:
        assert getattr(native, 'tpmshx_' + operation + '_3d_v3')(
            ct.byref(source), None, None, ct.byref(result), ct.byref(failure), error, len(error)) != 0
        assert 'release' in error.value.decode()
        assert bytes(result) == before
        v1._same(abi._array(result.controls.decision_mm), decisions, 'retained owner')
    finally:
        _release(native, result)


@pytest.mark.parametrize('pair', [('air', 'water'), ('co2', 'water')])
def test_continuous_3d_raw_and_thermal_geometry_keep_unit_order(native, monkeypatch, pair):
    config = _configuration(pair=pair, nx=3, ny=4, nz=3, mirror=False)
    calls = []
    original = three.preparation.geometry_fields

    def geometry(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append((np.array(args[1], copy=True), np.array(args[2], copy=True), result))
        return result

    monkeypatch.setattr(three.preparation, 'geometry_fields', geometry)
    expected, _ = _full(native, monkeypatch, config)
    thermal = expected.parameters['thermal_geometry']['fields']
    if pair[0] == 'co2':
        assert np.any(expected.design_fields['eps_arr'] != thermal['epsilon'])
    else:
        assert len(calls) == 2
        raw, converted = calls
        assert any(np.any(raw[index] != converted[index]) for index in (0, 1))
        assert any(np.any(raw[2][key] != thermal[key]) for key in ('A_0', 'D_h'))


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('record', ['input', 'values', 'case', 'result', 'options', 'callbacks', 'failure'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_continuous_3d_rejects_incompatible_records(native, operation, record, field):
    source = _input(_configuration(nz=3), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(3, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks))
    selected = {'input': source, 'values': source.values, 'case': source.values.input,
        'result': result, 'options': options, 'callbacks': callbacks, 'failure': failure}[record]
    setattr(selected, field, 99 if field == 'abi_version' else 1)
    before = bytes(result)
    assert getattr(native, 'tpmshx_' + operation + '_3d_v3')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error)) != 0
    assert error.value and bytes(result) == before


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('nz', [None, 1, 3])
@pytest.mark.parametrize('nx', [1, 4])
def test_continuous_3d_typed_grid_with_exact_width_coverage(native, monkeypatch, dtype, nz, nx):
    config = _configuration(nx=nx, nz=nz)
    config.solver.Nx = config.solver.Ny = config.solver.Nz = 4
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('nz', [None, 1], ids=['xy', 'xyz'])
@pytest.mark.parametrize('constant', [False, True])
@pytest.mark.parametrize('width_failure', [False, True])
def test_continuous_3d_rejects_rounded_control_axes_before_sampling(
        native, monkeypatch, operation, axis, nz, constant, width_failure):
    counts = {'nx': 4097, 'ny': 2} if axis == 'x' else {'nx': 2, 'ny': 4097}
    config = _configuration(**counts, nz=nz, mirror=False)
    config.solver.Nx = 5 if width_failure else 4
    config.solver.Ny = config.solver.Nz = 4
    config.geometry.L_dom_m = np.float16(.081)
    config.geometry.H_dom_m = np.float16(.063)
    if constant:
        count = len(config.zones.config['x_decision']) // 2
        config.zones.config['x_decision'] = [7.] * count + [.6] * count
    state, targets = {}, (.003, .03)
    with pytest.raises(ValueError) as reference:
        flow._reference(monkeypatch, operation, config, targets, scoped=True, state=state)
    assert str(reference.value) == (
        'control axes must increase across the domain, or use its midpoint for one control')
    status, result, failure, error, live, _ = _call(native, operation, config, targets)
    try:
        assert status != 0 and error == str(reference.value)
        assert failure.kind == 1 and failure.cause_count == 0
        assert bytes(result) == bytes(type(result)(3, ct.sizeof(result)))
        assert two._host_events(live) == state['events']
    finally:
        _release(native, result)
