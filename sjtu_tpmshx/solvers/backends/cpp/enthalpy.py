"""Explicit thin binding to the complete true-h thermal C ABI.

This callable matches the existing shared 3D/unit-depth-2D driver inputs.
Geometry, mass-face preparation and outer coupling remain caller concerns;
no solver dispatch/default is changed by importing or constructing it.
"""
import ctypes as ct
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.models.fluid_props import WaterStateError


class _Side(ct.Structure):
    _fields_ = [('fluid', ct.c_uint32), ('inlet_temperature', ct.c_double),
                ('inlet_pressure', ct.c_double)]


class _Config(ct.Structure):
    _fields_ = [('sides', _Side * 2), *[(name, ct.c_uint32) for name in
                ('warm_a', 'warm_b', 'warm_solid', 'coupled_gate', 'equation_gate')],
                ('max_iterations', ct.c_size_t), ('sweeps', ct.c_size_t),
                *[(name, ct.c_double) for name in
                  ('omega', 'update_tolerance', 'coupled_tolerance', 'equation_tolerance')],
                ('table_directory', ct.c_char_p)]


class _Audit(ct.Structure):
    _fields_ = [*[(name, ct.c_double) for name in
                 ('q_a', 'q_b', 'net', 'solid_abs_sum', 'denominator', 'coupled_ratio')],
                ('fluid_abs_sum', ct.c_double * 2), ('fluid_cell_max', ct.c_double * 2),
                ('equation_ratio', ct.c_double), ('fluid_equations_computed', ct.c_uint32)]


class _Result(ct.Structure):
    _fields_ = [('stop', ct.c_uint32), ('iterations', ct.c_size_t),
                *[(name, ct.c_double) for name in ('residual', 'q_a', 'q_b', 'energy_imbalance')],
                ('inlet_enthalpy', ct.c_double * 2), ('last_clips', ct.c_uint64 * 2),
                ('total_clips', ct.c_uint64 * 2), ('used_bicubic', ct.c_uint32 * 2),
                ('heos_polish', ct.c_uint32), ('audit_available', ct.c_uint32),
                ('audit', _Audit), ('coolprop_version', ct.c_char * 32)]


_ENERGY_NAMES = ('legacy_h_fou', 'temperature_fou', 'temperature_sou')


class _EnergyOptions(ct.Structure):
    _fields_ = [('algorithm', ct.c_uint32), ('temperature_update_tolerance', ct.c_double)]


class _EnergyResult(ct.Structure):
    _fields_ = [('algorithm', ct.c_uint32), ('has_temperature_update', ct.c_uint32),
                ('temperature_update', ct.c_double), ('picard_relaxation', ct.c_double)]


def _energy_options(algorithm, tolerance):
    from sjtu_tpmshx.domain.compute_config import validate_enthalpy_algorithm
    validate_enthalpy_algorithm(algorithm, tolerance)
    return _EnergyOptions(_ENERGY_NAMES.index(algorithm), tolerance)


def _energy_result_info(info, result, *, temperature_tol, abi):
    """Decode executed native identity, independently of the requested option."""
    if result.algorithm not in range(len(_ENERGY_NAMES)):
        raise RuntimeError('native energy returned an unknown algorithm')
    name = _ENERGY_NAMES[result.algorithm]
    if name == 'legacy_h_fou' or result.has_temperature_update != 1:
        raise RuntimeError('native candidate energy omitted its executed state')
    if not np.isfinite(result.temperature_update) or result.temperature_update < 0:
        raise RuntimeError('native energy returned an invalid temperature update')
    if not np.isfinite(result.picard_relaxation) or not 0 < result.picard_relaxation <= 1:
        raise RuntimeError('native energy returned an invalid Picard relaxation')
    info.update(energy_algorithm=name, energy_algorithm_version=1,
                temperature_update_K=result.temperature_update)
    info['effective_settings'].update(energy_algorithm=name, energy_algorithm_version=1,
        temperature_update_tol_K=float(temperature_tol), driver_abi=abi,
        picard_relaxation=result.picard_relaxation,
        nonlinear_state_update='HEOS_PT',
        enthalpy_face_reconstruction='FOU' if result.algorithm == 1 else 'h_minmod_outlet_v1',
        solid_omega=info['effective_settings']['omega'] if result.algorithm == 1 else 1.)
    return info


