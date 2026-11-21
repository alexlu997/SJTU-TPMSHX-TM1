"""Explicit thin binding to the direct T-SOU thermal C ABI.

This callable matches the existing shared 3D/unit-depth-2D driver inputs.
Geometry, mass-face preparation and outer coupling remain caller concerns;
no solver dispatch/default is changed by importing or constructing it.
"""
import ctypes as ct
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.physical_models.fluid_props import WaterStateError
from ._thermal_abi import (
    _EnthalpyResult as _Result,
    _EnergyOptions as _EnergyOptions,
    _EnergyOptionsV2 as _EnergyOptionsV2,
    _EnergyResult,
    _energy_options as _energy_options,
    _energy_algorithm_query,
)
from ._stage_capture_abi import _result_info, _energy_result_info


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


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('context', ct.c_void_p)]


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
        try:
            self.call = self.library.tpmshx_solve_enthalpy_v2
        except AttributeError as error:
            raise ValueError('native library lacks direct T-SOU execution; rebuild the library') from error
        self.version_query = _energy_algorithm_query(self.library)
        double_p, size_p = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
        self.call.argtypes = [size_p, ct.POINTER(double_p), size_p, ct.POINTER(_Config), ct.c_double,
                             ct.POINTER(_Callbacks), ct.POINTER(_Result), ct.POINTER(_EnergyResult),
                             ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int

    def __call__(self, Nx, Ny, Nz, dx, dy, dz, eps_arr, K_ss,
                 h_vA_field, h_vB_field, T_inA, T_inB, P_A, P_B,
                 *, mass_flux_A, mass_flux_B, fluid_A='sco2', fluid_B='sco2',
                 eps_A_field=None, eps_B_field=None, pressure_A_field=None,
                 pressure_B_field=None, Ta_init=None, Tb_init=None, Ts_init=None,
                 n_outer=3000, n_sweep=5, omega=.6, tol=2e-5,
                 cancel_check=None, coupled_energy_tol=None, equation_energy_tol=None,
                 temperature_tol_K=1e-8):
        from sjtu_tpmshx.data_types.compute_config import validate_enthalpy_algorithm
        validate_enthalpy_algorithm('temperature_sou', temperature_tol_K)
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
        fluid_codes = {'air': 0, 'water': 1, 'sco2': 2, 'co2': 3}
        if fluid_A not in fluid_codes or fluid_B not in fluid_codes:
            raise ValueError('native true-h supports air, water, sco2 and co2')
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
        result, energy, error = _Result(), _EnergyResult(), ct.create_string_buffer(2048)
        status = self.call((ct.c_size_t * 3)(*shape), pointers, sizes, ct.byref(config), temperature_tol_K,
                           ct.byref(callbacks), ct.byref(result), ct.byref(energy), error, len(error))
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
        _energy_result_info(info, energy, temperature_tol=temperature_tol_K, abi=self.abi,
                            version_query=self.version_query)
        if info['energy_algorithm'] != 'temperature_sou':
            raise RuntimeError('native direct energy did not execute T-SOU')
        info['effective_settings'].update(entry_version=2, require_enthalpy_update_on_temperature=True,
                                          coolprop_version=result.coolprop_version.decode('utf-8'))
        info['_native_state'].update(energy_algorithm=info['energy_algorithm'],
                                     energy_algorithm_version=info['energy_algorithm_version'])
        return state[2], state[3], state[4], info
