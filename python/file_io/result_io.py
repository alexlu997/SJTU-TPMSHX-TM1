"""Archive completed or explicitly rejected native results independently of solvers."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np

from tm1.data_types.field_result import FieldResult, validate_field_result_invariants
from tm1.data_types.model_refs import ModelRef, freeze_mapping, freeze_value
from tm1.data_types.persistence_validation import validate_result
from .hdf5_data import ArrayDescriptor, read_record, read_record_selection, write_record

# Cell-shaped TPMS geometry design fields documented in docs/contracts/three_module_v1/.
_DESIGN_FIELD_UNITS: dict[str, str] = {
    'L_field_m': 'm',
    't_field_m': 'm',
}


@dataclass(frozen=True)
class SelectedResultField:
    """One validated field and its physical grid from a saved FieldResult."""

    source_result_id: str
    name: str
    values: np.ndarray
    unit: str
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


def _validate_selected_result_data(data: dict[str, Any]) -> tuple[int, ...]:
    """Run the same identity, container, and schema validation as load_result."""
    record = SimpleNamespace(**data)
    validate_field_result_invariants(record, freeze=False, preserved_types=(ArrayDescriptor,))
    validate_result(record)
    grid = data['grid']
    return tuple(len(grid['d' + axis]) for axis in grid['axis_order'])


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
    return SelectedResultField(
        source_result_id=str(data['result_id']),
        name=field_name,
        values=values,
        unit=str(meta['unit']),
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
    return SelectedResultField(
        source_result_id=str(data['result_id']),
        name=field_name,
        values=values,
        unit=_DESIGN_FIELD_UNITS[field_name],
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
        run_status=freeze_mapping(data['run_status'], preserved_types=(ArrayDescriptor,)),
        metadata=freeze_mapping(data['metadata'], preserved_types=(ArrayDescriptor,)),
        model_refs=tuple(data['model_refs']),
    )
