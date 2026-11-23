"""Typed prepared-data binding to the full native 3D numerical driver.

Python validates the persisted schema, resolves recorded controls, and detaches
owned output views. Production runs use the saved stage protocol in
``full_3d_stage``. This direct v5 binding serves the native solver verification tests. SIMPLE, EOS, closure refresh, energy, outer coupling and
physical convergence verdicts are produced by the C++ call.
"""
import ctypes as ct
from math import prod


from sjtu_tpmshx.data_types.compute_config import reject_retired_research_options
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.physical_models.fluid_props import WaterStateError

from .. import full_3d_stage as stage
from ..full_3d_stage import _detach
from ._full_3d_abi import _Callbacks, _Control, _EnergyEvidence, _Input, _Result
from ._simple_abi import _F2
from ._stage_capture_abi import (
    _acceleration_query,
    _copy_iteration_records,
    _copy_update_scale,
    _iteration_query,
    _model_h_algorithm,
    _update_scale_query,
    copy_sampling,
    sampling_query,
)
from .closure_evidence import copy_range_observations, replay_range_observations, last_range_query, copy_last_ranges
from ._thermal_abi import (
    _EnergyOptions,
    _EnergyOptionsV2,
    _FullEnergyEffectiveSettings,
    _IterationOptions,
    _energy_algorithm_query,
    _full_enthalpy_defaults,
)
from .physical_ledger import HeatLedger, heat_ledger_query, copy_heat_ledger
from .simple_3d import _Config as _SimpleConfig
from .temperature import _temperature_algorithm
from .temperature_evidence import TemperatureEvidence, copy_temperature_evidence


