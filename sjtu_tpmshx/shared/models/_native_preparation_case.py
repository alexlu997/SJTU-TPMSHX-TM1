"""Transport owned 2D preparation data through the native C interface."""
from contextlib import contextmanager
import ctypes as ct
import dis
from functools import lru_cache, partial
import warnings

import numpy as np

from . import _native_flow, _native_preparation, _native_properties
from ._native_properties import _Failure as _PropertyFailure
from sjtu_tpmshx.shared.logutil import get_logger


_U = ct.c_uint32
_S = ct.c_size_t
_D = ct.c_double


def _structure(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


def _doubles(names):
    return [(name, _D) for name in names.split()]


_Port = _structure('Port', [('direction', ct.c_int32), *_doubles(
    'inlet_center_m inlet_width_m outlet_center_m outlet_width_m'), ('uniform_inlet', _U)])
_Inlet = _structure('Inlet', [('fluid', _U), *_doubles('velocity_m_s temperature_K pressure_Pa'),
                            ('port', _Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_InputV1 = _structure('Input', [('abi_version', _U), ('struct_size', _S),
    *_doubles('length_m height_m'), ('requested_nx', _S), ('requested_ny', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *_doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('have_physical_depth', _U), ('geometry_mode', _U), ('df_mode', _U),
    ('physical_depth_m', _D)])
_Options = _structure('Options', [('abi_version', _U), ('struct_size', _S),
                                ('have_chi', _U), ('allow_extrapolation', _U), ('chi', _D)])
_Array = _structure('Array', [('data', ct.POINTER(_D)), ('size', _S)])
_Text = _structure('Text', [('data', ct.POINTER(ct.c_char)), ('size', _S)])
_Event = _structure('Event', [('kind', _U), ('logger', _Text), ('message', _Text), ('floating_event', _U)])
_EventFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.POINTER(_Event))
_Callbacks = _structure('Callbacks', [('abi_version', _U), ('struct_size', _S),
                                    ('event', _EventFunction), ('context', ct.c_void_p)])
_Properties = _structure('Properties', _doubles(
    'rho mu k_f cp pr re nu permeability_m2 forchheimer_per_m pressure_gradient_Pa_m '
    'surface_transfer_W_m2K fluid_conductivity_W_mK solid_conductivity_W_mK'))
_DragSummary = _structure('DragSummary', [*_doubles('minimum maximum'), ('scalar', _U)])
_DragEvidence = _structure('DragEvidence', [(name, _DragSummary) for name in
    'base_permeability base_forchheimer applied_permeability applied_forchheimer'.split()] +
    _doubles('scale_permeability scale_forchheimer') + [('campaign', _Text), ('scope', _Text)])
_Side = _structure('Side', [('inlet', _Inlet), ('properties', _Properties),
    *_doubles('seed_permeability_m2 seed_forchheimer_per_m'),
    *((name, _Array) for name in ('cross_widths stream_widths row_permeability row_forchheimer '
        'permeability forchheimer inlet_geometry outlet_geometry inlet_profile outlet_profile outlet_u_fraction').split()),
    ('inlet_bounds', _D * 2), ('outlet_bounds', _D * 2), ('drag_evidence', _DragEvidence)])
_Sample = _structure('Sample', [('have_finite', _U), *_doubles('minimum maximum'),
    *((name, _S) for name in 'minimum_index maximum_index low high size nonfinite'.split())])
_Range = _structure('Range', [('source', ct.POINTER(_Text)), ('source_count', _S),
    *((name, _Text) for name in 'side stage layout label quantity unit'.split()),
    ('bounds', _D * 2), ('shape', ct.POINTER(_S)), ('rank', _S), ('sample', _Sample), ('last', _Sample)])
_Model = _structure('Model', [(name, _Text) for name in 'name version side'.split()])
_ResultV1 = _structure('Result', [('abi_version', _U), ('struct_size', _S), ('input', _InputV1),
    ('options', _Options), ('nx', _S), ('ny', _S),
    *((name, _Array) for name in 'dx dy x_edges y_edges x_breaks y_breaks'.split()),
    *_doubles('epsilon epsilon_a epsilon_b area_density_per_m hydraulic_diameter_m '
              'uniform_solid_conductivity hydraulic_radius_m cell_length_m wall_thickness_m split_a'),
    *((name, _Array) for name in 'cell_length wall_thickness total_porosity solid_conductivity hydraulic_radius'.split()),
    ('sides', _Side * 2), ('models', _Model * 4), ('ranges', ct.POINTER(_Range)), ('range_count', _S),
    ('warnings', ct.POINTER(_Text)), ('warning_count', _S), ('events', ct.POINTER(_Event)),
    ('event_count', _S), ('owner', ct.c_void_p)])


_struct = _structure
_Kind = _struct('Kind', [(name, _U) for name in ('precision', 'strong', 'layout')])
_GridKinds = _struct('GridKinds', [('abi_version', _U), ('struct_size', _S),
    ('lengths', _Kind * 2), ('ports', (_Kind * 4) * 2)])
_InletKinds = _struct('InletKinds', [(name, _Kind) for name in ('velocity', 'temperature', 'pressure')])
_Kinds = _struct('Kinds', [(name, _Kind) for name in ('cell_length', 'wall_thickness', 'solid_conductivity')] + [('sides', _InletKinds * 2)])
_Nu = _struct('Nu', [('mode', _U), ('have_alpha', _U * 2), ('alpha', _D * 2)] + [(name, _Text) for name in ('parameter_version', 'source', 'applicability')])
_InputV2 = _struct('InputV2', [('abi_version', _U), ('struct_size', _S), ('values', _InputV1), ('sco2_nu', _Nu), ('kinds', _Kinds)])
_Selection = _struct('Selection', [(name, _U) for name in ('branch', 'campaign', 'scope', 'flags')] + _doubles('scale_K scale_F') + [(name, _D * 2) for name in ('application_u', 'calibration_u', 'runtime_u')])
_TextField = _struct('TextField', [('key', _Text), ('value', _Text)])
_Drag = _struct('Drag', [('have_selection', _U), ('selection', _Selection), ('application_scope', _Text), ('fluid', _Text), ('calibration', ct.POINTER(_TextField)), ('calibration_count', _S)])
_Co2 = _struct('Co2', [('active', _U), ('sides', _U * 2)] + [(name, _Text) for name in ('version', 'application_version', 'pressure_model')] + _doubles('pressure_multiplier scale_K scale_F nu_multiplier nu_floor_multiplier') + [(name, _Text) for name in ('correction_source', 'property_model', 'common_geometry')] + [('re_range', _D * 2), ('pr_range', _D * 2)])
_ResultV2 = _struct('ResultV2', [('abi_version', _U), ('struct_size', _S), ('values', _ResultV1), ('input_kinds', _Kinds), ('field_kinds', _Kind * 5), ('property_kinds', (_Kind * 13) * 2), ('sco2_nu', _Nu), ('sco2_nu_model_version', _Text), ('sco2_nu_interpretation', _Text), ('sco2_nu_coefficients', (_D * 3) * 2), ('drag', _Drag * 2), ('co2', _Co2), ('notices', ct.POINTER(_Text)), ('notice_count', _S), ('range_bounds_list', ct.POINTER(_U))])
_Cause = _struct('Cause', [('kind', _U), ('message', ct.c_char * 4096)])
_Failure = _struct('Failure', [('abi_version', _U), ('struct_size', _S)] + [(name, _U) for name in ('kind', 'side', 'have_property', 'cause_count')] + [('property', _PropertyFailure), ('causes', _Cause * 2)])
_FLUIDS = ('air', 'water', 'sco2', 'co2')

_FlowInput = _struct('FlowInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _InputV2), ('physical_depth_kind', _Kind), ('target_kinds', _Kind * 2),
    ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)])
_Evidence = _struct('FlowEvidence', [('ranges', ct.POINTER(_Range)), ('range_count', _S),
    ('range_bounds_list', ct.POINTER(_U)), ('warnings', ct.POINTER(_Text)), ('warning_count', _S),
    ('events', ct.POINTER(_Event)), ('event_count', _S)])
_Flow = _struct('FlowResult', [('abi_version', _U), ('struct_size', _S), ('input', _InputV2),
    ('have_capacities', _U), ('capacities', _native_flow._Scalar * 2), ('speeds', _native_flow._Scalar * 2),
    ('evidence', _Evidence), ('owner', ct.c_void_p)])
_FlowCase = _struct('FlowCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _ResultV2), ('flow', _Flow), ('owner', ct.c_void_p)])

_Controls = _struct('ContinuousControls', [('n_ctrl_x', _S), ('n_ctrl_y', _S),
    ('spline_order', _U), ('symmetric_y', _U), ('L_bounds_mm', _D * 2),
    ('t_bounds_mm', _D * 2), ('decision_mm', _Array)])
_ContinuousInput = _struct('ContinuousInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _FlowInput), ('controls', _Controls)])
_ContinuousDrag = _struct('ContinuousDrag', [('transfer_policy', _Text),
    ('geometry_application', _Text), ('have_reference_geometry', _U), ('reference_geometry_mm', _D * 2)])
_ContinuousFlow = _struct('ContinuousFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_ContinuousCase = _struct('ContinuousCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _ResultV2), ('flow', _Flow), ('controls', _Controls),
    ('area_density_per_m', _Array), ('hydraulic_diameter_m', _Array),
    ('fluid_conductivity', _Array * 2), ('drag', _ContinuousDrag * 2), ('owner', ct.c_void_p)])

_HostFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U)
_HostCallbacks = _struct('HostCallbacks', [('values', _Callbacks), ('validate_host_input', _HostFunction)])
_GeometryCache = _struct('GeometryCache', _doubles('epsilon epsilon_a epsilon_b area_density_per_m hydraulic_diameter_m'))
_InletCache = _struct('InletCache', [('geometry', _GeometryCache), ('properties', _Properties),
                                  ('kinds', _Kind * 13), ('evidence', _Evidence)])
_GeometryCacheFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_GeometryCache), ct.POINTER(_U))
_InletCacheFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, ct.POINTER(_Inlet), _Kind,
                                 ct.POINTER(_InletCache), ct.POINTER(_U))
_RangeFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_Range), _U, _U, _D)
_NoticeFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, _D, _Text)
_CacheCallbacks = _struct('CacheCallbacks', [('values', _HostCallbacks),
    ('geometry_cache', _GeometryCacheFunction), ('inlet_cache', _InletCacheFunction),
    ('observe_range', _RangeFunction), ('observe_notice', _NoticeFunction)])


_GridScalar = _native_flow._Scalar
_Region = _struct('ZoneRegion', [('name', _Text), ('bounds', _GridScalar * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D), ('cell_kind', _Kind), ('wall_kind', _Kind)])
_ZonedInput = _struct('ZonedInput', [('abi_version', _U), ('struct_size', _S), ('values', _InputV2),
    ('kind', _U), ('axis', _U), ('regions', ct.POINTER(_Region)), ('region_count', _S)])
_RegionValues = _struct('ZoneValues', [('region', _Region), ('geometry', _GeometryCache),
    ('property_geometry', _GeometryCache * 2), ('solid_conductivity', _D),
    ('properties', _Properties * 2), ('property_kinds', (_Kind * 13) * 2)])
_ZonedCase = _struct('ZonedCase', [('abi_version', _U), ('struct_size', _S), ('prepared', _ResultV2),
    ('kind', _U), ('axis', _U), ('regions', ct.POINTER(_RegionValues)), ('region_count', _S),
    ('zone_id', ct.POINTER(ct.c_int32)), ('cell_count', _S),
    *[(name, _Array) for name in ('thermal_porosity', 'area_density_per_m', 'hydraulic_diameter_m',
                                'design_area_density_per_m')],
    ('fluid_conductivity', _Array * 2), ('volumetric_transfer', _Array * 2), ('owner', ct.c_void_p)])
