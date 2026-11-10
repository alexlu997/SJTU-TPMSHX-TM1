"""Pack named metric requests for the independent result image."""
import ctypes as ct
from itertools import zip_longest
import warnings

import numpy as np

from . import _native_result as native

_AP = ct.POINTER(native._Array)
_SP = ct.POINTER(native._Scalar)
_DP = ct.POINTER(ct.c_double)
_UP = ct.POINTER(native._UInt)


def _call(name, types, *args):
    native.call('tpmshx_result_' + name + '_v1', types, *args)


def _packed(values):
    owners = [native.array(value) for value in values]
    return owners, (native._Array * len(owners))(*(item.raw for item in owners))


def _output(shape, dtype, template):
    return np.empty_like(np.asarray(template), dtype=dtype, shape=shape, order='K', subok=False)


def _shape(*values):
    shape = ()
    for value in values:
        result = []
        for left, right in zip_longest(reversed(shape), reversed(np.shape(value)), fillvalue=1):
            if left != right and left != 1 and right != 1:
                # The named native operation owns its original shape error.
                return ()
            result.append(right if left == 1 else left)
        shape = tuple(reversed(result))
    return shape


def _array_call(name, values, shape, dtype):
    inputs = [native.array(value) for value in values]
    template = max(values, key=lambda value: np.ndim(value))
    output = _output(shape, dtype, template)
    target = native.array(output)
    _call(name, [_AP] * (len(inputs) + 1), *(ct.byref(item.raw) for item in inputs), ct.byref(target.raw))
    return output[()] if not shape else output


def pressure_ratio(first, second):
    dtype = np.result_type(first, second)
    if dtype.kind in 'biu':
        dtype = np.dtype('float64')
    return _array_call('pressure_ratio', (first, second), _shape(first, second), dtype)


def pressure_face(first, second, ratio):
    shape = _shape(ratio, first, second)
    return _array_call('pressure_face', (first, second, ratio), shape, np.result_type(first, second, ratio))


def capacity_porosity(epsilon, split):
    source, factor = native.array(epsilon), native.array(split)
    output = _output(_shape(epsilon, split), np.result_type(epsilon, split), epsilon)
    target = native.array(output)
    _call('capacity_porosity', [_AP, _AP, _AP], ct.byref(source.raw), ct.byref(factor.raw), ct.byref(target.raw))
    return output[()] if not output.ndim else output


def capacity_split(split, cold):
    if not cold:
        return split
    if np.ndim(split):
        return _array_call('capacity_split_field', (split,), np.shape(split), np.result_type(1, split))
    if native.integer_product_requires_python((split,)):
        return 1 - split
    source, output = native.scalar(split), native._Scalar()
    _call('capacity_split', [_SP, native._UInt, _SP], ct.byref(source), int(cold), ct.byref(output))
    return native.restore_scalar(output)


def _valid(name, values):
    source, output = native.array(values), native._UInt()
    _call(name, [_AP, _UP], ct.byref(source.raw), ct.byref(output))
    return bool(output.value)


def port_width_valid(values):
    return _valid('port_width_valid', values)


def port_opening_valid(values):
    return _valid('port_opening_valid', values)


def port_weights(dx, dz, inlet, outlet):
    inputs = [native.array(value) for value in (dx, dz, inlet, outlet)]
    shape = (len(dx), len(dz))
    area_dtype = np.result_type(dx, dz)
    wi = np.empty(shape, dtype=np.result_type(inlet, area_dtype))
    wo = np.empty(shape, dtype=np.result_type(outlet, area_dtype))
    outputs = [native.array(value) for value in (wi, wo)]
    _call('port_weights', [_AP] * 6, *(ct.byref(item.raw) for item in inputs + outputs))
    return wi, wo


def _double_arrays(name, values):
    sources = [native.array(value) for value in values]
    output = ct.c_double()
    _call(name, [_AP] * len(sources) + [_DP], *(ct.byref(item.raw) for item in sources), ct.byref(output))
    return output.value


def weighted_mean(values, weights):
    return _double_arrays('weighted_mean', (values, weights))


def capacity_duty(inlet, outlet, inlet_temperature, outlet_temperature):
    inlet_owners, incoming = _packed(inlet)
    outlet_owners, outgoing = _packed(outlet)
    tin, tout = native.array(inlet_temperature), native.array(outlet_temperature)
    output = ct.c_double()
    _call('capacity_duty', [_AP, _AP, _AP, _AP, _DP], incoming, outgoing,
          ct.byref(tin.raw), ct.byref(tout.raw), ct.byref(output))
    return output.value


def outlet_temperature_2d(temperature, mass, opening, reverse):
    sources = [native.array(value) for value in (temperature, mass, opening)]
    output = ct.c_double()
    _call('outlet_temperature_2d', [_AP, _AP, _AP, native._UInt, _DP],
          *(ct.byref(item.raw) for item in sources), int(reverse), ct.byref(output))
    return output.value


def outlet_temperature_3d(temperature, mass, reverse):
    sources = [native.array(value) for value in (temperature, mass)]
    output = ct.c_double()
    _call('outlet_temperature_3d', [_AP, _AP, native._UInt, _DP],
          *(ct.byref(item.raw) for item in sources), int(reverse), ct.byref(output))
    return output.value


