"""Pack float64 inlet-flow and quick-design inputs for the preparation core."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from . import _native_grid
from .stage_libraries import preparation_library
from ._native_values import real_scalar


_D = ct.c_double
_DP = ct.POINTER(_D)
_Size = ct.c_size_t
_UInt = ct.c_uint32
_Error = [ct.POINTER(ct.c_char), _Size]


class _Values(ct.Structure):
    _fields_ = [('data', _DP), ('count', _Size)]


_SIGNATURES = {
    'inlet_capacity_2d': [_Values, _Values, _Values, _Values, _D, _D],
    'inlet_capacity_3d': [_Values, ct.POINTER(_Size), _Size, ct.c_int32,
                          _Values, _Values, _Values, _D],
    'inlet_speeds': [_DP, _DP, _Size],
    'quick_design_sections': [_D, _D, _D, _D, _UInt],
    'quick_design_flow': [_D, _D, _D, _UInt],
    'relative_pressure': [_D, _D],
    'design_temperature_target': [_D, _UInt, _D, _D, _D, _D],
    'design_cooling_proxy': [_D, _D, _D, _D],
    'design_volume': [_D, _D, _D],
}


class _Bindings:
    def __init__(self, path):
        self.owner = preparation_library.load(path)
        for name, arguments in _SIGNATURES.items():
            setattr(self, name, self.owner.bind(
                f'tpmshx_preparation_{name}_v1', [*arguments, _DP, _Size, *_Error]))
        self.closure_geometry_ratio = self.owner.bind('tpmshx_preparation_closure_geometry_ratio_v1',
            [_Values, _Values, _DP, _Size, *_Error])


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _current():
    return _bindings(preparation_library.path())


def _check_status(status, error):
    if status:
        text = error.value.decode('utf-8', errors='replace') or f'native preparation failed with code {status}'
        if text == 'float division by zero':
            raise ZeroDivisionError(text)
        exception = {1: ValueError, 2: MemoryError}.get(status, RuntimeError)
        raise exception(text)


def _scalar(value):
    return real_scalar(value, allow_nonfinite=True)


def _values(value, *, shape=None):
    array = np.asarray(value)
    if array.dtype.kind not in 'fiu':
        raise TypeError(f'inlet buffers require real numbers, got {array.dtype}')
    packed = np.ascontiguousarray(array if shape is None else np.broadcast_to(array, shape), dtype=np.float64).ravel()
    return packed, _Values(packed.ctypes.data_as(_DP), packed.size)


def _result(function, arguments, count):
    output, error = (_D * count)(), ct.create_string_buffer(2048)
    _check_status(function(*arguments, output, count, error, len(error)), error)
    return tuple(output)


def capacity_2d(epsilon, opening, geometric, widths, density, depth):
    shape = np.broadcast(np.asarray(epsilon), np.asarray(opening), np.asarray(geometric), np.asarray(widths)).shape
    packed = [_values(value, shape=shape) for value in (epsilon, opening, geometric, widths)]
    return _result(_current().inlet_capacity_2d,
                   [*(value for _array, value in packed), _scalar(density), _scalar(depth)], 1)[0]


def capacity_3d(epsilon, direction, widths1, widths2, opening, density):
    epsilon = np.asarray(epsilon)
    if epsilon.ndim != 3:
        raise ValueError('3D inlet epsilon needs three physical axes')
    face_shape = (np.size(widths1), np.size(widths2))
    packed = [_values(value) for value in (epsilon, widths1, widths2)]
    packed.append(_values(opening, shape=face_shape))
    shape = (_Size * 3)(*epsilon.shape)
    e, w1, w2, o = (value for _array, value in packed)
    return _result(_current().inlet_capacity_3d,
                   [e, shape, 3, direction, w1, w2, o, _scalar(density)], 1)[0]


def inlet_speeds(targets, capacities):
    targets, capacities = tuple(targets), tuple(capacities)
    if len(targets) != len(capacities):
        raise ValueError('inlet target and capacity counts differ')
    count = len(targets)
    packed_targets = (_D * count)(*map(_scalar, targets))
    packed_capacities = (_D * count)(*map(_scalar, capacities))
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
    return _native_grid.uniform(count, length)


def closure_geometry_ratio(diameter_m, cell_mm):
    shape = np.broadcast(np.asarray(diameter_m), np.asarray(cell_mm)).shape
    inputs = [_values(value, shape=shape) for value in (diameter_m, cell_mm)]
    output, error = np.empty(inputs[0][0].size), ct.create_string_buffer(2048)
    _check_status(_current().closure_geometry_ratio(inputs[0][1], inputs[1][1], output.ctypes.data_as(_DP),
                  output.size, error, len(error)), error)
    result = output.reshape(shape)
    return result if result.ndim else float(result)
