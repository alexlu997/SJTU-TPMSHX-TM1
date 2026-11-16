"""Keep raw spatial flow preparation equal to the frozen public sequence."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
import os

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as v2
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as v3
from sjtu_tpmshx.development.tests import test_native_preparation_zones as v5
from sjtu_tpmshx.development.tests import test_native_preparation_sigmoid as v6
from sjtu_tpmshx.development.tests import test_native_preparation_grid_types as v7
from sjtu_tpmshx.development.tests.test_native_preparation_continuous import _host_events

_U, _S, _D, _struct = v1._U, v1._S, v1._D, v1._structure
_OPTIONS = [('physical_depth_kind', v2._Kind), ('target_kinds', v2._Kind * 2),
            ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)]
_ZonedInput = _struct('ZonedFlowInputV8', [('abi_version', _U), ('struct_size', _S),
    ('values', v5._Input), *_OPTIONS])
_SigmoidInput = _struct('SigmoidFlowInputV8', [('abi_version', _U), ('struct_size', _S),
    ('values', v6._Input), *_OPTIONS])
_ZonedFlow = _struct('ZonedFlowV8', [('abi_version', _U), ('struct_size', _S),
    ('flow', v3._Flow), ('input', v5._Input), ('owner', ct.c_void_p)])
_SigmoidFlow = _struct('SigmoidFlowV8', [('abi_version', _U), ('struct_size', _S),
    ('flow', v3._Flow), ('input', v6._Input), ('owner', ct.c_void_p)])
_ZonedCase = _struct('ZonedFlowCaseV8', [('abi_version', _U), ('struct_size', _S),
    ('prepared', v5._Result), ('flow', _ZonedFlow), ('owner', ct.c_void_p)])
_SigmoidCase = _struct('SigmoidFlowCaseV8', [('abi_version', _U), ('struct_size', _S),
    ('prepared', v6._Result), ('flow', _SigmoidFlow), ('owner', ct.c_void_p)])
_OPERATIONS = ('capacity', 'resolve', 'prepare')


def _name(mode, operation):
    prefix = 'sigmoid' if mode == 'sigmoid' else 'zoned'
    return {'capacity': f'prepare_{prefix}_inlet_mass_capacities',
            'resolve': f'resolve_{prefix}_inlet_flow',
            'prepare': f'prepare_{prefix}_flow_case'}[operation]


def _types(mode):
    return (_SigmoidInput, _SigmoidFlow, _SigmoidCase) if mode == 'sigmoid' else (_ZonedInput, _ZonedFlow, _ZonedCase)


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or v1._library_path())
    library.tpmshx_preparation_case_abi_version_v8.restype = _U
    assert library.tpmshx_preparation_case_abi_version_v8() == 8
    for mode in ('zones', 'sigmoid'):
        source, flow, prepared = _types(mode)
        for operation in _OPERATIONS:
            result = prepared if operation == 'prepare' else flow
            function = getattr(library, 'tpmshx_' + _name(mode, operation) + '_2d_v8')
            function.argtypes = [ct.POINTER(source), ct.POINTER(v7._GridKinds), ct.POINTER(v1._Options),
                ct.POINTER(v1._Callbacks), ct.POINTER(result), ct.POINTER(v2._Failure), ct.POINTER(ct.c_char), _S]
            function.restype = ct.c_int
        for suffix, value in [('flow', flow), ('flow_case', prepared)]:
            function = getattr(library, f'tpmshx_preparation_{"zoned" if mode == "zones" else mode}_{suffix}_2d_release_v8')
            function.argtypes, function.restype = [ct.POINTER(value)], None
    return library


@pytest.fixture(autouse=True)
def clear_reference_caches():
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear(); compute_geometry.cache_clear()
    yield
    compute.cache_clear(); compute_geometry.cache_clear()


def _configuration(mode, topology='Gyroid'):
    config = v6._configuration(topology) if mode == 'sigmoid' else v5._config(mode)
    config.geometry.tpms = topology
    config.zones.config.tpms_type = topology
    config.zones.grid['tpms_type'] = topology
    config.geometry.Lz_m = .042
    return config


def _input(mode, config, table, targets):
    source_type, _, _ = _types(mode)
    raw = v6._input(config, table) if mode == 'sigmoid' else v5._input(config)
    options = v3._input(config, targets)
    output = source_type(8, ct.sizeof(source_type), raw)
    for name, _ in _OPTIONS:
        setattr(output, name, getattr(options, name))
    output._raw = raw
    return output


def _borrowed(source, mode):
    raw = source._raw
    zones = raw._base if mode == 'sigmoid' else raw
    return [source, zones._regions, *zones._buffers, *zones._base._buffers,
            *([raw._decision, *raw._table.arrays] if mode == 'sigmoid' else [])]


def _call(native, mode, operation, config, *, table=None, targets=None, chi=None, stop_event=None,
          source=None, result=None):
    source = _input(mode, config, table, targets) if source is None else source
    _, flow_type, case_type = _types(mode)
    result_type = case_type if operation == 'prepare' else flow_type
    result = result_type(8, ct.sizeof(result_type)) if result is None else result
    failure, error = v2._Failure(2, ct.sizeof(v2._Failure)), ct.create_string_buffer(4096)
    options = v1._Options(1, ct.sizeof(v1._Options), chi is not None, config.extrap.allow, chi or 0.)
    grid, live = v7._kinds(config), []
    def event(_context, pointer):
        value = pointer.contents
        live.append((value.kind, v1._text(value.logger), v1._text(value.message), value.floating_event))
        return int(stop_event is not None and len(live) == stop_event)
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    borrowed = _borrowed(source, mode)
    before = [bytes(value) for value in borrowed]
    status = getattr(native, 'tpmshx_' + _name(mode, operation) + '_2d_v8')(
        ct.byref(source), ct.byref(grid), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert [bytes(value) for value in borrowed] == before
    return status, result, failure, error.value.decode(), live, source


def _release(native, mode, value):
    prefix = 'sigmoid' if mode == 'sigmoid' else 'zoned'
    suffix = 'flow_case' if isinstance(value, (_ZonedCase, _SigmoidCase)) else 'flow'
    getattr(native, f'tpmshx_preparation_{prefix}_{suffix}_2d_release_v8')(ct.byref(value))
    assert not value.owner


def _reference(monkeypatch, mode, operation, config, table, targets=None, chi=None):
    from sjtu_tpmshx.shared.models import sigmoid_field
    name = {'capacity': 'prepare_inlet_mass_capacities', 'resolve': 'resolve_inlet_flow',
            'prepare': 'prepare_flow_case'}[operation]
    with monkeypatch.context() as patch:
        if mode == 'sigmoid':
            patch.setattr(sigmoid_field, 'get_geometry_lut', lambda *args, **kwargs: table.reference)
        return v3._reference(patch, name, config, targets, chi=chi)


def _check_prepared(actual, expected, state, config, mode):
    value = actual.values if mode == 'sigmoid' else actual
    assert not value.owner and not value.prepared.values.owner
    v2._check_values(value.prepared, expected, config)
    events = v3._events(value.prepared.values)
    v2._check_evidence(value.prepared, expected, state['records']['final'], state['events']['final'],
                       events, config, event_converter=_host_events)
    shape = expected.design_fields['L_field_m'].shape
    v1._same(np.ctypeslib.as_array(value.zone_id, shape=(value.cell_count,)).reshape(shape),
             expected.design_fields['zone_id'], 'zone assignment')
    for name, key in [('thermal_porosity', 'epsilon'), ('area_density_per_m', 'A_0'),
                      ('hydraulic_diameter_m', 'D_h')]:
        v1._same(v1._array(getattr(value, name)).reshape(shape),
                 expected.parameters['thermal_geometry']['fields'][key], key)
    v1._same(v1._array(value.design_area_density_per_m).reshape(shape), expected.design_fields['A_0_arr'], 'design area')
    for index, side in enumerate('AB'):
        for field, key in [('fluid_conductivity', f'K_ff{side}_arr'), ('volumetric_transfer', f'h_v{side}_arr')]:
            v1._same(v1._array(getattr(value, field)[index]).reshape(shape), expected.design_fields[key], key)
    if mode == 'sigmoid':
        assert not actual.owner
        v6._snapshot_controls(actual.controls, config)
    else:
        v5._check_region_values(value, config)


def _check(native, monkeypatch, mode, operation, config, table, targets=None, chi=None):
    before = deepcopy(asdict(config))
    expected, state = _reference(monkeypatch, mode, operation, config, table, targets, chi)
    status, result, failure, error, live, source = _call(native, mode, operation, config,
        table=table, targets=targets, chi=chi)
    assert status == 0, error
    try:
        assert result.owner and not failure.kind
        spatial = result.flow if operation == 'prepare' else result
        assert not spatial.flow.owner
        v3._flow_evidence(spatial.flow.evidence, state)
        if operation == 'capacity':
            for i, side in enumerate('AB'):
                v3._scalar(spatial.flow.capacities[i], expected[side])
            assert not spatial.flow.evidence.range_count
        else:
            v3._resolved(spatial.flow, state['resolved'])
        if operation == 'prepare':
            assert not spatial.owner
            with monkeypatch.context() as patch:
                if chi is not None:
                    patch.setenv('TPMSHX_CHI_S', str(chi))
                _check_prepared(result.prepared, expected, state, state['resolved'], mode)
        assert live == _host_events(state['events']['preliminary'] + state['events']['final'])
        saved = spatial.input.values if mode == 'sigmoid' else spatial.input
        assert saved.values.values.geometry_mode == 2
        # Returned raw regions and LUT remain valid after borrowed buffers change.
        regions = source._raw._base if mode == 'sigmoid' else source._raw
        names = [v1._text(row.name) for row in saved.regions[:saved.region_count]]
        lengths = [row.cell_length_mm for row in saved.regions[:saved.region_count]]
        for buffer in regions._buffers:
            ct.memset(buffer, ord('X'), len(buffer)-1)
        regions._regions[0].cell_length_mm = -1.
        assert [v1._text(row.name) for row in saved.regions[:saved.region_count]] == names
        assert [row.cell_length_mm for row in saved.regions[:saved.region_count]] == lengths
        if mode == 'sigmoid':
            controls = v1._array(spatial.input.controls.decision_mm).copy()
            tables = [v1._array(getattr(spatial.input.lut, name)).copy()
                      for name in ('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m')]
            source._raw._decision[:] = -1.
            for array in source._raw._table.arrays:
                array[:] = -1.
            v1._same(v1._array(spatial.input.controls.decision_mm), controls, 'owned controls')
            for name, values in zip(('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m'), tables):
                v1._same(v1._array(getattr(spatial.input.lut, name)), values, 'owned LUT ' + name)
    finally:
        _release(native, mode, result)
        _release(native, mode, result)
    assert asdict(config) == before
    return expected


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('direction', range(4))
def test_spatial_fixed_flow_complete_result(native, monkeypatch, mode, topology, direction):
    config = _configuration(mode, topology)
    config.flags.port_wall_refine = direction % 2 == 1
    config.solver.Nx = config.solver.Ny = 64 if config.flags.port_wall_refine else 12
    for side, axis in zip('AB', (direction, (direction+1) % 4)):
        cross = config.geometry.H_dom_m if axis < 2 else config.geometry.L_dom_m
        setattr(config, 'bc_' + side, replace(getattr(config, 'bc_' + side), dir=axis,
            in_ctr=.4*cross, in_w=.4*cross, out_ctr=.6*cross, out_w=.4*cross,
            uniform_inlet_2d=side == 'A'))
    table = v6._table(topology) if mode == 'sigmoid' else None
    capacities, _ = _reference(monkeypatch, mode, 'capacity', config, table)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    config.fluid_A.u_mps = -99.; config.fluid_B.u_mps = -88.
    config.fluid_A.mass_flow_kg_s = .9; config.fluid_B.mass_flow_kg_s = .8
    for operation in _OPERATIONS:
        table = v6._table(topology) if mode == 'sigmoid' else None
        _check(native, monkeypatch, mode, operation, config, table, targets if operation != 'capacity' else None)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('targets', ['A', 'B', 'AB', 'none'])
@pytest.mark.parametrize('kind', [float, np.float16, np.float32])
def test_spatial_configured_flow_and_scalar_kinds(native, monkeypatch, mode, targets, kind):
    config = _configuration(mode)
    config.geometry.Lz_m = kind(.042)
    config.geometry.L_dom_m = np.float32(config.geometry.L_dom_m)
    config.geometry.H_dom_m = np.float64(config.geometry.H_dom_m)
    table = v6._table() if mode == 'sigmoid' else None
    capacities, _ = _reference(monkeypatch, mode, 'capacity', config, table)
    for side in targets if targets != 'none' else '':
        fluid = getattr(config, 'fluid_' + side)
        fluid.mass_flow_kg_s = float(capacities[side] * fluid.u_mps)
        fluid.u_mps = -77.
    for operation in ('resolve', 'prepare'):
        table = v6._table() if mode == 'sigmoid' else None
        _check(native, monkeypatch, mode, operation, config, table)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('operation', _OPERATIONS)
def test_spatial_flow_failure_does_not_publish(native, mode, operation):
    config = _configuration(mode)
    table = v6._table() if mode == 'sigmoid' else None
    status, result, failure, error, live, _ = _call(native, mode, operation, config,
        table=table, targets=None if operation == 'capacity' else (.001, .002), stop_event=1)
    assert status and failure.kind and not result.owner and live and error
    _release(native, mode, result)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('defect', ['depth', 'target', 'wall', 'delta', 'velocity'])
def test_spatial_first_error_matches_reference(native, monkeypatch, mode, defect):
    config = _configuration(mode)
    table = v6._table() if mode == 'sigmoid' else None
    targets = (.001, .002)
    if defect == 'depth':
        config.geometry.Lz_m = 0.
    elif defect == 'target':
        targets = (-.1, .2)
    elif defect == 'wall':
        config.geometry.t_wall_mm = 3.
    elif defect == 'delta':
        config.geometry.delta_levelset = .01
    else:
        targets = None
        config.fluid_A.u_mps = 0.
    with pytest.raises((ValueError, RuntimeError)) as expected:
        _reference(monkeypatch, mode, 'prepare', config, table, targets)
    status, result, failure, error, _, _ = _call(native, mode, 'prepare', config, table=table, targets=targets)
    assert status and failure.kind and not result.owner
    assert error == str(expected.value)
    _release(native, mode, result)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('kind', [np.float16, np.float32, np.float64])
def test_spatial_explicit_target_kinds(native, monkeypatch, mode, kind):
    config = _configuration(mode)
    config.geometry.Lz_m = kind(.042)
    table = v6._table() if mode == 'sigmoid' else None
    capacities, _ = _reference(monkeypatch, mode, 'capacity', config, table)
    targets = tuple(kind(capacities[side] * getattr(config, 'fluid_' + side).u_mps) for side in 'AB')
    config.fluid_A.u_mps = config.fluid_B.u_mps = -1.
    for operation in ('resolve', 'prepare'):
        table = v6._table() if mode == 'sigmoid' else None
        _check(native, monkeypatch, mode, operation, config, table, targets)


_ALIAS_CASES = [(mode, field) for mode in ('grid', 'sigmoid')
    for field in ('source', 'regions', 'name', 'model-text', 'grid') +
    (('controls', 'cell_mm', 'wall_mm', 'porosity', 'area_density_per_m') if mode == 'sigmoid' else ())]


@pytest.mark.parametrize('mode,borrowed', _ALIAS_CASES)
@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('destination', ['result', 'failure', 'error'])
def test_spatial_flow_aliases_preserve_borrowed_storage(native, mode, borrowed, operation, destination):
    config = _configuration(mode)
    source = _input(mode, config, v6._table() if mode == 'sigmoid' else None, None)
    source_type, flow_type, case_type = _types(mode)
    result_type = case_type if operation == 'prepare' else flow_type
    result, failure = result_type(8, ct.sizeof(result_type)), v2._Failure(2, ct.sizeof(v2._Failure))
    error, grid = ct.create_string_buffer(b'unchanged', 4096), v7._kinds(config)
    target = {'result': result, 'failure': failure, 'error': error}[destination]
    source_pointer, grid_pointer = ct.byref(source), ct.byref(grid)
    zones = source.values.values if mode == 'sigmoid' else source.values
    if borrowed == 'source':
        storage = ct.create_string_buffer(max(ct.sizeof(source), ct.sizeof(target)))
        ct.memmove(storage, ct.byref(source), ct.sizeof(source))
        source_pointer = ct.cast(storage, ct.POINTER(source_type))
        if destination == 'result':
            result = result_type.from_buffer(storage)
        elif destination == 'failure':
            failure = v2._Failure.from_buffer(storage)
        else:
            error = storage
        watched = [storage, result]
    else:
        if borrowed == 'grid':
            grid_pointer = ct.cast(ct.byref(target), ct.POINTER(v7._GridKinds))
        elif borrowed == 'regions':
            zones.regions = ct.cast(ct.byref(target), ct.POINTER(v5._Region))
            zones.region_count = 1
        elif borrowed in ('name', 'model-text'):
            text = v1._Text(ct.cast(ct.byref(target), ct.POINTER(ct.c_char)), ct.sizeof(target))
            if borrowed == 'name':
                zones.regions[0].name = text
            else:
                zones.values.sco2_nu.source = text
        else:
            array = v1._Array(ct.cast(ct.byref(target), ct.POINTER(_D)), 1)
            if borrowed == 'controls':
                source.values.controls.decision_mm = array
            else:
                setattr(source.values.lut, borrowed, array)
        watched = [source, result, failure, error, grid]
    before = [bytes(value) for value in watched]
    status = getattr(native, 'tpmshx_' + _name(mode, operation) + '_2d_v8')(
        source_pointer, grid_pointer, None, None, ct.byref(result), ct.byref(failure), error, len(error))
    assert status == 1
    assert [bytes(value) for value in watched] == before


@pytest.mark.parametrize('mode', ['grid', 'sigmoid'])
@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_spatial_flow_versioned_boundaries(native, mode, operation, field):
    config = _configuration(mode)
    table = v6._table() if mode == 'sigmoid' else None
    source = _input(mode, config, table, None)
    _, flow_type, case_type = _types(mode)
    result_type = case_type if operation == 'prepare' else flow_type
    result = result_type(8, ct.sizeof(result_type))
    zones = source.values.values if mode == 'sigmoid' else source.values
    for target in (source, source.values, zones, zones.values, zones.values.values, result):
        previous = getattr(target, field)
        setattr(target, field, 0)
        before = bytes(result)
        status, _, _, error, _, _ = _call(native, mode, operation, config, table=table, source=source, result=result)
        assert status == 1 and error and bytes(result) == before
        setattr(target, field, previous)


@pytest.mark.parametrize('mode', ['grid', 'sigmoid'])
@pytest.mark.parametrize('operation', _OPERATIONS)
def test_spatial_flow_owned_output_requires_release(native, mode, operation):
    config = _configuration(mode)
    table = v6._table() if mode == 'sigmoid' else None
    status, result, _, error, _, _ = _call(native, mode, operation, config, table=table)
    assert status == 0, error
    before = bytes(result)
    try:
        status, _, failure, error, live, _ = _call(native, mode, operation, config, table=table, result=result)
        assert status == 1 and failure.kind == 1 and 'release' in error and not live
        assert bytes(result) == before
    finally:
        _release(native, mode, result)


def _visible_buffers(value, path='result'):
    """Enumerate public views without using the native owner's private layout."""
    counts = {'ranges': 'range_count', 'warnings': 'warning_count',
              'events': 'event_count', 'source': 'source_count', 'shape': 'rank',
              'notices': 'notice_count', 'regions': 'region_count',
              'zone_id': 'cell_count', 'calibration': 'calibration_count'}
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


