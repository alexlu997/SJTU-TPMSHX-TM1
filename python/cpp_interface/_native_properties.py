"""Adapt property data and error policy for the native preparation library."""
import ctypes as ct
from collections import namedtuple
import sys
import warnings

import numpy as np

from ._native_values import geometry_topology, real_scalar
from ._native_diagnostics import native_error
from .stage_libraries import preparation_library


_Size = ct.c_size_t
_Uint = ct.c_uint32
_DoubleP = ct.POINTER(ct.c_double)
_UintP = ct.POINTER(_Uint)
_EVENTS = 32
GEOMETRY_CACHE, CO2_CACHE, SCO2_CACHE = range(3)


class _Input(ct.Structure):
    _fields_ = [('values', _DoubleP), ('count', _Size)]


class _Output(ct.Structure):
    _fields_ = [('values', _DoubleP), ('count', _Size),
                ('events', _UintP), ('event_capacity', _Size), ('event_count', ct.POINTER(_Size))]


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
    'cached_co2': [ct.c_double, ct.c_double, _DoubleP, _Size, ct.POINTER(_Size)],
    'cached_sco2': [_Key, ct.c_double, ct.c_double, _DoubleP],
    'cached_geometry': [_Uint, ct.c_double, ct.c_double, _Size, _DoubleP, _Size],
    'co2_pt': [_DoubleP, _DoubleP, _Size, _UintP, _Size, _DoubleP, _Size, ct.POINTER(_Size)],
    'sco2_validate': [_DoubleP, _Size, _DoubleP, _Size],
    'sco2_pt': [_Uint, ct.POINTER(_Key), _Size, _DoubleP, _DoubleP, _Size, _DoubleP, _Size],
    'sco2_hp_scalar': [ct.c_double, ct.c_double, _DoubleP, _Size],
    'sco2_hp': [_DoubleP, _DoubleP, _Size, _DoubleP, _Size],
    'nu_inputs': [_Uint, _Input, _Input, _Input, _Input, _Input, _Output, _DoubleP, _Size],
    'nu': [_Uint, _Uint, _Input, _Input, _Input, _Input, ct.c_double, _Output],
    'roughness': [_Uint, _Input, _Input, _Output],
    'reynolds': [_Input, _Input, _Input, _Input, _Output],
    'prandtl': [_Input, _Input, _Input, _Output],
    'surface_transfer': [_Input, _Input, _Input, _Output],
    'inlet_re_pr': [_Input] * 6 + [_Output] * 2,
    'inlet_transfer': [_Input] * 5 + [_Output] * 3,
    'volumetric_transfer': [_Input, _Input, _Output],
    'pore_conductivity': [_Input, _Input, _Output],
}


def _function(owner, name):
    version = 2 if name == 'co2_pt' else 1
    return owner.bind(f'tpmshx_preparation_{name}_v{version}',
                      _SIGNATURES[name] + [ct.POINTER(_Failure), ct.POINTER(ct.c_char), _Size])


def _call(name, *arguments, geometry=None):
    owner = preparation_library.get()
    failure, error = _Failure(), ct.create_string_buffer(4096)
    function = _function(owner, name)
    cause = _Size(-1)
    if name in ('cached_co2', 'co2_pt'):
        arguments = (*arguments, ct.byref(cause))
    status = function(*arguments, ct.byref(failure), error, len(error))
    if not status:
        return
    _floating_events(failure.fp.events[:failure.fp.event_count])
    text = error.value.decode('utf-8', errors='replace')
    if geometry is not None and status == 1 and failure.reason:
        raise_geometry_error(function.__name__, failure.reason, *geometry, text)
    problem = native_error('preparation', function.__name__, status, text,
                           cause=failure.fp.python_cause, events=tuple(failure.fp.events[:failure.fp.event_count]))
    if status in (10, 11, 12):
        state = StateError(status, text, failure)
        state.diagnostic = problem.diagnostic
        state.native_cause = (error.value[cause.value:].decode('utf-8', errors='replace')
                              if cause.value != _Size(-1).value else text)
        raise state
    raise problem


def _pointer(values):
    return values.ctypes.data_as(_DoubleP)


def _operand(value):
    """Normalize one real property operand; NaN and Inf propagate."""
    if np.ndim(value) == 0:
        return np.asarray(real_scalar(value, allow_nonfinite=True))
    array = np.asarray(value)
    if array.dtype.kind not in 'fiu':
        raise TypeError(f'property operands must contain real numbers, got {array.dtype}')
    return array


