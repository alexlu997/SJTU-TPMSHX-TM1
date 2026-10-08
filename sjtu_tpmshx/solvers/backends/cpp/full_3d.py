"""Typed prepared-data binding to the full native 3D numerical driver.

Python validates the persisted schema, resolves recorded controls, and detaches
owned output views. SIMPLE, EOS, closure refresh, energy, outer coupling and
physical convergence verdicts are produced by the C++ call.
"""
import ctypes as ct
import os
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_environment import run_environment, require_f2_mode
from sjtu_tpmshx.models.fluid_props import WaterStateError
from sjtu_tpmshx.models.field_coordinates_3d import _port_rectangles
from .simple_3d import _Config as _SimpleConfig, _Result as _SimpleResult, _STOPS, _count
from ._simple_abi import _F2
from .model_h import _Result as _ModelResult, _volume_info, _model_h_algorithm
from .temperature import _temperature_algorithm
from .temperature_evidence import TemperatureEvidence, copy_temperature_evidence
from .enthalpy import _Result as _EnthalpyResult, _result_info as _enthalpy_result_info
from .enthalpy import (_EnergyOptions, _EnergyResult, _energy_options,
                       _energy_algorithm_query, _energy_result_info, _energy_native_state, _ENERGY_NAMES)
from .closure_evidence import NuObservation, RangeObservation, copy_nu_observation, copy_range_observations, replay_range_observations


class _Array(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_double)), ('size', ct.c_size_t)]


class _Side(ct.Structure):
    _fields_ = [('fluid', ct.c_uint32), ('direction', ct.c_uint32), ('solver_axes', ct.c_uint32*3)]
    _fields_ += [(n, ct.c_double) for n in ('inlet_temperature', 'inlet_pressure', 'inlet_velocity')]
    _fields_ += [('inlet_rectangle', ct.c_double*4), ('outlet_rectangle', ct.c_double*4),
                ('inlet_opening', _Array), ('outlet_opening', _Array)]
    _fields_ += [(n, ct.c_double) for n in ('permeability_scale', 'forchheimer_scale', 'dispersion', 'sco2_nusselt_multiplier')]
    _fields_ += [('heat_transfer_geometry', ct.c_double*4)]


class _Input(ct.Structure):
    _fields_ = [('shape', ct.c_size_t*3), ('widths', _Array*3)]
    _fields_ += [(n, _Array) for n in ('epsilon', 'epsilon_a', 'epsilon_b', 'permeability', 'forchheimer',
                                     'solid_conductivity', 'cell_length', 'area_density', 'hydraulic_diameter')]
    _fields_ += [('reference_cell_length', ct.c_double), ('reference_hydraulic_diameter', ct.c_double)]
    _fields_ += [(n, ct.c_uint32) for n in ('topology', 'spatial', 'asymmetric', 'solve_b')]
    _fields_ += [('sides', _Side*2), ('sources', _Array*3)]


class _Control(ct.Structure):
    _fields_ = [(n, ct.c_size_t) for n in ('max_outer', 'initial_simple_iterations', 'warm_simple_iterations', 'thermal_iterations')]
    _fields_ += [(n, ct.c_double) for n in ('outer_temperature_tolerance', 'thermal_relaxation')]
    _fields_ += [(n, ct.c_uint32) for n in ('pressure_shooting', 'variable_rho_cp', 'conservative', 'strict_mass_balance',
        'force_cell_centered', 'refined_port_energy', 'red_black_energy', 'sco2_local_pressure_a', 'coarse_bootstrap', 'outer_anderson')]
    _fields_ += [(n, ct.c_size_t) for n in ('coarse_iterations', 'anderson_history', 'anderson_patience')]
    _fields_ += [('anderson_trust', ct.c_double)]
    _fields_ += [(n, ct.c_uint32) for n in ('roughness_mode', 'envelope_mode', 'has_initial_solid_temperature')]
    _fields_ += [(n, ct.c_double) for n in ('roughness_height', 'initial_solid_temperature')]
    _fields_ += [('simple', _SimpleConfig), ('enthalpy_iterations', ct.c_size_t), ('enthalpy_sweeps', ct.c_size_t),
                ('enthalpy_omega', ct.c_double), ('enthalpy_update_tolerance', ct.c_double), ('table_directory', ct.c_char_p)]


class _PressureState(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('passed', ct.c_uint32)]
    _fields_ += [(n, ct.c_double) for n in ('specified', 'realized', 'outlet', 'outlet_gauge', 'minimum', 'relative_error', 'relative_tolerance')]
    _fields_ += [('definition', ct.c_char_p)]


class _PressureIteration(ct.Structure):
    _fields_ = [('stage', ct.c_char_p)]
    _fields_ += [(n, ct.c_double) for n in ('anchor', 'estimate', 'relative_error', 'target', 'step_fraction')]
    _fields_ += [(n, ct.c_uint32) for n in ('has_estimate', 'has_relative_error', 'has_target', 'has_step_fraction')]
    _fields_ += [('method', ct.c_char_p)]


class _Bootstrap(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('available', 'applied', 'converged')]
    _fields_ += [('iterations', ct.c_size_t), ('shape', ct.c_size_t*3), ('residual', ct.c_double), ('reason', ct.c_char_p)]


