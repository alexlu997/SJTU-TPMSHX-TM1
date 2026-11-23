"""Own the shared preparation callbacks, native result lifetime and case records."""
from collections.abc import Callable, Mapping
from contextlib import contextmanager
import ctypes as ct
from dataclasses import replace
import dis
from functools import lru_cache, partial
from typing import NamedTuple
import warnings

import numpy as np

from sjtu_tpmshx.physical_models.preparation_cache import geometry_cache, inlet_cache, _InletCacheValue
from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
from sjtu_tpmshx.run_control.logutil import get_logger
from sjtu_tpmshx.run_control.run_warnings import (
    RangeRecord, current_warnings, merge_warnings, record_warning, warning_messages, _range_context,
)
from . import _native_flow, _native_preparation_case as abi, _native_properties
from ._native_values import TOPOLOGIES, PackedArray, _Array as StridedArray, borrow_text, read_text
from .stage_libraries import preparation_library


def validate_fluid_type(fluid_type: str, side: str) -> None:
    """Reject fluid names outside the supported air, water, sCO2 and CO2 set."""
    if fluid_type not in abi._FLUIDS:
        label = {'water': 'Water', 'sco2': 'sCO₂'}.get(fluid_type, fluid_type)
        raise NotImplementedError(
            f"Fluid {side} = {label} is not supported yet — no fitted "
            f"correlations (Nu / f-Re / D-F surrogate) for this fluid. "
            f"Supported fluids: air, water, sco2, co2."
        )


class _Operation(NamedTuple):
    call: Callable[..., int]
    result_type: type
    version: int


class _Bindings:
    def __init__(self, path, *, volume=False):
        self.owner = preparation_library.load(path)
        self.operations = {}
        self.releases = {}
        self.grid_arguments = [] if volume else [ct.POINTER(abi._GridKinds)]
        if volume:
            self._bind_volume()
        else:
            self._bind_plane()

    def _add(self, key, symbol, source, result, version):
        call = self.owner.bind(symbol, [ct.POINTER(source), *self.grid_arguments,
            ct.POINTER(abi._Options), ct.POINTER(abi._Callbacks), ct.POINTER(result),
            ct.POINTER(abi._Failure), ct.POINTER(ct.c_char), abi._S])
        self.operations[key] = _Operation(call, result, version)

    def _bind_volume(self):
        from . import _native_preparation_3d as layout
        version = self.owner.bind('tpmshx_preparation_host_3d_abi_version_v5', [], abi._U)()
        if version != 5:
            raise ValueError(f'unsupported native 3D preparation host ABI {version}; expected 5')
        for version, source, flow, full, prefix in layout.FAMILIES:
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case'):
                result = full if name == 'prepare_flow_case' else flow
                self._add((version, name), f'tpmshx_{name}_3d_v{version}', source, result, version)
            for result, suffix in ((flow, 'flow'), (full, 'case')):
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_{prefix}_{suffix}_3d_release_v{version}', [ct.POINTER(result)], None)

    def _bind_plane(self):
        # Uniform and continuous inlet stages use the v7 entries with the v3 and v4 flow layouts.
        for version, source, flow, prefix in (
                (3, abi._FlowInput, abi._Flow, 'flow'),
                (4, abi._ContinuousInput, abi._ContinuousFlow, 'continuous_flow')):
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow'):
                entry = name if version == 3 else name.replace('_', '_continuous_', 1)
                self._add((7, source, name), f'tpmshx_{entry}_2d_v7', source, flow, version)
            self.releases[flow] = self.owner.bind(
                f'tpmshx_preparation_{prefix}_2d_release_v{version}', [ct.POINTER(flow)], None)

        for version in (10, 11):
            query = self.owner.bind(f'tpmshx_preparation_case_abi_version_v{version}', [], abi._U)
            if query() != version:
                raise RuntimeError(f'native preparation v{version} ABI version is invalid')
        # Zoned and sigmoid inlet stages use the v10 entries with the v9 flow layouts.
        for source, flow, prefix in ((abi._ZonedHostInput, abi._ZonedHostFlow, 'zoned'),
                                     (abi._SigmoidHostInput, abi._SigmoidHostFlow, 'sigmoid')):
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow'):
                entry = name.replace('_', f'_{prefix}_', 1)
                self._add((10, source, name), f'tpmshx_{entry}_2d_v10', source, flow, 9)
            self.releases[flow] = self.owner.bind(
                f'tpmshx_preparation_{prefix}_flow_2d_release_v9', [ct.POINTER(flow)], None)
        for source, full, prefix in (
                (abi._FlowInput, abi._OffsetFlowCase, ''),
                (abi._ZonedHostInput, abi._OffsetZonedCase, 'zoned_'),
                (abi._SigmoidHostInput, abi._OffsetSigmoidCase, 'sigmoid_')):
            self._add((10, source, 'prepare_flow_case'), f'tpmshx_prepare_{prefix}flow_case_2d_v10', source, full, 10)
            self.releases[full] = self.owner.bind(
                f'tpmshx_preparation_{prefix}flow_case_2d_release_v10', [ct.POINTER(full)], None)
        for source, result, prefix in (
                (abi._ContinuousInput, abi._ContinuousGeometryCase, 'continuous'),
                (abi._ZonedHostInput, abi._StripeGeometryCase, 'stripe')):
            self._add((11, source, 'prepare_flow_case'), f'tpmshx_prepare_{prefix}_flow_case_2d_v11', source, result, 11)
            self.releases[result] = self.owner.bind(
                f'tpmshx_preparation_{prefix}_flow_case_2d_release_v11', [ct.POINTER(result)], None)


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
    source = tuple(read_text(item) for item in value.source[:value.source_count])
    context = tuple(read_text(getattr(value, name)) for name in ('side', 'stage', 'layout'))
    bounds = list(value.bounds) if bounds_list else tuple(value.bounds)
    record = RangeRecord(read_text(value.label), read_text(value.quantity), read_text(value.unit),
                         bounds, **_sample(value.sample, shape), last=_sample(value.last, shape))
    return (*source, shape, context), record


