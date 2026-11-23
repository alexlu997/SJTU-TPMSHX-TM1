"""Protect the active 2D preparation entries at their C boundary."""
import ctypes as ct

import pytest

from sjtu_tpmshx.cpp_interface import _native_preparation_case as abi
from sjtu_tpmshx.cpp_interface import native_preparation, preparation_host
from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
from tests.python import native_preparation_abi as support

# Each active entry, its source and result layouts, and their ABI versions.
_ENTRIES = [
    ('tpmshx_prepare_inlet_mass_capacities_2d_v7', abi._FlowInput, abi._Flow, 3, 3),
    ('tpmshx_resolve_inlet_flow_2d_v7', abi._FlowInput, abi._Flow, 3, 3),
    ('tpmshx_prepare_continuous_inlet_mass_capacities_2d_v7', abi._ContinuousInput, abi._ContinuousFlow, 4, 4),
    ('tpmshx_resolve_continuous_inlet_flow_2d_v7', abi._ContinuousInput, abi._ContinuousFlow, 4, 4),
    ('tpmshx_prepare_zoned_inlet_mass_capacities_2d_v10', abi._ZonedHostInput, abi._ZonedHostFlow, 9, 9),
    ('tpmshx_resolve_zoned_inlet_flow_2d_v10', abi._ZonedHostInput, abi._ZonedHostFlow, 9, 9),
    ('tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v10', abi._SigmoidHostInput, abi._SigmoidHostFlow, 9, 9),
    ('tpmshx_resolve_sigmoid_inlet_flow_2d_v10', abi._SigmoidHostInput, abi._SigmoidHostFlow, 9, 9),
    ('tpmshx_prepare_flow_case_2d_v10', abi._FlowInput, abi._OffsetFlowCase, 3, 10),
    ('tpmshx_prepare_zoned_flow_case_2d_v10', abi._ZonedHostInput, abi._OffsetZonedCase, 9, 10),
    ('tpmshx_prepare_sigmoid_flow_case_2d_v10', abi._SigmoidHostInput, abi._OffsetSigmoidCase, 9, 10),
    ('tpmshx_prepare_continuous_flow_case_2d_v11', abi._ContinuousInput, abi._ContinuousGeometryCase, 4, 11),
    ('tpmshx_prepare_stripe_flow_case_2d_v11', abi._ZonedHostInput, abi._StripeGeometryCase, 9, 11),
]


def _function(name):
    function = ct.CDLL(preparation_library.path())[name]
    function.argtypes = [ct.c_void_p] * 7 + [ct.c_size_t]
    function.restype = ct.c_int
    return function


def test_entries_cover_production_bindings():
    bindings = preparation_host._bindings(preparation_library.path())
    actual = sorted((key[1].__name__, operation.result_type.__name__) for key, operation in bindings.operations.items())
    assert actual == sorted((source.__name__, result.__name__) for _, source, result, _, _ in _ENTRIES)


@pytest.mark.parametrize('signature,overlap', [
    pytest.param(signature, overlap, id=signature[0] + '-' + overlap)
    for signature in _ENTRIES
    for overlap in ('source', 'options', 'callbacks', 'grid', 'failure')
])
def test_2d_top_level_aliases_preserve_all_buffers(signature, overlap):
    name, source_type, result_type, source_version, result_version = signature
    types = {'source': source_type, 'options': abi._Options, 'callbacks': abi._Callbacks,
             'grid': abi._GridKinds, 'failure': abi._Failure, 'result': result_type}
    values = {key: value() for key, value in types.items()}
    versions = {'source': source_version, 'result': result_version, 'options': 1, 'callbacks': 1, 'grid': 7, 'failure': 2}
    for key, version in versions.items():
        values[key].abi_version, values[key].struct_size = version, ct.sizeof(types[key])
    calls = []

    def event(_context, _value):
        calls.append(True)
        return 0

    callback = abi._EventFunction(event)
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
    keys = ['source', 'grid', 'options', 'callbacks', 'result', 'failure']
    assert _function(name)(*(pointers[key] for key in keys), error, len(error)) == 1
    assert bytes(storage) == storage_before and bytes(error) == error_before
    assert {key: bytes(value) for key, value in values.items()} == before
    assert not calls


def _configuration(source_type):
    if source_type is abi._FlowInput:
        return support._configuration_mass_flow(pair=('air', 'air'))
    if source_type is abi._ContinuousInput:
        return support._configuration_continuous(pair=('air', 'air'))
    return support._configuration_spatial('sigmoid' if source_type is abi._SigmoidHostInput else 'x')


@pytest.mark.parametrize('signature', _ENTRIES, ids=[entry[0] for entry in _ENTRIES])
@pytest.mark.parametrize('selection', ['missing', 'version', 'size', 'weak-precision', 'weak-layout',
    'float-precision', 'integer-precision', 'array-layout', 'unknown-strength'])
def test_typed_grid_descriptor_rejects_invalid_tags(signature, selection):
    name, source_type, result_type, _, version = signature
    operation = 'prepare_inlet_mass_capacities' if 'inlet_mass' in name else 'prepare_flow_case'
    source = native_preparation._input(_configuration(source_type), None, operation)
    assert type(source) is source_type
    kinds = source._grid_kinds
    if selection == 'version':
        kinds.abi_version = 0
    elif selection == 'size':
        kinds.struct_size -= 1
    elif selection != 'missing':
        tag = kinds.ports[1][3] if selection == 'array-layout' else kinds.lengths[0]
        values = {'weak-precision': (16, 0, 0), 'weak-layout': (64, 0, 1),
                  'float-precision': (8, 1, 1), 'integer-precision': (12, 2, 1),
                  'array-layout': (32, 1, 2), 'unknown-strength': (64, 3, 1)}[selection]
        tag.precision, tag.strong, tag.layout = values
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    result = result_type(version, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    watched = [source, kinds, options, result]
    before = [bytes(value) for value in watched]
    grid = None if selection == 'missing' else ct.byref(kinds)
    status = _function(name)(ct.cast(ct.byref(source), ct.c_void_p), ct.cast(grid, ct.c_void_p) if grid else None,
        ct.cast(ct.byref(options), ct.c_void_p), None, ct.cast(ct.byref(result), ct.c_void_p),
        ct.cast(ct.byref(failure), ct.c_void_p), error, len(error))
    assert status != 0
    if selection != 'missing':
        assert b'grid' in error.value or b'geometry scalar' in error.value, error.value
    assert [bytes(value) for value in watched] == before
