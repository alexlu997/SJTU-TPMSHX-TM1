"""Compare native canonical XY preparation with the production input path."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as v2
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as v3
from sjtu_tpmshx.shared.domain.compute_config import PartialBCConfig, ZoneInputConfig

_U, _S, _D, _struct = v1._U, v1._S, v1._D, v1._structure
_Controls = _struct('ContinuousControls', [('n_ctrl_x', _S), ('n_ctrl_y', _S),
    ('spline_order', _U), ('symmetric_y', _U), ('L_bounds_mm', _D * 2),
    ('t_bounds_mm', _D * 2), ('decision_mm', v1._Array)])
_Input = _struct('ContinuousInput', [('abi_version', _U), ('struct_size', _S),
    ('values', v3._Input), ('controls', _Controls)])
_Drag = _struct('ContinuousDrag', [('transfer_policy', v1._Text),
    ('geometry_application', v1._Text), ('have_reference_geometry', _U), ('reference_geometry_mm', _D * 2)])
_Flow = _struct('ContinuousFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', v3._Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_Result = _struct('ContinuousCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', v2._Result), ('flow', v3._Flow), ('controls', _Controls),
    ('area_density_per_m', v1._Array), ('hydraulic_diameter_m', v1._Array),
    ('fluid_conductivity', v1._Array * 2), ('drag', _Drag * 2), ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    for name, result in [('prepare_inlet_mass_capacities', _Flow), ('resolve_inlet_flow', _Flow),
                         ('prepare_flow_case', _Result)]:
        function = getattr(library, 'tpmshx_' + name + '_2d_v4')
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(v1._Options), ct.POINTER(v1._Callbacks),
            ct.POINTER(result), ct.POINTER(v2._Failure), ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    library.tpmshx_preparation_continuous_flow_2d_release_v4.argtypes = [ct.POINTER(_Flow)]
    library.tpmshx_preparation_continuous_case_2d_release_v4.argtypes = [ct.POINTER(_Result)]
    return library


def _configuration(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth', *, nx=4, ny=5, mirror=True, order=3):
    config = v3._configuration(topology, pair, mode)
    count = nx * ((ny + 1) // 2 if mirror else ny)
    spec = dict(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=mirror, spline_order=order,
        L_bounds=[4., 8.], t_bounds=[.3, .6],
        x_decision=[float(value) for value in np.r_[np.linspace(4.2, 7.8, count), np.linspace(.57, .32, count)]])
    config.zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec)
    return config


def _input(config, targets=None):
    flow = v3._input(config, targets)
    flow.values.values.geometry_mode = 1
    spec = config.zones.config
    decision = np.asarray(spec['x_decision'], dtype=np.float64)
    controls = _Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['spline_order'], spec['symmetric_y'],
        (_D * 2)(*spec['L_bounds']), (_D * 2)(*spec['t_bounds']),
        v1._Array(decision.ctypes.data_as(ct.POINTER(_D)), decision.size))
    source = _Input(4, ct.sizeof(_Input), flow, controls)
    source._flow, source._decision = flow, decision
    return source


def _call(native, operation, config, targets=None, *, chi=None):
    source = _input(config, targets)
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(4, ct.sizeof(result_type)), v2._Failure(2, ct.sizeof(v2._Failure))
    options = v1._Options(1, ct.sizeof(v1._Options), chi is not None, config.extrap.allow, chi or 0.)
    events, error = [], ct.create_string_buffer(4096)
    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, v1._text(item.logger), v1._text(item.message), item.floating_event))
        return 0
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    before, decisions = bytes(source), source._decision.copy()
    status = getattr(native, 'tpmshx_' + operation + '_2d_v4')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert bytes(source) == before
    v1._same(source._decision, decisions, 'unchanged controls')
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = ('tpmshx_preparation_continuous_case_2d_release_v4' if isinstance(result, _Result)
            else 'tpmshx_preparation_continuous_flow_2d_release_v4')
    getattr(native, name)(ct.byref(result))


def _snapshot(controls, config):
    spec = config.zones.config
    assert (controls.n_ctrl_x, controls.n_ctrl_y, controls.spline_order, bool(controls.symmetric_y)) == (
        spec['n_ctrl_x'], spec['n_ctrl_y'], spec['spline_order'], spec['symmetric_y'])
    v1._same(controls.L_bounds_mm, spec['L_bounds'], 'L bounds')
    v1._same(controls.t_bounds_mm, spec['t_bounds'], 't bounds')
    v1._same(v1._array(controls.decision_mm), spec['x_decision'], 'control snapshot')


def _host_events(events):
    from sjtu_tpmshx.shared.models._native_properties import _floating_events
    result = []
    for event in events:
        if event[0] != 2:
            result.append(event)
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _floating_events([event[3]])
        result.extend((1, '', str(item.message), 0) for item in caught)
    return result


def _full(native, monkeypatch, config, targets=None, *, chi=None):
    before = deepcopy(asdict(config))
    expected, state = v3._reference(monkeypatch, 'prepare_flow_case', config, targets, chi=chi)
    status, result, failure, error, live, source = _call(native, 'prepare_flow_case', config, targets, chi=chi)
    assert status == 0, error
    try:
        assert result.owner and not result.flow.owner and not result.prepared.values.owner and not failure.kind
        _snapshot(result.controls, config)
        source._decision[:] = -1.
        _snapshot(result.controls, config)
        v3._resolved(result.flow, state['resolved'])
        v3._flow_evidence(result.flow.evidence, state)
        with monkeypatch.context() as patch:
            if chi is not None:
                patch.setenv('TPMSHX_CHI_S', str(chi))
            v2._check_values(result.prepared, expected, state['resolved'])
        v2._check_evidence(result.prepared, expected, state['records']['final'], state['events']['final'],
                           v3._events(result.prepared.values), state['resolved'], event_converter=_host_events)
        assert live == v3._events(result.flow.evidence) + v3._events(result.prepared.values)
        assert _host_events(live) == state['events']['preliminary'] + state['events']['final']
        shape = expected.design_fields['L_field_m'].shape
        for name, key in [('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h')]:
            v1._same(v1._array(getattr(result, name)).reshape(shape),
                expected.parameters['thermal_geometry']['fields'][key], key)
        for i, side in enumerate('AB'):
            v1._same(v1._array(result.fluid_conductivity[i]).reshape(shape),
                expected.design_fields['K_ff' + side + '_arr'], side + ' Kff')
            metadata, drag = expected.parameters['flow_inputs'][side]['metadata'], result.drag[i]
            for name in ('transfer_policy', 'geometry_application'):
                assert v1._text(getattr(drag, name)) == metadata.get(name, '')
            assert bool(drag.have_reference_geometry) == ('reference_geometry_mm' in metadata)
            if drag.have_reference_geometry:
                v1._same(drag.reference_geometry_mm, [metadata['reference_geometry_mm'][key] for key in ('L', 't')], side + ' reference')
    finally:
        _release(native, result)
    assert asdict(config) == before
    return expected


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(v2._FLUIDS, repeat=2)))
def test_continuous_pair_capacity_resolve_and_full(native, monkeypatch, topology, pair):
    config = _configuration(topology, pair)
    capacities, state = v3._reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    status, result, failure, error, live, _ = _call(native, 'prepare_inlet_mass_capacities', config)
    assert status == 0, error
    try:
        for i, side in enumerate('AB'):
            v3._scalar(result.flow.capacities[i], capacities[side])
        v3._flow_evidence(result.flow.evidence, state)
        assert live == state['events']['preliminary']
        _snapshot(result.controls, config)
    finally:
        _release(native, result)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., -88.
    expected, state = v3._reference(monkeypatch, 'resolve_inlet_flow', config, targets)
    status, result, failure, error, live, _ = _call(native, 'resolve_inlet_flow', config, targets)
    assert status == 0, error
    try:
        v3._resolved(result.flow, expected);v3._flow_evidence(result.flow.evidence, state)
        assert live == state['events']['preliminary']
    finally:
        _release(native, result)
    _full(native, monkeypatch, config, targets)


@pytest.mark.parametrize('layout', [(1, 1, True, 3), (1, 4, False, 2), (4, 1, True, 3),
    (2, 2, False, 3), (3, 3, True, 2), (4, 4, False, 1), (5, 4, True, 3), (4, 5, False, 3)])
def test_continuous_control_layouts_and_orders(native, monkeypatch, layout):
    nx, ny, mirror, order = layout
    _full(native, monkeypatch, _configuration(nx=nx, ny=ny, mirror=mirror, order=order))


@pytest.mark.parametrize('directions', list(product(range(4), repeat=2)))
@pytest.mark.parametrize('refine', [False, True])
def test_continuous_inlet_slices_and_local_drag(native, monkeypatch, directions, refine):
    config = _configuration(nx=3, ny=4, mirror=False, order=2)
    config.solver.Nx = config.solver.Ny = 64 if refine else 12
    config.flags.port_wall_refine = refine
    for i, side in enumerate('AB'):
        direction = directions[i]
        cross = config.geometry.H_dom_m if direction < 2 else config.geometry.L_dom_m
        setattr(config, 'bc_' + side, PartialBCConfig(dir=direction, in_ctr=cross*.4, in_w=cross*.4,
            out_ctr=cross*.6, out_w=cross*.4, uniform_inlet_2d=side == 'B'))
    capacities, _ = v3._reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    for side in 'AB':
        fluid = getattr(config, 'fluid_' + side)
        fluid.mass_flow_kg_s = float(capacities[side] * fluid.u_mps)
        fluid.u_mps = -99.
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('topology,pair', [('Gyroid', ('air', 'water')),
    ('Diamond', ('co2', 'co2')), ('Gyroid', ('co2', 'co2'))])
@pytest.mark.parametrize('mass', [False, True])
def test_continuous_existing_experimental_scope(native, monkeypatch, topology, pair, mass):
    config = _configuration(topology, pair, 'experimental')
    targets = None
    if mass:
        capacities, _ = v3._reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
        targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _full(native, monkeypatch, config, targets)


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_continuous_typed_depth_targets(native, monkeypatch, dtype, array):
    config = _configuration()
    depth = dtype(1) if dtype is np.int16 else dtype(.042)
    config.geometry.Lz_m = np.asarray(depth) if array else depth
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value)
                    for value in ((1, 2) if dtype is np.int16 else (.003, .03)))
    expected, state = v3._reference(monkeypatch, 'resolve_inlet_flow', config, targets)
    status, result, failure, error, live, _ = _call(native, 'resolve_inlet_flow', config, targets)
    assert status == 0, error
    try:
        v3._resolved(result.flow, expected);v3._flow_evidence(result.flow.evidence, state)
        assert live == state['events']['preliminary']
        for i, side in enumerate('AB'):
            v3._scalar(result.flow.speeds[i], getattr(expected, 'fluid_' + side).u_mps)
    finally:
        _release(native, result)


@pytest.mark.parametrize('case', ['order', 'counts', 'L-bounds', 't-bounds', 'decision-length',
    'control-domain', 'control-nan', 'nan-before-bounds', 'bounds-nan', 'delta', 'experimental-pair', 'experimental-nominal',
    'experimental-domain', 'depth-before-controls', 'target-before-controls', 'water-before-grid'])
def test_continuous_first_error(native, monkeypatch, case):
    config, targets, operation = _configuration(), None, 'prepare_flow_case'
    spec = config.zones.config
    if case == 'order': spec['spline_order'] = 0
    elif case == 'counts': spec['n_ctrl_x'] = 0
    elif case == 'L-bounds': spec['L_bounds'] = [3., 9.]
    elif case == 't-bounds': spec['t_bounds'] = [.2, .7]
    elif case == 'decision-length': spec['x_decision'].pop()
    elif case == 'control-domain': spec['x_decision'][0] = 3.
    elif case == 'control-nan': spec['x_decision'][0] = float('nan')
    elif case == 'nan-before-bounds': spec['x_decision'][0], spec['L_bounds'] = float('nan'), [3., 9.]
    elif case == 'bounds-nan': spec['L_bounds'][0] = float('nan')
    elif case == 'delta': config.geometry.delta_levelset = .1
    elif case == 'experimental-pair': config.df_mode, config.fluid_A.type = 'experimental', 'water'
    elif case == 'experimental-nominal': config.df_mode, config.geometry.L_cell_mm = 'experimental', 6.
    elif case == 'experimental-domain':
        config = _configuration(mode='experimental');config.geometry.L_dom_m = .18
    elif case == 'depth-before-controls':
        config.geometry.Lz_m = None;spec['spline_order'] = 0;targets = (-1., -1.)
    elif case == 'target-before-controls':
        spec['spline_order'] = 0;targets = (float('nan'), .03)
    elif case == 'water-before-grid':
        config.fluid_B.T_in_K = 500.;config.solver.Nx = config.solver.Ny = 1
    with pytest.raises(Exception) as reference:
        v3._reference(monkeypatch, operation, config, targets)
    status, result, failure, error, live, _ = _call(native, operation, config, targets)
    assert status and not result.owner
    assert error == str(reference.value)
    _release(native, result)


def test_continuous_queries_keep_independent_boundaries(native, monkeypatch):
    config = _configuration()
    config.fluid_A.u_mps, config.fluid_B.u_mps, config.extrap.allow = -99., float('nan'), False
    expected, state = v3._reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    status, result, failure, error, live, _ = _call(native, 'prepare_inlet_mass_capacities', config)
    assert status == 0, error
    try:
        for i, side in enumerate('AB'): v3._scalar(result.flow.capacities[i], expected[side])
        v3._flow_evidence(result.flow.evidence, state)
    finally:
        _release(native, result)
    config.fluid_A.T_in_K = -1.
    expected, state = v3._reference(monkeypatch, 'resolve_inlet_flow', config)
    assert expected is config
    status, result, failure, error, live, source = _call(native, 'resolve_inlet_flow', config)
    assert status == 0, error
    try:
        assert not result.flow.have_capacities and not live
        _snapshot(result.controls, config)
        v3._flow_evidence(result.flow.evidence, state)
    finally:
        _release(native, result)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('pair', [('air', 'water'), ('co2', 'water')])
def test_continuous_material_override_and_nominal_scalar_kinds(native, monkeypatch, dtype, pair):
    config = _configuration(pair=pair)
    config.geometry.L_cell_mm = dtype(6.25)
    config.geometry.t_wall_mm = dtype(.45)
    config.geometry.k_s_W_mK = dtype(16.3)
    for side in 'AB':
        fluid = getattr(config, 'fluid_' + side)
        fluid.u_mps = dtype(fluid.u_mps)
    _full(native, monkeypatch, config, chi=.73)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_continuous_sco2_nu_provenance_and_gradient_notice(native, monkeypatch, topology):
    config = _configuration(topology, ('sco2', 'co2'))
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
        parameter_version='saved continuous version', source='retained source', applicability='retained scope')
    _full(native, monkeypatch, config)


def _visible_buffers(value, path='result'):
    """Enumerate public views without using the native owner's private layout."""
    counts = {'ranges': 'range_count', 'warnings': 'warning_count',
              'events': 'event_count', 'source': 'source_count', 'shape': 'rank',
              'notices': 'notice_count', 'calibration': 'calibration_count'}
    if isinstance(value, (v1._Array, v1._Text)):
        if value.size:
            yield path, ct.cast(value.data, ct.c_void_p).value, value.size * ct.sizeof(value.data._type_)
    elif isinstance(value, ct.Structure):
        for name, field in value._fields_:
            item, label = getattr(value, name), path + '.' + name
            if issubclass(field, ct._Pointer):
                if name == 'range_bounds_list':
                    size = getattr(value, 'values', value).range_count
                else:
                    assert name in counts, label
                    size = getattr(value, counts[name])
                if size:
                    yield label, ct.cast(item, ct.c_void_p).value, size * ct.sizeof(field._type_)
                    if issubclass(field._type_, ct.Structure):
                        for index in range(size):
                            yield from _visible_buffers(item[index], f'{label}[{index}]')
            elif isinstance(item, (ct.Structure, ct.Array)):
                yield from _visible_buffers(item, label)
    elif isinstance(value, ct.Array):
        for index, item in enumerate(value):
            yield from _visible_buffers(item, f'{path}[{index}]')