def observe_range(value, bounds_list, cached, scalar, selection=None, *, records=None):
    """Replay source records and the original standalone warning filters."""
    key, record = _range_record(value, bounds_list)
    if key[-1] == ('unbound', 'unbound', 'source'):
        key = (*key[:-1], _range_context.get())
    merge_warnings(current_warnings(), [{key: record}])
    merge_warnings(records, [{key[:-1]: record}])
    if cached or current_warnings() is not None or scalar is None:
        return
    from sjtu_tpmshx.physical_models import tpms_props, fluid_props, nu_correlations, co2_correlations
    source = key[:-2]
    if source[0] == 'property':
        fluid, property_name = source[1].split('_', 1)
        notice = tpms_props._range_notice(source[1], scalar, scalar, *record.bounds)
        if notice is not None:
            attribute = {'density': 'rho', 'viscosity': 'mu', 'conductivity': 'k', 'cp': 'cp'}[property_name]
            _source_warning(getattr(fluid_props.get(fluid), attribute), notice)
    elif source[0] in ('nu', 'nu_pr') and read_text(value.stage) in ('inlet', 'unbound'):
        fluid, topology = source[1:]
        if fluid == 'air':
            notices = nu_correlations._extrap_notices(topology, scalar, scalar)
            origin = fluid_props._nu_air
        elif fluid == 'water':
            notices = nu_correlations._water_nu_notices(scalar, scalar, topology)
            origin = fluid_props._nu_water
        elif fluid == 'sco2':
            notices = nu_correlations._sco2_nu_notices(scalar, scalar, topology)
            origin = (nu_correlations.nu_sco2_selected if selection is not None and selection.mode != 'cfd_smooth'
                      else nu_correlations.nu_sco2_topo)
        else:
            notices = ([co2_correlations._calibration_notice(record.quantity, record.bounds)]
                       if scalar < record.bounds[0] or scalar > record.bounds[1] else [])
            origin = fluid_props._nu_co2
        for notice in notices:
            _source_warning(origin, notice)


