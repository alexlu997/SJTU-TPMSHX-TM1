"""Call the native geometry core through its C data interface."""
import ctypes as ct
from functools import lru_cache
from importlib.resources import files
import os
from pathlib import Path
import platform
import sys
import weakref

import numpy as np


_DoubleP = ct.POINTER(ct.c_double)
_Int64P = ct.POINTER(ct.c_int64)
_SizeP = ct.POINTER(ct.c_size_t)
_Handle = ct.c_void_p
_HandleP = ct.POINTER(_Handle)
_Uint = ct.c_uint32
_Size = ct.c_size_t
_Double = ct.c_double
_Error = (ct.POINTER(ct.c_char), _Size)


class _Prepared(ct.Structure):
    _fields_ = [('split_a', _Double), ('has_sides', _Uint), ('sides', (_Double * 4) * 2)]


class _Levels(ct.Structure):
    _fields_ = [('lower', _Double), ('upper', _Double),
                ('comparison_lower', _Double), ('comparison_upper', _Double),
                ('lower_precision', _Uint), ('upper_precision', _Uint)]


_PreparedP = ct.POINTER(_Prepared)
_LevelsP = ct.POINTER(_Levels)
_SIGNATURES = {
    'index_create': [_Uint, _Size, _HandleP],
    'index_create_from_phi': [_SizeP, _DoubleP, _Size, _HandleP],
    'phi_grid': [_Uint, _Size, _DoubleP, _Size],
    'threshold_batch': [_Uint, _DoubleP, _Size, _DoubleP, _Size],
    'hydraulic_radius_batch': [_DoubleP, _Size, _DoubleP, _Size],
    'counts': [_Handle, _DoubleP, _Size, _Int64P, _Size],
    'standard_batch': [_Handle, _Uint, _DoubleP, _DoubleP, _Size,
                       _Double, _Uint, _Double, _DoubleP, _Size],
    'raw_batch': [_Handle, _Uint, _DoubleP, _DoubleP, _Size, _DoubleP, _Size],
    'chi_batch': [_Uint, _DoubleP, _Size, _Uint, _Double, _DoubleP, _Size],
    'material_batch': [_Uint, _DoubleP, _Size, _Double, _Uint, _Double, _DoubleP, _Size],
    'lut_batch': [_Uint, _DoubleP, _DoubleP, _Size, _Double, _Uint, _Double, _DoubleP, _Size],
    'standard_minimum': [_Handle, _Uint, _DoubleP, _DoubleP, _DoubleP, _Size],
    'co2_batch': [_Uint, _DoubleP, _DoubleP, _Size, _Double, _Uint, _Double, _DoubleP, _Size],
    'co2_minimum': [_Uint, _DoubleP, _DoubleP, _Uint, _Double, _DoubleP, _Size],
    'eps_sides': [_DoubleP, _Size, _LevelsP, _DoubleP, _Size],
    'area_sides': [_SizeP, _DoubleP, _Size, _LevelsP, _Double, _Double,
                   _Double, _Uint, _DoubleP, _Size],
    'dh_sides': [_SizeP, _DoubleP, _Size, _LevelsP, _Double, _Double,
                 _Double, _Uint, _DoubleP, _Size],
    'dh_from_sides': [_Double, _Double, _Double, _Double, _DoubleP, _Size],
    'wall_thickness': [_SizeP, _DoubleP, _Size, _LevelsP, _Double, _Double,
                       _Double, _DoubleP, _Size],
    'wall_from_sides': [_Double, _Double, _Double, _DoubleP, _Size],
    'split_a': [_DoubleP, _Size, _LevelsP, _Uint, _DoubleP, _Size],
    'split_fields': [_DoubleP, _Size, _Double, _DoubleP, _Size],
    'prepare_raw_sides': [_SizeP, _DoubleP, _Size, _LevelsP, _LevelsP, _Uint,
                          _Double, _Double, _Double, _PreparedP],
    'prepare_from_index': [_Handle, _Uint, _Double, _Double, _Double, _PreparedP],
    'split_from_index': [_Handle, _Uint, _Double, _Double, _Double, _DoubleP, _Size],
}
_GEOMETRY_KEYS = ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h', 'K_ss')
_MINIMUM_KEYS = ('L_mm', 't_mm', 'epsilon')