class _BootstrapLevel(ct.Structure):
    _fields_ = [('depth', ct.c_size_t), ('fine_shape', ct.c_size_t*3), ('coarse_shape', ct.c_size_t*3),
                ('iteration_cap', ct.c_size_t), ('charged_iterations', ct.c_size_t)]
    _fields_ += [(n, ct.c_uint32) for n in ('solve_started', 'applied', 'converged', 'child_selected')]
    _fields_ += [('stop', ct.c_char_p)]


class _BootstrapTrace(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('selected', ct.c_uint32), ('policy', ct.c_char_p),
                ('decision', ct.c_char_p), ('fine_shape', ct.c_size_t*3)]
    _fields_ += [(n, ct.c_size_t) for n in ('coarse_iteration_cap', 'recursive_iteration_cap',
                                           'auto_cell_threshold', 'min_coarse_axis')]
    _fields_ += [('levels', ct.POINTER(_BootstrapLevel))]
    _fields_ += [(n, ct.c_size_t) for n in ('level_count', 'actual_levels', 'started_cap_sum', 'total_charged_iterations')]


class _Anderson(ct.Structure):
    _fields_ = [('available', ct.c_uint32), *[(n, ct.c_size_t) for n in ('applied', 'rejected', 'resets')], ('residuals', _Array)]


_FLOW_ARRAYS = ('epsilon', 'permeability', 'forchheimer', 'temperature', 'viscosity', 'effective_viscosity', 'density',
    'u', 'v', 'w', 'pressure', 'pressure_correction', 'd_u', 'd_v', 'd_w', 'inlet_velocity', 'inlet_opening', 'outlet_opening',
    'outlet_u_fraction', 'outlet_w_fraction', 'fixed_inlet_massflux', 'pressure_real', 'density_real', 'speed_real')


class _Flow(ct.Structure):
    _fields_ = [('widths', _Array*3), *[(n, _Array) for n in _FLOW_ARRAYS],
                ('velocity_real', _Array*3), ('face_velocity_real', _Array*3), ('pressure_reference', ct.c_double),
                ('last', _SimpleResult), *[(n, _Array) for n in ('legacy', 'local_mass', 'global_mass', 'momentum')],
                ('pressure_iterations', ct.POINTER(_PressureIteration)), ('pressure_iteration_count', ct.c_size_t),
                ('inlet_pressure', _PressureState), ('bootstrap', _Bootstrap), ('anderson', _Anderson)]


class _Projection(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('available', 'skipped', 'used_bordered_lu')]
    _fields_ += [('cg_iterations', ct.c_size_t), ('rhs_mean', ct.c_double), ('residual_relative', ct.c_double),
                ('residual_cells', _Array), ('residual_available', ct.c_uint32)]
    _fields_ += [(n, ct.c_double) for n in ('residual_sum', 'residual_max', 'exchange', 'global_ratio', 'cell_ratio')]


class _Outer(ct.Structure):
    _fields_ = [('outer_index', ct.c_size_t), ('thermal_iterations', ct.c_size_t), ('thermal_residual', ct.c_double),
                ('temperature_change', ct.c_double*3), ('inlet_pressure', _PressureState*2),
                ('pressure_reference', ct.c_double*2), ('pressure_range', (ct.c_double*2)*2),
                ('thermal_converged', ct.c_uint32), ('coupling_converged', ct.c_uint32),
                ('rejected_startup_iterations', ct.POINTER(ct.c_size_t)), ('rejected_startup_count', ct.c_size_t),
                ('startup_total_iterations', ct.c_size_t), ('rejected_startup_reasons', ct.POINTER(ct.c_char_p)),
                ('has_model_h', ct.c_uint32), ('has_true_h', ct.c_uint32),
                ('model_h', _ModelResult), ('true_h', _EnthalpyResult)]


_FLAGS = ('stop', 'converged', 'simple_ok', 'thermal_ok', 'outer_ok', 'finite_fields', 'envelope_ok', 'post_after_last_thermal')
_PAIRS = ('pressure_drop', 'outlet_temperature', 'inlet_mass', 'duty', 'maximum_mach', 'minimum_pressure',
          'solid_exchange', 'interior_exchange', 'physical_mass_in', 'physical_mass_out', 'mass_imbalance')


class _Result(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in (*_FLAGS, 'thermal_mode')]
    _fields_ += [('thermal_outer_index', ct.c_size_t), ('flow', _Flow*2), ('temperature', _Array*3)]
    _fields_ += [(n, _Array*2) for n in ('thermal_pressure', 'hv', 'rho_cp', 'conductivity')]
    _fields_ += [('mass', (_Array*3)*2), ('face_velocity', (_Array*3)*2), ('inlet_capacity', _Array*2), ('enthalpy', _Array*2),
                ('has_model_h', ct.c_uint32), ('has_true_h', ct.c_uint32), ('model_h', _ModelResult), ('true_h', _EnthalpyResult),
                ('staggered', _Projection*2), ('outer', ct.POINTER(_Outer)), ('outer_count', ct.c_size_t),
                ('simple_failures', ct.POINTER(ct.c_char_p)), ('simple_failure_count', ct.c_size_t),
                ('warnings', ct.POINTER(ct.c_char_p)), ('warning_count', ct.c_size_t),
                ('envelope_reasons',ct.POINTER(ct.c_char_p)),('envelope_reason_count',ct.c_size_t),
                ('final_conductivity',_Array*2),('final_rho_cp',_Array*2),('inlet_cp',ct.c_double*2),
                ('nu_observations',NuObservation*2),('range_observations',ct.POINTER(RangeObservation)),('range_observation_count',ct.c_size_t)]
    _fields_ += [(n, ct.c_double*2) for n in _PAIRS]
    _fields_ += [(n, ct.c_double) for n in ('energy_imbalance', 'interior_duty', 'interior_imbalance', 'enthalpy_imbalance')]
    _fields_ += [('owner', ct.c_void_p)]


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_double)
_OuterProgress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_size_t)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('outer_iteration', _OuterProgress), ('context', ct.c_void_p)]


