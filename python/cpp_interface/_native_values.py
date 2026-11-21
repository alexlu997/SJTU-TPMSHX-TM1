"""Transport native scalar, array, and text values and apply the NumPy error policy."""
import ctypes as ct
import operator
import sys
import warnings

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
    value = operator.index(value)
    if not minimum <= value <= maximum:
        raise ValueError(error)
    return value


def iteration_count(value, *, zero=False):
    return bounded_index(value, ct.c_size_t(-1).value, 'SIMPLE count is outside native size_t bounds',
                         minimum=0 if zero else 1)


def grid_count(value):
    return bounded_index(value, ct.c_size_t(-1).value, 'grid count must be within size_t')


def floating_events(events, *, stacklevel):
    """Consume (NumPy flags, operation text) pairs in source operation order."""
    flags = ((1, 'divide', 'divide by zero'), (2, 'over', 'overflow'),
             (4, 'under', 'underflow'), (8, 'invalid', 'invalid value'))
    for value, operation in events:
        policy, handler = np.geterr(), np.geterrcall()
        for flag, category, label in flags:
            if not value & flag or policy[category] == 'ignore':
                continue
            text = f'{label} encountered in {operation}'
            mode = policy[category]
            if mode == 'warn':
                warnings.warn(text, RuntimeWarning, stacklevel=stacklevel)
            elif mode == 'raise':
                raise FloatingPointError(text)
            elif mode == 'print':
                print('Warning: ' + text, file=sys.stderr)
            elif mode == 'call':
                if handler is None:
                    raise NameError(f'python callback specified for {label} (in  {operation}) but no function found.')
                handler(label, value)
            elif mode == 'log':
                if handler is None:
                    raise NameError(f'log specified for {label} (in {operation}) but no object with write method found.')
                handler.write('Warning: ' + text + '\n')


class DoubleArray(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_double)), ('size', ct.c_size_t)]


class Text(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_char)), ('size', ct.c_size_t)]


def borrow_array(value, keepalive):
    storage = np.require(value, dtype=np.float64, requirements=['C', 'A'])
    keepalive.append(storage)
    return DoubleArray(storage.ctypes.data_as(ct.POINTER(ct.c_double)), storage.size)


def copy_array(value, shape=None, *, precision=64):
    dtype = np.dtype(f'float{precision}')
    if value.size:
        result = np.ctypeslib.as_array(value.data, shape=(value.size,)).astype(dtype, copy=True)
    else:
        result = np.empty(0, dtype=dtype)
    return result if shape is None else result.reshape(shape)


def borrow_text(value, keepalive):
    encoded = value.encode('utf-8')
    storage = ct.create_string_buffer(encoded)
    keepalive.append(storage)
    return Text(ct.cast(storage, ct.POINTER(ct.c_char)), len(encoded))


def read_text(value):
    return ct.string_at(value.data, value.size).decode('utf-8')


class GridScalar(ct.Structure):
    _fields_ = [('value', ct.c_double), ('precision', ct.c_uint32), ('strong', ct.c_uint32)]


class NumericBuffer(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_double)), ('count', ct.c_size_t), ('precision', ct.c_uint32), ('strong', ct.c_uint32)]


def grid_scalar(value):
    if isinstance(value, np.floating):
        precision = value.dtype.itemsize * 8
        if precision not in (16, 32, 64):
            raise TypeError('grid scalars support NumPy float16, float32 and float64')
        return GridScalar(float(value), precision, 1)
    if isinstance(value, np.integer):
        precision = value.dtype.itemsize * 8
        if precision not in (8, 16, 32, 64):
            raise TypeError('grid scalars support NumPy integers with 8, 16, 32 or 64 bits')
        return GridScalar(float(value), precision, 2)
    if isinstance(value, (float, int)):
        return GridScalar(float(value), 64, 0)
    raise TypeError('grid scalars require Python float/int or NumPy floating/integer values')


