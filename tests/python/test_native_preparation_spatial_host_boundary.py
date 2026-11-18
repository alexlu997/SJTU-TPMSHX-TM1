"""Protect all v9 public owner views when a new request is rejected."""
import ctypes as ct
import os

import pytest

from tests.python import test_native_preparation_spatial_flow as old

_U, _S = old._U, old._S
_Model = old._struct('ModelV9', [('solid_conductivity_W_mK', old.v1._D), ('solid_conductivity_kind', old.v2._Kind),
    ('allow_geometry_extrapolation', _U), ('load_default_lut', _U)])


def _types(mode):
    source, flow, prepared = old._types(mode)
    def extend(value, full=False):
        return old._struct(value.__name__ + 'V9', [('abi_version', _U), ('struct_size', _S),
            ('values', value), ('model', _Model)] + ([('design_pore_porosity', old.v1._Array)] if full else []) +
            ([] if value is source else [('owner', ct.c_void_p)]))
    return extend(source), extend(flow), extend(prepared, True)


@pytest.mark.parametrize('mode', ['x', 'sigmoid'])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'prepare'])
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', [None, 'source', 'result'])
def test_all_v9_owned_views_reject_diagnostic_aliases(mode, operation, destination, invalid):
    config = old._configuration(mode)
    config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    source_type, flow_type, case_type = _types(mode)
    table = old.v6._table() if mode == 'sigmoid' else None
    base = old._input(mode, config, table, None)
    source = source_type(9, ct.sizeof(source_type), base, _Model(config.geometry.k_s_W_mK, old.v2._Kind(64, 0, 0), 1, 0))
    result_type = case_type if operation == 'prepare' else flow_type
    result = result_type(9, ct.sizeof(result_type))
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or old.v1._library_path())
    call = getattr(library, 'tpmshx_' + old._name(mode, operation) + '_2d_v9')
    call.argtypes = [ct.POINTER(source_type), ct.POINTER(old.v7._GridKinds), ct.POINTER(old.v1._Options),
        ct.POINTER(old.v1._Callbacks), ct.POINTER(result_type), ct.POINTER(old.v2._Failure),
        ct.POINTER(ct.c_char), _S]
    call.restype = ct.c_int
    prefix = 'sigmoid' if mode == 'sigmoid' else 'zoned'
    suffix = 'flow_case' if operation == 'prepare' else 'flow'
    release = getattr(library, f'tpmshx_preparation_{prefix}_{suffix}_2d_release_v9')
    release.argtypes, release.restype = [ct.POINTER(result_type)], None
    failure, error = old.v2._Failure(2, ct.sizeof(old.v2._Failure)), ct.create_string_buffer(4096)
    grid = old.v7._kinds(config)
    options = old.v1._Options(1, ct.sizeof(old.v1._Options), 0, 1, 0.)
    status = call(ct.byref(source), ct.byref(grid), ct.byref(options), None,
                  ct.byref(result), ct.byref(failure), error, len(error))
    assert status == 0, error.value.decode()
    try:
        if invalid is not None:
            (source if invalid == 'source' else result).abi_version = 0
        def rejected(failure, error, capacity):
            return call(ct.byref(source), ct.byref(grid), ct.byref(options), None,
                        ct.byref(result), failure, error, capacity)
        labels = old._check_owned_aliases(rejected, result, destination)
        if operation == 'prepare':
            assert 'result.design_pore_porosity' in labels
    finally:
        release(ct.byref(result))
        assert not result.owner