def _ufunc_shape_error(*shapes):
    text = ' '.join('(' + ','.join(map(str, shape)) + (',' if len(shape) == 1 else '') + ')'
                    for shape in shapes)
    return ValueError(f'operands could not be broadcast together with shapes {text} ')


def _inputs(values, *, ufunc_shapes=False):
    arrays = [_operand(value) for value in values]
    try:
        broadcast = np.broadcast_arrays(*arrays)
    except ValueError:
        if ufunc_shapes:
            raise _ufunc_shape_error(*(item.shape for item in arrays)) from None
        raise
    buffers = [np.ascontiguousarray(value.reshape(-1), dtype=np.float64) for value in broadcast]
    inputs = [_Input(_pointer(buffer), buffer.size) for buffer in buffers]
    return broadcast[0].shape, buffers, inputs


class _Result:
    def __init__(self, count):
        self.values = np.empty(count, dtype=np.float64)
        self.events = np.zeros(_EVENTS, dtype=np.uint32)
        self.event_count = _Size()
        self.output = _Output(_pointer(self.values), count, self.events.ctypes.data_as(_UintP), _EVENTS,
                              ct.pointer(self.event_count))

    def restore(self, shape):
        _floating_events(self.events[:self.event_count.value])
        result = self.values.reshape(shape)
        return result if shape else float(result[()])


_OPERATIONS = {1: 'add', 2: 'subtract', 3: 'multiply', 4: 'divide',
               5: 'power', 6: 'log', 7: 'exp', 9: 'log10'}
_FLAGS = ((2, 'divide', 'divide by zero'), (4, 'over', 'overflow'),
          (8, 'under', 'underflow'), (1, 'invalid', 'invalid value'))


def _floating_events(events, *, warn=None):
    """Replay ordered native FP events with the NumPy 'ignore', 'warn', 'raise' and 'print' modes."""
    policy = np.geterr()
    for encoded in events:
        value = int(encoded)
        if not value:
            continue
        operation = _OPERATIONS.get((value >> 8) & 255, 'operation')
        for flag, category, label in _FLAGS:
            mode = policy[category]
            if not value & flag or mode not in ('warn', 'raise', 'print'):
                continue
            text = f'{label} encountered in {operation}'
            if mode == 'warn':
                if warn is None:
                    warnings.warn(text, RuntimeWarning, stacklevel=4)
                else:
                    warn(text)
            elif mode == 'raise':
                raise FloatingPointError(text)
            else:
                print('Warning: ' + text, file=sys.stderr)


def empirical(getter, temperature, pressure=101325.0):
    values = (temperature, pressure) if getter == 2 else (temperature,)
    shape, buffers, inputs = _inputs(values)
    result = _Result(1 if getter == 7 else buffers[0].size)
    _call('empirical', getter, inputs[0], inputs[1] if getter == 2 else _Input(), result.output)
    return result.restore(()) if getter == 7 else result.restore(shape)


def _derived(name, values, count):
    shape, buffers, inputs = _inputs(values)
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
    shape, buffers, _ = _inputs((temperature, pressure))
    _call(name, _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size)
    return shape, buffers


_CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')


class _Info(ct.Structure):
    _fields_ = [(name, _Size) for name in _CacheInfo._fields]


def cache_controls(cache_id):
    """Attach the cache controls of the selected preparation image."""
    def info():
        result, error = _Info(), ct.create_string_buffer(256)
        call = preparation_library.get().bind('tpmshx_preparation_read_cache_info_v1',
            [_Uint, ct.POINTER(_Info), ct.POINTER(ct.c_char), _Size])
        status = call(cache_id, ct.byref(result), error, len(error))
        if status:
            raise native_error('preparation', call.__name__, status, error.value.decode('utf-8'))
        return _CacheInfo(*(getattr(result, field) for field in _CacheInfo._fields))

    def clear():
        error = ct.create_string_buffer(256)
        call = preparation_library.get().bind('tpmshx_preparation_clear_cache_v1',
            [_Uint, ct.POINTER(ct.c_char), _Size])
        status = call(cache_id, error, len(error))
        if status:
            raise native_error('preparation', call.__name__, status, error.value.decode('utf-8'))

    def attach(function):
        function.cache_info = info
        function.cache_clear = clear
        function.cache_parameters = lambda: {'maxsize': info().maxsize, 'typed': False}
        return function
    return attach


