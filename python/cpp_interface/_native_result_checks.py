"""Adapt numerical check inputs to the independent result library."""
import ctypes as ct
import math

import numpy as np

from . import _native_result as native

_Array, _Scalar = native._Array, native._Scalar
_Size, _UInt = native._Size, native._UInt
_Double = ct.c_double
_DoubleP = ct.POINTER(_Double)


class _RangeSample(ct.Structure):
    _fields_ = [('minimum', _Double), ('maximum', _Double),
                ('minimum_index', _Size), ('maximum_index', _Size),
                ('low', _Size), ('high', _Size), ('size', _Size), ('nonfinite', _Size),
                ('have_finite', _UInt)]


class _ScalarSamples(ct.Structure):
    _fields_ = [('indices', _Size * 8), ('count', _Size)]


class _SourceBounds(ct.Structure):
    _fields_ = [('lower', _Double), ('upper', _Double), ('allowance_fraction', _Double), ('positive', _UInt)]


class _RangeDecision(ct.Structure):
    _fields_ = [('relative_extrapolation', _Double), ('numerical_case', _UInt), ('relative_present', _UInt)]


class _ArrayChecks(ct.Structure):
    _fields_ = [('all_finite', _UInt), ('all_zero', _UInt)]


class _StrictValues(ct.Structure):
    _fields_ = [('strict', _UInt * 4), ('source_pass', _UInt),
                ('source_residual', _Double), ('source_normalization', _Double), ('epsilon_ltne', _Double)]


def _call(name, signature, *arguments):
    native.call('tpmshx_result_' + name + '_v1', signature, *arguments)


def _output(name, signature, arguments, kind):
    result = kind()
    _call(name, [*signature, ct.POINTER(kind)], *arguments, ct.byref(result))
    return result


def _pointer(array):
    return array.ctypes.data_as(_DoubleP)


def collect_range(values, lower, upper):
    packed = native.array(values)
    return _output('collect_range', [_Array, _Double, _Double], (packed.raw, lower, upper), _RangeSample)


def scalar_samples(values, lower, upper):
    packed = native.array(values)
    result = _output('scalar_samples', [_Array, _Double, _Double], (packed.raw, lower, upper), _ScalarSamples)
    return tuple(int(index) for index in result.indices[:result.count])


def parameter_bounds(lower, upper):
    output = (_Double * 2)()
    _call('parameter_bounds', [_Double, _Double, _DoubleP, _Size], lower, upper, output, 2)
    return tuple(output)


def source_bounds(lower, upper):
    result = _output('source_bounds', [_Double, _Double], (lower, upper), _SourceBounds)
    return (result.lower, result.upper), bool(result.positive), result.allowance_fraction


def range_values(lower, upper, minimum, maximum, hard):
    return _output('range_values', [_Double] * 4 + [_UInt],
                   (lower, upper, minimum, maximum, int(hard)), _RangeDecision)


def array_checks(values):
    packed = native.array(values)
    result = _output('array_checks', [_Array], (packed.raw,), _ArrayChecks)
    return bool(result.all_finite), bool(result.all_zero)


def all_finite(values):
    array = np.asarray(values)
    if array.dtype.kind not in 'biufc':
        # Non-numeric Python protocols remain outside the typed result ABI.
        return bool(np.all(np.isfinite(array)))
    if not array.size:
        return True
    return array_checks(array)[0]


def all_zero(values):
    array = np.asarray(values)
    if array.dtype.kind not in 'biufc':
        return bool(np.all(array == 0))
    if not array.size:
        return True
    return array_checks(array)[1]


def strict_certificate(active_b, ratios, source_a, source_b):
    values = (_Double * 4)(*ratios)
    result = _output('strict_certificate', [_UInt, _DoubleP, _Size, _Double, _Double],
                     (int(active_b), values, 4, source_a, source_b), _StrictValues)
    return dict(strict=tuple(bool(value) for value in result.strict), source_pass=bool(result.source_pass),
                source_residual=result.source_residual, source_normalization=result.source_normalization,
                epsilon_ltne=result.epsilon_ltne)


def _python_protocol(values):
    for value in values:
        if type(value) is int:
            if not -(1 << 63) <= value < (1 << 64):
                return True
        elif type(value) in (float, bool, complex):
            continue
        elif isinstance(value, (np.generic, np.ndarray)):
            if np.asarray(value).dtype.kind not in 'biufc':
                return True
        else:
            return True
    return False


def _scalar_operand(value):
    if isinstance(value, np.ndarray) and value.ndim:
        if value.size != 1:
            bool(value)
        return value.reshape(())[()]
    return value


def _math_float(value):
    if isinstance(value, float):
        return float.__float__(value)
    if not (hasattr(type(value), '__float__') or hasattr(type(value), '__index__')):
        raise TypeError(f'must be real number, not {type(value).__name__}')
    return float(value)


def energy_ratio(ratio, tolerance):
    if _python_protocol((ratio, tolerance)):
        return bool(math.isfinite(ratio) and math.isfinite(tolerance)
                    and 0. <= ratio <= tolerance and tolerance > 0.)
    if not all_finite(_math_float(ratio)):
        return False
    if not all_finite(_math_float(tolerance)):
        return False
    result = _output('energy_ratio', [_Scalar, _Scalar],
        (native.scalar(_scalar_operand(ratio)), native.scalar(_scalar_operand(tolerance))), _UInt)
    return bool(result.value)


