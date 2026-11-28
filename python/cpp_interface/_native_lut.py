"""Keep RGI table ownership and call the native linear LUT evaluator."""
import ctypes as ct
from functools import lru_cache
from weakref import finalize

import numpy as np

from . import _native_preparation_case as abi
from ._native_diagnostics import native_error
from ._native_properties import cache_controls
from ._native_values import borrow_array, copy_array, geometry_topology, count
from .stage_libraries import preparation_library

_DP = ct.POINTER(ct.c_double)
_ERROR = [ct.POINTER(ct.c_char), ct.c_size_t]


image_path = preparation_library.path


class _Bindings:
    def __init__(self, path):
        self.owner = preparation_library.load(path)
        self.table = self.owner.bind('tpmshx_preparation_sigmoid_table_v1',
            [abi._U, abi._U, abi._S, ct.POINTER(abi._LUTView), ct.POINTER(abi._SigmoidLUT), *_ERROR])
        self.release = self.owner.bind('tpmshx_preparation_sigmoid_lut_release_v7', [ct.POINTER(abi._SigmoidLUT)], None)
        self.query = self.owner.bind('tpmshx_preparation_sigmoid_sample_v1',
            [ct.POINTER(abi._LUTView), abi._Array, abi._Array, _DP, _DP, abi._S, *_ERROR])


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _call(function, *args):
    error = ct.create_string_buffer(1024)
    status = function(*args, error, len(error))
    if status:
        raise native_error('preparation', function.__name__, status, error.value.decode('utf-8'))


def _sample(binding, table, x, y):
    buffers = []
    x, y = borrow_array(x, buffers), borrow_array(y, buffers)
    if x.size != y.size:
        raise ValueError('LUT query inputs must have the same number of values')
    epsilon, area = np.empty(x.size), np.empty(x.size)
    _call(binding.query, ct.byref(table), x, y, epsilon.ctypes.data_as(_DP), area.ctypes.data_as(_DP), x.size)
    return epsilon, area


class Table:
    """Pin one immutable value from the preparation image."""
    def __init__(self, binding, view):
        self.binding, self.view = binding, view
        self._release = finalize(self, binding.release, ct.byref(view))

    def close(self):
        self._release()

    def arrays(self):
        shape = self.view.cell_mm.size, self.view.wall_mm.size
        return copy_array(self.view.porosity, shape), copy_array(self.view.area_density_per_m, shape)

    def query(self, x, y):
        v = self.view
        table = abi._LUTView(v.cell_mm, v.wall_mm, v.porosity, v.area_density_per_m, v.porosity_fast, v.area_fast)
        return _sample(self.binding, table, x, y)


@cache_controls(4)
def table_value(topology, resolution, axes, *, find_only=False, tables=None, private=False):
    binding = _bindings(preparation_library.path())
    buffers = []
    source = abi._LUTView(*(borrow_array(axis, buffers) for axis in axes))
    operation = 0 if find_only else 1
    if tables is not None:
        epsilon, area = tables
        source.porosity, source.area_density_per_m = (borrow_array(values, buffers) for values in tables)
        _, descending = _normalized_axes(axes)
        source.porosity_fast, source.area_fast = (_fast(_normalized_values(v, descending)) for v in (epsilon, area))
        operation = 3 if private else 2
    resolution = count(resolution, name='N')
    if resolution <= 0 or resolution > ct.c_size_t(-1).value:
        raise ValueError('geometry resolution N must be a positive integer within size_t')
    view = abi._SigmoidLUT(1, ct.sizeof(abi._SigmoidLUT))
    _call(binding.table, operation, geometry_topology(topology), resolution, ct.byref(source), ct.byref(view))
    return Table(binding, view) if view.owner else None


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
        if not all(np.isfinite(axis).all() for axis in self.axes):
            raise ValueError('normalized LUT axes must increase strictly')
        self.binding = _bindings(preparation_library.path())

    def preparation_arrays(self):
        shape = tuple(axis.size for axis in self.axes)
        if self.epsilon.shape != shape or self.area.shape != shape:
            raise ValueError('LUT table shape no longer matches its captured axes')
        return (*self.axes, self.epsilon, self.area), (_fast(self.epsilon), _fast(self.area))

    def query(self, x, y):
        arrays, flags = self.preparation_arrays()
        buffers = []
        view = abi._LUTView(*(borrow_array(a, buffers) for a in arrays), *flags)
        return _sample(self.binding, view, x, y)
