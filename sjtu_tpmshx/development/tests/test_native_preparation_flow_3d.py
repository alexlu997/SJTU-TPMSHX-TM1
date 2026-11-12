"""Compare native 3D inlet-flow stages with the frozen Python 3D path."""
import ctypes as ct
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
from itertools import product
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_3d as three
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as flow
from sjtu_tpmshx.development.tests import preparation_api_reference as api
from sjtu_tpmshx.development.tests import preparation_3d_reference as preparation
from sjtu_tpmshx.shared.domain.run_warnings import (
    current_warnings, range_observations, warning_messages, warning_scope,
)
from sjtu_tpmshx.shared.models import _native_flow

abi, v1 = three.abi, three.v1
_U, _S, _D, _struct = abi._U, abi._S, abi._D, abi._structure
_Input = _struct('FlowInput3D', [('abi_version', _U), ('struct_size', _S),
    ('input', three._Input), ('target_kinds', abi._Kind * 2),
    ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)])
_Flow = _struct('Flow3D', [('abi_version', _U), ('struct_size', _S),
    ('input', three._Input), ('have_capacities', _U),
    ('capacities', _native_flow._Scalar * 2), ('speeds', _native_flow._Scalar * 2),
    ('evidence', abi._Evidence), ('owner', ct.c_void_p)])
_Result = _struct('FlowCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', three._Result), ('flow', _Flow), ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    version = library.tpmshx_preparation_flow_3d_abi_version_v2
    version.argtypes, version.restype = [], _U
    assert version() == 2
    for name, result in [('prepare_inlet_mass_capacities', _Flow),
                         ('resolve_inlet_flow', _Flow), ('prepare_flow_case', _Result)]:
        function = getattr(library, 'tpmshx_' + name + '_3d_v2')
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(abi._Options),
            ct.POINTER(abi._Callbacks), ct.POINTER(result), ct.POINTER(abi._Failure),
            ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    for name, result in [('flow', _Flow), ('flow_case', _Result)]:
        release = getattr(library, 'tpmshx_preparation_' + name + '_3d_release_v2')
        release.argtypes, release.restype = [ct.POINTER(result)], None
    return library


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)


def _input(config, targets=None):
    source = three._input(config)
    result = _Input(2, ct.sizeof(_Input), source)
    result._source = source
    result.have_explicit_targets = targets is not None
    for index, side in enumerate('AB'):
        target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
        kind = _native_flow._scalar(0. if target is None else target)
        result.target_kinds[index] = abi._Kind(kind.precision, kind.strong, int(bool(kind.strong)))
        if targets is not None:
            result.explicit_targets_kg_s[index] = target
    return result


def _call(native, operation, config, targets=None, *, reject_event=False):
    source = _input(config, targets)
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(2, ct.sizeof(result_type)), abi._Failure(2, ct.sizeof(abi._Failure))
    options = abi._Options(1, ct.sizeof(abi._Options), 0, config.extrap.allow, 0.)
    error, events = ct.create_string_buffer(4096), []

    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, abi._text(item.logger), abi._text(item.message), item.floating_event))
        return int(reject_event)

    callback = abi._EventFunction(event)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), callback, None)
    before = bytes(source), [bytes(buffer) for buffer in source._source._buffers]
    status = getattr(native, 'tpmshx_' + operation + '_3d_v2')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert (bytes(source), [bytes(buffer) for buffer in source._source._buffers]) == before
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = 'flow_case' if isinstance(result, _Result) else 'flow'
    release = getattr(native, 'tpmshx_preparation_' + name + '_3d_release_v2')
    release(ct.byref(result))
    assert not result.owner
    release(ct.byref(result))


