"""Pack physical balance and selected zone data for the native result core."""
import ctypes as ct

import numpy as np

from . import _native_result as core


_D = ct.c_double
_AP = ct.POINTER(core._Array)
_SP = ct.POINTER(core._Scalar)


class _Norms(ct.Structure):
    _fields_ = [('signed_sum', _D), ('l1', _D), ('cell_max', _D), ('cell_count', core._Size)]


class _Mass(ct.Structure):
    _fields_ = [('residual', _Norms), ('inflow', _D), ('outflow', _D), ('scale', _D),
                ('relative_net', _D), ('relative_l1', _D), ('boundary_out', _D * 6),
                ('telescoping_error', _D), ('has_scale', core._UInt), ('reserved', core._UInt)]


class _Planes(ct.Structure):
    _fields_ = [('values', _D * 6), ('total', _D)]


class _EnergyPhase(ct.Structure):
    _fields_ = [('residual', _Norms), ('source_integral', _D),
                ('advective_out_sum', _D), ('diffusive_out_sum', _D)]


class _Energy(ct.Structure):
    _fields_ = [(name, _D) for name in (
        'boundary_out', 'source_integral', 'prescribed_b_power', 'net_external_in',
        'residual_sum', 'telescoping_error', 'scale', 'relative_external_imbalance')]
    _fields_ += [('l1_relative', _D * 3), ('cell_max_relative', _D * 3)]


def _call(name, argtypes, *arguments):
    return core.call(f'tpmshx_result_{name}_v1', argtypes, *arguments)


def norm_record(value):
    return dict(signed_sum=value.signed_sum, l1=value.l1,
                cell_max=value.cell_max, cell_count=value.cell_count)


def norms(value):
    owner, output = core.array(value), _Norms()
    _call('balance_norms', [_AP, ct.POINTER(_Norms)], ct.byref(owner.raw), ct.byref(output))
    return norm_record(output)


def mass(faces):
    owners = [core.array(face) for face in faces]
    inputs = (core._Array * len(owners))(*(owner.raw for owner in owners))
    output = _Mass()
    _call('balance_mass', [_AP, core._Size, ct.POINTER(_Mass)], inputs, len(owners), ct.byref(output))
    return output


def plane_sums(planes):
    owners = [core.array(plane) for plane in planes]
    inputs = (core._Array * len(owners))(*(owner.raw for owner in owners))
    output = _Planes()
    _call('balance_planes', [_AP, core._Size, ct.POINTER(_Planes)], inputs, len(owners), ct.byref(output))
    return output


def energy_totals(phases, reservoir):
    records = []
    for row in phases:
        values = row['residual']
        norms = _Norms(values['signed_sum'], values['l1'], values['cell_max'], values['cell_count'])
        records.append(_EnergyPhase(norms, row['source_integral'], row['advective_out_sum'], row['diffusive_out_sum']))
    inputs = (_EnergyPhase * len(records))(*records)
    output = _Energy()
    _call('balance_energy', [ct.POINTER(_EnergyPhase), core._Size, _D, ct.POINTER(_Energy)],
          inputs, len(records), reservoir, ct.byref(output))
    return output


def zone_mean(value, weights=None):
    owner, output = core.array(value), core._Scalar()
    weight = None if weights is None else core.array(weights)
    _call('zone_mean', [_AP, _AP, core._UInt, _SP], ct.byref(owner.raw),
          None if weight is None else ct.byref(weight.raw), int(weight is not None), ct.byref(output))
    return core.restore_scalar(output)


def _square_fused(dtype):
    dtype = np.dtype(dtype)
    if dtype.char not in ('F', 'D'):
        return 0
    info = np.lib.introspect.opt_func_info(func_name='^square$', signature='complex64|complex128')
    try:
        target = info['square'][dtype.char * 2]['current']
    except (KeyError, TypeError) as error:
        raise RuntimeError(f'NumPy did not report the active complex square loop: {info!r}') from error
    if target in ('X86_V3', 'baseline(NEON NEON_FP16 NEON_VFPV4 ASIMD)'):
        return 1
    # NumPy 2.5.4 CPU_DISPATCH_INFO_BASE_HIGH_CB_ adds baseline parentheses.
    # Source: meson_cpu/main_config.h.in, lines 305-307.
    if target in ('X86_V2', 'baseline(X86_V2)'):
        return 0
    raise RuntimeError(f'unsupported NumPy complex square target {target!r}: {info!r}')


def zone_std(value, weights=None):
    owner, output = core.array(value), core._Scalar()
    weight = None if weights is None else core.array(weights)
    fused = 0
    if weight is not None:
        dtype = owner.owner.dtype
        average = (np.result_type(dtype, weight.owner.dtype, np.float64) if dtype.kind in 'biu'
                   else np.result_type(dtype, weight.owner.dtype))
        centered = np.subtract.resolve_dtypes((dtype, average, None))[-1]
        fused = _square_fused(centered)
    _call('zone_std', [_AP, _AP, core._UInt, core._UInt, _SP], ct.byref(owner.raw),
          None if weight is None else ct.byref(weight.raw), int(weight is not None), fused, ct.byref(output))
    return core.restore_scalar(output)


def _zone_reduction(name, value):
    owner, output = core.array(value), core._Scalar()
    _call('zone_' + name, [_AP, _SP], ct.byref(owner.raw), ct.byref(output))
    return core.restore_scalar(output)


def zone_minimum(value):
    return _zone_reduction('minimum', value)


def zone_maximum(value):
    return _zone_reduction('maximum', value)


def zone_spread(value):
    return _zone_reduction('spread', value)


def zone_power_two(value):
    value = np.asarray(value)
    dtype = np.square.resolve_dtypes((value.dtype, None))[-1]
    output = np.empty(value.shape, dtype=dtype)
    owner, kind = core.array(value), core._Scalar()
    _call('zone_power_two', [_AP, core._UInt, ct.POINTER(ct.c_ubyte), core._Size, _SP],
          ct.byref(owner.raw), _square_fused(value.dtype),
          output.ctypes.data_as(ct.POINTER(ct.c_ubyte)), output.nbytes, ct.byref(kind))
    if np.asarray(core.restore_scalar(kind)).dtype != dtype:
        raise RuntimeError('native zone power dtype disagrees with the result interface')
    return output


def zone_speed_from_squared(u, v):
    u, v = np.asarray(u), np.asarray(v)
    total = np.add.resolve_dtypes((u.dtype, v.dtype, None))[-1]
    dtype = np.sqrt.resolve_dtypes((total, None))[-1]
    output = np.empty(u.shape, dtype=dtype)
    first_owner, second_owner, kind = core.array(u), core.array(v), core._Scalar()
    _call('zone_speed_from_squared', [_AP, _AP, ct.POINTER(ct.c_ubyte), core._Size, _SP],
          ct.byref(first_owner.raw), ct.byref(second_owner.raw),
          output.ctypes.data_as(ct.POINTER(ct.c_ubyte)), output.nbytes, ct.byref(kind))
    if np.asarray(core.restore_scalar(kind)).dtype != dtype:
        raise RuntimeError('native zone speed dtype disagrees with the result interface')
    return output


def zone_cv(deviation, mean):
    output = _D()
    _call('zone_cv', [_D, _D, ct.POINTER(_D)], deviation, mean, ct.byref(output))
    return output.value
