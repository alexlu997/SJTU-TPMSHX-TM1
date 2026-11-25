"""Query a single inlet without a mesh or a prepared case."""
import ctypes as ct
from functools import lru_cache

from . import _native_preparation_case as abi, _native_properties, preparation_host as host
from ._native_values import TOPOLOGIES, borrow_text, real_scalar
from .stage_libraries import preparation_library


@lru_cache(maxsize=1)
def _inlet_query_function(path):
    owner = preparation_library.load(path)
    return owner.bind('tpmshx_query_inlet_properties_v2', [
        ct.POINTER(abi._InletQueryInput), ct.POINTER(abi._Callbacks),
        ct.POINTER(abi._InletQueryResult), ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S])


def inlet_query(topology, cell, wall, velocity, temperature, pressure, fluid,
                selection, geometry, records, notice):
    """Transport one float64 scalar query without a mesh or a prepared case."""
    from sjtu_tpmshx.physical_models import fluid_props

    buffers = []
    fluid_name = fluid_props.get(fluid, sco2_nu=selection).name
    if fluid_name in ('sco2', 'co2') and pressure is None:
        if fluid_name == 'co2':
            raise ValueError('CO2 requires absolute pressure P in Pa')
        raise ValueError('sCO2 properties require pressure P [Pa]; caller passed P=None. '
                         'Fix the call site to forward the inlet/local pressure.')

    def real(value, name):
        return real_scalar(value, name=name, allow_nonfinite=True)

    diameter, epsilon = real(geometry['D_h'], 'D_h'), real(geometry['epsilon_A'], 'epsilon_A')
    length, thickness = real(cell, 'L_cell_mm'), real(wall, 't_mm')
    speed, temp = real(velocity, 'u'), real(temperature, 'T')
    press = 0. if fluid_name == 'water' else real(pressure, 'P')
    settings = abi._Nu()
    have_nu = fluid_name == 'sco2' and selection is not None
    if have_nu:
        settings.mode = int(selection.mode == 'experimental')
        for index, name in enumerate(('alpha_D', 'alpha_G')):
            value = getattr(selection, name)
            settings.have_alpha[index] = value is not None
            settings.alpha[index] = real(value, name) if value is not None else 0.
        for name in ('parameter_version', 'source', 'applicability'):
            setattr(settings, name, borrow_text(getattr(selection, name), buffers))
    key = abi._InletKey(abi._GeometryKey(TOPOLOGIES.index(topology), length, thickness),
        abi._FLUIDS.index(fluid_name), speed, temp, press, have_nu, settings, False)
    source = abi._InletQueryInput(1, ct.sizeof(abi._InletQueryInput), key, diameter, epsilon, fluid_name == 'co2')

    def validate(stage, _step):
        if stage != 4:
            raise RuntimeError(f'unknown property query host stage {stage}')

    def observe(value, bounds_list, cached, scalar):
        host.observe_range(value, bounds_list, cached, scalar, selection, records=records)

    callbacks, callback_errors = host._callback_bridge(
        validate, observe_range=observe, observe_notice=notice)
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
    return list(result.values)
