"""Read independent result reports while the native library owns their buffers."""
import ast
import ctypes as ct
import json
import weakref

from . import _native_result as core
from ._native_result_stage import (
    Events, HostError, Input, InputError, Metric, Output, P, Spec, Z,
    _Evidence, _cause, _text,
)

__all__ = ['query_result', 'METRICS', 'APPLICABILITY', 'PHYSICAL_BALANCE', 'QUALIFICATION']

METRICS = 0
APPLICABILITY = 1
PHYSICAL_BALANCE = 2
QUALIFICATION = 3


def _spec(value):
    return Spec(*(_text(getattr(value, name)) for name in ('name', 'unit', 'definition_version', 'description')))


def query_result(result, query, declaration_dimension, *, metric_spec=None, metrics=None):
    """Return the decoded report and metric rows from the result library."""
    packed = _Evidence()
    output, diagnostics, token = Output(struct_size=ct.sizeof(Output)), core._Diagnostics(), ct.c_uint64()
    error = ct.create_string_buffer(4096)

    try:
        packed.pack(result, query, declaration_dimension)
        library = core.result_library.get()
        owner = weakref.proxy(packed)

        @Events
        def events(context, values, failure):
            try:
                core.notify(values.contents, stacklevel=6)
                return 0
            except BaseException as exception:
                identity = owner.token(exception)
                message = _text(str(exception))
                owner.keep.append(message)
                failure[0] = HostError(_cause(exception), 0, identity, message)
                return 1

        errors = packed.sequence(InputError, packed.errors)
        none_values = packed.sequence(ct.c_void_p, packed.none_values)
        argument = Input(3, ct.sizeof(Input), ct.pointer(packed.raw), errors, len(errors), none_values, len(none_values),
            packed.density, packed.split, packed.inlet_temperature, packed.invalid_mode_repr,
            packed.dimension_index, packed.dimension_slice, packed.qualification_error,
            packed.quick_access_recorded, packed.quick_access, None, events)
        selection = _spec(metric_spec) if metric_spec is not None else None
        statuses = [Metric(_text(name), Spec(b'', b'', b'', b''), 0, 0., _text(value.status), None)
                    for name, value in (metrics or {}).items()]
        supplied = packed.sequence(Metric, statuses)
        call = library.bind('tpmshx_result_stage_query_v3',
            [P(Input), ct.c_uint32, P(Spec), P(Metric), Z,
             P(Output), P(core._Diagnostics), P(ct.c_uint64), P(ct.c_char), Z])
        release = library.bind('tpmshx_result_stage_release_v1', [P(Output)], None)
        status = call(ct.byref(argument), query, ct.byref(selection) if selection is not None else None,
            supplied, len(statuses), ct.byref(output), ct.byref(diagnostics), ct.byref(token), error, len(error))
        core.notify(diagnostics, stacklevel=5)
        if status:
            if token.value:
                raise packed.exceptions[token.value]
            message = error.value.decode('utf-8', errors='replace') or f'native result stage failed with status {status}'
            if status == 1:
                raise ValueError(message)
            if status == 2:
                raise MemoryError(message)
            if status == 4:
                cause = {1: ZeroDivisionError, 2: OverflowError, 3: ValueError, 4: TypeError,
                         5: IndexError, 6: KeyError, 7: NotImplementedError}.get(diagnostics.python_cause)
                if cause is None:
                    raise RuntimeError('native result stage returned an invalid numerical cause')
                if cause is KeyError:
                    message = ast.literal_eval(message)
                raise cause(message)
            raise RuntimeError(message)
        report = json.loads(output.json)
        if query != METRICS:
            return report, ()
        rows = []
        for index in range(output.metric_count):
            row = output.metrics[index]
            spec = tuple(getattr(row.spec, field).decode('utf-8')
                         for field in ('name', 'unit', 'definition_version', 'description'))
            rows.append((row.name.decode('utf-8'), row.value if row.has_value else None,
                         spec, row.status.decode('utf-8'), row.reason.decode('utf-8')))
        return report, rows
    finally:
        try:
            if output.owner:
                release(ct.byref(output))
        finally:
            # Deferred tracebacks can refer to the query and its borrowed fields.
            packed.exceptions.clear()
            packed.array_errors.clear()