class _EnergyEvidence(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('energy', _EnergyResult),
                ('actual_conductivity', _Array * 2), ('boundary_power', (_Array * 6) * 2),
                ('outer', ct.POINTER(_EnergyResult)), ('outer_count', ct.c_size_t)]


class _EnergyOptionsV2(ct.Structure):
    _fields_ = [('algorithm', ct.c_uint32), ('temperature_update_tolerance', ct.c_double),
                ('coupled_energy_tolerance', ct.c_double), ('equation_energy_tolerance', ct.c_double),
                ('require_enthalpy_update_on_temperature', ct.c_uint32)]


class _EnergyEffectiveSettings(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in (
        'available', 'algorithm', 'require_enthalpy_update_on_temperature')]
    _fields_ += [(name, ct.c_size_t) for name in ('max_iterations', 'sweeps')]
    _fields_ += [(name, ct.c_double) for name in ('omega', 'update_tolerance',
        'temperature_update_tolerance', 'coupled_energy_tolerance', 'equation_energy_tolerance')]


class _FullEnergyEffectiveSettings(ct.Structure):
    _fields_ = [('resolved', _EnergyEffectiveSettings), ('last', _EnergyEffectiveSettings),
                ('outer', ct.POINTER(_EnergyEffectiveSettings)), ('outer_count', ct.c_size_t)]


def _executed_energy_settings(info, actual):
    if actual.available != 1 or actual.algorithm not in range(len(_ENERGY_NAMES)):
        raise RuntimeError('native full 3D omitted executed thermal settings')
    info['effective_settings'].update(
        update_tol=actual.update_tolerance,
        coupled_energy_tol=actual.coupled_energy_tolerance,
        equation_energy_tol=actual.equation_energy_tolerance,
        max_iterations=actual.max_iterations, sweeps=actual.sweeps, omega=actual.omega,
        energy_algorithm=_ENERGY_NAMES[actual.algorithm],
        require_enthalpy_update_on_temperature=bool(actual.require_enthalpy_update_on_temperature),
        effective_settings_source='native_completed_thermal_call', driver_abi=3)
    if actual.algorithm:
        info['effective_settings']['temperature_update_tol_K'] = actual.temperature_update_tolerance


def _copy(v, shape=None):
    if not v.size:
        return None
    result = np.ctypeslib.as_array(v.data, (v.size,)).copy()
    return result if shape is None else result.reshape(shape)


def _pressure(p):
    if not p.available:
        return None
    return dict(specified_Pa=p.specified, realized_Pa=p.realized, outlet_Pa=p.outlet,
                outlet_gauge_Pa=p.outlet_gauge, minimum_Pa=p.minimum,
                relative_error=p.relative_error, relative_tolerance=p.relative_tolerance,
                passed=bool(p.passed), definition=p.definition.decode())


def _enthalpy_info(r, settings):
    return _enthalpy_result_info(r, update_tol=settings.enthalpy_update_tolerance,
        coupled_energy_tol=.001,equation_energy_tol=.001,max_iterations=settings.enthalpy_iterations,
        sweeps=settings.enthalpy_sweeps,omega=settings.enthalpy_omega)


def _model_info(r, shape, *, include_faces):
    info = _volume_info(r, shape, include_faces=include_faces)
    names = [f'{side} strict {metric} < 1 %' for side in ('A', 'B') for metric in ('global', 'cellmax')]
    names += ['full-volume LTNE source balance < 1 %', 'physical boundary data complete']
    info['energy_finishing_checks'] = [dict(iterations=r.finishing_checks[i].iterations,
        gates=[(name, bool(value)) for name, value in zip(names, r.finishing_checks[i].gates)]) for i in range(r.finishing_count)]
    return info


