"""Pack raw Quick inputs at fixed native preparation boundaries."""
from contextlib import contextmanager
import ctypes as ct
from dataclasses import asdict
from functools import lru_cache
import inspect
import warnings

import numpy as np

from sjtu_tpmshx.shared.configs.model_parameters import MODEL_VERSIONS, load_quick_design_parameters
from sjtu_tpmshx.shared.domain.model_refs import ModelRef
from sjtu_tpmshx.shared.domain.run_environment import capture_environment
from sjtu_tpmshx.shared.domain.run_warnings import range_context, record_range
from sjtu_tpmshx.shared.df_surrogate import predict as df
from . import _native_df, _native_flow, _native_geometry, _native_grid, _native_preparation, _native_properties
from . import fluid_props as registry
from . import tpms_geometry, tpms_props
from ._native_preparation_case import _Array, _GeometryCache, _Text


_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Scalar = _native_grid._Scalar
_Parameters = load_quick_design_parameters()
K_STEEL, LTNE_TOL = _Parameters['k_s'], _Parameters['tol']


def _struct(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


_Input = _struct('QuickInput', [('abi_version', _U), ('struct_size', _S), ('values', _Scalar * 13),
    *((name, _Text) for name in ('topology', 'arrangement', 'property_mode')), ('fluids', _Text * 2),
    *((name, _U) for name in ('have_height', 'have_chi', 'strict')), ('chi', _D),
    ('warm_start', _U), ('initial_shape', _S * 3), ('initial', _Array * 3)])
_Controls = _struct('QuickControls', [('dir_b', _U), *((name, _S) for name in ('ny', 'nz', 'max_iterations')),
    ('alpha', _D), ('q_relative_tolerance', _D), ('chunk_iterations', _S),
    ('have_q_relative_tolerance', _U), ('have_chunk_iterations', _U)])
_Prepared = _struct('QuickPrepared', [('abi_version', _U), ('struct_size', _S), ('owner', ct.c_void_p),
    ('shape', _S * 3), *((name, _Array * 3) for name in ('widths', 'edges', 'initial')),
    ('width_precision', _U * 3), ('solid_precision', _U),
    *((name, _Array) for name in ('epsilon', 'epsilon_a', 'solid_conductivity')),
    ('geometry', _GeometryCache), ('cell_length_m', _Scalar), ('wall_thickness_m', _Scalar),
    ('fractions', _Scalar * 2), ('controls', _Controls), ('inlet_pressure', _native_df._Pressure * 2)])
_Pressure = _struct('QuickPressure', [('abi_version', _U), ('struct_size', _S),
    ('fractions', _Scalar * 2), ('inlet_pressure', _native_df._Pressure * 2)])
_Request = _struct('QuickRequest', [(name, _U) for name in ('operation', 'side', 'index')] +
    [('flags', _U * 4), ('scalars', _Scalar * 6), ('text', _Text),
     ('property_inputs', _native_properties._Input * 3), ('imaginary_inputs', _D * 3), ('categories', _U * 3),
     ('property_values', _Array), ('property_imaginary', _Array), ('property_kind', _Scalar),
     ('property_category', _U), ('floating_events', ct.POINTER(_U)), ('floating_event_count', _S),
     ('geometry', ct.POINTER(_GeometryCache)), ('pressure', ct.POINTER(_native_df._Pressure)),
     ('failure', ct.POINTER(_native_properties._Failure)), ('status', ct.c_int)])
_Host = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.POINTER(_Request))
_Cache = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_GeometryCache), ct.POINTER(_U))
_Callbacks = _struct('QuickCallbacks', [('abi_version', _U), ('struct_size', _S), ('context', ct.c_void_p), ('raw_objects', _U),
    ('host', _Host), ('geometry_cache', _Cache)])
_NAMES = ('l', 't', 's', 'Lx', 'height', 'k_s', 'tol', 'mdot_h', 'mdot_c',
          'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c')
_GEOMETRY = ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h')
_GEOMETRY_FIELDS = tuple(name for name, _ in _GeometryCache._fields_)
_FLUIDS = ('air', 'water', 'sco2', 'co2')
_EMPIRICAL = ((2, 0, 1, 3), (4, 5, 6, 7))