class NativeFull3DDriver:
    def __init__(self, library, *, table_directory=None):
        self._bind(stage.open_library(library, table_directory))

    def _bind(self, runtime):
        self.path, self.library, self.abi, self.table_directory = runtime
        try:
            self.call = self.library.tpmshx_solve_full_3d_v5
        except AttributeError as exc:
            raise ValueError('native full 3D library lacks tpmshx_solve_full_3d_v5; rebuild the library') from exc
        self.call.argtypes = [ct.POINTER(_Input), ct.POINTER(_Control), ct.POINTER(_EnergyOptions),
                              ct.POINTER(_EnergyOptionsV2), ct.POINTER(_IterationOptions), ct.c_size_t,
                              ct.POINTER(_Callbacks), ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
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
                      resume_state=None, checkpoint=None, checkpoint_due=None):
        control.check_cancelled()
        reject_retired_research_options(cfg)
        energy = stage.energy_request(cfg)
        defaults = _full_enthalpy_defaults(self.library, 3, energy.algorithm,
            'water' in (cfg['fluid_type_A'], cfg['fluid_type_B']))
        require_h, strict_options = stage.validate_energy_controls(cfg)
        energy_query = version_query = None
        entry_version = 5
        model_h_options = stage.model_h_request(cfg, strict_options)
        if model_h_options is None and strict_options:
            energy = _EnergyOptionsV2(energy.algorithm, energy.temperature_update_tolerance,
                defaults.coupled_energy_tolerance if cfg.get('ltne_enthalpy_coupled_energy_tol') is None else cfg['ltne_enthalpy_coupled_energy_tol'],
                defaults.equation_energy_tolerance if cfg.get('ltne_enthalpy_equation_energy_tol') is None else cfg['ltne_enthalpy_equation_energy_tol'],
                require_h)
        if energy.algorithm:
            version_query = _energy_algorithm_query(self.library)
            try:
                energy_query = self.library.tpmshx_full_3d_get_energy_evidence_v1
            except AttributeError as exc:
                raise ValueError('native full 3D library lacks conservative energy v5 evidence') from exc
            energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
            energy_query.restype = ct.c_int
        stage.validate_flow_options(cfg)
        shape = tuple(p['N'+a] for a in 'xyz')
        keepalive = []
        data = stage.pack_input(cfg, p, p, p['design'], shape, cfg['Lcell'], cfg['sco2_nu'], keepalive)
        request = stage._request(cfg, energy, model_h_options)
        stage.pack_run_controls(request, cfg, p, shape)

        def value_or(option, default):
            return option.value if option.present else default

        c = _Control()
        c.max_outer = value_or(request.max_outer_ltne, 12)
        c.initial_simple_iterations = value_or(request.max_iter_simple, 2000)
        c.warm_simple_iterations = value_or(request.max_iter_simple, 600)
        c.thermal_iterations = request.thermal_iterations.value
        c.outer_temperature_tolerance = value_or(request.outer_tol_K, .5)
        c.thermal_relaxation = value_or(request.thermal_relaxation, .7)
        for name in ('pressure_shooting', 'variable_rho_cp', 'conservative', 'strict_mass_balance',
                     'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a',
                     'coarse_bootstrap', 'roughness_mode', 'envelope_mode'):
            setattr(c, name, getattr(request, name).value)
        c.coarse_iterations = value_or(request.coarse_iterations, 200)
        c.red_black_energy = int(prod(shape)>30000 and not (energy.algorithm and data.solve_b
            and any(side.fluid in (2, 3) for side in data.sides)))
        c.has_initial_solid_temperature = request.solid_seed_K.present
        c.roughness_height, c.initial_solid_temperature = request.roughness_height_m.value, request.solid_seed_K.value
        c.simple = _SimpleConfig(2000, 1, 100, value_or(request.simple_velocity_relaxation, .5), .2, .3, 0., 287.05, .05, 1, 1, 0,
            request.adaptive_pressure_tolerance.value, request.track_momentum.value,
            int(request.parallel_threshold.value == 1),
            _F2(value_or(request.mom_tol, 1e-4), value_or(request.mass_local_tol, 1e-6), value_or(request.mass_global_tol, 1e-6),
                .01, 1e-4, 1e-3, 2, 5, 60))
        for target, source, default in (
                ('enthalpy_iterations', 'energy_iterations', defaults.max_iterations),
                ('enthalpy_sweeps', 'energy_sweeps', defaults.sweeps),
                ('enthalpy_omega', 'energy_omega', defaults.omega),
                ('enthalpy_update_tolerance', 'energy_update_tolerance', defaults.update_tolerance)):
            setattr(c, target, value_or(getattr(request, source), default))
        c.table_directory = self.table_directory
        callbacks, callback_errors = stage.make_callbacks(control)
        result, error = _Result(), ct.create_string_buffer(2048)
        cpu_thread_limit = control.native_cpu_threads()
        try:
            if resume_state is not None or checkpoint is not None:
                from sjtu_tpmshx.cpp_interface.solver_library.full_3d_run import NativeFull3DRun
                true_h = data.solve_b and any(side.fluid in (2, 3) for side in data.sides)
                options = energy if strict_options else (_EnergyOptionsV2(
                    energy.algorithm, energy.temperature_update_tolerance,
                    defaults.coupled_energy_tolerance, defaults.equation_energy_tolerance, require_h)
                    if true_h else None)
                with NativeFull3DRun(self.library, data, c, options, callbacks, cpu_threads=cpu_thread_limit,
                                     model_h=model_h_options, state=resume_state) as run:
                    while run.phase not in (3, 4):
                        phase = run.advance()
                        if callback_errors:
                            raise callback_errors[0]
                        if (checkpoint is not None and phase in (1, 2, 6, 7, 8, 9, 10)
                                and (checkpoint_due is None or checkpoint_due())):
                            checkpoint(run.snapshot())
                    result = run.take_result()
                code = 0
            else:
                code = self.call(ct.byref(data), ct.byref(c),
                    ct.byref(energy) if not strict_options and model_h_options is None else None,
                    ct.byref(energy) if strict_options else None,
                    ct.byref(model_h_options) if model_h_options is not None else None,
                    cpu_thread_limit, ct.byref(callbacks), ct.byref(result), error, len(error))
            if callback_errors:
                raise callback_errors[0]
            if code:
                raise {1:ValueError, 2:WaterStateError, 3:FloatingPointError}.get(code,RuntimeError)(error.value.decode())
            bootstrap_traces = stage.bootstrap_traces(self.query_bootstrap, result)
            stage.require_completed(result, bootstrap_traces)
            actual = _FullEnergyEffectiveSettings()
            if self.query_settings(ct.byref(result), ct.byref(actual)):
                raise RuntimeError('native full 3D effective settings query failed')
            if actual.outer_count != result.outer_count:
                raise RuntimeError('native full 3D effective settings do not match the thermal history')
            detached=_detach(result, shape, c, actual, entry_version,
                             emit_audit=bool(cfg.get('_emit_audit',False)), application_only=application_only)
            if actual.last.available and energy_query:
                extra = _EnergyEvidence()
                if energy_query(ct.byref(result), ct.byref(extra)):
                    raise RuntimeError('native full 3D energy evidence query failed')
                stage.add_energy_evidence(detached, extra, actual, entry_version, shape, version_query=version_query)
            detached['property_sampling'] = copy_sampling(sampling_query(self.library, 3, _Result), result)
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
            detached['last_closure_ranges'] = copy_last_ranges(last_range_query(self.library, 3, _Result), result)
            if 'temperature_evidence' not in detached:
                ledger = HeatLedger()
                if heat_ledger_query(self.library, 3, _Result)(ct.byref(result), ct.byref(ledger)):
                    raise RuntimeError('native full 3D heat ledger query failed')
                detached['physical_ledger'] = copy_heat_ledger(ledger, shape, 3)
            from sjtu_tpmshx.physical_models.co2_correlations import NU_MULTIPLIER
            for label in 'AB':
                if cfg['fluid_type_'+label] == 'co2' and detached['nu_observations'][label]:
                    detached['nu_observations'][label]['floor'] *= NU_MULTIPLIER
            detached['bootstrap_trace'] = bootstrap_traces
            if 'range_observations' not in detached:
                detached['range_observations'] = copy_range_observations(result.range_observations, result.range_observation_count)
            replay_range_observations(detached['range_observations'])
            from sjtu_tpmshx.physical_models.nu_correlations import warn_sco2_nu_evidence
            for s,label in enumerate('AB'):
                if cfg['fluid_type_'+label]=='sco2' and (s==0 or data.solve_b):
                    warn_sco2_nu_evidence(side=label,stage='3D h_v property refresh',tpms_type=cfg['tpms_type'],
                        L_mm=p['design']['L_field_m']*1e3 if data.spatial else cfg['Lcell'],
                        t_mm=p['design']['t_field_m']*1e3 if data.spatial else cfg['t_wall'],P_in=cfg['P_in'+label])
            return detached
        finally:
            if result.owner:
                self.release(ct.byref(result))
