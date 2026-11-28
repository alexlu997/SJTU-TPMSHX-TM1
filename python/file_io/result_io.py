"""Archive completed or explicitly rejected native results independently of solvers."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np

from tm1.data_types.case_data import SCHEMA_VERSION
from tm1.data_types.field_result import FieldResult
from tm1.data_types.model_refs import ModelRef, freeze_mapping, freeze_value
from tm1.data_types.persistence_validation import validate_result
from tm1.postprocess.result_display import RESULT_FIELD_SPECS
from .hdf5_data import ArrayDescriptor, read_record, read_record_selection, write_record

_RESULT_MAPPINGS = (
    'grid', 'fields', 'boundary_fluxes', 'pressure_evidence',
    'run_status', 'metadata', 'field_metadata',
)

_DESIGN_FIELD_UNITS: dict[str, str] = {
    'L_field_m': 'm',
    't_field_m': 'm',
    'r_h_arr': 'm',
    'eps_arr': '1',
    'eps_A': '1',
    'eps_B': '1',
    'zone_id': '1',
    'K_m2': 'm2',
    'cF_per_m': '1/m',
    'K_ss': 'W/(m K)',
    'K_ss_arr': 'W/(m K)',
    'K_ffA_arr': 'W/(m K)',
    'K_ffB_arr': 'W/(m K)',
    'h_vA_arr': 'W/(m3 K)',
    'h_vB_arr': 'W/(m3 K)',
    'A_0_arr': '1/m',
}


@dataclass(frozen=True)
class SelectedResultField:
    """One validated field and its physical grid from a saved FieldResult."""

    source_result_id: str
    name: str
    values: np.ndarray
    raw_unit: str
    display_unit: str
    grid: Mapping[str, Any]
    axes: tuple[str, ...]
    association: str
    shape: tuple[int, ...]
    dtype: np.dtype[Any]
    state: str


@dataclass(frozen=True)
class ResultHeader:
    """Validated metadata, physical grid, and field inventory from a saved FieldResult."""

    result_id: str
    case_id: str
    backend_id: str
    schema_version: str
    backend_version: str
    grid: Mapping[str, Any]
    available_fields: tuple[str, ...]
    available_design_fields: tuple[str, ...]
    field_metadata: Mapping[str, Any]
    run_status: Mapping[str, Any]
    metadata: Mapping[str, Any]
    model_refs: tuple[ModelRef, ...]


def _check_portable_tree(value: Any) -> None:
    if value is None or isinstance(value, (bool, int, float, str, bytes, ArrayDescriptor)):
        return
    if isinstance(value, np.generic):
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError('contract mapping keys must be strings')
        for item in value.values():
            _check_portable_tree(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check_portable_tree(item)
        return
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in 'biuf':
            raise TypeError('contract arrays must contain real numbers or booleans, not objects')
        return
    raise TypeError('contract data cannot contain callables or runtime objects')


def _strip_unloaded_arrays(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_unloaded_arrays(item)
            for key, item in value.items()
            if not isinstance(item, ArrayDescriptor)
        }
    if isinstance(value, tuple):
        return tuple(_strip_unloaded_arrays(item) for item in value if not isinstance(item, ArrayDescriptor))
    if isinstance(value, list):
        return [_strip_unloaded_arrays(item) for item in value if not isinstance(item, ArrayDescriptor)]
    return value


def _validate_selected_result_data(data: dict[str, Any]) -> tuple[int, ...]:
    """Run the same identity, container, and schema validation as load_result."""
    if not data['result_id'] or not data['case_id'] or not data['backend_id']:
        raise ValueError('FieldResult requires result_id, case_id and backend_id')
    if data['schema_version'] != SCHEMA_VERSION:
        raise ValueError(f"unsupported FieldResult schema_version: {data['schema_version']}")
    for name in _RESULT_MAPPINGS:
        if not isinstance(data[name], Mapping):
            raise TypeError('contract field must be a mapping')
        _check_portable_tree(data[name])
    if any(not isinstance(ref, ModelRef) for ref in data['model_refs']):
        raise TypeError('FieldResult.model_refs must contain ModelRef values')
    validate_result(SimpleNamespace(**data))
    grid = data['grid']
    return tuple(len(grid['d' + axis]) for axis in grid['axis_order'])


def _display_unit_for(name: str, raw_unit: str) -> str:
    spec = RESULT_FIELD_SPECS.get(name)
    if spec is not None and spec.stored_unit == raw_unit:
        return spec.display_unit
    if raw_unit == 'Pa':
        return RESULT_FIELD_SPECS['P_fA'].display_unit
    if name == 'L_field_m' and raw_unit == 'm':
        return RESULT_FIELD_SPECS['L_mm'].display_unit
    if name == 't_field_m' and raw_unit == 'm':
        return RESULT_FIELD_SPECS['t_mm'].display_unit
    return raw_unit


def save_result(result, path):
    validate_result(result)
    return write_record(path, result, 'FieldResult')


def load_result(path):
    return validate_result(read_record(path, FieldResult, 'FieldResult'))


def load_result_field(path, field_name: str) -> SelectedResultField:
    """Read one validated field and its physical grid from a saved result file."""
    if not isinstance(field_name, str) or not field_name:
        raise ValueError('field_name must be a non-empty string')
    data = read_record_selection(
        path,
        FieldResult,
        'FieldResult',
        load_array=lambda node: node[:1] == ('grid',) or node == ('fields', field_name),
    )
    _validate_selected_result_data(data)
    if field_name not in data['fields']:
        raise KeyError(field_name)
    raw = data['fields'][field_name]
    if not isinstance(raw, np.ndarray):
        raise ValueError(f'field {field_name} must be a numeric array')
    values = freeze_value(raw)
    grid = freeze_mapping(data['grid'])
    meta = data['field_metadata'][field_name]
    raw_unit = str(meta['unit'])
    return SelectedResultField(
        source_result_id=str(data['result_id']),
        name=field_name,
        values=values,
        raw_unit=raw_unit,
        display_unit=_display_unit_for(field_name, raw_unit),
        grid=grid,
        axes=tuple(meta['axes']),
        association=str(meta['location']),
        shape=values.shape,
        dtype=values.dtype,
        state=str(meta['state']),
    )


def load_result_design_field(path, field_name: str) -> SelectedResultField:
    """Read one validated cell-shaped design field from metadata.design_fields."""
    if not isinstance(field_name, str) or not field_name:
        raise ValueError('field_name must be a non-empty string')
    data = read_record_selection(
        path,
        FieldResult,
        'FieldResult',
        load_array=lambda node: (
            node[:1] == ('grid',) or node == ('metadata', 'design_fields', field_name)
        ),
    )
    grid_shape = _validate_selected_result_data(data)
    design_fields = data['metadata'].get('design_fields')
    if not isinstance(design_fields, Mapping) or field_name not in design_fields:
        raise KeyError(field_name)
    raw = design_fields[field_name]
    if not isinstance(raw, np.ndarray) or raw.shape != grid_shape:
        raise ValueError(f'design field {field_name} shape disagrees with grid')
    if field_name not in _DESIGN_FIELD_UNITS:
        raise KeyError(field_name)
    values = freeze_value(raw)
    grid = freeze_mapping(data['grid'])
    raw_unit = _DESIGN_FIELD_UNITS[field_name]
    return SelectedResultField(
        source_result_id=str(data['result_id']),
        name=field_name,
        values=values,
        raw_unit=raw_unit,
        display_unit=_display_unit_for(field_name, raw_unit),
        grid=grid,
        axes=tuple(grid['axis_order']),
        association='cell',
        shape=values.shape,
        dtype=values.dtype,
        state='design',
    )


def load_result_header(path) -> ResultHeader:
    """Read validated result metadata, grid, and field names without field arrays."""
    data = read_record_selection(
        path,
        FieldResult,
        'FieldResult',
        load_array=lambda node: node[:1] == ('grid',),
    )
    grid_shape = _validate_selected_result_data(data)
    design_fields = data['metadata'].get('design_fields')
    available_design: tuple[str, ...] = ()
    if isinstance(design_fields, Mapping):
        available_design = tuple(
            key
            for key, item in design_fields.items()
            if key in _DESIGN_FIELD_UNITS
            and isinstance(item, (np.ndarray, ArrayDescriptor))
            and item.shape == grid_shape
        )
    return ResultHeader(
        result_id=str(data['result_id']),
        case_id=str(data['case_id']),
        backend_id=str(data['backend_id']),
        schema_version=str(data['schema_version']),
        backend_version=str(data['backend_version']),
        grid=freeze_mapping(data['grid']),
        available_fields=tuple(data['fields']),
        available_design_fields=available_design,
        field_metadata=freeze_mapping(data['field_metadata']),
        run_status=freeze_mapping(_strip_unloaded_arrays(data['run_status'])),
        metadata=freeze_mapping(_strip_unloaded_arrays(data['metadata'])),
        model_refs=tuple(data['model_refs']),
    )
