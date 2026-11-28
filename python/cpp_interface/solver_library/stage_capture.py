"""Copy completed solver capture views and records before native release."""
import ctypes as ct
import json
from math import prod

import numpy as np


def solver_entry(library, name):
    """Return a required solver symbol. A missing symbol is a deployment error."""
    try:
        return getattr(library, name)
    except AttributeError as error:
        raise ValueError(f'native solver library lacks {name}; rebuild the library') from error


def execution_view_query(library, dimension, result_type, view_type):
    query = solver_entry(library, f'tpmshx_stage_run_{dimension}d_execution_view_v1')
    query.argtypes, query.restype = [ct.POINTER(result_type)], ct.POINTER(view_type)
    return query


def executed_view(query, result):
    view = query(ct.byref(result))
    if not view:
        raise RuntimeError('native stage returned no execution record')
    return view.contents


def completed_report(library, result):
    query = solver_entry(library, f'tpmshx_stage_run_{result.evidence.dimension}d_report_v1')
    query.argtypes, query.restype = [ct.POINTER(type(result)), ct.POINTER(ct.c_char), ct.c_size_t], ct.c_char_p
    error = ct.create_string_buffer(1024)
    data = query(ct.byref(result), error, len(error))
    if data is None:
        raise RuntimeError(error.value.decode() or 'native stage returned no execution report')
    return json.loads(data)


def _stage_array(value, shape):
    count = prod(shape)
    if (value.rank != len(shape) or tuple(value.shape[:value.rank]) != tuple(shape)
            or (count and not value.data)):
        raise RuntimeError('native result array has an invalid layout')
    if not count:
        return np.empty(shape, dtype=np.float64)
    return np.frombuffer(ct.string_at(value.data, count * 8), dtype=np.float64).reshape(shape)


def detach_stage_fields(evidence, shape, *, prepared_fields=None):
    """Copy each cell buffer once while the native stage owns it."""
    buffers = {}
    fields = {}
    for named in evidence.fields[:evidence.field_count]:
        name = named.name.decode()
        if prepared_fields is not None and name in prepared_fields:
            fields[name] = prepared_fields[name]
            continue
        value = named.value
        if value.data not in buffers:
            buffers[value.data] = _stage_array(value, shape)
        fields[name] = buffers[value.data]
    return fields, field_declarations(evidence)


def closure_records(rows, count):
    from tm1.run_control.run_warnings import RangeRecord
    samples = []
    records: dict[tuple, RangeRecord] = {}
    for entry in rows[:count] if count else ():
        value = entry.sample.contents
        row = {name: getattr(value, name).decode() for name in ('view', 'model', 'topology', 'stage', 'layout')}
        shape = tuple(value.shape[:value.ndim])
        bounds = value.lower, value.upper
        row.update(side='AB'[value.side], shape=shape, bounds=bounds, low=value.low, high=value.high,
                   size=value.size, nonfinite=value.nonfinite)
        for key in ('minimum', 'maximum'):
            position = getattr(entry, key + '_index')
            row[key] = (getattr(value, key), tuple(position[:value.ndim])) if value.have_finite else None
        samples.append(row)
        source = (row['view'], row['model'], row['topology'])[:entry.source_count]
        source_key = (*source, shape, (row['side'], row['stage'], row['layout']))
        record = RangeRecord(entry.label.decode(), entry.quantity.decode(), entry.unit.decode(),
            bounds, row['minimum'], row['maximum'], value.low, value.high, value.size, value.nonfinite)
        previous = records.get(source_key)
        records[source_key] = record if previous is None else previous.merged(record)
    return samples, records


def nu_observation(value, shape, summary):
    if not value.available:
        return {}
    return dict(stage='last local h_v coefficient evaluation (lagged temperature)',
        shape=list(shape), cells=value.cells, floor_cells=value.floor_cells,
        floor_fraction=summary['floor_fraction'],
        floor=summary['floor'],
        pre_floor_min=value.raw_min, pre_floor_max=value.raw_max, Re_min=value.re_min, Re_max=value.re_max,
        Pr_min=value.pr_min, Pr_max=value.pr_max, T_min_K=value.temperature_min, T_max_K=value.temperature_max,
        P_abs_Pa=value.pressure)


