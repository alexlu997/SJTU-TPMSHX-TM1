"""Pack native Quick Design preparation inputs and copy the returned data."""
from contextlib import contextmanager
import ctypes as ct
from functools import lru_cache
from types import SimpleNamespace

import numpy as np

from . import _native_flow, _native_properties
from ._native_diagnostics import native_error
from ._native_preparation_case import _GeometryCache, _Sample
from ._native_preparation_case import (_QuickInputV2 as _Input, _QuickPreparedV2 as _Prepared,
                                       _QuickPressureV2 as _Pressure)
from ._native_values import DoubleArray as _Array, borrow_text, copy_array, real_scalar
from .stage_libraries import preparation_library


_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_NAMES = ('l', 't', 's', 'Lx', 'height', 'k_s', 'tol', 'mdot_h', 'mdot_c',
          'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c')
_GEOMETRY_FIELDS = tuple(name for name, _ in _GeometryCache._fields_)
_GeometryFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_GeometryCache), ct.POINTER(_U))
_EosFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, _U, _D, _D,
                            ct.POINTER(_D), _S, ct.POINTER(_S), ct.POINTER(_U))
_Callbacks = type('QuickCallbacks', (ct.Structure,), {'_fields_': [
    ('abi_version', _U), ('struct_size', _S), ('context', ct.c_void_p),
    ('geometry_cache', _GeometryFunction), ('eos_cache', _EosFunction)]})


class _Bindings:
    def __init__(self, path):
        self.owner = preparation_library.load(path)
        arguments = [ct.POINTER(_Input), ct.POINTER(_Callbacks)]
        self.prepare = self.owner.bind('tpmshx_prepare_quick_design_v2',
            [*arguments, ct.POINTER(_Prepared), ct.POINTER(ct.c_char), _S])
        self.pressure = self.owner.bind('tpmshx_quick_pressure_fractions_v2',
            [*arguments, ct.POINTER(_Pressure), ct.POINTER(ct.c_char), _S])
        self.release = self.owner.bind('tpmshx_quick_prepared_release_v2', [ct.POINTER(_Prepared)], None)
        self.range_query = self.owner.bind('tpmshx_preparation_collect_range_v1',
            [_Array, _D, _D, ct.POINTER(_Sample), ct.POINTER(ct.c_char), _S])

    def collect_range(self, values, lower, upper):
        storage = np.require(values, dtype=np.float64, requirements=['C', 'A'])
        view = _Array(storage.ctypes.data_as(ct.POINTER(_D)), storage.size)
        result, error = _Sample(), ct.create_string_buffer(2048)
        status = self.range_query(view, lower, upper, ct.byref(result), error, len(error))
        if status:
            _native_flow._check_status(self.range_query.__name__, status, error)
        return result


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


class _CacheCallbacks:
    """Copy cache values across the C interface and save Python exceptions."""

    def __init__(self, geometry_cache, eos_cache):
        self.geometry_cache = geometry_cache
        self.eos_cache = eos_cache
        self.errors = []

    def geometry(self, _context, action, pointer, hit):
        try:
            if action == 0:
                values = self.geometry_cache(None)
                hit[0] = values is not None
                if values is not None:
                    for field, value in zip(_GEOMETRY_FIELDS, values):
                        setattr(pointer.contents, field, float(value))
            elif action == 1:
                stored = [getattr(pointer.contents, field) for field in _GEOMETRY_FIELDS]
                self.geometry_cache(tuple(stored))
                hit[0] = 0
            else:
                raise RuntimeError('unknown Quick geometry cache operation')
            return 0
        except BaseException as problem:
            self.errors.append(problem)
            return 1

    def eos(self, _context, action, fluid, index, temperature, pressure, values, capacity, count, hit):
        try:
            name = 'sco2' if fluid == 2 else 'co2'
            if action:
                stored = [values[n] for n in range(count[0])]
                self.eos_cache(name, index, temperature, pressure, tuple(stored))
            else:
                data = self.eos_cache(name, index, temperature, pressure, None)
                hit[0] = data is not None
                if data is not None:
                    if len(data) > capacity:
                        raise RuntimeError('Quick EOS cache value exceeds the native buffer')
                    count[0] = len(data)
                    for n, item in enumerate(data):
                        values[n] = float(item)
            return 0
        except BaseException as problem:
            self.errors.append(problem)
            return 1