def _reference(monkeypatch, operation, config, targets=None, *, scoped=False, state=None):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    state = {} if state is None else state
    state.update(records={}, capacity_records={}, events=[], capacity_events=[],
                 resolved=config, geometry_calls=0)

    @contextmanager
    def capture_scope(initial):
        with warning_scope(initial) as records:
            try:
                yield records
            finally:
                state['records'].update(records)

    original_geometry, original_finish = preparation._prepare_geometry_data, preparation._finish_problem_data

    def geometry(*args, **kwargs):
        state['geometry_calls'] += 1
        prepared = original_geometry(*args, **kwargs)
        state['capacity_records'] = dict(current_warnings() or {})
        state['capacity_events'] = list(state['events'])
        return prepared

    def finish(prepared):
        state['resolved'] = prepared['cfg']['compute_cfg']
        return original_finish(prepared)

    with monkeypatch.context() as patch, warnings.catch_warnings():
        patch.setattr(api, 'warning_scope', capture_scope)
        patch.setattr(preparation, '_prepare_geometry_data', geometry)
        patch.setattr(preparation, '_finish_problem_data', finish)
        warnings.simplefilter('always')
        patch.setattr(warnings, 'showwarning', lambda message, *args, **kwargs:
            state['events'].append((1, '', str(message), 0)))
        with capture_scope({}) if scoped else nullcontext():
            if operation == 'prepare_inlet_mass_capacities':
                expected = api.prepare_inlet_mass_capacities(config)
            elif operation == 'resolve_inlet_flow':
                expected = (api.resolve_inlet_flow_config(config) if targets is None else
                    api.resolve_fixed_mass_flow_config(config,
                        mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1]))
                state['resolved'] = expected
            else:
                expected = (api.prepare_case(config, case_id='native-3d-flow-reference') if targets is None else
                    api.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=targets[0],
                        mass_flow_B_kg_s=targets[1], case_id='native-3d-flow-reference'))
    return expected, state


def _evidence(actual, records):
    for last in (False, True):
        rows = []
        for index in range(actual.range_count):
            row = v1._range(actual.ranges[index], last=last)
            if actual.range_bounds_list[index]:
                row['bounds'] = list(row['bounds'])
            rows.append(row)
        assert rows == range_observations(records, last=last)
    assert [abi._text(item) for item in actual.warnings[:actual.warning_count]] == list(warning_messages(records))


def _resolved(actual, expected):
    for index, side in enumerate('AB'):
        inlet, fluid = actual.input.sides[index], getattr(expected, 'fluid_' + side)
        v1._same(inlet.velocity_m_s, fluid.u_mps, side + ' resolved speed')
        assert bool(inlet.have_mass_flow) == (fluid.mass_flow_kg_s is not None)
        if inlet.have_mass_flow:
            v1._same(inlet.mass_flow_kg_s, fluid.mass_flow_kg_s, side + ' stored target')
        assert v1._struct_values(actual.input.kinds.sides[index].velocity) == v1._struct_values(three._kind(fluid.u_mps))
        flow._scalar(actual.speeds[index], fluid.u_mps)


def _full(native, monkeypatch, config, targets=None):
    expected, state = _reference(monkeypatch, 'prepare_flow_case', config, targets)
    status, result, failure, error, live, _ = _call(native, 'prepare_flow_case', config, targets)
    assert status == 0, error
    try:
        assert not failure.kind and result.owner
        assert not result.prepared.owner and not result.flow.owner
        assert state['geometry_calls'] == 1
        three._check_values(result.prepared, expected, state['resolved'])
        three._check_evidence(result.prepared, expected, state['records'], state['events'], live, state['resolved'])
        have_targets = targets is not None or any(getattr(config, 'fluid_' + side).mass_flow_kg_s is not None for side in 'AB')
        assert bool(result.flow.have_capacities) == have_targets
        if have_targets:
            _resolved(result.flow, state['resolved'])
            _evidence(result.flow.evidence, state['capacity_records'])
            assert three._host_events(flow._events(result.flow.evidence)) == state['capacity_events']
        else:
            assert result.flow.evidence.range_count == result.flow.evidence.event_count == 0
    finally:
        _release(native, result)
    return expected, state


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(abi._FLUIDS, repeat=2)))
@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_native_3d_explicit_flow_matches_original(native, monkeypatch, topology, pair, mode):
    config = three._configuration(topology, pair, mode)
    before = asdict(config)
    capacities, standalone = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    scoped, scoped_state = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config, scoped=True)
    assert capacities == scoped
    status, result, failure, error, live, _ = _call(native, 'prepare_inlet_mass_capacities', config)
    assert status == 0, error
    try:
        assert result.have_capacities and not failure.kind
        for index, side in enumerate('AB'):
            flow._scalar(result.capacities[index], capacities[side])
        _evidence(result.evidence, scoped_state['records'])
        assert three._host_events(live) == standalone['events']
    finally:
        _release(native, result)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    stale = replace(config, fluid_A=replace(config.fluid_A, u_mps=-99., mass_flow_kg_s=.9),
                    fluid_B=replace(config.fluid_B, u_mps=-88., mass_flow_kg_s=.8))
    resolved, state = _reference(monkeypatch, 'resolve_inlet_flow', stale, targets)
    status, result, _, error, live, _ = _call(native, 'resolve_inlet_flow', stale, targets)
    assert status == 0, error
    try:
        _resolved(result, resolved)
        assert result.have_capacities
        assert three._host_events(live) == state['events']
    finally:
        _release(native, result)
    expected, _ = _full(native, monkeypatch, stale, targets)
    assert 'inlet_inputs' not in expected.parameters
    assert asdict(config) == before


