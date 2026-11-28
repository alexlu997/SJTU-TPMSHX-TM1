"""Query a single inlet without a mesh or a prepared case."""
import ctypes as ct
from functools import lru_cache

from . import _native_preparation_case as abi, _native_properties, preparation_host as host
from ._native_diagnostics import native_error
from ._native_values import geometry_topology, borrow_text, real_scalar
from .stage_libraries import preparation_library


@lru_cache(maxsize=1)
def _inlet_functions(owner, cached):
    symbol = 'tpmshx_preparation_cached_inlet_v1' if cached else 'tpmshx_query_inlet_properties_v2'
    call = owner.bind(symbol, [
        ct.POINTER(abi._CachedInletInput if cached else abi._InletQueryInput), ct.POINTER(abi._Callbacks),
        ct.POINTER(abi._CachedInletResult if cached else abi._InletQueryResult), ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S])
    release = (owner.bind('tpmshx_preparation_cached_inlet_release_v1', [ct.POINTER(abi._CachedInletResult)], None)
               if cached else None)
    return call, release


def query_values(topology, cell, wall, velocity, temperature, pressure, fluid_name,
                 selection, geometry, observe, notice, observe_event, property_error, water_error, *, exact_co2_drag, co2_geometry=False, records=None,
                 validate_geometry=None, validate_model=None):
    """Pack one inlet and return its twelve inline float64 values."""
    buffers = []

    def real(value, name):
        return real_scalar(value, name=name, allow_nonfinite=True)

    cached = geometry is None
    if not cached:
        diameter, epsilon = real(geometry['D_h'], 'D_h'), real(geometry['epsilon_A'], 'epsilon_A')
    length, thickness = real(cell, 'L_cell_mm'), real(wall, 't_mm')
    speed, temp = real(velocity, 'u'), real(temperature, 'T')
    press = real(pressure, 'P')
    settings = abi._Nu()
    if selection is not None:
        settings.mode = {'cfd_smooth': 0, 'experimental': 1}.get(selection.mode, 2)
        for index, name in enumerate(('alpha_D', 'alpha_G')):
            value = getattr(selection, name)
            settings.have_alpha[index] = value is not None
            settings.alpha[index] = real(value, name) if value is not None else 0.
        for name in ('parameter_version', 'source', 'applicability'):
            setattr(settings, name, borrow_text(getattr(selection, name), buffers))
    key = abi._InletKey(abi._GeometryKey(geometry_topology(topology), length, thickness),
        abi._FLUIDS.index(fluid_name), speed, temp, press, selection is not None, settings, co2_geometry)
    if cached:
        source = abi._CachedInletInput(1, ct.sizeof(abi._CachedInletInput), key)
    else:
        source = abi._InletQueryInput(1, ct.sizeof(abi._InletQueryInput), key, diameter, epsilon, exact_co2_drag)

    def validate(stage, step):
        if stage != 4:
            raise RuntimeError(f'unknown property query host stage {stage}')
        if step == 10 and validate_geometry is not None:
            validate_geometry()
        elif cached and step == 0 and validate_model is not None:
            validate_model()

    callbacks, callback_errors = host._callback_bridge(
        validate, observe_range=observe, observe_notice=notice, observe_event=observe_event)
    kind = abi._CachedInletResult if cached else abi._InletQueryResult
    result = kind(1, ct.sizeof(kind))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    call, release = _inlet_functions(preparation_library.get(), cached)
    status = call(
        ct.byref(source), ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    try:
        if callback_errors:
            raise callback_errors[0]
        if status and failure.have_property:
            if cached and status == 1 and failure.property.reason in (1, 2, 3, 4) and not failure.property.fp.python_cause:
                _native_properties.raise_geometry_error(call.__name__, failure.property.reason,
                    topology, cell, wall, error.value.decode('utf-8'))
            fp = failure.property.fp
            _native_properties._floating_events(fp.events[:fp.event_count])
            text = error.value.decode('utf-8', errors='replace')
            if fp.python_cause:
                raise native_error('preparation', call.__name__, status, text, cause=fp.python_cause,
                                   events=tuple(fp.events[:fp.event_count]))
            try:
                cause = failure.causes[0].message.decode('utf-8', errors='replace') if failure.cause_count else None
                property_error(status, text, cause)
            except ValueError as problem:
                native_error('preparation', call.__name__, status, text, problem=problem, T_K=temp, P_abs_Pa=press,
                             state_reason=failure.property.reason)
                raise
        host._check_status(call.__name__, status, error, failure, water_error)
        if not cached:
            return list(result.values)
        evidence = result.evidence
        for i in range(evidence.range_count):
            key, record = host._range_record(evidence.ranges[i], evidence.range_bounds_list[i])
            records[key[:-1]] = record
        for i, value in enumerate(evidence.warnings[:evidence.warning_count]):
            records['native-preparation', i] = host.read_text(value)
        return host.geometry_scalars(result.geometry), list(result.values)
    finally:
        if release is not None:
            release(ct.byref(result))
