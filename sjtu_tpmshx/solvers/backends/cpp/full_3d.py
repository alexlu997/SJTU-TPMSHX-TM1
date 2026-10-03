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
from .model_h import _Result as _ModelResult, _volume_info
from .enthalpy import _Result as _EnthalpyResult, _result_info as _enthalpy_result_info
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
        control.check_cancelled()
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
        c.refined_port_energy = bool(cfg.get('port_wall_refine', False));c.red_black_energy = int(np.prod(shape)>30000)
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
        c.enthalpy_iterations, c.enthalpy_sweeps = _count(cfg.get('ltne_enthalpy_outer',1500)), _count(cfg.get('ltne_enthalpy_nsweep',25),zero=True)
        c.enthalpy_omega, c.enthalpy_update_tolerance = cfg.get('ltne_enthalpy_omega',.6), cfg.get('ltne_enthalpy_tol',1e-3)
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
            detached=_detach(result, shape, c, emit_audit=bool(cfg.get('_emit_audit',False)))
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


def _detach(r, shape, settings, *, emit_audit=False):
    result = {name: getattr(r, name) if name == 'stop' else bool(getattr(r, name)) for name in _FLAGS}
    result.update({name: list(getattr(r, name)) for name in _PAIRS})
    result.update({name: getattr(r, name) for name in ('energy_imbalance', 'interior_duty', 'interior_imbalance', 'enthalpy_imbalance')})
    result['mode'], result['outer_index'] = ('temperature', 'model_h', 'true_h')[r.thermal_mode], r.thermal_outer_index
    result['temperature'] = tuple(_copy(value, shape) for value in r.temperature)
    for key in ('thermal_pressure', 'hv', 'rho_cp', 'conductivity', 'enthalpy'):
        result[key] = tuple(_copy(value, shape) for value in getattr(r, key))
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
        flow.update({key:_copy(getattr(f,key),sizes[key]) for key in _FLOW_ARRAYS})
        flow['velocity_real'] = tuple(_copy(value,shape) for value in f.velocity_real)
        flow['face_velocity_real'] = tuple(_copy(value,sh) for value,sh in zip(f.face_velocity_real,face_shapes))
        for key in ('legacy','local_mass','global_mass','momentum'):
            flow[key] = _copy(getattr(f,key))
        if flow['momentum'] is not None:
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
    from uuid import uuid4
    from sjtu_tpmshx.domain.field_result import FieldResult
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    if control.backend != 'cpp':
        raise ValueError('full native 3D requires backend=cpp')
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    cfg,p=build_execution_inputs(case)
    driver=NativeFull3DDriver(control.native_library, table_directory=getattr(control,'native_table_directory',None))
    r=driver.run_prepared(cfg,p,control)
    control.check_cancelled()
    fields=dict(zip(('Ta','Tb','Ts'),r['temperature']))
    fields.update(h_vA=r['hv'][0],h_vB=r['hv'][1],K_ss=np.asarray(p['design']['K_ss']))
    for s,label in enumerate('AB'):
        if r['thermal_pressure'][s] is not None:
            fields['P_thermal_'+label]=r['thermal_pressure'][s]
    display_units={}
    for name in ('Ta','Tb','Ts'):
        fields[name+'_display']=fields[name];display_units[name+'_display']='K'
    pressure,report={},{}
    for s,label in enumerate('AB'):
        f=r['flow'][s]
        if f is None:
            continue
        axis=case.parameters['prepared']['axes'][label]
        # Shape/axis restoration only. All values have already been solved.
        gauge=f['pressure'].transpose(axis['solver_to_real_perm'])
        if axis['is_reverse']:
            gauge=np.flip(gauge,axis=axis['stream_real_axis'])
        fields['P_gauge_'+label]=np.ascontiguousarray(gauge)
        fields['P_report_'+label]=f['pressure_real']
        fields['P_f'+label+'_display']=f['pressure_real'];display_units['P_f'+label+'_display']='Pa'
        for name,value in zip(('uc','vc','wc'),f['velocity_real']):
            fields[name+label]=value;display_units[name+label]='m/s'
        fields['vmag_'+label]=f['speed_real'];display_units['vmag_'+label]='m/s'
        pressure[label]=dict(P=f['pressure'],dx=f['widths'][0],dy=f['widths'][1],dz=f['widths'][2],
            inlet_frac=f['inlet_opening'],outlet_frac=f['outlet_opening'],P_ref_abs=f['pressure_reference'],axis_map=axis,
            unit='Pa',axes=('solver_x','solver_y','solver_z'),stream_axis=1,state='final SIMPLE flow',method='face_extrapolation_v1')
        report[label]=dict(direction=cfg['fluid_'+label+'_cfg']['dir'])
    field_metadata={key:dict(unit='K' if key in ('Ta','Tb','Ts') else 'Pa' if key.startswith('P_') else
        'W/(m3 K)' if key.startswith('h_v') else 'W/(m K)',axes=('x','y','z'),location='cell',
        state='final SIMPLE flow' if key.startswith(('P_report','P_gauge')) else 'last thermal solve') for key in fields}
    for name,unit in display_units.items():
        field_metadata[name]=dict(unit=unit,axes=('x','y','z'),location='cell',state='display' if name.endswith('_display') else 'final flow/report')
    from sjtu_tpmshx.df_surrogate.experimental_correction import cfd_metadata
    df_metadata=dict(mode=cfg.get('df_mode','cfd_smooth'))
    for label,f in zip('AB',r['flow']):
        if f is None:
            df_metadata[label]=None
        else:
            base=cfd_metadata(p['design']['K_m2'],p['design']['cF_per_m'])
            applied=cfd_metadata(f['permeability'],f['forchheimer'])
            df_metadata[label]=dict((cfg.get('df_application') or {}).get(label,{}) if df_metadata['mode']=='experimental' else base,
                base_K=base['base_K'],base_cF=base['base_cF'],applied_K=applied['applied_K'],applied_cF=applied['applied_cF'])
    ltne=[]
    for h in r['outer']:
        row={key:h[key] for key in ('outer','iters','converged','residual')}
        for key in ('coupling_startup','energy_finishing_checks','model_h_balance'):
            if key in h:
                row[key]=h[key]
        if 'true_h_info' in h:
            info=h['true_h_info']
            row['true_h_balance']=dict(Q_A=info['Q_A'],Q_B=info['Q_B'],units='W',outer_index=h['outer'],
                converged=h['converged'],iterations=h['iters'],residual=h['residual'],
                pressure_source='completed SIMPLE P_ref_abs + gauge',P_in_A_Pa=cfg['P_inA'],P_in_B_Pa=cfg['P_inB'],
                P_A_offset_Pa=h['pressure_reference'][0],P_B_offset_Pa=h['pressure_reference'][1],
                P_A_range_Pa=h['pressure_range'][0],P_B_range_Pa=h['pressure_range'][1])
            row['true_h_balance'].update({key:info[key] for key in ('exit_reason','enthalpy_clip_counts','effective_settings',
                'coupled_energy_balance','equation_energy_balance') if key in info})
        ltne.append(row)
    final_info=ltne[-1]
    strict={}
    for s,label in enumerate('AB'):
        for suffix in ('','_cellmax'):
            value=None
            if r['model_h'] is not None:
                value=r['model_h']['eps_'+label+'_strict'+suffix]
            elif r['mode']=='temperature' and r['staggered'][s] is not None and r['staggered'][s]['residual_available']:
                value=r['staggered'][s]['cell_ratio' if suffix else 'global_ratio']
            strict['eps_'+label+'_strict'+suffix]=value
    diagnostics=dict(dP=r['pressure_drop'][0],dP_A=r['pressure_drop'][0],dP_B=r['pressure_drop'][1],
        Lx=cfg['L'],Ly=cfg['H'],Lz=cfg['Lz'],Q=r['duty'][0],Q_total=r['duty'][0],
        Q_enthalpy_A=r['duty'][0],Q_enthalpy_B=r['duty'][1],Q_solid_B=r['solid_exchange'][1],
        mass_flow_A_kg_s=r['inlet_mass'][0],mass_flow_B_kg_s=r['inlet_mass'][1] if r['flow'][1] else None,
        u_A=cfg['u_A'],T_in=cfg['T_inA'],T_A_out=r['outlet_temperature'][0],T_B_out=r['outlet_temperature'][1] if r['flow'][1] else None,
        T_out_A=r['outlet_temperature'][0],T_out_B=r['outlet_temperature'][1] if r['flow'][1] else None,
        dir_A=cfg['fluid_A_cfg']['dir'],dir_B=cfg['fluid_B_cfg']['dir'] if r['flow'][1] else None,
        Q_sA=r['solid_exchange'][0],Q_sB=r['solid_exchange'][1],Q_net=sum(r['solid_exchange']),
        energy_imbalance_rel=r['energy_imbalance'],mass_imbalance_rel_A=r['mass_imbalance'][0],mass_imbalance_rel_B=r['mass_imbalance'][1],
        Q_AB_imbalance_rel=r['enthalpy_imbalance'],Q_sA_interior=r['interior_exchange'][0],Q_sB_interior=r['interior_exchange'][1],
        Q_interior=r['interior_duty'],AB_interior=r['interior_imbalance'],**strict,_ltne_info=ltne,
        _max_outer=p['max_outer'] if p['max_outer'] is not None else 12,_ltne_max_iter=p['ltne_max_iter'],
        _needs_full_validate=bool(p.get('compact',False) and not all(h['converged'] for h in ltne)),
        sco2_nu_observations=r['nu_observations'],df_metadata=df_metadata,
        solver_converged=r['converged'],envelope_valid=r['envelope_ok'],envelope_reasons=r['envelope_reasons'],
        envelope_warnings=list(r['warnings']),p_clip_hits=sum(f['last']['pressure_clip_hits'] for f in r['flow'] if f is not None))
    pressure_states={label:None if f is None else f['inlet_pressure'] for label,f in zip('AB',r['flow'])}
    for label in 'AB':
        state=pressure_states[label]
        diagnostics['P_in_realized_'+label]=np.nan if state is None else state['realized_Pa']
        diagnostics['P_in_shoot_resid_'+label]=np.nan if state is None else state['relative_error']
    def simple_detail(f):
        if f is None:
            return None
        last=f['last']
        return dict(**{key:last[key] for key in ('exit_reason','final_res','res_norm_ref','final_res_mom',
            'final_res_mass_local','final_res_mass_global','outlet_backflow_frac')},convergence_mode='f2',iterations=len(f['legacy']))
    transient=[name for name in r['simple_failures'] if name.startswith(('A@init','B@init'))]
    final=[name for name in r['simple_failures'] if name not in transient]
    if not r['simple_ok']:
        diagnostics['envelope_warnings'].append('SIMPLE momentum solve did not converge in the FINAL solve: '
            + ', '.join(final or r['simple_failures'])
            + ' — the reported velocity/pressure field is not converged (inspect the F2 residuals and iteration budget).')
    elif transient:
        diagnostics['envelope_warnings'].append('SIMPLE momentum solve stalled in a TRANSIENT (superseded) solve: '
            + ', '.join(transient) + ' — the cold-start field was re-solved by the outer loop and the '
            'reported field DID converge, so this is informational. It does flag a hard cold start (typically high u).')
    if not r['finite_fields']:
        diagnostics['envelope_warnings'].append('Non-finite (NaN/inf) cells in the converged temperature or '
            'velocity field — the result is not physical; solver_converged is forced False.')
    diagnostics['envelope_warnings']=list(dict.fromkeys(diagnostics['envelope_warnings']))
    diagnostics['convergence_detail']=dict(inlet_pressure=pressure_states,
        simple_A=simple_detail(r['flow'][0]),simple_B=simple_detail(r['flow'][1]),simple_nonconv=r['simple_failures'],
        outer_dT=[h['temperature_change'] for h in r['outer']],outer_converged=r['outer_ok'],outer_iters=len(r['outer']),
        outer_hit_cap=not r['outer_ok'],simple_ok=r['simple_ok'],simple_nonconv_final=final,simple_nonconv_transient=transient,
        simple_exit_A=r['flow'][0]['last']['exit_reason'],simple_exit_B=None if r['flow'][1] is None else r['flow'][1]['last']['exit_reason'],
        ltne_ok=r['thermal_ok'],fields_finite=r['finite_fields'],envelope_ok=r['envelope_ok'],
        outer_anderson=None if not cfg.get('outer_anderson',False) else {label:None if f is None else f['anderson'] for label,f in zip('AB',r['flow'])})
    for mode in ('true_h','model_h'):
        key=mode+'_balance'
        diagnostics[key]=dict(final_info[key],outer_converged=r['outer_ok'],post_after_last_thermal=r['post_after_last_thermal'],
            state='last true-h solve, before any final post update' if mode=='true_h' else 'last model-h thermal solve, before any final post update') if key in final_info else None
    diagnostics['native_full_3d']=dict(abi=driver.abi,numerical_driver='cpp',
        coarse_bootstrap={label:None if f is None else f['bootstrap'] for label,f in zip('AB',r['flow'])},
        pressure={label:None if f is None else f['last']['pressure'] for label,f in zip('AB',r['flow'])})
    diagnostics['coarse_bootstrap_trace'] = r['bootstrap_trace']
    model_metadata=dict(case.metadata['model_metadata'])
    true_h=None if r['true_h'] is None else r['true_h']['_native_state']
    if true_h and 'sco2_enthalpy_eos' in true_h:
        model_metadata['sco2_enthalpy_eos']=true_h['sco2_enthalpy_eos']
    emit_audit=bool(cfg.get('_emit_audit',False))
    if emit_audit:
        from sjtu_tpmshx.solvers.simple_solver_3d import _build_outlet_frac_taper
        for s,label in enumerate('AB'):
            f=r['flow'][s];bc=cfg['fluid_'+label+'_cfg'];axes=p['axes'][label]
            outlet_coeff=None if f is None else f['outlet_opening']
            if f is not None and cfg['fluid_type_'+label]!='sco2':
                # Legacy audit-only display weight; raw opening owns every solved face.
                outlet_coeff=outlet_coeff*_build_outlet_frac_taper(*outlet_coeff.shape)
            diagnostics['_audit_s'+label+'_face']=None if f is None else dict(
                u=f['u'],v=f['v'],w=f['w'],rho=f['density'],outlet_coeff=outlet_coeff,
                inlet_frac=f['inlet_opening'],outlet_frac=f['outlet_opening'],eps=f['epsilon'],
                dx=f['widths'][0],dy=f['widths'][1],dz=f['widths'][2],dir_real=bc['dir'],solver_to_real_perm=axes['solver_to_real_perm'])
            for key,value in (('m_dot_'+label+'_simple',r['inlet_mass'][s]),('cp_'+label,r['inlet_cp'][s]),
                ('T_in'+label,cfg['T_in'+label]),('u_'+label,cfg['u_'+label]),('f'+label,bc)):
                diagnostics['_audit_'+key]=value if f is not None else None
            diagnostics['_audit_P_in'+label]=cfg['P_in'+label]
        diagnostics['_audit_eps']=float(cfg['eps'])
        diagnostics['_audit_m_dot_B_phys_in']=r['physical_mass_in'][1] if r['flow'][1] else None
        diagnostics['_audit_m_dot_B_phys_out']=r['physical_mass_out'][1] if r['flow'][1] else None
    return FieldResult(result_id=str(uuid4()),case_id=case.case_id,backend_id='cpp',backend_version='full_3d_v1',grid=case.grid,
        fields=fields,field_metadata=field_metadata,model_refs=case.model_refs,
        boundary_fluxes=dict(mass_A=None if r['mass'][0][0] is None else r['mass'][0],mass_B=None if r['mass'][1][0] is None else r['mass'][1],
            mass_unit='kg/s',mass_axes=('x-face','y-face','z-face'),mass_sign='positive along physical coordinate axis',state='last thermal input',
            model_h=None if r['model_h'] is None else r['model_h']['_native_model_h'],true_h=true_h,report=report,
            face_velocity_A=r['face_velocity'][0],face_velocity_B=r['face_velocity'][1] if r['flow'][1] else None),
        pressure_evidence=pressure,run_status=dict(execution='completed',converged=r['converged'],outer_index=r['outer_index']),
        metadata=dict(dimension=3,quantity_basis='total',thermal_mode=r['mode'],parameters=case.parameters,design_fields=case.design_fields,
            design_mode=case.metadata['design_mode'],model_metadata=model_metadata,notices=case.metadata['notices'],
            application=dict(coeffs=dict(K_ffA=r['final_conductivity'][0],K_ffB=r['final_conductivity'][1],
                K_ss=np.asarray(p['design']['K_ss']) if emit_audit else None),
                props=dict(rho_cp_A=r['final_rho_cp'][0],rho_cp_B=r['final_rho_cp'][1],u_A_in_mps=cfg['u_A'],T_in_A_K=cfg['T_inA'])),
            diagnostics=diagnostics,df_metadata=df_metadata,model_roles=case.metadata['model_roles'],
            reporting_reference={key:diagnostics[key] for key in ('Q','dP_A','dP_B','T_out_A','T_out_B')}))
