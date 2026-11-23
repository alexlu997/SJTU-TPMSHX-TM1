"""Normalize and transport native float64 scalars, arrays, and text."""
import ctypes as ct
import math
import operator

import numpy as np


# The order matches tpmshx::Topology in the C++ interface.
TOPOLOGIES = ('Diamond', 'Gyroid')
TOPOLOGY_CODES = {name: index for index, name in enumerate(TOPOLOGIES)}


def geometry_topology(name):
    try:
        return TOPOLOGY_CODES[name]
    except (KeyError, TypeError) as error:
        raise ValueError(f'TPMS geometry supports Diamond and Gyroid only: {name!r}') from error


def bounded_index(value, maximum, error, *, minimum=0):
    value = count(value, name='count')
    if not minimum <= value <= maximum:
        raise ValueError(error)
    return value


def iteration_count(value, *, zero=False):
    return bounded_index(value, ct.c_size_t(-1).value, 'SIMPLE count is outside native size_t bounds',
                         minimum=0 if zero else 1)


def grid_count(value):
    return bounded_index(value, ct.c_size_t(-1).value, 'grid count must be within size_t')


def real_scalar(value, *, name='value', allow_nonfinite=False):
    """Return one real number as a Python float.

    Raw numerical kernels set allow_nonfinite so that NaN and Inf propagate.
    """
    if isinstance(value, np.ndarray):
        if value.ndim:
            raise TypeError(f'{name} must be a real scalar, not an array')
        value = value[()]
    if (isinstance(value, (bool, np.bool_, complex, np.complexfloating, str, bytes))
            or not isinstance(value, (int, float, np.integer, np.floating))):
        raise TypeError(f'{name} must be a real number, got {type(value).__name__}')
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f'{name} is outside the float64 range') from error
    if not allow_nonfinite and not math.isfinite(result):
        raise ValueError(f'{name} must be finite, got {result}')
    return result


def real_array(value, *, name='values', allow_nonfinite=False):
    """Return a C-contiguous float64 copy of a real array."""
    array = np.asarray(value)
    if array.dtype.kind not in 'fiu':
        raise TypeError(f'{name} must contain real numbers, got {array.dtype}')
    try:
        result = np.array(array, dtype=np.float64, order='C', copy=True)
    except OverflowError as error:
        raise ValueError(f'{name} is outside the float64 range') from error
    if not allow_nonfinite and not np.isfinite(result).all():
        raise ValueError(f'{name} must be finite')
    return result


def count(value, *, name='count'):
    """Return a non-boolean integer count."""
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f'{name} must be an integer, not bool')
    return operator.index(value)


class DoubleArray(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_double)), ('size', ct.c_size_t)]


class Text(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_char)), ('size', ct.c_size_t)]


def borrow_array(value, keepalive):
    storage = np.require(value, dtype=np.float64, requirements=['C', 'A'])
    keepalive.append(storage)
    return DoubleArray(storage.ctypes.data_as(ct.POINTER(ct.c_double)), storage.size)


def copy_array(value, shape=None):
    if value.size:
        result = np.empty(value.size, dtype=np.float64)
        result[:] = np.ctypeslib.as_array(value.data, shape=(value.size,))
    else:
        result = np.empty(0, dtype=np.float64)
    return result if shape is None else result.reshape(shape)


def borrow_text(value, keepalive):
    encoded = value.encode('utf-8')
    storage = ct.create_string_buffer(encoded)
    keepalive.append(storage)
    return Text(ct.cast(storage, ct.POINTER(ct.c_char)), len(encoded))


def read_text(value):
    return ct.string_at(value.data, value.size).decode('utf-8')


class GridPort(ct.Structure):
    _fields_ = [('direction', ct.c_int32), ('active', ct.c_uint32),
                ('values', (ct.c_double * 4) * 2), ('present', (ct.c_uint32 * 4) * 2)]

    def set_windows(self, get, *, full_width=False):
        for row, end in enumerate(('in', 'out')):
            for column, name in enumerate(('ctr', 'w', 'z_ctr', 'z_w')):
                key = end + '_' + name
                value = get(key)
                if full_width and column < 2:
                    value = 0.
                if value is not None:
                    self.present[row][column] = 1
                    self.values[row][column] = real_scalar(value, name=key, allow_nonfinite=True)

    @classmethod
    def from_mapping(cls, config):
        if config is None:
            return cls()
        port = cls(count(config.get('dir', 0), name='dir'), 1)
        port.set_windows(config.get)
        return port


class _Event(ct.Structure):
    _fields_ = [('flags', ct.c_uint32), ('operation', ct.c_uint32), ('scalar', ct.c_uint32), ('reserved', ct.c_uint32)]


class _Diagnostics(ct.Structure):
    _fields_ = [('python_cause', ct.c_uint32), ('event_count', ct.c_uint32), ('error_number', ct.c_int32),
                ('reserved', ct.c_uint32), ('events', _Event * 64)]


_OPERATIONS = {1: 'add', 2: 'subtract', 3: 'multiply', 4: 'divide', 5: 'power', 6: 'log',
               7: 'exp', 8: 'cast', 9: 'log10', 10: 'sqrt', 11: 'reduce', 12: 'absolute',
               13: 'maximum', 14: 'minimum', 15: 'square'}
