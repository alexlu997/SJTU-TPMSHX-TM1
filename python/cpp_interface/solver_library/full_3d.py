"""Typed prepared-data binding to the full native 3D numerical driver.

Python validates the persisted schema, resolves recorded controls, and detaches
owned output views. SIMPLE, EOS, closure refresh, energy, outer coupling and
physical convergence verdicts are produced by the C++ call.
"""
import ctypes as ct
from math import prod

import numpy as np

from sjtu_tpmshx.data_types.compute_config import reject_retired_research_options
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.physical_models.fluid_props import WaterStateError

from .. import full_3d_stage as stage
from ..full_3d_stage import _copy, _detach
from ._full_3d_abi import _Callbacks, _Control, _EnergyEvidence, _Input, _Result
from ._simple_abi import _F2
from ._stage_capture_abi import copy_sampling, executed_inputs, execution_view_query, sampling_query, sampling_records, stage_records
from .closure_evidence import copy_range_observations, replay_range_observations, last_range_query, copy_last_ranges
from .enthalpy import (_EnergyOptions, _EnergyOptionsV2, _energy_algorithm_query,
                       _FullEnergyEffectiveSettings, _full_enthalpy_defaults, _update_scale_query, _copy_update_scale)
from .model_h import (_IterationOptions, _iteration_query, _copy_iteration_records,
                      _acceleration_query, _model_h_algorithm)
from .physical_ledger import HeatLedger, heat_ledger_query, copy_heat_ledger
from .simple_3d import _Config as _SimpleConfig
from .temperature import _temperature_algorithm
from .temperature_evidence import TemperatureEvidence, copy_temperature_evidence