def _copy_prepared(output):
    shape = tuple(output.shape)
    controls = output.controls
    # A generator would convert StopIteration from the copier into RuntimeError.
    axes = [(copy_array(widths), copy_array(edges)) for widths, edges in zip(output.widths, output.edges)]
    return SimpleNamespace(
        axes=tuple(axes),
        epsilon=copy_array(output.epsilon, shape), epsilon_a=copy_array(output.epsilon_a, shape),
        solid_conductivity=copy_array(output.solid_conductivity, shape),
        controls=SimpleNamespace(**{name: getattr(controls, name) for name, _ in controls._fields_}),
        fractions=tuple(output.fractions), cell_length_m=output.cell_length_m, wall_thickness_m=output.wall_thickness_m,
        area_density_per_m=output.geometry.area_density_per_m, hydraulic_diameter_m=output.geometry.hydraulic_diameter_m)


@contextmanager
def _native_result(state, geometry_cache, eos_cache, check_model_error, observe):
    """Keep the native output live until the binding has copied it."""
    bindings = _bindings(preparation_library.path())
    keepalive = []
    source = _Input(2, ct.sizeof(_Input))
    for n, value in enumerate(state.values):
        source.values[n] = real_scalar(value, name='quick-design ' + _NAMES[n])
    for name, value in (('topology', state.topo), ('arrangement', state.arrangement),
                        ('property_mode', state.prop_model)):
        setattr(source, name, borrow_text(str(value), keepalive))
    for index, fluid in enumerate(state.fluids):
        source.fluids[index] = borrow_text(fluid, keepalive)
    source.have_height = 1
    source.have_chi, source.chi = state.chi is not None, 0. if state.chi is None else real_scalar(state.chi, name='chi_s')
    source.strict = int(bool(state.strict))
    if state.init is not None:
        arrays = [np.array(value, dtype=np.float64, order='C', copy=True) for value in state.init]
        keepalive.extend(arrays)
        source.warm_start = 1
        source.initial_shape[:] = arrays[0].shape if arrays[0].ndim == 3 else (0, 0, 0)
        for n, array in enumerate(arrays):
            source.initial[n] = _Array(array.ctypes.data_as(ct.POINTER(_D)), array.size)
    callbacks = _CacheCallbacks(geometry_cache, eos_cache)
    table = _Callbacks(2, ct.sizeof(_Callbacks), None, _GeometryFunction(callbacks.geometry),
                       _EosFunction(callbacks.eos))
    result_type = _Prepared if state.full else _Pressure
    result, error = result_type(2, ct.sizeof(result_type)), ct.create_string_buffer(4096)
    try:
        call = bindings.prepare if state.full else bindings.pressure
        status = call(
            ct.byref(source), ct.byref(table), ct.byref(result), error, len(error))
        if callbacks.errors:
            raise callbacks.errors[0]
        if status:
            if status == 1:
                text = error.value.decode('utf-8', errors='replace')
                try:
                    check_model_error(text)
                except ValueError as problem:
                    evidence = dict(topology=state.topo, L_cell_mm=source.values[0],
                                    t_wall_mm=source.values[1], reason='geometry')
                    causes = ()
                    if problem.__cause__ is not None:
                        inner = native_error('preparation', call.__name__, status, text,
                                             problem=problem.__cause__, **evidence)
                        causes = (inner.diagnostic,)
                    native_error('preparation', call.__name__, status, text, problem=problem,
                                 causes=causes, **evidence)
                    raise
            _native_flow._check_status(call.__name__, status, error)
        ranges = [(item.label, item.side, tuple(item.bounds), item.temperature_K)
                  for item in result.ranges[:result.range_count]]
        pressures = [(tuple(item.floating_events), item.no_positive_outlet, item.outlet_squared)
                     for item in result.inlet_pressure]
        observe(tuple(ranges), tuple(result.floating_events), tuple(pressures), bindings.collect_range,
                _native_properties._floating_events)
        yield result
    finally:
        if state.full:
            bindings.release(ct.byref(result))


def run_preparation(state, *, geometry_cache, eos_cache, check_model_error, observe):
    """Return copied preparation data or the two pressure fractions."""
    with _native_result(state, geometry_cache, eos_cache, check_model_error, observe) as result:
        return _copy_prepared(result) if state.full else tuple(result.fractions)
