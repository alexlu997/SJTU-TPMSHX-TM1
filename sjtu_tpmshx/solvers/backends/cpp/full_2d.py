"""Prepared rectangular 2D binding; the complete numerical loop is native."""
import ctypes as ct
from .property_sampling import sampling_query, copy_sampling
from .enthalpy import _update_scale_query, _copy_update_scale
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import validate_simple_velocity_relaxation
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_environment import run_environment
from sjtu_tpmshx.models.envelope import ChokedFlowError
from sjtu_tpmshx.models.fluid_props import WaterStateError
from sjtu_tpmshx.models.grid import _port_overlap_1d, _port_fractions_1d
from sjtu_tpmshx.domain.run_environment import require_f2_mode
from ._simple_abi import _F2
from .physical_ledger import HeatLedger2D, heat_ledger_query, copy_heat_ledger
from .simple_2d import _Result as _SimpleResult, _result_dict
from .model_h import _Array, _Result as _ModelResult, _plane_info, _model_h_algorithm
from .temperature_evidence import TemperatureEvidence2D, copy_temperature_evidence
from .model_h import _IterationOptions, _iteration_options, _iteration_query, _copy_iteration_records
from .enthalpy import _Result as _EnthalpyResult
from .enthalpy import (_EnergyOptions, _EnergyOptionsV2, _EnergyResult, _energy_options,
                       _energy_algorithm_query, _energy_result_info, _energy_native_state,
                       _FullEnergyEffectiveSettings, _full_enthalpy_defaults, _full_enthalpy_info,
                       _executed_energy_settings)
from .closure_evidence import NuObservation, RangeObservation, copy_nu_observation, copy_range_observations, last_range_query, copy_last_ranges


class _Side(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('fluid', 'direction', 'uniform_inlet')]
    _fields_ += [(n, ct.c_double) for n in ('inlet_temperature', 'inlet_pressure', 'inlet_velocity',
        'initial_viscosity', 'seed_permeability', 'seed_forchheimer', 'inlet_lo', 'inlet_hi',
        'outlet_lo', 'outlet_hi', 'side_area_density', 'side_hydraulic_diameter',
        'reference_area_density', 'reference_hydraulic_diameter')]


class _Config(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('topology', 'thermal_mode', 'asymmetric', 'have_solid_seed',
                                         'pressure_shooting', 'red_black', 'spatial_geometry')]
    _fields_ += [('sides', _Side*2)]
    _fields_ += [(n, ct.c_double) for n in ('reference_cell_length', 'reference_porosity', 'split_a',
                                          'sco2_nu_multiplier', 'solid_seed')]
    _fields_ += [(n, ct.c_size_t) for n in ('simple_iterations', 'simple_sweeps', 'outer_iterations',
                                          'thermal_iterations', 'thermal_chunk')]
    _fields_ += [(n, ct.c_double) for n in ('alpha_velocity', 'alpha_pressure', 'alpha_density',
                                          'gas_constant', 'cf_anisotropy')]
    _fields_ += [('massflux_inlet', ct.c_uint32), ('close_outlet_on_exit', ct.c_uint32), ('f2', _F2)]
    _fields_ += [(n, ct.c_double) for n in ('outer_temperature_tolerance', 'outer_density_tolerance',
        'outer_relaxation', 'thermal_q_tolerance', 'enthalpy_update_tolerance')]
    _fields_ += [('envelope_mode', ct.c_char_p), ('table_directory', ct.c_char_p)]


class _EnergyControl(ct.Structure):
    _fields_ = [('max_iterations', ct.c_size_t), ('sweeps', ct.c_size_t),
                ('omega', ct.c_double), ('update_tolerance', ct.c_double),
                ('energy', _EnergyOptionsV2)]


class _Pressure(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('passed', ct.c_uint32)]
    _fields_ += [(n, ct.c_double) for n in ('specified_Pa', 'realized_Pa', 'outlet_Pa', 'outlet_gauge_Pa',
                                          'minimum_Pa', 'relative_error', 'relative_tolerance')]
    _fields_ += [('definition', ct.c_char_p)]


class _PressureIteration(ct.Structure):
    _fields_ = [('stage', ct.c_char_p), ('anchor_Pa', ct.c_double)]
    _fields_ += [(n, ct.c_uint32) for n in ('have_estimate', 'have_relative_error', 'have_target', 'have_step')]
    _fields_ += [(n, ct.c_double) for n in ('estimate_Pa2', 'relative_error', 'target_Pa2', 'step_fraction')]
    _fields_ += [('method', ct.c_char_p)]


_FLOW_ARRAYS = ('dx', 'dy', 'u', 'v', 'pressure', 'pressure_correction', 'd_u', 'd_v', 'density',
    'inlet_velocity', 'viscosity', 'effective_viscosity', 'temperature', 'epsilon', 'uc', 'vc',
    'absolute_pressure', 'mass_x', 'mass_y')


