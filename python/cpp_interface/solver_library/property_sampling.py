"""Copy the native sampler records before their result owner is released."""
import ctypes as ct


class _Sample(ct.Structure):
    _fields_ = [('side', ct.c_uint32), ('outer_index', ct.c_int64)]
    _fields_ += [(name, ct.c_char_p) for name in
                ('stage', 'quantity', 'provider', 'temperature', 'pressure', 'operation')]


class _Sampling(ct.Structure):
    _fields_ = [('records', ct.POINTER(_Sample)), ('count', ct.c_size_t)]


def sampling_query(library, dimension, result_type):
    try:
        query = getattr(library, f'tpmshx_full_{dimension}d_get_property_sampling_v1')
    except AttributeError as exc:
        raise ValueError('native library lacks property sampling records; rebuild the library') from exc
    query.argtypes = [ct.POINTER(result_type), ct.POINTER(_Sampling)]
    query.restype = ct.c_int
    return query


def copy_sampling(query, result):
    view = _Sampling()
    if query(ct.byref(result), ct.byref(view)):
        raise RuntimeError('native property sampling query failed')
    from .._native_result_stage import sampling_records
    return sampling_records(view)
