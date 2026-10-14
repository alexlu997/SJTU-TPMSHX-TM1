"""Copy native heat evidence while its full result owner is alive."""
import ctypes as ct

import numpy as np

from .model_h import _Array


class HeatLedger(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('physical_dimension', ct.c_uint32),
                ('boundary_complete', ct.c_uint32), ('solved', ct.c_uint32 * 3),
                ('residual', _Array * 3), ('advective_out', (_Array * 6) * 3),
                ('diffusive_out', (_Array * 6) * 3),
                ('source_integral', ct.c_double * 3), ('prescribed_b_power', ct.c_double)]


class HeatLedger2D(ct.Structure):
    _fields_ = [('main', HeatLedger), ('fine', HeatLedger)]


def heat_ledger_query(library, dimension, result_type):
    try:
        query = getattr(library, f'tpmshx_full_{dimension}d_get_physical_heat_ledger_v1')
    except AttributeError as exc:
        raise ValueError('native library lacks physical heat ledgers; rebuild the library') from exc
    query.argtypes = [ct.POINTER(result_type), ct.POINTER(HeatLedger2D if dimension == 2 else HeatLedger)]
    query.restype = ct.c_int
    return query


def copy_heat_ledger(value, shape, dimension, *, name='native heat ledger'):
    if value.available == 0:
        return None
    if value.available != 1 or value.physical_dimension != dimension:
        raise RuntimeError(f'{name} has an invalid availability or dimension')
    if value.boundary_complete not in (0, 1) or any(v not in (0, 1) for v in value.solved):
        raise RuntimeError(f'{name} has invalid state flags')
    shape = tuple(shape)
    if len(shape) != 3 or dimension not in (2, 3) or (dimension == 2 and shape[2] != 1):
        raise RuntimeError(f'{name} has an inconsistent cell shape')
    def copy(array, expected):
        if not array.data or array.size != int(np.prod(expected)):
            raise RuntimeError(f'{name} array extent disagrees with grid')
        return np.ctypeslib.as_array(array.data, shape=(array.size,)).copy().reshape(expected)
    labels = ('A', 'B', 'solid')
    names = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
    planes = tuple(tuple(n for d, n in enumerate(shape) if d != axis)
                   for axis in range(3) for _ in range(2))
    result = dict(definition='physical_heat_ledger_v1', physical_dimension=dimension,
        power_units='W/m' if dimension == 2 else 'W',
        physical_boundary_complete=bool(value.boundary_complete),
        solved=dict(zip(labels, map(bool, value.solved))),
        residual={label: copy(value.residual[s], shape[:dimension]) if value.solved[s] else None
                  for s, label in enumerate(labels)},
        source_integral={label: value.source_integral[s] if value.solved[s] else None
                         for s, label in enumerate(labels)},
        prescribed_b_power=value.prescribed_b_power)
    for key in ('advective_out', 'diffusive_out'):
        arrays = getattr(value, key)
        result[key] = {label: {name: copy(arrays[s][face], planes[face])
                      for face, name in enumerate(names)} if value.solved[s] else None
                      for s, label in enumerate(labels)}
    return result