def _library_path():
    selected = os.environ.get('TPMSHX_GEOMETRY_LIBRARY')
    if selected is not None:
        if not selected.strip():
            raise ValueError('TPMSHX_GEOMETRY_LIBRARY must name a prebuilt geometry library')
        path = Path(selected).expanduser()
    else:
        machine = platform.machine().lower()
        if sys.platform == 'darwin' and machine in ('arm64', 'aarch64'):
            host, name = 'macos-arm64', 'libtpmshx_geometry_shared.dylib'
        elif sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
            host, name = 'windows-x64', 'tpmshx_geometry_shared.dll'
        else:
            raise RuntimeError(
                f'no default native geometry library for {sys.platform}/{machine}; '
                'set TPMSHX_GEOMETRY_LIBRARY to a prebuilt library')
        if getattr(sys, 'frozen', False):
            path = Path(sys._MEIPASS) / 'native' / name
        else:
            resource = files('sjtu_tpmshx').joinpath('solvers', 'native', 'lib', host, name)
            path = Path(str(resource))
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f'prebuilt native geometry library is missing: {path}')
    return str(path)


class _NativeLibrary:
    def __init__(self, path):
        self.path = path
        try:
            self.library = ct.CDLL(path)
        except OSError as error:
            raise OSError(f'cannot load prebuilt native geometry library {path}: {error}') from error
        version = self._bind('abi_version', [], ct.c_uint32, error=False)
        abi = version()
        if abi != 1:
            raise ValueError(f'unsupported native geometry ABI {abi} in {path}; expected 1')
        self.index_destroy = self._bind('index_destroy', [_Handle], None, error=False)
        for name, signature in _SIGNATURES.items():
            setattr(self, name, self._bind(name, signature))

    def _bind(self, name, signature, result=ct.c_int, *, error=True):
        symbol = f'tpmshx_geometry_{name}_v1'
        try:
            function = getattr(self.library, symbol)
        except AttributeError as missing:
            raise ValueError(f'prebuilt native geometry library {self.path} lacks {symbol}') from missing
        function.argtypes = [*signature, *_Error] if error else signature
        function.restype = result
        return function


@lru_cache(maxsize=1)
def _load_library(path):
    return _NativeLibrary(path)


def _library():
    return _load_library(_library_path())


def _call(function, *arguments):
    error = ct.create_string_buffer(2048)
    status = function(*arguments, error, len(error))
    if status:
        message = error.value.decode('utf-8', errors='replace') or f'native geometry failed with code {status}'
        exception = {1: ValueError, 2: ZeroDivisionError, 3: RuntimeError}.get(status, RuntimeError)
        raise exception(message)


def _topology(name):
    try:
        return {'Diamond': 0, 'Gyroid': 1}[name]
    except (KeyError, TypeError) as error:
        raise ValueError(f'TPMS geometry supports Diamond and Gyroid only: {name!r}') from error


def _resolution(value):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
            or value < 1 or value > ct.c_size_t(-1).value):
        raise ValueError('geometry resolution N must be a positive integer within size_t')
    return int(value)


def _release_index(destroy, library, handle):
    # Retain the library in the finalizer arguments until destroy returns.
    destroy(handle)


class _Index:
    __slots__ = ('library', 'handle', '_finalizer', '__weakref__')

    def __init__(self, library, topology, resolution):
        handle = _Handle()
        _call(library.index_create, topology, resolution, ct.byref(handle))
        if not handle.value:
            raise RuntimeError('native geometry index creation returned a null handle')
        self.library, self.handle = library, handle
        self._finalizer = weakref.finalize(
            self, _release_index, library.index_destroy, library, handle)


@lru_cache(maxsize=2)
def _cached_index(path, topology, resolution):
    return _Index(_load_library(path), topology, resolution)


def _index(topology, resolution):
    code, n = _topology(topology), _resolution(resolution)
    return _cached_index(_library_path(), code, n), code


def _array(values):
    return np.require(values, dtype=np.float64, requirements=['C', 'A', 'E'])


def _pair(cells, walls):
    cell, wall = _array(cells), _array(walls)
    if cell.shape != wall.shape:
        raise ValueError('L/t fields must have the same array shape')
    return cell, wall


def _pointer(values):
    return values.ctypes.data_as(_DoubleP)


def _override(value):
    return (0, 0.) if value is None else (1, float(value))


def _rows(shape, columns):
    return np.empty((*shape, columns), dtype=np.float64, order='C')


def _fields(rows, keys):
    return {key: np.array(rows[..., column], dtype=np.float64, order='C', copy=True)
            for column, key in enumerate(keys)}


def _bounds(values):
    result = _array(values)
    if result.shape != (2,):
        raise ValueError('geometry bounds require two values')
    return result


def _phi3(values):
    phi = _array(values)
    if phi.ndim != 3:
        raise ValueError('raw geometry phi must have three dimensions')
    return phi, (ct.c_size_t * 3)(*phi.shape)


