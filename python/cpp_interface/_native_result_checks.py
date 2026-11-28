"""Adapt numerical check inputs to the independent result library."""
import ctypes as ct
import math

import numpy as np

from tm1.run_control import run_warnings

from . import _native_result as native

_Array = native._Array
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
    return array.ctypes.data_as(_DoubleP) if array.size else None


def collect_range(values, lower, upper):
    packed = native.array(values)
    return _output('collect_range', [_Array, _Double, _Double], (packed.raw, lower, upper), _RangeSample)


def record_range(source, values, bounds, *, label, quantity, unit):
    """Record a model range with the native result collector."""
    return run_warnings.record_range(source, values, bounds, label=label, quantity=quantity,
                                     unit=unit, collect=collect_range)


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
    packed = native.array(values)
    if not packed.owner.size:
        return True
    result = _output('array_checks', [_Array], (packed.raw,), _ArrayChecks)
    return bool(result.all_finite)


def all_zero(values):
    packed = native.array(values)
    if not packed.owner.size:
        return True
    result = _output('array_checks', [_Array], (packed.raw,), _ArrayChecks)
    return bool(result.all_zero)


def strict_certificate(active_b, ratios, source_a, source_b):
    values = (_Double * 4)(*ratios)
    result = _output('strict_certificate', [_UInt, _DoubleP, _Size, _Double, _Double],
                     (int(active_b), values, 4, source_a, source_b), _StrictValues)
    return dict(strict=tuple(bool(value) for value in result.strict), source_pass=bool(result.source_pass),
                source_residual=result.source_residual, source_normalization=result.source_normalization,
                epsilon_ltne=result.epsilon_ltne)


def energy_ratio(ratio, tolerance):
    ratio_value = native.scalar(ratio)
    tolerance_value = native.scalar(tolerance)
    if not math.isfinite(ratio_value) or not math.isfinite(tolerance_value):
        return False
    result = _output('energy_ratio', [_Double, _Double], (ratio_value, tolerance_value), _UInt)
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
    packed = native.array(values)
    buffer = np.empty(packed.owner.size, dtype=np.float64)
    _call(name, [_Array, *([_Double] * len(scalars)), _DoubleP, _Size],
          packed.raw, *scalars, _pointer(buffer), buffer.size)
    return buffer.reshape(packed.owner.shape)


def field_temperature_floor(temperature):
    return _field_output('field_temperature_floor', temperature)


def field_sound_speed(temperature, gamma, gas_constant):
    return _field_output('field_sound_speed', temperature, (gamma, gas_constant))


def field_mach_max(speed, sound):
    left, right = native.array(speed), native.array(sound)
    return _output('field_mach_max', [_Array, _Array], (left.raw, right.raw), _Double).value


def pressure_flags(pressure, floor, allowance):
    result = _output('pressure_flags', [_Double, _Double, _Double],
                     (native.scalar(pressure), native.scalar(floor), native.scalar(allowance)), _UInt)
    return int(result.value)


def mach_limit_flags(mach, limit):
    mach_value = native.scalar(mach)
    if not math.isfinite(mach_value):
        return 1
    if isinstance(limit, np.ndarray) and limit.ndim:
        packed = native.array(limit)
        result = _output('mach_limit_array_flags', [_Double, _Array],
                         (mach_value, packed.raw), _UInt)
        if packed.owner.size != 1:
            bool(np.empty(packed.owner.shape, dtype=bool))
        return int(result.value)
    result = _output('mach_limit_flags', [_Double, _Double],
                     (mach_value, native.scalar(limit)), _UInt)
    return int(result.value)


def _box_shape(owners):
    try:
        return np.broadcast_shapes(*(owner.owner.shape for owner in owners))
    except ValueError:
        # The native stage reports shape errors after its earlier arithmetic.
        return (0,)


def _box_array_call(name, values):
    owners = [native.array(value) for value in values]
    shape = _box_shape(owners)
    output = np.empty(shape, dtype=np.float64)
    target = native.array(output)
    _call(name, [_Array] * len(owners) + [ct.POINTER(_Array)],
          *(owner.raw for owner in owners), ct.byref(target.raw))
    return output


def _has_array_operand(values):
    return any(isinstance(value, (np.ndarray, list, tuple)) and np.ndim(value) > 0 for value in values)


def box_density_length(density, length):
    values = (density, length)
    if _has_array_operand(values):
        return _box_array_call('box_density_length_array', values)
    result = _output('box_density_length', [_Double] * 2,
                     (native.scalar(density), native.scalar(length)), _Double)
    return result.value


def box_bulk_mass(density_length, height, depth):
    values = (density_length, height, depth)
    if _has_array_operand(values):
        return _box_array_call('box_bulk_mass_array', values)
    result = _output('box_bulk_mass', [_Double] * 3,
                     (native.scalar(density_length), native.scalar(height), native.scalar(depth)), _Double)
    return result.value


def box_solid_mass(bulk_mass, epsilon):
    values = (bulk_mass, epsilon)
    if _has_array_operand(values):
        return _box_array_call('box_solid_mass_array', values)
    result = _output('box_solid_mass', [_Double] * 2,
                     (native.scalar(bulk_mass), native.scalar(epsilon)), _Double)
    return result.value
