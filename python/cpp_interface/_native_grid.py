"""Adapt grid data for the native geometry library."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from sjtu_tpmshx.cpp_interface import _native_geometry as _geometry

from ._native_values import GridPort as _Port, count as _index, grid_count as _count, real_scalar

_DoubleP = ct.POINTER(ct.c_double)
_Size = ct.c_size_t
_Uint = ct.c_uint32
_SizeP = ct.POINTER(_Size)
_IntP = ct.POINTER(ct.c_int32)
_ByteP = ct.POINTER(ct.c_uint8)


_port = _Port.from_mapping


class _WallSpec(ct.Structure):
    _fields_ = [('layers', _Size), ('minimum', _Size),
                ('first', ct.c_double), ('growth', ct.c_double)]


_D = ct.c_double
_PortP = ct.POINTER(_Port)
_SIGNATURES = {
    'uniform': [_Size, _D, _DoubleP, _Size],
    'adaptive': [_DoubleP, _D, _D, _DoubleP, _Size],
    'aligned_filter': [_D, _DoubleP, _Size, _ByteP, _Size],
    'aligned': [_Size, _DoubleP, _Size, _DoubleP, _Size],
    'wall': [_D, _Size, _Size, _D, _D, _DoubleP, _Size],
    'port_edges': [_DoubleP, _Size, _PortP, _Size, _Size, _DoubleP, _Size, _SizeP],
    'breaks_2d': [_DoubleP, _PortP, _Size, _Size, _DoubleP, _Size, _SizeP],
    'wall_spec': [_Size, _Size, ct.POINTER(_WallSpec)],
    'port_wall_axis': [_Size, _Size, _Size, _DoubleP, _Size, _DoubleP, _Size, _DoubleP, _Size],
    'suggest': [_DoubleP, _D, _Size, _SizeP, _SizeP, _Size],
    'axis_map': [ct.c_int32, _IntP, _Size],
    'rectangles': [_PortP, _D, _DoubleP, _Size],
    'overlap': [_DoubleP, _Size, _D, _D, _Uint, _DoubleP, _Size],
    'fractions': [_DoubleP, _Size, _D, _D, _Uint, _DoubleP, _DoubleP, _Size],
    'partial': [_PortP, _DoubleP, _Size, _DoubleP, _Size, _Uint, _Size,
                _DoubleP, _DoubleP, _Size],
    'continuous_centres': [_Size, _D, _DoubleP, _Size, _Uint, _DoubleP, _Size],
    'sigmoid_centres': [_Size, _D, _DoubleP, _Size, _Uint, _DoubleP, _Size],
}


def _scalar(value):
    return real_scalar(value, allow_nonfinite=True)


def _scalars(values):
    values = tuple(values)
    return (_D * len(values))(*(_scalar(value) for value in values))


def _widths(values):
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError('grid widths must be one-dimensional')
    if array.dtype.kind not in 'fiu':
        raise TypeError(f'grid widths must contain real numbers, got {array.dtype}')
    return np.ascontiguousarray(array, dtype=np.float64)


def _ports(configs):
    configs = tuple(configs)
    return (_Port * len(configs))(*(_port(config) for config in configs))


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
    points = tuple(_scalar(value) for value in breakpoints)
    length = _scalar(length)
    values = (_D * len(points))(*points)
    keep = np.empty(len(points), dtype=np.uint8)
    _geometry._call(_function('aligned_filter'), length, values, len(values),
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
    result = (_D * (4 * len(ports)))()
    actual = _Size()
    arguments = [lengths, len(lengths)] if name == 'port_edges' else [lengths]
    _geometry._call(_function(name), *arguments, ports, len(ports), _count(axis),
                    result, len(result), ct.byref(actual))
    return [result[i] for i in range(actual.value)]


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
    _geometry._call(_function('axis_map'), _index(direction, name='direction'), result, 7)
    return tuple(result)


def rectangles(port, cross2_length):
    config, result = _port(port), (_D * 8)()
    _geometry._call(_function('rectangles'), ct.byref(config), _scalar(cross2_length), result, 8)
    values = tuple(result)
    return {'inlet_rect': values[:4], 'outlet_rect': values[4:]}


def overlap(widths, lower, upper, *, staggered=False):
    values = _widths(widths)
    if not values.size:
        raise IndexError('index -1 is out of bounds for axis 0 with size 0')
    result = np.empty(values.size + bool(staggered), dtype=np.float64)
    _geometry._call(_function('overlap'), _pointer(values), values.size,
                    _scalar(lower), _scalar(upper), bool(staggered), _pointer(result), result.size)
    return result


def fractions(widths, lower, upper, *, uniform=False):
    values = _widths(widths)
    if not values.size:
        raise IndexError('index -1 is out of bounds for axis 0 with size 0')
    raw, profile = np.empty_like(values), np.empty_like(values)
    _geometry._call(_function('fractions'), _pointer(values), values.size,
                    _scalar(lower), _scalar(upper), bool(uniform), _pointer(raw), _pointer(profile), raw.size)
    return raw, profile


def partial_masks(port, cross1, cross2, n_cross2):
    config = _port(port)
    first = _widths(cross1)
    second = np.empty(0, dtype=np.float64) if cross2 is None else _widths(cross2)
    shape = (len(first), _count(n_cross2))
    inlet, outlet = np.empty(shape, dtype=np.float64), np.empty(shape, dtype=np.float64)
    _geometry._call(_function('partial'), ct.byref(config), _pointer(first), first.size,
                    _pointer(second), second.size, cross2 is not None, shape[1],
                    _pointer(inlet), _pointer(outlet), inlet.size)
    return inlet, outlet


def continuous_centres(count, length, widths=None):
    span = _scalar(length)
    count = _count(count)
    values = np.empty(0, dtype=np.float64) if widths is None else _widths(widths)
    result = np.empty(count, dtype=np.float64)
    _geometry._call(_function('continuous_centres'), count, span, _pointer(values),
                    values.size, widths is not None, _pointer(result), result.size)
    return result


def sigmoid_centres(count, length, widths=None):
    count = _count(count)
    values = np.empty(0, dtype=np.float64) if widths is None else _widths(widths)
    result = np.empty(count if widths is None else values.size, dtype=np.float64)
    _geometry._call(_function('sigmoid_centres'), count, _scalar(length), _pointer(values),
                    values.size, widths is not None, _pointer(result), result.size)
    return result
