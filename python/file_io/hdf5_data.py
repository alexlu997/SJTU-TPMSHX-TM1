"""Versioned JSON data tree plus typed native HDF5 arrays, without pickle."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
import base64
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import numpy as np

from tm1.data_types.case_data import SCHEMA_VERSION
from tm1.data_types.model_refs import ModelRef


@dataclass(frozen=True)
class ArrayDescriptor:
    """Validated shape and dtype metadata for an unloaded HDF5 array dataset."""

    shape: tuple[int, ...]
    dtype: np.dtype[Any]


def _encode(value, arrays):
    if isinstance(value, np.ndarray):
        name = f'arrays/{len(arrays)}'
        arrays[name] = value
        return {'array': name, 'dtype': value.dtype.str, 'shape': list(value.shape)}
    if isinstance(value, np.generic):
        return _encode(value.item(), arrays)
    if isinstance(value, Mapping):
        return {'mapping': {key: _encode(item, arrays) for key, item in value.items()}}
    if isinstance(value, (tuple, list)):
        return {'sequence': [_encode(item, arrays) for item in value]}
    if isinstance(value, ModelRef):
        return {'model_ref': {item.name: _encode(getattr(value, item.name), arrays) for item in fields(value)}}
    if isinstance(value, bytes):
        return {'bytes': base64.b64encode(value).decode('ascii')}
    if isinstance(value, float) and not math.isfinite(value):
        return {'nonfinite': 'nan' if math.isnan(value) else '+inf' if value > 0 else '-inf'}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'unsupported persistent data: {type(value).__name__}')


def _arrays_group(source, state, h5py):
    if 'arrays_group' not in state:
        if not isinstance(source.get('arrays', getlink=True), h5py.HardLink):
            raise ValueError('external or symbolic HDF5 resources are unsupported')
        group = source['arrays']
        if not isinstance(group, h5py.Group):
            raise ValueError('external or symbolic HDF5 resources are unsupported')
        state['arrays_group'] = group
    return state['arrays_group']


def _validate_array_dataset(value, source, state, h5py):
    name = value['array']
    if not isinstance(name, str) or re.fullmatch(r'arrays/[0-9]+', name) is None:
        raise ValueError('array resource must be local to the HDF5 arrays group')
    group = _arrays_group(source, state, h5py)
    leaf = name.split('/', 1)[1]
    if not isinstance(group.get(leaf, getlink=True), h5py.HardLink):
        raise ValueError('external or symbolic HDF5 resources are unsupported')
    dataset = group[leaf]
    if not isinstance(dataset, h5py.Dataset) or dataset.dtype.kind not in 'biuf':
        raise ValueError('arrays must contain real numeric or boolean data')
    if dataset.is_virtual or dataset.external:
        raise ValueError('external dataset storage is unsupported')
    if dataset.dtype.str != value['dtype'] or list(dataset.shape) != value['shape']:
        raise ValueError('array dtype or shape disagrees with its descriptor')
    return dataset


def _decode(value, source, *, load_array: Callable[[tuple[str | int, ...]], bool] | None = None,
            path: tuple[str | int, ...] = (), state: dict[str, Any] | None = None):
    if state is None:
        import h5py
        state = {'h5py': h5py}
    if not isinstance(value, dict):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ValueError('invalid data node')
    if set(value) == {'array', 'dtype', 'shape'}:
        dataset = _validate_array_dataset(value, source, state, state['h5py'])
        if load_array is None or load_array(path):
            return dataset[...]
        return ArrayDescriptor(shape=tuple(dataset.shape), dtype=dataset.dtype)
    if set(value) == {'mapping'} and isinstance(value['mapping'], dict):
        return {key: _decode(item, source, load_array=load_array, path=(*path, key), state=state)
                for key, item in value['mapping'].items()}
    if set(value) == {'sequence'} and isinstance(value['sequence'], list):
        return tuple(_decode(item, source, load_array=load_array, path=(*path, index), state=state)
                     for index, item in enumerate(value['sequence']))
    if set(value) == {'model_ref'} and isinstance(value['model_ref'], dict):
        return ModelRef(**{key: _decode(item, source, load_array=None, path=(*path, key), state=state)
                           for key, item in value['model_ref'].items()})
    if set(value) == {'bytes'}:
        return base64.b64decode(value['bytes'], validate=True)
    if set(value) == {'nonfinite'} and value['nonfinite'] in ('nan', '+inf', '-inf'):
        return float(value['nonfinite'])
    raise ValueError('unknown encoded data node')


def _open_descriptor(source, kind):
    import h5py
    if source.attrs.get('schema_version') != SCHEMA_VERSION or source.attrs.get('record_kind') != kind:
        raise ValueError('unsupported file schema or record kind')
    if not isinstance(source.get('descriptor', getlink=True), h5py.HardLink):
        raise ValueError('descriptor must be a local HDF5 dataset')
    dataset = source['descriptor']
    if not isinstance(dataset, h5py.Dataset):
        raise ValueError('descriptor must be a local HDF5 dataset')
    if dataset.is_virtual or dataset.external:
        raise ValueError('external dataset storage is unsupported')
    return json.loads(dataset.asstr()[()])


def write_record(path, record, kind):
    import h5py
    path = Path(path)
    arrays = {}
    data = {item.name: getattr(record, item.name) for item in fields(record)}
    descriptor = json.dumps(_encode(data, arrays), ensure_ascii=False, allow_nan=False)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    os.close(fd)
    try:
        with h5py.File(temporary, 'w') as target:
            target.attrs['schema_version'] = SCHEMA_VERSION
            target.attrs['record_kind'] = kind
            target.create_dataset('descriptor', data=descriptor, dtype=h5py.string_dtype('utf-8'))
            target.create_group('arrays')
            for name, array in arrays.items():
                target.create_dataset(name, data=array)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def read_record_selection(path, record_type, kind, *, load_array: Callable[[tuple[str | int, ...]], bool]):
    """Validate an HDF5 record tree and read bytes only for selected array paths."""
    import h5py
    with h5py.File(path, 'r') as source:
        descriptor = _open_descriptor(source, kind)
        data = _decode(descriptor, source, load_array=load_array)
    expected = {item.name for item in fields(record_type)}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError('record fields are missing or unknown')
    return data


def read_record(path, record_type, kind):
    import h5py
    with h5py.File(path, 'r') as source:
        descriptor = _open_descriptor(source, kind)
        data = _decode(descriptor, source)
    expected = {item.name for item in fields(record_type)}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError('record fields are missing or unknown')
    return record_type(**data)
