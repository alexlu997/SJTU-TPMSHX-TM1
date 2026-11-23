"""C layouts for complete preparation and independent inlet-property queries."""
import ctypes as ct

from ._native_df import _Pressure as _DFPressure
from ._native_properties import _Failure as _PropertyFailure
from ._native_values import DoubleArray as _Array, Text as _Text


_U = ct.c_uint32
_S = ct.c_size_t
_D = ct.c_double


def _structure(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


def _doubles(names):
    return [(name, _D) for name in names.split()]


_struct = _structure
_FLUIDS = ('air', 'water', 'sco2', 'co2')

_Port = _structure('Port', [('direction', ct.c_int32), *_doubles(
    'inlet_center_m inlet_width_m outlet_center_m outlet_width_m'), ('uniform_inlet', _U)])
_Inlet = _structure('Inlet', [('fluid', _U), *_doubles('velocity_m_s temperature_K pressure_Pa'),
                              ('port', _Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_TextField = _struct('TextField', [('key', _Text), ('value', _Text)])
_Nu = _struct('Nu', [('mode', _U), ('have_alpha', _U * 2), ('alpha', _D * 2)] + [
    (name, _Text) for name in ('parameter_version', 'source', 'applicability')])
_Input = _structure('Input', [('abi_version', _U), ('struct_size', _S),
    *_doubles('length_m height_m'), ('requested_nx', _S), ('requested_ny', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *_doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('have_physical_depth', _U), ('geometry_mode', _U), ('df_mode', _U),
    ('physical_depth_m', _D), ('sco2_nu', _Nu)])
_Options = _structure('Options', [('abi_version', _U), ('struct_size', _S),
                                  ('have_chi', _U), ('allow_extrapolation', _U), ('chi', _D)])
_Event = _structure('Event', [('kind', _U), ('logger', _Text), ('message', _Text), ('floating_event', _U)])
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
_Selection = _struct('Selection', [(name, _U) for name in ('branch', 'campaign', 'scope', 'flags')] +
    _doubles('scale_K scale_F') + [(name, _D * 2) for name in ('application_u', 'calibration_u', 'runtime_u')])
_Drag = _struct('Drag', [('have_selection', _U), ('selection', _Selection), ('application_scope', _Text),
    ('fluid', _Text), ('calibration', ct.POINTER(_TextField)), ('calibration_count', _S)])
_Co2 = _struct('Co2', [('active', _U), ('sides', _U * 2)] +
    [(name, _Text) for name in ('version', 'application_version', 'pressure_model')] +
    _doubles('pressure_multiplier scale_K scale_F nu_multiplier nu_floor_multiplier') +
    [(name, _Text) for name in ('correction_source', 'property_model', 'common_geometry')] +
    [('re_range', _D * 2), ('pr_range', _D * 2)])
_Result = _structure('Result', [('abi_version', _U), ('struct_size', _S), ('input', _Input),
    ('options', _Options), ('nx', _S), ('ny', _S),
    *((name, _Array) for name in 'dx dy x_edges y_edges x_breaks y_breaks'.split()),
    *_doubles('epsilon epsilon_a epsilon_b area_density_per_m hydraulic_diameter_m '
              'uniform_solid_conductivity hydraulic_radius_m cell_length_m wall_thickness_m split_a'),
    *((name, _Array) for name in 'cell_length wall_thickness total_porosity solid_conductivity hydraulic_radius'.split()),
    ('sides', _Side * 2), ('models', _Model * 4), ('ranges', ct.POINTER(_Range)), ('range_count', _S),
    ('range_bounds_list', ct.POINTER(_U)), ('warnings', ct.POINTER(_Text)), ('warning_count', _S),
    ('events', ct.POINTER(_Event)), ('event_count', _S), ('sco2_nu', _Nu),
    ('sco2_nu_model_version', _Text), ('sco2_nu_interpretation', _Text),
    ('sco2_nu_coefficients', (_D * 3) * 2), ('drag', _Drag * 2), ('co2', _Co2),
    ('notices', ct.POINTER(_Text)), ('notice_count', _S)])

_Cause = _struct('Cause', [('kind', _U), ('message', ct.c_char * 4096)])
_Failure = _struct('Failure', [('abi_version', _U), ('struct_size', _S)] +
    [(name, _U) for name in ('kind', 'side', 'have_property', 'cause_count')] +
    [('property', _PropertyFailure), ('causes', _Cause * 2)])

_Evidence = _struct('FlowEvidence', [('ranges', ct.POINTER(_Range)), ('range_count', _S),
    ('range_bounds_list', ct.POINTER(_U)), ('warnings', ct.POINTER(_Text)), ('warning_count', _S),
    ('events', ct.POINTER(_Event)), ('event_count', _S)])
_GeometryCache = _struct('GeometryCache', _doubles('epsilon epsilon_a epsilon_b area_density_per_m hydraulic_diameter_m'))
_InletCache = _struct('InletCache', [('geometry', _GeometryCache), ('properties', _Properties),
                                     ('evidence', _Evidence)])
_GeometryKey = _struct('GeometryKey', [('topology', _U), *_doubles('cell_length_mm wall_thickness_mm')])
_InletKey = _struct('InletKey', [('geometry', _GeometryKey), ('fluid', _U),
    *_doubles('velocity_m_s temperature_K pressure_Pa'),
    ('have_sco2_nu', _U), ('sco2_nu', _Nu), ('co2_geometry', _U)])
_LUTView = _struct('SigmoidLUTView', [(name, _Array) for name in
    ('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m')] + [('porosity_fast', _U), ('area_fast', _U)])

_EventFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.POINTER(_Event))
_HostFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U)
_GeometryCacheFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_GeometryCache), ct.POINTER(_U))
_InletCacheFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, ct.POINTER(_Inlet),
                                   ct.POINTER(_InletCache), ct.POINTER(_U))
_RangeFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_Range), _U, _U, _D)
_NoticeFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, _D, _Text)
_GeometryAtFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_GeometryKey),
                                   ct.POINTER(_GeometryCache), ct.POINTER(_U))
_InletAtFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, ct.POINTER(_InletKey),
                                ct.POINTER(_InletCache), ct.POINTER(_U))
_LUTCacheFunction = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, _U, _U, _S, ct.POINTER(_LUTView), ct.POINTER(_U))
_Callbacks = _structure('Callbacks', [('abi_version', _U), ('struct_size', _S),
    ('context', ct.c_void_p), ('validate_grid_stage', _U),
    ('event', _EventFunction), ('validate_host_input', _HostFunction),
    ('geometry_cache', _GeometryCacheFunction), ('inlet_cache', _InletCacheFunction),
    ('observe_range', _RangeFunction), ('observe_notice', _NoticeFunction),
    ('geometry_cache_at', _GeometryAtFunction), ('inlet_cache_at', _InletAtFunction),
    ('sigmoid_lut_cache', _LUTCacheFunction)])

_Flow = _struct('FlowResult', [('input', _Input), ('have_capacities', _U),
    ('capacities', _D * 2), ('speeds', _D * 2), ('evidence', _Evidence)])
_ThermalSides = _struct('ThermalSides', [('have_side_geometry', _U), ('side_geometry', (_D * 4) * 2)])
_Controls = _struct('ContinuousControls', [('n_ctrl_x', _S), ('n_ctrl_y', _S),
    ('spline_order', _U), ('symmetric_y', _U), ('L_bounds_mm', _D * 2),
    ('t_bounds_mm', _D * 2), ('decision_mm', _Array)])
_ContinuousDrag = _struct('ContinuousDrag', [('transfer_policy', _Text),
    ('geometry_application', _Text), ('have_reference_geometry', _U), ('reference_geometry_mm', _D * 2)])
_Region = _struct('ZoneRegion', [('name', _Text), ('bounds', _D * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D)])
_RegionValues = _struct('ZoneValues', [('region', _Region), ('geometry', _GeometryCache),
    ('property_geometry', _GeometryCache * 2), ('solid_conductivity', _D),
    ('properties', _Properties * 2)])
_SigmoidControls = _struct('SigmoidControls', [('decision_mm', _Array),
    ('inlet_transition', _D), ('outlet_transition', _D)])
_SpatialModel = _struct('SpatialModel', [('solid_conductivity_W_mK', _D),
    ('allow_geometry_extrapolation', _U), ('load_default_lut', _U)])
_SigmoidLUT = _struct('SigmoidLUT', [('abi_version', _U), ('struct_size', _S),
    *((name, _Array) for name in ('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m')),
    ('porosity_fast', _U), ('area_fast', _U), ('owner', ct.c_void_p)])

_FlowOptions = [('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)]

_UniformInput = _struct('UniformInput', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), *_FlowOptions])
_UniformFlow = _struct('UniformFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('owner', ct.c_void_p)])
_UniformCase = _struct('UniformCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('thermal', _ThermalSides), ('owner', ct.c_void_p)])

_ContinuousInput = _struct('ContinuousInput', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), *_FlowOptions, ('controls', _Controls)])
_ContinuousFlow = _struct('ContinuousFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_ContinuousCase = _struct('ContinuousCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('controls', _Controls),
    ('area_density_per_m', _Array), ('hydraulic_diameter_m', _Array),
    ('fluid_conductivity', _Array * 2), ('design_pore_porosity', _Array),
    ('drag', _ContinuousDrag * 2), ('owner', ct.c_void_p)])