def pressure_square(inlet):
    return _output('pressure_square', [_Double], (inlet,), _Double).value


def outlet_pressure_squared(square, gas_constant, temperature, drag, length):
    return _output('outlet_pressure_squared', [_Double] * 5,
                   (square, gas_constant, temperature, drag, length), _Double).value


def sound_speed(gamma, gas_constant, temperature):
    return _output('sound_speed', [_Double] * 3, (gamma, gas_constant, temperature), _Double).value


def mach_from_sound(speed, sound):
    return _output('mach_from_sound', [_Double] * 2, (speed, sound), _Double).value


def _field_output(name, values, scalars=()):
    array = np.asarray(values, dtype=np.float64)
    packed = native.array(array)
    buffer = np.empty(array.size, dtype=np.float64)
    _call(name, [_Array, *([_Double] * len(scalars)), _DoubleP, _Size],
          packed.raw, *scalars, _pointer(buffer), buffer.size)
    output = np.empty_like(array, order='K')
    output[...] = buffer.reshape(array.shape)
    return output


def field_temperature_floor(temperature):
    return _field_output('field_temperature_floor', temperature)


def field_sound_speed(temperature, gamma, gas_constant):
    return _field_output('field_sound_speed', temperature, (gamma, gas_constant))


def field_mach_max(speed, sound):
    left, right = native.array(speed), native.array(sound)
    return _output('field_mach_max', [_Array, _Array], (left.raw, right.raw), _Double).value


def pressure_flags(pressure, floor, allowance):
    if _python_protocol((pressure,)):
        return 1 if not np.isfinite(pressure) else 2 if pressure <= floor * (1. + allowance) else 0
    result = _output('pressure_flags', [_Scalar, _Double, _Double],
                     (native.scalar(_scalar_operand(pressure)), floor, allowance), _UInt)
    return int(result.value)


def mach_limit_flags(mach, limit):
    if not all_finite(mach):
        return 1
    if _python_protocol((mach, limit)):
        return 2 if mach >= limit else 0
    if isinstance(limit, np.ndarray) and limit.ndim:
        packed = native.array(limit)
        result = _output('mach_limit_array_flags', [_Scalar, _Array],
                         (native.scalar(_scalar_operand(mach)), packed.raw), _UInt)
        if limit.size != 1:
            bool(np.empty(limit.shape, dtype=bool))
        return int(result.value)
    result = _output('mach_limit_flags', [_Scalar, _Scalar],
                     (native.scalar(_scalar_operand(mach)), native.scalar(_scalar_operand(limit))), _UInt)
    return int(result.value)


def _product_template(first, second):
    dtype = np.result_type(first, second)
    if isinstance(first, (np.generic, np.ndarray)) or isinstance(second, (np.generic, np.ndarray)):
        return np.empty((), dtype=dtype)
    return 0j if dtype.kind == 'c' else 0. if dtype.kind == 'f' else 0


def _box_shape(values):
    try:
        return np.broadcast_shapes(*(np.shape(value) for value in values))
    except ValueError:
        # The native stage reports shape errors after its earlier arithmetic.
        return (0,)


def _box_array_call(name, values, dtype):
    owners = [native.array(value) for value in values]
    shape = _box_shape(values)
    template = max(values, key=np.ndim)
    output = np.empty_like(np.asarray(template), shape=shape, dtype=dtype, order='K', subok=False)
    target = native.array(output)
    _call(name, [_Array] * len(owners) + [ct.POINTER(_Array)],
          *(owner.raw for owner in owners), ct.byref(target.raw))
    return output


def box_density_length(density, length):
    values = (density, length)
    if _python_protocol(values) or native.integer_product_requires_python(values):
        # Python object and wide integer products have a separate data contract.
        return density * length
    if any(np.ndim(value) for value in values):
        return _box_array_call('box_density_length_array', values, np.result_type(*values))
    result = _output('box_density_length', [_Scalar] * 2, tuple(native.scalar(value) for value in values), _Scalar)
    return native.restore_scalar(result)


def box_bulk_mass(density_length, height, depth):
    values = (density_length, height, depth)
    if _python_protocol(values) or native.integer_product_requires_python(values):
        return density_length * height * depth
    if any(np.ndim(value) for value in values):
        prefix = _product_template(density_length, height)
        return _box_array_call('box_bulk_mass_array', values, np.result_type(prefix, depth))
    result = _output('box_bulk_mass', [_Scalar] * 3, tuple(native.scalar(value) for value in values), _Scalar)
    return native.restore_scalar(result)


def box_solid_mass(bulk_mass, epsilon):
    values = (bulk_mass, epsilon)
    if _python_protocol(values):
        return bulk_mass * (1. - epsilon)
    if any(np.ndim(value) for value in values):
        fraction = _product_template(1., epsilon)
        return _box_array_call('box_solid_mass_array', values, np.result_type(bulk_mass, fraction))
    result = _output('box_solid_mass', [_Scalar] * 2, tuple(native.scalar(value) for value in values), _Scalar)
    return native.restore_scalar(result)
