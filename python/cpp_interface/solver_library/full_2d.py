"""Run a direct 2D solve or restore a library without the saved stage protocol."""
import ctypes as ct
from ._full_2d_abi import _Callbacks, _Config, _EnergyControl, _EnergyEvidence, _Result, _Side
from functools import partial
from types import SimpleNamespace
import numpy as np
from sjtu_tpmshx.data_types.compute_config import validate_simple_velocity_relaxation
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.run_environment import run_environment
from sjtu_tpmshx.physical_models.envelope import ChokedFlowError
from sjtu_tpmshx.physical_models.fluid_props import WaterStateError
from sjtu_tpmshx.solvers.backends.prepared_2d import _validated_outlet_fraction
from ._simple_abi import _F2
from .model_h import _IterationOptions, _iteration_options
from .enthalpy import _EnergyOptions, _EnergyOptionsV2, _energy_options, _energy_algorithm_query, _full_enthalpy_defaults
from ..full_2d_stage import StageDriver, _callbacks, configure_convergence, run_case as _run_case


class NativeFull2DDriver(StageDriver):
    def __init__(self, library, *, table_directory=None):
        super().__init__(library, table_directory=table_directory)
        self.call = self.library.tpmshx_solve_full_2d_v2
        dp, sp = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
        self.call.argtypes = [sp, ct.POINTER(dp), sp, ct.POINTER(_Config), ct.POINTER(_Callbacks),
                             ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int
        self.release = self.library.tpmshx_full_2d_release_v2
        self.release.argtypes, self.release.restype = [ct.POINTER(_Result)], None

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
            _full_enthalpy_defaults(self.library, 2, energy.algorithm,
                                   any(side.fluid == 1 for side in config.sides))
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
        callbacks, errors = _callbacks(control)
        dp = ct.POINTER(ct.c_double)
        pointers = (dp*len(arrays))(*(x.ctypes.data_as(dp) for x in arrays))
        sizes = (ct.c_size_t*len(arrays))(*(x.size for x in arrays))
        result, error = _Result(), ct.create_string_buffer(2048)
        try:
            args = ((ct.c_size_t*2)(*shape), pointers, sizes, ct.byref(config))
            tail = (ct.byref(callbacks), ct.byref(result), error, len(error))
            basic_energy = energy if energy_control is None and model_h_options is None else None
            if resume_state is not None or checkpoint is not None:
                from sjtu_tpmshx.cpp_interface.solver_library.full_2d_run import NativeFull2DRun
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
            return self.copy_result(result, shape, config, entry_version=entry_version, control=control,
                have_cpu_limit=thread_call is not None, energy_query=energy_query, version_query=version_query,
                resume_state=resume_state)
        finally:
            if result.owner:
                self.release(ct.byref(result))


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
        outlet_fraction = _validated_outlet_fraction(flow, opening, port, side)
        arrays.extend([flow['K_m2'], flow['cF_per_m'], flow.get('K_field_m2', np.empty(0)),
            flow.get('cF_field_per_m', np.empty(0)), opening['in_geom_frac'], opening['out_geom_frac'],
            opening['in_profile_frac'], opening['out_profile_frac'],
            outlet_fraction])
        physical = getattr(cfg['compute_cfg'], 'fluid_'+side)
        side_geometry = (cfg['thermal_geometry']['side_geometry'] or {}).get(side, (0., 0., 0., 0.))
        config.sides[i] = _Side(('air', 'water', 'sco2', 'co2').index(cfg['fluid_'+side]), cfg['dir_'+side],
            int(port.get('uniform_inlet_2d', False)), cfg['T_in'+side], physical.P_in_Pa, cfg['u_'+side],
            properties[side]['mu'], flow['seed_K_m2'], flow['seed_cF_per_m'],
            port['in_ctr']-port['in_w']/2, port['in_ctr']+port['in_w']/2,
            port['out_ctr']-port['out_w']/2, port['out_ctr']+port['out_w']/2, *side_geometry)
    # Keep the original closure's unit-conversion order before L_mm is
    # rounded into its separate SI transport field.
    from sjtu_tpmshx.cpp_interface._native_flow import closure_geometry_ratio
    arrays.append(cell(closure_geometry_ratio(geometry['D_h'], cfg['Lcell'] if zones is None else zones['L_field'])))
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

def _run_direct(case, cfg, prepared, control, resume_state, checkpoint, checkpoint_due):
    from .full_2d_capture import capture_result
    driver = NativeFull2DDriver(control.native_library, table_directory=control.native_table_directory)
    native = driver.run_prepared(cfg, prepared, control, resume_state=resume_state,
        checkpoint=checkpoint, checkpoint_due=checkpoint_due)
    control.check_cancelled()
    return capture_result(case, cfg, prepared, native)


run_case = partial(_run_case, direct_run=_run_direct)
