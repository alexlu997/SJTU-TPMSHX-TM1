"""Common layouts and requests for native thermal calls."""
import ctypes as ct

import numpy as np


class _EnthalpyAudit(ct.Structure):
    _fields_ = [*[(name, ct.c_double) for name in
                 ('q_a', 'q_b', 'net', 'solid_abs_sum', 'denominator', 'coupled_ratio')],
                ('fluid_abs_sum', ct.c_double * 2), ('fluid_cell_max', ct.c_double * 2),
                ('equation_ratio', ct.c_double), ('fluid_equations_computed', ct.c_uint32)]


class _EnthalpyResult(ct.Structure):
    _fields_ = [('stop', ct.c_uint32), ('iterations', ct.c_size_t),
                *[(name, ct.c_double) for name in ('residual', 'q_a', 'q_b', 'energy_imbalance')],
                ('inlet_enthalpy', ct.c_double * 2), ('last_clips', ct.c_uint64 * 2),
                ('total_clips', ct.c_uint64 * 2), ('used_bicubic', ct.c_uint32 * 2),
                ('heos_polish', ct.c_uint32), ('audit_available', ct.c_uint32),
                ('audit', _EnthalpyAudit), ('coolprop_version', ct.c_char * 32)]


_ENERGY_NAMES = ('legacy_h_fou', 'temperature_fou', 'temperature_sou')


class _EnergyOptions(ct.Structure):
    _fields_ = [('algorithm', ct.c_uint32), ('temperature_update_tolerance', ct.c_double)]


class _EnergyOptionsV2(ct.Structure):
    _fields_ = [('algorithm', ct.c_uint32), ('temperature_update_tolerance', ct.c_double),
                ('coupled_energy_tolerance', ct.c_double), ('equation_energy_tolerance', ct.c_double),
                ('require_enthalpy_update_on_temperature', ct.c_uint32)]


class _EnergyResult(ct.Structure):
    _fields_ = [('algorithm', ct.c_uint32), ('has_temperature_update', ct.c_uint32),
                ('temperature_update', ct.c_double), ('picard_relaxation', ct.c_double)]


class _EnergyUpdateScale(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('reference_independent', ct.c_uint32),
                ('scale', ct.c_double * 2)]


class _EnergyEffectiveSettings(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in (
        'available', 'algorithm', 'require_enthalpy_update_on_temperature')]
    _fields_ += [(name, ct.c_size_t) for name in ('max_iterations', 'sweeps')]
    _fields_ += [(name, ct.c_double) for name in ('omega', 'update_tolerance',
        'temperature_update_tolerance', 'coupled_energy_tolerance', 'equation_energy_tolerance')]


class _FullEnergyEffectiveSettings(ct.Structure):
    _fields_ = [('resolved', _EnergyEffectiveSettings), ('last', _EnergyEffectiveSettings),
                ('outer', ct.POINTER(_EnergyEffectiveSettings)), ('outer_count', ct.c_size_t)]


def _energy_options(algorithm, tolerance):
    from tm1.data_types.compute_config import validate_enthalpy_algorithm
    validate_enthalpy_algorithm(algorithm, tolerance)
    return _EnergyOptions(_ENERGY_NAMES.index(algorithm), tolerance)


def _full_enthalpy_defaults(library, dimension, algorithm, has_water):
    try:
        query = library.tpmshx_full_enthalpy_defaults_v1
    except AttributeError as error:
        raise ValueError('native library lacks full enthalpy defaults; rebuild the library') from error
    query.argtypes = [ct.c_uint32, ct.c_uint32, ct.c_uint32, ct.POINTER(_EnergyEffectiveSettings)]
    query.restype = ct.c_int
    defaults = _EnergyEffectiveSettings()
    if query(dimension, algorithm, has_water, ct.byref(defaults)):
        raise ValueError('invalid native full enthalpy defaults request')
    return defaults


class _IterationOptions(ct.Structure):
    _fields_ = [('max_iterations', ct.c_size_t), ('temperature_tolerance', ct.c_double),
                ('q_relative_tolerance', ct.c_double)]


class _IterationRecord(ct.Structure):
    _fields_ = [('outer_index', ct.c_size_t), ('attempt', ct.c_size_t), ('refined', ct.c_uint32),
                ('max_iterations', ct.c_size_t), ('chunk_iterations', ct.c_size_t),
                ('temperature_tolerance', ct.c_double), ('q_relative_tolerance', ct.c_double),
                ('total_iteration_budget', ct.c_size_t)]


