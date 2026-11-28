"""Shared domain exceptions and diagnostic records."""
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
import json
import math

import numpy as np


class WaterStateError(ValueError):
    """The specified water state is outside the supported range or is unconfirmed."""


class QuickDesignWaterFieldError(WaterStateError):
    """A Quick Design field fails the liquid-water requirements."""


class ChokedFlowError(RuntimeError):
    """The compressible flow fails an envelope requirement."""


@cache
def diagnostic_catalog():
    """Load the versioned catalog from the installed package."""
    resource = files('tm1.model_configs') / 'diagnostic_codes_v1.json'
    return json.loads(resource.read_text(encoding='utf-8'))


def record_value(value):
    """Copy a diagnostic value. Encode nonfinite evidence and retain sequence order."""
    if isinstance(value, np.ndarray):
        value = value.tolist()
    elif isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError('diagnostic detail names must be strings')
        return {key: record_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(record_value(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        return 'NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity'
    if value is None or type(value) in (str, float, int, bool):
        return value
    raise TypeError(f'unsupported diagnostic value {type(value).__name__}')


def _matches(value, kind):
    if '|' in kind:
        return any(_matches(value, part) for part in kind.split('|'))
    if kind.endswith('[]'):
        return isinstance(value, tuple) and all(_matches(item, kind[:-2]) for item in value)
    if kind == 'number':
        return type(value) in (float, int) or value in ('NaN', 'Infinity', '-Infinity')
    if kind == 'record':
        return isinstance(value, dict) and value.keys() == {'code', 'message', 'details'}
    return type(value) is {'null': type(None), 'integer': int, 'string': str, 'object': dict}[kind]


def diagnostic_record(code, message, details):
    """Return a detached record with its required details in catalog units."""
    catalog = diagnostic_catalog()
    definition = catalog['codes'][code]
    if not isinstance(message, str) or not isinstance(details, Mapping):
        raise TypeError('a diagnostic requires text and a detail object')
    data = record_value(details)
    for group in definition['required']:
        for field in catalog['detail_groups'].get(group, (group,)):
            if field not in data:
                raise ValueError(f'{code} requires {field}')
    for field, value in data.items():
        kind = catalog['detail_types'].get(field)
        if kind is not None and not _matches(value, kind):
            raise TypeError(f'{code}.{field} requires {kind}')
    return {'code': code, 'message': message, 'details': data}


def diagnosed(problem, code, **details):
    """Attach a producer record to the original exception."""
    problem.diagnostic = diagnostic_record(code, str(problem), details)
    return problem
