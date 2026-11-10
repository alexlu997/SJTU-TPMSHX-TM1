"""Pack fixed D-F, correction, and projection inputs for the native core."""
from __future__ import annotations

import ctypes as ct
import errno
import os
from functools import lru_cache

import numpy as np

from . import _native_grid, _native_preparation
from . import _native_properties as _properties
from ._native_properties import _EVENTS as _FP_EVENT_COUNT, _FPFailure

_D = ct.c_double
_U = ct.c_uint32
_S = ct.c_size_t
_DP = ct.POINTER(_D)
_IP = ct.POINTER(ct.c_int64)
_ERROR = [ct.POINTER(ct.c_char), _S]
_Scalar = _native_grid._Scalar


class _Pressure(ct.Structure):
    _fields_ = [('dP', _D), ('outlet_squared', _D), ('no_positive_outlet', _U),
                ('precision', _U), ('strong', _U), ('floating_events', _U * _FP_EVENT_COUNT)]


class _Selection(ct.Structure):
    _fields_ = [('branch', _U), ('campaign', _U), ('scope', _U), ('flags', _U),
                ('scale_K', _D), ('scale_F', _D), ('application_u', _D * 2),
                ('calibration_u', _D * 2), ('runtime_u', _D * 2)]


class _Summary(ct.Structure):
    _fields_ = [('minimum', _D), ('maximum', _D), ('scalar', _U)]


_SIGNATURES = {
    'fixed': [_U, _DP, _DP, _S, _DP, _S, _DP, _S],
    'incompressible': [_U, _D, _D, *([_Scalar] * 4), ct.POINTER(_Pressure), ct.POINTER(_FPFailure)],
    'compressible': [_U, _D, _D, *([_Scalar] * 5), _U, ct.POINTER(_Pressure), ct.POINTER(_FPFailure)],
    'pressure_gradient': [*([_properties._Input] * 5), _properties._Output, ct.POINTER(_FPFailure)],
    'correction_select': [_U, _U, _U, _DP, _S, _DP, _S, _DP, _S, _U, ct.POINTER(_Selection)],
    'correction_scales': [_U, ct.POINTER(_Selection), _DP, _DP, _S, _DP, _S, _DP, _S],
    'apply_scale': [_DP, _DP, _S, _U, _DP, _S],
    'summarize': [_DP, _S, _U, ct.POINTER(_Summary)],
    'co2_factors': [_DP, _S],
    'project_rows': [_S, _S, _DP, _DP, _S, _U, _U, _U, _U, _U, _S,
                     _DP, _S, _U, _DP, _S, _U, _DP, _S,
                     _DP, _S, _DP, _S, _IP, _S],
    'row_means': [_S, _S, _DP, _DP, _S, _U, _U, _DP, _S, _DP, _S],
}


@lru_cache(maxsize=1)
def _bindings(path):
    owner = _native_preparation._load_library(path)
    return {name: owner.bind(f'tpmshx_preparation_df_{name}_v1', [*args, *_ERROR])
            for name, args in _SIGNATURES.items()}


def _raise_status(status, error, cause=0):
    if status:
        message = error.value.decode('utf-8', errors='replace') or f'native preparation failed with code {status}'
        if status == 1:
            raise ValueError(message)
        if status == 2:
            raise MemoryError(message)
        if cause == 2:
            raise OverflowError(errno.ERANGE, os.strerror(errno.ERANGE))
        if cause:
            raise {1: ZeroDivisionError, 3: ValueError, 4: TypeError}[cause](message)
        if message == "Weights sum to zero, can't be normalized":
            raise ZeroDivisionError(message)
        raise RuntimeError(message)


def _call(name, *arguments):
    error = ct.create_string_buffer(2048)
    status = _bindings(_native_preparation._library().path)[name](*arguments, error, len(error))
    _raise_status(status,error)


def _pressure_failure(status,failure,error):
    if status:
        if failure.event_count > _FP_EVENT_COUNT or failure.python_cause > 4:
            raise RuntimeError('invalid native pressure failure diagnostics')
        _properties._floating_events(failure.events[:failure.event_count])
        _raise_status(status,error,failure.python_cause)


