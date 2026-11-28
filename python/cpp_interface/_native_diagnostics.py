"""Decode a native failure with the catalog for its image and versioned entry."""
import builtins
import errno
from functools import cache
import os

from tm1.run_control.cancellation import CancelledError
from tm1.run_control.diagnostics import (
    ChokedFlowError, QuickDesignWaterFieldError, WaterStateError, diagnosed, diagnostic_catalog,
)


@cache
def _operations():
    return {(family['image'], operation): family
            for family in diagnostic_catalog()['native_operations'].values()
            for operation in family['operations']}


def native_code(image, operation, status, *, kind=0, cause=0, stop=None):
    """Return the producer code. A successful stop has no error record."""
    unknown = 'contract.unknown_status'
    family = _operations().get((image, operation))
    if family is None:
        return unknown
    if status == 0:
        if stop is None:
            return None
        return family.get('stop', {}).get(str(stop), unknown)
    code = family['status'].get(str(status), unknown)
    if cause and status in family.get('cause_status', ()):
        return family['cause'].get(str(cause), unknown)
    if kind and status != 2 and str(status) in family['status'] and 'kind' in family:
        return family['kind'].get(str(kind), unknown)
    return code


_DOMAIN_ERRORS = {cls.__name__: cls for cls in (
    ChokedFlowError, QuickDesignWaterFieldError, WaterStateError, CancelledError)}


@cache
def result_host_causes():
    """Return the public exception classes and their result ABI cause numbers."""
    catalog = diagnostic_catalog()
    return tuple((getattr(builtins, catalog['codes'][code]['exception']), int(number))
                 for number, code in catalog['native_operations']['result']['cause'].items())


def native_error(image, operation, status, message, *, cause=0, kind=0, stop=None,
                 causes=(), problem=None, **evidence):
    """Build the public exception and copy its raw identity and ordered causes."""
    family = _operations().get((image, operation), {})
    code = native_code(image, operation, status, cause=cause, kind=kind, stop=stop)
    if 'unresolved_token' in evidence:
        code = 'contract.unknown_status'
    exception = diagnostic_catalog()['codes'][code]['exception']
    cls = _DOMAIN_ERRORS.get(exception) or getattr(builtins, exception)
    if problem is None:
        if code == 'numeric.overflow' and image == 'preparation':
            problem = cls(errno.ERANGE, os.strerror(errno.ERANGE))
        else:
            problem = cls(message)
    suffix = operation.rpartition('_v')[2]
    details = dict(image=image, operation=operation, version=int(suffix) if suffix.isdigit() else None,
                   status=status, kind=kind, cause=cause, stop=stop, causes=tuple(causes),
                   severity='error', stage=family.get('stage', 'unknown'), **evidence)
    if code == 'internal.error':
        details.update(type=exception, notes=())
    return diagnosed(problem, code, **details)