@pytest.mark.parametrize('mode', ['x', 'sigmoid'])
@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', [None, 'source', 'result'])
def test_spatial_owned_views_reject_diagnostic_aliases(native, mode, operation, destination, invalid):
    config = _configuration(mode)
    config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    table = v6._table() if mode == 'sigmoid' else None
    status, result, _, error, _, _ = _call(native, mode, operation, config, table=table)
    assert status == 0, error
    source = _input(mode, config, table, None)
    grid = v7._kinds(config)
    try:
        if invalid is not None:
            (source if invalid == 'source' else result).abi_version = 0
        borrowed = _borrowed(source, mode)
        source_before = [bytes(item) for item in borrowed]
        def call(failure, error, capacity):
            return getattr(native, 'tpmshx_' + _name(mode, operation) + '_2d_v8')(
                ct.byref(source), ct.byref(grid), None, None, ct.byref(result), failure, error, capacity)
        labels = _check_owned_aliases(call, result, destination)
        assert any('.input.' in label and '.regions' in label for label in labels)
        assert any('.evidence.events' in label for label in labels)
        if operation == 'prepare':
            assert any('.prepared.' in label and '.total_porosity' in label for label in labels)
            assert any('.ranges' in label for label in labels)
        if mode == 'sigmoid':
            assert any('.lut.porosity' in label for label in labels)
            assert any('.controls.decision_mm' in label for label in labels)
        assert [bytes(item) for item in borrowed] == source_before
    finally:
        _release(native, mode, result)


