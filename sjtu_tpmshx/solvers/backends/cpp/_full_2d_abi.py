"""C layouts shared by complete 2D solves and native continuation."""
import ctypes as ct

from ._simple_abi import _F2
from .simple_2d import _Result as _SimpleResult
from .model_h import _Array, _Result as _ModelResult
from .enthalpy import _Result as _EnthalpyResult, _EnergyOptionsV2, _EnergyResult
from .closure_evidence import NuObservation, RangeObservation


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


class _FlowMethod(ct.Structure):
    _fields_ = [('algorithm', ct.c_char_p), ('iterations', ct.c_size_t),
                ('proposal_steps', ct.c_size_t), ('accepted_proposals', ct.c_size_t)]