class _Flow(ct.Structure):
    _fields_ = [(n, _Array) for n in _FLOW_ARRAYS]
    _fields_ += [('reference_pressure', ct.c_double), ('taper_flux_scale', ct.c_double), ('result', _SimpleResult),
        ('history', _Array*4), ('inlet_pressure', _Pressure),
        ('pressure_iterations', ct.POINTER(_PressureIteration)), ('pressure_iteration_count', ct.c_size_t),
        ('envelope_valid', ct.c_uint32), ('envelope_reasons', ct.POINTER(ct.c_char_p)), ('envelope_reason_count', ct.c_size_t)]


class _Thermal(ct.Structure):
    _fields_ = [('nx', ct.c_size_t), ('ny', ct.c_size_t), ('mode', ct.c_uint32), ('stop', ct.c_uint32),
        ('iterations', ct.c_size_t), ('residual', ct.c_double), ('q_b', ct.c_double),
        ('dx', _Array), ('dy', _Array), ('temperature', _Array*3)]
    _fields_ += [(n, _Array*2) for n in ('hv', 'conductivity', 'pressure', 'rho_cp', 'mass_x', 'mass_y', 'inlet_capacity')]
    _fields_ += [('solid_conductivity', _Array), ('enthalpy', _Array*2), ('uc', _Array*2), ('vc', _Array*2),
        ('epsilon', _Array), ('inlet_profile', _Array*2), ('outlet_profile', _Array*2),
        ('model_h', _ModelResult), ('true_h', _EnthalpyResult)]


class _Outer(ct.Structure):
    _fields_ = [('iteration', ct.c_size_t), ('thermal_iterations', ct.c_size_t),
        ('thermal_converged', ct.c_uint32), ('outer_converged', ct.c_uint32),
        ('relative_density_change', ct.c_double*2), ('temperature_change', ct.c_double*3)]


_FLAGS = ('cancelled', 'converged', 'outer_converged', 'post_after_last_thermal', 'simple_ok',
          'thermal_ok', 'envelope_ok', 'pair_balance_ok', 'model_balance_ok')
_FINE_FLAGS = ('have_fine', 'fine_accepted', 'fine_extrapolated', 'fine_warning')


class _Result(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in _FLAGS]
    _fields_ += [('iterations', ct.c_size_t), ('flow', _Flow*2), ('main', _Thermal), ('fine', _Thermal)]
    _fields_ += [(n, ct.c_uint32) for n in _FINE_FLAGS]
    _fields_ += [('fine_duty', ct.c_double*2), ('extrapolated_duty', ct.c_double*2)]
    _fields_ += [(n, _Array*2) for n in ('density', 'viscosity', 'rho_cp')]
    _fields_ += [('outer_history', ct.POINTER(_Outer)), ('outer_history_count', ct.c_size_t)]
    _fields_ += [(n, ct.c_double*2) for n in ('pressure_drop', 'outlet_temperature', 'inlet_mass', 'duty')]
    _fields_ += [(n, ct.c_double) for n in ('q_total', 'q_solid', 'energy_imbalance')]
    _fields_ += [('nu_observations', NuObservation*2), ('range_observations', ct.POINTER(RangeObservation)),
                ('range_observation_count', ct.c_size_t)]
    _fields_ += [('owner', ct.c_void_p)]


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_size_t)
_Residual = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_size_t, ct.c_double)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('residual', _Residual), ('context', ct.c_void_p)]


class _EnergyState(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('energy', _EnergyResult),
                ('actual_conductivity', _Array * 2), ('boundary_power', (_Array * 6) * 2)]


class _EnergyEvidence(ct.Structure):
    _fields_ = [('main', _EnergyState), ('fine', _EnergyState),
                ('outer', ct.POINTER(_EnergyResult)), ('outer_count', ct.c_size_t)]


def _copy(view, shape=None):
    if not view.size:
        return None
    value = np.ctypeslib.as_array(view.data, (view.size,)).copy()
    return value if shape is None else value.reshape(shape)


