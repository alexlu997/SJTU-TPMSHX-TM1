"""Adapt property data and error policy for the native preparation library."""
import ctypes as ct
import errno
from functools import lru_cache
import sys
import os
import warnings

import numpy as np

from ._native_grid import _Scalar, _scalar
from ._native_preparation import _library


_Size = ct.c_size_t
_Uint = ct.c_uint32
_DoubleP = ct.POINTER(ct.c_double)
_UintP = ct.POINTER(_Uint)
_EVENTS = 32


class _Input(ct.Structure):
    _fields_ = [('values', _DoubleP), ('count', _Size), ('kind', _Scalar), ('layout', _Uint)]


class _Operand(ct.Structure):
    _fields_ = [('real', _Input), ('imaginary', ct.c_double), ('category', _Uint)]


class _Output(ct.Structure):
    _fields_ = [('values', _DoubleP), ('imaginary', _DoubleP), ('count', _Size),
                ('kind', ct.POINTER(_Scalar)), ('category', _UintP),
                ('events', _UintP), ('event_count', _Size)]


class _FPFailure(ct.Structure):
    _fields_ = [('python_cause', _Uint), ('event_count', _Uint), ('events', _Uint * _EVENTS)]


class _Failure(ct.Structure):
    _fields_ = [('reason', _Uint), ('input', _Uint),
                ('index', _Size), ('first_t_index', _Size), ('first_p_index', _Size),
                ('temperature', ct.c_double), ('pressure', ct.c_double), ('detail', ct.c_double), ('fp', _FPFailure)]


class _Key(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_char)), ('size', _Size)]


class StateError(ValueError):
    """Carry native state diagnostics to the original public error context."""
    def __init__(self, status, text, failure):
        super().__init__(text)
        self.status, self.failure = status, failure


_SIGNATURES = {
    'empirical': [_Uint, _Input, _Input, _Output],
    'water_pt': [_DoubleP, _DoubleP, _Size],
    'co2_validate_pt': [_DoubleP, _DoubleP, _Size],
    'co2_scalar_bundle': [ct.c_double, ct.c_double, _DoubleP, _Size],
    'co2_pt': [_DoubleP, _DoubleP, _Size, _UintP, _Size, _DoubleP, _Size],
    'sco2_validate': [_DoubleP, _Size, _DoubleP, _Size],
    'sco2_pt': [_Uint, ct.POINTER(_Key), _Size, _DoubleP, _DoubleP, _Size, _DoubleP, _Size],
    'sco2_hp_scalar': [ct.c_double, ct.c_double, _DoubleP, _Size],
    'sco2_hp': [_DoubleP, _DoubleP, _Size, _DoubleP, _Size],
    'nu_inputs': [_Uint, _Input, _Input, _Input, _Input, _Input, _Output, _DoubleP, _Size],
    'nu': [_Uint, _Uint, _Input, _Input, _Input, _Input, _Scalar, _Output],
    'roughness': [_Uint, _Input, _Input, _Output],
    'reynolds': [_Input, _Input, _Input, _Input, _Output],
    'prandtl': [_Operand, _Operand, _Operand, _Output],
    'surface_transfer': [_Operand, _Operand, _Operand, _Output],
    'inlet_re_pr': [_Input] * 6 + [_Output] * 2,
    'inlet_transfer': [_Input] * 5 + [_Output] * 3,
    'volumetric_transfer': [_Input, _Input, _Output],
    'pore_conductivity': [_Input, _Input, _Output],
}


@lru_cache(maxsize=None)
def _function(owner, name):
    return owner.bind(f'tpmshx_preparation_{name}_v1',
                      _SIGNATURES[name] + [ct.POINTER(_Failure), ct.POINTER(ct.c_char), _Size])


def _call(name, *arguments):
    owner = _library()
    failure, error = _Failure(), ct.create_string_buffer(4096)
    status = _function(owner, name)(*arguments, ct.byref(failure), error, len(error))
    if not status:
        return
    _floating_events(failure.fp.events[:failure.fp.event_count])
    text = error.value.decode('utf-8', errors='replace')
    if status in (10, 11, 12):
        raise StateError(status, text, failure)
    if status == 2:
        raise MemoryError(text)
    if status == 1:
        raise ValueError(text)
    if failure.fp.python_cause == 2:
        raise OverflowError(errno.ERANGE, os.strerror(errno.ERANGE))
    exception = {1: ZeroDivisionError, 2: OverflowError, 3: ValueError, 4: TypeError}.get(
        failure.fp.python_cause, RuntimeError)
    raise exception(text)