class NativeFull3DDriver:
    def __init__(self, library, *, table_directory=None):
        self._bind(stage.open_library(library, table_directory))

    def _bind(self, runtime):
        self.path, self.library, self.abi, self.table_directory = runtime
        self.call = self.library.tpmshx_solve_full_3d_v1
        self.call.argtypes = [ct.POINTER(_Input), ct.POINTER(_Control), ct.POINTER(_Callbacks),
                             ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int
        self.release = self.library.tpmshx_full_3d_release_v1
        self.release.argtypes, self.release.restype = [ct.POINTER(_Result)], None
        try:
            self.query_settings = self.library.tpmshx_full_3d_get_energy_effective_settings_v1
        except AttributeError as exc:
            raise ValueError('native full 3D library lacks executed settings; rebuild the library') from exc
        self.query_settings.argtypes = [ct.POINTER(_Result), ct.POINTER(_FullEnergyEffectiveSettings)]
        self.query_settings.restype = ct.c_int
        self.query_update_scale = _update_scale_query(self.library, 3, _Result)
        self.query_model_h = _iteration_query(self.library, 3, _Result)
        self.query_model_h_acceleration = _acceleration_query(self.library, _Result)
        self.query_bootstrap = stage.bootstrap_query(self.library)

    def run_prepared(self, cfg, p, control=RunControl(), *, resume_state=None, checkpoint=None, checkpoint_due=None):
        return self._run_prepared(cfg, p, control, resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)

    def _run_prepared(self, cfg, p, control=RunControl(), *, application_only=False,
                      resume_state=None, checkpoint=None, checkpoint_due=None, stage_case=None):
        control.check_cancelled()
        reject_retired_research_options(cfg)
        energy = stage.energy_request(cfg)
        defaults = _full_enthalpy_defaults(self.library, 3, energy.algorithm,
            'water' in (cfg['fluid_type_A'], cfg['fluid_type_B']))
        require_h, strict_options = stage.validate_energy_controls(cfg)
        thread_call = getattr(self.library, 'tpmshx_solve_full_3d_v5', None)
        if thread_call is None and control.cpu_threads is not None:
            raise ValueError('this retained native library has no CPU thread limit; leave cpu_threads unset')
        energy_call = energy_query = version_query = None
        entry_version = 1
        model_h_options = stage.model_h_request(cfg, strict_options)
        if model_h_options is not None:
            if thread_call is None:
                try:
                    energy_call = self.library.tpmshx_solve_full_3d_v4
                except AttributeError as exc:
                    raise ValueError('native full 3D library lacks model-h controls v4; rebuild the library') from exc
                energy_call.argtypes = [*self.call.argtypes[:2], ct.POINTER(_IterationOptions), *self.call.argtypes[2:]]
                energy_call.restype = ct.c_int
            entry_version = 4
        elif strict_options:
            energy = _EnergyOptionsV2(energy.algorithm, energy.temperature_update_tolerance,
                defaults.coupled_energy_tolerance if cfg.get('ltne_enthalpy_coupled_energy_tol') is None else cfg['ltne_enthalpy_coupled_energy_tol'],
                defaults.equation_energy_tolerance if cfg.get('ltne_enthalpy_equation_energy_tol') is None else cfg['ltne_enthalpy_equation_energy_tol'],
                require_h)
            if thread_call is None:
                try:
                    energy_call = self.library.tpmshx_solve_full_3d_v3
                except AttributeError as exc:
                    raise ValueError('native full 3D library lacks explicit energy controls v3') from exc
                energy_call.argtypes = [*self.call.argtypes[:2], ct.POINTER(_EnergyOptionsV2), *self.call.argtypes[2:]]
                energy_call.restype = ct.c_int
            entry_version = 3
        elif energy.algorithm:
            if thread_call is None:
                try:
                    energy_call = self.library.tpmshx_solve_full_3d_v2
                except AttributeError as exc:
                    raise ValueError('native full 3D library lacks conservative energy v2') from exc
                energy_call.argtypes = [*self.call.argtypes[:2], ct.POINTER(_EnergyOptions), *self.call.argtypes[2:]]
                energy_call.restype = ct.c_int
            entry_version = 2
        if thread_call is not None:
            entry_version = 5
            thread_call.argtypes = [*self.call.argtypes[:2], ct.POINTER(_EnergyOptions),
                ct.POINTER(_EnergyOptionsV2), ct.POINTER(_IterationOptions), ct.c_size_t, *self.call.argtypes[2:]]
            thread_call.restype = ct.c_int
        if energy.algorithm:
            version_query = _energy_algorithm_query(self.library)
            try:
                energy_query = self.library.tpmshx_full_3d_get_energy_evidence_v1
            except AttributeError as exc:
                raise ValueError(f'native full 3D library lacks conservative energy v{entry_version} evidence') from exc
            energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
            energy_query.restype = ct.c_int
        stage.validate_flow_options(cfg)
        shape = tuple(p['N'+a] for a in 'xyz')
        keepalive = []
        saved_v2 = stage_case is not None and hasattr(self.library, 'tpmshx_stage_run_3d_create_saved_v2')
        data = stage.pack_input(cfg, p, p, p['design'], shape, cfg['Lcell'], cfg['sco2_nu'],
                                keepalive, saved_v2=saved_v2)
        request = stage._request(cfg, p, shape, energy, model_h_options)
        c = _Control()
        c.max_outer = request.max_outer_ltne.value
        c.initial_simple_iterations = request.max_iter_simple.value if request.max_iter_simple.present else 2000
        c.warm_simple_iterations = request.max_iter_simple.value if request.max_iter_simple.present else 600
        c.thermal_iterations = request.thermal_iterations.value
        c.outer_temperature_tolerance = request.outer_tol_K.value
        c.thermal_relaxation = request.thermal_relaxation.value
        for name in ('pressure_shooting', 'variable_rho_cp', 'conservative', 'strict_mass_balance',
                     'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a',
                     'coarse_bootstrap', 'coarse_iterations', 'roughness_mode', 'envelope_mode'):
            setattr(c, name, getattr(request, name).value)
        c.red_black_energy = int(prod(shape)>30000 and not (energy.algorithm and data.solve_b
            and any(side.fluid in (2, 3) for side in data.sides)))
        c.has_initial_solid_temperature = request.solid_seed_K.present
        c.roughness_height, c.initial_solid_temperature = request.roughness_height_m.value, request.solid_seed_K.value
        c.simple = _SimpleConfig(2000, 1, 100, request.simple_velocity_relaxation.value, .2, .3, 0., 287.05, .05, 1, 1, 0,
            request.adaptive_pressure_tolerance.value, request.track_momentum.value,
            int(request.parallel_threshold.value == 1),
            _F2(request.mom_tol.value, request.mass_local_tol.value, request.mass_global_tol.value,
                .01, 1e-4, 1e-3, 2, 5, 60))
        for target, source, default in (
                ('enthalpy_iterations', 'energy_iterations', defaults.max_iterations),
                ('enthalpy_sweeps', 'energy_sweeps', defaults.sweeps),
                ('enthalpy_omega', 'energy_omega', defaults.omega),
                ('enthalpy_update_tolerance', 'energy_update_tolerance', defaults.update_tolerance)):
            option = getattr(request, source)
            setattr(c, target, option.value if option.present else default)
        c.table_directory = self.table_directory
        callbacks, callback_errors = stage.make_callbacks(control)
        result, error = _Result(), ct.create_string_buffer(2048)
        stage_result = capture_scalars = None
        cpu_thread_limit = control.native_cpu_threads() if stage_case is not None or thread_call else None
        try:
            if stage_case is not None:
                host = stage._Host(stage_case.case_id.encode(), self.table_directory, cpu_thread_limit, callbacks)
                with stage.SavedRun(self.library, stage_case, data, cfg['Lcell'], cfg['t_wall'], cfg['sco2_nu'],
                                    request, host, callback_errors, keepalive, resume_state, version=2 if saved_v2 else 1) as run:
                    run.finish(checkpoint, checkpoint_due, (1, 2, 6, 7, 8, 9, 10))
                    stage_result = run.take_result()
                result = stage_result.raw
                c = stage_result.resolved
                code = 0
            elif resume_state is not None or checkpoint is not None:
                from sjtu_tpmshx.cpp_interface.solver_library.full_3d_run import NativeFull3DRun
                true_h = data.solve_b and any(side.fluid in (2, 3) for side in data.sides)
                options = energy if strict_options else (_EnergyOptionsV2(
                    energy.algorithm, energy.temperature_update_tolerance,
                    defaults.coupled_energy_tolerance, defaults.equation_energy_tolerance, require_h)
                    if true_h else None)
                with NativeFull3DRun(self.library, data, c, options, callbacks,
                                     model_h=model_h_options, state=resume_state,
                                     cpu_threads=cpu_thread_limit) as run:
                    while run.phase not in (3, 4):
                        phase = run.advance()
                        if callback_errors:
                            raise callback_errors[0]
                        if (checkpoint is not None and phase in (1, 2, 6, 7, 8, 9, 10)
                                and (checkpoint_due is None or checkpoint_due())):
                            checkpoint(run.snapshot())
                    result = run.take_result()
                code = 0
            elif thread_call:
                code = thread_call(ct.byref(data), ct.byref(c),
                    ct.byref(energy) if not strict_options and model_h_options is None else None,
                    ct.byref(energy) if strict_options else None,
                    ct.byref(model_h_options) if model_h_options is not None else None,
                    cpu_thread_limit, ct.byref(callbacks), ct.byref(result), error, len(error))
            elif energy_call:
                options = model_h_options if model_h_options is not None else energy
                code = energy_call(ct.byref(data), ct.byref(c), ct.byref(options), ct.byref(callbacks), ct.byref(result), error, len(error))
            else:
                code = self.call(ct.byref(data), ct.byref(c), ct.byref(callbacks), ct.byref(result), error, len(error))
            if callback_errors:
                raise callback_errors[0]
            if code:
                raise {1:ValueError, 2:WaterStateError, 3:FloatingPointError}.get(code,RuntimeError)(error.value.decode())
            bootstrap_traces = stage.bootstrap_traces(self.query_bootstrap, result)
            stage.require_completed(result, bootstrap_traces)
            if stage_result is not None:
                capture_scalars = stage.copy_summary(self.library, stage_result,
                    emit_audit=bool(cfg.get('_emit_audit', False)), copy_array=_copy)
            actual = _FullEnergyEffectiveSettings()
            if self.query_settings(ct.byref(result), ct.byref(actual)):
                raise RuntimeError('native full 3D effective settings query failed')
            if actual.outer_count != result.outer_count:
                raise RuntimeError('native full 3D effective settings do not match the thermal history')
            records = stage_fields = None
            if stage_result is not None and application_only:
                from sjtu_tpmshx.cpp_interface._native_result_stage import detach_stage_fields
                records = stage_records(self.library, stage_result)
                if hasattr(self.library, 'tpmshx_stage_run_3d_create_saved_v2'):
                    cfg['_input_resolution'] = executed_inputs(stage_case, stage_result.evidence)
                # The public solid conductivity retains the precision of the saved design.
                stage_fields = detach_stage_fields(stage_result.evidence, shape,
                    prepared_fields={'K_ss': np.asarray(p['design']['K_ss'])})
            detached=_detach(result, shape, c, actual, entry_version,
                             emit_audit=bool(cfg.get('_emit_audit',False)), application_only=application_only,
                             capture_scalars=capture_scalars, stage_fields=stage_fields, records=records)
            if actual.last.available and energy_query:
                extra = _EnergyEvidence()
                if energy_query(ct.byref(result), ct.byref(extra)):
                    raise RuntimeError('native full 3D energy evidence query failed')
                stage.add_energy_evidence(detached, extra, actual, entry_version, shape, version_query=version_query)
            if records is None:
                detached['property_sampling'] = copy_sampling(sampling_query(self.library, 3, _Result), result)
            else:
                detached['property_sampling'] = sampling_records(records.sampling)
            detached['enthalpy_update_normalization'] = _copy_update_scale(self.query_update_scale, result)
            detached['model_h_iterations'] = _copy_iteration_records(
                self.query_model_h, result, self.query_model_h_acceleration)
            stage.add_run_evidence(detached, c, entry_version, control, cpu_thread_limit, resume_state)
            if detached['mode'] in ('model_h', 'temperature'):
                if detached['mode'] == 'model_h':
                    algorithm = _model_h_algorithm(self.library, 3)
                    red_black = bool(c.red_black_energy)
                else:
                    scheme = 0 if shape[2] == 1 else (2 if c.conservative or not c.force_cell_centered else 1)
                    red_black = bool(c.red_black_energy and scheme == 2)
                    if scheme == 2:
                        algorithm = _temperature_algorithm(self.library, scheme)
                if detached['mode'] == 'model_h' or scheme != 2:
                    if records is not None:
                        identity = records.temperature[0]
                        if detached['mode'] == 'model_h':
                            if identity:
                                algorithm = identity.contents.algorithm.decode('ascii')
                        else:
                            from .._native_result_stage import stage_ledger
                            detached['temperature_evidence'] = stage_ledger(stage_result.evidence.thermal, identity, shape)
                            algorithm = detached['temperature_evidence']['algorithm']
                    else:
                        query = self.library.tpmshx_full_3d_get_model_enthalpy_evidence_v1
                        query.argtypes = [ct.POINTER(_Result), ct.POINTER(TemperatureEvidence)]
                        query.restype = ct.c_int
                        extra = TemperatureEvidence()
                        if query(ct.byref(result), ct.byref(extra)):
                            raise RuntimeError('native full 3D temperature evidence query failed')
                        if detached['mode'] == 'model_h':
                            if extra.available or extra.algorithm:
                                if extra.available != 1 or extra.physical_dimension != 3 or not extra.algorithm:
                                    raise RuntimeError('native strict model-h identity or ledger is invalid')
                                algorithm = extra.algorithm.decode('ascii')
                        else:
                            detached['temperature_evidence'] = copy_temperature_evidence(extra, shape, 3)
                            algorithm = detached['temperature_evidence']['algorithm']
                detached['native_metadata'] = dict(abi=self.abi, algorithm=algorithm, red_black=red_black)
            if records is None:
                detached['last_closure_ranges'] = copy_last_ranges(last_range_query(self.library, 3, _Result), result)
            if stage_result is not None and application_only:
                warnings = stage.add_saved_evidence(detached, stage_case, stage_result.evidence, records, stage_fields, shape)
            if records is None and 'temperature_evidence' not in detached:
                ledger = HeatLedger()
                if heat_ledger_query(self.library, 3, _Result)(ct.byref(result), ct.byref(ledger)):
                    raise RuntimeError('native full 3D heat ledger query failed')
                detached['physical_ledger'] = copy_heat_ledger(ledger, shape, 3)
            if capture_scalars is None:
                from sjtu_tpmshx.physical_models.co2_correlations import NU_MULTIPLIER
                for label in 'AB':
                    if cfg['fluid_type_'+label] == 'co2' and detached['nu_observations'][label]:
                        detached['nu_observations'][label]['floor'] *= NU_MULTIPLIER
            else:
                detached['capture_scalars'] = capture_scalars
            detached['bootstrap_trace'] = bootstrap_traces
            if records is None:
                if 'range_observations' not in detached:
                    detached['range_observations'] = copy_range_observations(result.range_observations, result.range_observation_count)
                replay_range_observations(detached['range_observations'])
            else:
                from sjtu_tpmshx.run_control.run_warnings import current_warnings, merge_warnings
                merge_warnings(current_warnings(), [warnings])
            from sjtu_tpmshx.physical_models.nu_correlations import warn_sco2_nu_evidence
            for s,label in enumerate('AB'):
                if cfg['fluid_type_'+label]=='sco2' and (s==0 or data.solve_b):
                    warn_sco2_nu_evidence(side=label,stage='3D h_v property refresh',tpms_type=cfg['tpms_type'],
                        L_mm=p['design']['L_field_m']*1e3 if data.spatial else cfg['Lcell'],
                        t_mm=p['design']['t_field_m']*1e3 if data.spatial else cfg['t_wall'],P_in=cfg['P_in'+label])
            return detached
        finally:
            if stage_result is not None:
                stage.release_result(self.library, stage_result)
            elif result.owner:
                self.release(ct.byref(result))


def run_case(case, control=RunControl(), *, resume_state=None, checkpoint=None, checkpoint_due=None):
    if control.backend != 'cpp':
        raise ValueError('full native 3D requires backend=cpp')
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    control.check_cancelled()
    from sjtu_tpmshx.data_types.persistence_validation import grid_axes, validate_axis_permutation
    grid_axes(case.grid)
    for side, axes in case.parameters['prepared']['axes'].items():
        if axes is not None:
            validate_axis_permutation(axes, side)
    runtime = stage.open_library(control.native_library, getattr(control, 'native_table_directory', None))
    _, library, abi, table_directory = runtime
    saved_v2 = hasattr(library, 'tpmshx_stage_run_3d_create_saved_v2')
    saved = stage.has_saved_stage(library)
    if saved and saved_v2:
        query = execution_view_query(library, 3, stage._StageResult, stage._ExecutionView)
        if query is not None:
            return stage.run_saved(case, control, library, abi, table_directory, query,
                resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)
    driver = NativeFull3DDriver.__new__(NativeFull3DDriver)
    driver._bind(runtime)
    if saved and saved_v2:
        _, cell_mm, wall_mm, nu = stage.validate_saved_case(case)
        cfg = dict(case.parameters, Lcell=cell_mm, t_wall=wall_mm, sco2_nu=nu)
        cfg.pop('_input_resolution', None)
        p = dict(case.parameters['prepared'], design=case.design_fields,
                 **{'d' + axis: case.grid['d' + axis] for axis in 'xyz'})
    else:
        from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
        cfg, p = build_execution_inputs(case, copy_design=False)
    r = driver._run_prepared(cfg, p, control, application_only=True, resume_state=resume_state,
        checkpoint=checkpoint, checkpoint_due=checkpoint_due, stage_case=case if saved else None)
    control.check_cancelled()
    if "stage_diagnostics" not in r:
        from .full_3d_capture import capture_result
    else:
        capture_result = stage.capture_result
    if '_input_resolution' not in cfg:
        from sjtu_tpmshx.data_types.case_data import resolved_input_record
        cfg['_input_resolution'] = resolved_input_record(case, {side: cfg['fluid_type_' + side] for side in 'AB'},
            tuple(p['N' + axis] for axis in 'xyz'), {side: cfg['fluid_' + side + '_cfg']['dir'] for side in p['axes']})
    return capture_result(case, cfg, p, r, abi)
