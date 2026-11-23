"""Pack float64 Quick inputs for the native preparation stage."""
from contextlib import contextmanager
import ctypes as ct
from dataclasses import asdict
from functools import lru_cache
import inspect
from types import SimpleNamespace
import warnings

import numpy as np

from sjtu_tpmshx.model_configs.model_parameters import MODEL_VERSIONS, fixed_geometry_error, load_quick_design_parameters
from sjtu_tpmshx.data_types.model_refs import ModelRef
from sjtu_tpmshx.run_control.run_environment import _resolve_chi_s, capture_environment
from sjtu_tpmshx.run_control.run_warnings import range_context, record_range
from sjtu_tpmshx.physical_models.df_surrogate.backend import resolve_method
from . import _native_flow, _native_properties
from .stage_libraries import preparation_library
from sjtu_tpmshx.physical_models import fluid_props as registry
from sjtu_tpmshx.physical_models import co2_props, sco2_props, tpms_geometry
from ._native_values import TOPOLOGIES, DoubleArray as _Array, borrow_text, copy_array, real_scalar
from ._native_preparation_case import _GeometryCache, _Sample
from ._native_preparation_case import (_QuickInputV2 as _Input, _QuickPreparedV2 as _Prepared,
                                       _QuickPressureV2 as _Pressure)


_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Parameters = load_quick_design_parameters()
K_STEEL, LTNE_TOL = _Parameters['k_s'], _Parameters['tol']
_NAMES = ('l', 't', 's', 'Lx', 'height', 'k_s', 'tol', 'mdot_h', 'mdot_c',
          'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c')
_GEOMETRY = ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h')
_GEOMETRY_FIELDS = tuple(name for name, _ in _GeometryCache._fields_)
_FLUIDS = ('air', 'water', 'sco2', 'co2')
_EOS_KEYS = ('D', 'V', 'L', 'C')
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
            _native_flow._check_status(status, error)
        return result


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _bind_pressure_options(compressible, options):
    from sjtu_tpmshx.physical_models.df_surrogate import predict as df

    function = df.predict_dP_compressible if compressible else df.predict_dP
    try:
        bound = inspect.signature(function).bind(*([None] * (9 if compressible else 8)), **options)
    except TypeError as problem:
        message = str(problem)
        if message.startswith('multiple values for argument'):
            message = 'got ' + message
        raise TypeError(f'{function.__name__}() {message}') from None
    bound.apply_defaults()
    return bound.arguments['method'], bound.arguments.get('strict', False)


def _fluid_name(fluid):
    name = fluid.strip().lower() if type(fluid) is str else None
    return name if name in _FLUIDS else registry.get(fluid).name


class _Caches:
    """Transport completed geometry and EOS values through the shared Python caches."""

    def __init__(self, key):
        self.key, self.errors = key, []

    def geometry(self, _context, action, pointer, hit):
        try:
            owner = tpms_geometry._compute_geometry_cached
            if action == 0:
                found, value = owner.lookup(self.key)
                hit[0] = found
                if found:
                    for name, field in zip(_GEOMETRY, _GEOMETRY_FIELDS):
                        setattr(pointer.contents, field, float(value[name]))
            elif action == 1:
                value = {name: (float if n < 3 else np.float64)(getattr(pointer.contents, field))
                         for n, (name, field) in enumerate(zip(_GEOMETRY, _GEOMETRY_FIELDS))}
                owner.store(self.key, None, value)
                hit[0] = 0
            else:
                raise RuntimeError('unknown Quick geometry cache operation')
            return 0
        except BaseException as problem:
            self.errors.append(problem)
            return 1

    def eos(self, _context, action, fluid, index, temperature, pressure, values, capacity, count, hit):
        try:
            sco2 = fluid == 2
            owner = sco2_props._prop if sco2 else co2_props._scalar
            key = (_EOS_KEYS[index], temperature, pressure) if sco2 else (temperature, pressure)
            if action:
                stored = tuple(values[n] for n in range(count[0]))
                owner.store(key, None, stored[0] if sco2 else stored)
                return 0
            found, value = owner.lookup(key)
            hit[0] = found
            if found:
                data = (value,) if sco2 else tuple(value)
                if len(data) > capacity:
                    raise RuntimeError('Quick EOS cache value exceeds the native buffer')
                count[0] = len(data)
                for n, item in enumerate(data):
                    values[n] = float(item)
            return 0
        except BaseException as problem:
            self.errors.append(problem)
            return 1