def _flow(f, physical_shape):
    nx, ny = f.dx.size, f.dy.size
    out = {}
    for name in _FLOW_ARRAYS:
        shape = (nx+1, ny) if name in ('u', 'd_u') else (nx, ny+1) if name in ('v', 'd_v') else (nx, ny)
        if name in ('dx', 'dy', 'inlet_velocity'):
            shape = None
        elif name in ('uc', 'vc', 'absolute_pressure'):
            shape = physical_shape
        elif name in ('mass_x', 'mass_y'):
            shape = tuple(n + int(axis == (name == 'mass_y')) for axis, n in enumerate(physical_shape))
        out[name] = _copy(getattr(f, name), shape)
    out.update(reference_pressure=f.reference_pressure, taper_flux_scale=f.taper_flux_scale,
        result=_result_dict(f.result, 1),
        history={name: _copy(value, (-1, 8) if name == 'momentum' else None)
                 for name, value in zip(('legacy', 'local_mass', 'global_mass', 'momentum'), f.history)},
        envelope_valid=bool(f.envelope_valid),
        envelope_reasons=[f.envelope_reasons[i].decode() for i in range(f.envelope_reason_count)])
    iterations = []
    for i in range(f.pressure_iteration_count):
        p = f.pressure_iterations[i]
        row = dict(stage=p.stage.decode(), anchor_Pa=p.anchor_Pa)
        for flag, name in zip(('have_estimate', 'have_relative_error', 'have_target', 'have_step'),
                              ('estimate_Pa2', 'relative_error', 'target_Pa2', 'step_fraction')):
            if getattr(p, flag):
                row[name] = getattr(p, name)
        if p.method:
            row['method'] = p.method.decode()
        iterations.append(row)
    out['pressure_iterations'] = iterations
    p = f.inlet_pressure
    out['inlet_pressure'] = None
    if p.available:
        out['inlet_pressure'] = {name: getattr(p, name) for name, _ in _Pressure._fields_[2:-1]}
        out['inlet_pressure'].update(passed=bool(p.passed), definition=p.definition.decode(), iterations=iterations)
    return out


def _thermal(t, actual, abi):
    shape = (t.nx, t.ny)
    out = dict(shape=shape, mode=('temperature', 'model_h', 'true_h')[t.mode], stop=t.stop,
               iterations=t.iterations, residual=t.residual, q_b=t.q_b)
    for name in ('dx', 'dy', 'epsilon', 'solid_conductivity'):
        out[name] = _copy(getattr(t, name), shape if name not in ('dx', 'dy') else None)
    for name in ('temperature', 'hv', 'conductivity', 'pressure', 'rho_cp', 'enthalpy', 'uc', 'vc',
                 'mass_x', 'mass_y', 'inlet_capacity', 'inlet_profile', 'outlet_profile'):
        extent = shape
        if name in ('mass_x', 'mass_y'):
            extent = tuple(n+int(axis == (name == 'mass_y')) for axis, n in enumerate(shape))
        elif name in ('inlet_capacity', 'inlet_profile', 'outlet_profile'):
            extent = None
        out[name] = [_copy(value, extent) for value in getattr(t, name)]
    out['model_h'], out['true_h'] = None, None
    masses = list(zip(out['mass_x'], out['mass_y']))
    if t.mode == 1:
        out['model_h'] = _plane_info(t.model_h, shape, (out['dx'], out['dy']), masses)
        out['model_h']['energy_finishing_checks'] = [dict(iterations=t.model_h.finishing_checks[i].iterations,
            passed=bool(t.model_h.finishing_checks[i].gates[0]), equations_ok=bool(t.model_h.finishing_checks[i].gates[1]))
            for i in range(t.model_h.finishing_count)]
    elif t.mode == 2:
        h = t.true_h
        out['true_h'] = _full_enthalpy_info(h, actual, abi)
        mass3 = [(*[face[..., None] for face in pair], np.zeros((*shape, 2))) for pair in masses]
        out['true_h']['_native_state'] = state = dict(h_A=out['enthalpy'][0][..., None], h_B=out['enthalpy'][1][..., None],
            h_in_A=h.inlet_enthalpy[0], h_in_B=h.inlet_enthalpy[1], mass_flux_A=mass3[0], mass_flux_B=mass3[1])
        sides = [side for side, used in zip(('A', 'B'), h.used_bicubic) if used]
        if sides:
            state['enthalpy_eos'] = dict(algorithm='bicubic_iteration_heos_polish_v2',
                iteration_backend='BICUBIC&HEOS', final_backend='HEOS', transport_backend='HEOS',
                coolprop_version=h.coolprop_version.decode(), sides=sides, heos_polish=bool(h.heos_polish))
    return out


def _set_native_metadata(result, abi, algorithm, red_black):
    for stage in (result['main'], result['fine']):
        if stage is not None:
            actual = stage['temperature_evidence']['algorithm'] if 'temperature_evidence' in stage else algorithm
            stage['native_metadata'] = dict(abi=abi, algorithm=actual,
                red_black=bool(red_black and np.prod(stage['shape']) > 30000))
    result['native_metadata'] = result['main']['native_metadata']


class _FlowMethod(ct.Structure):
    _fields_ = [('algorithm', ct.c_char_p), ('iterations', ct.c_size_t),
                ('proposal_steps', ct.c_size_t), ('accepted_proposals', ct.c_size_t)]


