"""Call independent result primitives with contiguous float64 arrays and int32 labels."""
import ctypes as ct
import os
import warnings

import numpy as np

from .stage_libraries import result_library
from ._native_values import _Diagnostics, _OPERATIONS


_Size, _UInt = ct.c_size_t, ct.c_uint32
_SizeP = ct.POINTER(_Size)
_FLOAT64 = np.dtype(np.float64)
_INT32 = np.dtype(np.int32)
_INT32_INFO = np.iinfo(np.int32)


class _Array(ct.Structure):
    _fields_ = [('data', ct.c_void_p), ('rank', _Size), ('shape', _SizeP)]


class _Labels(ct.Structure):
    _fields_ = [('data', ct.c_void_p), ('rank', _Size), ('shape', _SizeP)]


def _normalize_float64(value):
    if isinstance(value, (bool, np.bool_)):
        raise TypeError('native result buffers require real numeric data, got bool')
    if isinstance(value, (int, float)):
        return np.array(float(value), dtype=_FLOAT64)
    arr = np.asarray(value)
    if arr.dtype.kind not in ('i', 'u', 'f'):
        raise TypeError(f'native result buffers require real numeric data, got {arr.dtype}')
    if (type(arr) is np.ndarray and arr.dtype == _FLOAT64 and arr.dtype.isnative
            and arr.flags['C_CONTIGUOUS'] and arr.flags['ALIGNED']):
        return arr
    return np.array(arr, dtype=_FLOAT64, order='C', copy=True, subok=False)


def _normalize_int32(value):
    if isinstance(value, (bool, np.bool_)):
        raise TypeError('native result labels require integer data, got bool')
    if isinstance(value, int):
        if not _INT32_INFO.min <= value <= _INT32_INFO.max:
            raise ValueError('native result labels must fit in int32')
        return np.array(value, dtype=_INT32)
    arr = np.asarray(value)
    if arr.dtype.kind not in ('i', 'u'):
        raise TypeError(f'native result labels require integer data, got {arr.dtype}')
    if arr.size:
        if arr.dtype.kind == 'u':
            if int(arr.max()) > _INT32_INFO.max:
                raise ValueError('native result labels must fit in int32')
        elif int(arr.min()) < _INT32_INFO.min or int(arr.max()) > _INT32_INFO.max:
            raise ValueError('native result labels must fit in int32')
    if (type(arr) is np.ndarray and arr.dtype == _INT32 and arr.dtype.isnative
            and arr.flags['C_CONTIGUOUS'] and arr.flags['ALIGNED']):
        return arr
    return np.array(arr, dtype=_INT32, order='C', copy=True, subok=False)


class PackedArray:
    def __init__(self, value):
        self.owner = _normalize_float64(value)
        shape = self.owner.shape
        self.shape = (_Size * len(shape))(*shape)
        pointer = self.owner.ctypes.data if self.owner.size else None
        self.raw = _Array(pointer, len(shape), self.shape if shape else None)


class PackedLabels:
    def __init__(self, value):
        self.owner = _normalize_int32(value)
        shape = self.owner.shape
        self.shape = (_Size * len(shape))(*shape)
        pointer = self.owner.ctypes.data if self.owner.size else None
        self.raw = _Labels(pointer, len(shape), self.shape if shape else None)


def array(value):
    return PackedArray(value)


def labels(value):
    return PackedLabels(value)


def scalar(value):
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f'native result scalar requires a real number, got {type(value).__name__}')
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    if isinstance(value, np.ndarray):
        if value.ndim:
            raise TypeError('native result scalar requires a scalar or a zero-dimensional array')
        if value.dtype.kind not in ('i', 'u', 'f'):
            raise TypeError(f'native result scalar requires a real number, got {value.dtype}')
        return float(value[()])
    raise TypeError(f'native result scalar requires a real number, got {type(value).__name__}')


def notify(diagnostics, *, stacklevel=4):
    """Emit RuntimeWarning for divide, overflow, and invalid events; ignore underflow."""
    if diagnostics.reserved or diagnostics.event_count > 64:
        raise RuntimeError('native result returned invalid diagnostics')
    categories = ((1, 'divide by zero'), (2, 'overflow'), (8, 'invalid value'))
    for event in diagnostics.events[:diagnostics.event_count]:
        if event.reserved or event.flags > 15 or event.scalar > 1 or event.operation not in _OPERATIONS:
            raise RuntimeError('native result returned an invalid floating-point event')
        operation = _OPERATIONS[event.operation]
        if event.scalar and event.operation in (1, 2, 3, 4, 5, 8):
            operation = 'scalar ' + operation
        for flag, label in categories:
            if event.flags & flag:
                warnings.warn(f'{label} encountered in {operation}', RuntimeWarning, stacklevel=stacklevel)


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