_LUTView = _struct('SigmoidLUTView', [(name, _Array) for name in
    ('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m')] + [('porosity_fast', _U), ('area_fast', _U)])
_SigmoidControls = _struct('SigmoidControls', [('decision_mm', _Array),
    ('inlet_transition', _GridScalar), ('outlet_transition', _GridScalar)])
_SigmoidInput = _struct('SigmoidInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _ZonedInput), ('controls', _SigmoidControls), ('lut', _LUTView)])
_SigmoidCase = _struct('SigmoidCase', [('abi_version', _U), ('struct_size', _S),
    ('values', _ZonedCase), ('controls', _SigmoidControls), ('owner', ct.c_void_p)])
_FlowOptions = [('physical_depth_kind', _Kind), ('target_kinds', _Kind * 2),
                ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)]
_ZonedFlowInput = _struct('ZonedFlowInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _ZonedInput), *_FlowOptions])
_SigmoidFlowInput = _struct('SigmoidFlowInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _SigmoidInput), *_FlowOptions])
_ZonedFlow = _struct('ZonedFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('input', _ZonedInput), ('owner', ct.c_void_p)])
_SigmoidFlow = _struct('SigmoidFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('input', _SigmoidInput), ('owner', ct.c_void_p)])
_ZonedFlowCase = _struct('ZonedFlowCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _ZonedCase), ('flow', _ZonedFlow), ('owner', ct.c_void_p)])
_SigmoidFlowCase = _struct('SigmoidFlowCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _SigmoidCase), ('flow', _SigmoidFlow), ('owner', ct.c_void_p)])
_SpatialModel = _struct('SpatialModel', [('solid_conductivity_W_mK', _D), ('solid_conductivity_kind', _Kind), ('allow_geometry_extrapolation', _U), ('load_default_lut', _U)])
_ZonedHostInput = _struct('ZonedHostInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _ZonedFlowInput), ('model', _SpatialModel)])
_SigmoidHostInput = _struct('SigmoidHostInput', [('abi_version', _U), ('struct_size', _S),
    ('values', _SigmoidFlowInput), ('model', _SpatialModel)])
_ZonedHostFlow = _struct('ZonedHostFlow', [('abi_version', _U), ('struct_size', _S),
    ('values', _ZonedFlow), ('model', _SpatialModel), ('owner', ct.c_void_p)])
_SigmoidHostFlow = _struct('SigmoidHostFlow', [('abi_version', _U), ('struct_size', _S),
    ('values', _SigmoidFlow), ('model', _SpatialModel), ('owner', ct.c_void_p)])
_ZonedHostCase = _struct('ZonedHostCase', [('abi_version', _U), ('struct_size', _S),
    ('values', _ZonedFlowCase), ('model', _SpatialModel), ('design_pore_porosity', _Array), ('owner', ct.c_void_p)])
_SigmoidHostCase = _struct('SigmoidHostCase', [('abi_version', _U), ('struct_size', _S),
    ('values', _SigmoidFlowCase), ('model', _SpatialModel), ('design_pore_porosity', _Array), ('owner', ct.c_void_p)])
_GeometryKey = _struct('GeometryKey', [('topology', _U), *_doubles('cell_length_mm wall_thickness_mm'),
    ('cell_kind', _Kind), ('wall_kind', _Kind)])
_InletKey = _struct('InletKey', [('geometry', _GeometryKey), ('fluid', _U),
    *_doubles('velocity_m_s temperature_K pressure_Pa'), ('kinds', _InletKinds),
    ('have_sco2_nu', _U), ('sco2_nu', _Nu), ('co2_geometry', _U)])
_GeometryAtFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_GeometryKey),
                                 ct.POINTER(_GeometryCache), ct.POINTER(_U))
_InletAtFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_InletKey),
                              ct.POINTER(_InletCache), ct.POINTER(_U))
_LUTCacheFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, _S, ct.POINTER(_LUTView), ct.POINTER(_U))
_KeyedCallbacks = _struct('KeyedCallbacks', [('values', _CacheCallbacks),
    ('geometry_cache_at', _GeometryAtFunction), ('inlet_cache_at', _InletAtFunction),
    ('sigmoid_lut_cache', _LUTCacheFunction)])


class _Bindings:
    def __init__(self, path):
        self.owner = _native_preparation._load_library(path)
        self.operations = {}
        self.releases = {}
        for version, source, flow, full, prefix in (
                (3, _FlowInput, _Flow, _FlowCase, 'flow'),
                (4, _ContinuousInput, _ContinuousFlow, _ContinuousCase, 'continuous')):
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case'):
                result = full if name == 'prepare_flow_case' else flow
                entry = name if version == 3 else name.replace('_', '_continuous_', 1)
                self.operations[version, name] = self.owner.bind(
                    f'tpmshx_{entry}_2d_v7',
                    [ct.POINTER(source), ct.POINTER(_GridKinds), ct.POINTER(_Options), ct.POINTER(_Callbacks),
                     ct.POINTER(result), ct.POINTER(_Failure), ct.POINTER(ct.c_char), _S])
            for result, suffix in ((flow, 'flow' if version == 4 else ''), (full, 'case')):
                middle = '_'.join(value for value in (prefix, suffix) if value)
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_{middle}_2d_release_v{version}', [ct.POINTER(result)], None)


        for source, flow, full, prefix in (
                (_ZonedHostInput, _ZonedHostFlow, _ZonedHostCase, 'zoned'),
                (_SigmoidHostInput, _SigmoidHostFlow, _SigmoidHostCase, 'sigmoid')):
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case'):
                result = full if name == 'prepare_flow_case' else flow
                entry = name.replace('_', '_' + prefix + '_', 1)
                self.operations[source, name] = self.owner.bind(
                    f'tpmshx_{entry}_2d_v9',
                    [ct.POINTER(source), ct.POINTER(_GridKinds), ct.POINTER(_Options), ct.POINTER(_Callbacks),
                     ct.POINTER(result), ct.POINTER(_Failure), ct.POINTER(ct.c_char), _S])
            for result, suffix in ((flow, 'flow'), (full, 'flow_case')):
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_{prefix}_{suffix}_2d_release_v9', [ct.POINTER(result)], None)


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


def _text(value):
    return ct.string_at(value.data, value.size).decode('utf-8')


def _array(value, shape=None, *, precision=64):
    result = (np.ctypeslib.as_array(value.data, shape=(value.size,)).astype(f'float{precision}', copy=True)
              if value.size else np.empty(0, dtype=f'float{precision}'))
    return result if shape is None else result.reshape(shape)


def _restore(value, kind):
    if not kind.strong:
        return float(value)
    dtype = np.dtype(f'float{kind.precision}')
    return np.asarray(value, dtype=dtype) if kind.layout == 2 else dtype.type(value)


def _check_status(status, error, failure):
    if not status:
        return
    from .fluid_props import WaterStateError
    classes = {1: ValueError, 2: WaterStateError, 3: RuntimeError}
    exception = MemoryError if status == 2 else classes.get(failure.kind, RuntimeError)
    problem = exception(error.value.decode('utf-8', errors='replace'))
    current = problem
    for item in failure.causes[:failure.cause_count]:
        cause = classes.get(item.kind, RuntimeError)(item.message.decode('utf-8', errors='replace'))
        current.__cause__ = cause
        current = cause
    raise problem


def _source_warning(function, message, *, call=None, binary=None, category=UserWarning):
    """Keep the original warning module, source line and filter registry."""
    code = function.__code__
    if binary is not None:
        operator, occurrence = binary
        line = [item.positions.lineno for item in dis.get_instructions(function)
                if item.opname == 'BINARY_OP' and item.argrepr == operator][occurrence]
        module = function.__globals__['__name__']
    else:
        line = (next(item.positions.lineno for item in dis.get_instructions(function)
                     if item.opname.startswith('LOAD_')
                     and (item.argval == call or item.opname.startswith('LOAD_FAST')
                          and isinstance(item.argval, tuple) and call in item.argval)) if call else
                max(line for _start, _end, line in code.co_lines() if line is not None))
        module = function.__module__
    warnings.warn_explicit(message, category, code.co_filename, line,
        module=module, registry=function.__globals__.setdefault('__warningregistry__', {}))


def _control_axis_warning(source, message):
    from .continuous_field import ContinuousFieldConfig, control_axis
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
                     geometry_cache_at=None, inlet_cache_at=None, sigmoid_lut_cache=None):
    """Own callbacks and preserve their first exception across the C boundary."""
    callback_errors = []

    def event(_context, pointer):
        try:
            item = pointer.contents
            if item.kind == 0:
                get_logger(_text(item.logger).removeprefix('tpmshx.')).info(_text(item.message))
            elif item.kind == 1:
                message = _text(item.message)
                if message.startswith('[geometry extrap]'):
                    from .sigmoid_field import build_continuous_geometry
                    _source_warning(build_continuous_geometry, message, call='_geometry_from_fields')
                else:
                    from .input_validation import surrogate_extrap_reasons
                    _source_warning(surrogate_extrap_reasons, message, call='check_surrogate_domain_at_point')
            elif item.kind == 2:
                source = _text(item.message)
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

    def validate(_context, stage, side):
        try:
            validate_host_input(stage, side)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def geometry(_context, action, value, hit):
        try:
            hit[0] = geometry_cache(action, value.contents)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def inlet(_context, action, side, source, kind, value, hit):
        try:
            hit[0] = inlet_cache(action, side, source.contents, kind, value.contents)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def observe(_context, cached, value, bounds_list, have_scalar, scalar):
        try:
            if observe_range is not None:
                observe_range(value.contents, bool(bounds_list), bool(cached), scalar if have_scalar else None)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def notice(_context, kind, side, value, message):
        try:
            if observe_notice is not None:
                observe_notice(kind, side, value, _text(message))
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def geometry_at(_context, action, key, value, hit):
        try:
            hit[0] = geometry_cache_at(action, key.contents, value.contents)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def inlet_at(_context, action, key, value, hit):
        try:
            hit[0] = inlet_cache_at(action, key.contents, value.contents)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    def lut_cache(_context, action, topology, resolution, value, hit):
        try:
            hit[0] = sigmoid_lut_cache(action, topology, resolution, value.contents)
            return 0
        except BaseException as problem:
            callback_errors.append(problem)
            return 1

    event_function, host_function = _EventFunction(event), _HostFunction(validate)
    if geometry_cache_at is not None or inlet_cache_at is not None or sigmoid_lut_cache is not None:
        callbacks = _KeyedCallbacks(_CacheCallbacks(_HostCallbacks(
            _Callbacks(9, ct.sizeof(_KeyedCallbacks), event_function, None), host_function),
            _GeometryCacheFunction(), _InletCacheFunction(), _RangeFunction(observe), _NoticeFunction(notice)),
            _GeometryAtFunction(geometry_at) if geometry_cache_at else _GeometryAtFunction(),
            _InletAtFunction(inlet_at) if inlet_cache_at else _InletAtFunction(),
            _LUTCacheFunction(lut_cache) if sigmoid_lut_cache else _LUTCacheFunction())
        descriptor = callbacks.values.values.values
    elif geometry_cache is None and inlet_cache is None and observe_range is None and observe_notice is None:
        callbacks = _HostCallbacks(_Callbacks(2, ct.sizeof(_HostCallbacks), event_function, None), host_function)
        descriptor = callbacks.values
    else:
        callbacks = _CacheCallbacks(_HostCallbacks(_Callbacks(4, ct.sizeof(_CacheCallbacks), event_function, None), host_function),
                                   _GeometryCacheFunction(geometry), _InletCacheFunction(inlet),
                                   _RangeFunction(observe), _NoticeFunction(notice))
        descriptor = callbacks.values.values
    return callbacks, descriptor, callback_errors


@contextmanager
def operation(name, source, options, validate_host_input, geometry_cache=None, inlet_cache=None,
              observe_range=None, observe_notice=None, nominal_grid_warning=None, *,
              geometry_cache_at=None, inlet_cache_at=None, sigmoid_lut_cache=None):
    """Keep the complete owner alive until the caller copies all required data."""
    version = source.abi_version
    result_type = ((_ContinuousCase if name == 'prepare_flow_case' else _ContinuousFlow)
                   if version == 4 else (_FlowCase if name == 'prepare_flow_case' else _Flow))
    if version == 9:
        result_type = ((_SigmoidHostCase if name == 'prepare_flow_case' else _SigmoidHostFlow)
                       if isinstance(source, _SigmoidHostInput) else
                       (_ZonedHostCase if name == 'prepare_flow_case' else _ZonedHostFlow))
    result = result_type(version, ct.sizeof(result_type))
    failure, error = _Failure(2, ct.sizeof(_Failure)), ct.create_string_buffer(4096)
    bindings = _bindings(_native_preparation._library().path)
    callbacks, descriptor, callback_errors = _callback_bridge(
        validate_host_input, geometry_cache, inlet_cache, observe_range, observe_notice,
        nominal_grid_warning, geometry_cache_at=geometry_cache_at, inlet_cache_at=inlet_cache_at,
        sigmoid_lut_cache=sigmoid_lut_cache)
    try:
        status = bindings.operations[type(source) if version == 9 else version, name](
            ct.byref(source), ct.byref(source._grid_kinds), ct.byref(options), ct.byref(descriptor), ct.byref(result),
            ct.byref(failure), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        _check_status(status, error, failure)
        yield result
    finally:
        bindings.releases[result_type](ct.byref(result))