def _raw_levels(phi, C, delta):
    source = np.asarray(phi)
    lower, upper = delta - C, delta + C
    # Keep NumPy weak-scalar comparisons after the borrowed buffer becomes float64.
    return _Levels(float(lower), float(upper),
                   float(np.result_type(source, lower).type(lower)),
                   float(np.result_type(source, upper).type(upper)),
                   np.result_type(lower, 0.).itemsize * 8,
                   np.result_type(upper, 0.).itemsize * 8)


@lru_cache(maxsize=4)
def _cached_phi(path, topology, resolution):
    library = _load_library(path)
    result = np.empty((resolution, resolution, resolution), dtype=np.float64, order='C')
    _call(library.phi_grid, topology, resolution, _pointer(result), result.size)
    result.flags.writeable = False
    return result


def phi_grid(topology, N=128):
    code, n = _topology(topology), _resolution(N)
    return _cached_phi(_library_path(), code, n)


def threshold(topology, wall_over_cell):
    code, values = _topology(topology), _array(wall_over_cell)
    result = np.empty(values.shape, dtype=np.float64, order='C')
    _call(_library().threshold_batch, code, _pointer(values), values.size, _pointer(result), result.size)
    return result


def hydraulic_radius(diameter):
    values = _array(diameter)
    result = np.empty(values.shape, dtype=np.float64, order='C')
    _call(_library().hydraulic_radius_batch, _pointer(values), values.size,
          _pointer(result), result.size)
    return result


def counts(topology, thresholds, N=128):
    index, _ = _index(topology, N)
    values = _array(thresholds)
    result = np.empty((*values.shape, 3), dtype=np.int64, order='C')
    _call(index.library.counts, index.handle, _pointer(values), values.size,
          result.ctypes.data_as(_Int64P), result.size)
    return result


def standard_fields(topology, cells_mm, walls_mm, conductivity, *, chi_s=None, N=128):
    cells, walls = _pair(cells_mm, walls_mm)
    index, code = _index(topology, N)
    result = _rows(cells.shape, 6)
    _call(index.library.standard_batch, index.handle, code, _pointer(cells), _pointer(walls), cells.size,
          float(conductivity), *_override(chi_s), _pointer(result), result.size)
    return _fields(result, _GEOMETRY_KEYS)


def raw_fields(topology, cells_mm, walls_mm, *, N=128):
    cells, walls = _pair(cells_mm, walls_mm)
    index, code = _index(topology, N)
    result = _rows(cells.shape, 2)
    _call(index.library.raw_batch, index.handle, code, _pointer(cells), _pointer(walls), cells.size,
          _pointer(result), result.size)
    return _fields(result, ('epsilon', 'A_0'))


def chi_fields(topology, epsilon, *, chi_s=None):
    code, values = _topology(topology), _array(epsilon)
    result = np.empty(values.shape, dtype=np.float64, order='C')
    _call(_library().chi_batch, code, _pointer(values), values.size, *_override(chi_s),
          _pointer(result), result.size)
    return result


def material_fields(topology, epsilon, conductivity, *, chi_s=None):
    code, values = _topology(topology), _array(epsilon)
    result = _rows(values.shape, 2)
    _call(_library().material_batch, code, _pointer(values), values.size, float(conductivity),
          *_override(chi_s), _pointer(result), result.size)
    return _fields(result, ('chi_s', 'K_ss'))


def lut_fields(topology, epsilon, area, conductivity, *, chi_s=None):
    code = _topology(topology)
    values, areas = _pair(epsilon, area)
    result = _rows(values.shape, 7)
    _call(_library().lut_batch, code, _pointer(values), _pointer(areas), values.size,
          float(conductivity), *_override(chi_s), _pointer(result), result.size)
    return _fields(result, (*_GEOMETRY_KEYS, 'r_h'))


def standard_minimum(topology, cell_bounds_mm, wall_bounds_mm):
    cells, walls = _bounds(cell_bounds_mm), _bounds(wall_bounds_mm)
    index, code = _index(topology, 128)
    result = np.empty(3, dtype=np.float64)
    _call(index.library.standard_minimum, index.handle, code, _pointer(cells), _pointer(walls),
          _pointer(result), result.size)
    return dict(zip(_MINIMUM_KEYS, result))


def co2_fields(topology, cells_mm, walls_mm, conductivity, *, chi_s=None):
    code = _topology(topology)
    cells, walls = _pair(cells_mm, walls_mm)
    result = _rows(cells.shape, 6)
    _call(_library().co2_batch, code, _pointer(cells), _pointer(walls), cells.size, float(conductivity),
          *_override(chi_s), _pointer(result), result.size)
    return _fields(result, _GEOMETRY_KEYS)