class GridPort(ct.Structure):
    _fields_ = [('direction', ct.c_int32), ('active', ct.c_uint32),
                ('values', (GridScalar * 4) * 2), ('present', (ct.c_uint32 * 4) * 2)]

    def set_windows(self, get, scalar=grid_scalar, *, full_width=False):
        for row, end in enumerate(('in', 'out')):
            for column, name in enumerate(('ctr', 'w', 'z_ctr', 'z_w')):
                value = get(end + '_' + name)
                if full_width and column < 2:
                    value = 0.
                if value is not None:
                    self.present[row][column] = 1
                    self.values[row][column] = scalar(value)

    @classmethod
    def from_mapping(cls, config):
        if config is None:
            return cls()
        port = cls(operator.index(config.get('dir', 0)), 1)
        port.set_windows(config.get)
        return port


def restore_grid_scalar(value):
    if value.strong:
        return np.dtype(f'float{value.precision}').type(value.value)
    return value.value


def buffer_scalar(value):
    if isinstance(value, np.ndarray) and value.ndim == 0:
        value = value[()]
    return grid_scalar(value)


def restore_buffer_scalar(value):
    if value.strong == 2:
        return np.dtype(f'int{value.precision}').type(value.value)
    return restore_grid_scalar(value)


def numeric_buffer(value, *, shape=None, preserve_scalar=False):
    original, value = value, np.asarray(value)
    if preserve_scalar and np.isscalar(original):
        tag = buffer_scalar(original)
        precision, strong = tag.precision, tag.strong
    elif value.dtype.kind == 'f' and value.dtype.itemsize in (2, 4, 8):
        precision, strong = value.dtype.itemsize * 8, 1
    elif value.dtype.kind in 'iub' and value.dtype.itemsize in (1, 2, 4, 8):
        precision, strong = value.dtype.itemsize * 8, 2
    else:
        raise TypeError('inlet buffers require real floating or integer values')
    packed = np.ascontiguousarray(value if shape is None else np.broadcast_to(value, shape), dtype=np.float64).ravel()
    return packed, NumericBuffer(packed.ctypes.data_as(ct.POINTER(ct.c_double)), packed.size, precision, strong)


def grid_widths(values):
    original = np.asarray(values)
    if original.ndim != 1:
        raise ValueError('grid widths must be one-dimensional')
    precision = original.dtype.itemsize * 8 if original.dtype.kind == 'f' else 64
    if precision not in (16, 32, 64):
        raise TypeError('grid widths support NumPy float16, float32 and float64')
    return np.ascontiguousarray(original, dtype=np.float64), precision


class _Scalar(ct.Structure):
    _fields_ = [('dtype', ct.c_uint32), ('origin', ct.c_uint32), ('byte_order', ct.c_uint32), ('reserved', ct.c_uint32),
                ('data', ct.c_ubyte * 32)]


class _Array(ct.Structure):
    _fields_ = [('data', ct.c_void_p), ('bytes', ct.c_size_t), ('offset', ct.c_size_t),
                ('dtype', ct.c_uint32), ('origin', ct.c_uint32), ('byte_order', ct.c_uint32), ('reserved', ct.c_uint32),
                ('rank', ct.c_size_t), ('shape', ct.POINTER(ct.c_size_t)), ('strides', ct.POINTER(ct.c_ssize_t))]


class _Event(ct.Structure):
    _fields_ = [('flags', ct.c_uint32), ('operation', ct.c_uint32), ('scalar', ct.c_uint32), ('reserved', ct.c_uint32)]


class _Diagnostics(ct.Structure):
    _fields_ = [('python_cause', ct.c_uint32), ('event_count', ct.c_uint32), ('error_number', ct.c_int32),
                ('reserved', ct.c_uint32), ('events', _Event * 64)]


_KINDS = {('b', 1): 1, ('i', 1): 2, ('u', 1): 3, ('i', 2): 4, ('u', 2): 5,
          ('i', 4): 6, ('u', 4): 7, ('i', 8): 8, ('u', 8): 9,
          ('f', 2): 10, ('f', 4): 11, ('f', 8): 12, ('c', 8): 14, ('c', 16): 15}
