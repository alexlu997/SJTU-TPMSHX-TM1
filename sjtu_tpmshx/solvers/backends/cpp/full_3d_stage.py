"""Bind validated saved 3D inputs to the native run and capture lifecycle."""
import ctypes as ct

from sjtu_tpmshx.shared._native_result_stage import Evidence, Input as Evaluation, record
from sjtu_tpmshx.shared.models._native_preparation_case import _Array as PreparedArray, _Evidence, _Text
from ._full_3d_abi import _Array, _Callbacks, _Control, _Input, _Result
from .enthalpy import _EnergyOptions
from .model_h import _IterationOptions
from .prepared_stage_2d import _array, _ranges, _text
from .run_state import NativeRun

_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Size = record('SizeOption3D', [('present', _U), ('value', _Z)])
_Double = record('DoubleOption3D', [('present', _U), ('value', _D)])
_Uint = record('UintOption3D', [('present', _U), ('value', _U)])
_Request = record('StageRequest3D', [('abi_version', _U), ('struct_size', _Z),
    *((name, _Size) for name in ('max_iter_simple', 'max_outer_ltne', 'thermal_iterations',
        'coarse_iterations', 'parallel_threshold')),
    *((name, _Double) for name in ('outer_tol_K', 'thermal_relaxation', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K', 'roughness_height_m')),
    *((name, _Uint) for name in ('pressure_shooting', 'variable_rho_cp', 'conservative',
        'strict_mass_balance', 'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a',
        'coarse_bootstrap', 'adaptive_pressure_tolerance', 'track_momentum', 'roughness_mode', 'envelope_mode')),
    ('convergence_mode', ct.c_char_p), ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *((name, _Double) for name in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')),
    ('require_enthalpy_update_on_temperature', _U)])
_Host = record('StageControl3D', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _Z), ('callbacks', _Callbacks)])
_Saved = record('StageSaved3D', [('abi_version', _U), ('struct_size', _Z), ('input', ct.POINTER(_Input)),
    *((name, _D) for name in ('nominal_cell_length_mm', 'nominal_wall_thickness_mm', 'nominal_porosity')),
    ('wall_thickness_m', PreparedArray), ('preparation', _Evidence),
    ('notices', ct.POINTER(_Text)), ('notice_count', _Z), ('inlet_recorded', _U),
    ('range_captured', ct.POINTER(_U))])
_Summary = record('StageCapture3D', [('nu_available', _U * 2), ('model_h_cell_count', _Z),
    ('nu_floor', _D * 2), ('nu_floor_fraction', _D * 2), ('q_net', _D),
    ('pressure_clip_hits', _Z), ('audit_outlet', _Array * 2)])


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', _U), ('struct_size', _Z), ('owner', ct.c_void_p),
        ('raw', _Result), ('evidence', Evidence), ('resolved', _Control), ('evaluation', Evaluation)]

    def __init__(self):
        super().__init__(1, ct.sizeof(type(self)))


def has_saved_stage(library):
    """Select the protocol before execution; partial protocols are errors."""
    version = getattr(library, 'tpmshx_stage_capture_3d_abi_version', None)
    capture = getattr(library, 'tpmshx_stage_run_3d_get_capture_v1', None)
    if version is None and capture is None:
        return False
    names = ('create_saved', 'restore_saved', 'advance_step', 'phase', 'snapshot',
             'take_result', 'release_run', 'release')
    if version is None or capture is None or not all(
            hasattr(library, 'tpmshx_stage_run_3d_' + name + '_v1') for name in names):
        raise ValueError('native library has an incomplete saved 3D stage protocol')
    version.argtypes, version.restype = [], _U
    abi = version()
    if abi != 1:
        raise ValueError(f'unsupported saved 3D capture ABI {abi}; expected 1')
    return True


