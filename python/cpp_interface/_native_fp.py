"""Transport typed numerical inputs and apply the NumPy error policy."""
import ctypes as ct
import sys
import warnings

import numpy as np


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