class NativeFull3DDriver:
    def __init__(self, library, *, table_directory=None):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native full 3D library must be an absolute path')
        self.path = path.resolve(strict=True)
        self.library = ct.CDLL(str(self.path))
        version = self.library.tpmshx_full_3d_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 1:
            raise ValueError(f'unsupported full 3D ABI {self.abi}; expected 1')
        if table_directory is not None and not Path(table_directory).is_absolute():
            raise ValueError('native full 3D table directory must be an absolute path')
        self.table_directory = None if table_directory is None else str(table_directory).encode()
        self.call = self.library.tpmshx_solve_full_3d_v1
        self.call.argtypes = [ct.POINTER(_Input), ct.POINTER(_Control), ct.POINTER(_Callbacks),
                             ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int
        self.release = self.library.tpmshx_full_3d_release_v1
        self.release.argtypes, self.release.restype = [ct.POINTER(_Result)], None
        try:
            self.query_bootstrap = self.library.tpmshx_full_3d_get_bootstrap_trace_v1
        except AttributeError as exc:
            raise ValueError('native full 3D library lacks bootstrap trace v1; rebuild the library for this binding') from exc
        self.query_bootstrap.argtypes = [ct.POINTER(_Result), ct.c_size_t, ct.POINTER(_BootstrapTrace)]
        self.query_bootstrap.restype = ct.c_int

    def _bootstrap_traces(self, result):
        traces = {}
        for side, label in enumerate('AB'):
            view = _BootstrapTrace()
            if self.query_bootstrap(ct.byref(result), side, ct.byref(view)):
                raise RuntimeError('native full 3D bootstrap trace query failed')
            if not view.available:
                traces[label] = None
                continue
            trace = dict(policy=view.policy.decode(), decision=view.decision.decode(),
                         selected=bool(view.selected), fine_shape=tuple(view.fine_shape))
            trace.update({key: getattr(view, key) for key in ('coarse_iteration_cap', 'recursive_iteration_cap',
                'auto_cell_threshold', 'min_coarse_axis', 'actual_levels', 'started_cap_sum', 'total_charged_iterations')})
            trace['levels'] = []
            for index in range(view.level_count):
                row = view.levels[index]
                record = dict(depth=row.depth, fine_shape=tuple(row.fine_shape), coarse_shape=tuple(row.coarse_shape),
                              iteration_cap=row.iteration_cap, charged_iterations=row.charged_iterations, stop=row.stop.decode())
                record.update({key: bool(getattr(row, key)) for key in ('solve_started', 'applied', 'converged', 'child_selected')})
                trace['levels'].append(record)
            traces[label] = trace
        return traces

    def run_prepared(self, cfg, p, control=RunControl()):
        return self._run_prepared(cfg, p, control)

    def _run_prepared(self, cfg, p, control=RunControl(), *, application_only=False):
        control.check_cancelled()
        energy = _energy_options(cfg.get('enthalpy_algorithm', 'legacy_h_fou'),
                                 cfg.get('enthalpy_temperature_tol_K', 1e-8))
        require_h = cfg.get('require_enthalpy_update_on_temperature', False)
        if type(require_h) is not bool:
            raise ValueError('require_enthalpy_update_on_temperature must be boolean')
        strict_options = require_h or any(cfg.get(name) is not None for name in (
            'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol'))
        energy_call = energy_query = settings_query = version_query = None
        entry_version = 1
        if strict_options:
            energy = _EnergyOptionsV2(energy.algorithm, energy.temperature_update_tolerance,
                .001 if cfg.get('ltne_enthalpy_coupled_energy_tol') is None else cfg['ltne_enthalpy_coupled_energy_tol'],
                .001 if cfg.get('ltne_enthalpy_equation_energy_tol') is None else cfg['ltne_enthalpy_equation_energy_tol'],
                require_h)
            try:
                energy_call = self.library.tpmshx_solve_full_3d_v3
                settings_query = self.library.tpmshx_full_3d_get_energy_effective_settings_v1
            except AttributeError as exc:
                raise ValueError('native full 3D library lacks explicit energy controls v3') from exc
            energy_call.argtypes = [*self.call.argtypes[:2], ct.POINTER(_EnergyOptionsV2), *self.call.argtypes[2:]]
            energy_call.restype = ct.c_int
            settings_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_FullEnergyEffectiveSettings)]
            settings_query.restype = ct.c_int
            entry_version = 3
        elif energy.algorithm:
            try:
                energy_call = self.library.tpmshx_solve_full_3d_v2
            except AttributeError as exc:
                raise ValueError('native full 3D library lacks conservative energy v2') from exc
            energy_call.argtypes = [*self.call.argtypes[:2], ct.POINTER(_EnergyOptions), *self.call.argtypes[2:]]
            energy_call.restype = ct.c_int
            entry_version = 2
        if energy.algorithm:
            version_query = _energy_algorithm_query(self.library)
            try:
                energy_query = self.library.tpmshx_full_3d_get_energy_evidence_v1
            except AttributeError as exc:
                raise ValueError(f'native full 3D library lacks conservative energy v{entry_version} evidence') from exc
            energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
            energy_query.restype = ct.c_int
        require_f2_mode(cfg.get('convergence_mode') or run_environment(cfg, 'TPMSHX_CONV_MODE', 'f2'))
        if cfg.get('use_anderson', False):
            raise ValueError('use_anderson=True in SIMPLE has been retired; disable TPMSHX_PHASE_B/use_anderson')
        shape = tuple(p['N'+a] for a in 'xyz')
        keepalive = []
        def view(value, expected=None):
            value = np.asarray(value, dtype=np.float64)
            if expected is not None:
                value = np.broadcast_to(value, expected)
            value = np.require(value, requirements=['C', 'A'])
            keepalive.append(value)
            return _Array(value.ctypes.data_as(ct.POINTER(ct.c_double)), value.size)
        data = _Input()
        data.shape[:] = shape
        data.widths[:] = [view(p['d'+axis]) for axis in 'xyz']
        for key, source in zip(('epsilon', 'epsilon_a', 'epsilon_b', 'permeability', 'forchheimer', 'solid_conductivity', 'cell_length'),
                               ('eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m', 'K_ss', 'L_field_m')):
            setattr(data, key, view(p['design'][source], shape))
        thermal = cfg['thermal_geometry']
        spatial = bool(cfg.get('zone_grid_cells') or cfg.get('continuous_field'))
        geometry = thermal['fields' if spatial else 'uniform']
        data.area_density, data.hydraulic_diameter = view(geometry['A_0'], shape), view(geometry['D_h'], shape)
        data.reference_cell_length, data.reference_hydraulic_diameter = cfg['Lcell']*1e-3, p['geometry']['D_h']
        data.topology = ('Diamond', 'Gyroid').index(cfg['tpms_type'])
        data.spatial, data.asymmetric, data.solve_b = spatial, cfg.get('delta_levelset', 0.) != 0., cfg.get('fluid_B_cfg') is not None
        for s, label in enumerate('AB'):
            a = data.sides[s];axis = p['axes'][label];bc = cfg['fluid_'+label+'_cfg']
            a.fluid = ('air', 'water', 'sco2').index(cfg['fluid_type_'+label]);a.direction = 3 if bc is None else bc['dir']
            a.solver_axes[:] = [axis[key+'_real_axis'] for key in ('cross1', 'stream', 'cross2')]
            a.inlet_temperature, a.inlet_pressure, a.inlet_velocity = cfg['T_in'+label], cfg['P_in'+label], cfg['u_'+label]
            rectangles = _port_rectangles(bc, float(sum(axis['dcross2']))) if bc is not None else dict(inlet_rect=(0.,1.,0.,1.),outlet_rect=(0.,1.,0.,1.))
            a.inlet_rectangle[:], a.outlet_rectangle[:] = rectangles['inlet_rect'], rectangles['outlet_rect']
            a.inlet_opening, a.outlet_opening = (view(p['openings'][label][end]) for end in ('inlet', 'outlet'))
            correction = (cfg.get('df_application') or {}).get(label, {})
            a.permeability_scale, a.forchheimer_scale = correction.get('scale_K', 1.), correction.get('scale_F', 1.)
            a.dispersion = cfg.get('disp_C_'+label, 0.)
            nu = cfg['sco2_nu']
            a.sco2_nusselt_multiplier = getattr(nu, 'alpha_D' if data.topology == 0 else 'alpha_G') if nu.mode == 'experimental' else 1.
            a.heat_transfer_geometry[:] = thermal['side_geometry'][label] if data.asymmetric else (1.,1.,1.,1.)
        data.sources[:] = [view(cfg.get('mms_S_'+s+'_field', np.empty(0))) for s in ('A', 'B', 's')]
        c = _Control()
        c.max_outer = _count(p['max_outer'] if p['max_outer'] is not None else 12)
        c.initial_simple_iterations = _count(cfg.get('max_iter_simple') if cfg.get('max_iter_simple') is not None else 2000)
        c.warm_simple_iterations = _count(cfg.get('max_iter_simple') if cfg.get('max_iter_simple') is not None else 600)
        c.thermal_iterations = _count(p['ltne_max_iter']);c.outer_temperature_tolerance = cfg.get('outer_tol_K') if cfg.get('outer_tol_K') is not None else .5
        c.thermal_relaxation = cfg.get('ltne_alpha_T', .7)
        c.pressure_shooting = run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') != '0'
        vrho = run_environment(cfg, 'TPMSHX_VAR_RHOCP')
        c.variable_rho_cp = vrho == '1' if vrho in ('0', '1') else bool(cfg.get('variable_rho_cp', True))
        c.conservative, c.strict_mass_balance, c.force_cell_centered = (bool(cfg.get(k, True)) for k in ('conservative_ltne', 'strict_mass_balance', 'force_cc_ltne'))
        c.refined_port_energy = bool(cfg.get('port_wall_refine', False))
        c.red_black_energy = int(not energy.algorithm and np.prod(shape)>30000)
        c.sco2_local_pressure_a = run_environment(cfg, 'TPMSHX_SCO2_COMPRESSIBLE', '').lower() in ('1','true','yes')
        c.coarse_bootstrap, c.outer_anderson = bool(cfg.get('use_coarse_bootstrap', False)), bool(cfg.get('outer_anderson', False))
        c.coarse_iterations, c.anderson_history, c.anderson_patience = (_count(cfg.get(k, d)) for k, d in (
            ('coarse_bootstrap_max_iter', 200), ('outer_anderson_m', 3), ('outer_anderson_patience', 3)))
        c.anderson_trust = cfg.get('outer_anderson_trust', 5.)
        c.roughness_mode = ('baseline','norris_1a','bhatti_shah_1b').index(cfg['roughness_resolved']['mode'])
        c.envelope_mode = ('raise','warn','off').index(cfg.get('envelope_mode','raise'))
        c.has_initial_solid_temperature = cfg.get('T_s_init') is not None
        c.roughness_height, c.initial_solid_temperature = cfg['roughness_resolved']['eps_m'], cfg.get('T_s_init') or 0.
        c.simple = _SimpleConfig(2000, 1, 100, .5, .2, .3, 0., 287.05, .05, 1, 1, 0,
            bool(cfg.get('use_adaptive_amg_tol', True)), bool(cfg.get('track_momentum_residual', False)),
            int(np.prod(shape)>=int(os.environ.get('TPMSHX_PARALLEL_THRESHOLD','200000'))),
            _F2(cfg.get('mom_tol') or 1e-4, cfg.get('mass_local_tol') or 1e-6, cfg.get('mass_global_tol') or 1e-6,
                .01, 1e-4, 1e-3, 2, 5, 60))
        c.enthalpy_iterations, c.enthalpy_sweeps = _count(cfg.get('ltne_enthalpy_outer',1500)), _count(cfg.get('ltne_enthalpy_nsweep',5 if energy.algorithm else 25),zero=True)
        c.enthalpy_omega, c.enthalpy_update_tolerance = cfg.get('ltne_enthalpy_omega',.2 if energy.algorithm == 2 else .6), cfg.get('ltne_enthalpy_tol',1e-3)
        c.table_directory = self.table_directory
        callback_errors = []
        def callback(fn, *args):
            if not callback_errors:
                try:
                    return fn(*args)
                except BaseException as error:
                    callback_errors.append(error)
            return None
        @_Cancel
        def cancelled(_):
            return int(bool(callback_errors) or bool(callback(control.cancel_check) if control.cancel_check else False))
        @_Progress
        def progress(_, percent):
            callback(control.report_progress, int(percent))
        @_OuterProgress
        def outer(_, done, total):
            if control.iteration is not None:
                callback(control.iteration, f'outer {done}/{total}')
            if control.outer_iteration is not None:
                callback(control.outer_iteration, done, total)
        callbacks = _Callbacks(cancelled, progress, outer, None)
        result, error = _Result(), ct.create_string_buffer(2048)
        try:
            if energy_call:
                code = energy_call(ct.byref(data), ct.byref(c), ct.byref(energy), ct.byref(callbacks), ct.byref(result), error, len(error))
            else:
                code = self.call(ct.byref(data), ct.byref(c), ct.byref(callbacks), ct.byref(result), error, len(error))
            if callback_errors:
                raise callback_errors[0]
            if code:
                raise {1:ValueError, 2:WaterStateError, 3:FloatingPointError}.get(code,RuntimeError)(error.value.decode())
            bootstrap_traces = self._bootstrap_traces(result)
            if result.stop == 2:
                cancelled_error = CancelledError('compute cancelled by user')
                cancelled_error.coarse_bootstrap_trace = bootstrap_traces
                raise cancelled_error
            if result.stop not in (0,1):
                raise RuntimeError('invalid native full 3D exit')
            detached=_detach(result, shape, c, emit_audit=bool(cfg.get('_emit_audit',False)),
                             application_only=application_only)
            if energy_query:
                extra = _EnergyEvidence()
                if energy_query(ct.byref(result), ct.byref(extra)):
                    raise RuntimeError('native full 3D energy evidence query failed')
                if detached['true_h'] is None or extra.outer_count != len(detached['outer']):
                    raise RuntimeError('native full 3D energy evidence does not match the thermal history')
                _energy_result_info(detached['true_h'], extra.energy,
                    temperature_tol=energy.temperature_update_tolerance, abi=entry_version, version_query=version_query)
                _energy_native_state(detached['true_h'], extra, shape, 'W')
                for index, row in enumerate(detached['outer']):
                    _energy_result_info(row['true_h_info'], extra.outer[index],
                        temperature_tol=energy.temperature_update_tolerance, abi=entry_version, version_query=version_query)
                detached['mode'] = 'conservative_energy'
            detached['entry_version'] = entry_version
            if settings_query:
                actual = _FullEnergyEffectiveSettings()
                if settings_query(ct.byref(result), ct.byref(actual)):
                    raise RuntimeError('native full 3D effective settings query failed')
                if (actual.resolved.available != 1 or detached['true_h'] is None
                        or actual.outer_count != len(detached['outer'])):
                    raise RuntimeError('native full 3D effective settings do not match the thermal history')
                _executed_energy_settings(detached['true_h'], actual.last)
                for index, row in enumerate(detached['outer']):
                    _executed_energy_settings(row['true_h_info'], actual.outer[index])
            if detached['mode'] in ('model_h', 'temperature'):
                if detached['mode'] == 'model_h':
                    algorithm = _model_h_algorithm(self.library, 3)
                    red_black = bool(c.red_black_energy)
                else:
                    scheme = 0 if shape[2] == 1 else (2 if c.conservative or not c.force_cell_centered else 1)
                    red_black = bool(c.red_black_energy and scheme == 2)
                    if scheme == 2:
                        algorithm = _temperature_algorithm(self.library, scheme)
                    else:
                        query = self.library.tpmshx_full_3d_get_model_enthalpy_evidence_v1
                        query.argtypes = [ct.POINTER(_Result), ct.POINTER(TemperatureEvidence)]
                        query.restype = ct.c_int
                        extra = TemperatureEvidence()
                        if query(ct.byref(result), ct.byref(extra)):
                            raise RuntimeError('native full 3D temperature evidence query failed')
                        if not data.solve_b and data.sides[0].fluid == 2:
                            identity = 'legacy_frozen_cp_single_a_cc_v1'
                            if (extra.available or extra.physical_dimension != 3
                                    or extra.algorithm != identity.encode('ascii')):
                                raise RuntimeError('native single-A sCO2 temperature identity or absent ledger is invalid')
                            detached['temperature_transport'] = identity
                            algorithm = identity
                        else:
                            detached['temperature_evidence'] = copy_temperature_evidence(extra, shape, 3)
                            algorithm = detached['temperature_evidence']['algorithm']
                detached['native_metadata'] = dict(abi=self.abi, algorithm=algorithm, red_black=red_black)
                if 'temperature_transport' in detached:
                    detached['native_metadata']['transport'] = detached['temperature_transport']
            detached['bootstrap_trace'] = bootstrap_traces
            replay_range_observations(detached['range_observations'])
            from sjtu_tpmshx.models.nu_correlations import warn_sco2_nu_evidence
            for s,label in enumerate('AB'):
                if cfg['fluid_type_'+label]=='sco2' and (s==0 or data.solve_b):
                    warn_sco2_nu_evidence(side=label,stage='3D h_v property refresh',tpms_type=cfg['tpms_type'],
                        L_mm=p['design']['L_field_m']*1e3 if spatial else cfg['Lcell'],
                        t_mm=p['design']['t_field_m']*1e3 if spatial else cfg['t_wall'],P_in=cfg['P_in'+label])
            return detached
        finally:
            if result.owner:
                self.release(ct.byref(result))


