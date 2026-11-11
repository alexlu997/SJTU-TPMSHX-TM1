"""Run saved 2D inputs through one native lifecycle and capture owner."""
import ctypes as ct
from types import SimpleNamespace

from sjtu_tpmshx.shared._native_result_stage import Evidence, record
from sjtu_tpmshx.shared.domain.cancellation import CancelledError
from sjtu_tpmshx.shared.domain.compute_config import validate_simple_velocity_relaxation
from sjtu_tpmshx.shared.domain.run_environment import run_environment
from sjtu_tpmshx.shared.models._native_preparation_case import _Array, _ResultV2
from sjtu_tpmshx.shared.models.envelope import ChokedFlowError
from ._full_2d_abi import _Callbacks, _Config, _EnergyControl, _EnergyEvidence, _Result
from .enthalpy import _EnergyOptions, _energy_algorithm_query, _energy_options
from .full_2d import _callbacks, configure_convergence
from .full_2d_capture import capture_result
from .model_h import _IterationOptions, _iteration_options
from .prepared_stage_2d import prepare_stage
from .run_state import NativeRun

_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double
_Size = record('SizeOption', [('present', _U), ('value', _S)])
_Double = record('DoubleOption', [('present', _U), ('value', _D)])
_RequestV1 = record('RunRequestV1', [('abi_version', _U), ('struct_size', _S),
    ('max_iter_simple', _Size), ('max_outer_ltne', _Size),
    *((key, _Double) for key in ('outer_tol_K', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K')),
    ('have_pressure_shooting', _U), ('pressure_shooting', _U), ('convergence_mode', ct.c_char_p),
    ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('explicit_energy', ct.POINTER(_EnergyControl))])
_RequestV2 = record('RunRequestV2', [('abi_version', _U), ('struct_size', _S),
    ('values', _RequestV1), ('envelope_mode', ct.c_char_p)])
_Request = record('RunRequestV3', [('abi_version', _U), ('struct_size', _S),
    ('values', _RequestV2), ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *((key, _Double) for key in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')),
    ('require_enthalpy_update_on_temperature', _U)])
_Control = record('StageControl', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _S), ('callbacks', _Callbacks)])
_Saved = record('SavedCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', ct.POINTER(_ResultV2)), ('area_density_per_m', _Array),
    ('hydraulic_diameter_m', _Array), ('fluid_conductivity', _Array * 2),
    ('inlet_recorded', _U), ('range_captured', ct.POINTER(_U))])


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', _U), ('struct_size', _S), ('owner', ct.c_void_p),
               ('raw', _Result), ('evidence', Evidence), ('resolved', _Config)]

    def __init__(self):
        super().__init__(1, ct.sizeof(type(self)))


_Application = record('CaptureApplication', [
    ('area_density_per_m', _D * 2), ('surface_htc_W_m2K', _D * 2)])
_Summary = record('CaptureSummary', [
    ('model_h_available', _U * 2), ('nu_available', _U * 2), ('pressure_available', _U),
    ('model_h_cell_count', _S * 2), ('model_h_area_m2', _D * 2),
    ('nu_floor', _D * 2), ('nu_floor_fraction', _D * 2),
    ('pressure_min_Pa', _D * 2), ('pressure_max_Pa', _D * 2),
    ('q_net', _D), ('absolute_duty', _D * 2), ('application_hv', _D * 2),
    ('pressure_clip_hits', _S), ('have_finite_duty', _U), ('red_black', _U * 2)])