def _check_owned_aliases(call, result, destination):
    buffers = list(_visible_buffers(result))
    assert buffers
    before = [(label, address, ct.string_at(address, size)) for label, address, size in buffers]
    outer = bytes(result)
    for label, address, _ in buffers:
        failure = v2._Failure(2, ct.sizeof(v2._Failure))
        error = ct.create_string_buffer(b'unchanged', 4096)
        failure_before, error_before = bytes(failure), bytes(error)
        failure_pointer = ct.cast(address, ct.POINTER(v2._Failure)) if destination == 'failure' else ct.byref(failure)
        error_pointer = ct.cast(address, ct.POINTER(ct.c_char)) if destination == 'error' else error
        status = call(failure_pointer, error_pointer, 1 if destination == 'error' else len(error))
        assert status == 1, label
        assert bytes(result) == outer, label
        assert bytes(failure) == failure_before and bytes(error) == error_before, label
        for name, pointer, saved in before:
            assert ct.string_at(pointer, len(saved)) == saved, (label, name)
    return [label for label, _, _ in buffers]


_OWNED_OPERATIONS = ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case')


@pytest.mark.parametrize('version,operation,model', [
    (version, operation, 'air') for version in (3, 4) for operation in _OWNED_OPERATIONS
] + [(3, 'prepare_flow_case', 'co2'), (4, 'prepare_flow_case', 'experimental')])
@pytest.mark.parametrize('destination', ['error', 'failure'])
def test_flow_owned_views_reject_diagnostic_aliases(native, version, operation, model, destination):
    library = v3.native.__wrapped__() if version == 3 else native
    create, make_source, release = (v3._call, v3._input, v3._release) if version == 3 else (_call, _input, _release)
    config = v3._configuration('Gyroid', ('air', 'air')) if version == 3 else _configuration(pair=('air', 'air'))
    if model == 'co2':
        config = v3._configuration('Gyroid', ('co2', 'air'))
    elif model == 'experimental':
        config = _configuration(pair=('air', 'water'), mode='experimental')
    config.geometry.Lz_m = .042
    if operation == 'resolve_inlet_flow':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    status, result, _, error, _, _ = create(library, operation, config)
    assert status == 0, error
    source = make_source(config)
    source_before = bytes(source)
    function = getattr(library, 'tpmshx_' + operation + f'_2d_v{version}')
    try:
        labels = _check_owned_aliases(lambda failure, error, capacity: function(
            ct.byref(source), None, None, ct.byref(result), failure, error, capacity), result, destination)
        if version == 4:
            assert any('.controls.decision_mm' in label for label in labels)
        if operation == 'prepare_flow_case':
            assert any('.total_porosity' in label for label in labels)
        assert bytes(source) == source_before
    finally:
        release(library, result)


