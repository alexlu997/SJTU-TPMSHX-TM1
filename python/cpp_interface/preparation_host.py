"""Pack preparation callbacks and release their native results."""
from collections.abc import Callable, Mapping
from contextlib import contextmanager
import ctypes as ct
from functools import lru_cache
from types import SimpleNamespace
from typing import NamedTuple

import numpy as np

from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
from sjtu_tpmshx.run_control.run_warnings import RangeRecord
from . import _native_preparation_case as abi, _native_properties, _native_result
from ._native_values import TOPOLOGIES, borrow_text, read_text
from .stage_libraries import preparation_library


class _Operation(NamedTuple):
    call: Callable[..., int]
    result_type: type
    version: int


class _Bindings:
    def __init__(self, path, *, volume=False):
        self.owner = preparation_library.load(path)
        self.operations = {}
        self.releases = {}
        if volume:
            self._bind_volume()
        else:
            self._bind_plane()

    def _add(self, key, symbol, source, result, version):
        call = self.owner.bind(symbol, [ct.POINTER(source),
            ct.POINTER(abi._Options), ct.POINTER(abi._Callbacks), ct.POINTER(result),
            ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S])
        self.operations[key] = _Operation(call, result, version)

    def _bind_volume(self):
        from . import _native_preparation_3d as layout
        for family, source, flow, full in layout.FAMILIES:
            for name, suffix, result in (
                    ('prepare_inlet_mass_capacities', 'capacities', flow),
                    ('resolve_inlet_flow', 'resolve_flow', flow),
                    ('prepare_flow_case', 'prepare_case', full)):
                self._add((source, name), f'tpmshx_preparation_3d_{family}_{suffix}_v1', source, result, 1)
            for result, suffix in ((flow, 'flow'), (full, 'case')):
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_3d_{family}_{suffix}_release_v1', [ct.POINTER(result)], None)

    def _bind_plane(self):
        for family, source, flow, full in (
                ('uniform', abi._UniformInput, abi._UniformFlow, abi._UniformCase),
                ('continuous', abi._ContinuousInput, abi._ContinuousFlow, abi._ContinuousCase),
                ('zoned', abi._ZonedInput, abi._ZonedFlow, abi._ZonedCase),
                ('sigmoid', abi._SigmoidInput, abi._SigmoidFlow, abi._SigmoidCase)):
            for name, suffix, result in (
                    ('prepare_inlet_mass_capacities', 'capacities', flow),
                    ('resolve_inlet_flow', 'resolve_flow', flow),
                    ('prepare_flow_case', 'prepare_case', full)):
                self._add((family, name), f'tpmshx_preparation_2d_{family}_{suffix}_v1', source, result, 1)
            for result, suffix in ((flow, 'flow'), (full, 'case')):
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_2d_{family}_{suffix}_release_v1', [ct.POINTER(result)], None)
        self._add(('stripe', 'prepare_flow_case'), 'tpmshx_preparation_2d_stripe_prepare_case_v1',
                  abi._ZonedInput, abi._StripeCase, 1)
        self.releases[abi._StripeCase] = self.owner.bind(
            'tpmshx_preparation_2d_stripe_case_release_v1', [ct.POINTER(abi._StripeCase)], None)


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _sample(value, shape):
    def extreme(name):
        if not value.have_finite:
            return None
        index = tuple(int(item) for item in np.unravel_index(getattr(value, name + '_index'), shape))
        return getattr(value, name), index
    return dict(minimum=extreme('minimum'), maximum=extreme('maximum'),
                **{name: getattr(value, name) for name in ('low', 'high', 'size', 'nonfinite')})


def _range_record(value, bounds_list):
    shape = tuple(value.shape[:value.rank])
    try:
        source = tuple([read_text(item) for item in value.source[:value.source_count]])
        context = tuple([read_text(getattr(value, name)) for name in ('side', 'stage', 'layout')])
    except StopIteration as problem:
        # The scalar inlet exposes the exception chain from these two original iterators.
        raise RuntimeError('generator raised StopIteration') from problem
    bounds = list(value.bounds) if bounds_list else tuple(value.bounds)
    record = RangeRecord(read_text(value.label), read_text(value.quantity), read_text(value.unit),
                         bounds, **_sample(value.sample, shape), last=_sample(value.last, shape))
    return (*source, shape, context), record


