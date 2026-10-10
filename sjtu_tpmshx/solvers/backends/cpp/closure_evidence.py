"""Detach native closure evidence and replay the existing warning formatter."""
import ctypes as ct

import numpy as np

from sjtu_tpmshx.domain.run_warnings import RangeRecord, current_warnings, merge_warnings, warning_messages
from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR


class NuObservation(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('cells', ct.c_size_t), ('floor_cells', ct.c_size_t)]
    _fields_ += [(name, ct.c_double) for name in ('raw_min', 'raw_max', 're_min', 're_max', 'pr_min', 'pr_max',
                                               'temperature_min', 'temperature_max', 'pressure')]


class RangeObservation(ct.Structure):
    _fields_ = [(name, ct.c_char_p) for name in ('view', 'model', 'topology', 'stage', 'layout')]
    _fields_ += [(name, ct.c_uint32) for name in ('side', 'ndim', 'have_finite')]
    _fields_ += [('shape', ct.c_size_t * 3)]
    _fields_ += [(name, ct.c_size_t) for name in ('minimum_index', 'maximum_index', 'low', 'high', 'size', 'nonfinite')]
    _fields_ += [(name, ct.c_double) for name in ('lower', 'upper', 'minimum', 'maximum')]


def copy_nu_observation(value, shape):
    if not value.available:
        return {}
    return dict(stage='last local h_v coefficient evaluation (lagged temperature)',
        shape=list(shape), cells=value.cells, floor_cells=value.floor_cells,
        floor_fraction=value.floor_cells / value.cells, floor=NU_LAM_FLOOR,
        pre_floor_min=value.raw_min, pre_floor_max=value.raw_max, Re_min=value.re_min, Re_max=value.re_max,
        Pr_min=value.pr_min, Pr_max=value.pr_max, T_min_K=value.temperature_min, T_max_K=value.temperature_max,
        P_abs_Pa=value.pressure)


def copy_range_observations(values, count):
    """Return owned ordinary values; no native string/pointer outlives release."""
    rows = []
    for i in range(count):
        value = values[i]
        row = {name: getattr(value, name).decode() for name in ('view', 'model', 'topology', 'stage', 'layout')}
        row.update(side=('A', 'B')[value.side], shape=tuple(value.shape[:value.ndim]),
            bounds=(value.lower, value.upper), low=value.low, high=value.high, size=value.size, nonfinite=value.nonfinite,
            minimum=None, maximum=None)
        if value.have_finite:
            for key in ('minimum', 'maximum'):
                index = tuple(int(i) for i in np.unravel_index(getattr(value, key + '_index'), row['shape']))
                row[key] = (getattr(value, key), index)
        rows.append(row)
    return rows


def range_records(rows):
    """Reconstruct RangeRecord values from captured inputs without properties."""
    records = {}
    for row in rows:
        nu = row['view'] in ('nu', 'nu_raw', 'nu_pr')
        source = (row['view'], row['model'], row['topology']) if nu else (row['view'], row['model'])
        if row['view'] == 'nu_raw':
            label = f"[{row['model']} Nu raw] {row['topology']}"
        elif row['view'] in ('nu', 'nu_pr'):
            prefix = {'air': 'Nu extrap', 'water': 'water Nu extrap', 'sco2': 'sCO2 Nu extrap', 'co2': 'CO2 Nu extrap'}[row['model']]
            label = f"[{prefix}] {row['topology']}"
        else:
            label = row['model']
        key = (*source, tuple(row['shape']), (row['side'], row['stage'], row['layout']))
        record = RangeRecord(label, 'Pr' if row['view'] == 'nu_pr' else 'Re' if nu else 'T', '-' if nu else 'K', tuple(row['bounds']),
            row['minimum'], row['maximum'], row['low'], row['high'], row['size'], row['nonfinite'])
        previous = records.get(key)
        records[key] = record if previous is None else previous.merged(record)
    return records


def replay_range_observations(rows):
    records = range_records(rows)
    merge_warnings(current_warnings(), [records])
    return list(warning_messages(records))
