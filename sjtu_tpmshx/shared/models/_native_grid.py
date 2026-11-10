"""Adapt grid data for the native geometry library."""
import ctypes as ct
from functools import lru_cache
import operator

import numpy as np

from sjtu_tpmshx.shared.models import _native_geometry as _geometry

_DoubleP = ct.POINTER(ct.c_double)
_Size = ct.c_size_t
_Uint = ct.c_uint32
_SizeP = ct.POINTER(_Size)
_IntP = ct.POINTER(ct.c_int32)
_ByteP = ct.POINTER(ct.c_uint8)


class _Scalar(ct.Structure):
    _fields_ = [('value', ct.c_double), ('precision', _Uint), ('strong', _Uint)]


class _Port(ct.Structure):
    _fields_ = [('direction', ct.c_int32), ('active', _Uint),
                ('values', (_Scalar * 4) * 2), ('present', (_Uint * 4) * 2)]


class _WallSpec(ct.Structure):
    _fields_ = [('layers', _Size), ('minimum', _Size),
                ('first', ct.c_double), ('growth', ct.c_double)]


_ScalarP = ct.POINTER(_Scalar)
_PortP = ct.POINTER(_Port)
_SIGNATURES = {
    'uniform': [_Size, _Scalar, _DoubleP, _Size],
    'adaptive': [_ScalarP, _Scalar, _Scalar, _DoubleP, _Size],
    'aligned_filter': [_Scalar, _ScalarP, _Size, _ByteP, _Size],
    'aligned': [_Size, _ScalarP, _Size, _DoubleP, _Size],
    'wall': [_Scalar, _Size, _Size, _Scalar, _Scalar, _DoubleP, _Size],
    'port_edges': [_ScalarP, _Size, _PortP, _Size, _Size, _ScalarP, _Size, _SizeP],
    'breaks_2d': [_ScalarP, _PortP, _Size, _Size, _ScalarP, _Size, _SizeP],
    'wall_spec': [_Size, _Size, ct.POINTER(_WallSpec)],
    'port_wall_axis': [_Size, _Size, _Size, _ScalarP, _Size, _ScalarP, _Size, _DoubleP, _Size],
    'suggest': [_ScalarP, _Scalar, _Size, _SizeP, _SizeP, _Size],
    'axis_map': [ct.c_int32, _IntP, _Size],
    'rectangles': [_PortP, _Scalar, _ScalarP, _Size],
    'overlap': [_DoubleP, _Size, _Uint, _Scalar, _Scalar, _Uint, _DoubleP, _Size],
    'fractions': [_DoubleP, _Size, _Uint, _Scalar, _Scalar, _Uint, _DoubleP, _DoubleP, _Size],
    'partial': [_PortP, _DoubleP, _Size, _Uint, _DoubleP, _Size, _Uint, _Uint, _Size,
                _DoubleP, _DoubleP, _Size],
    'continuous_centres': [_Size, _Scalar, _DoubleP, _Size, _Uint, _DoubleP, _Size],
    'sigmoid_centres': [_Size, _Scalar, _DoubleP, _Size, _Uint, _Uint, _DoubleP, _Size,
                        ct.POINTER(_Uint)],
}


def _scalar(value):
    if isinstance(value, np.floating):
        precision = value.dtype.itemsize * 8
        if precision not in (16, 32, 64):
            raise TypeError('grid scalars support NumPy float16, float32 and float64')
        return _Scalar(float(value), precision, 1)
    if isinstance(value, np.integer):
        precision = value.dtype.itemsize * 8
        if precision not in (8, 16, 32, 64):
            raise TypeError('grid scalars support NumPy integers with 8, 16, 32 or 64 bits')
        return _Scalar(float(value), precision, 2)
    if isinstance(value, (float, int)):
        return _Scalar(float(value), 64, 0)
    raise TypeError('grid scalars require Python float/int or NumPy floating/integer values')


def _restore(value):
    if value.strong:
        return np.dtype(f'float{value.precision}').type(value.value)
    return value.value


