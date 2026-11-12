"""Transport owned 3D preparation data through the native C interface."""
from contextlib import contextmanager
import ctypes as ct
from functools import lru_cache

from . import _native_grid as grid
from . import _native_preparation
from . import _native_preparation_case as native


_U, _S, _D = native._U, native._S, native._D
_struct, _doubles = native._structure, native._doubles
_Inlet = _struct('Inlet3D', [('fluid', _U), *_doubles('velocity_m_s temperature_K pressure_Pa'),
    ('port', grid._Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])
_Input = _struct('Input3D', [('abi_version', _U), ('struct_size', _S),
    ('lengths_m', grid._Scalar * 3), ('counts', _S * 3), ('max_cells', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *_doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('geometry_mode', _U), ('df_mode', _U),
    ('kinds', native._Kinds), ('sco2_nu', native._Nu)])
_Side = _struct('Side3D', [('axes', ct.c_int32 * 7),
    ('inlet_opening', native._Array), ('outlet_opening', native._Array),
    *_doubles('rho mu cp k_f'), ('have_drag_application', _U),
    ('drag_evidence', native._DragEvidence), ('drag_selection', native._Drag)])
_Result = _struct('Result3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('options', native._Options), ('widths', native._Array * 3),
    ('edges', native._Array * 3), ('geometry', native._GeometryCache),
    ('uniform_solid_conductivity', _D),
    *((name, native._Array) for name in ('cell_length', 'wall_thickness', 'total_porosity',
        'side_porosity', 'permeability', 'forchheimer', 'solid_conductivity')),
    ('length_kinds', native._Kind * 2), ('sides', _Side * 2), ('models', native._Model * 4),
    ('evidence', native._Evidence), ('sco2_nu_model_version', native._Text),
    ('sco2_nu_interpretation', native._Text), ('sco2_nu_coefficients', (_D * 3) * 2),
    ('co2', native._Co2), ('notices', ct.POINTER(native._Text)), ('notice_count', _S),
    ('owner', ct.c_void_p)])
_FlowInput = _struct('FlowInput3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('target_kinds', native._Kind * 2),
    ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)])
_Flow = _struct('Flow3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input), ('have_capacities', _U),
    ('capacities', grid._Scalar * 2), ('speeds', grid._Scalar * 2),
    ('evidence', native._Evidence), ('owner', ct.c_void_p)])
_Controls = _struct('ContinuousControls3D', [('n_ctrl_x', _S), ('n_ctrl_y', _S), ('n_ctrl_z', _S),
    ('have_ctrl_z', _U), ('spline_order', _U), ('symmetric_y', _U),
    ('L_bounds_mm', _D * 2), ('t_bounds_mm', _D * 2), ('decision_mm', native._Array)])
_ContinuousInput = _struct('ContinuousInput3D', [('abi_version', _U), ('struct_size', _S),
    ('values', _FlowInput), ('controls', _Controls)])
_ContinuousFlow = _struct('ContinuousFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('controls', _Controls), ('owner', ct.c_void_p)])
_ContinuousCase = _struct('ContinuousCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('controls', _Controls),
    ('area_density_per_m', native._Array), ('hydraulic_diameter_m', native._Array),
    ('thermal_porosity', native._Array), ('drag', native._ContinuousDrag * 2), ('owner', ct.c_void_p)])
_Cell = _struct('GridCell3D', [('bounds', grid._Scalar * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D)])
_SpatialInput = _struct('SpatialInput3D', [('abi_version', _U), ('struct_size', _S),
    ('values', _FlowInput), ('cells', ct.POINTER(_Cell)), ('cell_count', _S)])
_SpatialFlow = _struct('SpatialFlow3D', [('abi_version', _U), ('struct_size', _S),
    ('flow', _Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S), ('owner', ct.c_void_p)])
_SpatialCase = _struct('SpatialCase3D', [('abi_version', _U), ('struct_size', _S),
    ('prepared', _Result), ('flow', _Flow), ('cells', ct.POINTER(_Cell)), ('cell_count', _S),
    ('side_b_porosity', native._Array), ('area_density_per_m', native._Array),
    ('hydraulic_diameter_m', native._Array), ('thermal_porosity', native._Array),
    ('split_a', _D), ('have_side_geometry', _U), ('side_geometry', (_D * 4) * 2),
    ('owner', ct.c_void_p)])


class _Bindings:
    def __init__(self, path):
        self.owner = _native_preparation._load_library(path)
        version = self.owner.bind('tpmshx_preparation_host_3d_abi_version_v5', [], _U)()
        if version != 5:
            raise ValueError(f'unsupported native 3D preparation host ABI {version}; expected 5')
        self.operations, self.releases = {}, {}
        for version, source, flow, full, prefix in (
                (3, _ContinuousInput, _ContinuousFlow, _ContinuousCase, 'continuous'),
                (4, _SpatialInput, _SpatialFlow, _SpatialCase, 'spatial')):
            for name in ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case'):
                result = full if name == 'prepare_flow_case' else flow
                self.operations[version, name] = self.owner.bind(f'tpmshx_{name}_3d_v{version}',
                    [ct.POINTER(source), ct.POINTER(native._Options), ct.POINTER(native._Callbacks),
                     ct.POINTER(result), ct.POINTER(native._Failure), ct.POINTER(ct.c_char), _S])
            for result, suffix in ((flow, 'flow'), (full, 'case')):
                self.releases[result] = self.owner.bind(
                    f'tpmshx_preparation_{prefix}_{suffix}_3d_release_v{version}', [ct.POINTER(result)], None)


@lru_cache(maxsize=1)
def _bindings(path):
    return _Bindings(path)


@contextmanager
def operation(name, source, options, validate_host_input, cache):
    """Keep the native owner alive through immutable CaseData construction."""
    version = source.abi_version
    result_type = ((_ContinuousCase if name == 'prepare_flow_case' else _ContinuousFlow)
                   if version == 3 else (_SpatialCase if name == 'prepare_flow_case' else _SpatialFlow))
    result = result_type(version, ct.sizeof(result_type))
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    bindings = _bindings(_native_preparation._library().path)
    callbacks, descriptor, callback_errors = native._callback_bridge(validate_host_input,
        observe_range=cache.observe_range, observe_notice=cache.observe_notice,
        geometry_cache_at=cache.geometry_at, inlet_cache_at=cache.inlet_at)
    try:
        status = bindings.operations[version, name](ct.byref(source), ct.byref(options), ct.byref(descriptor),
            ct.byref(result), ct.byref(failure), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        native._check_status(status, error, failure)
        yield result
    finally:
        bindings.releases[result_type](ct.byref(result))