def _check_status(status, error, failure, water_error):
    if not status:
        return
    classes = {1: ValueError, 2: water_error, 3: RuntimeError, 4: NotImplementedError}
    exception = MemoryError if status == 2 else classes.get(failure.kind, RuntimeError)
    problem = exception(error.value.decode('utf-8', errors='replace'))
    current = problem
    for item in failure.causes[:failure.cause_count]:
        cause = classes.get(item.kind, RuntimeError)(item.message.decode('utf-8', errors='replace'))
        current.__cause__ = cause
        current = cause
    raise problem


def _callback_bridge(validate_host_input, geometry_cache=None, inlet_cache=None,
                     observe_range=None, observe_notice=None, observe_event=None, *,
                     geometry_cache_at=None, inlet_cache_at=None, sigmoid_lut_cache=None,
                     validate_grid_stage=False):
    """Own callbacks and preserve their first exception across the C boundary."""
    callback_errors = []

    def event(_context, pointer):
        try:
            item = pointer.contents
            if observe_event is not None:
                logger = read_text(item.logger) if item.kind == 0 else ''
                message = read_text(item.message) if item.kind in (0, 1, 2) else ''
                observe_event(item.kind, logger, message, item.floating_event, _native_properties._floating_events)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def callback(signature, function):
        def dispatch(_context, *arguments):
            try:
                function(*arguments)
                return 0
            except BaseException as problem:
                callback_errors.append(problem)
                return 1
        return signature(dispatch)

    def geometry(action, value, hit):
        hit[0] = geometry_cache(action, value.contents)

    def inlet(action, side, source, value, hit):
        hit[0] = inlet_cache(action, side, source.contents, value.contents)

    def observe(cached, value, bounds_list, have_scalar, scalar):
        if observe_range is not None:
            observe_range(*_range_record(value.contents, bool(bounds_list)), bool(cached), scalar if have_scalar else None)

    def notice(kind, side, value, message):
        if observe_notice is not None:
            observe_notice(kind, side, value, read_text(message))

    def geometry_at(action, key, value, hit):
        hit[0] = geometry_cache_at(action, key.contents, value.contents)

    def inlet_at(action, key, value, hit):
        hit[0] = inlet_cache_at(action, key.contents, value.contents)

    def lut_cache(action, topology, resolution, value, hit):
        hit[0] = sigmoid_lut_cache(action, topology, resolution, value.contents)

    callbacks = abi._Callbacks(
        1, ct.sizeof(abi._Callbacks), None, int(bool(validate_grid_stage)),
        abi._EventFunction(event),
        callback(abi._HostFunction, validate_host_input) if validate_host_input is not None else abi._HostFunction(),
        callback(abi._GeometryCacheFunction, geometry) if geometry_cache is not None else abi._GeometryCacheFunction(),
        callback(abi._InletCacheFunction, inlet) if inlet_cache is not None else abi._InletCacheFunction(),
        callback(abi._RangeFunction, observe) if observe_range is not None else abi._RangeFunction(),
        callback(abi._NoticeFunction, notice) if observe_notice is not None else abi._NoticeFunction(),
        callback(abi._GeometryAtFunction, geometry_at) if geometry_cache_at is not None else abi._GeometryAtFunction(),
        callback(abi._InletAtFunction, inlet_at) if inlet_cache_at is not None else abi._InletAtFunction(),
        callback(abi._LUTCacheFunction, lut_cache) if sigmoid_lut_cache is not None else abi._LUTCacheFunction(),
    )
    return callbacks, callback_errors


