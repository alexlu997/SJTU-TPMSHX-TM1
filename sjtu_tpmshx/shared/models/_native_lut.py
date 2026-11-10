"""Keep RGI table ownership and call the native linear LUT evaluator."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from . import _native_geometry
from ._native_continuous import _array, _call, _pointer


_DP = ct.POINTER(ct.c_double)
_ERROR = [ct.POINTER(ct.c_char), ct.c_size_t]


class _Bindings:
    def __init__(self, path):
        self.geometry = _native_geometry._load_library(path)
        self.library, self.path = self.geometry.library, path
        version = self._bind('abi_version', [], ct.c_uint32)
        abi = version()
        if abi != 2:
            raise ValueError(f'unsupported native field ABI {abi} in {path}; expected 2')
        self.validate = self._bind('lut_validate', [_DP, ct.c_size_t, _DP, ct.c_size_t, *_ERROR], ct.c_int)
        self.query = self._bind('lut_query', [_DP, ct.c_size_t, _DP, ct.c_size_t,
            _DP, _DP, ct.c_size_t, ct.c_uint32, ct.c_uint32, _DP, _DP, ct.c_size_t,
            _DP, _DP, ct.c_size_t, *_ERROR], ct.c_int)

    def _bind(self, name, signature, result):
        symbol = f'tpmshx_field_{name}_v1'
        try:
            function = getattr(self.library, symbol)
        except AttributeError as failure:
            raise ValueError(f'prebuilt geometry library {self.path} lacks field symbol {symbol}') from failure
        function.argtypes, function.restype = signature, result
        return function


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _normalized_axes(points):
    grid, descending = [], []
    for index, values in enumerate(points):
        axis = np.asarray(values, dtype=float)
        if not np.all(axis[1:] > axis[:-1]):
            if np.all(axis[1:] < axis[:-1]):
                descending.append(index)
                axis = np.flip(axis)
            else:
                raise ValueError(f'The points in dimension {index} must be strictly ascending or descending')
        grid.append(np.ascontiguousarray(axis))
    return tuple(grid), tuple(descending)


def _normalized_values(original, descending):
    values = np.asarray(original)
    if not np.issubdtype(values.dtype, np.inexact):
        values = values.astype(float)
    if descending:
        values = np.flip(original, axis=descending)
    return values


def _fast(values):
    return int(values.ndim == 2 and values.flags.writeable
               and values.dtype == np.dtype(np.float64) and values.dtype.byteorder == '=')


class LUT:
    """Retain original normalized array references and the creating library."""
    def __init__(self, x, y, epsilon, area):
        self.axes, descending = _normalized_axes((x, y))
        self.epsilon = _normalized_values(epsilon, descending)
        self.area = _normalized_values(area, descending)
        shape = tuple(axis.size for axis in self.axes)
        if self.epsilon.shape != shape or self.area.shape != shape:
            raise ValueError('LUT table shape must match both axes')
        self.binding = _bindings(_native_geometry._library().path)
        axis_x, axis_y = (_array(axis) for axis in self.axes)
        _call(self.binding.validate, _pointer(axis_x), axis_x.size, _pointer(axis_y), axis_y.size)

    def query(self, x, y):
        x, y = _array(x).ravel(), _array(y).ravel()
        if x.size != y.size:
            raise ValueError('LUT query inputs must have the same number of values')
        # Capture each current RGI path before packing its table as double.
        epsilon_fast, area_fast = _fast(self.epsilon), _fast(self.area)
        epsilon, area = _array(self.epsilon), _array(self.area)
        axis_x, axis_y = (_array(axis) for axis in self.axes)
        shape = (axis_x.size, axis_y.size)
        if epsilon.shape != shape or area.shape != shape:
            raise ValueError('LUT table shape no longer matches its captured axes')
        eps_result, area_result = np.empty(x.size), np.empty(x.size)
        _call(self.binding.query, _pointer(axis_x), axis_x.size, _pointer(axis_y), axis_y.size,
              _pointer(epsilon), _pointer(area), epsilon.size, epsilon_fast, area_fast,
              _pointer(x), _pointer(y), x.size, _pointer(eps_result), _pointer(area_result), x.size)
        return eps_result, area_result
