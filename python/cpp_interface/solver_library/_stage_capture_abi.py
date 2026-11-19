"""Borrowed records from a completed native 2D or 3D stage."""

import ctypes as ct

from .._df_abi import DragSummary
from .closure_evidence import RangeObservation
from .property_sampling import _Sampling
from .temperature_evidence import TemperatureEvidence


class RangeRecordView(ct.Structure):
    _fields_ = [('sample', ct.POINTER(RangeObservation)), ('label', ct.c_char_p),
                ('quantity', ct.c_char_p), ('unit', ct.c_char_p), ('source_count', ct.c_size_t),
                ('minimum_index', ct.c_size_t * 3), ('maximum_index', ct.c_size_t * 3)]


class EnergyRelation(ct.Structure):
    _fields_ = [(name, ct.c_char_p) for name in ('relation', 'provider', 'state_update', 'eos_fluid')]
    _fields_ += [('solved', ct.c_uint32)]


class StageRecords(ct.Structure):
    _fields_ = [('sampling', _Sampling), ('observations', ct.POINTER(RangeRecordView)),
                ('last', ct.POINTER(RangeRecordView)), ('observation_count', ct.c_size_t), ('last_count', ct.c_size_t),
                ('temperature', ct.POINTER(TemperatureEvidence) * 2), ('simple_stop', ct.c_char_p * 2),
                ('energy', EnergyRelation * 2), ('transient_failures', ct.POINTER(ct.c_char_p)),
                ('final_failures', ct.POINTER(ct.c_char_p)), ('transient_count', ct.c_size_t),
                ('final_count', ct.c_size_t), ('base_drag', DragSummary * 2), ('applied_drag', (DragSummary * 2) * 2),
                ('thermal_history_converged', ct.c_uint32)]