def _record_ranges(output, collect):
    from sjtu_tpmshx.physical_models.tpms_props import _range_notice

    for item in output.ranges[:output.range_count]:
        name = item.label.decode('utf-8')
        bounds = item.bounds[0], item.bounds[1]
        values = np.asarray(item.temperature_K, dtype=float)
        with range_context(side='AB'[item.side], stage='design-dp-inlet', layout='scalar'):
            if record_range(('property', name), values, bounds, label=name, quantity='T', unit='K', collect=collect):
                continue
        message = _range_notice(name, item.temperature_K, item.temperature_K, *bounds)
        if message is not None:
            warnings.warn(message, UserWarning, stacklevel=4)


@contextmanager
def _operation(state):
    bindings = _bindings(preparation_library.path())
    caches = _Caches((state.topo, state.l, state.t, _Parameters['geometry_resolution']))
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
    callbacks = _Callbacks(2, ct.sizeof(_Callbacks), None,
                           _GeometryFunction(caches.geometry), _EosFunction(caches.eos))
    result_type = _Prepared if state.full else _Pressure
    result, error = result_type(2, ct.sizeof(result_type)), ct.create_string_buffer(4096)
    try:
        status = (bindings.prepare if state.full else bindings.pressure)(
            ct.byref(source), ct.byref(callbacks), ct.byref(result), error, len(error))
        if caches.errors:
            raise caches.errors[0]
        if status:
            message = error.value.decode('utf-8', errors='replace')
            if status == 10:
                raise registry.WaterStateError(message)
            if status in (11, 12):
                raise ValueError(message)
            if message == 'Wall thickness must satisfy 2*t < L, with usable pore space':
                raise ValueError(f'Wall thickness t={state.t}mm >= L={state.l}mm, no pore space')
            if message == 'L_mm must be positive':
                raise ValueError(f'L_mm must be positive, got {state.l}')
            if message == 't_mm must be positive':
                raise ValueError(f't_mm must be positive, got {state.t}')
            if message.startswith('Degenerate TPMS geometry:'):
                raise ValueError(f'Degenerate TPMS geometry: {state.topo} L={state.l}mm t={state.t}mm '
                                 'has no usable pore space. Reduce t or increase L.') from ValueError(message)
            _native_flow._check_status(status, error)
        _record_ranges(result, bindings.collect_range)
        _native_properties._floating_events(result.floating_events)
        for side in range(2):
            pressure = result.inlet_pressure[side]
            _native_properties._floating_events(pressure.floating_events)
            if state.fluids[side] == 'air' and pressure.no_positive_outlet:
                from sjtu_tpmshx.physical_models.df_surrogate.predict import _record_pressure_limit
                _record_pressure_limit(state.topo, state.l, state.t, pressure.outlet_squared, state.strict)
        yield result
    finally:
        if state.full:
            bindings.release(ct.byref(result))


def _state(case, topo, l, t, s, length, arrangement, height, *, init, conductivity, prop_model,
           tolerance, df_options, full):
    if topo not in TOPOLOGIES:
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{topo}'")
    try:
        float(l), float(t)
    except (TypeError, ValueError) as problem:
        raise ValueError(fixed_geometry_error()) from problem
    if init is not None:
        registry.check_finite_temperatures(*init, where='design external warm start')
    fluids = tuple(_fluid_name(getattr(case, name)) for name in ('hot_fluid', 'cold_fluid'))
    for fluid, pressure in zip(fluids, (case.P_in_h, case.P_in_c)):
        if fluid == 'sco2':
            registry._require_sco2_pressure(pressure)
        elif fluid == 'co2' and pressure is None:
            raise ValueError('CO2 requires absolute pressure P in Pa')
    strict = False
    if full:
        df_options = dict(method=resolve_method())
    else:
        options = dict(df_options or {})
        for fluid in fluids:
            method, selected = _bind_pressure_options(fluid == 'air', options)
            resolve_method(method)
            strict = strict or (fluid == 'air' and bool(selected))
    height = s if height is None else height
    values = (l, t, s, length, height, conductivity if full else K_STEEL, tolerance,
              case.mdot_h, case.mdot_c, case.T_in_h, case.T_in_c, case.P_in_h, case.P_in_c)
    return SimpleNamespace(case=case, topo=topo, l=l, t=t, s=s, length=length, height=height,
        arrangement=arrangement, prop_model=prop_model, init=init, fluids=fluids, values=values,
        chi=_resolve_chi_s(), strict=strict, df_options=df_options, full=full)