@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
@pytest.mark.parametrize('direction', range(6))
def test_native_3d_configured_and_mixed_flow_on_partial_ports(native, monkeypatch, sides, direction):
    config = three._configuration()
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .081, .063, .047
    three._partial_ports(config, direction)
    capacities, _ = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    for side in sides:
        fluid = getattr(config, 'fluid_' + side)
        setattr(config, 'fluid_' + side, replace(fluid,
            u_mps=-99., mass_flow_kg_s=float(capacities[side] * fluid.u_mps)))
    before = asdict(config)
    expected, state = _full(native, monkeypatch, config)
    assert set(expected.parameters['inlet_inputs']) == {'A', 'B'}
    for side in set('AB') - set(sides):
        assert getattr(state['resolved'], 'fluid_' + side).u_mps == getattr(config, 'fluid_' + side).u_mps
    assert asdict(config) == before


@pytest.mark.parametrize('direction', [0, 5])
def test_native_3d_flow_uses_refined_physical_port_grid(native, monkeypatch, direction):
    config = three._configuration()
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
    capacities, _ = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    expected, _ = _full(native, monkeypatch, config, targets)
    assert any(np.ptp(expected.grid['d' + axis]) > 0 for axis in 'xyz')


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_native_3d_explicit_target_types(native, monkeypatch, dtype, array):
    config = three._configuration()
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value)
                    for value in ((1, 2) if dtype is np.int16 else (.003, .03)))
    expected, state = _reference(monkeypatch, 'resolve_inlet_flow', config, targets)
    status, result, _, error, live, _ = _call(native, 'resolve_inlet_flow', config, targets)
    assert status == 0, error
    try:
        _resolved(result, expected)
        capacities, _ = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
        for index, side in enumerate('AB'):
            flow._scalar(result.capacities[index], capacities[side])
        assert three._host_events(live) == state['events']
    finally:
        _release(native, result)


def test_native_3d_capacity_ignores_old_speed_and_explicit_targets(native, monkeypatch):
    config = three._configuration(mode='experimental')
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., float('nan')
    config.extrap.allow = False
    expected, state = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    status, result, _, error, live, _ = _call(native, 'prepare_inlet_mass_capacities', config, (-1., float('nan')))
    assert status == 0, error
    try:
        for index, side in enumerate('AB'):
            flow._scalar(result.capacities[index], expected[side])
        assert all(abi._text(result.evidence.ranges[index].source[0]) != 'nu'
                   for index in range(result.evidence.range_count))
        assert three._host_events(live) == state['events']
    finally:
        _release(native, result)


def test_native_3d_resolve_without_targets_keeps_unvalidated_owned_input(native, monkeypatch):
    config = three._configuration()
    config.fluid_A.T_in_K = -1.
    config.sco2_nu = replace(config.sco2_nu, source='retained source text')
    expected, state = _reference(monkeypatch, 'resolve_inlet_flow', config)
    assert expected is config and state['geometry_calls'] == 0
    status, result, _, error, live, source = _call(native, 'resolve_inlet_flow', config)
    assert status == 0, error
    try:
        assert not result.have_capacities and not live
        for name, _ in three._Input._fields_:
            if name != 'sco2_nu':
                assert v1._struct_values(getattr(result.input, name)) == v1._struct_values(getattr(source.input, name))
        for name in ('mode', 'have_alpha', 'alpha'):
            assert v1._struct_values(getattr(result.input.sco2_nu, name)) == v1._struct_values(getattr(source.input.sco2_nu, name))
        for buffer in source._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        for name in ('parameter_version', 'source', 'applicability'):
            assert abi._text(getattr(result.input.sco2_nu, name)) == getattr(config.sco2_nu, name)
        assert result.evidence.range_count == result.evidence.warning_count == result.evidence.event_count == 0
    finally:
        _release(native, result)


