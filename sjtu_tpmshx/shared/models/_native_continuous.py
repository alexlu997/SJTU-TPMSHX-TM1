"""Call continuous-field entries in the existing native geometry library."""
import ctypes as ct
from functools import lru_cache
import weakref

import numpy as np

from . import _native_geometry


_DoubleP = ct.POINTER(ct.c_double)
_SizeP = ct.POINTER(ct.c_size_t)
_AxesP = ct.POINTER(_DoubleP)
_Handle = ct.c_void_p
_HandleP = ct.POINTER(_Handle)
_Error = [ct.POINTER(ct.c_char), ct.c_size_t]
_SIGNATURES = {
    'xy_create': [_DoubleP, ct.c_size_t, _DoubleP, ct.c_size_t, _DoubleP,
                  ct.c_size_t, ct.c_int, ct.c_int, _HandleP],
    'xy_sample': [_Handle, _DoubleP, ct.c_size_t, _DoubleP, ct.c_size_t,
                  _DoubleP, ct.c_size_t, ct.c_double, ct.c_double, _DoubleP, ct.c_size_t],
    'tensor_sample': [ct.c_size_t, _SizeP, _AxesP, _DoubleP, ct.c_size_t, ct.c_int,
                      _SizeP, _AxesP, ct.c_double, ct.c_double, _DoubleP, ct.c_size_t],
}


class _Bindings:
    def __init__(self, path):
        self.geometry = _native_geometry._load_library(path)
        self.library = self.geometry.library
        self.path = path
        version = self._bind('abi_version', [], ct.c_uint32)
        abi = version()
        if abi != 1:
            raise ValueError(f'unsupported native field ABI {abi} in {path}; expected 1')
        self.release = self._bind('xy_release', [_Handle], None)
        for name, signature in _SIGNATURES.items():
            setattr(self, name, self._bind(name, [*signature, *_Error], ct.c_int))

    def _bind(self, name, arguments, result):
        symbol = f'tpmshx_field_{name}_v1'
        try:
            function = getattr(self.library, symbol)
        except AttributeError as failure:
            raise ValueError(f'prebuilt geometry library {self.path} lacks field symbol {symbol}') from failure
        function.argtypes, function.restype = arguments, result
        return function


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _current():
    return _bindings(_native_geometry._library().path)


def _call(function, *arguments):
    error = ct.create_string_buffer(2048)
    status = function(*arguments, error, len(error))
    if status:
        message = error.value.decode('utf-8', errors='replace') or f'native field failed with code {status}'
        exception = {1: ValueError, 2: MemoryError, 3: RuntimeError}.get(status, RuntimeError)
        raise exception(message)


def _array(values):
    return np.require(values, dtype=np.float64, requirements=['C', 'A', 'E'])


def _pointer(values):
    return values.ctypes.data_as(_DoubleP)


def _axes(values):
    arrays = tuple(_array(axis) for axis in values)
    if any(axis.ndim != 1 for axis in arrays):
        raise ValueError('native field axes must be one-dimensional')
    counts = (ct.c_size_t * len(arrays))(*(axis.size for axis in arrays))
    pointers = (_DoubleP * len(arrays))(*(_pointer(axis) for axis in arrays))
    return arrays, counts, pointers


def _release(binding, destroy, handle):
    destroy(handle)


class XYFit:
    """Keep one captured fit and its creating library alive until release."""
    def __init__(self, x, y, values, degree_x, degree_y):
        self.binding = _current()
        x, y, values = _array(x), _array(y), _array(values)
        self.handle = _Handle()
        _call(self.binding.xy_create, _pointer(x), x.size, _pointer(y), y.size,
              _pointer(values), values.size, degree_x, degree_y, ct.byref(self.handle))
        if not self.handle.value:
            raise RuntimeError('native XY field returned a null fit owner')
        self._finalizer = weakref.finalize(self, _release, self.binding,
                                          self.binding.release, self.handle)

    def sample(self, values, coordinates, bounds):
        arrays, _counts, _pointers = _axes(coordinates)
        if len(arrays) != 2:
            raise ValueError('XY fit requires two sampling axes')
        x, y = arrays
        values = _array(values)
        result = np.empty((x.size, y.size), dtype=np.float64, order='C')
        _call(self.binding.xy_sample, self.handle, _pointer(values), values.size,
              _pointer(x), x.size, _pointer(y), y.size, bounds[0], bounds[1],
              _pointer(result), result.size)
        return result


def tensor_sample(nodes, values, order, coordinates, bounds):
    axes, counts, axis_pointers = _axes(nodes)
    samples, sample_counts, sample_pointers = _axes(coordinates)
    if len(axes) not in (2, 3) or len(samples) != len(axes):
        raise ValueError('tensor sampling axes must match its two or three control axes')
    values = _array(values)
    result = np.empty(tuple(points.size for points in samples), dtype=np.float64, order='C')
    binding = _current()
    _call(binding.tensor_sample, len(axes), counts, axis_pointers, _pointer(values), values.size,
          order, sample_counts, sample_pointers, bounds[0], bounds[1], _pointer(result), result.size)
    return result