class _Bindings:
    def __init__(self, path):
        self.owner = _native_preparation._load_library(path)
        arguments = [ct.POINTER(_Input), ct.POINTER(_Callbacks)]
        self.prepare = self.owner.bind('tpmshx_prepare_quick_design_v2',
            [*arguments, ct.POINTER(_Prepared), ct.POINTER(ct.c_char), _S])
        self.pressure = self.owner.bind('tpmshx_quick_pressure_fractions_v2',
            [*arguments, ct.POINTER(_Pressure), ct.POINTER(ct.c_char), _S])
        self.release = self.owner.bind('tpmshx_quick_prepared_release_v2', [ct.POINTER(_Prepared)], None)


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _copy(value, *, precision=64, shape=None):
    result = (np.ctypeslib.as_array(value.data, shape=(value.size,)).astype(f'float{precision}', copy=True)
              if value.size else np.empty(0, dtype=f'float{precision}'))
    return result if shape is None else result.reshape(shape)


def _text(value):
    return ct.string_at(value.data, value.size).decode('utf-8')


def _bind_pressure_options(compressible, options):
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


def _record_property_range(fluid, at, temperature):
    names = (('air_density', 'air_viscosity', 'air_conductivity', 'air_cp'),
             ('water_density', 'water_viscosity', 'water_conductivity', 'water_cp'))
    if fluid == 0 and at == 0:
        return
    name = names[fluid][at]
    bounds = (tpms_props._WATER_T_RANGE if fluid else
              tpms_props._AIR_CP_RANGE if at == 3 else tpms_props._AIR_T_RANGE)
    values = np.asarray(temperature, dtype=float)
    if not values.size or record_range(('property', name), values, bounds, label=name, quantity='T', unit='K'):
        return
    message = tpms_props._range_notice(name, float(values.min()), float(values.max()), *bounds)
    if message is not None:
        provider = registry.FLUIDS[_FLUIDS[fluid]]
        caller = getattr(provider, ('rho', 'mu', 'k', 'cp')[at])
        warnings.warn_explicit(message, UserWarning, caller.__code__.co_filename,
            caller.__code__.co_firstlineno, module=caller.__module__,
            registry=caller.__globals__.setdefault('__warningregistry__', {}))


