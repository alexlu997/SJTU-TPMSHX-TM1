"""Protect the active 2D preparation entries at their C boundary."""
import ctypes as ct

import pytest

from sjtu_tpmshx.cpp_interface import _native_preparation_case as abi
from sjtu_tpmshx.cpp_interface import native_preparation, preparation_host
from sjtu_tpmshx.preprocess.two_d import preparation
from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
from tests.python import native_preparation_abi as support

# Each active entry, its source and result layouts, and their ABI versions.
_ENTRIES = [
    ('tpmshx_preparation_2d_uniform_capacities_v1', abi._UniformInput, abi._UniformFlow, 1, 1),
    ('tpmshx_preparation_2d_uniform_resolve_flow_v1', abi._UniformInput, abi._UniformFlow, 1, 1),
    ('tpmshx_preparation_2d_continuous_capacities_v1', abi._ContinuousInput, abi._ContinuousFlow, 1, 1),
    ('tpmshx_preparation_2d_continuous_resolve_flow_v1', abi._ContinuousInput, abi._ContinuousFlow, 1, 1),
    ('tpmshx_preparation_2d_zoned_capacities_v1', abi._ZonedInput, abi._ZonedFlow, 1, 1),
    ('tpmshx_preparation_2d_zoned_resolve_flow_v1', abi._ZonedInput, abi._ZonedFlow, 1, 1),
    ('tpmshx_preparation_2d_sigmoid_capacities_v1', abi._SigmoidInput, abi._SigmoidFlow, 1, 1),
    ('tpmshx_preparation_2d_sigmoid_resolve_flow_v1', abi._SigmoidInput, abi._SigmoidFlow, 1, 1),
    ('tpmshx_preparation_2d_uniform_prepare_case_v1', abi._UniformInput, abi._UniformCase, 1, 1),
    ('tpmshx_preparation_2d_zoned_prepare_case_v1', abi._ZonedInput, abi._ZonedCase, 1, 1),
    ('tpmshx_preparation_2d_sigmoid_prepare_case_v1', abi._SigmoidInput, abi._SigmoidCase, 1, 1),
    ('tpmshx_preparation_2d_continuous_prepare_case_v1', abi._ContinuousInput, abi._ContinuousCase, 1, 1),
    ('tpmshx_preparation_2d_stripe_prepare_case_v1', abi._ZonedInput, abi._StripeCase, 1, 1),
]


def _function(name):
    function = ct.CDLL(preparation_library.path())[name]
    function.argtypes = [ct.c_void_p] * 6 + [ct.c_size_t]
    function.restype = ct.c_int
    return function


def test_entries_cover_production_bindings():
    bindings = preparation_host._bindings(preparation_library.path())
    actual = sorted((operation.call.argtypes[0]._type_.__name__, operation.result_type.__name__)
                    for operation in bindings.operations.values())
    assert actual == sorted((source.__name__, result.__name__) for _, source, result, _, _ in _ENTRIES)


@pytest.mark.parametrize('signature,overlap', [
    pytest.param(signature, overlap, id=signature[0] + '-' + overlap)
    for signature in _ENTRIES
    for overlap in ('source', 'options', 'callbacks', 'failure')
])
def test_2d_top_level_aliases_preserve_all_buffers(signature, overlap):
    name, source_type, result_type, source_version, result_version = signature
    types = {'source': source_type, 'options': abi._Options, 'callbacks': abi._Callbacks,
             'failure': abi._Failure, 'result': result_type}
    values = {key: value() for key, value in types.items()}
    versions = {'source': source_version, 'result': result_version, 'options': 1, 'callbacks': 1, 'failure': 2}
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
    keys = ['source', 'options', 'callbacks', 'result', 'failure']
    assert _function(name)(*(pointers[key] for key in keys), error, len(error)) == 1
    assert bytes(storage) == storage_before and bytes(error) == error_before
    assert {key: bytes(value) for key, value in values.items()} == before
    assert not calls


def _configuration(source_type):
    if source_type is abi._UniformInput:
        return support._configuration_mass_flow(pair=('air', 'air'))
    if source_type is abi._ContinuousInput:
        return support._configuration_continuous(pair=('air', 'air'))
    return support._configuration_spatial('sigmoid' if source_type is abi._SigmoidInput else 'x')


@pytest.mark.parametrize('signature', _ENTRIES, ids=[entry[0] for entry in _ENTRIES])
@pytest.mark.parametrize('selection', ['version', 'size'])
def test_2d_source_header_rejects_invalid_metadata(signature, selection):
    name, source_type, result_type, _, version = signature
    operation = 'prepare_inlet_mass_capacities' if 'capacities' in name else 'prepare_flow_case'
    source, error = native_preparation.pack_input(_configuration(source_type), None,
        lambda fluid: preparation._inlet_speed(operation, None, fluid), preparation._spatial_rows)
    assert error is None
    assert type(source) is source_type
    if selection == 'version':
        source.abi_version = 0
    else:
        source.struct_size -= 1
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    result = result_type(version, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    watched = [source, options, result]
    before = [bytes(value) for value in watched]
    status = _function(name)(ct.cast(ct.byref(source), ct.c_void_p),
        ct.cast(ct.byref(options), ct.c_void_p), None, ct.cast(ct.byref(result), ct.c_void_p),
        ct.cast(ct.byref(failure), ct.c_void_p), error, len(error))
    assert status == 1
    assert error.value
    assert [bytes(value) for value in watched] == before