NATIVE_DTYPES = {value: np.dtype(kind + str(size)) for (kind, size), value in _KINDS.items()}
NATIVE_DTYPES[13], NATIVE_DTYPES[16] = np.dtype(np.longdouble), np.dtype(np.clongdouble)
_OPERATIONS = {1: 'add', 2: 'subtract', 3: 'multiply', 4: 'divide', 5: 'power', 6: 'log',
               7: 'exp', 8: 'cast', 9: 'log10', 10: 'sqrt', 11: 'reduce', 12: 'absolute',
               13: 'maximum', 14: 'minimum', 15: 'square'}


def _dtype_tag(dtype, check_extended):
    dtype = np.dtype(dtype)
    key = dtype.kind, dtype.itemsize
    if key in _KINDS:
        return _KINDS[key]
    if dtype.kind == 'f' and dtype.itemsize == np.dtype(np.longdouble).itemsize:
        if check_extended is not None:
            check_extended()
        return 13
    if dtype.kind == 'c' and dtype.itemsize == np.dtype(np.clongdouble).itemsize:
        if check_extended is not None:
            check_extended()
        return 16
    raise TypeError(f'native result buffers require numeric data, got {dtype}')


def _origin(value):
    if isinstance(value, np.ndarray):
        return 2
    if isinstance(value, np.generic):
        return 1
    if type(value) is float:
        return 0
    if type(value) is int:
        return 3
    if type(value) is bool:
        return 4
    if type(value) is complex:
        return 5
    return 2


def _order(dtype):
    return {'<': 1, '>': 2}.get(dtype.byteorder, 0)


class PackedArray:
    def __init__(self, value, *, check_extended=None):
        self.owner = np.asarray(value)
        tag, origin = _dtype_tag(self.owner.dtype, check_extended), _origin(value)
        shape, strides = self.owner.shape, self.owner.strides
        self.shape = (ct.c_size_t * len(shape))(*shape)
        self.strides = (ct.c_ssize_t * len(strides))(*strides)
        if self.owner.size:
            lower = sum(min(0, stride * (size - 1)) for size, stride in zip(shape, strides))
            upper = sum(max(0, stride * (size - 1)) for size, stride in zip(shape, strides))
            pointer, count, offset = self.owner.ctypes.data + lower, upper - lower + self.owner.itemsize, -lower
        else:
            pointer, count, offset = None, 0, 0
        self.raw = _Array(pointer, count, offset, tag, origin, _order(self.owner.dtype), 0,
                          self.owner.ndim, self.shape, self.strides)


def packed_scalar(value, *, check_extended=None):
    owner = np.asarray(value)
    if owner.ndim:
        raise TypeError('native result scalar requires a scalar or a zero-dimensional array')
    tag = _dtype_tag(owner.dtype, check_extended)
    raw = _Scalar(tag, _origin(value), _order(owner.dtype), 0)
    data = owner.tobytes()
    if len(data) > len(raw.data):
        raise RuntimeError('native result scalar payload is too small')
    ct.memmove(raw.data, data, len(data))
    return raw


def notify_diagnostics(diagnostics, *, stacklevel):
    """Apply host error policy at one completed native primitive boundary."""
    if diagnostics.reserved or diagnostics.event_count > 64:
        raise RuntimeError('native result returned invalid diagnostics')
    events = []
    for event in diagnostics.events[:diagnostics.event_count]:
        if event.reserved or event.flags > 15 or event.scalar > 1 or event.operation not in _OPERATIONS:
            raise RuntimeError('native result returned an invalid floating-point event')
        operation = _OPERATIONS[event.operation]
        if event.scalar and event.operation in (1, 2, 3, 4, 5, 8):
            operation = 'scalar ' + operation
        events.append((event.flags, operation))
    floating_events(events, stacklevel=stacklevel)