def operation(name, source, options, validate_host_input, water_error, geometry_cache=None, inlet_cache=None,
              observe_range=None, observe_notice=None, observe_event=None, *,
              geometry_cache_at=None, inlet_cache_at=None, sigmoid_lut_cache=None):
    kind = type(source)
    if kind is abi._UniformInput:
        family = 'uniform'
    elif kind is abi._ContinuousInput:
        family = 'continuous'
    elif kind is abi._SigmoidInput:
        family = 'sigmoid'
    elif kind is abi._ZonedInput:
        family = 'stripe' if name == 'prepare_flow_case' and source.kind == 0 else 'zoned'
    else:
        raise TypeError(f'unsupported 2D preparation input type {kind.__name__}')
    bindings = _bindings(preparation_library.path())
    key = (family, name)
    bridge = _callback_bridge(validate_host_input, geometry_cache, inlet_cache, observe_range, observe_notice,
        observe_event, geometry_cache_at=geometry_cache_at, inlet_cache_at=inlet_cache_at,
        sigmoid_lut_cache=sigmoid_lut_cache, validate_grid_stage=validate_host_input is not None)
    return _owned_result(bindings, key, (source,), options, bridge, water_error)


@lru_cache(maxsize=1)
def _volume_bindings(path):
    return _Bindings(path, volume=True)


def volume_operation(name, source, options, validate_host_input, policy, water_error):
    cache = PreparationCacheBridge(policy)
    bindings = _volume_bindings(preparation_library.path())
    bridge = _callback_bridge(validate_host_input, observe_range=policy.observe_range, observe_notice=policy.observe_notice,
                              observe_event=policy.observe_event,
                              geometry_cache_at=cache.geometry_at, inlet_cache_at=cache.inlet_at)
    return _owned_result(bindings, (type(source), name), (source,), options, bridge, water_error)