def _pointer(values):
    return values.ctypes.data_as(_DoubleP)


def _typed(value, *, coerce=False):
    if coerce:
        array = np.asarray(value, dtype=np.float64)
        return array, _Scalar(float(array) if array.ndim == 0 else 0., 64, 1), 2 if array.ndim == 0 else 3
    array = np.asarray(value)
    if isinstance(value, (float, int, np.floating, np.integer)):
        kind = _scalar(value)
        return array, kind, 1 if isinstance(value, np.generic) else 0
    if array.dtype.kind not in 'fiu' or array.dtype.itemsize * 8 not in (8, 16, 32, 64):
        raise TypeError('property arrays require supported real floating or integer values')
    bits = array.dtype.itemsize * 8
    if array.dtype.kind == 'f' and bits not in (16, 32, 64):
        raise TypeError('property arrays support float16, float32 and float64')
    return array, _Scalar(float(array) if array.ndim == 0 else 0., bits,
                          1 if array.dtype.kind == 'f' else 2), 2 if array.ndim == 0 else 3


def _ufunc_shape_error(*shapes):
    text = ' '.join('(' + ','.join(map(str, shape)) + (',' if len(shape) == 1 else '') + ')'
                    for shape in shapes)
    return ValueError(f'operands could not be broadcast together with shapes {text} ')


def _inputs(values, *, coerce=False, ufunc_shapes=False):
    tagged = [_typed(value, coerce=coerce) for value in values]
    try:
        broadcast = np.broadcast_arrays(*(item[0] for item in tagged))
    except ValueError:
        if ufunc_shapes:
            raise _ufunc_shape_error(*(item[0].shape for item in tagged)) from None
        raise
    buffers = [np.ascontiguousarray(value.reshape(-1), dtype=np.float64) for value in broadcast]
    inputs = [_Input(_pointer(buffer), buffer.size, kind, layout)
              for buffer, (_, kind, layout) in zip(buffers, tagged)]
    return broadcast[0].shape, buffers, inputs


class _Result:
    def __init__(self, count):
        self.real = np.empty(count, dtype=np.float64)
        self.imaginary = np.empty(count, dtype=np.float64)
        self.kind, self.category = _Scalar(), _Uint()
        self.events = np.zeros(_EVENTS, dtype=np.uint32)
        self.output = _Output(_pointer(self.real), _pointer(self.imaginary), count,
                              ct.pointer(self.kind), ct.pointer(self.category),
                              self.events.ctypes.data_as(_UintP), _EVENTS)

    def restore(self, shape):
        _floating_events(self.events)
        dtype = np.dtype(f'complex{self.kind.precision * 2}' if self.category.value
                         else f'float{self.kind.precision}')
        if self.category.value:
            result = np.empty(shape, dtype=dtype)
            result.real[...] = self.real.reshape(shape)
            result.imag[...] = self.imaginary.reshape(shape)
        else:
            result = self.real.astype(dtype).reshape(shape)
        if shape:
            return result
        return result[()] if self.kind.strong else result.item()


def _floating_events(events, *, warn=None):
    policy = np.geterr()
    operations = {1: 'add', 2: 'subtract', 3: 'multiply', 4: 'divide',
                  5: 'power', 6: 'log', 7: 'exp', 8: 'cast', 9: 'log10'}
    flags = ((2, 'divide', 'divide by zero'), (4, 'over', 'overflow'),
             (8, 'under', 'underflow'), (1, 'invalid', 'invalid value'))
    for encoded in events:
        value = int(encoded)
        if not value:
            continue
        operation = operations[(value >> 8) & 255]
        if value & 0x10000 and operation not in ('log', 'exp', 'log10'):
            operation = 'scalar ' + operation
        for flag, category, label in flags:
            if not value & flag or policy[category] == 'ignore':
                continue
            text = f'{label} encountered in {operation}'
            mode = policy[category]
            if mode == 'warn':
                if warn is None:
                    warnings.warn(text, RuntimeWarning, stacklevel=4)
                else:
                    warn(text)
            elif mode == 'raise':
                raise FloatingPointError(text)
            elif mode == 'print':
                print('Warning: ' + text, file=sys.stderr)
            elif mode == 'call':
                handler = np.geterrcall()
                if handler is None:
                    raise NameError('python callback specified for error but no function found.')
                numpy_flags = ((1 if value & 2 else 0) | (2 if value & 4 else 0)
                               | (4 if value & 8 else 0) | (8 if value & 1 else 0))
                handler(label, numpy_flags)
            elif mode == 'log':
                handler = np.geterrcall()
                if handler is None:
                    raise NameError('log specified for error but no object with write method found.')
                handler.write('Warning: ' + text + '\n')