def _detach(r, shape, settings, *, emit_audit=False, application_only=False):
    result = {name: getattr(r, name) if name == 'stop' else bool(getattr(r, name)) for name in _FLAGS}
    result.update({name: list(getattr(r, name)) for name in _PAIRS})
    result.update({name: getattr(r, name) for name in ('energy_imbalance', 'interior_duty', 'interior_imbalance', 'enthalpy_imbalance')})
    result['mode'], result['outer_index'] = ('temperature', 'model_h', 'true_h')[r.thermal_mode], r.thermal_outer_index
    result['temperature'] = tuple(_copy(value, shape) for value in r.temperature)
    for key in ('thermal_pressure', 'hv', 'rho_cp', 'conductivity', 'enthalpy'):
        if application_only and key in ('rho_cp', 'conductivity'):
            continue
        result[key] = tuple(_copy(value, shape) for value in getattr(r, key))
    if not application_only:
        result['inlet_capacity'] = tuple(_copy(value) for value in r.inlet_capacity)
    face_shapes = tuple(tuple(n+int(d==axis) for d,n in enumerate(shape)) for axis in range(3))
    for key in ('mass', 'face_velocity'):
        result[key] = tuple(tuple(_copy(value, sh) for value,sh in zip(side,face_shapes)) for side in getattr(r,key))
    result['flow'] = []
    for f in r.flow:
        if not f.widths[0].size:
            result['flow'].append(None)
            continue
        flow = dict(widths=tuple(_copy(value) for value in f.widths), pressure_reference=f.pressure_reference)
        nx, ny, nz = fshape = tuple(len(w) for w in flow['widths'])
        sizes = {key:fshape for key in _FLOW_ARRAYS}
        for axis, names in enumerate((('u','d_u'),('v','d_v'),('w','d_w'))):
            for key in names:
                sizes[key] = tuple(n+int(d==axis) for d,n in enumerate(fshape))
        for key in ('inlet_velocity','inlet_opening','outlet_opening','fixed_inlet_massflux'):
            sizes[key] = (nx,nz)
        sizes['outlet_u_fraction'], sizes['outlet_w_fraction'] = (nx+1,nz),(nx,nz+1)
        for key in ('pressure_real','density_real','speed_real'):
            sizes[key] = shape
        application_arrays = ('permeability', 'forchheimer', 'pressure', 'pressure_real',
                              'speed_real', 'inlet_opening', 'outlet_opening')
        audit_arrays = ('u', 'v', 'w', 'density', 'epsilon') if emit_audit else ()
        flow.update({key:_copy(getattr(f,key),sizes[key]) for key in _FLOW_ARRAYS
                     if not application_only or key in application_arrays + audit_arrays})
        flow['velocity_real'] = tuple(_copy(value,shape) for value in f.velocity_real)
        if not application_only:
            flow['face_velocity_real'] = tuple(_copy(value,sh) for value,sh in zip(f.face_velocity_real,face_shapes))
        for key in (('legacy',) if application_only else ('legacy','local_mass','global_mass','momentum')):
            flow[key] = _copy(getattr(f,key))
        if flow.get('momentum') is not None:
            flow['momentum'] = flow['momentum'].reshape(-1,11)
        last = f.last
        pressure = {name:getattr(last.pressure,name) for name,_ in last.pressure._fields_}
        flow['last'] = dict(exit_reason=_STOPS.get(last.stop,'ongoing'), converged=bool(last.converged),
            post_closure_measured=bool(last.post_closure_measured), post_closure_certified=bool(last.post_closure_certified),
            iterations=last.iterations, pressure_clip_hits=last.pressure_clip_hits, post_closure_rejections=last.post_closure_rejections,
            final_res=last.legacy_residual, res_norm_ref=last.legacy_reference,
            final_res_mom=last.momentum.maximum, final_res_mass_local=last.mass.local_residual,
            final_res_mass_global=last.mass.global_residual, outlet_backflow_frac=last.mass.backflow_fraction,
            pressure={name:value.decode() if isinstance(value,bytes) else value for name,value in pressure.items()})
        history = []
        for i in range(f.pressure_iteration_count):
            p=f.pressure_iterations[i];row=dict(stage=p.stage.decode(),anchor_Pa=p.anchor)
            for source,key in (('estimate','estimate_Pa2'),('relative_error','relative_error'),('target','target_Pa2'),('step_fraction','step_fraction')):
                if getattr(p,'has_'+source):
                    row[key]=getattr(p,source)
            if p.method:
                row['method']=p.method.decode()
            history.append(row)
        flow['pressure_iterations']=history;flow['inlet_pressure']=_pressure(f.inlet_pressure)
        if flow['inlet_pressure'] is not None:
            flow['inlet_pressure']['iterations']=history
        b=f.bootstrap
        flow['bootstrap']=None if not b.available else dict(applied=bool(b.applied),coarse_converged=bool(b.converged),
            coarse_iters=b.iterations,coarse_shape=tuple(b.shape),coarse_residual=b.residual,reason=b.reason.decode())
        a=f.anderson
        flow['anderson']=None if not a.available else dict(applied=a.applied,rejected=a.rejected,resets=a.resets,
                                                          residuals=[] if not a.residuals.size else _copy(a.residuals).tolist())
        result['flow'].append(flow)
    result['model_h'] = _model_info(r.model_h,shape,include_faces=True) if r.has_model_h else None
    result['true_h'] = _enthalpy_info(r.true_h,settings) if r.has_true_h else None
    if r.has_true_h:
        true_h=result['true_h']
        true_h['_native_state']=dict(h_A=result['enthalpy'][0],h_B=result['enthalpy'][1],
            h_in_A=r.true_h.inlet_enthalpy[0],h_in_B=r.true_h.inlet_enthalpy[1],
            mass_flux_A=result['mass'][0],mass_flux_B=result['mass'][1])
        used=[s for s,flag in zip('AB',r.true_h.used_bicubic) if flag]
        if used:
            true_h['_native_state']['sco2_enthalpy_eos']=dict(algorithm='bicubic_iteration_heos_polish_v2',
                iteration_backend='BICUBIC&HEOS',final_backend='HEOS',transport_backend='HEOS',
                coolprop_version=r.true_h.coolprop_version.decode(),sides=used,heos_polish=bool(r.true_h.heos_polish))
    result['staggered'] = []
    for p in r.staggered:
        result['staggered'].append(None if not p.available else dict(skipped=bool(p.skipped),used_bordered_lu=bool(p.used_bordered_lu),
            cg_iterations=p.cg_iterations,rhs_mean=p.rhs_mean,residual_relative=p.residual_relative,
            residual_available=bool(p.residual_available),residual_cells=_copy(p.residual_cells,shape),
            residual_sum=p.residual_sum,residual_max=p.residual_max,exchange=p.exchange,global_ratio=p.global_ratio,cell_ratio=p.cell_ratio))
    result['outer'] = []
    for i in range(r.outer_count):
        h=r.outer[i]
        row=dict(outer=h.outer_index,iters=h.thermal_iterations,residual=h.thermal_residual,converged=bool(h.thermal_converged),
                 coupling_converged=bool(h.coupling_converged),temperature_change=dict(zip(('Ta','Tb','Ts'),h.temperature_change)),
                 inlet_pressure=tuple(_pressure(p) for p in h.inlet_pressure),pressure_reference=list(h.pressure_reference),
                 pressure_range=[list(p) for p in h.pressure_range])
        if h.startup_total_iterations:
            row['coupling_startup']=dict(rejected_attempts=[dict(iterations=h.rejected_startup_iterations[k],
                reason=h.rejected_startup_reasons[k].decode()) for k in range(h.rejected_startup_count)],
                total_iterations=h.startup_total_iterations,iteration_budget=settings.thermal_iterations)
        if h.has_model_h:
            info=_model_info(h.model_h,shape,include_faces=False)
            row['energy_finishing_checks']=info['energy_finishing_checks']
            row['model_h_balance']=dict(info['model_h_balance'],outer_index=h.outer_index,converged=bool(h.thermal_converged),iterations=h.thermal_iterations)
        if h.has_true_h:
            row['true_h_info']=_enthalpy_info(h.true_h,settings)
        result['outer'].append(row)
    result['simple_failures']=[r.simple_failures[i].decode() for i in range(r.simple_failure_count)]
    result['warnings']=[r.warnings[i].decode() for i in range(r.warning_count)]
    result['envelope_reasons']=[r.envelope_reasons[i].decode() for i in range(r.envelope_reason_count)]
    result['nu_observations']={label:copy_nu_observation(n,shape) for label,n in zip('AB',r.nu_observations)}
    result['range_observations']=copy_range_observations(r.range_observations,r.range_observation_count)
    result['final_conductivity']=tuple(_copy(v,shape) if emit_audit else None for v in r.final_conductivity)
    result['final_rho_cp']=tuple(_copy(v,shape) if emit_audit else None for v in r.final_rho_cp)
    result['inlet_cp']=list(r.inlet_cp)
    return result


def run_case(case, control=RunControl()):
    from .full_3d_capture import capture_result
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    if control.backend != 'cpp':
        raise ValueError('full native 3D requires backend=cpp')
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    control.check_cancelled()
    cfg,p=build_execution_inputs(case)
    driver=NativeFull3DDriver(control.native_library, table_directory=getattr(control,'native_table_directory',None))
    r=driver._run_prepared(cfg,p,control,application_only=True)
    control.check_cancelled()
    return capture_result(case, cfg, p, r, driver.abi)
