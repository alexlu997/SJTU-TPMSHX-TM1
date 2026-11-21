"""Load the independent result image and adapt typed borrowed buffers."""
import ctypes as ct
from functools import lru_cache
import os

import numpy as np

from .stage_libraries import result_library

from ._native_values import floating_events


_Size, _UInt = ct.c_size_t, ct.c_uint32


class _Scalar(ct.Structure):
    _fields_ = [('dtype', _UInt), ('origin', _UInt), ('byte_order', _UInt), ('reserved', _UInt),
                ('data', ct.c_ubyte * 32)]


class _Array(ct.Structure):
    _fields_ = [('data', ct.c_void_p), ('bytes', _Size), ('offset', _Size),
                ('dtype', _UInt), ('origin', _UInt), ('byte_order', _UInt), ('reserved', _UInt),
                ('rank', _Size), ('shape', ct.POINTER(_Size)), ('strides', ct.POINTER(ct.c_ssize_t))]


class _Event(ct.Structure):
    _fields_ = [('flags', _UInt), ('operation', _UInt), ('scalar', _UInt), ('reserved', _UInt)]


class _Diagnostics(ct.Structure):
    _fields_ = [('python_cause', _UInt), ('event_count', _UInt), ('error_number', ct.c_int32),
                ('reserved', _UInt), ('events', _Event * 64)]


class _Platform(ct.Structure):
    _fields_ = [('long_double_size', _UInt), ('long_double_digits', _UInt),
                ('long_double_max_exponent', _UInt), ('reserved', _UInt)]


_KINDS = {('b', 1): 1, ('i', 1): 2, ('u', 1): 3, ('i', 2): 4, ('u', 2): 5,
          ('i', 4): 6, ('u', 4): 7, ('i', 8): 8, ('u', 8): 9,
          ('f', 2): 10, ('f', 4): 11, ('f', 8): 12, ('c', 8): 14, ('c', 16): 15}
_DTYPES = {value: np.dtype(kind + str(size)) for (kind, size), value in _KINDS.items()}
_DTYPES[13], _DTYPES[16] = np.dtype(np.longdouble), np.dtype(np.clongdouble)
_OPERATIONS = {1: 'add', 2: 'subtract', 3: 'multiply', 4: 'divide', 5: 'power', 6: 'log',
               7: 'exp', 8: 'cast', 9: 'log10', 10: 'sqrt', 11: 'reduce', 12: 'absolute',
               13: 'maximum', 14: 'minimum', 15: 'square'}


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


def _dtype_tag(dtype):
    dtype = np.dtype(dtype)
    key = dtype.kind, dtype.itemsize
    if key in _KINDS:
        return _KINDS[key]
    if dtype.kind == 'f' and dtype.itemsize == np.dtype(np.longdouble).itemsize:
        _extended_format(result_library.path())
        return 13
    if dtype.kind == 'c' and dtype.itemsize == np.dtype(np.clongdouble).itemsize:
        _extended_format(result_library.path())
        return 16
    raise TypeError(f'native result buffers require numeric data, got {dtype}')


def _origin(value):
    if isinstance(value, np.ndarray):
        return 2
    if isinstance(value, np.generic):
        return 1
    if type(value) is float:
        return 0
    if type(value) is int:
        return 3
    if type(value) is bool:
        return 4
    if type(value) is complex:
        return 5
    return 2


def _order(dtype):
    return {'<': 1, '>': 2}.get(dtype.byteorder, 0)


class PackedArray:
    def __init__(self, value):
        self.owner = np.asarray(value)
        tag, origin = _dtype_tag(self.owner.dtype), _origin(value)
        shape, strides = self.owner.shape, self.owner.strides
        self.shape = (_Size * len(shape))(*shape)
        self.strides = (ct.c_ssize_t * len(strides))(*strides)
        if self.owner.size:
            lower = sum(min(0, stride * (size - 1)) for size, stride in zip(shape, strides))
            upper = sum(max(0, stride * (size - 1)) for size, stride in zip(shape, strides))
            pointer, count, offset = self.owner.ctypes.data + lower, upper - lower + self.owner.itemsize, -lower
        else:
            pointer, count, offset = None, 0, 0
        self.raw = _Array(pointer, count, offset, tag, origin, _order(self.owner.dtype), 0,
                          self.owner.ndim, self.shape, self.strides)


def array(value):
    return PackedArray(value)


def scalar(value):
    owner = np.asarray(value)
    if owner.ndim:
        raise TypeError('native result scalar requires a scalar or a zero-dimensional array')
    tag = _dtype_tag(owner.dtype)
    raw = _Scalar(tag, _origin(value), _order(owner.dtype), 0)
    data = owner.tobytes()
    if len(data) > len(raw.data):
        raise RuntimeError('native result scalar payload is too small')
    ct.memmove(raw.data, data, len(data))
    return raw


def restore_scalar(value):
    if value.reserved or value.dtype not in _DTYPES or value.origin > 5 or value.byte_order > 2:
        raise RuntimeError('native result returned an invalid scalar description')
    dtype = _DTYPES[value.dtype]
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


def notify(diagnostics, *, stacklevel):
    """Apply host error policy at one completed native primitive boundary."""
    if diagnostics.reserved or diagnostics.event_count > 64:
        raise RuntimeError('native result returned invalid diagnostics')
    events = []
    for event in diagnostics.events[:diagnostics.event_count]:
        if event.reserved or event.flags > 15 or event.scalar > 1 or event.operation not in _OPERATIONS:
            raise RuntimeError('native result returned an invalid floating-point event')
        operation = _OPERATIONS[event.operation]
        if event.scalar and event.operation in (1, 2, 3, 4, 5, 8):
            operation = 'scalar ' + operation
        events.append((event.flags, operation))
    floating_events(events, stacklevel=stacklevel)