def _energy_native_state(info, evidence, shape, units):
    """Copy native face powers; never reconstruct SOU in the Python binding."""
    if evidence.available != 1:
        raise RuntimeError('native energy omitted final boundary evidence')
    def copy(value, expected):
        return np.ctypeslib.as_array(value.data, (value.size,)).copy().reshape(expected)
    planes = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
    boundary = {}
    state = info['_native_state']
    for side, label in enumerate('AB'):
        boundary[label] = {name: copy(evidence.boundary_power[side][index],
            tuple(n for axis, n in enumerate(shape) if axis != index // 2))
            for index, name in enumerate(planes)}
        state['actual_conductivity_' + label] = copy(evidence.actual_conductivity[side], shape)
    state.update(energy_algorithm=info['energy_algorithm'], energy_algorithm_version=1,
                 boundary_power=boundary, boundary_power_units=units, physical_boundary_complete=True)


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('context', ct.c_void_p)]


def _result_info(result, *, update_tol, coupled_energy_tol, equation_energy_tol,
                 max_iterations, sweeps, omega, abi=1):
    """Detach the common scalar audit returned by each complete true-h driver."""
    info = dict(iterations=result.iterations, converged=result.stop == 0,
        residual=result.residual, enthalpy_mode=True, Q_A=result.q_a, Q_B=result.q_b,
        energy_imbalance_rel=result.energy_imbalance,
        exit_reason=('converged', 'enthalpy_limited', 'iteration_limit', 'cancelled')[result.stop],
        enthalpy_clip_counts=dict(total=list(result.total_clips), last=list(result.last_clips)),
        effective_settings=dict(update_tol=float(update_tol), coupled_energy_tol=coupled_energy_tol,
            equation_energy_tol=equation_energy_tol, max_iterations=max_iterations, sweeps=sweeps,
            omega=float(omega), sweep_kernel='cpp', energy_audit='cpp', thermal_driver='cpp', driver_abi=abi))
    if result.audit_available:
        a = result.audit
        info['coupled_energy_balance'] = dict(net=a.net, solid_abs_sum=a.solid_abs_sum,
                                             denominator=a.denominator, ratio=a.coupled_ratio)
        if a.fluid_equations_computed:
            info['equation_energy_balance'] = dict(fluid_abs_sum=list(a.fluid_abs_sum),
                fluid_cell_max=list(a.fluid_cell_max), solid_abs_sum=a.solid_abs_sum,
                denominator=a.denominator, ratio=a.equation_ratio)
    return info


class NativeEnthalpyDriver:
    """Load an explicit independent native capability; never select a fallback."""

    def __init__(self, library, *, table_directory=None):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native true-h library must be an absolute path')
        self.path = path.resolve(strict=True)
        self.library = ct.CDLL(str(self.path))
        version = self.library.tpmshx_enthalpy_driver_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 1:
            raise ValueError(f'unsupported true-h driver ABI: {self.abi}; expected 1')
        if table_directory is not None and not Path(table_directory).is_absolute():
            raise ValueError('native true-h table directory must be an absolute path')
        self.table_directory = None if table_directory is None else str(table_directory).encode('utf-8')
        self.call = self.library.tpmshx_solve_enthalpy_v1
        double_p, size_p = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
        self.call.argtypes = [size_p, ct.POINTER(double_p), size_p, ct.POINTER(_Config),
                             ct.POINTER(_Callbacks), ct.POINTER(_Result),
                             ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int

    def __call__(self, Nx, Ny, Nz, dx, dy, dz, eps_arr, K_ss,
                 h_vA_field, h_vB_field, T_inA, T_inB, P_A, P_B,
                 *, mass_flux_A, mass_flux_B, fluid_A='sco2', fluid_B='sco2',
                 eps_A_field=None, eps_B_field=None, pressure_A_field=None,
                 pressure_B_field=None, Ta_init=None, Tb_init=None, Ts_init=None,
                 n_outer=3000, n_sweep=5, omega=.6, tol=2e-5,
                 cancel_check=None, coupled_energy_tol=None, equation_energy_tol=None):
        shape = tuple(operator.index(n) for n in (Nx, Ny, Nz))
        maximum = ct.c_size_t(-1).value
        if any(n <= 0 or n > maximum for n in shape):
            raise ValueError('invalid native true-h grid extent')
        budget, sweeps = operator.index(n_outer), int(n_sweep)
        if budget <= 0 or sweeps < 0 or budget > maximum or sweeps > maximum:
            raise ValueError('invalid native true-h iteration/sweep budget')

        def array(value, expected, *, broadcast=False):
            value = np.asarray(value, dtype=np.float64)
            if broadcast:
                value = np.broadcast_to(value, expected)
            if value.shape != expected:
                raise ValueError(f'true-h array shape {value.shape} does not match {expected}')
            return np.require(value, requirements=['C', 'A'])

        eps_a = array(.5 * np.asarray(eps_arr, dtype=np.float64) if eps_A_field is None else eps_A_field, shape)
        eps_b = eps_a.copy() if eps_B_field is None else array(eps_B_field, shape)
        pa = np.full(shape, float(P_A)) if pressure_A_field is None else array(pressure_A_field, shape)
        pb = np.full(shape, float(P_B)) if pressure_B_field is None else array(pressure_B_field, shape)
        face_shapes = tuple(tuple(n + int(axis == k) for k, n in enumerate(shape)) for axis in range(3))
        if len(mass_flux_A) != 3 or len(mass_flux_B) != 3:
            raise ValueError('true-h requires three signed mass-face arrays per side')
        faces_a = tuple(array(value, expected) for value, expected in zip(mass_flux_A, face_shapes))
        faces_b = tuple(array(value, expected) for value, expected in zip(mass_flux_B, face_shapes))
        warm = (Ta_init, Tb_init, Ts_init)
        state = [np.empty(shape), np.empty(shape)]
        state += [np.empty(shape) if value is None else np.array(array(value, shape), order='C', copy=True)
                  for value in warm]
        arrays = [array(value, (n,)) for value, n in zip((dx, dy, dz), shape)]
        arrays += [array(K_ss, shape, broadcast=True), pa, eps_a, array(h_vA_field, shape), *faces_a,
                   pb, eps_b, array(h_vB_field, shape), *faces_b, *state]
        fluid_codes = {'air': 0, 'water': 1, 'sco2': 2}
        if fluid_A not in fluid_codes or fluid_B not in fluid_codes:
            raise ValueError('native true-h supports air, water and sco2')
        config = _Config((_Side * 2)(_Side(fluid_codes[fluid_A], T_inA, P_A),
                                    _Side(fluid_codes[fluid_B], T_inB, P_B)),
            *(int(value is not None) for value in warm),
            int(coupled_energy_tol is not None), int(equation_energy_tol is not None),
            budget, sweeps, omega, tol,
            0. if coupled_energy_tol is None else coupled_energy_tol,
            0. if equation_energy_tol is None else equation_energy_tol, self.table_directory)
        callback_errors = []

        @_Cancel
        def cancelled(_):
            if callback_errors:
                return 1
            try:
                return int(cancel_check())
            except BaseException as error:
                callback_errors.append(error)
                return 1

        callbacks = _Callbacks(cancelled if cancel_check is not None else _Cancel(), None)
        double_p = ct.POINTER(ct.c_double)
        pointers = (double_p * len(arrays))(*(value.ctypes.data_as(double_p) for value in arrays))
        sizes = (ct.c_size_t * len(arrays))(*(value.size for value in arrays))
        result, error = _Result(), ct.create_string_buffer(2048)
        status = self.call((ct.c_size_t * 3)(*shape), pointers, sizes, ct.byref(config),
                           ct.byref(callbacks), ct.byref(result), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        if status:
            exception = {1: ValueError, 2: WaterStateError, 3: FloatingPointError}.get(status, RuntimeError)
            raise exception(error.value.decode('utf-8', errors='replace'))
        if result.stop == 3:
            raise CancelledError('compute cancelled by user')
        if result.stop not in (0, 1, 2):
            raise RuntimeError('native true-h returned an invalid stop contract')
        info = _result_info(result, update_tol=tol, coupled_energy_tol=coupled_energy_tol,
            equation_energy_tol=equation_energy_tol, max_iterations=budget, sweeps=sweeps,
            omega=omega, abi=self.abi)
        info['_native_state'] = dict(h_A=state[0], h_B=state[1], h_in_A=result.inlet_enthalpy[0],
            h_in_B=result.inlet_enthalpy[1], mass_flux_A=faces_a, mass_flux_B=faces_b)
        table_sides = [side for side, used in zip(('A', 'B'), result.used_bicubic) if used]
        if table_sides:
            info['_native_state']['sco2_enthalpy_eos'] = dict(
                algorithm='bicubic_iteration_heos_polish_v2', iteration_backend='BICUBIC&HEOS',
                final_backend='HEOS', transport_backend='HEOS',
                coolprop_version=result.coolprop_version.decode('utf-8'),
                sides=table_sides, heos_polish=bool(result.heos_polish))
        return state[2], state[3], state[4], info