@pytest.mark.parametrize('version,operation,model', [(3, 'prepare_inlet_mass_capacities', 'air'),
    (3, 'prepare_flow_case', 'air'), (4, 'prepare_inlet_mass_capacities', 'air'),
    (4, 'prepare_flow_case', 'air'), (5, 'prepare', 'air'), (6, 'prepare', 'air'),
    (3, 'prepare_flow_case', 'co2'), (4, 'prepare_flow_case', 'experimental')])
@pytest.mark.parametrize('destination', ['error', 'failure'])
def test_existing_flow_owners_reject_diagnostic_aliases(version, operation, model, destination):
    from sjtu_tpmshx.development.tests import test_native_preparation_continuous as v4
    module = {3: v3, 4: v4, 5: v5, 6: v6}[version]
    library = module.native.__wrapped__()
    config = (v3._configuration('Gyroid', ('air', 'air')) if version == 3 else
              v4._configuration(pair=('air', 'air')) if version == 4 else _configuration('x' if version == 5 else 'sigmoid'))
    if model == 'co2':
        config = v3._configuration('Gyroid', ('co2', 'air'))
    elif model == 'experimental':
        config = v4._configuration(pair=('air', 'water'), mode='experimental')
    config.geometry.Lz_m = .042
    if version in (3, 4):
        status, result, _, error, _, _ = module._call(library, operation, config)
        source = module._input(config)
        function = getattr(library, 'tpmshx_' + operation + f'_2d_v{version}')
        release = lambda: module._release(library, result)
    elif version == 5:
        status, result, _, error, _, _ = module._call(library, config)
        source = module._input(config)
        function = library.tpmshx_prepare_zoned_case_2d_v5
        release = lambda: library.tpmshx_preparation_zoned_case_2d_release_v5(ct.byref(result))
    else:
        table = v6._table()
        status, result, _, error, _, _ = module._call(library, config, table)
        source = module._input(config, table)
        function = library.tpmshx_prepare_sigmoid_case_2d_v6
        release = lambda: library.tpmshx_preparation_sigmoid_case_2d_release_v6(ct.byref(result))
    assert status == 0, error
    try:
        _check_owned_aliases(lambda failure, error, capacity: function(ct.byref(source), None, None,
            ct.byref(result), failure, error, capacity), result, destination)
    finally:
        release()


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_spatial_no_target_resolve_preserves_invalid_unconsumed_input(native, mode):
    config = _configuration(mode)
    config.geometry.Lz_m = None
    config.geometry.L_cell_mm = -1.
    config.fluid_A.u_mps = float('nan')
    config.zones.grid['cells'][0]['x1'] = -1.
    if mode == 'sigmoid':
        config.zones.pareto_x_decision = []
    source = _input(mode, config, v6._table() if mode == 'sigmoid' else None, None)
    status, result, failure, error, live, _ = _call(native, mode, 'resolve', config, source=source)
    assert status == 0, error
    try:
        assert not result.flow.have_capacities and not failure.kind and not live
        assert np.isnan(result.flow.input.values.sides[0].velocity_m_s)
        assert result.flow.input.values.cell_length_mm == -1.
        assert not result.flow.input.values.have_physical_depth
    finally:
        _release(native, mode, result)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('kind', [np.float16, np.float32, np.float64])