_ZonedInput = _struct('ZonedInput', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), *_FlowOptions, ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_Region)), ('region_count', _S), ('model', _SpatialModel)])
_ZonedFlow = _struct('ZonedFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_Region)), ('region_count', _S), ('model', _SpatialModel),
    ('owner', ct.c_void_p)])
_ZonedCase = _struct('ZonedCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_RegionValues)), ('region_count', _S),
    ('zone_id', ct.POINTER(ct.c_int32)), ('cell_count', _S),
    *((name, _Array) for name in ('thermal_porosity', 'area_density_per_m', 'hydraulic_diameter_m',
                                  'design_area_density_per_m', 'design_pore_porosity')),
    ('fluid_conductivity', _Array * 2), ('volumetric_transfer', _Array * 2),
    ('model', _SpatialModel), ('thermal', _ThermalSides), ('owner', ct.c_void_p)])

_SigmoidInput = _struct('SigmoidInput', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), *_FlowOptions, ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_Region)), ('region_count', _S),
    ('controls', _SigmoidControls), ('lut', _LUTView), ('model', _SpatialModel)])
_SigmoidFlow = _struct('SigmoidFlow', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_Region)), ('region_count', _S),
    ('controls', _SigmoidControls), ('lut', _LUTView), ('model', _SpatialModel),
    ('owner', ct.c_void_p)])
_SigmoidCase = _struct('SigmoidCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_RegionValues)), ('region_count', _S),
    ('zone_id', ct.POINTER(ct.c_int32)), ('cell_count', _S),
    *((name, _Array) for name in ('thermal_porosity', 'area_density_per_m', 'hydraulic_diameter_m',
                                  'design_area_density_per_m', 'design_pore_porosity')),
    ('fluid_conductivity', _Array * 2), ('volumetric_transfer', _Array * 2),
    ('controls', _SigmoidControls), ('lut', _LUTView),
    ('model', _SpatialModel), ('thermal', _ThermalSides), ('owner', ct.c_void_p)])

_StripeCase = _struct('StripeCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('kind', _U), ('axis', _U),
    ('regions', ct.POINTER(_RegionValues)), ('region_count', _S),
    ('zone_id', ct.POINTER(ct.c_int32)), ('cell_count', _S),
    *((name, _Array) for name in ('thermal_porosity', 'area_density_per_m', 'hydraulic_diameter_m',
                                  'design_area_density_per_m', 'design_pore_porosity')),
    ('fluid_conductivity', _Array * 2), ('volumetric_transfer', _Array * 2),
    ('region_hydraulic_radii_m', _Array),
    ('model', _SpatialModel), ('thermal', _ThermalSides), ('owner', ct.c_void_p)])

_InletQueryInput = _struct('InletQueryInput', [('abi_version', _U), ('struct_size', _S),
    ('inlet', _InletKey), *_doubles('hydraulic_diameter_m epsilon_a'), ('exact_co2_drag', _U)])
_InletQueryResult = _struct('InletQueryResult', [('abi_version', _U), ('struct_size', _S),
    ('values', _D * 12)])

_QuickInputV2 = _struct('QuickInput', [('abi_version', _U), ('struct_size', _S), ('values', _D * 13),
    *((name, _Text) for name in ('topology', 'arrangement', 'property_mode')), ('fluids', _Text * 2),
    *((name, _U) for name in ('have_height', 'have_chi', 'strict')), ('chi', _D),
    ('warm_start', _U), ('initial_shape', _S * 3), ('initial', _Array * 3)])
_QuickControls = _struct('QuickControls', [('dir_b', _U), *((name, _S) for name in ('ny', 'nz', 'max_iterations')),
    ('alpha', _D), ('q_relative_tolerance', _D), ('chunk_iterations', _S),
    ('have_q_relative_tolerance', _U), ('have_chunk_iterations', _U)])
_QuickRange = _struct('QuickRange', [('label', ct.c_char_p), ('side', _U), ('bounds', _D * 2),
    ('temperature_K', _D)])
_QuickOutput = [('floating_events', _U * 4), ('ranges', _QuickRange * 8), ('range_count', _S)]
_QuickPreparedV2 = _struct('QuickPrepared', [('abi_version', _U), ('struct_size', _S), ('owner', ct.c_void_p),
    ('shape', _S * 3), *((name, _Array * 3) for name in ('widths', 'edges', 'initial')),
    *((name, _Array) for name in ('epsilon', 'epsilon_a', 'solid_conductivity')),
    ('geometry', _GeometryCache), ('cell_length_m', _D), ('wall_thickness_m', _D),
    ('fractions', _D * 2), ('controls', _QuickControls), ('inlet_pressure', _DFPressure * 2), *_QuickOutput])
_QuickPressureV2 = _struct('QuickPressure', [('abi_version', _U), ('struct_size', _S),
    ('fractions', _D * 2), ('inlet_pressure', _DFPressure * 2), *_QuickOutput])