def _array(value):
    return np.ascontiguousarray(np.asarray(value, dtype=np.float64)).ravel()


def _ptr(value):
    return value.ctypes.data_as(_DP)


def _topology(value):
    return {'Diamond': 0, 'Gyroid': 1}[value]


def fixed(topology, lengths, walls):
    lengths, walls = np.asarray(lengths, dtype=np.float64), np.asarray(walls, dtype=np.float64)
    if lengths.shape != walls.shape:
        raise ValueError('fixed DF fields must have matching extents')
    shape = lengths.shape
    lengths, walls = _array(lengths), _array(walls)
    k, f = np.empty(shape, dtype=np.float64), np.empty(shape, dtype=np.float64)
    _call('fixed', _topology(topology), _ptr(lengths), _ptr(walls), lengths.size,
          _ptr(k), k.size, _ptr(f), f.size)
    return k, f


def pressure(topology, length, wall, *values, compressible=False, strict=False):
    try:
        length, wall = float(length), float(wall)
    except ValueError as failure:
        raise ValueError('geometry is outside the fixed sCO2 CFD grid: '
                         '4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm') from failure
    packed = [_native_grid._scalar(value[()] if isinstance(value, np.ndarray) and value.ndim == 0 else value)
              for value in values]
    output, failure, error = _Pressure(), _FPFailure(), ct.create_string_buffer(2048)
    name = 'compressible' if compressible else 'incompressible'
    arguments = [_topology(topology), length, wall, *packed]
    if compressible:
        arguments.append(int(bool(strict)))
    function = _bindings(_native_preparation._library().path)[name]
    status = function(*arguments,ct.byref(output),ct.byref(failure),error,len(error))
    # This decoder applies NumPy error policy; it evaluates no property formula.
    from ._native_properties import _floating_events
    _pressure_failure(status,failure,error)
    _floating_events(output.floating_events)
    result = values[2] if compressible and output.no_positive_outlet and not strict else (
        _native_grid._restore(_Scalar(output.dP, output.precision, output.strong)))
    if compressible:
        return result, output.outlet_squared, bool(output.no_positive_outlet)
    return result


def pressure_gradient(rho,mu,u,permeability,inertial):
    """Evaluate the original ordered gradient with supplied K/cF data."""
    shape, buffers, inputs = _properties._inputs((rho,mu,u,permeability,inertial))
    result, failure, error = _properties._Result(buffers[0].size), _FPFailure(), ct.create_string_buffer(2048)
    function = _bindings(_native_preparation._library().path)['pressure_gradient']
    status = function(*inputs,result.output,ct.byref(failure),error,len(error))
    _pressure_failure(status,failure,error)
    return result.restore(shape)


def selection(topology, fluid, lengths, walls, velocity=None, *, transfer=False):
    if transfer and (topology != 'Gyroid' or fluid not in ('air', 'water')):
        raise ValueError('HX trend extrapolation is limited to Gyroid air/water')
    if fluid not in ('air', 'water', 'sco2'):
        if transfer:
            raise ValueError('HX trend extrapolation is limited to Gyroid air/water')
        raise ValueError(f'no approved experiment calibration for fluid {fluid!r}')
    l, t = _array(lengths), _array(walls)
    output = _Selection()
    arguments = [_topology(topology), ('air', 'water', 'sco2').index(fluid), int(bool(transfer)),
                 _ptr(l), l.size, _ptr(t), t.size]
    # Native selection first checks geometry and can ignore a specimen's u.
    try:
        _call('correction_select', *arguments, None, 0, 0, ct.byref(output))
    except ValueError as failure:
        if not str(failure).endswith(' HX experiment calibration requires inlet velocity') or velocity is None:
            raise
        u = _array(velocity)
        try:
            _call('correction_select', *arguments, _ptr(u), u.size, 1, ct.byref(output))
        except ValueError as invalid:
            if str(invalid) != 'HX velocity outside application window':
                raise
            # The message keeps the original source-window and summary text.
            from sjtu_tpmshx.shared.configs.model_parameters import load_preparation_df_parameters
            lo, hi = load_preparation_df_parameters()['hx']['application_u_mps'][fluid][topology]
            raise ValueError(f'{fluid} HX experiment calibration requires {lo:.6g}<=u<='
                             f'{hi:.6g} m/s for {topology}; got {summary(velocity)}') from invalid
    return output