def boundary_enthalpy_duty(adjacent, mass, inlet_h):
    adjacent_owners, h = _packed(adjacent)
    mass_owners, flow = _packed(mass)
    inlet, output = native.scalar(inlet_h), ct.c_double()
    _call('boundary_enthalpy_duty', [_AP, _AP, _SP, _DP], h, flow, ct.byref(inlet), ct.byref(output))
    return output.value


def plane_duty(faces):
    owners, packed = _packed(faces)
    output = ct.c_double()
    _call('plane_duty', [_AP, native._Size, _DP], packed, len(owners), ct.byref(output))
    return output.value


def staggered_power_duty_2d(faces):
    owners, packed = _packed(faces)
    output = ct.c_double()
    _call('staggered_power_duty_2d', [_AP, _DP], packed, ct.byref(output))
    return output.value


def boundary_mass(faces, dimension):
    owners, packed = _packed(faces)
    output = (ct.c_double * 2)()
    _call('boundary_mass_' + str(dimension) + 'd', [_AP, _DP], packed, output)
    return tuple(output)


def solid_mass(epsilon, density, widths):
    source, factor = native.array(epsilon), native.array(density)
    grid = [native.array(value) for value in widths]
    output = ct.c_double()
    _call('solid_mass_' + str(len(widths)) + 'd', [_AP, _AP] + [_AP] * len(grid) + [_DP],
          ct.byref(source.raw), ct.byref(factor.raw), *(ct.byref(item.raw) for item in grid), ct.byref(output))
    return output.value


def outlet_mean(plane):
    if np.size(plane) == 0:
        warnings.warn('Mean of empty slice', RuntimeWarning, stacklevel=2)
    return _double_arrays('outlet_mean', (plane,))


def capture_area(dx, dy):
    return _double_arrays('capture_area', (dx, dy))


def capture_area_weights(dx, dy):
    return _array_call('capture_area_weights', (dx, dy),
                       (np.size(dx), np.size(dy)), np.result_type(dx, dy))


def duty_magnitude(duty):
    output = ct.c_double()
    _call('duty_magnitude', [ct.c_double, _DP], duty, ct.byref(output))
    return output.value


def _double_pair(name, first, second):
    output = ct.c_double()
    _call(name, [ct.c_double, ct.c_double, _DP], first, second, ct.byref(output))
    return output.value


def mass_imbalance(inlet, outlet):
    return _double_pair('mass_imbalance', inlet, outlet)


def full_energy_imbalance(first, second):
    return _double_pair('full_energy_imbalance', first, second)


def richardson_duty(fine, coarse):
    return _double_pair('richardson_duty', fine, coarse)


def _scalar_pair(name, first, second):
    a, b, output = native.scalar(first), native.scalar(second), native._Scalar()
    _call(name, [_SP, _SP, _SP], ct.byref(a), ct.byref(b), ct.byref(output))
    return native.restore_scalar(output)


def pressure_difference(first, second):
    return _metric_pair('pressure_difference', first, second)


def absolute_outlet_pressure(outlet, reference):
    return _scalar_pair('absolute_outlet_pressure', outlet, reference)


def quick_energy_imbalance(first, second):
    return _metric_pair('quick_energy_imbalance', first, second, division=True)


def quick_capacity_product(mass, cp):
    return _metric_pair('quick_capacity_product', mass, cp)


def quick_temperature_difference(inlet, outlet):
    if np.ndim(inlet):
        source = native.array(inlet)
        output = _output(np.shape(inlet), np.result_type(inlet, outlet), inlet)
        target = native.array(output)
        _call('quick_temperature_difference_field', [_AP, ct.c_double, _AP],
              ct.byref(source.raw), outlet, ct.byref(target.raw))
        return output
    value, output = native.scalar(inlet), native._Scalar()
    _call('quick_temperature_difference', [_SP, ct.c_double, _SP], ct.byref(value), outlet, ct.byref(output))
    return native.restore_scalar(output)


def quick_duty_from_capacity(capacity, delta, cold):
    if np.ndim(capacity) or np.ndim(delta):
        owners = [native.array(value) for value in (capacity, delta)]
        output = _output(_shape(capacity, delta), np.result_type(capacity, delta),
                         capacity if np.ndim(capacity) else delta)
        target = native.array(output)
        _call('quick_duty_from_capacity_field', [_AP, _AP, native._UInt, _AP],
              *(ct.byref(item.raw) for item in owners), int(cold), ct.byref(target.raw))
        return output
    a, b, output = native.scalar(capacity), native.scalar(delta), native._Scalar()
    _call('quick_duty_from_capacity', [_SP, _SP, native._UInt, _SP],
          ct.byref(a), ct.byref(b), int(cold), ct.byref(output))
    return native.restore_scalar(output)


def quick_reynolds_flow(rho, velocity):
    return _metric_pair('quick_reynolds_flow', rho, velocity)


def quick_reynolds_length(flow, diameter):
    return _metric_pair('quick_reynolds_length', flow, diameter)


def quick_reynolds_quotient(numerator, mu):
    return _metric_pair('quick_reynolds_quotient', numerator, mu, division=True)


def _metric_pair(name, first, second, *, division=False):
    if not (np.ndim(first) or np.ndim(second)):
        return _scalar_pair(name, first, second)
    dtype = np.result_type(first, second)
    if division and dtype.kind in 'biu':
        dtype = np.dtype('float64')
    return _array_call(name + '_field', (first, second), _shape(first, second), dtype)
