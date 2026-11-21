"""Call independent result primitives and check the native long-double format."""
import ctypes as ct
from functools import lru_cache, partial
import os

import numpy as np

from .stage_libraries import result_library

from ._native_values import (
    _Array as _Array, _Diagnostics, _Scalar as _Scalar, NATIVE_DTYPES, PackedArray,
    notify_diagnostics as notify, packed_scalar,
)


_Size, _UInt = ct.c_size_t, ct.c_uint32


class _Platform(ct.Structure):
    _fields_ = [('long_double_size', _UInt), ('long_double_digits', _UInt),
                ('long_double_max_exponent', _UInt), ('reserved', _UInt)]


@lru_cache(maxsize=1)
def _extended_format(path):
    owner = result_library.load(path)
    output, error = _Platform(), ct.create_string_buffer(4096)
    query = owner.bind('tpmshx_result_platform_info_v1',
                       [ct.POINTER(_Platform), ct.POINTER(ct.c_char), _Size])
    status = query(ct.byref(output), error, len(error))
    if status:
        raise RuntimeError(error.value.decode('utf-8', errors='replace') or 'cannot query result numeric format')
    expected = np.finfo(np.longdouble)
    if (output.long_double_size, output.long_double_digits, output.long_double_max_exponent) != (
            np.dtype(np.longdouble).itemsize, expected.nmant + 1, expected.maxexp):
        raise RuntimeError('native result long double format does not match NumPy')


def _check_extended():
    _extended_format(result_library.path())


array = partial(PackedArray, check_extended=_check_extended)
scalar = partial(packed_scalar, check_extended=_check_extended)


def restore_scalar(value):
    if value.reserved or value.dtype not in NATIVE_DTYPES or value.origin > 5 or value.byte_order > 2:
        raise RuntimeError('native result returned an invalid scalar description')
    dtype = NATIVE_DTYPES[value.dtype]
    if value.dtype in (13, 16):
        _extended_format(result_library.path())
    if value.byte_order:
        dtype = dtype.newbyteorder('<' if value.byte_order == 1 else '>')
    values = np.frombuffer(bytes(value.data[:dtype.itemsize]), dtype=dtype, count=1)
    if value.origin == 2:
        return values.copy().reshape(())
    result = values[0]
    if value.origin == 0:
        return float(result)
    if value.origin == 3:
        return int(result)
    if value.origin == 4:
        return bool(result)
    if value.origin == 5:
        return complex(result)
    return result


def integer_product_requires_python(values):
    """Select existing Python integer protocols before a bounded native call."""
    values = tuple(values)
    if any(type(value) is int and not -(1 << 63) <= value < (1 << 63) for value in values):
        return True
    bits = 0
    for value in values:
        if type(value) not in (int, bool):
            break
        bits += abs(value).bit_length()
        if bits > 63:
            return True
    return False


def call(name, argtypes, *arguments, stacklevel=4, library=None):
    types = [*argtypes, ct.POINTER(_Diagnostics), ct.POINTER(ct.c_char), _Size]
    if library is None:
        function = result_library.get().bind(name, types)
    else:
        function = library[name]
        function.argtypes, function.restype = types, ct.c_int
    diagnostics, error = _Diagnostics(), ct.create_string_buffer(4096)
    status = function(*arguments, ct.byref(diagnostics), error, len(error))
    notify(diagnostics, stacklevel=stacklevel)
    if not status:
        return
    text = error.value.decode('utf-8', errors='replace') or f'native result failed with status {status}'
    if status == 1:
        raise ValueError(text)
    if status == 2:
        raise MemoryError(text)
    if status == 4:
        exception = {1: ZeroDivisionError, 2: OverflowError, 3: ValueError, 4: TypeError, 5: IndexError}.get(
            diagnostics.python_cause)
        if exception is None:
            raise RuntimeError('native result returned an invalid numerical cause')
        if diagnostics.error_number and exception is OverflowError:
            raise OverflowError(diagnostics.error_number, os.strerror(diagnostics.error_number))
        raise exception(text)
    raise RuntimeError(text)