def scales(topology, selected, lengths, walls, velocity=None):
    if selected.branch:
        shape = np.broadcast(np.asarray(lengths), np.asarray(walls), np.asarray(velocity, dtype=float)).shape
    else:
        shape = np.broadcast(np.asarray(lengths, dtype=float), np.asarray(walls, dtype=float)).shape
    l, t = (_array(np.broadcast_to(value, shape)) for value in (lengths, walls))
    k, f = np.empty(shape), np.empty(shape)
    _call('correction_scales', _topology(topology), ct.byref(selected), _ptr(l), _ptr(t), l.size,
          _ptr(k), k.size, _ptr(f), f.size)
    return k, f[()] if not selected.branch and shape == () else f


def apply_scale(base, scale, *, prepared=False):
    base, scale = np.broadcast_arrays(np.asarray(base, dtype=float), np.asarray(scale, dtype=float))
    shape = base.shape
    b, s = _array(base), _array(scale)
    output = np.empty(shape)
    _call('apply_scale', _ptr(b), _ptr(s), b.size, int(bool(prepared)), _ptr(output), output.size)
    return output


def summary(value):
    value = np.asarray(value, dtype=float)
    array, result = _array(value), _Summary()
    _call('summarize', _ptr(array), array.size, int(value.ndim == 0 or value.size == 1), ct.byref(result))
    return result.minimum if result.scalar else {'min': result.minimum, 'max': result.maximum}


def co2_factors():
    output = np.empty(2)
    _call('co2_factors', _ptr(output), output.size)
    return float(output[0]), float(output[1])


def _precision(value):
    dtype = np.asarray(value).dtype
    return dtype.itemsize * 8 if dtype.kind == 'f' and dtype.itemsize in (2, 4, 8) else 64


def _column_major(value):
    # Keep the original reduction order before packing the values in C order.
    first, second = map(abs, value.strides)
    return int(0 < first < second)


def project_rows(lengths, walls, target_count, direction, widths=None, source_grid=None):
    l0, t0 = np.asarray(lengths), np.asarray(walls)
    if l0.ndim != 2 or l0.shape != t0.shape:
        raise ValueError('projection requires matching two-dimensional L/t fields')
    l, t = _array(l0), _array(t0)
    dx0, dy0 = (None, None) if source_grid is None else tuple(np.asarray(w) for w in source_grid)
    dx, dy = (_array([]) if w is None else _array(w) for w in (dx0, dy0))
    target = _array([]) if widths is None else _array(widths)
    lr, tr = np.empty(target_count), np.empty(target_count)
    indices = np.empty(target_count, dtype=np.int64)
    _call('project_rows', *l0.shape, _ptr(l), _ptr(t), l.size, _precision(l0), _precision(t0),
          _column_major(l0), _column_major(t0), direction, target_count,
          _ptr(dx), dx.size, _precision(dx0), _ptr(dy), dy.size, _precision(dy0), _ptr(target), target.size,
          _ptr(lr), lr.size, _ptr(tr), tr.size, indices.ctypes.data_as(_IP), indices.size)
    return lr, tr, indices


def row_means(permeability, inertial):
    permeability, inertial = np.asarray(permeability, dtype=float), np.asarray(inertial, dtype=float)
    if permeability.ndim != 2 or permeability.shape != inertial.shape:
        raise ValueError('DF row means require matching two-dimensional fields')
    k, f = _array(permeability), _array(inertial)
    kr, fr = np.empty(permeability.shape[1]), np.empty(permeability.shape[1])
    _call('row_means', *permeability.shape, _ptr(k), _ptr(f), k.size,
          _column_major(permeability), _column_major(inertial), _ptr(kr), kr.size, _ptr(fr), fr.size)
    return kr, fr