class _HostState:
    def __init__(self, case, topo, l, t, s, length, arrangement, height, *,
                 init, conductivity, prop_model, tolerance, df_options, full):
        self.case, self.topo, self.l, self.t = case, topo, l, t
        self.s, self.length, self.arrangement = s, length, arrangement
        self.height = s if height is None else height
        self.init, self.conductivity, self.prop_model, self.tolerance = init, conductivity, prop_model, tolerance
        self.df_options, self.full = df_options, full
        self.props = [[None] * 5 for _ in range(2)]
        self.pressures, self.units = [None] * 2, [None] * 2
        self.errors, self.buffers = [], []
        self.scope = None
        self.geometry = None

    def enter(self, side):
        self.close()
        self.scope = range_context(side='AB'[side], stage='design-dp-inlet', layout='scalar')
        self.scope.__enter__()

    def close(self):
        if self.scope is not None:
            scope, self.scope = self.scope, None
            scope.__exit__(None, None, None)

    def string(self, value):
        encoded = value.encode('utf-8')
        storage = ct.create_string_buffer(encoded)
        self.buffers.append(storage)
        return _Text(ct.cast(storage, ct.POINTER(ct.c_char)), len(encoded))

    def pack_properties(self, request, values, *, coerce=False):
        self.property_shape, self.buffers, inputs = _native_properties._inputs(values, coerce=coerce)
        for n, value in enumerate(inputs):
            request.property_inputs[n] = value

    def cache(self, _context, action, pointer, hit):
        try:
            key = (self.topo, self.l, self.t, _Parameters['geometry_resolution'])
            owner = tpms_geometry._compute_geometry_cached
            if action == 0:
                found, value = owner.lookup(key)
                hit[0] = found
                if found:
                    self.geometry = dict(value)
                    for name, field in zip(_GEOMETRY, _GEOMETRY_FIELDS):
                        setattr(pointer.contents, field, float(value[name]))
            elif action == 1:
                value = {name: (float if n < 3 else np.float64)(getattr(pointer.contents, field))
                         for n, (name, field) in enumerate(zip(_GEOMETRY, _GEOMETRY_FIELDS))}
                owner.store(key, None, value)
                self.geometry = value
                hit[0] = 0
            else:
                raise RuntimeError('unknown Quick geometry cache operation')
            return 0
        except BaseException as problem:
            self.errors.append(problem)
            return 1

    def host(self, _context, pointer):
        try:
            self.dispatch(pointer.contents)
            return 0
        except BaseException as problem:
            self.errors.append(problem)
            return 1

    def dispatch(self, request):
        operation, side, at = request.operation, request.side, request.index
        if operation == 1:
            if self.init is not None:
                registry.check_finite_temperatures(*self.init, where='design external warm start')
        elif operation == 2:
            if self.arrangement not in _Parameters['arrangements'] or self.prop_model not in ('const', 'mean'):
                raise ValueError('unsupported quick-design arrangement or property model')
        elif operation == 3:
            self.positive = (self.l, self.t, self.s, self.length, self.height, self.conductivity, self.tolerance,
                self.case.mdot_h, self.case.mdot_c, self.case.T_in_h, self.case.T_in_c, self.case.P_in_h, self.case.P_in_c)
        elif operation == 4:
            value = self.positive[at]
            request.flags[0] = not (not np.isfinite(value) or value <= 0)
        elif operation == 5:
            arr = _Parameters['arrangements'][self.arrangement]
            shape = (_Parameters['nx'], arr['ny'], arr['nz'])
            request.flags[0] = arr['nz'] == 1
            if self.init is not None and (len(self.init) != 3 or any(np.shape(a) != shape for a in self.init)):
                raise ValueError('quick-design warm start must match the prepared grid')
        elif operation == 6:
            if self.topo not in ('Diamond', 'Gyroid'):
                raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{self.topo}'")
            if self.l <= 0:
                raise ValueError(f'L_mm must be positive, got {self.l}')
            if self.t <= 0:
                raise ValueError(f't_mm must be positive, got {self.t}')
            if 2 * self.t >= self.l:
                raise ValueError(f'Wall thickness t={self.t}mm >= L={self.l}mm, no pore space')
            request.flags[0] = _native_geometry._topology(self.topo)
            request.flags[1] = _native_geometry._floating_dtype(self.l, 0.).itemsize * 8
            request.flags[2] = _native_geometry._floating_dtype(self.t, self.l).itemsize * 8
            request.scalars[0] = _Scalar(float(self.l), 64, 0)
            request.scalars[1] = _Scalar(float(self.t), 64, 0)
        elif operation == 7:
            chi = 1. if at else tpms_props._resolve_chi_s()
            request.flags[0] = _native_geometry._topology(self.topo)
            conductivity = self.conductivity if self.full else _Parameters['k_s']
            request.flags[2] = _native_geometry._floating_dtype(self.geometry['epsilon'], conductivity).itemsize * 8
            request.scalars[0] = _Scalar(float(conductivity), 64, 0)
            have, value = _native_geometry._override(chi)
            request.flags[1], request.scalars[1] = have, _Scalar(value, 64, 0)
        elif operation == 8:
            length = (self.length, self.s, self.height)[at]
            value = np.asarray(length)
            dtype = value.dtype if value.dtype.kind == 'f' else np.dtype('float64')
            raw = value[()] if isinstance(length, np.ndarray) else length
            request.scalars[0] = _native_grid._scalar(raw)
            request.flags[0] = dtype.itemsize * 8
        elif operation == 9:
            self.operating = {name: getattr(self.case, name) for name in
                ('hot_fluid', 'cold_fluid', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c', 'mdot_h', 'mdot_c')}
            self.df_options = dict(method=df._resolve_method())
        elif operation == 10:
            self.enter(side)
            names = ('hot_fluid', 'T_in_h', 'P_in_h') if side == 0 else ('cold_fluid', 'T_in_c', 'P_in_c')
            self.inlet = tuple(getattr(self.case, name) for name in names)
            name = registry.get(self.inlet[0]).name
            request.text = self.string(name)
        elif operation == 11:
            self.state_pack(request)
        elif operation == 12:
            self.property_pack(request)
        elif operation == 13:
            self.property_result(request)
        elif operation == 14:
            values = (self.props[side][1], self.props[side][3], self.props[side][2])
            self.property_shape, self.buffers, inputs = _native_properties._derived_inputs('prandtl', values)
            for n, value in enumerate(inputs):
                request.property_inputs[n] = value.real
                request.imaginary_inputs[n], request.categories[n] = value.imaginary, value.category
        elif operation == 15:
            self.close()
            self.cross = self.arrangement == 'cross'
            for n, value in enumerate((self.geometry['epsilon_A'], self.s, self.length, self.height)):
                request.scalars[n] = _native_flow._scalar(value)
            request.flags[0] = int(self.cross)
        elif operation == 16:
            self.enter(side)
            names = ('hot_fluid', 'mdot_h', 'T_in_h', 'P_in_h') if side == 0 else ('cold_fluid', 'mdot_c', 'T_in_c', 'P_in_c')
            self.pressure_inlet = tuple(getattr(self.case, name) for name in names)
            self.options = dict(self.df_options or {})
        elif operation == 17:
            raw_fluid, mass, _temperature, _pressure = self.pressure_inlet
            density = 0. if raw_fluid == 'air' else self.props[side][0]
            self.air_flow = raw_fluid == 'air'
            for n, value in enumerate((mass, self.sections[side * 2], density)):
                request.scalars[n] = _native_flow._scalar(value)
            request.flags[0] = int(self.air_flow)
        elif operation == 18:
            self.mass_flux = _native_flow._restore(request.scalars[0])
            self.velocity = None if self.air_flow else _native_flow._restore(request.scalars[1])
        elif operation == 19:
            request.flags[0] = bool(self.pressure_inlet[0] == 'air')
        elif operation == 20:
            self.pressure_pack(request)
        elif operation == 21:
            self.pressure_result(request)
        elif operation == 22:
            self.close()
            pressure = self.case.P_in_h if side == 0 else self.case.P_in_c
            request.scalars[0] = _native_flow._scalar(self.pressures[side])
            request.scalars[1] = _native_flow._scalar(pressure)
        elif operation == 23:
            self.config = asdict(self.case)
        elif operation == 24:
            value = (self.l, self.t)[at]
            direct = type(value) not in (int, float, np.float16, np.float32, np.float64,
                np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64)
            request.flags[0] = direct
            if direct:
                self.units[at] = value / 1000.
            else:
                request.scalars[0] = _native_grid._scalar(value)
        elif operation == 25:
            if not request.flags[0]:
                self.units[at] = _native_grid._restore(request.scalars[0])
        elif operation == 26:
            self.environment = capture_environment()
            self.model_refs = (ModelRef('quick_design', MODEL_VERSIONS['quick_design']),
                ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': self.case.hot_fluid}),
                ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': self.case.cold_fluid}))
        elif operation == 27:
            self.failure(request)
        elif operation == 28:
            self.sections = [_native_flow._restore(request.scalars[n]) for n in range(4)]
            self.sections[1] = self.length
            self.sections[3] = self.s if self.cross else self.length
        else:
            raise RuntimeError(f'unknown Quick host operation {operation}')

    def state_pack(self, request):
        _fluid, temperature, pressure = self.inlet
        if request.flags[0] == 1:
            try:
                self.state_temperatures, self.state_pressures = np.broadcast_arrays(
                    np.asarray(temperature, dtype=float), np.asarray(pressure, dtype=float))
            except (TypeError, ValueError) as problem:
                raise registry.WaterStateError('quick-design properties: water requires paired T/P states') from problem
            self.pack_properties(request, (self.state_temperatures, self.state_pressures), coerce=True)
        else:
            self.pack_properties(request, (self.eos_temperature, self.eos_pressure), coerce=True)
            request.flags[1] = self.eos_temperature.ndim == 0 and self.eos_pressure.ndim == 0

    def property_pack(self, request):
        fluid, at = request.flags[0], request.index
        _raw_fluid, temperature, pressure = self.inlet
        if fluid < 2:
            _record_property_range(fluid, at, temperature)
            getter = _EMPIRICAL[fluid][at]
            self.property_shape, self.buffers, inputs = _native_properties._empirical_inputs(getter, temperature, pressure)
            for n, value in enumerate(inputs):
                request.property_inputs[n] = value
            if getter == 7:
                self.property_shape = ()
        else:
            if fluid == 3 and pressure is None:
                raise ValueError('CO2 requires absolute pressure P in Pa')
            self.eos_temperature, self.eos_pressure = np.asarray(temperature, dtype=float), np.asarray(pressure, dtype=float)
            if fluid == 3:
                self.eos_temperature, self.eos_pressure = np.broadcast_arrays(self.eos_temperature, self.eos_pressure)
                self.pack_properties(request, (self.eos_temperature, self.eos_pressure), coerce=True)
            else:
                self.buffers = [np.ascontiguousarray(value.reshape(-1)) for value in (self.eos_temperature, self.eos_pressure)]
                for n, value in enumerate(self.buffers):
                    request.property_inputs[n] = _native_properties._Input(
                        value.ctypes.data_as(ct.POINTER(_D)), value.size, _Scalar(0., 64, 1), 3)

    def property_result(self, request):
        events = [request.floating_events[n] for n in range(request.floating_event_count)]
        _native_properties._floating_events(events)
        bits, strong = request.property_kind.precision, request.property_kind.strong
        values = _copy(request.property_values, precision=bits, shape=self.property_shape)
        if request.property_category:
            imaginary = _copy(request.property_imaginary, precision=bits, shape=self.property_shape)
            combined = np.empty(self.property_shape, dtype=f'complex{bits * 2}')
            combined.real[...], combined.imag[...] = values, imaginary
            values = combined
        self.props[request.side][request.index] = (values if self.property_shape else
            values[()] if strong else values.item())

    def pressure_pack(self, request):
        air, side = bool(request.flags[0]), request.side
        method, self.strict = _bind_pressure_options(air, self.options)
        df._get_model(self.topo, method)
        try:
            length, wall = float(self.l), float(self.t)
        except ValueError as problem:
            raise ValueError('geometry is outside the fixed sCO2 CFD grid: '
                             '4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm') from problem
        _fluid, _mass, temperature, pressure = self.pressure_inlet
        values = ((self.mass_flux, temperature, pressure, self.props[side][1], self.sections[side * 2 + 1])
                  if air else (self.velocity, self.props[side][0], self.props[side][1], self.sections[side * 2 + 1]))
        for n, value in enumerate(values):
            request.scalars[n] = _native_flow._scalar(value)
        request.flags[1] = _native_df._topology(self.topo)
        if air:
            request.flags[2] = int(bool(self.strict))
        request.scalars[5], request.property_kind = _Scalar(length, 64, 0), _Scalar(wall, 64, 0)

    def pressure_result(self, request):
        air, output = request.flags[0], request.pressure.contents
        _native_properties._floating_events(output.floating_events)
        self.pressures[request.side] = (self.pressure_inlet[3] if air and output.no_positive_outlet and not self.strict
            else _native_grid._restore(_Scalar(output.dP, output.precision, output.strong)))
        if air and output.no_positive_outlet:
            df._record_pressure_limit(self.topo, self.l, self.t, output.outlet_squared, self.strict)

    def failure(self, request):
        failure, message = request.failure.contents, _text(request.text)
        _native_properties._floating_events(failure.fp.events[:failure.fp.event_count])
        phase = request.flags[1]
        if phase == 0 and request.status == 10:
            values, pressures = self.state_temperatures, self.state_pressures
            if not values.size:
                raise registry.WaterStateError('quick-design properties: water requires finite positive K and Pa(abs)') from None
            index = tuple(map(int, np.unravel_index(failure.index, values.shape)))
            problem = registry.WaterStateError(f'quick-design properties: water index={index}, '
                f'T={values[index]:g} K, P_abs={pressures[index]:g} Pa: {message}')
            if failure.reason == 1:
                raise problem from None
            cause = registry.WaterStateError(message) if failure.reason == 6 else ValueError(message)
            raise problem from cause
        if phase in (2, 4, 5) and request.status in (11, 12):
            raise ValueError(message) from None
        if phase == 3 and request.status == 11:
            prefix = ('CO2 requires a stable single-phase PT state; '
                      'saturation, two-phase and critical-point states are unsupported. ')
            raise ValueError(message) from ValueError(message.removeprefix(prefix))
        _native_df._raise_status(request.status, ct.create_string_buffer(message.encode('utf-8')),
                                 failure.fp.python_cause)


@contextmanager
def _operation(state):
    bindings = _bindings(_native_preparation._library().path)
    source = _Input(2, ct.sizeof(_Input))
    for n in range(13):
        source.values[n] = _Scalar(0., 64, 0)
    callbacks = _Callbacks(2, ct.sizeof(_Callbacks), None, 1, _Host(state.host), _Cache(state.cache))
    result_type = _Prepared if state.full else _Pressure
    result, error = result_type(2, ct.sizeof(result_type)), ct.create_string_buffer(4096)
    try:
        status = (bindings.prepare if state.full else bindings.pressure)(
            ct.byref(source), ct.byref(callbacks), ct.byref(result), error, len(error))
        if state.errors:
            raise state.errors[0]
        if status:
            message = error.value.decode('utf-8', errors='replace')
            if message.startswith('Degenerate TPMS geometry:'):
                raise ValueError(f'Degenerate TPMS geometry: {state.topo} L={state.l}mm t={state.t}mm '
                                 'has no usable pore space. Reduce t or increase L.') from ValueError(message)
            _native_flow._check_status(status, error)
        yield result
    finally:
        state.close()
        if state.full:
            bindings.release(ct.byref(result))


def prepare_values(case, topo, l, t, s, Lx, arrangement='cross', *, init=None,
                   k_s=K_STEEL, prop_model='const', tol=LTNE_TOL, height=None):
    """Return copied native fields and detached host snapshots for CaseData."""
    state = _HostState(case, topo, l, t, s, Lx, arrangement, height, init=init,
        conductivity=k_s, prop_model=prop_model, tolerance=tol, df_options=None, full=True)
    with _operation(state) as output:
        shape = tuple(output.shape)
        grid = dict(dimension=3, length_unit='m', axis_order=('x', 'y', 'z'))
        for n, axis in enumerate('xyz'):
            grid['d' + axis] = _copy(output.widths[n], precision=output.width_precision[n])
            grid[axis + '_edges'] = _copy(output.edges[n], precision=output.width_precision[n])
        fields = dict(eps=_copy(output.epsilon, shape=shape), eps_A=_copy(output.epsilon_a, shape=shape),
            K_ss=_copy(output.solid_conductivity, precision=output.solid_precision, shape=shape))
        c = output.controls
        controls = dict(dirB=c.dir_b, alpha=c.alpha, maxit=c.max_iterations,
            qtol=c.q_relative_tolerance if c.have_q_relative_tolerance else None,
            chunk=c.chunk_iterations if c.have_chunk_iterations else None)
        fractions = tuple(_native_flow._restore(value) for value in output.fractions)
    return state, grid, fields, controls, fractions


def pressure_fractions(case, topo, l, t, s, Lx, arrangement='cross', height=None, *, df_options=None):
    """Query analytical inlet pressure fractions without allocating thermal fields."""
    state = _HostState(case, topo, l, t, s, Lx, arrangement, height, init=None,
        conductivity=K_STEEL, prop_model='const', tolerance=LTNE_TOL, df_options=df_options, full=False)
    with _operation(state) as output:
        return tuple(_native_flow._restore(value) for value in output.fractions)