class NativeFull2DDriver:
    def __init__(self, library, *, table_directory=None):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native full 2D library must be an absolute path')
        self.path = path.resolve(strict=True)
        if table_directory is not None and not Path(table_directory).is_absolute():
            raise ValueError('native full 2D table directory must be an absolute path')
        self.table_directory = None if table_directory is None else str(table_directory).encode()
        self.library = ct.CDLL(str(self.path))
        version = self.library.tpmshx_full_2d_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 2:
            raise ValueError(f'unsupported full 2D ABI {self.abi}; expected 2')
        self.call = self.library.tpmshx_solve_full_2d_v2
        dp, sp = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
        self.call.argtypes = [sp, ct.POINTER(dp), sp, ct.POINTER(_Config), ct.POINTER(_Callbacks),
                             ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int
        self.release = self.library.tpmshx_full_2d_release_v2
        self.release.argtypes, self.release.restype = [ct.POINTER(_Result)], None
        try:
            self.query_settings = self.library.tpmshx_full_2d_get_energy_effective_settings_v1
        except AttributeError as exc:
            raise ValueError('native full 2D library lacks executed settings; rebuild the library') from exc
        self.query_settings.argtypes = [ct.POINTER(_Result), ct.POINTER(_FullEnergyEffectiveSettings)]
        self.query_settings.restype = ct.c_int
        self.query_last_ranges = last_range_query(self.library, 2, _Result)
        self.query_heat_ledger = heat_ledger_query(self.library, 2, _Result)
        self.query_sampling = sampling_query(self.library, 2, _Result)
        self.query_update_scale = _update_scale_query(self.library, 2, _Result)
        self.query_model_h = _iteration_query(self.library, 2, _Result)
        self.query_flow_methods = self.library.tpmshx_full_2d_get_flow_methods_v1
        self.query_flow_methods.argtypes = [ct.POINTER(_Result), ct.POINTER(_FlowMethod)]
        self.query_flow_methods.restype = ct.c_int

    def run_prepared(self, cfg, prepared, control=RunControl(), *, resume_state=None, checkpoint=None, checkpoint_due=None):
        control.check_cancelled()
        shape, arrays, config = _pack(cfg, prepared, self.table_directory, self.library)
        solver = cfg['compute_cfg'].solver
        energy_control = None
        names = ('ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega',
                 'ltne_enthalpy_tol', 'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol')
        if solver.require_enthalpy_update_on_temperature or any(getattr(solver, name) is not None for name in names):
            if config.thermal_mode != 2:
                raise ValueError('explicit full 2D energy controls require the existing true-h route')
            energy = _energy_options(solver.enthalpy_algorithm, solver.enthalpy_temperature_tol_K)
            defaults = _full_enthalpy_defaults(self.library, 2, energy.algorithm,
                                               any(side.fluid == 1 for side in config.sides))
            values = [getattr(solver, name) if getattr(solver, name) is not None else getattr(defaults, field)
                      for name, field in zip(names, ('max_iterations', 'sweeps', 'omega', 'update_tolerance',
                                                    'coupled_energy_tolerance', 'equation_energy_tolerance'))]
            energy_control = _EnergyControl(*values[:4], _EnergyOptionsV2(
                energy.algorithm, energy.temperature_update_tolerance, *values[4:],
                solver.require_enthalpy_update_on_temperature))
        return self.solve(shape, arrays, config, control, energy_algorithm=solver.enthalpy_algorithm,
                          temperature_update_tolerance=solver.enthalpy_temperature_tol_K,
                          energy_control=energy_control, model_h_options=_iteration_options(vars(solver)),
                          resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)

    def solve(self, shape, arrays, config, control=RunControl(), *,
              energy_algorithm='temperature_sou', temperature_update_tolerance=1e-8, energy_control=None,
              model_h_options=None, resume_state=None, checkpoint=None, checkpoint_due=None):
        """Synchronous C call; detach all views before releasing their sole owner."""
        if len(shape) != 2 or len(arrays) != 29:
            raise ValueError('full 2D requires two extents and 29 prepared arrays')
        energy = _energy_options(energy_algorithm, temperature_update_tolerance)
        if energy_control is not None:
            energy = energy_control.energy
        thread_call = getattr(self.library, 'tpmshx_solve_full_2d_v6', None)
        if thread_call is None and control.cpu_threads is not None:
            raise ValueError('this retained native library has no CPU thread limit; leave cpu_threads unset')
        energy_call = energy_query = version_query = None
        entry_version = 2
        if model_h_options is not None:
            if energy_control is not None or config.thermal_mode == 2:
                raise ValueError('model-h iteration controls require an integral h(T) route')
            if thread_call is None:
                try:
                    energy_call = self.library.tpmshx_solve_full_2d_v5
                except AttributeError as exc:
                    raise ValueError('native full 2D library lacks model-h controls v5; rebuild the library') from exc
                energy_call.argtypes = [*self.call.argtypes[:4], ct.POINTER(_IterationOptions), *self.call.argtypes[4:]]
                energy_call.restype = ct.c_int
            entry_version = 5
        elif energy_control is not None:
            if thread_call is None:
                try:
                    energy_call = self.library.tpmshx_solve_full_2d_v4
                except AttributeError as exc:
                    raise ValueError('native full 2D library lacks explicit energy controls v4') from exc
                energy_call.argtypes = [*self.call.argtypes[:4], ct.POINTER(_EnergyControl), *self.call.argtypes[4:]]
                energy_call.restype = ct.c_int
            entry_version = 4
        elif energy.algorithm:
            if thread_call is None:
                try:
                    energy_call = self.library.tpmshx_solve_full_2d_v3
                except AttributeError as exc:
                    raise ValueError('native full 2D library lacks conservative energy v3') from exc
                energy_call.argtypes = [*self.call.argtypes[:4], ct.POINTER(_EnergyOptions), *self.call.argtypes[4:]]
                energy_call.restype = ct.c_int
            entry_version = 3
        if thread_call is not None:
            entry_version = 6
            thread_call.argtypes = [*self.call.argtypes[:4], ct.POINTER(_EnergyOptions),
                ct.POINTER(_EnergyControl), ct.POINTER(_IterationOptions), ct.c_size_t, *self.call.argtypes[4:]]
            thread_call.restype = ct.c_int
        if energy.algorithm:
            try:
                energy_query = self.library.tpmshx_full_2d_get_energy_evidence_v1
            except AttributeError as exc:
                raise ValueError(f'native full 2D library lacks conservative energy v{entry_version}') from exc
            version_query = _energy_algorithm_query(self.library)
            energy_query.argtypes = [ct.POINTER(_Result), ct.POINTER(_EnergyEvidence)]
            energy_query.restype = ct.c_int
        arrays = [np.require(np.asarray(x, dtype=np.float64), requirements=['C', 'A']) for x in arrays]
        errors = []

        @_Cancel
        def cancelled(_):
            if errors:
                return 1
            try:
                return int(bool(control.cancel_check())) if control.cancel_check is not None else 0
            except BaseException as error:
                errors.append(error)
                return 1

        @_Progress
        def progress(_, done, total):
            if errors:
                return
            try:
                control.report_progress(10 + int(80 * done / total))
                if control.iteration is not None:
                    control.iteration(f'iter {done + 1}/{total}')
                if control.outer_iteration is not None:
                    control.outer_iteration(done, total)
            except BaseException as error:
                errors.append(error)

        @_Residual
        def residual(_, side, iteration, value):
            if errors:
                return
            try:
                if control.residual is not None:
                    control.residual(('A', 'B')[side], iteration, value)
            except BaseException as error:
                errors.append(error)

        callbacks = _Callbacks(cancelled, progress, residual, None)
        dp = ct.POINTER(ct.c_double)
        pointers = (dp*len(arrays))(*(x.ctypes.data_as(dp) for x in arrays))
        sizes = (ct.c_size_t*len(arrays))(*(x.size for x in arrays))
        result, error = _Result(), ct.create_string_buffer(2048)
        try:
            args = ((ct.c_size_t*2)(*shape), pointers, sizes, ct.byref(config))
            tail = (ct.byref(callbacks), ct.byref(result), error, len(error))
            basic_energy = energy if energy_control is None and model_h_options is None else None
            if resume_state is not None or checkpoint is not None:
                from .full_2d_run import NativeFull2DRun
                with NativeFull2DRun(self.library, *args[:3], config, callbacks,
                        energy=basic_energy, energy_control=energy_control, model_h=model_h_options,
                        state=resume_state, cpu_threads=control.native_cpu_threads() if thread_call else None) as run:
                    while run.phase not in (3, 4):
                        phase = run.advance()
                        if errors:
                            raise errors[0]
                        if (checkpoint is not None and phase in (1, 2, 6, 7, 8)
                                and (checkpoint_due is None or checkpoint_due())):
                            checkpoint(run.snapshot())
                    result = run.take_result()
                status = 0
            elif thread_call:
                status = thread_call(*args, ct.byref(basic_energy) if basic_energy is not None else None,
                    ct.byref(energy_control) if energy_control is not None else None,
                    ct.byref(model_h_options) if model_h_options is not None else None,
                    control.native_cpu_threads(), *tail)
            else:
                options = model_h_options if model_h_options is not None else energy_control if energy_control is not None else energy
                status = energy_call(*args, ct.byref(options), *tail) if energy_call else self.call(*args, *tail)
            if errors:
                raise errors[0]
            if status:
                exception = {1: ValueError, 2: WaterStateError, 3: FloatingPointError, 4: ChokedFlowError}.get(status, RuntimeError)
                raise exception(error.value.decode('utf-8', errors='replace'))
            if result.cancelled:
                raise CancelledError('compute cancelled by user')
            actual = _FullEnergyEffectiveSettings()
            if self.query_settings(ct.byref(result), ct.byref(actual)):
                raise RuntimeError('native full 2D effective settings query failed')
            if actual.outer_count != result.outer_history_count:
                raise RuntimeError('native full 2D effective settings do not match the thermal history')
            out = {name: bool(getattr(result, name)) for name in (*_FLAGS, *_FINE_FLAGS)}
            out.update(iterations=result.iterations, flow=[_flow(f, shape) for f in result.flow],
                       main=_thermal(result.main, actual.last, entry_version),
                       fine=_thermal(result.fine, actual.last, entry_version) if result.have_fine else None)
            out['property_sampling'] = copy_sampling(self.query_sampling, result)
            out['enthalpy_update_normalization'] = _copy_update_scale(self.query_update_scale, result)
            out['simple_velocity_relaxation'] = config.alpha_velocity
            out['model_h_iterations'] = _copy_iteration_records(self.query_model_h, result)
            for name in ('density', 'viscosity', 'rho_cp'):
                out[name] = [_copy(x, shape) for x in getattr(result, name)]
            for name in ('fine_duty', 'extrapolated_duty', 'pressure_drop', 'outlet_temperature', 'inlet_mass', 'duty'):
                out[name] = list(getattr(result, name))
            for name in ('q_total', 'q_solid', 'energy_imbalance'):
                out[name] = getattr(result, name)
            out['last_closure_ranges'] = copy_last_ranges(self.query_last_ranges, result)
            out['sco2_nu_observations'] = {side: copy_nu_observation(value, shape)
                                         for side, value in zip(('A', 'B'), result.nu_observations)}
            from sjtu_tpmshx.models.co2_correlations import NU_MULTIPLIER
            for i, side in enumerate('AB'):
                if config.sides[i].fluid == 3 and out['sco2_nu_observations'][side]:
                    out['sco2_nu_observations'][side]['floor'] *= NU_MULTIPLIER
            out['range_observations'] = copy_range_observations(result.range_observations, result.range_observation_count)
            out['outer_history'] = []
            for i in range(result.outer_history_count):
                h = result.outer_history[i]
                out['outer_history'].append(dict(iteration=h.iteration, thermal_iterations=h.thermal_iterations,
                    thermal_converged=bool(h.thermal_converged), outer_converged=bool(h.outer_converged),
                    relative_density_change=list(h.relative_density_change), temperature_change=list(h.temperature_change)))
                if out['main']['true_h'] is not None:
                    info = dict(effective_settings={})
                    _executed_energy_settings(info, actual.outer[i], entry_version)
                    out['outer_history'][-1]['energy_info'] = info
            if resume_state is not None:
                out['continuation'] = dict(format='full_2d_continuation_v1', build=resume_state['build'],
                    completed_outer_steps=int(resume_state['state.result.outer_history.size'][0]),
                    saved_phase=int(resume_state['state.phase'][0]))
            methods = (_FlowMethod*2)()
            if self.query_flow_methods(ct.byref(result), methods):
                raise RuntimeError('native full 2D flow method query failed')
            out['simple_flow'] = {side: dict(algorithm=value.algorithm.decode() if value.algorithm else None,
                iterations=value.iterations, proposal_steps=value.proposal_steps,
                accepted_proposals=value.accepted_proposals) for side, value in zip('AB', methods)}
            out['entry_version'] = entry_version
            if thread_call:
                out['runtime_resources'] = dict(cpu_thread_limit=control.native_cpu_threads(),
                    requested_cpu_threads=control.cpu_threads, policy='native_cpu_limit_v1')
            if energy_query and actual.last.available:
                extra = _EnergyEvidence()
                if energy_query(ct.byref(result), ct.byref(extra)):
                    raise RuntimeError('native full 2D energy evidence query failed')
                if out['main']['true_h'] is None or extra.outer_count != len(out['outer_history']):
                    raise RuntimeError('native full 2D energy evidence does not match the thermal history')
                info = out['main']['true_h']
                _energy_result_info(info, extra.main.energy,
                    temperature_tol=actual.last.temperature_update_tolerance, abi=entry_version, version_query=version_query, state_update='per_side_energy_relation')
                _energy_native_state(info, extra.main, (*shape, 1), 'W/m')
                out['main']['mode'] = 'conservative_energy'
                if out['fine'] is not None:
                    raise RuntimeError('native conservative energy unexpectedly returned Richardson evidence')
                for index, row in enumerate(out['outer_history']):
                    _energy_result_info(row['energy_info'], extra.outer[index],
                        temperature_tol=actual.outer[index].temperature_update_tolerance, abi=entry_version,
                        version_query=version_query)
            if out['main']['mode'] == 'temperature':
                query = self.library.tpmshx_full_2d_get_model_enthalpy_evidence_v1
                query.argtypes = [ct.POINTER(_Result), ct.POINTER(TemperatureEvidence2D)]
                query.restype = ct.c_int
                extra = TemperatureEvidence2D()
                if query(ct.byref(result), ct.byref(extra)):
                    raise RuntimeError('native full 2D temperature evidence query failed')
                out['main']['temperature_evidence'] = copy_temperature_evidence(extra.main, (*shape, 1), 2)
                if out['fine'] is not None:
                    fine_shape = (len(out['fine']['dx']), len(out['fine']['dy']), 1)
                    out['fine']['temperature_evidence'] = copy_temperature_evidence(extra.fine, fine_shape, 2)
            if 'temperature_evidence' not in out['main']:
                ledger = HeatLedger2D()
                if self.query_heat_ledger(ct.byref(result), ct.byref(ledger)):
                    raise RuntimeError('native full 2D heat ledger query failed')
                out['main']['physical_ledger'] = copy_heat_ledger(ledger.main, (*shape, 1), 2)
                if out['fine'] is not None:
                    fine_shape = (len(out['fine']['dx']), len(out['fine']['dy']), 1)
                    out['fine']['physical_ledger'] = copy_heat_ledger(ledger.fine, fine_shape, 2)
            if out['main']['mode'] in ('model_h', 'temperature'):
                algorithm = (_model_h_algorithm(self.library, 2) if out['main']['mode'] == 'model_h'
                             else out['main']['temperature_evidence']['algorithm'])
                _set_native_metadata(out, self.abi, algorithm, config.red_black)
            return out
        finally:
            if result.owner:
                self.release(ct.byref(result))



def configure_convergence(solver, cfg, solver_config=None):
    """Apply captured environment > typed settings > cfg > shared defaults."""
    def knob(name, default):
        value = getattr(solver_config, name, None)
        if value is None:
            value = cfg.get(name)
        return default if value is None else value

    solver.convergence_mode = require_f2_mode(run_environment(
        cfg, 'TPMSHX_CONV_MODE', knob('convergence_mode', 'f2')))
    solver.mom_tol = float(knob('mom_tol', 1e-4))
    solver.mass_local_tol = float(knob('mass_local_tol', 1e-6))
    solver.mass_global_tol = float(knob('mass_global_tol', 1e-6))


def _pack(cfg, prepared, table_directory, library):
    """Pack already validated CaseData without constructing Python solvers."""
    shape = (len(prepared['energy_dx']), len(prepared['energy_dy']))
    properties, zones = cfg['static_properties'], cfg['za']
    geometry = cfg['thermal_geometry']['fields'] or cfg['thermal_geometry']['uniform']
    cell = lambda value: np.ascontiguousarray(np.broadcast_to(np.asarray(value, dtype=np.float64), shape))
    arrays = [prepared['energy_dx'], prepared['energy_dy'], np.ones(1),
        cell(properties['A']['K_ff'] if zones is None else zones['K_ffA_arr']),
        cell(properties['B']['K_ff'] if zones is None else zones['K_ffB_arr']),
        cell(properties['geometry']['K_ss'] if zones is None else zones['K_ss_arr']),
        cell(cfg['eps'] if zones is None else zones['eps_arr']), cell(geometry['A_0']), cell(geometry['D_h']),
        cell(cfg['Lcell']*1e-3 if zones is None else zones['L_field']*1e-3)]
    config = _Config()
    config.topology = ('Diamond', 'Gyroid').index(cfg['tpms_type'])
    config.asymmetric = cfg['compute_cfg'].geometry.delta_levelset != 0
    fluids = (cfg['fluid_A'], cfg['fluid_B'])
    config.thermal_mode = (2 if any(f in ('sco2', 'co2') for f in fluids)
                           and (cfg['zone_config'] is None or cfg['z_axis'] == 'continuous') else
        1 if all(f in ('air', 'water') for f in fluids) and not config.asymmetric and
        (cfg['zone_config'] is None or cfg['z_axis'] == 'continuous') else 0)
    config.spatial_geometry = zones is not None
    config.have_solid_seed = cfg.get('T_s_init') is not None
    config.solid_seed = cfg.get('T_s_init') or 0.
    config.pressure_shooting = cfg.get('p_in_shooting', run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') == '1')
    # The original public 2D route has no runtime RB selector; it is disabled.
    config.red_black = 0
    config.reference_cell_length, config.reference_porosity = cfg['Lcell']*1e-3, cfg['eps']
    config.split_a = cfg['thermal_geometry']['split_A']
    config.sco2_nu_multiplier = 1.
    nu = cfg['compute_cfg'].sco2_nu
    if config.thermal_mode == 2 and nu.mode != 'cfd_smooth':
        config.sco2_nu_multiplier = getattr(nu, 'alpha_G' if cfg['tpms_type'] == 'Gyroid' else 'alpha_D')
    for i, side in enumerate(('A', 'B')):
        flow, opening, port = cfg['flow_inputs'][side], cfg['boundary_openings'][side], cfg['cfg'+side]
        for end in ('in', 'out'):
            fractions = _port_fractions_1d(flow['dx'], port[end+'_ctr']-port[end+'_w']/2,
                port[end+'_ctr']+port[end+'_w']/2,
                uniform=end == 'in' and port.get('uniform_inlet_2d', False))
            for kind, expected in zip(('geom', 'profile'), fractions):
                name = end+'_'+kind+'_frac'
                supplied = np.asarray(opening[name])
                if supplied.shape != expected.shape or not np.allclose(supplied, expected, rtol=1e-12, atol=1e-15):
                    raise ValueError(f'prepared Fluid {side} {name} disagrees with its grid and port geometry')
        arrays.extend([flow['K_m2'], flow['cF_per_m'], flow.get('K_field_m2', np.empty(0)),
            flow.get('cF_field_per_m', np.empty(0)), opening['in_geom_frac'], opening['out_geom_frac'],
            opening['in_profile_frac'], opening['out_profile_frac'],
            _port_overlap_1d(flow['dx'], port['out_ctr']-port['out_w']/2, port['out_ctr']+port['out_w']/2, staggered=True)])
        physical = getattr(cfg['compute_cfg'], 'fluid_'+side)
        side_geometry = (cfg['thermal_geometry']['side_geometry'] or {}).get(side, (0., 0., 0., 0.))
        config.sides[i] = _Side(('air', 'water', 'sco2', 'co2').index(cfg['fluid_'+side]), cfg['dir_'+side],
            int(port.get('uniform_inlet_2d', False)), cfg['T_in'+side], physical.P_in_Pa, cfg['u_'+side],
            properties[side]['mu'], flow['seed_K_m2'], flow['seed_cF_per_m'],
            port['in_ctr']-port['in_w']/2, port['in_ctr']+port['in_w']/2,
            port['out_ctr']-port['out_w']/2, port['out_ctr']+port['out_w']/2, *side_geometry)
    # Keep the original closure's unit-conversion order before L_mm is
    # rounded into its separate SI transport field.
    arrays.append(cell(geometry['D_h']*1000. / (cfg['Lcell'] if zones is None else zones['L_field'])))
    solver = cfg['compute_cfg'].solver
    settings = SimpleNamespace()
    configure_convergence(settings, cfg, solver)
    config.f2 = _F2(settings.mom_tol, settings.mass_local_tol, settings.mass_global_tol,
                     .01, 1e-4, 1e-3, 2, 5, 60)
    config.simple_iterations, config.simple_sweeps = solver.max_iter_simple or 10000, 2
    config.outer_iterations = solver.max_outer_ltne or 10
    config.outer_temperature_tolerance = solver.outer_tol_K or 1.
    config.outer_density_tolerance, config.outer_relaxation = .01, .7
    if config.thermal_mode == 2:
        energy = _energy_options(solver.enthalpy_algorithm, solver.enthalpy_temperature_tol_K)
        defaults = _full_enthalpy_defaults(library, 2, energy.algorithm, 'water' in fluids)
        config.thermal_iterations = defaults.max_iterations
        config.enthalpy_update_tolerance = defaults.update_tolerance
        config.thermal_chunk, config.thermal_q_tolerance = 3, .1*2e-3
    else:
        config.thermal_iterations = 12000 if 'water' in fluids else 5000
        config.thermal_chunk = 500
        tolerance = 1. if 'water' in fluids else .5
        config.thermal_q_tolerance = min(tolerance*2e-3, 1e-3)
        config.enthalpy_update_tolerance = tolerance/100.
    relaxation = solver.simple_velocity_relaxation
    validate_simple_velocity_relaxation(relaxation)
    config.alpha_velocity = .7 if relaxation is None else relaxation
    config.alpha_pressure, config.alpha_density = .3, .3
    config.gas_constant, config.cf_anisotropy = 287.05, 0.
    config.massflux_inlet, config.close_outlet_on_exit = 1, 1
    config.envelope_mode, config.table_directory = cfg.get('envelope_mode', 'raise').encode(), table_directory
    return shape, arrays, config


def run_case(case, control=RunControl(), *, resume_state=None, checkpoint=None, checkpoint_due=None):
    from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
    from .full_2d_capture import capture_result
    if control.backend != 'cpp' or control.native_library is None:
        raise ValueError('full native 2D requires backend=cpp and an explicit native_library')
    control.check_cancelled()
    cfg, prepared = build_execution_inputs(case, copy_design=False)
    driver = NativeFull2DDriver(control.native_library, table_directory=control.native_table_directory)
    native = driver.run_prepared(cfg, prepared, control, resume_state=resume_state, checkpoint=checkpoint, checkpoint_due=checkpoint_due)
    control.check_cancelled()
    result = capture_result(case, cfg, prepared, native)
    control.report_progress(100)
    return result
