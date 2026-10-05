"""Detach the full-compute model-enthalpy temperature power ledger.

Each solved fluid records [c0, c1, c2, Tbase, Tref] for the existing model:
cp(T) = c0 + c1*(T-Tbase) + c2*(T-Tbase)**2, h(Tref) = 0.
The boundary powers already contain signed mass times integral h(T_face).
"""
import ctypes as ct

import numpy as np

from .model_h import _Array


class TemperatureEvidence(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('physical_dimension', ct.c_uint32),
                ('boundary_complete', ct.c_uint32), ('solved', ct.c_uint32 * 3),
                ('algorithm', ct.c_char_p), ('cp_coefficients', (ct.c_double * 5) * 2),
                ('residual', _Array * 3), ('advective_out', (_Array * 6) * 3),
                ('diffusive_out', (_Array * 6) * 3),
                ('source_integral', ct.c_double * 3), ('prescribed_b_power', ct.c_double)]


class TemperatureEvidence2D(ct.Structure):
    _fields_ = [('main', TemperatureEvidence), ('fine', TemperatureEvidence)]


def copy_temperature_evidence(value, shape, dimension):
    if value.available != 1 or value.physical_dimension != dimension:
        raise RuntimeError('native temperature evidence is unavailable or has the wrong dimension')
    if value.boundary_complete not in (0, 1) or any(v not in (0, 1) for v in value.solved):
        raise RuntimeError('native temperature evidence has invalid state flags')
    if not value.algorithm:
        raise RuntimeError('native temperature evidence has no executed algorithm')
    coefficients = {}
    for index, label in enumerate('AB'):
        row = np.array(value.cp_coefficients[index], dtype=np.float64)
        if value.solved[index] and not np.all(np.isfinite(row)):
            raise RuntimeError('native temperature evidence has invalid enthalpy coefficients')
        coefficients[label] = row if value.solved[index] else None
    shape = tuple(shape)
    if len(shape) != 3 or (dimension == 2 and shape[2] != 1):
        raise RuntimeError('native temperature evidence has inconsistent cell shape')
    cell_shape = shape[:dimension]
    def copy(array, expected):
        if not array.data or array.size != int(np.prod(expected)):
            raise RuntimeError('native temperature evidence array extent disagrees with grid')
        return np.ctypeslib.as_array(array.data, shape=(array.size,)).copy().reshape(expected)
    planes = tuple(tuple(n for d, n in enumerate(shape) if d != axis)
                   for axis in range(3) for _ in range(2))
    labels = ('A', 'B', 'solid')
    names = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
    result = dict(definition='model_enthalpy_temperature_v1', physical_dimension=dimension,
        algorithm=value.algorithm.decode('ascii'),
        power_units='W/m' if dimension == 2 else 'W',
        cp_coefficients=coefficients,
        physical_boundary_complete=bool(value.boundary_complete),
        solved=dict(zip(labels, map(bool, value.solved))),
        residual={label: copy(value.residual[s], cell_shape) if value.solved[s] else None
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
