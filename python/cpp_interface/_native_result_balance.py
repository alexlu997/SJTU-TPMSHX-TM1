"""Pack selected zone data for the native result core."""
import ctypes as ct

import numpy as np

from . import _native_result as core


_D = ct.c_double
_DP = ct.POINTER(_D)
_AP = ct.POINTER(core._Array)


def _call(name, argtypes, *arguments):
    return core.call(f'tpmshx_result_{name}_v1', argtypes, *arguments)


def zone_mean(value, weights=None):
    owner, output = core.array(value), _D()
    weight = None if weights is None else core.array(weights)
    _call('zone_mean', [_AP, _AP, core._UInt, _DP], ct.byref(owner.raw),
          None if weight is None else ct.byref(weight.raw), int(weight is not None), ct.byref(output))
    return output.value


def zone_std(value, weights=None):
    owner, output = core.array(value), _D()
    weight = None if weights is None else core.array(weights)
    _call('zone_std', [_AP, _AP, core._UInt, _DP], ct.byref(owner.raw),
          None if weight is None else ct.byref(weight.raw), int(weight is not None), ct.byref(output))
    return output.value


def _zone_reduction(name, value):
    owner, output = core.array(value), _D()
    _call('zone_' + name, [_AP, _DP], ct.byref(owner.raw), ct.byref(output))
    return output.value


def zone_minimum(value):
    return _zone_reduction('minimum', value)


def zone_maximum(value):
    return _zone_reduction('maximum', value)


def zone_spread(value):
    return _zone_reduction('spread', value)


def zone_power_two(value):
    owner = core.array(value)
    output = np.empty(owner.owner.shape, dtype=np.float64)
    _call('zone_power_two', [_AP, _DP, core._Size], ct.byref(owner.raw),
          output.ctypes.data_as(_DP) if output.size else None, output.size)
    return output


def zone_speed_from_squared(u, v):
    first, second = core.array(u), core.array(v)
    output = np.empty(first.owner.shape, dtype=np.float64)
    _call('zone_speed_from_squared', [_AP, _AP, _DP, core._Size],
          ct.byref(first.raw), ct.byref(second.raw),
          output.ctypes.data_as(_DP) if output.size else None, output.size)
    return output


def zone_cv(deviation, mean):
    output = _D()
    _call('zone_cv', [_D, _D, _DP], core.scalar(deviation), core.scalar(mean), ct.byref(output))
    return output.value
