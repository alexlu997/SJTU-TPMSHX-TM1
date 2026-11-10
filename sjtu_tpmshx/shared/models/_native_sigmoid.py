"""Pack sigmoid inputs for the field entries in the geometry library."""
import ctypes as ct
from functools import lru_cache
import warnings

import numpy as np

from . import _native_geometry, _native_grid
from ._native_continuous import _array, _call, _pointer


_Scalar = _native_grid._Scalar
_SP = ct.POINTER(_Scalar)
_DP = ct.POINTER(ct.c_double)
_UP = ct.POINTER(ct.c_uint32)
_ERROR = [ct.POINTER(ct.c_char), ct.c_size_t]
_SIGNATURES = {
    'sigmoid_values': [_DP, ct.c_size_t, _Scalar, _Scalar, _Scalar,
                       _DP, ct.c_size_t, _UP, _UP, ct.c_size_t, ct.c_uint32],
    'sigmoid_blend': [_DP, ct.c_size_t, _Scalar, _SP, ct.c_size_t,
                      _DP, ct.c_size_t, _SP, ct.c_size_t, _Scalar,
                      _DP, ct.c_size_t, _UP, _UP, ct.c_size_t, ct.c_uint32],
    'sigmoid_field': [_DP, _DP, ct.c_size_t, _Scalar, _Scalar,
                      _SP, ct.c_size_t, _SP, ct.c_size_t, _Scalar,
                      _SP, ct.c_size_t, _Scalar, _Scalar,
                      _DP, ct.c_size_t, _UP, _UP, ct.c_size_t, ct.c_uint32],
    'clip': [_DP, ct.c_size_t, _Scalar, _Scalar, _Scalar, _DP, ct.c_size_t, _UP],
}


class _Bindings:
    def __init__(self, path):
        self.geometry = _native_geometry._load_library(path)
        self.library, self.path = self.geometry.library, path
        version = self._bind('abi_version', [], ct.c_uint32)
        abi = version()
        if abi != 2:
            raise ValueError(f'unsupported native field ABI {abi} in {path}; expected 2')
        dispatch = np.lib.introspect.opt_func_info(func_name='^exp$', signature='float32')
        current = dispatch['exp']['ff']['current']
        self.exp_mode = int('X86_V3' in current or 'X86_V4' in current or 'AVX512F' in current
                            or ('AVX2' in current and 'FMA3' in current))
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
    if isinstance(value, np.ndarray) and value.ndim == 0:
        value = value[()]
    return _native_grid._scalar(value)


def _kind(value):
    if np.isscalar(value):
        return _scalar(value)
    values = np.asarray(value)
    if values.dtype.kind != 'f' or values.dtype.itemsize not in (2, 4, 8):
        raise TypeError('sigmoid fields require float16, float32 or float64 coordinates and layers')
    return _Scalar(0.0, values.dtype.itemsize * 8, 1)


def _scalars(values):
    values = tuple(values)
    return (_Scalar * len(values))(*(_scalar(value) for value in values))


def _run(function, *arguments):
    try:
        _call(function, *arguments)
    except RuntimeError as failure:
        # Plain Python scalar division failed before the original NumPy call.
        if str(failure) == 'float division by zero':
            raise ZeroDivisionError(str(failure)) from failure
        raise


def _exp_warnings(flags):
    mode = np.geterr()['over']
    for overflow in flags:
        if overflow and mode == 'warn':
            warnings.warn('overflow encountered in exp', RuntimeWarning, stacklevel=3)
        elif overflow and mode == 'raise':
            raise FloatingPointError('overflow encountered in exp')


def _output(result, shape, precision):
    dtype = np.dtype(f'float{precision.value}')
    result = result.astype(dtype, copy=False).reshape(shape)
    return result[()] if result.ndim == 0 else result


def values(x, center, width):
    kind = _kind(x)
    source = _array(x)
    result, precision, flags = np.empty(source.size), ct.c_uint32(), (ct.c_uint32 * 1)()
    binding = _current()
    _run(binding.sigmoid_values, _pointer(source), source.size, kind, _scalar(center), _scalar(width),
         _pointer(result), result.size, ct.byref(precision), flags, len(flags), binding.exp_mode)
    _exp_warnings(flags)
    return _output(result, source.shape, precision)


def blend(x, boundaries, layers, width):
    boundaries, layers = tuple(boundaries), tuple(layers)
    if not layers or len(boundaries) != len(layers) - 1:
        raise ValueError('incorrect sigmoid layer count')
    if not boundaries and hasattr(layers[0], 'copy'):
        return layers[0].copy()
    x_kind = _kind(x)
    arrays, kinds = [], []
    for value in layers:
        if hasattr(value, 'copy'):
            arrays.append(np.asarray(value))
            kinds.append(_kind(value))
        else:
            arrays.append(np.broadcast_to(value, np.shape(x)))
            kinds.append(_Scalar(0.0, x_kind.precision, 1))
    original_x = np.asarray(x)
    inputs = np.broadcast_arrays(original_x, *arrays)
    source = _array(inputs[0])
    packed = np.stack([_array(value).ravel() for value in inputs[1:]])
    bounds = _scalars(boundaries)
    types = (_Scalar * len(kinds))(*kinds)
    result, precision = np.empty(source.size), ct.c_uint32()
    flags = (ct.c_uint32 * len(boundaries))()
    binding = _current()
    _run(binding.sigmoid_blend, _pointer(source), source.size, x_kind, bounds, len(bounds),
         _pointer(packed), packed.size, types, len(types), _scalar(width), _pointer(result), result.size,
         ct.byref(precision), flags, len(flags), binding.exp_mode)
    _exp_warnings(flags)
    if not source.size and original_x.size:
        for boundary in boundaries:
            values(original_x, boundary, width)
    return _output(result, source.shape, precision)


def field(x, y, inlet, outlet, uniform, boundaries, width_x, width_y):
    boundaries = tuple(boundaries)
    x_kind, y_kind = _kind(x), _kind(y)
    original_x, original_y = np.asarray(x), np.asarray(y)
    x, y = (_array(value) for value in np.broadcast_arrays(original_x, original_y))
    inlet = _scalars(inlet[row][column] for row in range(3) for column in range(3))
    outlet = _scalars(outlet[row][column] for row in range(3) for column in range(3))
    bounds = _scalars(boundaries)
    result, precision, flags = np.empty(x.size), ct.c_uint32(), (ct.c_uint32 * 8)()
    binding = _current()
    _run(binding.sigmoid_field, _pointer(x), _pointer(y), x.size, x_kind, y_kind,
         inlet, len(inlet), outlet, len(outlet), _scalar(uniform), bounds, len(bounds),
         _scalar(width_x), _scalar(width_y), _pointer(result), result.size,
         ct.byref(precision), flags, len(flags), binding.exp_mode)
    _exp_warnings(flags)
    # The original exp inputs can be nonempty when the final broadcast is empty.
    if not x.size:
        if original_x.size:
            values(original_x, 1.0 / 3, width_x)
            values(original_x, 2.0 / 3, width_x)
        if original_y.size:
            for boundary in boundaries:
                values(original_y, boundary, width_y)
    return _output(result, x.shape, precision)


def clip(values, lower, upper):
    kind = _kind(values)
    source = _array(values)
    result, precision = np.empty(source.size), ct.c_uint32()
    _run(_current().clip, _pointer(source), source.size, kind, _scalar(lower), _scalar(upper),
         _pointer(result), result.size, ct.byref(precision))
    return _output(result, source.shape, precision)