def _scalars(values):
    values = tuple(values)
    return (_Scalar * len(values))(*(_scalar(value) for value in values))


def _count(value):
    result = operator.index(value)
    if result < 0 or result > _Size(-1).value:
        raise ValueError('grid count must be within size_t')
    return result


def _port(config):
    result = _Port()
    if config is None:
        return result
    result.active, result.direction = 1, operator.index(config.get('dir', 0))
    for row, end in enumerate(('in', 'out')):
        for column, key in enumerate((f'{end}_ctr', f'{end}_w', f'{end}_z_ctr', f'{end}_z_w')):
            value = config.get(key)
            if value is not None:
                result.present[row][column] = 1
                result.values[row][column] = _scalar(value)
    return result


def _ports(configs):
    configs = tuple(configs)
    return (_Port * len(configs))(*(_port(config) for config in configs))


def _widths(values):
    original = np.asarray(values)
    if original.ndim != 1:
        raise ValueError('grid widths must be one-dimensional')
    precision = original.dtype.itemsize * 8 if original.dtype.kind == 'f' else 64
    if precision not in (16, 32, 64):
        raise TypeError('grid widths support NumPy float16, float32 and float64')
    return np.ascontiguousarray(original, dtype=np.float64), precision


def _pointer(array):
    return array.ctypes.data_as(_DoubleP)


@lru_cache(maxsize=1)
def _functions(owner):
    return {name: owner._bind(f'grid_{name}', signature)
            for name, signature in _SIGNATURES.items()}


def _function(name):
    return _functions(_geometry._library())[name]


def uniform(count, length):
    count = _count(count)
    result = np.empty(count, dtype=np.float64)
    _geometry._call(_function('uniform'), count, _scalar(length), _pointer(result), result.size)
    return result


def adaptive(length, height, diameter, alpha):
    result = np.empty(2, dtype=np.float64)
    _geometry._call(_function('adaptive'), _scalars((length, height)), _scalar(diameter),
                    _scalar(alpha), _pointer(result), result.size)
    return tuple(int(value) for value in result)


def aligned_bounds(length, breakpoints):
    points = tuple(breakpoints)
    values = _scalars(points)
    keep = np.empty(len(points), dtype=np.uint8)
    _geometry._call(_function('aligned_filter'), _scalar(length), values, len(values),
                    keep.ctypes.data_as(_ByteP), keep.size)
    return sorted(set([0.] + [value for value, selected in zip(points, keep) if selected] + [length]))


def aligned(count, bounds):
    count = _count(count)
    values = _scalars(bounds)
    result = np.empty(count, dtype=np.float64)
    _geometry._call(_function('aligned'), count, values, len(values), _pointer(result), result.size)
    return result


def wall(length, bulk, layers, first, growth):
    bulk, layers = _count(bulk), _count(layers)
    result = np.empty(bulk + 2 * layers, dtype=np.float64)
    _geometry._call(_function('wall'), _scalar(length), bulk, layers, _scalar(first), _scalar(growth),
                    _pointer(result), result.size)
    return result


def _edges(name, lengths, ports, axis):
    lengths, ports = _scalars(lengths), _ports(ports)
    result = (_Scalar * (4 * len(ports)))()
    actual = _Size()
    arguments = [lengths, len(lengths)] if name == 'port_edges' else [lengths]
    _geometry._call(_function(name), *arguments, ports, len(ports), _count(axis),
                    result, len(result), ct.byref(actual))
    return [_restore(result[i]) for i in range(actual.value)]


def port_edges(lengths, ports, axis):
    return _edges('port_edges', lengths, ports, axis)


def breaks_2d(lengths, ports, axis):
    return _edges('breaks_2d', lengths, ports, axis)


def wall_spec(dimensions, knots):
    result = _WallSpec()
    _geometry._call(_function('wall_spec'), _count(dimensions), _count(knots), ct.byref(result))
    return result.layers, result.first, result.growth, result.minimum


