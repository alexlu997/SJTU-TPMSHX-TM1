"""Pack inlet-flow and quick-design inputs for the preparation core."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from . import _native_grid, _native_preparation


_Scalar = _native_grid._Scalar
_SP = ct.POINTER(_Scalar)
_Size = ct.c_size_t
_UInt = ct.c_uint32
_DP = ct.POINTER(ct.c_double)
_Error = [ct.POINTER(ct.c_char), _Size]


class _Values(ct.Structure):
    _fields_ = [('data', _DP), ('count', _Size), ('precision', _UInt), ('strong', _UInt)]


_SIGNATURES = {
    'inlet_capacity_2d': [_Values, _Values, _Values, _Values, _Scalar, _Scalar],
    'inlet_capacity_3d': [_Values, ct.POINTER(_Size), _Size, ct.c_int32,
                          _Values, _Values, _Values, _Scalar],
    'inlet_speeds': [_SP, _SP, _Size],
    'quick_design_sections': [_Scalar, _Scalar, _Scalar, _Scalar, _UInt],
    'quick_design_flow': [_Scalar, _Scalar, _Scalar, _UInt],
    'relative_pressure': [_Scalar, _Scalar],
    'design_temperature_target': [_Scalar, _UInt, _Scalar, _Scalar, _Scalar, _Scalar],
    'design_cooling_proxy': [_Scalar, _Scalar, _Scalar, _Scalar],
    'design_volume': [_Scalar, _Scalar, _Scalar],
}


class _Bindings:
    def __init__(self, path):
        self.owner = _native_preparation._load_library(path)
        for name, arguments in _SIGNATURES.items():
            setattr(self, name, self.owner.bind(
                f'tpmshx_preparation_{name}_v1', [*arguments, _SP, _Size, *_Error]))
        self.closure_geometry_ratio = self.owner.bind('tpmshx_preparation_closure_geometry_ratio_v1',
            [_Values, _Values, _DP, _Size, _SP, *_Error])


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _current():
    return _bindings(_native_preparation._library().path)


def _scalar(value):
    if isinstance(value, np.ndarray) and value.ndim == 0:
        value = value[()]
    return _native_grid._scalar(value)


def _restore(value):
    if value.strong == 2:
        return np.dtype(f'int{value.precision}').type(value.value)
    return _native_grid._restore(value)


def _values(value, *, shape=None, preserve_scalar=False):
    original, value = value, np.asarray(value)
    if preserve_scalar and np.isscalar(original):
        tag = _scalar(original)
        precision, strong = tag.precision, tag.strong
    elif value.dtype.kind == 'f' and value.dtype.itemsize in (2, 4, 8):
        precision, strong = value.dtype.itemsize * 8, 1
    elif value.dtype.kind in 'iub' and value.dtype.itemsize in (1, 2, 4, 8):
        precision, strong = value.dtype.itemsize * 8, 2
    else:
        raise TypeError('inlet buffers require real floating or integer values')
    packed = np.ascontiguousarray(value if shape is None else np.broadcast_to(value, shape), dtype=np.float64).ravel()
    return packed, _Values(packed.ctypes.data_as(_DP), packed.size, precision, strong)


def _check_status(status, error):
    if status:
        text = error.value.decode('utf-8', errors='replace') or f'native preparation failed with code {status}'
        if text == 'float division by zero':
            raise ZeroDivisionError(text)
        exception = {1: ValueError, 2: MemoryError}.get(status, RuntimeError)
        raise exception(text)


def _result(function, arguments, count):
    output, error = (_Scalar * count)(), ct.create_string_buffer(2048)
    _check_status(function(*arguments, output, count, error, len(error)), error)
    return tuple(_restore(value) for value in output)


def capacity_2d(epsilon, opening, geometric, widths, density, depth):
    shape = np.broadcast(np.asarray(epsilon), np.asarray(opening), np.asarray(geometric), np.asarray(widths)).shape
    packed = [_values(value, shape=shape, preserve_scalar=True) for value in (epsilon, opening, geometric, widths)]
    return _result(_current().inlet_capacity_2d,
                   [*(value for _array, value in packed), _scalar(density), _scalar(depth)], 1)[0]


def capacity_3d(epsilon, direction, widths1, widths2, opening, density):
    epsilon = np.asarray(epsilon)
    if epsilon.ndim != 3:
        raise ValueError('3D inlet epsilon needs three physical axes')
    face_shape = (np.size(widths1), np.size(widths2))
    packed = [_values(value) for value in (epsilon, widths1, widths2)]
    packed.append(_values(opening, shape=face_shape, preserve_scalar=True))
    shape = (_Size * 3)(*epsilon.shape)
    e, w1, w2, o = (value for _array, value in packed)
    return _result(_current().inlet_capacity_3d,
                   [e, shape, 3, direction, w1, w2, o, _scalar(density)], 1)[0]


def inlet_speeds(targets, capacities):
    targets, capacities = tuple(targets), tuple(capacities)
    if len(targets) != len(capacities):
        raise ValueError('inlet target and capacity counts differ')
    count = len(targets)
    packed_targets = (_Scalar * count)(*map(_scalar, targets))
    packed_capacities = (_Scalar * count)(*map(_scalar, capacities))
    return _result(_current().inlet_speeds, [packed_targets, packed_capacities, count], count)


def quick_design_sections(epsilon, width, length, height, cross):
    values = _result(_current().quick_design_sections,
                     [*map(_scalar, (epsilon, width, length, height)), int(cross)], 4)
    return values[0], length, values[2], width if cross else length


def quick_design_flow(mass_flow, area, density, air):
    values = _result(_current().quick_design_flow,
                     [*map(_scalar, (mass_flow, area, density)), int(air)], 2)
    return values[0], None if air else values[1]


def relative_pressure(pressure_drop, inlet_pressure):
    return _result(_current().relative_pressure, list(map(_scalar, (pressure_drop, inlet_pressure))), 1)[0]


def temperature_target(temperature, delta, duty, mass_flow, heat_capacity):
    values = (delta, 0., 0., 0.) if delta is not None else (0., duty, mass_flow, heat_capacity)
    return _result(_current().design_temperature_target,
                   [_scalar(temperature), int(delta is not None), *map(_scalar, values)], 1)[0]


def cooling_proxy(hot, cold, target, mass_flow):
    return _result(_current().design_cooling_proxy, list(map(_scalar, (hot, cold, target, mass_flow))), 2)[0]


def cooling_proxy_needs_target(hot, cold):
    return bool(_result(_current().design_cooling_proxy, list(map(_scalar, (hot, cold, 0., 1.))), 2)[1])


def volume(width, height, length):
    return _result(_current().design_volume, list(map(_scalar, (width, height, length))), 1)[0]


def uniform_widths(count, length):
    value = np.asarray(length)
    dtype = value.dtype if value.dtype.kind == 'f' else np.dtype('float64')
    scalar = value[()] if isinstance(length, np.ndarray) else length
    return _native_grid.uniform(count, scalar).astype(dtype, copy=False)


def closure_geometry_ratio(diameter_m, cell_mm):
    shape = np.broadcast(np.asarray(diameter_m), np.asarray(cell_mm)).shape
    inputs = [_values(value, shape=shape, preserve_scalar=True) for value in (diameter_m, cell_mm)]
    output, kind, error = np.empty(inputs[0][0].size), _Scalar(), ct.create_string_buffer(2048)
    _check_status(_current().closure_geometry_ratio(inputs[0][1], inputs[1][1], output.ctypes.data_as(_DP),
                  output.size, ct.byref(kind), error, len(error)), error)
    result = output.astype(f'float{kind.precision}', copy=False).reshape(shape)
    if result.ndim:
        return result
    return result[()] if kind.strong else float(result)