def _request(cfg, controls, energy, model_h):
    request = _Request(1, ct.sizeof(_Request))
    if cfg.get('max_iter_simple') is not None:
        request.max_iter_simple = _Size(1, controls.initial_simple_iterations)
    for target, source in (('max_outer_ltne', 'max_outer'), ('thermal_iterations', 'thermal_iterations'),
                           ('coarse_iterations', 'coarse_iterations')):
        setattr(request, target, _Size(1, getattr(controls, source)))
    request.parallel_threshold = _Size(1, 1 if controls.simple.ordering else ct.c_size_t(-1).value)
    for target, source in (('outer_tol_K', 'outer_temperature_tolerance'), ('thermal_relaxation', 'thermal_relaxation'),
                           ('roughness_height_m', 'roughness_height')):
        setattr(request, target, _Double(1, getattr(controls, source)))
    request.simple_velocity_relaxation = _Double(1, controls.simple.alpha_velocity)
    for target, source in (('mom_tol', 'momentum_tolerance'), ('mass_local_tol', 'local_mass_tolerance'), ('mass_global_tol', 'global_mass_tolerance')):
        setattr(request, target, _Double(1, getattr(controls.simple.convergence, source)))
    if controls.has_initial_solid_temperature:
        request.solid_seed_K = _Double(1, controls.initial_solid_temperature)
    for name in ('pressure_shooting', 'variable_rho_cp', 'conservative', 'strict_mass_balance',
                 'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a', 'coarse_bootstrap',
                 'roughness_mode', 'envelope_mode'):
        setattr(request, name, _Uint(1, getattr(controls, name)))
    request.adaptive_pressure_tolerance = _Uint(1, controls.simple.adaptive_pressure_tolerance)
    request.track_momentum = _Uint(1, controls.simple.track_momentum)
    request.convergence_mode = b'f2'
    if model_h is not None:
        request.model_h = model_h
    selected = _EnergyOptions(energy.algorithm, energy.temperature_update_tolerance)
    request.energy = ct.pointer(selected)
    for target, source in (('energy_iterations', 'ltne_enthalpy_outer'), ('energy_sweeps', 'ltne_enthalpy_nsweep')):
        if cfg.get(source) is not None:
            setattr(request, target, _Size(1, cfg[source]))
    for target, source in (('energy_omega', 'ltne_enthalpy_omega'), ('energy_update_tolerance', 'ltne_enthalpy_tol'),
                           ('energy_coupled_tolerance', 'ltne_enthalpy_coupled_energy_tol'),
                           ('energy_equation_tolerance', 'ltne_enthalpy_equation_energy_tol')):
        if cfg.get(source) is not None:
            setattr(request, target, _Double(1, cfg[source]))
    request.require_enthalpy_update_on_temperature = cfg.get('require_enthalpy_update_on_temperature', False)
    return request


class SavedRun(NativeRun):
    api_prefix = 'tpmshx_stage_run_3d'
    creation_version = 1
    advance_name = 'advance_step'
    entry_names = {'create': 'create_saved', 'restore': 'restore_saved', 'release': 'release_run'}
    result_type = _StageResult
    result_release_name = 'tpmshx_stage_run_3d_release_v1'

    def __init__(self, library, case, cfg, prepared, data, controls, energy, model_h, callbacks, errors, control, state):
        self.errors, self.keepalive = errors, []
        ranges, captured = _ranges(case.metadata.get('applicability_inputs', ()), self.keepalive)
        notices = (_Text * len(case.metadata['notices']))(*(
            _text(notice, self.keepalive) for notice in case.metadata['notices']))
        evidence = _Evidence(ranges=ranges, range_count=len(ranges))
        saved = _Saved(1, ct.sizeof(_Saved), ct.pointer(data), cfg['Lcell'], cfg['t_wall'], cfg['eps'],
            _array(prepared['design']['t_field_m'], self.keepalive), evidence, notices, len(notices),
            'applicability_inputs' in case.metadata, captured)
        request = _request(cfg, controls, energy, model_h)
        host = _Host(case.case_id.encode(), controls.table_directory, control.native_cpu_threads(), callbacks)
        self.keepalive.extend((saved, request, host, notices))
        super().__init__(library, [ct.POINTER(_Saved), ct.POINTER(_Request), ct.POINTER(_Host)],
            [ct.byref(saved), ct.byref(request), ct.byref(host)], callbacks, state)

    def _call(self, function, *args):
        error = ct.create_string_buffer(2048)
        code = function(*args, error, len(error))
        if self.errors:
            raise self.errors[0]
        if code:
            raise self.error_types.get(code, RuntimeError)(error.value.decode())


def copy_summary(library, result, *, emit_audit):
    from .full_3d import _copy
    query = library.tpmshx_stage_run_3d_get_capture_v1
    query.argtypes, query.restype = [ct.POINTER(_StageResult), _U, ct.POINTER(_Summary)], ct.c_int
    summary = _Summary()
    if query(ct.byref(result), emit_audit, ct.byref(summary)):
        raise RuntimeError('native full 3D capture query failed')
    return dict(model_h_cell_count=summary.model_h_cell_count, q_net=summary.q_net,
        pressure_clip_hits=summary.pressure_clip_hits,
        nu=[dict(floor=summary.nu_floor[i], floor_fraction=summary.nu_floor_fraction[i])
            if summary.nu_available[i] else None for i in range(2)],
        audit_outlet=[_copy(value, (result.raw.flow[i].widths[0].size, result.raw.flow[i].widths[2].size))
                      for i, value in enumerate(summary.audit_outlet)])


def release_result(library, result):
    release = library.tpmshx_stage_run_3d_release_v1
    release.argtypes, release.restype = [ct.POINTER(_StageResult)], None
    release(ct.byref(result))