def prepare_values(case, topo, l, t, s, Lx, arrangement='cross', *, init=None,
                   k_s=K_STEEL, prop_model='const', tol=LTNE_TOL, height=None):
    """Return copied native fields and detached host snapshots for CaseData."""
    state = _state(case, topo, l, t, s, Lx, arrangement, height, init=init, conductivity=k_s,
                   prop_model=prop_model, tolerance=tol, df_options=None, full=True)
    with _operation(state) as output:
        shape = tuple(output.shape)
        grid = dict(dimension=3, length_unit='m', axis_order=('x', 'y', 'z'))
        for n, axis in enumerate('xyz'):
            grid['d' + axis] = copy_array(output.widths[n])
            grid[axis + '_edges'] = copy_array(output.edges[n])
        fields = dict(eps=copy_array(output.epsilon, shape=shape), eps_A=copy_array(output.epsilon_a, shape=shape),
            K_ss=copy_array(output.solid_conductivity, shape=shape))
        c = output.controls
        controls = dict(dirB=c.dir_b, alpha=c.alpha, maxit=c.max_iterations,
            qtol=c.q_relative_tolerance if c.have_q_relative_tolerance else None,
            chunk=c.chunk_iterations if c.have_chunk_iterations else None)
        fractions = tuple(output.fractions)
        state.units = output.cell_length_m, output.wall_thickness_m
        state.geometry = dict(A_0=np.float64(output.geometry.area_density_per_m),
                              D_h=np.float64(output.geometry.hydraulic_diameter_m))
    state.config = asdict(case)
    state.operating = {name: getattr(case, name) for name in
        ('hot_fluid', 'cold_fluid', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c', 'mdot_h', 'mdot_c')}
    state.environment = capture_environment()
    state.model_refs = (ModelRef('quick_design', MODEL_VERSIONS['quick_design']),
        ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.hot_fluid}),
        ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.cold_fluid}))
    return state, grid, fields, controls, fractions


def pressure_fractions(case, topo, l, t, s, Lx, arrangement='cross', height=None, *, df_options=None):
    """Query analytical inlet pressure fractions without allocating thermal fields."""
    state = _state(case, topo, l, t, s, Lx, arrangement, height, init=None, conductivity=K_STEEL,
                   prop_model='const', tolerance=LTNE_TOL, df_options=df_options, full=False)
    with _operation(state) as output:
        return tuple(output.fractions)


def prepare_quick_design(case, topo, l, t, s, Lx, arrangement='cross', *,
                         case_id, init=None, k_s=K_STEEL, prop_model='const',
                         tol=LTNE_TOL, height=None):
    from sjtu_tpmshx.data_types.case_data import CaseData
    state, grid, fields, controls, fractions = prepare_values(
        case, topo, l, t, s, Lx, arrangement, init=init, k_s=k_s,
        prop_model=prop_model, tol=tol, height=height)
    return CaseData(
        case_id=case_id, config_snapshot=state.config, grid=grid, design_fields=fields,
        parameters=dict(operating_point=state.operating, topology=topo,
                        L_cell_m=state.units[0], t_wall_m=state.units[1], Lx=Lx,
                        s=s, height=state.height, k_s=k_s,
                        A_0=state.geometry['A_0'], D_h=state.geometry['D_h'],
                        arrangement=arrangement, prop_model=prop_model, tol=tol,
                        controls=controls, initial_fields=init, df_options=state.df_options,
                        _environment=state.environment,
                        inlet_pressure_fractions=dict(zip(('A', 'B'), fractions))),
        model_refs=state.model_refs,
        metadata=dict(mode='quick_design', model='plug_ltne_analytic_dp_v1',
                      quantity_basis='total', geometry_resolution=_Parameters['geometry_resolution'],
                      thermal_kernel=('2d_delegation' if fields['eps'].shape[2] == 1 else '3d'),
                      applicability='Sizing approximation; prescribed velocity, analytical inlet-state dP; not full SIMPLE or experimental validation.'))
