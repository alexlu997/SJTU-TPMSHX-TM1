"""Read saved HDF5 result summaries, single fields, and full field sets for the GUI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from tm1.applications.result_adapter import to_compute_result_header
from tm1.data_types.compute_result import ComputeResult
from tm1.data_types.portable_data import mutable_data
from tm1.file_io.metrics_io import load_metrics
from tm1.file_io.result_io import (
    load_result,
    load_result_design_field,
    load_result_field,
    load_result_header,
)
from tm1.physical_models.zone_units import _legacy_zone_units
from tm1.postprocess.result_display import RESULT_FIELD_SPECS

_DIRECT_RESULT_FIELDS = frozenset({
    'Ta', 'Tb', 'Ts',
    'ucA', 'vcA', 'wcA',
    'ucB', 'vcB', 'wcB',
    'h_vA', 'h_vB',
})


def _read_checked(reader, result_file: str | Path, field_name: str, expected_result_id: str | None) -> np.ndarray:
    selected = reader(result_file, field_name)
    if expected_result_id is not None and selected.source_result_id != expected_result_id:
        raise ValueError(
            f'result file changed on disk: expected source_result_id '
            f'{expected_result_id!r}, got {selected.source_result_id!r}'
        )
    return selected.values


def build_saved_compute_result(
    result_file: str | Path,
    *,
    metrics_file: str | Path | None = None,
) -> tuple[str, ComputeResult, str, tuple[str, ...]]:
    """Build a lightweight ComputeResult from a saved HDF5 header and required metrics.json."""
    path = Path(result_file)
    metrics_path = path.with_name('metrics.json') if metrics_file is None else Path(metrics_file)
    header = load_result_header(path)
    performance = load_metrics(metrics_path)
    compute_result = to_compute_result_header(header, performance)

    dimension = header.grid['dimension']
    mode = f'{dimension}d'
    available: list[str] = [
        name for name in header.available_fields if name in _DIRECT_RESULT_FIELDS
    ]
    for side in ('A', 'B'):
        if f'P_report_{side}' in header.available_fields:
            available.append(f'P_f{side}')
    if dimension == 2:
        for side in ('A', 'B'):
            if f'uc{side}' in header.available_fields and f'vc{side}' in header.available_fields:
                available.append(f'vmag_{side}')
    elif dimension == 3:
        for name in ('vmag_A', 'vmag_B'):
            if name in header.available_fields:
                available.append(name)
        if 'L_field_m' in header.available_design_fields:
            available.append('L_mm')
        if 't_field_m' in header.available_design_fields:
            available.append('t_mm')
    return mode, compute_result, header.result_id, tuple(dict.fromkeys(available))


def read_saved_display_field(
    result_file: str | Path,
    field_key: str,
    *,
    mode: str,
    expected_result_id: str | None = None,
) -> np.ndarray:
    """Read one display field from a saved result file through the selected-field reader."""
    if field_key in _DIRECT_RESULT_FIELDS:
        return _read_checked(load_result_field, result_file, field_key, expected_result_id)
    if field_key == 'P_fA':
        return _read_checked(load_result_field, result_file, 'P_report_A', expected_result_id)
    if field_key == 'P_fB':
        return _read_checked(load_result_field, result_file, 'P_report_B', expected_result_id)
    if field_key == 'P_kPa':
        raw = _read_checked(load_result_field, result_file, 'P_report_A', expected_result_id)
        return np.ascontiguousarray(raw * RESULT_FIELD_SPECS['P_fA'].display_scale)
    if field_key == 'P_B_kPa':
        raw = _read_checked(load_result_field, result_file, 'P_report_B', expected_result_id)
        return np.ascontiguousarray(raw * RESULT_FIELD_SPECS['P_fB'].display_scale)
    if field_key in ('vmag', 'vmag_A'):
        if mode == '3d':
            return _read_checked(load_result_field, result_file, 'vmag_A', expected_result_id)
        u = _read_checked(load_result_field, result_file, 'ucA', expected_result_id)
        v = _read_checked(load_result_field, result_file, 'vcA', expected_result_id)
        return np.hypot(u, v)
    if field_key == 'vmag_B':
        if mode == '3d':
            return _read_checked(load_result_field, result_file, 'vmag_B', expected_result_id)
        u = _read_checked(load_result_field, result_file, 'ucB', expected_result_id)
        v = _read_checked(load_result_field, result_file, 'vcB', expected_result_id)
        return np.hypot(u, v)
    if field_key == 'L_mm':
        return _read_checked(load_result_design_field, result_file, 'L_field_m', expected_result_id) * 1e3
    if field_key == 't_mm':
        return _read_checked(load_result_design_field, result_file, 't_field_m', expected_result_id) * 1e3
    raise KeyError(field_key)


def load_all_saved_display_fields(
    result_file: str | Path,
    *,
    mode: str,
    expected_result_id: str | None = None,
) -> dict[str, Any]:
    """Read every display field from a saved result file through the full load_result path."""
    result = load_result(result_file)
    if expected_result_id is not None and result.result_id != expected_result_id:
        raise ValueError(
            f'result file changed on disk: expected source_result_id '
            f'{expected_result_id!r}, got {result.result_id!r}'
        )
    f = result.fields
    fields: dict[str, Any] = {name: mutable_data(f[name]) for name in ('Ta', 'Tb', 'Ts')}
    fields.update({f'P_f{side}': mutable_data(f.get(f'P_report_{side}')) for side in 'AB'})
    fields.update({name: mutable_data(f.get(name)) for name in ('ucA', 'vcA', 'ucB', 'vcB')})
    if mode == '2d':
        for side in 'AB':
            u, v = fields['uc' + side], fields['vc' + side]
            fields['vmag_' + side] = None if u is None or v is None else np.hypot(u, v)
        fields['za'] = (
            _legacy_zone_units(mutable_data(result.metadata['design_fields']))
            if result.metadata['design_mode'] != 'uniform'
            else None
        )
    elif mode == '3d':
        fields.update({name: mutable_data(f.get(name)) for name in ('wcA', 'wcB', 'vmag_A', 'vmag_B')})
        design_fields = result.metadata['design_fields']
        fields.update(
            L_mm=design_fields['L_field_m'] * 1e3,
            t_mm=design_fields['t_field_m'] * 1e3,
            h_vA_field=mutable_data(f['h_vA']),
            h_vB_field=mutable_data(f['h_vB']),
        )
    else:
        raise ValueError(f'unsupported result mode: {mode}')
    return fields