@pytest.mark.parametrize('operation', _OWNED_OPERATIONS)
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', ['source_abi', 'source_size', 'result_abi', 'result_size'])
def test_continuous_owned_alias_guard_precedes_header_errors(native, operation, destination, invalid):
    config = _configuration(pair=('air', 'air'))
    if operation == 'resolve_inlet_flow':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    status, result, _, error, _, _ = _call(native, operation, config)
    assert status == 0, error
    source = _input(config)
    target = source if invalid.startswith('source') else result
    setattr(target, 'abi_version' if invalid.endswith('abi') else 'struct_size', 0)
    function = getattr(native, 'tpmshx_' + operation + '_2d_v4')
    try:
        _check_owned_aliases(lambda failure, error, capacity: function(
            ct.byref(source), None, None, ct.byref(result), failure, error, capacity), result, destination)
    finally:
        _release(native, result)


@pytest.mark.parametrize('version', [3, 4])
@pytest.mark.parametrize('operation', _OWNED_OPERATIONS)
def test_flow_owned_output_keeps_safe_reuse_diagnostics(native, version, operation):
    library = v3.native.__wrapped__() if version == 3 else native
    create, make_source, release = (v3._call, v3._input, v3._release) if version == 3 else (_call, _input, _release)
    config = v3._configuration('Gyroid', ('air', 'air')) if version == 3 else _configuration(pair=('air', 'air'))
    if operation == 'resolve_inlet_flow':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    status, result, _, error, _, _ = create(library, operation, config)
    assert status == 0, error
    source = make_source(config)
    outer = bytes(result)
    buffers = [(address, ct.string_at(address, size)) for _, address, size in _visible_buffers(result)]
    failure, error = v2._Failure(2, ct.sizeof(v2._Failure)), ct.create_string_buffer(4096)
    events = []
    def event(_context, _pointer):
        events.append(True)
        return 0
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    try:
        status = getattr(library, 'tpmshx_' + operation + f'_2d_v{version}')(
            ct.byref(source), None, ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
        assert status == 1 and failure.kind == 1
        assert b'release the previous flow result' in error.value and not events
        assert bytes(result) == outer
        assert all(ct.string_at(address, len(saved)) == saved for address, saved in buffers)
    finally:
        release(library, result)