def _empirical_inputs(getter, temperature, pressure):
    """Pack one fixed empirical operation without evaluating a model."""
    water = getter >= 4
    if not water:
        def operand(value, operation, reverse=False):
            if isinstance(value, (float, int, np.number, np.ndarray)):
                return
            if operation == '*' and isinstance(value, (str, bytes, list, tuple)):
                raise TypeError("can't multiply sequence by non-int of type 'float'")
            first, second = ('float', type(value).__name__) if reverse else (type(value).__name__, 'float')
            raise TypeError(f"unsupported operand type(s) for {operation}: '{first}' and '{second}'")
        if getter == 2:
            operand(pressure, '*')
            operand(temperature, '*', True)
        else:
            operand(temperature, '-' if getter == 3 else '/')
    values = (temperature, pressure) if getter == 2 else (temperature,)
    return _inputs(values, coerce=water)


def empirical(getter, temperature, pressure=101325.0):
    shape, buffers, inputs = _empirical_inputs(getter, temperature, pressure)
    result = _Result(1 if getter == 7 else buffers[0].size)
    _call('empirical', getter, inputs[0], inputs[1] if getter == 2 else _Input(), result.output)
    return result.restore(()) if getter == 7 else result.restore(shape)


def _derived_inputs(name, values):
    """Pack derived-property operands without evaluating their expression."""
    if name in ('prandtl', 'surface_transfer'):
        real, imaginary, categories = [], [], []
        for value in values:
            if isinstance(value, (complex, np.complexfloating)):
                if np.asarray(value).dtype.itemsize not in (8, 16):
                    raise TypeError('property operands support complex64 and complex128 scalars')
                real.append(value.real)
                imaginary.append(float(value.imag))
                categories.append(1)
            else:
                if np.asarray(value).dtype.kind == 'c':
                    raise TypeError('property operands support complex scalars only')
                real.append(value)
                imaginary.append(0.)
                categories.append(0)
        shape, buffers, packed = _inputs(real)
        inputs = [_Operand(value, imag, category) for value, imag, category in zip(packed, imaginary, categories)]
    else:
        shape, buffers, inputs = _inputs(values)
    return shape, buffers, inputs


def _derived(name, values, count):
    shape, buffers, inputs = _derived_inputs(name, values)
    outputs = [_Result(buffers[0].size) for _ in range(count)]
    _call(name, *inputs, *(value.output for value in outputs))
    restored = tuple(value.restore(shape) for value in outputs)
    return restored[0] if count == 1 else restored


def reynolds(rho, speed, diameter_m, mu):
    return _derived('reynolds', (rho, speed, diameter_m, mu), 1)


def prandtl(mu, cp, k):
    return _derived('prandtl', (mu, cp, k), 1)


def surface_transfer(nu, k, diameter_m):
    return _derived('surface_transfer', (nu, k, diameter_m), 1)


def inlet_re_pr(rho, mu, k, cp, speed, diameter_m):
    return _derived('inlet_re_pr', (rho, mu, k, cp, speed, diameter_m), 2)


def inlet_transfer(nu, k, diameter_m, area_density, epsilon_side):
    return _derived('inlet_transfer', (nu, k, diameter_m, area_density, epsilon_side), 3)


def volumetric_transfer(surface_coefficient, area_density):
    return _derived('volumetric_transfer', (surface_coefficient, area_density), 1)


def pore_conductivity(epsilon, k):
    return _derived('pore_conductivity', (epsilon, k), 1)


def paired_state(name, temperature, pressure):
    shape, buffers, _ = _inputs((temperature, pressure), coerce=True)
    _call(name, _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size)
    return shape, buffers


def co2_scalar_bundle(temperature, pressure):
    output = np.empty(5, dtype=np.float64)
    _call('co2_scalar_bundle', temperature, pressure, _pointer(output), output.size)
    return tuple(float(value) for value in output)