def port_wall_axis(dimensions, axis, count, bounds, bulk_bounds):
    count = _count(count)
    outer, bulk = _scalars(bounds), _scalars(bulk_bounds)
    result = np.empty(count, dtype=np.float64)
    _geometry._call(_function('port_wall_axis'), _count(dimensions), _count(axis), count,
                    outer, len(outer), bulk, len(bulk), _pointer(result), result.size)
    return result


def suggest(lengths, diameter, budget, minimum):
    lengths = _scalars(lengths)
    floor = (_Size * 3)(*(_count(value) for value in minimum))
    result = (_Size * 3)()
    _geometry._call(_function('suggest'), lengths, _scalar(diameter), _count(budget), floor, result, 3)
    return tuple(result)


def axis_map(direction):
    result = (ct.c_int32 * 7)()
    _geometry._call(_function('axis_map'), operator.index(direction), result, 7)
    return tuple(result)


def rectangles(port, cross2_length):
    config, result = _port(port), (_Scalar * 8)()
    _geometry._call(_function('rectangles'), ct.byref(config), _scalar(cross2_length), result, 8)
    values = tuple(_restore(value) for value in result)
    return {'inlet_rect': values[:4], 'outlet_rect': values[4:]}


def overlap(widths, lower, upper, *, staggered=False):
    values, precision = _widths(widths)
    if not values.size:
        raise IndexError('index -1 is out of bounds for axis 0 with size 0')
    result = np.empty(values.size + bool(staggered), dtype=np.float64)
    _geometry._call(_function('overlap'), _pointer(values), values.size, precision,
                    _scalar(lower), _scalar(upper), bool(staggered), _pointer(result), result.size)
    if staggered:
        return result.astype(np.result_type(np.asarray(widths), lower, upper), copy=False)
    return result


def fractions(widths, lower, upper, *, uniform=False):
    values, precision = _widths(widths)
    if not values.size:
        raise IndexError('index -1 is out of bounds for axis 0 with size 0')
    raw, profile = np.empty_like(values), np.empty_like(values)
    _geometry._call(_function('fractions'), _pointer(values), values.size, precision,
                    _scalar(lower), _scalar(upper), bool(uniform), _pointer(raw), _pointer(profile), raw.size)
    return raw, profile


def partial_masks(port, cross1, cross2, n_cross2):
    config = _port(port)
    first, precision1 = _widths(cross1)
    second, precision2 = (np.empty(0, dtype=np.float64), 64) if cross2 is None else _widths(cross2)
    shape = (len(first), _count(n_cross2))
    inlet, outlet = np.empty(shape, dtype=np.float64), np.empty(shape, dtype=np.float64)
    _geometry._call(_function('partial'), ct.byref(config), _pointer(first), first.size, precision1,
                    _pointer(second), second.size, precision2, cross2 is not None, shape[1],
                    _pointer(inlet), _pointer(outlet), inlet.size)
    return inlet, outlet


def continuous_centres(count, length, widths=None):
    span = _scalar(length)
    if widths is None and isinstance(count, np.integer):
        dtype = np.result_type(length, count)
        precision = dtype.itemsize * 8 if dtype.kind == 'f' else 64
        span = _Scalar(float(length), precision, 1)
    count = _count(count)
    values = np.empty(0, dtype=np.float64) if widths is None else np.ascontiguousarray(widths, dtype=np.float64)
    result = np.empty(count, dtype=np.float64)
    _geometry._call(_function('continuous_centres'), count, span, _pointer(values),
                    values.size, widths is not None, _pointer(result), result.size)
    return result


def sigmoid_centres(count, length, widths=None):
    count = _count(count)
    values, precision = (np.empty(0, dtype=np.float64), 64) if widths is None else _widths(widths)
    result = np.empty(count if widths is None else values.size, dtype=np.float64)
    output_precision = _Uint()
    _geometry._call(_function('sigmoid_centres'), count, _scalar(length), _pointer(values),
                    values.size, widths is not None, precision, _pointer(result), result.size,
                    ct.byref(output_precision))
    return result.astype(np.dtype(f'float{output_precision.value}'), copy=False)