def stage_closures(records):
    from tm1.run_control.run_warnings import range_observations
    rows, warnings = closure_records(records.observations, records.observation_count)
    _, last = closure_records(records.last, records.last_count)
    return rows, warnings, range_observations(last)


def stage_ledger(thermal, temperature, shape):
    """Detach the cell residuals and signed face powers from the stage."""
    pointer = thermal.temperature if thermal.temperature else thermal.energy
    if not pointer:
        return None
    ledger = pointer.contents
    dimension = len(shape)
    if dimension != ledger.physical_dimension or ledger.phase_count != 3:
        raise RuntimeError('native stage ledger has an invalid dimension or phase count')
    output = dict(definition=ledger.definition.decode(), power_units=ledger.power_units.decode(),
        physical_dimension=dimension, physical_boundary_complete=bool(ledger.physical_boundary_complete),
        prescribed_b_power=_stage_array(ledger.prescribed_b_power.contents, ()).item())
    for key in ('solved', 'residual', 'source_integral', 'advective_out', 'diffusive_out'):
        output[key] = {}
    volume = (*shape, 1) if dimension == 2 else shape
    for phase in ledger.phases[:ledger.phase_count]:
        label = phase.name.decode()
        output['solved'][label] = bool(phase.solved)
        output['residual'][label] = _stage_array(phase.residual.contents, shape) if phase.solved else None
        output['source_integral'][label] = _stage_array(phase.source_integral.contents, ()).item() if phase.solved else None
        for key, count in (('advective_out', phase.advective_count), ('diffusive_out', phase.diffusive_count)):
            faces = None
            if phase.solved:
                faces = {}
                for named in getattr(phase, key)[:count]:
                    name = named.name.decode()
                    axis = 'xyz'.index(name[0])
                    faces[name] = _stage_array(named.value, volume[:axis] + volume[axis + 1:])
            output[key][label] = faces
    if thermal.temperature:
        info = temperature.contents
        output.update(algorithm=info.algorithm.decode('ascii'), cp_coefficients={
            side: np.array(info.cp_coefficients[i]) if info.solved[i] else None for i, side in enumerate('AB')})
    return output


def field_declarations(evidence):
    axes = ('x', 'y', 'z')[:evidence.dimension]
    return {row.name.decode(): dict(unit=row.unit.decode(), state=row.state.decode(),
            axes=axes, location='cell')
            for row in evidence.field_metadata[:evidence.field_metadata_count]}


def copy_applicability(pointer, saved_inlet):
    """Copy selected evidence before the native result owner is released."""
    if not pointer or pointer.contents.version != b'applicability_evidence_v1':
        raise RuntimeError('native result lacks supported applicability evidence')
    value = pointer.contents
    if value.inlet_count < len(saved_inlet):
        raise RuntimeError('native applicability evidence lacks saved inlet rows')
    inlet = []
    for index in range(value.inlet_count):
        raw = value.inlet[index]
        # Saved rows retain host fields and scalar types absent from the C descriptor.
        row = dict(saved_inlet[index]) if index < len(saved_inlet) else _copy_range(raw)
        if raw.constraint is not None:
            row['constraint'] = raw.constraint.decode()
        inlet.append(row)
    required = []
    for row in value.required[:value.required_count]:
        source = tuple([item.decode() for item in row.source[:row.source_count]])
        required.append(dict(group=row.group.decode(), side=row.side.decode(), source=source))
    return dict(version=value.version.decode(), inlet_recorded=bool(value.inlet_recorded),
        inlet=inlet, final=[_copy_range(value.final_state[index]) for index in range(value.final_count)],
        required=required)


def _copy_range(value):
    row = {name: getattr(value, name).decode() for name in ('side', 'quantity', 'stage', 'layout', 'unit')}
    row.update(source=tuple([item.decode() for item in value.source[:value.source_count]]),
        captured=bool(value.captured), shape=tuple(value.shape[:value.rank]), bounds=tuple(value.bounds))
    for name in ('constraint', 'reason'):
        if getattr(value, name) is not None:
            row[name] = getattr(value, name).decode()
    if value.captured:
        row.update({name: getattr(value, name) for name in ('size', 'low', 'high', 'nonfinite')})
        for name in ('minimum', 'maximum'):
            row[name] = ((getattr(value, name)[0], tuple(getattr(value, name + '_index')[:value.rank]))
                         if getattr(value, name) else None)
    return row