def _restore(value, kind):
    if not kind.strong:
        return float(value)
    dtype = np.dtype(f'float{kind.precision}')
    return np.asarray(value, dtype=dtype) if kind.layout == 2 else dtype.type(value)


def _check_status(status, error, failure):
    if not status:
        return
    from sjtu_tpmshx.physical_models.fluid_props import WaterStateError
    classes = {1: ValueError, 2: WaterStateError, 3: RuntimeError, 4: NotImplementedError}
    exception = MemoryError if status == 2 else classes.get(failure.kind, RuntimeError)
    problem = exception(error.value.decode('utf-8', errors='replace'))
    current = problem
    for item in failure.causes[:failure.cause_count]:
        cause = classes.get(item.kind, RuntimeError)(item.message.decode('utf-8', errors='replace'))
        current.__cause__ = cause
        current = cause
    raise problem


def _source_warning(function, message, *, call=None, occurrence=0, binary=None, category=UserWarning):
    """Keep the original warning module, source line and filter registry."""
    code = function.__code__
    if binary is not None:
        operator, occurrence = binary
        line = [item.positions.lineno for item in dis.get_instructions(function)
                if item.opname == 'BINARY_OP' and item.argrepr == operator][occurrence]
        module = function.__globals__['__name__']
    else:
        line = ([item.positions.lineno for item in dis.get_instructions(function)
                     if item.opname.startswith('LOAD_')
                     and (item.argval == call or item.opname.startswith('LOAD_FAST')
                          and isinstance(item.argval, tuple) and call in item.argval)][occurrence] if call else
                max(line for _start, _end, line in code.co_lines() if line is not None))
        module = function.__module__
    warnings.warn_explicit(message, category, code.co_filename, line,
        module=module, registry=function.__globals__.setdefault('__warningregistry__', {}))


def _control_axis_warning(source, message):
    from sjtu_tpmshx.physical_models.continuous_field import ContinuousFieldConfig, control_axis
    function, operator, occurrence = {
        'control-axis-step': (np.linspace.__wrapped__, '/', 0),
        'control-axis-divide': (np.linspace.__wrapped__, '/=', 0),
        'control-axis-scale': (np.linspace.__wrapped__, '*=', 0),
        'control-axis-multiply': (np.linspace.__wrapped__, '*=', 1),
        'control-axis-midpoint': (control_axis, '/', 0),
        'control-axis-check-midpoint': (ContinuousFieldConfig.__post_init__, '/', 0),
    }[source]
    _source_warning(function, message, binary=(operator, occurrence), category=RuntimeWarning)