@pytest.mark.parametrize('hook', ['inlet', 'lut'])
@pytest.mark.parametrize('destination', ['result', 'failure', 'error'])
@pytest.mark.parametrize('callback_status,cache_hit', [
    pytest.param(0, 1, id='hit'), pytest.param(0, 0, id='miss'), pytest.param(1, 0, id='failure'),
])
def test_v9_cache_callbacks_reject_borrowed_diagnostic_aliases(hook, destination, callback_status, cache_hit):
    from sjtu_tpmshx.cpp_interface import _native_preparation_case as binding

    mode = 'sigmoid' if hook == 'lut' else 'x'
    config = old._configuration(mode)
    source_type, _, result_type = _types(mode)
    table = old.v6._table() if mode == 'sigmoid' else None
    base = old._input(mode, config, table, None)
    source = source_type(9, ct.sizeof(source_type), base,
        _Model(config.geometry.k_s_W_mK, old.v2._Kind(64, 0, 0), 1, int(hook == 'lut')))
    result = result_type(9, ct.sizeof(result_type))
    failure = old.v2._Failure(2, ct.sizeof(old.v2._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    target = {'result': result, 'failure': failure, 'error': error}[destination]
    # Keep the text container separate so a missing guard cannot read an arbitrary pointer.
    warnings = (binding._Text * 1)(binding._Text(ct.cast(ct.byref(target), ct.POINTER(ct.c_char)), 1))
    calls = []

    def cache(_context, action, *args):
        value, hit = args[-2:]
        calls.append(action)
        if hook == 'inlet':
            value.contents.evidence.warnings = warnings
            value.contents.evidence.warning_count = 1
        else:
            value.contents.cell_mm = binding._Array(ct.cast(ct.byref(target), ct.POINTER(old.v1._D)), 1)
        hit[0] = cache_hit
        return callback_status

    def cache_miss(_context, _action, _key, _value, hit):
        hit[0] = 0
        return 0

    callbacks = binding._KeyedCallbacks()
    callbacks.values.values.values.abi_version = 9
    callbacks.values.values.values.struct_size = ct.sizeof(callbacks)
    callbacks.geometry_cache_at = binding._GeometryAtFunction(cache_miss)
    callbacks.inlet_cache_at = binding._InletAtFunction(cache_miss)
    if hook == 'inlet':
        callbacks.inlet_cache_at = binding._InletAtFunction(cache)
    else:
        callbacks.sigmoid_lut_cache = binding._LUTCacheFunction(cache)
    grid = old.v7._kinds(config)
    options = old.v1._Options(1, ct.sizeof(old.v1._Options), 0, 1, 0.)
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or old.v1._library_path())
    call = getattr(library, 'tpmshx_' + old._name(mode, 'prepare') + '_2d_v9')
    call.argtypes = [ct.POINTER(source_type), ct.POINTER(old.v7._GridKinds), ct.POINTER(old.v1._Options),
        ct.POINTER(old.v1._Callbacks), ct.POINTER(result_type), ct.POINTER(old.v2._Failure),
        ct.POINTER(ct.c_char), _S]
    call.restype = ct.c_int
    watched = [source, result, failure, error, grid, callbacks, warnings, *old._borrowed(base, mode)]
    before = [bytes(value) for value in watched]
    status = call(ct.byref(source), ct.byref(grid), ct.byref(options),
        ct.cast(ct.byref(callbacks), ct.POINTER(old.v1._Callbacks)),
        ct.byref(result), ct.byref(failure), error, len(error))
    assert calls == [0], (status, failure.kind, error.value.decode(), calls)
    assert status == 1
    assert [bytes(value) for value in watched] == before
    assert not result.owner


@pytest.mark.parametrize('mode', ['x', 'sigmoid'])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'prepare'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_v9_nested_headers_preserve_result(mode, operation, field):
    config = old._configuration(mode)
    config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .003
    source_type, flow_type, case_type = _types(mode)
    table = old.v6._table() if mode == 'sigmoid' else None
    base = old._input(mode, config, table, None)
    source = source_type(9, ct.sizeof(source_type), base,
        _Model(config.geometry.k_s_W_mK, old.v2._Kind(64, 0, 0), 1, 0))
    result_type = case_type if operation == 'prepare' else flow_type
    result = result_type(9, ct.sizeof(result_type))
    failure, error = old.v2._Failure(2, ct.sizeof(old.v2._Failure)), ct.create_string_buffer(4096)
    grid = old.v7._kinds(config)
    options = old.v1._Options(1, ct.sizeof(old.v1._Options), 0, 1, 0.)
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or old.v1._library_path())
    call = getattr(library, 'tpmshx_' + old._name(mode, operation) + '_2d_v9')
    call.argtypes = [ct.POINTER(source_type), ct.POINTER(old.v7._GridKinds), ct.POINTER(old.v1._Options),
        ct.POINTER(old.v1._Callbacks), ct.POINTER(result_type), ct.POINTER(old.v2._Failure),
        ct.POINTER(ct.c_char), _S]
    call.restype = ct.c_int
    prefix = 'sigmoid' if mode == 'sigmoid' else 'zoned'
    suffix = 'flow_case' if operation == 'prepare' else 'flow'
    release = getattr(library, f'tpmshx_preparation_{prefix}_{suffix}_2d_release_v9')
    release.argtypes, release.restype = [ct.POINTER(result_type)], None
    zones = source.values.values.values if mode == 'sigmoid' else source.values.values
    for target in (source, source.values, source.values.values, zones, zones.values, zones.values.values, result):
        previous = getattr(target, field)
        setattr(target, field, 0)
        before = bytes(result)
        try:
            status = call(ct.byref(source), ct.byref(grid), ct.byref(options), None,
                          ct.byref(result), ct.byref(failure), error, len(error))
            assert status == 1 and error.value and bytes(result) == before
        finally:
            if result.owner:
                release(ct.byref(result))
            setattr(target, field, previous)


