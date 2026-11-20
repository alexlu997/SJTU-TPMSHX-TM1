"""Pack named metric requests for the independent result image."""
import ctypes as ct
from itertools import zip_longest

import numpy as np

from . import _native_result as native

_AP = ct.POINTER(native._Array)
_DP = ct.POINTER(ct.c_double)


def _call(name, types, *args):
    native.call('tpmshx_result_' + name + '_v1', types, *args)


def _packed(values):
    owners = [native.array(value) for value in values]
    return owners, (native._Array * len(owners))(*(item.raw for item in owners))


def _output(shape, dtype, template):
    return np.empty_like(np.asarray(template), dtype=dtype, shape=shape, order='K', subok=False)


def _shape(*values):
    shape = ()
    for value in values:
        result = []
        for left, right in zip_longest(reversed(shape), reversed(np.shape(value)), fillvalue=1):
            if left != right and left != 1 and right != 1:
                # The named native operation owns its original shape error.
                return ()
            result.append(right if left == 1 else left)
        shape = tuple(reversed(result))
    return shape


def _array_call(name, values, shape, dtype):
    inputs = [native.array(value) for value in values]
    template = max(values, key=lambda value: np.ndim(value))
    output = _output(shape, dtype, template)
    target = native.array(output)
    _call(name, [_AP] * (len(inputs) + 1), *(ct.byref(item.raw) for item in inputs), ct.byref(target.raw))
    return output[()] if not shape else output


def pressure_ratio(first, second):
    dtype = np.result_type(first, second)
    if dtype.kind in 'biu':
        dtype = np.dtype('float64')
    return _array_call('pressure_ratio', (first, second), _shape(first, second), dtype)


def pressure_face(first, second, ratio):
    shape = _shape(ratio, first, second)
    return _array_call('pressure_face', (first, second, ratio), shape, np.result_type(first, second, ratio))


def _double_arrays(name, values):
    sources = [native.array(value) for value in values]
    output = ct.c_double()
    _call(name, [_AP] * len(sources) + [_DP], *(ct.byref(item.raw) for item in sources), ct.byref(output))
    return output.value


def plane_duty(faces):
    owners, packed = _packed(faces)
    output = ct.c_double()
    _call('plane_duty', [_AP, native._Size, _DP], packed, len(owners), ct.byref(output))
    return output.value


def capture_area(dx, dy):
    return _double_arrays('capture_area', (dx, dy))


def capture_area_weights(dx, dy):
    return _array_call('capture_area_weights', (dx, dy),
                       (np.size(dx), np.size(dy)), np.result_type(dx, dy))
