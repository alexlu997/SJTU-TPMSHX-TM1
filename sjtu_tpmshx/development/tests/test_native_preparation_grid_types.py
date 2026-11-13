"""Keep original scalar arithmetic across the complete typed 2D grid boundary."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict
import dis
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import grid_ports_reference, grid_source_reference
from sjtu_tpmshx.development.tests import test_native_prepare_adapter as adapter
from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as v2
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as v3
from sjtu_tpmshx.development.tests import test_native_preparation_continuous as v4
from sjtu_tpmshx.shared.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, GeometryConfig, PartialBCConfig, SolverConfig, bc_to_dict,
)
from sjtu_tpmshx.shared.models import _native_grid

_GridKinds = v1._structure('PreparationGridKindsV7', [
    ('abi_version', v1._U), ('struct_size', v1._S),
    ('lengths', v2._Kind * 2), ('ports', (v2._Kind * 4) * 2)])
_OPERATIONS = ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case')
_SCOPES = ('uniform', 'continuous')
_PORT_FIELDS = ('in_ctr', 'in_w', 'out_ctr', 'out_w')


def _signature(scope, operation):
    if scope == 'uniform':
        return operation, v3._Input, v3._Result if operation == _OPERATIONS[2] else v3._Flow, 3
    if scope == 'continuous':
        name = {'prepare_inlet_mass_capacities': 'prepare_continuous_inlet_mass_capacities',
                'resolve_inlet_flow': 'resolve_continuous_inlet_flow',
                'prepare_flow_case': 'prepare_continuous_flow_case'}[operation]
        return name, v4._Input, v4._Result if operation == _OPERATIONS[2] else v4._Flow, 4


@pytest.fixture(scope='module')
def native():
    path = os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or v1._library_path()
    library = ct.CDLL(path)
    for scope in _SCOPES:
        for operation in _OPERATIONS:
            name, source, result, _ = _signature(scope, operation)
            function = getattr(library, 'tpmshx_' + name + '_2d_v7')
            function.argtypes = [ct.POINTER(source), ct.POINTER(_GridKinds), ct.POINTER(v1._Options),
                ct.POINTER(v1._Callbacks), ct.POINTER(result), ct.POINTER(v2._Failure),
                ct.POINTER(ct.c_char), v1._S]
            function.restype = ct.c_int
    for name, result in [
            ('flow_2d_release_v3', v3._Flow), ('flow_case_2d_release_v3', v3._Result),
            ('continuous_flow_2d_release_v4', v4._Flow), ('continuous_case_2d_release_v4', v4._Result)]:
        function = getattr(library, 'tpmshx_preparation_' + name)
        function.argtypes, function.restype = [ct.POINTER(result)], None
    return library


@pytest.fixture(autouse=True)
def clear_reference_caches():
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    yield
    compute.cache_clear()
    compute_geometry.cache_clear()


def _kinds(config):
    def kind(value):
        scalar = _native_grid._scalar(value)
        return v2._Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))
    output = _GridKinds(7, ct.sizeof(_GridKinds))
    output.lengths[:] = tuple(kind(value) for value in (config.geometry.L_dom_m, config.geometry.H_dom_m))
    for index, side in enumerate('AB'):
        port = getattr(config, 'bc_' + side)
        output.ports[index][:] = tuple(kind(getattr(port, name)) for name in _PORT_FIELDS)
    return output


def _ci_config(integer=np.int8, floating=np.float16):
    return ComputeConfig(
        geometry=GeometryConfig(L_dom_m=integer(1), H_dom_m=np.int16(2)),
        solver=SolverConfig(Nx=12, Ny=12, Nz=1), extrap=ExtrapPolicy(allow=True),
        bc_A=PartialBCConfig(dir=0, in_ctr=integer(1), out_ctr=integer(1),
            in_w=floating(.2), out_w=floating(.2), uniform_inlet_2d=True),
        bc_B=PartialBCConfig(dir=3, in_ctr=.5, out_ctr=.5,
            in_w=1., out_w=1., uniform_inlet_2d=True))


def _configuration(scope):
    if scope == 'uniform':
        config = v3._configuration(pair=('air', 'air'))
    elif scope == 'continuous':
        config = v4._configuration(pair=('air', 'air'), nx=4, ny=3, mirror=False, order=2)
    config.geometry.L_dom_m, config.geometry.H_dom_m = np.float16(.125), np.float32(.0625)
    config.geometry.Lz_m = .042
    config.solver.Nx = config.solver.Ny = 16
    for side, direction in zip('AB', (0, 1)):
        setattr(config, 'bc_' + side, PartialBCConfig(dir=direction,
            in_ctr=np.float16(.03125), in_w=np.float32(.03125),
            out_ctr=np.float32(.03125), out_w=np.float16(.03125),
            uniform_inlet_2d=side == 'A'))
    return config


def _source(config, scope, targets=None):
    if scope == 'uniform':
        return v3._input(config, targets)
    if scope == 'continuous':
        return v4._input(config, targets)


def _storage(source, scope):
    if scope == 'continuous':
        return [source, source._decision, *_storage(source._flow, 'uniform')]
    return [source, *source._source._buffers]


def _call(native, scope, config, operation='prepare_flow_case', targets=None, *,
          source=None, kinds=None, stop_event=None):
    source = _source(config, scope, targets) if source is None else source
    kinds = _kinds(config) if kinds is None else kinds
    name, _, result_type, version = _signature(scope, operation)
    result, failure = result_type(version, ct.sizeof(result_type)), v2._Failure(2, ct.sizeof(v2._Failure))
    error, live = ct.create_string_buffer(4096), []
    options = v1._Options(1, ct.sizeof(v1._Options), 0, config.extrap.allow, 0.)
    def event(_context, pointer):
        item = pointer.contents
        live.append((item.kind, v1._text(item.logger), v1._text(item.message), item.floating_event))
        return int(stop_event is not None and len(live) == stop_event)
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    watched = [kinds, *_storage(source, scope)]
    before = [bytes(value) for value in watched]
    status = getattr(native, 'tpmshx_' + name + '_2d_v7')(ct.byref(source), ct.byref(kinds),
        ct.byref(options), ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    assert [bytes(value) for value in watched] == before
    return status, result, failure, error.value.decode(), live, source, kinds


def _release(native, scope, result):
    {'uniform': v3._release, 'continuous': v4._release}[scope](native, result)


def _check_frozen_grid_and_ports(actual, expected, config):
    ports = tuple(bc_to_dict(getattr(config, 'bc_' + side), config.geometry.L_dom_m,
                            config.geometry.H_dom_m, side='A') for side in 'AB')
    widths = grid_source_reference.build_grid_2d(config.geometry.L_dom_m, config.geometry.H_dom_m,
        config.solver.Nx, config.solver.Ny, ports,
        zone_axis=config.zones.axis if config.zones.enabled else None,
        port_wall_refine=config.flags.port_wall_refine)
    for name, values in zip(('dx', 'dy', 'x_breaks', 'y_breaks'), widths[:4]):
        v1._same(v1._array(getattr(actual, name)), values, 'frozen ' + name)
    for index, (side, port) in enumerate(zip('AB', ports)):
        output = actual.sides[index]
        cross = expected.grid['dy' if port['dir'] < 2 else 'dx']
        rectangles = grid_ports_reference._port_rectangles(port, 1.)
        for end in ('inlet', 'outlet'):
            lower, upper = rectangles[end + '_rect'][:2]
            v1._same(getattr(output, end + '_bounds'), [lower, upper], side + ' ' + end + ' bounds')
            raw, profile = grid_source_reference._port_fractions_1d(cross, lower, upper,
                uniform=end == 'inlet' and port.get('uniform_inlet_2d', False))
            v1._same(v1._array(getattr(output, end + '_geometry')), raw, side + ' ' + end + ' opening')
            v1._same(v1._array(getattr(output, end + '_profile')), profile, side + ' ' + end + ' profile')
            if end == 'outlet':
                staggered = grid_source_reference._port_overlap_1d(cross, lower, upper, staggered=True)
                v1._same(v1._array(output.outlet_u_fraction), staggered, side + ' staggered outlet')


def _check_spatial_fields(result, expected):
    shape = expected.design_fields['L_field_m'].shape
    for name, key in [('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h')]:
        v1._same(v1._array(getattr(result, name)).reshape(shape),
                 expected.parameters['thermal_geometry']['fields'][key], key)
    for index, side in enumerate('AB'):
        v1._same(v1._array(result.fluid_conductivity[index]).reshape(shape),
                 expected.design_fields['K_ff' + side + '_arr'], side + ' fluid conductivity')


def _full(native, monkeypatch, scope, config, targets=None):
    before = deepcopy(asdict(config))
    expected, state = v3._reference(monkeypatch, 'prepare_flow_case', config, targets)
    status, result, failure, error, live, _, kinds = _call(native, scope, config, targets=targets)
    assert status == 0, error
    try:
        assert result.owner and not failure.kind
        resolved = state['resolved']
        prepared = result.prepared
        assert not prepared.values.owner
        v2._check_values(prepared, expected, resolved)
        final_events = v3._events(prepared.values)
        v2._check_evidence(prepared, expected, state['records']['final'], state['events']['final'],
                           final_events, resolved, event_converter=v4._host_events)
        _check_frozen_grid_and_ports(prepared.values, expected, resolved)
        assert not result.flow.owner
        v3._resolved(result.flow, resolved)
        v3._flow_evidence(result.flow.evidence, state)
        assert live == v3._events(result.flow.evidence) + final_events
        if scope == 'continuous':
            _check_spatial_fields(result, expected)
            v4._snapshot(result.controls, config)
            for index, side in enumerate('AB'):
                metadata = expected.parameters['flow_inputs'][side]['metadata']
                for name in ('transfer_policy', 'geometry_application'):
                    assert v1._text(getattr(result.drag[index], name)) == metadata.get(name, '')
        # The result must remain usable after borrowed type tags are changed.
        kinds.lengths[0].precision = 8
        kinds.ports[0][1].strong = 0
        _check_frozen_grid_and_ports(prepared.values, expected, resolved)
    finally:
        _release(native, scope, result)
    adapter._same(asdict(config), before, 'unchanged input')
    return expected


def test_public_prepare_restores_original_integer_half_width_contract(monkeypatch):
    config = _ci_config()
    before = deepcopy(asdict(config))
    expected = adapter._capture(monkeypatch, adapter.reference, 'full', config)
    actual = adapter._capture(monkeypatch, adapter.api, 'full', config)
    adapter._same(actual, expected)
    adapter._same(asdict(config), before, 'unchanged input')
    assert actual[0].grid['dy'][0] == .179931640625


def test_raw_typed_prepare_matches_original_ci_grid(native, monkeypatch):
    case = _full(native, monkeypatch, 'uniform', _ci_config())
    assert case.grid['dy'][0] == .179931640625


@pytest.mark.parametrize('integer', [np.int8, np.uint8, np.int16, np.uint16,
                                     np.int32, np.uint32, np.int64, np.uint64])
@pytest.mark.parametrize('floating', [np.float16, np.float32])
def test_raw_grid_integer_and_narrow_float_promotion(native, monkeypatch, integer, floating):
    _full(native, monkeypatch, 'uniform', _ci_config(integer, floating))


@pytest.mark.parametrize('integer,floating', [(int, float), (int, np.float16),
    (np.int8, float), (np.int8, np.float64)])
def test_raw_grid_keeps_python_weak_scalars(native, monkeypatch, integer, floating):
    _full(native, monkeypatch, 'uniform', _ci_config(integer, floating))


@pytest.mark.parametrize('direction', range(4))
@pytest.mark.parametrize('refine', [False, True])
@pytest.mark.parametrize('full_face', [False, True])
def test_raw_typed_ports_keep_direction_normalization_and_refinement(native, monkeypatch,
                                                                    direction, refine, full_face):
    config = _ci_config()
    config.flags.port_wall_refine = refine
    config.solver.Nx = config.solver.Ny = 96 if refine else 12
    for side, selected in zip('AB', (direction, (direction + 1) % 4)):
        center = np.int8(1) if selected < 2 else np.float32(.5)
        width = np.float16(0. if full_face else .2)
        setattr(config, 'bc_' + side, PartialBCConfig(dir=selected, in_ctr=center,
            out_ctr=center, in_w=width, out_w=width, uniform_inlet_2d=side == 'A'))
    _full(native, monkeypatch, 'uniform', config)


@pytest.mark.parametrize('first_narrow', [False, True])
def test_raw_equal_breakpoints_keep_first_scalar_kind(native, monkeypatch, first_narrow):
    config = _ci_config()
    config.solver.Nx = config.solver.Ny = 13
    kinds = (np.float16, float) if first_narrow else (float, np.float16)
    for side, dtype in zip('AB', kinds):
        setattr(config, 'bc_' + side, PartialBCConfig(dir=0,
            in_ctr=dtype(.5), in_w=dtype(.25), out_ctr=dtype(.5), out_w=dtype(.25)))
    _full(native, monkeypatch, 'uniform', config)


@pytest.mark.parametrize('scope', ['uniform', 'continuous'])
@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('targets_mode', ['explicit', 'configured', 'mixed'])
def test_typed_grid_capacity_resolution_and_complete_flow(native, monkeypatch, scope, operation, targets_mode):
    config = _configuration(scope)
    capacities, _ = v3._reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    selected = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    targets = selected if targets_mode == 'explicit' and operation != _OPERATIONS[0] else None
    for index, side in enumerate('AB'):
        if targets_mode != 'explicit' and (targets_mode != 'mixed' or side == 'A'):
            fluid = getattr(config, 'fluid_' + side)
            fluid.mass_flow_kg_s, fluid.u_mps = selected[index], -99.
        elif targets is not None or operation == _OPERATIONS[0]:
            getattr(config, 'fluid_' + side).u_mps = -99.
    if operation == _OPERATIONS[2]:
        _full(native, monkeypatch, scope, config, targets)
        return
    expected, state = v3._reference(monkeypatch, operation, config, targets)
    status, result, failure, error, live, _, _ = _call(native, scope, config, operation, targets)
    assert status == 0, error
    try:
        assert result.owner and not failure.kind
        flow = result.flow if scope == 'continuous' else result
        assert flow.have_capacities
        for index, side in enumerate('AB'):
            v3._scalar(flow.capacities[index], capacities[side])
            if operation == _OPERATIONS[0]:
                v3._scalar(flow.capacities[index], expected[side])
        if operation == _OPERATIONS[1]:
            v3._resolved(flow, expected)
            for index, side in enumerate('AB'):
                v3._scalar(flow.speeds[index], getattr(expected, 'fluid_' + side).u_mps)
        v3._flow_evidence(flow.evidence, state)
        assert v4._host_events(live) == state['events']['preliminary']
    finally:
        _release(native, scope, result)


@pytest.mark.parametrize('scope', ['uniform', 'continuous'])
def test_raw_no_target_resolution_keeps_unvalidated_physical_input(native, scope):
    config = _configuration(scope)
    config.fluid_A.T_in_K = -1.
    config.geometry.L_dom_m = np.float16(-1.)
    status, result, failure, error, live, source, _ = _call(native, scope, config, _OPERATIONS[1])
    assert status == 0, error
    try:
        flow = result.flow if scope == 'continuous' else result
        original = source.values.values if scope == 'continuous' else source.values
        assert not failure.kind and not flow.have_capacities and not live
        assert v1._struct_values(flow.input.values) == v1._struct_values(original.values)
        assert flow.evidence.range_count == flow.evidence.event_count == flow.evidence.warning_count == 0
    finally:
        _release(native, scope, result)


@pytest.mark.parametrize('dtype', [np.float16, np.float32])
@pytest.mark.parametrize('nx', [1, 4])
def test_typed_continuous_domain_controls_and_final_fields(native, monkeypatch, dtype, nx):
    config = _configuration('continuous')
    config.geometry.L_dom_m, config.geometry.H_dom_m = dtype(.125), dtype(.0625)
    controls = v4._configuration(pair=('air', 'air'), nx=nx, ny=3, mirror=False, order=2)
    config.zones = controls.zones
    _full(native, monkeypatch, 'continuous', config)
    expected = adapter._capture(monkeypatch, adapter.reference, 'full', config)
    actual = adapter._capture(monkeypatch, adapter.api, 'full', config)
    adapter._same(actual, expected)


@pytest.mark.parametrize('scope', _SCOPES)
@pytest.mark.parametrize('selection', ['version', 'size', 'weak-precision', 'weak-layout',
    'float-precision', 'integer-precision', 'array-layout', 'unknown-strength'])
def test_typed_grid_descriptor_rejects_invalid_tags(native, scope, selection):
    config = _configuration(scope)
    kinds = _kinds(config)
    if selection == 'version':
        kinds.abi_version = 0
    elif selection == 'size':
        kinds.struct_size -= 1
    else:
        tag = kinds.ports[1][3] if selection == 'array-layout' else kinds.lengths[0]
        values = {'weak-precision': (16, 0, 0), 'weak-layout': (64, 0, 1),
                  'float-precision': (8, 1, 1), 'integer-precision': (12, 2, 1),
                  'array-layout': (32, 1, 2), 'unknown-strength': (64, 3, 1)}[selection]
        tag.precision, tag.strong, tag.layout = values
    _, _, result_type, version = _signature(scope, _OPERATIONS[2])
    status, result, _, error, _, _, _ = _call(native, scope, config, kinds=kinds)
    assert status != 0 and error
    assert bytes(result) == bytes(result_type(version, ct.sizeof(result_type)))


@pytest.mark.parametrize('scope', _SCOPES)
@pytest.mark.parametrize('target', ['source', 'result', 'failure', 'error', 'options', 'callbacks'])
def test_typed_descriptor_storage_is_disjoint(native, scope, target):
    config = _configuration(scope)
    source, kinds = _source(config, scope), _kinds(config)
    name, source_type, result_type, version = _signature(scope, _OPERATIONS[2])
    result = result_type(version, ct.sizeof(result_type))
    failure, error = v2._Failure(2, ct.sizeof(v2._Failure)), ct.create_string_buffer(b'unchanged', 4096)
    options = v1._Options(1, ct.sizeof(v1._Options), 0, 1, 0.)
    callback = v1._EventFunction(lambda context, event: 0)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    values = {'source': source, 'result': result, 'failure': failure, 'error': error,
              'options': options, 'callbacks': callbacks}
    original = values[target]
    storage = ct.create_string_buffer(max(ct.sizeof(original), ct.sizeof(kinds)))
    ct.memmove(storage, ct.byref(original), ct.sizeof(original))
    grid_pointer = ct.cast(storage, ct.POINTER(_GridKinds))
    source_pointer = ct.cast(storage, ct.POINTER(source_type)) if target == 'source' else ct.byref(source)
    result_pointer = ct.cast(storage, ct.POINTER(result_type)) if target == 'result' else ct.byref(result)
    failure_pointer = ct.cast(storage, ct.POINTER(v2._Failure)) if target == 'failure' else ct.byref(failure)
    options_pointer = ct.cast(storage, ct.POINTER(v1._Options)) if target == 'options' else ct.byref(options)
    callbacks_pointer = ct.cast(storage, ct.POINTER(v1._Callbacks)) if target == 'callbacks' else ct.byref(callbacks)
    error_pointer, capacity = (storage, len(storage)) if target == 'error' else (error, len(error))
    watched = [storage, source, result, failure, error, options, callbacks]
    before = [bytes(value) for value in watched]
    status = getattr(native, 'tpmshx_' + name + '_2d_v7')(source_pointer, grid_pointer,
        options_pointer, callbacks_pointer, result_pointer, failure_pointer, error_pointer, capacity)
    assert status != 0
    assert [bytes(value) for value in watched] == before


@pytest.mark.parametrize('scope,borrowed', [('uniform', 'nu-text'), ('continuous', 'controls')])
def test_typed_descriptor_cannot_overlap_borrowed_payload(native, scope, borrowed):
    config = _configuration(scope)
    source, kinds = _source(config, scope), _kinds(config)
    if borrowed == 'nu-text':
        source.values.sco2_nu.source = v1._Text(ct.cast(ct.byref(kinds), ct.POINTER(ct.c_char)), 1)
    elif borrowed == 'controls':
        source.controls.decision_mm = v1._Array(ct.cast(ct.byref(kinds), ct.POINTER(v1._D)), 1)
    name, _, result_type, version = _signature(scope, _OPERATIONS[2])
    result, failure = result_type(version, ct.sizeof(result_type)), v2._Failure(2, ct.sizeof(v2._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    watched = [kinds, source, result, failure, error]
    before = [bytes(value) for value in watched]
    status = getattr(native, 'tpmshx_' + name + '_2d_v7')(ct.byref(source), ct.byref(kinds),
        None, None, ct.byref(result), ct.byref(failure), error, len(error))
    assert status != 0
    assert [bytes(value) for value in watched] == before


@pytest.mark.parametrize('scope', _SCOPES)
def test_typed_grid_requires_descriptor_without_partial_output(native, scope):
    config = _configuration(scope)
    source = _source(config, scope)
    name, _, result_type, version = _signature(scope, _OPERATIONS[2])
    result, failure = result_type(version, ct.sizeof(result_type)), v2._Failure(2, ct.sizeof(v2._Failure))
    error = ct.create_string_buffer(4096)
    before = bytes(result)
    status = getattr(native, 'tpmshx_' + name + '_2d_v7')(ct.byref(source), None,
        None, None, ct.byref(result), ct.byref(failure), error, len(error))
    assert status != 0 and bytes(result) == before


def test_typed_grid_callback_stop_keeps_prior_evidence(native):
    config = _ci_config()
    config.fluid_A.u_mps = 500.
    status, accepted, _, error, events, _, _ = _call(native, 'uniform', config)
    assert status == 0, error
    _release(native, 'uniform', accepted)
    assert events
    status, result, failure, error, live, _, _ = _call(native, 'uniform', config, stop_event=1)
    assert status != 0 and failure.kind and error and live == events[:1]
    assert bytes(result) == bytes(v3._Result(3, ct.sizeof(v3._Result)))


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('field', ['L_dom_m', 'in_ctr'])
@pytest.mark.parametrize('earlier', ['none', 'geometry-object', 'water-state', 'extrapolation'])
@pytest.mark.parametrize('fixed', [False, True])
def test_host_grid_object_error_keeps_original_order(monkeypatch, spatial, field, earlier, fixed):
    config = (v4._configuration if spatial else v3._configuration)(pair=('air', 'water'))
    if field == 'L_dom_m':
        config.geometry.L_dom_m = np.asarray(config.geometry.L_dom_m)
    else:
        config.bc_A.in_ctr = np.asarray(.02)
        config.bc_A.out_ctr = .02
        config.bc_A.in_w = config.bc_A.out_w = .02
    if earlier == 'geometry-object':
        config.geometry.L_cell_mm = np.asarray(7.)
    elif earlier == 'water-state':
        config.fluid_B.T_in_K = 450.
    elif earlier == 'extrapolation':
        config.fluid_A.u_mps = 500.
    targets = (.003, .03) if fixed else None
    expected = adapter._failure(monkeypatch, adapter.reference, config, targets)
    actual = adapter._failure(monkeypatch, adapter.api, config, targets)
    assert actual == expected


@pytest.mark.parametrize('spatial', [False, True])
def test_full_face_does_not_consume_replaced_port_objects(monkeypatch, spatial):
    config = (v4._configuration if spatial else v3._configuration)(pair=('air', 'water'))
    for side in 'AB':
        port = getattr(config, 'bc_' + side)
        port.in_ctr = port.out_ctr = np.asarray(0.)
        port.in_w = port.out_w = np.asarray(0.)
    adapter._same(adapter._capture(monkeypatch, adapter.api, 'full', config),
                  adapter._capture(monkeypatch, adapter.reference, 'full', config))


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('operation', _OPERATIONS)
def test_typed_continuous_rejects_repeated_control_nodes(native, monkeypatch, axis, operation):
    config = v4._configuration(pair=('air', 'air'), nx=4097 if axis == 'x' else 1,
                               ny=4097 if axis == 'y' else 1, mirror=False, order=1)
    config.geometry.L_dom_m = np.float16(.125)
    config.geometry.H_dom_m = np.float16(.0625)
    config.zones.config['x_decision'] = [7.] * 4097 + [.6] * 4097
    targets = (.003, .004) if operation == 'resolve_inlet_flow' else None
    with pytest.raises(ValueError, match='control axes must increase') as expected:
        v3._reference(monkeypatch, operation, config, targets)
    status, result, failure, error, _, _, _ = _call(native, 'continuous', config, operation, targets)
    try:
        assert status != 0 and failure.kind == 1 and error == str(expected.value)
        assert not result.owner
    finally:
        _release(native, 'continuous', result)


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_typed_continuous_keeps_exact_domain_coverage_gate(native, monkeypatch, operation):
    config = v4._configuration(pair=('air', 'air'))
    config.geometry.L_dom_m = np.float16(.182)
    config.geometry.H_dom_m = np.float16(.042)
    targets = (.003, .004) if operation == 'resolve_inlet_flow' else None
    with pytest.raises(ValueError, match='cell widths must be finite, positive and cover') as expected:
        v3._reference(monkeypatch, operation, config, targets)
    status, result, failure, error, _, _, _ = _call(native, 'continuous', config, operation, targets)
    try:
        assert status != 0 and failure.kind == 1 and error == str(expected.value)
        assert not result.owner
    finally:
        _release(native, 'continuous', result)


@pytest.mark.parametrize('scope,error', [
    ('integer', 'prepared y grid does not cover the physical domain'),
    ('uniform', None), ('continuous', None)])
def test_public_typed_case_keeps_saved_grid_and_ports(monkeypatch, tmp_path, scope, error):
    from sjtu_tpmshx.shared.io.case_io import load_case, save_case
    from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs

    config = _ci_config() if scope == 'integer' else _configuration(scope)
    case = adapter._capture(monkeypatch, adapter.api, 'full', config)[0]
    reference = adapter._capture(monkeypatch, adapter.reference, 'full', config)[0]
    adapter._same(case, reference)
    save_case(case, tmp_path / 'case.h5')
    save_case(reference, tmp_path / 'reference.h5')
    restored = load_case(tmp_path / 'case.h5')
    expected_case = load_case(tmp_path / 'reference.h5')
    adapter._same(restored.grid, case.grid)
    adapter._same(restored.design_fields, case.design_fields)
    adapter._same(restored, expected_case)
    if error is not None:
        for saved in (expected_case, restored):
            with pytest.raises(ValueError) as failure:
                build_execution_inputs(saved, copy_design=False)
            assert str(failure.value) == error
        return
    actual, _ = build_execution_inputs(restored, copy_design=False)
    expected, _ = build_execution_inputs(expected_case, copy_design=False)
    for name in ('cfgA', 'cfgB', 'boundary_openings', 'flow_inputs'):
        adapter._same(actual[name], expected[name])


def _axis_config(count, axis):
    config = v4._configuration(pair=('air', 'air'), nx=count if axis == 'x' else 1,
                               ny=count if axis == 'y' else 1, mirror=False, order=1)
    config.geometry.L_dom_m, config.geometry.H_dom_m = np.float16(.125), np.float16(.0625)
    config.zones.config['x_decision'] = [7.] * count + [.6] * count
    return config


def _axis_observation(monkeypatch, module, config, operation, *, filter_module=False):
    from sjtu_tpmshx.shared.logutil import get_logger
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    events = []
    targets = (.003, .004)
    result, failure = None, None
    with monkeypatch.context() as patch, warnings.catch_warnings():
        warnings.simplefilter('always')
        if filter_module:
            warnings.filterwarnings('error', module=r'^numpy\._core\.function_base$')
        patch.setattr(warnings, 'showwarning', lambda message, category, filename, lineno, *args, **kwargs:
                      events.append((category.__name__, str(message), filename, lineno)))
        patch.setattr(get_logger('sjtu_tpmshx.preprocess.two_d.preparation'), 'info',
                      lambda message: events.append(('log', message)))
        try:
            if operation == 'capacity':
                result = module.prepare_inlet_mass_capacities(config)
            elif operation == 'resolve':
                result = module.resolve_fixed_mass_flow_config(config,
                    mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1])
            elif operation == 'fixed':
                result = module.prepare_fixed_mass_flow_case(config, case_id='axis-error',
                    mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1])
            else:
                result = module.prepare_case(config, case_id='axis-error')
        except Exception as caught:
            failure = type(caught), str(caught)
    return result, failure, events


def _axis_failure(monkeypatch, module, config, operation, *, filter_module=False):
    _result, failure, events = _axis_observation(
        monkeypatch, module, config, operation, filter_module=filter_module)
    assert failure is not None
    return *failure, events


@pytest.mark.parametrize('count', [4097, 65521])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_control_axis_failure_keeps_host_events(monkeypatch, count, axis, policy, operation):
    config = _axis_config(count, axis)
    with np.errstate(over=policy, invalid=policy):
        expected = _axis_failure(monkeypatch, adapter.reference, config, operation)
        actual = _axis_failure(monkeypatch, adapter.api, config, operation)
    assert actual == expected


@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_control_axis_keeps_original_warning_module_filter(monkeypatch, operation):
    config = _axis_config(65521, 'x')
    with np.errstate(over='warn', invalid='warn'):
        expected = _axis_failure(monkeypatch, adapter.reference, config, operation, filter_module=True)
        actual = _axis_failure(monkeypatch, adapter.api, config, operation, filter_module=True)
    assert expected[0] is RuntimeWarning
    assert actual == expected


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_control_axis_error_precedes_only_later_host_grid_error(monkeypatch, axis, operation):
    config = _axis_config(4097, axis)
    name = 'H_dom_m' if axis == 'x' else 'L_dom_m'
    setattr(config.geometry, name, np.asarray(getattr(config.geometry, name)))
    assert _axis_failure(monkeypatch, adapter.api, config, operation) == _axis_failure(
        monkeypatch, adapter.reference, config, operation)


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('axis', ['x', 'y'])
def test_raw_control_axis_keeps_cast_and_divide_events(native, operation, axis):
    config = _axis_config(65521, axis)
    targets = (.003, .004) if operation == 'resolve_inlet_flow' else None
    status, result, failure, error, events, _, _ = _call(native, 'continuous', config, operation, targets)
    try:
        assert status != 0 and failure.kind == 1 and not result.owner
        assert error.startswith('control axes must increase')
        assert [event[3] for event in events if event[0] == 2] == [4 | 8 << 8, 4 | 8 << 8, 1 | 4 << 8]
        assert [event[0] for event in events] == ([2, 2, 2] if operation == 'prepare_flow_case'
                                                 else [0, 2, 2, 2])
    finally:
        _release(native, 'continuous', result)



def _underflow_config(axis, sampling, *, one_cell=False):
    count = 1 if sampling else 2
    config = v4._configuration(pair=('air', 'air'), nx=count if axis == 'x' else 1,
                               ny=count if axis == 'y' else 1, mirror=False, order=1)
    config.geometry.L_dom_m, config.geometry.H_dom_m = np.float16(.125), np.float16(.0625)
    setattr(config.geometry, 'L_dom_m' if axis == 'x' else 'H_dom_m',
            np.float16(2. ** (-24 if sampling else -15)))
    config.solver.Nx = config.solver.Ny = 4
    setattr(config.solver, 'Nx' if axis == 'x' else 'Ny', 1 if one_cell else 4 if sampling else 3)
    config.flags.port_wall_refine = False
    config.bc_A = PartialBCConfig(dir=0 if axis == 'x' else 2)
    config.bc_B = PartialBCConfig(dir=0 if axis == 'x' else 2)
    return config


def _nominal_divide_sources():
    from sjtu_tpmshx.development.tests import preparation_case_reference
    from sjtu_tpmshx.preprocess.two_d import preparation

    def locations(module):
        function = module._parse_geometry_inputs_cfg
        return [(function.__code__.co_filename, item.positions.lineno)
                for item in dis.get_instructions(function)
                if item.opname == 'BINARY_OP' and item.argrepr == '/']

    original, current = locations(preparation_case_reference), locations(preparation)
    assert len(original) == len(current) == 2
    return dict(zip(original, current))


def _normalize_nominal_sources(events):
    sources = _nominal_divide_sources()
    return [(*event[:2], *sources.get(event[2:], event[2:])) if len(event) == 4 else event
            for event in events]


@pytest.mark.parametrize('sampling', [False, True], ids=['nominal-quotient', 'requested-sampling'])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_half_domain_underflow_keeps_host_failure_order(monkeypatch, sampling, axis, policy, operation):
    config = _underflow_config(axis, sampling)
    with np.errstate(under=policy):
        error, message, events = _axis_failure(monkeypatch, adapter.reference, config, operation)
        actual = _axis_failure(monkeypatch, adapter.api, config, operation)
    expected_events = _normalize_nominal_sources(events)
    assert actual == (error, message, expected_events)
    if policy == 'raise':
        assert error is FloatingPointError and message == 'underflow encountered in scalar divide'
    else:
        assert error is ValueError
        floating = [event for event in expected_events if event[0] == 'RuntimeWarning']
        assert floating[0] == ('RuntimeWarning', 'underflow encountered in scalar divide',
                              *tuple(_nominal_divide_sources().values())[axis == 'y'])
        if operation == 'full':
            assert len(floating) == (3 if sampling else 1)
            assert message == ('sampling axes must be finite, increasing and inside the field domain'
                               if sampling else 'cell widths must be finite, positive and cover the field domain')


@pytest.mark.parametrize('axis', ['x', 'y'])
def test_one_cell_half_domain_keeps_success_and_midpoint_sources(monkeypatch, axis):
    config = _underflow_config(axis, True, one_cell=True)
    with np.errstate(under='warn'):
        expected = _axis_observation(monkeypatch, adapter.reference, config, 'full')
        actual = _axis_observation(monkeypatch, adapter.api, config, 'full')
    assert expected[1] is None
    adapter._same(actual, expected)
    floating = [event for event in expected[2] if event[0] == 'RuntimeWarning']
    assert len(floating) == 4
    assert all(event[1] == 'underflow encountered in scalar divide' for event in floating)
    assert not any(event[2:] in _nominal_divide_sources() for event in floating)


@pytest.mark.parametrize('sampling', [False, True], ids=['nominal-quotient', 'requested-sampling'])
@pytest.mark.parametrize('axis', ['x', 'y'])
def test_raw_half_domain_keeps_nominal_and_midpoint_event_order(native, axis, sampling):
    config = _underflow_config(axis, sampling)
    status, result, failure, error, events, _, _ = _call(native, 'continuous', config)
    try:
        assert status != 0 and failure.kind == 1 and not result.owner
        assert error == ('sampling axes must be finite, increasing and inside the field domain'
                         if sampling else 'cell widths must be finite, positive and cover the field domain')
        sources = ['nominal-grid-' + axis]
        if sampling:
            sources += ['control-axis-midpoint', 'control-axis-check-midpoint']
        assert [(event[2], event[3]) for event in events if event[0] == 2] == [
            (name, 8 | 4 << 8 | 0x10000) for name in sources]
    finally:
        _release(native, 'continuous', result)


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
def test_uniform_half_domain_keeps_one_nominal_event(monkeypatch, axis, policy):
    config = _underflow_config(axis, False)
    config.zones.enabled = False
    with np.errstate(under=policy):
        expected, failure, events = _axis_observation(monkeypatch, adapter.reference, config, 'full')
        actual = _axis_observation(monkeypatch, adapter.api, config, 'full')
    adapter._same(actual, (expected, failure, _normalize_nominal_sources(events)))
    if policy == 'warn':
        assert failure is None
        assert len([event for event in events if event[0] == 'RuntimeWarning']) == 1
    else:
        assert failure == (FloatingPointError, 'underflow encountered in scalar divide')


@pytest.mark.parametrize('scope', _SCOPES)
@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', [None, 'source_abi', 'source_size', 'result_abi',
    'result_size', 'grid_abi', 'grid_size', 'grid_null'])
def test_typed_owned_views_reject_diagnostic_aliases(native, scope, operation, destination, invalid):
    config = (v3._configuration('Gyroid', ('air', 'air')) if scope == 'uniform'
              else v4._configuration(pair=('air', 'air')))
    config.geometry.Lz_m = .042
    if operation == 'resolve_inlet_flow':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    status, result, _, error, _, source, kinds = _call(native, scope, config, operation)
    assert status == 0 and result.owner, error
    if invalid is not None and invalid != 'grid_null':
        selected, field = invalid.split('_')
        target = {'source': source, 'result': result, 'grid': kinds}[selected]
        setattr(target, 'abi_version' if field == 'abi' else 'struct_size', 0)
    grid_pointer = None if invalid == 'grid_null' else ct.byref(kinds)
    watched = [kinds, *_storage(source, scope)]
    before = [bytes(value) for value in watched]
    name, _, _, _ = _signature(scope, operation)
    function = getattr(native, 'tpmshx_' + name + '_2d_v7')
    try:
        labels = v4._check_owned_aliases(lambda failure, error, capacity: function(
            ct.byref(source), grid_pointer, None, None, ct.byref(result), failure, error, capacity),
            result, destination)
        if scope == 'continuous':
            assert any('.controls.decision_mm' in label for label in labels)
        if operation == 'prepare_flow_case':
            assert any('.total_porosity' in label for label in labels)
        assert [bytes(value) for value in watched] == before
    finally:
        _release(native, scope, result)


@pytest.mark.parametrize('scope', _SCOPES)
@pytest.mark.parametrize('operation', _OPERATIONS)
def test_typed_owned_output_keeps_safe_reuse_diagnostics(native, scope, operation):
    config = (v3._configuration('Gyroid', ('air', 'air')) if scope == 'uniform'
              else v4._configuration(pair=('air', 'air')))
    config.geometry.Lz_m = .042
    if operation == 'resolve_inlet_flow':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    status, result, _, error, _, source, kinds = _call(native, scope, config, operation)
    assert status == 0 and result.owner, error
    outer = bytes(result)
    buffers = [(address, ct.string_at(address, size))
               for _, address, size in v4._visible_buffers(result)]
    watched = [kinds, *_storage(source, scope)]
    before = [bytes(value) for value in watched]
    failure, error = v2._Failure(2, ct.sizeof(v2._Failure)), ct.create_string_buffer(4096)
    events = []

    def event(_context, _pointer):
        events.append(True)
        return 0

    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    name, _, _, _ = _signature(scope, operation)
    try:
        status = getattr(native, 'tpmshx_' + name + '_2d_v7')(
            ct.byref(source), ct.byref(kinds), None, ct.byref(callbacks), ct.byref(result),
            ct.byref(failure), error, len(error))
        assert status == 1 and failure.kind == 1
        assert b'release the previous flow result' in error.value and not events
        assert bytes(result) == outer
        assert all(ct.string_at(address, len(saved)) == saved for address, saved in buffers)
        assert [bytes(value) for value in watched] == before
    finally:
        _release(native, scope, result)