def _callback_bridge(validate_host_input, geometry_cache=None, inlet_cache=None,
                     observe_range=None, observe_notice=None, nominal_grid_warning=None, *,
                     geometry_cache_at=None, inlet_cache_at=None, sigmoid_lut_cache=None, query=False):
    """Own callbacks and preserve their first exception across the C boundary."""
    callback_errors = []

    def event(_context, pointer):
        try:
            item = pointer.contents
            if item.kind == 0:
                get_logger(read_text(item.logger).removeprefix('tpmshx.')).info(read_text(item.message))
            elif item.kind == 1:
                message = read_text(item.message)
                if message.startswith('[geometry extrap]'):
                    from sjtu_tpmshx.physical_models.sigmoid_field import build_continuous_geometry
                    _source_warning(build_continuous_geometry, message, call='_geometry_from_fields')
                else:
                    from sjtu_tpmshx.physical_models.input_validation import surrogate_extrap_reasons
                    _source_warning(surrogate_extrap_reasons, message, call='check_surrogate_domain_at_point')
            elif item.kind == 2:
                source = read_text(item.message)
                if source in ('nominal-grid-x', 'nominal-grid-y'):
                    warn = partial(nominal_grid_warning, source[-1]) if nominal_grid_warning else None
                else:
                    warn = partial(_control_axis_warning, source) if source else None
                _native_properties._floating_events([item.floating_event], warn=warn)
            else:
                raise RuntimeError(f'unknown preparation event kind {item.kind}')
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

    def inlet(action, side, source, kind, value, hit):
        hit[0] = inlet_cache(action, side, source.contents, kind, value.contents)

    def observe(cached, value, bounds_list, have_scalar, scalar):
        if observe_range is not None:
            observe_range(value.contents, bool(bounds_list), bool(cached), scalar if have_scalar else None)

    def notice(kind, side, value, message):
        if observe_notice is not None:
            observe_notice(kind, side, value, read_text(message))

    def geometry_at(action, key, value, hit):
        hit[0] = geometry_cache_at(action, key.contents, value.contents)

    def inlet_at(action, key, value, hit):
        hit[0] = inlet_cache_at(action, key.contents, value.contents)

    def lut_cache(action, topology, resolution, value, hit):
        hit[0] = sigmoid_lut_cache(action, topology, resolution, value.contents)

    keyed = any(value is not None for value in (geometry_cache_at, inlet_cache_at, sigmoid_lut_cache))
    cached = any(value is not None for value in (geometry_cache, inlet_cache, observe_range, observe_notice))
    if keyed:
        version, layout = 9, abi._KeyedCallbacks
    elif cached:
        version, layout = 3 if query else 4, abi._CacheCallbacks
    else:
        version, layout = 2, abi._HostCallbacks

    descriptor = abi._Callbacks(version, ct.sizeof(layout), abi._EventFunction(event), None)
    callbacks = abi._HostCallbacks(descriptor, callback(abi._HostFunction, validate_host_input))
    if keyed or cached:
        callbacks = abi._CacheCallbacks(callbacks,
            callback(abi._GeometryCacheFunction, geometry) if geometry_cache and not keyed else abi._GeometryCacheFunction(),
            callback(abi._InletCacheFunction, inlet) if inlet_cache and not keyed else abi._InletCacheFunction(),
            callback(abi._RangeFunction, observe), callback(abi._NoticeFunction, notice))
    if keyed:
        callbacks = abi._KeyedCallbacks(callbacks,
            callback(abi._GeometryAtFunction, geometry_at) if geometry_cache_at else abi._GeometryAtFunction(),
            callback(abi._InletAtFunction, inlet_at) if inlet_cache_at else abi._InletAtFunction(),
            callback(abi._LUTCacheFunction, lut_cache) if sigmoid_lut_cache else abi._LUTCacheFunction())
    # The C entry reads the full versioned layout from its first member.
    descriptor = abi._Callbacks.from_buffer(callbacks)
    return callbacks, descriptor, callback_errors


def operation(name, source, options, validate_host_input, geometry_cache=None, inlet_cache=None,
              observe_range=None, observe_notice=None, nominal_grid_warning=None, *,
              geometry_cache_at=None, inlet_cache_at=None, sigmoid_lut_cache=None):
    kind = type(source)
    if name != 'prepare_flow_case':
        version = 10 if source.abi_version == 9 else 7
    elif kind is abi._ContinuousInput or kind is abi._ZonedHostInput and source.values.values.kind == 0:
        # Continuous fields and scalar stripe zones return the geometry-owning v11 case.
        version = 11
    else:
        version = 10
    bindings = _bindings(preparation_library.path())
    key = (version, kind, name)
    bridge = _callback_bridge(validate_host_input, geometry_cache, inlet_cache, observe_range, observe_notice,
        nominal_grid_warning, geometry_cache_at=geometry_cache_at, inlet_cache_at=inlet_cache_at,
        sigmoid_lut_cache=sigmoid_lut_cache)
    return _owned_result(bindings, key, (source, source._grid_kinds), options, bridge)