def test_spatial_geometry_cache_keeps_first_scalar_kind(native, monkeypatch, mode, kind):
    config = _configuration(mode)
    config.geometry.L_cell_mm = kind(7.)
    config.geometry.t_wall_mm = kind(.4)
    config.geometry.k_s_W_mK = kind(15.)
    config.zones.config.k_s = kind(15.)
    config.zones.grid['k_s'] = kind(15.)
    if mode == 'grid':
        for index, cell in enumerate(config.zones.grid['cells']):
            cell['L'], cell['t'] = (kind(7.), kind(.4)) if index % 2 else (7., float(kind(.4)))
    elif mode != 'sigmoid':
        for index, zone in enumerate(config.zones.config.zones):
            zone.L_mm, zone.t_mm = (kind(7.), kind(.4)) if index % 2 else (7., float(kind(.4)))
    table = v6._table() if mode == 'sigmoid' else None
    capacities, _ = _reference(monkeypatch, mode, 'capacity', config, table)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _check(native, monkeypatch, mode, 'prepare', config, table, targets, chi=.75)


@pytest.mark.parametrize('allow', [False, True])
def test_sigmoid_fixed_flow_keeps_clipping_and_repeated_geometry_events(native, monkeypatch, allow):
    config = _configuration('sigmoid')
    config.extrap.allow = allow
    config.zones.pareto_x_decision[0::2] = [3.99, 8.01] * 9
    config.zones.pareto_x_decision[1::2] = [.2999, .6001] * 9
    table = v6._table()
    capacities, _ = _reference(monkeypatch, 'sigmoid', 'capacity', config, table)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _check(native, monkeypatch, 'sigmoid', 'prepare', config, table, targets)
