"""Borrowed records from a completed native 2D or 3D stage."""

import ctypes as ct
import warnings

from sjtu_tpmshx.data_types.case_data import resolved_input_record
from .._df_abi import DragSummary
from .closure_evidence import RangeObservation
from .enthalpy import _EnergyUpdateScale
from .model_h import _Acceleration, _IterationRecords
from .temperature_evidence import TemperatureEvidence


class _Sample(ct.Structure):
    _fields_ = [('side', ct.c_uint32), ('outer_index', ct.c_int64)]
    _fields_ += [(name, ct.c_char_p) for name in
                ('stage', 'quantity', 'provider', 'temperature', 'pressure', 'operation')]


class _Sampling(ct.Structure):
    _fields_ = [('records', ct.POINTER(_Sample)), ('count', ct.c_size_t)]


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


class StageExecution(ct.Structure):
    _fields_ = [('records', ct.POINTER(StageRecords)),
                ('update_scale', _EnergyUpdateScale), ('model_h', _IterationRecords),
                ('acceleration', ct.POINTER(_Acceleration)), ('last_main_model_h', ct.c_size_t),
                ('unknown', ct.c_char_p), ('algorithm', ct.c_char_p), ('sco2_notices', ct.c_char_p * 2),
                ('red_black', ct.c_uint32)]


def execution_view_query(library, dimension, result_type, view_type):
    query = getattr(library, f'tpmshx_stage_run_{dimension}d_execution_view_v1', None)
    if query is not None:
        query.argtypes, query.restype = [ct.POINTER(result_type)], ct.POINTER(view_type)
    return query


def executed_view(query, result):
    view = query(ct.byref(result))
    if not view:
        raise RuntimeError('native stage returned no execution record')
    return view.contents


def thermal_execution(executed, evidence, iterations, energy):
    if executed.last_main_model_h < executed.model_h.count:
        settings = iterations['records'][executed.last_main_model_h]['settings']
    else:
        settings = {} if energy is None else energy['effective_settings']
    return dict(thermal_mode=evidence.thermal_mode.decode(), unknown=executed.unknown.decode(),
                temperature_transport=evidence.temperature_transport.decode() if evidence.temperature_transport else None,
                effective_settings=settings)


def replay_sco2_notices(notices, stage):
    from sjtu_tpmshx.run_control.run_warnings import record_warning
    for side, raw in zip('AB', notices):
        if raw is not None:
            message = raw.decode()
            if not record_warning(('nu-evidence', 'sco2', side, stage), message):
                warnings.warn(message, stacklevel=2)


def stage_records(library, result):
    query = getattr(library, f'tpmshx_stage_run_{result.evidence.dimension}d_records_v1', None)
    if query is None:
        return None
    query.argtypes, query.restype = [ct.POINTER(type(result))], ct.POINTER(StageRecords)
    records = query(ct.byref(result))
    if not records:
        raise RuntimeError('native stage returned no result records')
    return records.contents


def sampling_query(library, dimension, result_type):
    try:
        query = getattr(library, f'tpmshx_full_{dimension}d_get_property_sampling_v1')
    except AttributeError as exc:
        raise ValueError('native library lacks property sampling records; rebuild the library') from exc
    query.argtypes = [ct.POINTER(result_type), ct.POINTER(_Sampling)]
    query.restype = ct.c_int
    return query


def copy_sampling(query, result):
    view = _Sampling()
    if query(ct.byref(result), ct.byref(view)):
        raise RuntimeError('native property sampling query failed')
    return sampling_records(view)


def sampling_records(view):
    records = []
    for sample in view.records[:view.count] if view.count else ():
        row = dict(side='AB'[sample.side], outer_index=sample.outer_index)
        for name, _ in sample._fields_[2:]:
            value = getattr(sample, name)
            row[name] = value.decode('ascii') if value is not None else None
        records.append(row)
    return records


def executed_inputs(case, evidence):
    shape = tuple(width.contents.shape[0] for width in evidence.grid.widths[:evidence.dimension])
    directions = evidence.direction if evidence.dimension == 2 else evidence.thermal.report_direction
    fluids = {side.side.decode(): side.fluid.decode()
              for side in evidence.executed_sides[:evidence.executed_side_count]}
    return resolved_input_record(case, fluids, shape,
        {side: direction[0] for side, direction, active in zip('AB', directions, evidence.active_fluids) if active})


def execution_sides(records, evidence, case, declarations):
    roles = case.metadata['model_roles']
    sides = {}
    for index, row in enumerate(records.energy):
        side = evidence.executed_sides[index].side.decode()
        model = roles['fluid_' + side]
        energy = dict(relation=row.relation.decode(), property_provider=row.provider.decode() if row.provider else None,
                      model_ref=model if row.solved and not row.eos_fluid else None, temperature_field=('Ta', 'Tb')[index])
        evaluation = dict(state_update=row.state_update.decode() if row.state_update else None)
        if row.eos_fluid:
            field = 'P_thermal_' + side
            energy.update(fluid=row.eos_fluid.decode(), pressure_field=field, pressure_state=declarations[field]['state'])
            evaluation['final_property_backend'] = 'HEOS'
        sides[side] = dict(fluid=evidence.executed_sides[index].fluid.decode(), solved=bool(row.solved),
                           flow_and_exchange_model_ref=model, energy=energy, property_evaluation=evaluation)
    return sides