def raise_geometry_error(operation, reason, topology, cell, wall, text):
    evidence = dict(topology=topology, L_cell_mm=float(cell), t_wall_mm=float(wall),
                    reason={1: 'cell', 2: 'wall', 3: 'no_pore', 4: 'degenerate'}[reason])
    if reason == 1:
        message = f'L_mm must be positive, got {cell}'
    elif reason == 2:
        message = f't_mm must be positive, got {wall}'
    elif reason == 3:
        message = f'Wall thickness t={wall}mm >= L={cell}mm, no pore space'
    else:
        message = (f'Degenerate TPMS geometry: {topology} L={cell}mm t={wall}mm '
                   'has no usable pore space. Reduce t or increase L.')
        cause = native_error('preparation', operation, 1, text, **evidence)
        raise native_error('preparation', operation, 1, message, causes=(cause.diagnostic,), **evidence) from cause
    raise native_error('preparation', operation, 1, message, **evidence)


def cached_geometry(topology, cell, wall, resolution):
    output = np.empty(5, dtype=np.float64)
    _call('cached_geometry', geometry_topology(topology), real_scalar(cell, allow_nonfinite=True),
          real_scalar(wall, allow_nonfinite=True), resolution, _pointer(output), output.size,
          geometry=(topology, cell, wall))
    return output


def cached_co2(temperature, pressure):
    output = np.empty(5, dtype=np.float64)
    _call('cached_co2', temperature, pressure, _pointer(output), output.size)
    return tuple(float(value) for value in output)


def cached_sco2(key, temperature, pressure):
    encoded = key.encode('utf-8')
    storage = ct.create_string_buffer(encoded)
    result = ct.c_double()
    _call('cached_sco2', _Key(ct.cast(storage, ct.POINTER(ct.c_char)), len(encoded)),
          temperature, pressure, ct.byref(result))
    return result.value


def co2_pt(keys, temperature, pressure):
    shape, buffers, _ = _inputs((temperature, pressure))
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
        from tm1.model_configs.model_parameters import load_model_parameters
        lo, hi = load_model_parameters()['sco2']['pressure_range_Pa']
        raise ValueError(f'sCO2 pressure must be within {lo/1e6:g}..{hi/1e6:g} MPa') from None


def sco2_pt(key, temperature, pressure):
    keys = (key,) if isinstance(key, str) else tuple(key)
    encoded = [value.encode('utf-8') for value in keys]
    storage = [ct.create_string_buffer(value) for value in encoded]
    key_buffer = (_Key * len(keys))(*(_Key(ct.cast(value, ct.POINTER(ct.c_char)), len(encoded[index]))
                                    for index, value in enumerate(storage)))
    shape, buffers, _ = _inputs((temperature, pressure))
    output = np.empty((len(keys),) + shape, dtype=np.float64)
    form = 1 if isinstance(key, str) else 2
    _call('sco2_pt', form, key_buffer, len(keys), _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size,
          _pointer(output), output.size)
    if not keys and not buffers[0].size:
        # The original empty tuple path fails at this shape operation.
        output.reshape(-1, 0)
    return output[0] if isinstance(key, str) else output


def sco2_hp(enthalpy, pressure, *, scalar=False):
    shape, buffers, _ = _inputs((enthalpy, pressure))
    output = np.empty(shape, dtype=np.float64)
    if scalar:
        _call('sco2_hp_scalar', float(buffers[0][0]), float(buffers[1][0]), _pointer(output), output.size)
        return float(output)
    _call('sco2_hp', _pointer(buffers[0]), _pointer(buffers[1]), buffers[0].size, _pointer(output), output.size)
    return output


def nu_inputs(route, re, *, pr=None, cell=None, diameter=None, re_floor=10.0):
    if route == 4:
        shape, buffers, inputs = _inputs((re, pr, cell, diameter))
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
    shape, buffers, inputs = _inputs(values)
    if route == 2:
        inputs += [_Input(), _Input()]
    result = _Result(buffers[0].size)
    _call('nu', route, topology, *inputs, real_scalar(alpha, name='alpha', allow_nonfinite=True), result.output)
    return result.restore(shape)


def roughness(quantity, first=None, second=None):
    if quantity == 5:
        result = _Result(1)
        _call('roughness', quantity, _Input(), _Input(), result.output)
        return result.restore(())
    values = (first, second) if quantity in (1, 2, 3) else (first,)
    shape, buffers, inputs = _inputs(values)
    if len(inputs) == 1:
        inputs.append(_Input())
    result = _Result(buffers[0].size)
    _call('roughness', quantity, *inputs, result.output)
    return result.restore(shape)
