"""Query a single inlet without a mesh or a prepared case."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from . import _native_preparation_case as abi, _native_properties, preparation_host as host
from ._native_values import TOPOLOGIES, borrow_text, read_text as _text
from .stage_libraries import preparation_library


@lru_cache(maxsize=1)
def _inlet_query_function(path):
    owner = preparation_library.load(path)
    return owner.bind('tpmshx_query_inlet_properties_v1', [
        ct.POINTER(abi._InletQueryInput), ct.POINTER(abi._CacheCallbacks),
        ct.POINTER(abi._InletQueryResult), ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S])


def inlet_query(topology, cell, wall, velocity, temperature, pressure, fluid,
                selection, geometry, records, notice):
    """Transport one scalar query without a mesh or a prepared case."""
    from sjtu_tpmshx.physical_models import fluid_props

    errors, buffers, range_errors = {}, [], {}
    model = None
    try:
        model = fluid_props.get(fluid, sco2_nu=selection)
    except Exception as problem:
        errors[1] = problem
    fluid_name = model.name if model is not None else 'air'
    eos = fluid_name in ('sco2', 'co2')

    def pack(value, step, *, coerce=False):
        try:
            # The original property owner emits conversion warnings at each use.
            if coerce and isinstance(value, np.complexfloating):
                value = value.real
            array, scalar, layout = _native_properties._typed(value, coerce=coerce)
            return float(array), abi._Kind(scalar.precision, scalar.strong, layout)
        except Exception as problem:
            errors.setdefault(step, problem)
            return 0., abi._Kind(64, 0, 0)

    diameter, diameter_kind = pack(geometry['D_h'], 0)
    epsilon, epsilon_kind = pack(geometry['epsilon_A'], 9)
    length, length_kind = pack(cell, 7)
    thickness, thickness_kind = pack(wall, 8)
    speed, speed_kind = pack(velocity, 6)
    temp, temp_kind = pack(temperature, 'temperature' if eos else 2, coerce=fluid_name != 'air')
    if fluid_name == 'air' and 2 in errors:
        # A property observes its source temperature before its operand check.
        range_errors[2] = errors.pop(2)
        try:
            observed = temperature.real if isinstance(temperature, np.complexfloating) else temperature
            temp = float(np.asarray(observed, dtype=float))
        except Exception as problem:
            errors[2] = problem
    if fluid_name == 'water':
        press, press_kind = 0., abi._Kind(64, 0, 0)
    else:
        press, press_kind = pack(pressure, 'pressure' if eos else 4,
                                 coerce=fluid_name != 'air')
    settings = abi._Nu()
    if model is not None and model.name == 'sco2' and selection is not None:
        settings.mode = int(selection.mode == 'experimental')
        for index, name in enumerate(('alpha_D', 'alpha_G')):
            value = getattr(selection, name)
            settings.have_alpha[index] = value is not None
            settings.alpha[index] = float(value) if value is not None else 0.
        for name in ('parameter_version', 'source', 'applicability'):
            setattr(settings, name, borrow_text(getattr(selection, name), buffers))
    key = abi._InletKey(abi._GeometryKey(TOPOLOGIES.index(topology), length, thickness,
        length_kind, thickness_kind), abi._FLUIDS.index(fluid_name), speed, temp, press,
        abi._InletKinds(speed_kind, temp_kind, press_kind),
        model is not None and model.name == 'sco2' and selection is not None, settings, False)
    source = abi._InletQueryInput(1, ct.sizeof(abi._InletQueryInput), key, diameter, epsilon,
                             diameter_kind, epsilon_kind, fluid == 'co2')

    def conversion_warning(value, origin, occurrence=0):
        if isinstance(value, np.complexfloating):
            host._source_warning(origin, 'Casting complex values to real discards the imaginary part',
                call='asarray', occurrence=occurrence, category=np.exceptions.ComplexWarning)

    def validate(stage, step):
        if stage != 4:
            raise RuntimeError(f'unknown property query host stage {stage}')
        if step in (2, 3, 4, 5) and eos:
            if pressure is None:
                if fluid_name == 'co2':
                    raise ValueError('CO2 requires absolute pressure P in Pa')
                raise ValueError('sCO2 properties require pressure P [Pa]; caller passed P=None. '
                                 'Fix the call site to forward the inlet/local pressure.')
            from sjtu_tpmshx.physical_models import co2_props, sco2_props
            origin = co2_props._states if fluid_name == 'co2' else sco2_props.sco2_prop
            conversion_warning(temperature, origin)
            if 'temperature' in errors:
                raise errors['temperature']
            conversion_warning(pressure, origin, int(fluid_name == 'sco2'))
            if 'pressure' in errors:
                raise errors['pressure']
        if step in (2, 3, 4, 5) and fluid_name in ('air', 'water'):
            from sjtu_tpmshx.physical_models import tpms_props
            conversion_warning(temperature, tpms_props._warn_range_once)
        if step == 2 and fluid_name == 'air':
            np.asarray(temperature.real if isinstance(temperature, np.complexfloating) else temperature, dtype=float)
            if not isinstance(temperature, (float, int, np.number, np.ndarray)):
                range_errors[2] = TypeError(
                    f"unsupported operand type(s) for /: '{type(temperature).__name__}' and 'float'")
        if step == 4 and fluid_name == 'air' and not isinstance(
                pressure, (float, int, np.number, np.ndarray)):
            if isinstance(pressure, (str, bytes, list, tuple)):
                raise TypeError("can't multiply sequence by non-int of type 'float'")
            raise TypeError(f"unsupported operand type(s) for *: '{type(pressure).__name__}' and 'float'")
        if step in errors:
            raise errors[step]
        if step == 8:
            float(cell), float(wall), float(geometry['epsilon_A'])

    def observe(value, bounds_list, cached, scalar):
        host.observe_range(value, bounds_list, cached, scalar, selection, records=records)
        if range_errors:
            raise range_errors[2]
        if fluid_name == 'water' and _text(value.quantity) == 'T':
            conversion_warning(temperature, _native_properties._typed)

    callbacks, _descriptor, callback_errors = host._callback_bridge(
        validate, observe_range=observe, observe_notice=notice, query=True)
    result = abi._InletQueryResult(1, ct.sizeof(abi._InletQueryResult))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    status = _inlet_query_function(preparation_library.path())(
        ct.byref(source), ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    if callback_errors:
        raise callback_errors[0]
    if status and failure.have_property:
        import errno
        import os
        fp = failure.property.fp
        _native_properties._floating_events(fp.events[:fp.event_count])
        text = error.value.decode('utf-8', errors='replace')
        if fp.python_cause == 2:
            raise OverflowError(errno.ERANGE, os.strerror(errno.ERANGE))
        if fp.python_cause:
            exception = {1: ZeroDivisionError, 3: ValueError, 4: TypeError}.get(fp.python_cause, RuntimeError)
            raise exception(text)
        if status == 11 and fluid_name == 'co2':
            if failure.property.reason in (1, 5):
                raise ValueError(text) from None
            prefix = ('CO2 requires a stable single-phase PT state; '
                      'saturation, two-phase and critical-point states are unsupported. ')
            raise ValueError(text) from ValueError(text.removeprefix(prefix))
        if status in (10, 12):
            raise ValueError(text) from None
    host._check_status(status, error, failure)
    values = []
    for item in result.values:
        if item.category:
            value = complex(item.real, item.imaginary)
            if item.kind.strong:
                value = np.dtype(f'complex{item.kind.precision * 2}').type(value)
        else:
            value = host._restore(item.real, item.kind)
        values.append(value)
    return values
