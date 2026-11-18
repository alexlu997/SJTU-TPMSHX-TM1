"""C layouts shared by complete 3D solves and native continuation."""
import ctypes as ct

from .simple_3d import _Config as _SimpleConfig, _Result as _SimpleResult
from .model_h import _Result as _ModelResult
from .enthalpy import _Result as _EnthalpyResult, _EnergyResult
from .closure_evidence import NuObservation, RangeObservation


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
        'force_cell_centered', 'refined_port_energy', 'red_black_energy', 'sco2_local_pressure_a', 'coarse_bootstrap')]
    _fields_ += [('coarse_iterations', ct.c_size_t)]
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


_FLOW_ARRAYS = ('epsilon', 'permeability', 'forchheimer', 'temperature', 'viscosity', 'effective_viscosity', 'density',
    'u', 'v', 'w', 'pressure', 'pressure_correction', 'd_u', 'd_v', 'd_w', 'inlet_velocity', 'inlet_opening', 'outlet_opening',
    'outlet_u_fraction', 'outlet_w_fraction', 'fixed_inlet_massflux', 'pressure_real', 'density_real', 'speed_real')


class _Flow(ct.Structure):
    _fields_ = [('widths', _Array*3), *[(n, _Array) for n in _FLOW_ARRAYS],
                ('velocity_real', _Array*3), ('face_velocity_real', _Array*3), ('pressure_reference', ct.c_double),
                ('last', _SimpleResult), *[(n, _Array) for n in ('legacy', 'local_mass', 'global_mass', 'momentum')],
                ('pressure_iterations', ct.POINTER(_PressureIteration)), ('pressure_iteration_count', ct.c_size_t),
                ('inlet_pressure', _PressureState), ('bootstrap', _Bootstrap)]


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
