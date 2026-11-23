"""Pack float64 sigmoid inputs for the field entries in the geometry library."""
import ctypes as ct
from functools import lru_cache
import warnings

import numpy as np

from . import _native_geometry
from ._native_continuous import _call, _pointer
from ._native_values import real_scalar


_D = ct.c_double
_DP = ct.POINTER(_D)
_UP = ct.POINTER(ct.c_uint32)
_ERROR = [ct.POINTER(ct.c_char), ct.c_size_t]
_SIGNATURES = {
    'sigmoid_values': [_DP, ct.c_size_t, _D, _D, _DP, ct.c_size_t, _UP, ct.c_size_t],
    'sigmoid_blend': [_DP, ct.c_size_t, _DP, ct.c_size_t, _DP, ct.c_size_t, ct.c_size_t, _D,
                      _DP, ct.c_size_t, _UP, ct.c_size_t],
    'sigmoid_field': [_DP, _DP, ct.c_size_t, _DP, ct.c_size_t, _DP, ct.c_size_t, _D,
                      _DP, ct.c_size_t, _D, _D, _DP, ct.c_size_t, _UP, ct.c_size_t],
    'clip': [_DP, ct.c_size_t, _D, _D, _DP, ct.c_size_t],
}


class _Bindings:
    def __init__(self, path):
        self.geometry = _native_geometry._load_library(path)
        self.library, self.path = self.geometry.library, path
        version = self._bind('abi_version', [], ct.c_uint32)
        abi = version()
        if abi != 3:
            raise ValueError(f'unsupported native field ABI {abi} in {path}; expected 3')
        for name, arguments in _SIGNATURES.items():
            setattr(self, name, self._bind(name, [*arguments, *_ERROR], ct.c_int))

    def _bind(self, name, arguments, result):
        version = 2 if name.startswith('sigmoid_') else 1
        symbol = f'tpmshx_field_{name}_v{version}'
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


def _scalar(value):
    return real_scalar(value, allow_nonfinite=True)


def _scalars(values):
    values = tuple(values)
    return (_D * len(values))(*(_scalar(value) for value in values))


def _array(value):
    values = np.asarray(value)
    if values.dtype.kind not in 'fiu':
        raise TypeError(f'sigmoid fields require real coordinates and layers, got {values.dtype}')
    if values.ndim == 0:
        return np.asarray(values, dtype=np.float64)
    return np.ascontiguousarray(values, dtype=np.float64)


def _exp_warnings(flags):
    mode = np.geterr()['over']
    for overflow in flags:
        if overflow and mode == 'warn':
            warnings.warn('overflow encountered in exp', RuntimeWarning, stacklevel=3)
        elif overflow and mode == 'raise':
            raise FloatingPointError('overflow encountered in exp')


def _output(result, shape):
    result = result.reshape(shape)
    return result[()] if result.ndim == 0 else result


def values(x, center, width):
    source = _array(x)
    result, flags = np.empty(source.size), (ct.c_uint32 * 1)()
    _call(_current().sigmoid_values, _pointer(source), source.size, _scalar(center), _scalar(width),
          _pointer(result), result.size, flags, len(flags))
    _exp_warnings(flags)
    return _output(result, source.shape)


def blend(x, boundaries, layers, width):
    boundaries, layers = tuple(boundaries), tuple(layers)
    if not layers or len(boundaries) != len(layers) - 1:
        raise ValueError('incorrect sigmoid layer count')
    if not boundaries and hasattr(layers[0], 'copy'):
        return _array(layers[0]).copy()
    arrays = [_array(value) if hasattr(value, 'copy') else np.broadcast_to(_scalar(value), np.shape(x))
              for value in layers]
    original_x = _array(x)
    inputs = np.broadcast_arrays(original_x, *arrays)
    source = np.ascontiguousarray(inputs[0])
    packed = np.stack([np.ascontiguousarray(value).ravel() for value in inputs[1:]])
    bounds = _scalars(boundaries)
    result = np.empty(source.size)
    flags = (ct.c_uint32 * len(boundaries))()
    _call(_current().sigmoid_blend, _pointer(source), source.size, bounds, len(bounds),
          _pointer(packed), packed.size, len(layers), _scalar(width), _pointer(result), result.size,
          flags, len(flags))
    _exp_warnings(flags)
    if not source.size and original_x.size:
        for boundary in boundaries:
            values(original_x, boundary, width)
    return _output(result, source.shape)


def field(x, y, inlet, outlet, uniform, boundaries, width_x, width_y):
    boundaries = tuple(boundaries)
    original_x, original_y = _array(x), _array(y)
    x, y = (value if value.ndim == 0 else np.ascontiguousarray(value)
            for value in np.broadcast_arrays(original_x, original_y))
    inlet = _scalars(inlet[row][column] for row in range(3) for column in range(3))
    outlet = _scalars(outlet[row][column] for row in range(3) for column in range(3))
    bounds = _scalars(boundaries)
    result, flags = np.empty(x.size), (ct.c_uint32 * 8)()
    _call(_current().sigmoid_field, _pointer(x), _pointer(y), x.size,
          inlet, len(inlet), outlet, len(outlet), _scalar(uniform), bounds, len(bounds),
          _scalar(width_x), _scalar(width_y), _pointer(result), result.size, flags, len(flags))
    _exp_warnings(flags)
    # The original exp inputs can be nonempty when the final broadcast is empty.
    if not x.size:
        if original_x.size:
            values(original_x, 1.0 / 3, width_x)
            values(original_x, 2.0 / 3, width_x)
        if original_y.size:
            for boundary in boundaries:
                values(original_y, boundary, width_y)
    return _output(result, x.shape)


def clip(values, lower, upper):
    source = _array(values)
    result = np.empty(source.size)
    _call(_current().clip, _pointer(source), source.size, _scalar(lower), _scalar(upper),
          _pointer(result), result.size)
    return _output(result, source.shape)
