"""Detach the full-compute model-enthalpy temperature power ledger.

Each solved fluid records [c0, c1, c2, Tbase, Tref] for the existing model:
cp(T) = c0 + c1*(T-Tbase) + c2*(T-Tbase)**2, h(Tref) = 0.
The boundary powers already contain signed mass times integral h(T_face).
"""
import ctypes as ct

import numpy as np

from .model_h import _Array
from .physical_ledger import copy_heat_ledger


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
    if not value.algorithm:
        raise RuntimeError('native temperature evidence has no executed algorithm')
    coefficients = {}
    for index, label in enumerate('AB'):
        row = np.array(value.cp_coefficients[index], dtype=np.float64)
        if value.solved[index] and not np.all(np.isfinite(row)):
            raise RuntimeError('native temperature evidence has invalid enthalpy coefficients')
        coefficients[label] = row if value.solved[index] else None
    result = copy_heat_ledger(value, shape, dimension, name='native temperature evidence')
    result.update(definition='model_enthalpy_temperature_v1',
                  algorithm=value.algorithm.decode('ascii'), cp_coefficients=coefficients)
    return result