def co2_pt(keys, temperature, pressure):
    shape, buffers, _ = _inputs((temperature, pressure), coerce=True)
    indices = np.asarray(keys, dtype=np.uint32)
    output = np.empty((len(keys),) + shape, dtype=np.float64)
    _call('co2_pt', _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size,
          indices.ctypes.data_as(_UintP), indices.size, _pointer(output), output.size)
    return tuple(output[index] for index in range(len(keys)))


def sco2_validate(temperature, pressure):
    first = np.ascontiguousarray(np.asarray(temperature, dtype=np.float64).reshape(-1))
    second = np.ascontiguousarray(np.asarray(pressure, dtype=np.float64).reshape(-1))
    _call('sco2_validate', _pointer(first), first.size, _pointer(second), second.size)


def sco2_scalar_pressure(pressure):
    """Check scalar HP pressure before the original enthalpy conversion."""
    try:
        sco2_validate(np.empty(0, dtype=np.float64), pressure)
    except StateError:
        raise ValueError('sCO2 pressure must be within 7.9..16 MPa') from None


def sco2_pt(key, temperature, pressure, *, scalar=False):
    keys = (key,) if isinstance(key, str) else tuple(key)
    encoded = [value.encode('utf-8') for value in keys]
    storage = [ct.create_string_buffer(value) for value in encoded]
    key_buffer = (_Key * len(keys))(*(_Key(ct.cast(value, ct.POINTER(ct.c_char)), len(encoded[index]))
                                    for index, value in enumerate(storage)))
    shape, buffers, _ = _inputs((temperature, pressure), coerce=True)
    output = np.empty((len(keys),) + shape, dtype=np.float64)
    form = 0 if scalar else 1 if isinstance(key, str) else 2
    _call('sco2_pt', form, key_buffer, len(keys), _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size,
          _pointer(output), output.size)
    if scalar:
        return float(output[0])
    if not keys and not buffers[0].size:
        # The original empty tuple path fails at this shape operation.
        output.reshape(-1, 0)
    return output[0] if isinstance(key, str) else output


def sco2_hp(enthalpy, pressure, *, scalar=False):
    shape, buffers, _ = _inputs((enthalpy, pressure), coerce=True)
    output = np.empty(shape, dtype=np.float64)
    if scalar:
        _call('sco2_hp_scalar', float(buffers[0][0]), float(buffers[1][0]), _pointer(output), output.size)
        return float(output)
    _call('sco2_hp', _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size, _pointer(output), output.size)
    return output


def nu_inputs(route, re, *, pr=None, cell=None, diameter=None, re_floor=10.0):
    if route in (0, 1, 4):
        original = np.asarray(re, dtype=np.float64)
        re = float(original) if route == 0 and original.ndim == 0 else original
    if route == 4:
        shape, buffers, inputs = _inputs((re, pr, cell, diameter), coerce=True)
        floor = _Input()
    elif route == 1:
        shape, buffers, paired = _inputs((re, re_floor), ufunc_shapes=True)
        inputs, floor = [paired[0], _Input(), _Input(), _Input()], paired[1]
    else:
        shape, buffers, inputs = _inputs((re,))
        inputs += [_Input(), _Input(), _Input()]
        floor = _Input()
    result, extrema = _Result(buffers[0].size), np.empty(4, dtype=np.float64)
    _call('nu_inputs', route, *inputs, floor, result.output, _pointer(extrema), extrema.size)
    return result.restore(shape), extrema


def nusselt(route, topology, re, pr, cell=None, diameter=None, *, alpha=1.0):
    values = (re, pr) if route == 2 else (re, pr, cell, diameter)
    shape, buffers, inputs = _inputs(values, coerce=route == 4)
    if route == 2:
        inputs += [_Input(), _Input()]
    result = _Result(buffers[0].size)
    _call('nu', route, topology, *inputs, _scalar(alpha), result.output)
    return result.restore(shape)


def roughness(quantity, first=None, second=None):
    if quantity == 5:
        result = _Result(1)
        _call('roughness', quantity, _Input(), _Input(), result.output)
        return result.restore(())
    if quantity in (0, 1, 3):
        first = np.asarray(first, dtype=np.float64)
    values = (first, second) if quantity in (1, 2, 3) else (first,)
    shape, buffers, inputs = _inputs(values)
    if len(inputs) == 1:
        inputs.append(_Input())
    result = _Result(buffers[0].size)
    _call('roughness', quantity, *inputs, result.output)
    return result.restore(shape)