@lru_cache(maxsize=1)
def _volume_bindings(path):
    return _Bindings(path, volume=True)


def volume_operation(name, source, options, validate_host_input, cache):
    bindings = _volume_bindings(preparation_library.path())
    bridge = _callback_bridge(validate_host_input, observe_range=cache.observe_range, observe_notice=cache.observe_notice,
                              geometry_cache_at=cache.geometry_at, inlet_cache_at=cache.inlet_at)
    return _owned_result(bindings, (source.abi_version, name), (source,), options, bridge)


@contextmanager
def _owned_result(bindings, key, inputs, options, bridge):
    """Keep the callbacks and borrowed arrays alive until the consumer finishes."""
    call, result_type, version = bindings.operations[key]
    result = result_type(version, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    callbacks, descriptor, callback_errors = bridge
    try:
        status = call(*map(ct.byref, inputs), ct.byref(options), ct.byref(descriptor),
                      ct.byref(result), ct.byref(failure), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        _check_status(status, error, failure)
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
    _fields_ = [('dimension', ct.c_size_t), ('widths', StridedArray * 3), ('edges', StridedArray * 3)]
    _fields_ += [(name, ct.c_double) for name in ('area_density', 'hydraulic_diameter', 'porosity', 'split_a')]
    _fields_ += [('fields', StridedArray * 3), ('side_geometry', StridedArray * 2),
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
        packed = PackedArray(array)
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


def prepared_port(bc, cross_length, direction, centers, widths):
    """Keep the scalar types of the recorded input when copying native port values."""
    result = {'dir': type(bc.dir)(direction)}
    for end, center, width in zip(('in', 'out'), centers, widths):
        if bc.in_w > 0:
            center_type = type(getattr(bc, end + '_ctr'))
            width_type = type(getattr(bc, end + '_w'))
        else:
            width_type = type(cross_length)
            center_type = (np.float64 if isinstance(cross_length, np.integer) else
                           width_type if isinstance(cross_length, np.floating) else float)
        result[end + '_ctr'] = center_type(center)
        result[end + '_w'] = width_type(width)
    return result


def _kind(value):
    if isinstance(value, np.ndarray):
        return abi._Kind(value.dtype.itemsize * 8 if value.dtype.kind == 'f' else 64, 1, 2)
    if isinstance(value, np.floating):
        return abi._Kind(value.dtype.itemsize * 8, 1, 1)
    if isinstance(value, np.integer):
        return abi._Kind(64, 1, 1)
    return abi._Kind(64, 0, 0)


def _flow_kind(value):
    scalar = _native_flow._scalar(value)
    return abi._Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))


def _summary(value):
    return value.minimum if value.scalar else {'min': value.minimum, 'max': value.maximum}


def _records(evidence, bounds_list):
    """Restore ordered source observations without computing their values."""
    ranges = []
    for index in range(evidence.range_count):
        key, record = _range_record(evidence.ranges[index], bounds_list[index])
        message = next(iter(warning_messages({key: record})), None)
        ranges.append((key, record, message))
    pending = [read_text(item) for item in evidence.warnings[:evidence.warning_count]]
    records = {}
    plain = 0
    for key, record, message in ranges:
        if message is not None:
            while pending and pending[0] != message:
                records['native-preparation', plain] = pending.pop(0)
                plain += 1
            if pending:
                pending.pop(0)
        records[key] = record
    for message in pending:
        records['native-preparation', plain] = message
        plain += 1
    return records


_GEOMETRY_NAMES = (('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
                   ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'))
_PROPERTY_NAMES = (('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
    ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'), ('pressure_gradient_Pa_m', 'dP_per_L'),
    ('surface_transfer_W_m2K', 'H_sf'), ('fluid_conductivity_W_mK', 'K_ff'))
_PROPERTY_COLUMNS = {name: index for index, (name, _) in enumerate(abi._Properties._fields_)}


def _geometry_values(value, co2=False):
    return {key: (np.float64(getattr(value, name)) if co2 or key in ('A_0', 'D_h') else getattr(value, name))
            for name, key in _GEOMETRY_NAMES}


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
        sources = (abi._Text * (len(key)-1))(*(text(item) for item in key[:-1]))
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
    return (TOPOLOGIES[value.topology], _restore(value.cell_length_mm, value.cell_kind),
            _restore(value.wall_thickness_mm, value.wall_kind), 128)


def _inlet_key(value):
    selection = None
    if value.have_sco2_nu:
        selected = value.sco2_nu
        selection = Sco2NuConfig(
            mode=('cfd_smooth', 'experimental')[selected.mode],
            alpha_D=selected.alpha[0] if selected.have_alpha[0] else None,
            alpha_G=selected.alpha[1] if selected.have_alpha[1] else None,
            **{name: read_text(getattr(selected, name))
               for name in ('parameter_version', 'source', 'applicability')})
    return (*_geometry_key(value.geometry)[:3],
            _restore(value.velocity_m_s, value.kinds.velocity),
            _restore(value.temperature_K, value.kinds.temperature),
            _restore(value.pressure_Pa, value.kinds.pressure),
            abi._FLUIDS[value.fluid], selection, bool(value.co2_geometry))


class PreparationCacheBridge:
    """Transport completed native values through the existing scalar caches.

    Keep one bridge for each native call. It owns callback buffers and the
    last geometry observed for each inlet key. The scalar caches own entries.
    """

    def __init__(self, config, chi_error=None):
        self.config = config
        self.chi_error = chi_error
        self.buffers = []
        self.inlet_geometry = {}
        self.extrap_reasons = []
        self._active_inlet_key = None

    def geometry_at(self, action, key, value):
        """Look up or store the actual typed geometry key."""
        return self.geometry(action, _geometry_key(key), value)

    def geometry(self, action, cache_key, value):
        if action:
            geometry_cache.store(cache_key, None, _geometry_values(value))
            hit = False
        else:
            hit, saved = geometry_cache.lookup(cache_key)
            if hit:
                for name, field in _GEOMETRY_NAMES:
                    setattr(value, name, saved[field])
        if (action or hit) and self.chi_error is not None:
            raise self.chi_error
        return hit

    def inlet_at(self, action, key, value):
        """Transport inlet values and evidence without a numerical cache call."""
        cache_key = _inlet_key(key)
        return self.inlet(action, cache_key, value, bool(key.co2_geometry) or abi._FLUIDS[key.fluid] == 'co2')

    def inlet(self, action, cache_key, value, co2):
        self._active_inlet_key = cache_key
        if not action:
            hit, saved = inlet_cache.lookup(cache_key)
            if not hit:
                return False
            properties, records = saved
            for name, field in _GEOMETRY_NAMES:
                setattr(value.geometry, name, properties[field])
            for name, field in (*_PROPERTY_NAMES, ('cp', None), ('pr', None)):
                scalar = properties[field] if field is not None else getattr(saved, name)
                setattr(value.properties, name, scalar)
                value.kinds[_PROPERTY_COLUMNS[name]] = _kind(scalar)
            value.evidence, buffers = _cache_record_view(records)
            self.buffers.extend(buffers)
            self.inlet_geometry[cache_key] = _geometry_values(value.geometry, co2)
            return True
        properties = _geometry_values(value.geometry, co2)
        for name, field in _PROPERTY_NAMES:
            properties[field] = _restore(getattr(value.properties, name), value.kinds[_PROPERTY_COLUMNS[name]])
        bound = _records(value.evidence, value.evidence.range_bounds_list)
        records = {key[:-1] if isinstance(record, RangeRecord) else key: record for key, record in bound.items()}
        inlet_cache.store(cache_key, None,
            _InletCacheValue(properties, records, value.properties.cp, value.properties.pr))
        self.inlet_geometry[cache_key] = _geometry_values(value.geometry, co2)
        return False

    def observe_range(self, value, bounds_list, cached, scalar):
        selection = self._active_inlet_key[7] if self._active_inlet_key is not None else self.config.sco2_nu
        observe_range(value, bounds_list, cached, scalar, selection)

    def observe_notice(self, kind, side, value, message):
        """Use the native notice from the actual inlet topology and fluid."""
        if kind == 1:
            record_warning(('nu_preflight', 'AB'[side]), message)
        elif kind == 2:
            self.extrap_reasons.append(message)
        elif kind == 0:
            if current_warnings() is None and message:
                from sjtu_tpmshx.physical_models import tpms_calc
                _source_warning(tpms_calc.compute, message, call='_compute_cached')
        else:
            raise RuntimeError(f'unknown preparation notice kind {kind}')


def model_metadata(value, settings, config):
    """Restore model metadata from the shared prepared result views."""
    nu = dict(mode=config.sco2_nu.mode, model_version=read_text(value.sco2_nu_model_version))
    if settings.mode:
        nu.update(alpha_D=settings.alpha[0], alpha_G=settings.alpha[1],
                  interpretation=read_text(value.sco2_nu_interpretation))
        nu.update({name: read_text(getattr(settings, name))
                   for name in ('parameter_version', 'source', 'applicability')})
    else:
        nu['coefficients'] = {name: dict(zip(('c', 'a', 'd'), value.sco2_nu_coefficients[index]))
                              for index, name in enumerate(TOPOLOGIES)}
    metadata = {'sco2_nu': nu}
    co2 = value.co2
    if co2.active:
        details = {name: read_text(getattr(co2, name)) for name in (
            'version', 'application_version', 'pressure_model', 'correction_source', 'property_model', 'common_geometry')}
        details.update({name: getattr(co2, name) for name in (
            'pressure_multiplier', 'scale_K', 'scale_F', 'nu_multiplier', 'nu_floor_multiplier')})
        details.update(sides=[side for index, side in enumerate('AB') if co2.sides[index]],
                       Re_range=list(co2.re_range), Pr_range=list(co2.pr_range))
        metadata['co2'] = details
    return metadata


def resolved_flow_config(config, flow, targets):
    """Return a config with the native inlet speeds."""
    fluids = {}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        if targets is not None or fluid.mass_flow_kg_s is not None:
            fluids['fluid_' + side] = replace(fluid, u_mps=_native_flow._restore(flow.speeds[index]),
                mass_flow_kg_s=None if targets is not None else fluid.mass_flow_kg_s)
    return replace(config, **fluids).validate(resolved_inlet_speeds=True) if fluids else config


def drag_application_metadata(value, extra, inlet_speed, extension):
    """Read the native D-F application record for a saved case."""
    metadata = {key: _summary(getattr(value, name)) for name, key in (
        ('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
        ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF'))}
    metadata.update(scale_K=value.scale_permeability, scale_F=value.scale_forchheimer,
                    campaign=read_text(value.campaign), scope=read_text(value.scope))
    for name in ('application_scope', 'fluid'):
        text = read_text(getattr(extra, name))
        if text:
            metadata[name] = text
    if extra.calibration_count:
        metadata['calibration'] = {read_text(item.key): read_text(item.value)
                                   for item in extra.calibration[:extra.calibration_count]}
    if extra.have_selection and extra.selection.scope:
        metadata.update(inlet_u_mps=inlet_speed, extrapolated=bool(extra.selection.flags & 2))
        for name, key in (('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')):
            values = getattr(extra.selection, name)
            metadata[key] = {'min': values[0], 'max': values[1]}
    if extension is not None:
        for name in ('transfer_policy', 'geometry_application'):
            text = read_text(getattr(extension, name))
            if text:
                metadata[name] = text
        if extension.have_reference_geometry:
            metadata['reference_geometry_mm'] = dict(zip(('L', 't'), extension.reference_geometry_mm))
    return metadata