@contextmanager
def _owned_result(bindings, key, inputs, options, bridge, water_error):
    """Keep the callbacks and borrowed arrays alive until the consumer finishes."""
    call, result_type, version = bindings.operations[key]
    result = result_type(version, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    callbacks, callback_errors = bridge
    try:
        status = call(*map(ct.byref, inputs), ct.byref(options), ct.byref(callbacks),
                      ct.byref(result), ct.byref(failure), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        _check_status(status, error, failure, water_error)
        yield result
    finally:
        bindings.releases[result_type](ct.byref(result))


def borrow_ranges(rows, keepalive):
    values = (abi._Range * len(rows))()
    captured = (ct.c_uint32 * len(rows))()
    keepalive.extend((values, captured))
    for index, row in enumerate(rows):
        value = values[index]
        source = (abi._Text * len(row['source']))(*(borrow_text(item, keepalive) for item in row['source']))
        shape = (ct.c_size_t * len(row['shape']))(*row['shape'])
        keepalive.extend((source, shape))
        value.source, value.source_count = source, len(source)
        value.shape, value.rank = shape, len(shape)
        for name in ('side', 'stage', 'layout', 'quantity', 'unit'):
            setattr(value, name, borrow_text(row[name], keepalive))
        value.bounds[:] = row['bounds']
        if type(row['captured']) is not bool:
            raise ValueError('range evidence requires an explicit capture flag')
        captured[index] = row['captured']
        if not row['captured']:
            continue
        sample = value.sample
        for name in ('low', 'high', 'size', 'nonfinite'):
            setattr(sample, name, row[name])
        sample.have_finite = row['minimum'] is not None
        if sample.have_finite:
            for name in ('minimum', 'maximum'):
                scalar, position = row[name]
                setattr(sample, name, scalar)
                setattr(sample, name + '_index', int(np.ravel_multi_index(position, row['shape'])))
    return values, captured


def pack_nu(target, settings, keepalive):
    target.mode = settings.mode == 'experimental'
    for index, value in enumerate((settings.alpha_D, settings.alpha_G)):
        target.have_alpha[index] = value is not None
        target.alpha[index] = value or 0.
    for name in ('parameter_version', 'source', 'applicability'):
        setattr(target, name, borrow_text(getattr(settings, name), keepalive))


class _PreparedMesh(ct.Structure):
    _fields_ = [('dimension', ct.c_size_t), ('widths', _native_result._Array * 3), ('edges', _native_result._Array * 3)]
    _fields_ += [(name, ct.c_double) for name in ('area_density', 'hydraulic_diameter', 'porosity', 'split_a')]
    _fields_ += [('fields', _native_result._Array * 3), ('side_geometry', _native_result._Array * 2),
                 ('axis_present', ct.c_uint32 * 2), ('axes', (ct.c_int32 * 6) * 2),
                 ('solver_widths', abi._Array * 3), ('solver_area', abi._Array), ('solver_diameter', abi._Array)]

    @property
    def shape(self):
        return tuple(width.size for width in self.solver_widths[:self.dimension])


def borrow_solver_mesh(case, library, dimension):
    """Borrow the prepared mesh. Other numeric layouts use the portable schema checks."""
    try:
        check = library.tpmshx_stage_borrow_mesh_v1
    except AttributeError as error:
        raise ValueError('native solver library lacks tpmshx_stage_borrow_mesh_v1; rebuild the library') from error
    keepalive = []

    def view(array):
        if not (isinstance(array, np.ndarray) and array.dtype == np.float64 and array.dtype.isnative
                and array.flags['C_CONTIGUOUS'] and array.flags['ALIGNED']):
            raise TypeError('borrowed solver mesh requires contiguous native float64 arrays')
        packed = _native_result.array(array)
        keepalive.append(packed)
        return packed.raw

    grid = case.grid
    axes = tuple('xyz'[:dimension])
    try:
        if (type(grid['dimension']) is not int or grid['dimension'] != dimension
                or grid['length_unit'] != 'm' or tuple(grid['axis_order']) != axes):
            return None
        mesh = _PreparedMesh(dimension)
        for i, axis in enumerate(axes):
            mesh.widths[i] = view(grid['d' + axis])
            mesh.edges[i] = view(grid[axis + '_edges'])
        thermal = case.parameters['thermal_geometry']
        if 'air_bulk_hv' in thermal and not (isinstance(thermal['air_bulk_hv'], Mapping) and not thermal['air_bulk_hv']):
            return None
        keys = ('A_0', 'D_h', 'epsilon')
        values = tuple(thermal['uniform'][key] for key in keys) + (thermal['split_A'],)
        # Accept historical saved CaseData scalar types before borrowing float64 values.
        if any(type(x) not in (float, np.float16, np.float32, np.float64) for x in values):
            return None
        mesh.area_density, mesh.hydraulic_diameter, mesh.porosity, mesh.split_a = values
        if thermal['fields'] is not None:
            for i, key in enumerate(keys):
                mesh.fields[i] = view(thermal['fields'][key])
        sides = thermal['side_geometry']
        if sides is not None:
            if set(sides) != {'A', 'B'}:
                return None
            for i, side in enumerate('AB'):
                mesh.side_geometry[i] = view(sides[side])
        if dimension == 3:
            mappings = case.parameters['prepared']['axes']
            if not set(mappings).issubset('AB'):
                return None
            for i, side in enumerate('AB'):
                mapping = mappings.get(side)
                if mapping is None:
                    continue
                indices = (mapping['cross1_real_axis'], mapping['stream_real_axis'], mapping['cross2_real_axis'],
                           *mapping['solver_to_real_perm'])
                if len(indices) != 6 or any(type(x) is not int or x not in (0, 1, 2) for x in indices):
                    return None
                mesh.axes[i][:] = indices
                mesh.axis_present[i] = 1
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, AttributeError):
        return None
    check.argtypes, check.restype = [ct.POINTER(_PreparedMesh)], ct.c_int
    if check(ct.byref(mesh)):
        mesh.storage = keepalive
        return mesh
    return None


def pack_saved_resources(case, models, nu, saved, settings, keepalive):
    from sjtu_tpmshx.data_types.model_refs import ModelRef

    roles = case.metadata['model_roles']
    names = ('fluid_A', 'fluid_B', 'geometry', 'darcy_forchheimer')
    if set(roles) != set(names) or sorted(roles.values()) != list(range(len(case.model_refs))):
        raise ValueError(f"{case.grid['dimension']}D model roles must account for every recorded resource")
    recorded_settings = case.parameters['sco2_nu'] if case.grid['dimension'] == 3 else vars(settings)
    for index, role in enumerate(names):
        ref = case.model_refs[roles[role]]
        if not isinstance(ref, ModelRef):
            raise TypeError('model resource must be a ModelRef')
        model = models[index]
        model.name, model.version = borrow_text(ref.name, keepalive), borrow_text(ref.version, keepalive)
        params = ref.parameters
        if index < 2:
            if set(params) - {'fluid', 'sco2_nu'} or 'fluid' not in params:
                raise ValueError('fluid model requires fluid and optional sco2_nu parameters')
            fluid = params['fluid']
            if (ref.name == 'co2_fluid') != (fluid == 'co2'):
                raise ValueError('CO2 requires its versioned fluid resource')
            try:
                normalized = fluid.strip().lower()
            except AttributeError:
                normalized = None
            if normalized not in ('air', 'co2', 'sco2', 'water'):
                raise ValueError(f"unknown fluid {fluid!r}; known: ['air', 'co2', 'sco2', 'water']")
            saved.resource_fluids[index] = borrow_text(normalized, keepalive)
            if params['sco2_nu'] != recorded_settings:
                raise ValueError(f'prepared Nu settings and fluid {"AB"[index]} resource disagree')
            selection = Sco2NuConfig(**params['sco2_nu']).validate()
            pack_nu(saved.resource_nu[index], selection, keepalive)
        elif index == 2 and params:
            raise ValueError('geometry resource takes no fixed parameters')
        elif index == 3:
            if set(params) != {'topology'}:
                raise ValueError('Darcy-Forchheimer resource requires topology')
            saved.resource_topology = borrow_text(params['topology'], keepalive)
    pack_nu(nu, settings, keepalive)


def _cache_record_view(records):
    """Keep copied cache evidence alive until the native stage returns."""
    buffers, ranges, bounds_list, warnings = [], [], [], []

    def text(value):
        return borrow_text(value, buffers)

    def sample(value, shape):
        finite = value['minimum'] is not None
        def index(name):
            return int(np.ravel_multi_index(value[name][1], shape)) if shape else 0
        return abi._Sample(finite, value['minimum'][0] if finite else 0.,
            value['maximum'][0] if finite else 0., index('minimum') if finite else 0,
            index('maximum') if finite else 0, *(value[name] for name in ('low', 'high', 'size', 'nonfinite')))

    for key, record in records.items():
        if not isinstance(record, RangeRecord):
            warnings.append(text(record))
            continue
        shape = key[-1]
        sources = (abi._Text * (len(key)-1))(*[text(item) for item in key[:-1]])
        sizes = (abi._S * len(shape))(*shape)
        buffers.extend((sources, sizes))
        values = {name: getattr(record, name) for name in ('minimum', 'maximum', 'low', 'high', 'size', 'nonfinite')}
        ranges.append(abi._Range(sources, len(sources), text('unbound'), text('unbound'), text('source'),
            text(record.label), text(record.quantity), text(record.unit), (abi._D * 2)(*record.bounds),
            sizes, len(shape), sample(values, shape), sample(record.last or values, shape)))
        bounds_list.append(isinstance(record.bounds, list))
    ranges = (abi._Range * len(ranges))(*ranges)
    bounds = (abi._U * len(bounds_list))(*bounds_list)
    warnings = (abi._Text * len(warnings))(*warnings)
    buffers.extend((ranges, bounds, warnings))
    return abi._Evidence(ranges, len(ranges), bounds, warnings, len(warnings), None, 0), buffers


def _geometry_key(value):
    return (TOPOLOGIES[value.topology], value.cell_length_mm, value.wall_thickness_mm)


_GEOMETRY_FIELDS = tuple(name for name, _ in abi._GeometryCache._fields_)
_INLET_FIELDS = ('rho', 'mu', 'k_f', 're', 'nu', 'permeability_m2', 'forchheimer_per_m',
                 'pressure_gradient_Pa_m', 'surface_transfer_W_m2K', 'fluid_conductivity_W_mK')


def _read_fields(value, names):
    return tuple([getattr(value, name) for name in names])


def geometry_scalars(value):
    return _read_fields(value, _GEOMETRY_FIELDS)


def property_scalars(value):
    return (*_read_fields(value, _INLET_FIELDS), value.solid_conductivity_W_mK)


def _write_fields(value, names, items):
    for name, item in zip(names, items, strict=True):
        setattr(value, name, item)


class PreparationCacheBridge:
    """Keep borrowed cache buffers alive until a native preparation operation returns."""

    def __init__(self, policy):
        self.policy = policy
        self.buffers = []

    def geometry_at(self, action, key, value):
        cache_key = self.policy.geometry_key(*_geometry_key(key))
        return self.geometry(action, cache_key, value)

    def geometry(self, action, key, value):
        def read():
            return geometry_scalars(value)

        def write(items):
            _write_fields(value, _GEOMETRY_FIELDS, items)

        return self.policy.geometry(action, key, read, write)

    def inlet_at(self, action, key, value):
        settings = fixed_record(key.sco2_nu) if key.have_sco2_nu else None
        cache_key = self.policy.inlet_key(_geometry_key(key.geometry), key.velocity_m_s, key.temperature_K,
                                          key.pressure_Pa, abi._FLUIDS[key.fluid], settings, bool(key.co2_geometry))
        return self.inlet(action, cache_key, value)

    def inlet(self, action, key, value):
        def read():
            evidence = value.evidence
            ranges = [_range_record(evidence.ranges[i], evidence.range_bounds_list[i])
                      for i in range(evidence.range_count)]
            messages = [read_text(item) for item in evidence.warnings[:evidence.warning_count]]
            return (geometry_scalars(value.geometry), _read_fields(value.properties, _INLET_FIELDS),
                    value.properties.cp, value.properties.pr, ranges, messages)

        def write(geometry, properties, cp, pr, records):
            _write_fields(value.geometry, _GEOMETRY_FIELDS, geometry)
            _write_fields(value.properties, _INLET_FIELDS, properties)
            value.properties.cp, value.properties.pr = cp, pr
            value.evidence, buffers = _cache_record_view(records)
            self.buffers.extend(buffers)
            return geometry_scalars(value.geometry)

        return self.policy.inlet(action, key, read, write)


def fixed_record(value):
    """Copy fixed ABI records to Python values. Pointers require an explicit extent."""
    if isinstance(value, abi._Text):
        return read_text(value)
    if isinstance(value, ct.Array):
        return tuple([fixed_record(item) for item in value])
    if isinstance(value, ct.Structure):
        return SimpleNamespace(**{name: fixed_record(getattr(value, name)) for name, _ in value._fields_})
    if isinstance(value, (float, int)):
        return value
    raise TypeError(f'unsupported fixed preparation field {type(value).__name__}')


def model_evidence(value, settings):
    """Copy the active model evidence before native release."""
    nu = SimpleNamespace(mode=settings.mode, model_version=read_text(value.sco2_nu_model_version))
    if settings.mode:
        nu.alpha = tuple(settings.alpha)
        nu.interpretation = read_text(value.sco2_nu_interpretation)
        for name in ('parameter_version', 'source', 'applicability'):
            setattr(nu, name, read_text(getattr(settings, name)))
    else:
        nu.coefficients = [(name, tuple(row)) for name, row in zip(TOPOLOGIES, value.sco2_nu_coefficients, strict=True)]
    co2 = fixed_record(value.co2) if value.co2.active else None
    return nu, co2


def drag_evidence(value, extra, extension):
    """Copy one D-F evidence record and its variable-length calibration table."""
    selection = fixed_record(extra.selection) if extra.have_selection and extra.selection.scope else None
    calibration = [(read_text(item.key), read_text(item.value))
                   for item in extra.calibration[:extra.calibration_count]]
    details = SimpleNamespace(application_scope=read_text(extra.application_scope), fluid=read_text(extra.fluid),
                              calibration=calibration, selection=selection)
    return fixed_record(value), details, fixed_record(extension) if extension is not None else None