def co2_minimum(topology, cell_bounds_mm, wall_bounds_mm, *, chi_s=None):
    code = _topology(topology)
    cells, walls = _bounds(cell_bounds_mm), _bounds(wall_bounds_mm)
    result = np.empty(3, dtype=np.float64)
    _call(_library().co2_minimum, code, _pointer(cells), _pointer(walls), *_override(chi_s),
          _pointer(result), result.size)
    return dict(zip(_MINIMUM_KEYS, result))


def eps_sides(phi, C, delta=0.):
    values = _array(phi)
    levels = _raw_levels(phi, C, delta)
    result = np.empty(3, dtype=np.float64)
    _call(_library().eps_sides, _pointer(values), values.size, ct.byref(levels),
          _pointer(result), result.size)
    return result


def area_sides(phi, C, delta, length_m, N, area_correction, *, mc=False):
    values, shape = _phi3(phi)
    levels = _raw_levels(phi, C, delta)
    result = np.empty(2, dtype=np.float64)
    _call(_library().area_sides, shape, _pointer(values), values.size,
          ct.byref(levels), float(length_m), float(N), float(area_correction), int(mc),
          _pointer(result), result.size)
    return result


def dh_sides(phi, C, delta, length_m, N, area_correction, *, mc=False):
    values, shape = _phi3(phi)
    levels = _raw_levels(phi, C, delta)
    result = np.empty(2, dtype=np.float64)
    _call(_library().dh_sides, shape, _pointer(values), values.size,
          ct.byref(levels), float(length_m), float(N), float(area_correction), int(mc),
          _pointer(result), result.size)
    return result


def dh_from_sides(epsilon_a, epsilon_b, area_a, area_b):
    result = np.empty(2, dtype=np.float64)
    _call(_library().dh_from_sides, float(epsilon_a), float(epsilon_b), float(area_a), float(area_b),
          _pointer(result), result.size)
    return result


def wall_thickness(phi, C, delta, length_m, N, area_correction):
    values, shape = _phi3(phi)
    levels = _raw_levels(phi, C, delta)
    result = np.empty(1, dtype=np.float64)
    _call(_library().wall_thickness, shape, _pointer(values), values.size,
          ct.byref(levels), float(length_m), float(N), float(area_correction),
          _pointer(result), result.size)
    return result[0]


def wall_from_sides(epsilon_total, area_a, area_b):
    result = np.empty(1, dtype=np.float64)
    _call(_library().wall_from_sides, float(epsilon_total), float(area_a), float(area_b),
          _pointer(result), result.size)
    return result[0]


def split_a(phi, C, delta):
    values = _array(phi)
    levels = _raw_levels(phi, C, delta)
    result = np.empty(1, dtype=np.float64)
    _call(_library().split_a, _pointer(values), values.size, ct.byref(levels), int(delta == 0.),
          _pointer(result), result.size)
    return result[0]


def split_fields(epsilon_total, fraction_a):
    values = _array(epsilon_total)
    result = _rows(values.shape, 2)
    _call(_library().split_fields, _pointer(values), values.size, float(fraction_a),
          _pointer(result), result.size)
    return _fields(result, ('epsilon_A', 'epsilon_B'))


def _prepared_values(result):
    if result.has_sides not in (0, 1):
        raise RuntimeError('native geometry returned an invalid prepared-side flag')
    sides = ({side: tuple(result.sides[index]) for index, side in enumerate(('A', 'B'))}
             if result.has_sides else None)
    return {'split_A': result.split_a, 'side_geometry': sides}


def prepare_raw_sides(phi, C, delta, length_m, N, area_correction):
    values, shape = _phi3(phi)
    levels, reference = _raw_levels(phi, C, delta), _raw_levels(phi, C, 0.)
    result = _Prepared()
    _call(_library().prepare_raw_sides, shape, _pointer(values), values.size,
          ct.byref(levels), ct.byref(reference), int(delta == 0.),
          float(length_m), float(N), float(area_correction), ct.byref(result))
    return _prepared_values(result)


def prepare_sides(topology, cell_mm, wall_mm, delta):
    if delta == 0.:
        # The native zero-offset rule does not need a standard-geometry index.
        return prepare_raw_sides(np.empty((0, 0, 0)), 0., 0., 0., 0., 0.)
    index, code = _index(topology, 128)
    result = _Prepared()
    _call(index.library.prepare_from_index, index.handle, code,
          float(cell_mm), float(wall_mm), float(delta), ct.byref(result))
    return _prepared_values(result)


def split_from_index(topology, cell_mm, wall_mm, delta):
    index, code = _index(topology, 128)
    result = np.empty(1, dtype=np.float64)
    _call(index.library.split_from_index, index.handle, code, float(cell_mm), float(wall_mm),
          float(delta), _pointer(result), result.size)
    return result[0]