def _request(cfg):
    solver = cfg['compute_cfg'].solver
    request = _Request(3, ct.sizeof(_Request),
        _RequestV2(2, ct.sizeof(_RequestV2), _RequestV1(1, ct.sizeof(_RequestV1))))
    values = request.values.values
    for name in ('max_iter_simple', 'max_outer_ltne'):
        value = getattr(solver, name)
        setattr(values, name, _Size(bool(value), value or 0))
    value = solver.outer_tol_K
    values.outer_tol_K = _Double(bool(value), value or 0.)
    settings = SimpleNamespace()
    configure_convergence(settings, cfg, solver)
    values.convergence_mode = settings.convergence_mode.encode()
    for name in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        setattr(values, name, _Double(1, getattr(settings, name)))
    validate_simple_velocity_relaxation(solver.simple_velocity_relaxation)
    if solver.simple_velocity_relaxation is not None:
        values.simple_velocity_relaxation = _Double(1, solver.simple_velocity_relaxation)
    if cfg.get('T_s_init') is not None:
        values.solid_seed_K = _Double(1, cfg['T_s_init'])
    values.have_pressure_shooting = 1
    values.pressure_shooting = cfg.get('p_in_shooting', run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') == '1')
    request.values.envelope_mode = cfg.get('envelope_mode', 'raise').encode()
    energy = _energy_options(solver.enthalpy_algorithm, solver.enthalpy_temperature_tol_K)
    model_h = _iteration_options(vars(solver))
    if model_h is not None:
        values.model_h = model_h
    else:
        values.energy = ct.pointer(energy)
    for name, target, kind in (
            ('ltne_enthalpy_outer', 'energy_iterations', _Size),
            ('ltne_enthalpy_nsweep', 'energy_sweeps', _Size),
            ('ltne_enthalpy_omega', 'energy_omega', _Double),
            ('ltne_enthalpy_tol', 'energy_update_tolerance', _Double),
            ('ltne_enthalpy_coupled_energy_tol', 'energy_coupled_tolerance', _Double),
            ('ltne_enthalpy_equation_energy_tol', 'energy_equation_tolerance', _Double)):
        value = getattr(solver, name)
        if value is not None:
            setattr(request, target, kind(1, value))
    request.require_enthalpy_update_on_temperature = solver.require_enthalpy_update_on_temperature
    return request, energy


class _Run(NativeRun):
    api_prefix = 'tpmshx_stage_run_2d'
    advance_name = 'advance_step'
    entry_names = {'create': 'create_saved', 'restore': 'restore_saved', 'release': 'release_run'}
    creation_version = 1
    result_type = _StageResult
    error_types = {**NativeRun.error_types, 4: ChokedFlowError, 6: CancelledError}

    def __init__(self, library, saved, request, control, errors, state):
        self.errors = errors
        common = [ct.POINTER(_Saved), ct.POINTER(_Request), ct.POINTER(_Control)]
        super().__init__(library, common, [ct.byref(saved), ct.byref(request), ct.byref(control)], control, state)

    def _call(self, function, *args):
        error = ct.create_string_buffer(2048)
        code = function(*args, error, len(error))
        if self.errors:
            raise self.errors[0]
        if code:
            raise self.error_types.get(code, RuntimeError)(error.value.decode())


def _scalars(summary):
    return dict(
        model_h=[dict(cell_count=summary.model_h_cell_count[i], area_m2=summary.model_h_area_m2[i])
                 if summary.model_h_available[i] else None for i in range(2)],
        nu=[dict(floor=summary.nu_floor[i], floor_fraction=summary.nu_floor_fraction[i])
            if summary.nu_available[i] else None for i in range(2)],
        pressure_ranges=([(summary.pressure_min_Pa[i], summary.pressure_max_Pa[i]) for i in range(2)]
                         if summary.pressure_available else None),
        q_net=summary.q_net, absolute_duty=list(summary.absolute_duty),
        pressure_clip_hits=summary.pressure_clip_hits, have_finite_duty=bool(summary.have_finite_duty),
        red_black=[bool(value) for value in summary.red_black])


def run_stage(driver, case, cfg, prepared, control, *, resume_state=None, checkpoint=None, checkpoint_due=None):
    """Keep preparation and result storage alive through late application capture."""
    library = driver.library
    try:
        release = library.tpmshx_stage_run_2d_release_v1
        query = library.tpmshx_stage_run_2d_get_capture_v1
        release.argtypes, release.restype = [ct.POINTER(_StageResult)], None
        query.argtypes = [ct.POINTER(_StageResult), ct.POINTER(_Application), ct.POINTER(_Summary)]
        query.restype = ct.c_int
    except AttributeError as error:
        raise ValueError('native library has an incomplete saved 2D stage protocol') from error
    control.check_cancelled()
    uniform, area, diameter, conductivity, recorded, captured, keepalive = prepare_stage(case, cfg, prepared)
    saved = _Saved(1, ct.sizeof(_Saved), ct.pointer(uniform), area, diameter,
                   (_Array * 2)(*conductivity), recorded, captured)
    request, energy = _request(cfg)
    callbacks, errors = _callbacks(control)
    stage_control = _Control(case.case_id.encode(), driver.table_directory, control.native_cpu_threads(), callbacks)
    energy_query = version_query = None
    if energy.algorithm:
        energy_query = library.tpmshx_full_2d_get_energy_evidence_v1
        energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
        energy_query.restype = ct.c_int
        version_query = _energy_algorithm_query(library)
    result = _StageResult()
    try:
        with _Run(library, saved, request, stage_control, errors, resume_state) as run:
            while run.phase not in (3, 4):
                phase = run.advance()
                if (checkpoint is not None and phase in (1, 2, 6, 7, 8)
                        and (checkpoint_due is None or checkpoint_due())):
                    checkpoint(run.snapshot())
            result = run.take_result()
        summary = _Summary()
        if query(ct.byref(result), ct.byref(_Application()), ct.byref(summary)):
            raise RuntimeError('native full 2D capture query failed')
        native = driver.copy_result(result.raw, (uniform.values.nx, uniform.values.ny), result.resolved,
            entry_version=6, control=control, have_cpu_limit=True, energy_query=energy_query,
            version_query=version_query, resume_state=resume_state, capture_scalars=_scalars(summary))
        control.check_cancelled()

        def application_hv(area_density, surface_htc):
            if area_density < 0 or surface_htc < 0:
                raise ValueError(f'A_0={area_density}, H_sf={surface_htc} must both be >= 0')
            application = _Application((_D * 2)(float(area_density), 0.), (_D * 2)(float(surface_htc), 0.))
            values = _Summary()
            if query(ct.byref(result), ct.byref(application), ct.byref(values)):
                raise RuntimeError('native full 2D application capture query failed')
            return values.application_hv[0]

        return capture_result(case, cfg, prepared, native, application_hv=application_hv)
    finally:
        if result.owner:
            release(ct.byref(result))
        del keepalive