class _IterationRecords(ct.Structure):
    _fields_ = [('records', ct.POINTER(_IterationRecord)), ('count', ct.c_size_t)]


class _Acceleration(ct.Structure):
    _fields_ = [('enabled', ct.c_uint32), ('sweeps_per_block', ct.c_size_t), ('history_limit', ct.c_size_t)]


def _iteration_options(settings):
    names = ('model_h_max_iterations', 'model_h_temperature_tol_K', 'model_h_q_relative_tol')
    values = [settings.get(name) for name in names]
    if all(value is None for value in values):
        return None
    for index, (name, value) in enumerate(zip(names, values)):
        if value is None:
            values[index] = 0
        elif index == 0:
            if type(value) is not int or not 0 < value <= ct.c_size_t(-1).value:
                raise ValueError(f'{name} must be a positive size_t integer')
        elif (isinstance(value, bool) or not isinstance(value, (int, float))
              or not np.isfinite(value) or value <= 0.):
            raise ValueError(f'{name} must be finite and positive')
    return _IterationOptions(*values)


class _ThermalArray(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_double)), ('size', ct.c_size_t)]


class _Side2D(ct.Structure):
    _fields_ = [(n, ct.c_double) for n in
                ('q_advective', 'inlet_conduction', 'exchange', 'residual_sum', 'residual_max',
                 'linearized_sum', 'linearized_max', 'defect_sum', 'defect_max', 'mass_net',
                 'mass_local_max', 'mass_in', 'mass_out', 'normalization', 'cell_ratio')]
    _fields_ += [('unknown_inflow_faces', ct.c_size_t), ('cp_coefficients', ct.c_double * 5),
                 ('boundary_mass_out', _ThermalArray * 4), ('boundary_h_out', _ThermalArray * 4),
                 ('h_faces', _ThermalArray * 2), ('inlet_conduction_faces', _ThermalArray),
                 ('residual', _ThermalArray), ('linearization_defect', _ThermalArray)]


class _Audit2D(ct.Structure):
    _fields_ = [('sides', _Side2D * 2)]
    _fields_ += [(n, ct.c_double) for n in
                 ('solid_sum', 'solid_max', 'solid_cell_ratio', 'residual_sum', 'telescoping_error',
                  'net_boundary_in', 'denominator', 'energy_imbalance', 'solid_imbalance')]
    _fields_ += [(n, ct.c_uint32) for n in
                 ('boundary_complete', 'finite', 'energy_ok', 'solid_ok', 'equations_ok', 'passed')]
    _fields_ += [('solid_residual', _ThermalArray)]


class _Boundary3D(ct.Structure):
    _fields_ = [(n, ct.c_double) for n in
                ('mass_out', 'enthalpy_out', 'unknown_mass_in', 'inlet_reverse_mass_out')]
    _fields_ += [('unknown_inflow_count', ct.c_size_t), ('enthalpy_faces', _ThermalArray)]


class _Side3D(ct.Structure):
    _fields_ = [('boundaries', _Boundary3D * 6), ('cp_coefficients', ct.c_double * 5)]
    _fields_ += [(n, ct.c_double) for n in
                 ('temperature_min', 'temperature_max', 'mass_net', 'advective_in', 'diffusion_in',
                  'numerical_external_in', 'exchange', 'source', 'residual_sum', 'residual_max',
                  'normalization', 'global_ratio', 'cell_ratio')]
    _fields_ += [('boundary_complete', ct.c_uint32), ('residual', _ThermalArray), ('inlet_diffusion', _ThermalArray)]


class _Audit3D(ct.Structure):
    _fields_ = [('sides', _Side3D * 2)]
    _fields_ += [(n, ct.c_double) for n in
                 ('volume', 'numerical_external_in', 'explicit_source', 'solid_sum', 'solid_max',
                  'full_residual_sum', 'telescoping_error', 'ltne_source_ratio')]
    _fields_ += [('boundary_complete', ct.c_uint32), ('gates', ct.c_uint32 * 6),
                 ('passed', ct.c_uint32), ('solid_residual', _ThermalArray)]


class _Check(ct.Structure):
    _fields_ = [('iterations', ct.c_size_t), ('gates', ct.c_uint32 * 6)]


class _ModelHResult(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('dimension', 'stop', 'audit_available', 'has_sources')]
    _fields_ += [('iterations', ct.c_size_t), ('residual', ct.c_double), ('q_b', ct.c_double),
                 ('plane', _Audit2D), ('volume', _Audit3D), ('finishing_checks', ct.POINTER(_Check)),
                 ('finishing_count', ct.c_size_t), ('owner', ct.c_void_p)]