def _top_level_signatures():
    from sjtu_tpmshx.cpp_interface import _native_preparation_case as binding

    yield 'tpmshx_prepare_case_2d_v1', old.v1._Input, old.v1._Result, 1, False
    yield 'tpmshx_prepare_case_2d_v2', old.v2._Input, old.v2._Result, 2, False
    for scope in old.v7._SCOPES:
        operations = old.v7._OPERATIONS if scope in ('uniform', 'continuous') else ('prepare_flow_case',)
        for operation in operations:
            name, source, result, version = old.v7._signature(scope, operation)
            for api_version in (version, 7):
                entry = operation if scope == 'continuous' and api_version == 4 else name
                yield f'tpmshx_{entry}_2d_v{api_version}', source, result, version, api_version == 7
    for mode in ('x', 'sigmoid'):
        for version in (8, 9, 10):
            source, flow, prepared = old._types(mode) if version == 8 else _types(mode)
            for operation in old._OPERATIONS:
                result = prepared if operation == 'prepare' else flow
                if version == 10:
                    result = binding._OffsetSigmoidCase if mode == 'sigmoid' else binding._OffsetZonedCase
                yield f'tpmshx_{old._name(mode, operation)}_2d_v{version}', source, result, min(version, 9), True
    yield 'tpmshx_prepare_flow_case_2d_v10', old.v3._Input, binding._OffsetFlowCase, 3, True


@pytest.mark.parametrize('signature,overlap', [
    pytest.param(signature, overlap, id=signature[0] + '-' + overlap)
    for signature in _top_level_signatures()
    for overlap in ('source', 'options', 'callbacks', *(['grid'] if signature[4] else []),
                    *(['failure'] if not signature[0].endswith('_v1') else []))
])
def test_2d_top_level_aliases_preserve_all_buffers(signature, overlap):
    name, source_type, result_type, source_version, typed = signature
    types = {'source': source_type, 'options': old.v1._Options, 'callbacks': old.v1._Callbacks,
             'grid': old.v7._GridKinds, 'failure': old.v2._Failure, 'result': result_type}
    values = {key: value() for key, value in types.items()}
    versions = {'source': source_version, 'options': 1, 'callbacks': 1, 'grid': 7, 'failure': 2}
    for key, version in versions.items():
        values[key].abi_version, values[key].struct_size = version, ct.sizeof(types[key])
    calls = []

    def event(_context, _value):
        calls.append(True)
        return 0

    callback = old.v1._EventFunction(event)
    values['callbacks'].event = callback
    # Pad the aliased input so a regression can inspect the old owner slot safely.
    storage_type = type('AliasStorage', (ct.Union,), {'_fields_': [
        ('input', types[overlap]), ('output', result_type)]})
    storage = storage_type()
    storage.input = values[overlap]
    pointers = {key: ct.cast(ct.byref(value), ct.c_void_p) for key, value in values.items()}
    pointers[overlap] = pointers['result'] = ct.cast(ct.byref(storage), ct.c_void_p)
    error = ct.create_string_buffer(b'unchanged', 128)
    before = {key: bytes(value) for key, value in values.items()}
    storage_before, error_before = bytes(storage), bytes(error)
    keys = ['source', *(['grid'] if typed else []), 'options', 'callbacks', 'result',
            *(['failure'] if not name.endswith('_v1') else [])]
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or old.v1._library_path())
    function = getattr(library, name)
    function.argtypes = [ct.c_void_p] * (len(keys) + 1) + [_S]
    function.restype = ct.c_int
    assert function(*(pointers[key] for key in keys), error, len(error)) == 1
    assert bytes(storage) == storage_before and bytes(error) == error_before
    assert {key: bytes(value) for key, value in values.items()} == before
    assert not calls
