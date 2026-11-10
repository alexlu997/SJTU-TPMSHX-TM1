"""Call native zone assignment and the fixed two-axis Gaussian filter."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from . import _native_geometry as geometry
from ._native_grid import _Scalar, _scalar

_Size = ct.c_size_t
_DoubleP = ct.POINTER(ct.c_double)
_IntP = ct.POINTER(ct.c_int32)
_ScalarP = ct.POINTER(_Scalar)


@lru_cache(maxsize=1)
def _bindings(path):
    library = geometry._load_library(path)
    return (
        library,
        library._bind('zone_ids', [ct.c_uint32, _Size, _Size, ct.c_int, _Scalar,
                                  _ScalarP, _Size, _DoubleP, _Size, _DoubleP, _Size,
                                  _IntP, _Size]),
        library._bind('zone_gaussian', [_Size, _Size, _DoubleP, _Size, _DoubleP, _Size]),
    )


def _widths(values):
    return None if values is None else geometry._array(values)


def _pointer(values):
    return None if values is None else values.ctypes.data_as(_DoubleP)


def assign(kind, nx, ny, rows, *, axis=1, domain=1., dx=None, dy=None):
    nx, ny = geometry._resolution(nx), geometry._resolution(ny)
    if any(len(row) != 4 for row in rows):
        raise ValueError('zone bounds must have four values per row')
    packed = (_Scalar * (4 * len(rows)))(*(_scalar(value) for row in rows for value in row))
    dx, dy = _widths(dx), _widths(dy)
    output = np.empty((nx, ny), dtype=np.int32)
    _library, function, _ = _bindings(geometry._library_path())
    geometry._call(function, kind, nx, ny, axis, _scalar(domain), packed, len(rows),
                   _pointer(dx), 0 if dx is None else dx.size,
                   _pointer(dy), 0 if dy is None else dy.size,
                   output.ctypes.data_as(_IntP), output.size)
    return output


def gaussian(values):
    values = geometry._array(values)
    if values.ndim != 2:
        raise ValueError('zone Gaussian input must have two dimensions')
    output = np.empty_like(values)
    _library, _, function = _bindings(geometry._library_path())
    geometry._call(function, *values.shape, _pointer(values), values.size,
                   _pointer(output), output.size)
    return output