def test_native_3d_prepare_without_targets_keeps_prescribed_route(native, monkeypatch):
    _full(native, monkeypatch, three._configuration())


@pytest.mark.parametrize('selection', ['target-a', 'target-b', 'configured-before-geometry',
    'geometry', 'temperature', 'depth', 'port', 'water-vapor', 'water-before-co2',
    'co2-critical', 'resolved-experiment', 'untargeted-speed'])
@pytest.mark.parametrize('operation', ['resolve_inlet_flow', 'prepare_flow_case'])
def test_native_3d_flow_first_error(native, monkeypatch, selection, operation):
    config, targets = three._configuration(), (.003, .03)
    if selection == 'target-a':
        targets = (float('nan'), 0.)
        config.geometry.L_cell_mm = -1.
    elif selection == 'target-b':
        targets = (.003, -1.)
    elif selection == 'configured-before-geometry':
        targets, config.fluid_A.mass_flow_kg_s = None, -1.
        config.geometry.L_cell_mm = -1.
    elif selection == 'geometry':
        config.geometry.L_cell_mm = 3.
    elif selection == 'temperature':
        config.fluid_B.T_in_K = float('nan')
    elif selection == 'depth':
        config.geometry.Lz_m = 0.
    elif selection == 'port':
        config.bc_A.in_z_ctr, config.bc_A.in_z_w = .01, None
    elif selection in ('water-vapor', 'water-before-co2'):
        config.fluid_B.T_in_K = 500.
        if selection == 'water-before-co2':
            config.fluid_A.type = 'co2'
            config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 304.1282, 7377298.373
    elif selection == 'co2-critical':
        config.fluid_A.type = 'co2'
        config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 304.1282, 7377298.373
    elif selection == 'resolved-experiment':
        config.df_mode, targets = 'experimental', (1e-12, .03)
    else:
        targets, config.fluid_A.mass_flow_kg_s, config.fluid_B.u_mps = None, .003, -1.
    state = {}
    with pytest.raises(ValueError) as reference:
        _reference(monkeypatch, operation, config, targets, state=state)
    status, result, failure, error, live, _ = _call(native, operation, config, targets)
    assert status != 0 and error == str(reference.value)
    assert failure.kind == three.fluids._error_kind(reference.value)
    assert bytes(result) == bytes(type(result)(2, ct.sizeof(result)))
    assert three._host_events(live) == state['events']
    _release(native, result)


@pytest.mark.parametrize('operation', ['prepare_inlet_mass_capacities', 'resolve_inlet_flow'])
def test_native_3d_query_ranges_keep_standalone_notices_distinct(native, monkeypatch, operation):
    from sjtu_tpmshx.shared.models import tpms_props
    config = three._configuration()
    config.fluid_A.T_in_K = min(tpms_props._AIR_T_RANGE[0], tpms_props._AIR_CP_RANGE[0]) - 10.
    monkeypatch.setattr(tpms_props, '_range_warnings_emitted', set())
    targets = (.003, .03) if operation == 'resolve_inlet_flow' else None
    expected, standalone = _reference(monkeypatch, operation, config, targets)
    _, scoped = _reference(monkeypatch, operation, config, targets, scoped=True)
    assert any('outside fitted range' in event[2] for event in standalone['events'])
    status, result, _, error, live, _ = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        if targets is None:
            for index, side in enumerate('AB'):
                flow._scalar(result.capacities[index], expected[side])
        else:
            _resolved(result, expected)
        _evidence(result.evidence, scoped['records'])
        assert any(result.evidence.ranges[index].sample.low for index in range(result.evidence.range_count))
        # Raw v1 callbacks expose scoped evidence; the later host adapter owns standalone notices.
        assert three._host_events(live) == scoped['events']
        assert standalone['events'] != scoped['events']
    finally:
        _release(native, result)
