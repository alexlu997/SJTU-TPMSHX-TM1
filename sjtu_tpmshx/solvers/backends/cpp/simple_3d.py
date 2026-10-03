"""Explicit thin adapter for the independent prepared 3D SIMPLE C ABI.

The caller supplies material, boundary and mutable staggered fields, including
any explicit coarse seed. All equations, pressure solves, rho/inlet updates,
raw face flows and F2 decisions execute in C++. No default route is changed.
"""
import ctypes as ct
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from ._simple_abi import _Callbacks, _Cancel, _F2, _Mass, _Momentum, _Progress


class _Config(ct.Structure):
    _fields_ = [*[(name, ct.c_size_t) for name in
        ('max_iterations', 'inner_sweeps', 'pressure_rebuild_every')],
        *[(name, ct.c_double) for name in
          ('alpha_velocity', 'alpha_pressure', 'alpha_density',
           'pressure_reference_absolute', 'gas_constant', 'pressure_diagonal_drift')],
        *[(name, ct.c_uint32) for name in
          ('ideal_gas', 'massflux_inlet', 'second_order_upwind',
           'adaptive_pressure_tolerance', 'track_momentum', 'ordering')],
        ('convergence', _F2)]


class _Pressure(ct.Structure):
    _fields_ = [('success', ct.c_uint32), *[(name, ct.c_size_t) for name in
        ('iterations', 'rebuild_count', 'hierarchy_bytes')], ('superlu_info', ct.c_int),
        *[(name, ct.c_double) for name in
          ('rhs_scale', 'relative_residual', 'absolute_residual', 'iterative_relative_residual',
           'pin_max_abs', 'diagonal_drift', 'build_seconds', 'solve_seconds')],
        ('method', ct.c_char*32), ('exit', ct.c_char*64), ('amg_exit', ct.c_char*64),
        ('rebuild_reason', ct.c_char*64), ('detail', ct.c_char*512)]


class _Result(ct.Structure):
    _fields_ = [*[(name, ct.c_uint32) for name in
        ('stop', 'converged', 'post_closure_measured', 'post_closure_certified', 'mass_faces_available')],
        *[(name, ct.c_size_t) for name in ('iterations', 'pressure_clip_hits', 'post_closure_rejections')],
        ('legacy_residual', ct.c_double), ('legacy_reference', ct.c_double),
        ('momentum', _Momentum), ('mass', _Mass), ('pressure', _Pressure)]


_DOUBLE = ct.POINTER(ct.c_double)
_SIZE = ct.POINTER(ct.c_size_t)
_MATERIAL = ('epsilon', 'viscosity', 'effective_viscosity', 'permeability', 'forchheimer', 'temperature')
_STATE = ('u', 'v', 'w', 'pressure', 'pressure_correction', 'd_u', 'd_v', 'd_w', 'density', 'inlet_velocity')
_STOPS = {1: 'tol', 2: 'stall', 3: 'max_iter', 4: 'nonfinite', 5: 'cancelled',
          6: 'pressure_failure', 7: 'post_closure'}


def _status(code, error):
    if code:
        exception = {1: ValueError, 2: FloatingPointError}.get(code, RuntimeError)
        raise exception(error.value.decode('utf-8', errors='replace'))


def _count(value, *, zero=False):
    value = operator.index(value)
    if value < (0 if zero else 1) or value > ct.c_size_t(-1).value:
        raise ValueError('SIMPLE count is outside native size_t bounds')
    return value


def _array(value, shape, *, mutable=False):
    if mutable:
        if (not isinstance(value, np.ndarray) or value.dtype != np.float64
                or not value.flags.c_contiguous or not value.flags.aligned or not value.flags.writeable):
            raise ValueError('mutable SIMPLE fields require writable aligned C-order float64 arrays')
        array = value
    else:
        array = np.require(value, dtype=np.float64, requirements=['C', 'A'])
    if array.shape != shape:
        raise ValueError(f'SIMPLE array shape {array.shape} does not match {shape}')
    return array


class NativeSimple3D:
    """One prepared +y grid/support with persistent native warm-solve state.

    Use as a context manager or call close(). Independent instances may run
    concurrently; an instance and its arrays have one caller at a time.
    """

    def __init__(self, library, dx, dy, dz, outlet_open):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native SIMPLE library must be an absolute path')
        self.path = path.resolve(strict=True)
        self.library = ct.CDLL(str(self.path))
        self._handle = ct.c_void_p()
        version = self.library.tpmshx_simple_3d_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 1:
            raise ValueError(f'unsupported 3D SIMPLE ABI {self.abi}; expected 1')
        widths = [np.require(value, dtype=np.float64, requirements=['C', 'A']) for value in (dx, dy, dz)]
        if any(value.ndim != 1 or not value.size for value in widths):
            raise ValueError('SIMPLE grid widths must be nonempty one-dimensional arrays')
        self.shape = tuple(_count(value.size) for value in widths)
        opening = np.asarray(outlet_open)
        if opening.dtype not in (np.dtype(bool), np.dtype('uint8')) or opening.shape != (self.shape[0], self.shape[2]):
            raise ValueError('SIMPLE outlet_open requires bool/uint8 shape (nx,nz)')
        opening = np.require(opening, dtype=np.uint8, requirements=['C', 'A'])
        create = self.library.tpmshx_simple_3d_create_v1
        create.argtypes = [ct.c_size_t]*3 + [_DOUBLE]*3 + [ct.POINTER(ct.c_uint8), ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_char), ct.c_size_t]
        create.restype = ct.c_int
        self._destroy = self.library.tpmshx_simple_3d_destroy
        self._destroy.argtypes, self._destroy.restype = [ct.c_void_p], None
        self._call = self.library.tpmshx_simple_3d_solve_v1
        self._call.argtypes = [ct.c_void_p, ct.POINTER(_DOUBLE), _SIZE, ct.POINTER(_Config),
            ct.POINTER(_Callbacks), ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
        self._call.restype = ct.c_int
        self._history = self.library.tpmshx_simple_3d_history_v1
        self._history.argtypes = [ct.c_void_p, ct.c_uint32, _DOUBLE, ct.c_size_t,
            ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_char), ct.c_size_t]
        self._history.restype = ct.c_int
        error = ct.create_string_buffer(2048)
        _status(create(*self.shape, *(value.ctypes.data_as(_DOUBLE) for value in widths),
            opening.ctypes.data_as(ct.POINTER(ct.c_uint8)), ct.byref(self._handle), error, len(error)), error)
        self.last_result = None

    def close(self):
        if self._handle:
            self._destroy(self._handle)
            self._handle = ct.c_void_p()

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()

    def _require_open(self):
        if not self._handle:
            raise ValueError('native SIMPLE handle is closed')

    def history(self, kind='legacy'):
        self._require_open()
        code = {'legacy': 0, 'local_mass': 1, 'global_mass': 2, 'momentum': 3, 'massflux_target': 4}[kind]
        size, error = ct.c_size_t(), ct.create_string_buffer(2048)
        _status(self._history(self._handle, code, None, 0, ct.byref(size), error, len(error)), error)
        values = np.empty(size.value)
        _status(self._history(self._handle, code, values.ctypes.data_as(_DOUBLE), values.size,
            ct.byref(size), error, len(error)), error)
        if code == 3:
            return values.reshape(-1, 11)
        if code == 4 and values.size:
            return values.reshape(self.shape[0], self.shape[2])
        return values

    def solve(self, material, boundary, state, *, max_iter=3000, n_inner=1,
              alpha_u=.5, alpha_p=.2, alpha_rho=.3, P_ref_abs=101325., R_gas=287.05,
              pressure_rebuild_every=100, pressure_diagonal_drift=.05,
              ideal_gas=True, massflux_inlet=True, second_order_upwind=False,
              adaptive_pressure_tolerance=True, track_momentum=False, ordering='natural',
              mom_tol=1e-4, mass_local_tol=1e-6, mass_global_tol=1e-6,
              backflow_max=.01, velocity_check_tol=1e-4, stall_ratio=1e-3,
              confirmations=2, momentum_interval=5, stall_window=60,
              cancel_check=None, progress=None):
        """Update caller-owned state and return native diagnostics/raw mass faces.

        material keys: epsilon,viscosity,effective_viscosity,permeability,
        forchheimer,temperature. boundary: outlet_u_fraction,outlet_w_fraction.
        state: u,v,w,pressure,pressure_correction,d_u,d_v,d_w,density,
        inlet_velocity. All supplied state arrays are mutable float64 C-order;
        no Python numerical routine initializes, updates or certifies them.
        """
        self._require_open()
        self.last_result = None
        nx, ny, nz = self.shape
        faces = ((nx+1, ny, nz), (nx, ny+1, nz), (nx, ny, nz+1))
        state_shapes = (*faces, self.shape, self.shape, *faces, self.shape, (nx, nz))
        arrays = [_array(material[key], self.shape) for key in _MATERIAL]
        arrays += [_array(state[key], shape, mutable=True) for key, shape in zip(_STATE, state_shapes)]
        arrays += [_array(boundary['outlet_u_fraction'], (nx+1, nz)),
                   _array(boundary['outlet_w_fraction'], (nx, nz+1))]
        raw_mass = tuple(np.empty(shape) for shape in faces)
        arrays += list(raw_mass)
        flags = (ideal_gas, massflux_inlet, second_order_upwind, adaptive_pressure_tolerance, track_momentum)
        if any(value not in (0, 1) for value in flags):
            raise ValueError('SIMPLE flags must be bool or 0/1')
        if ordering not in ('natural', 'red_black'):
            raise ValueError('SIMPLE ordering must be natural or red_black')
        config = _Config(_count(max_iter), _count(n_inner), _count(pressure_rebuild_every),
            alpha_u, alpha_p, alpha_rho, P_ref_abs, R_gas, pressure_diagonal_drift,
            *(int(value) for value in flags), int(ordering == 'red_black'),
            _F2(mom_tol, mass_local_tol, mass_global_tol, backflow_max, velocity_check_tol,
                stall_ratio, _count(confirmations), _count(momentum_interval), _count(stall_window, zero=True)))
        callback_errors = []
        @_Cancel
        def cancelled(_):
            if callback_errors:
                return 1
            try:
                return int(cancel_check is not None and cancel_check())
            except BaseException as error:
                callback_errors.append(error)
                return 1
        @_Progress
        def report(_, iteration, residual):
            if not callback_errors:
                try:
                    if progress is not None:
                        progress(iteration, residual)
                except BaseException as error:
                    callback_errors.append(error)
        callbacks = _Callbacks(cancelled if cancel_check is not None or progress is not None else _Cancel(),
            report if progress is not None else _Progress(), None)
        pointers = (_DOUBLE*len(arrays))(*(value.ctypes.data_as(_DOUBLE) for value in arrays))
        sizes = (ct.c_size_t*len(arrays))(*(value.size for value in arrays))
        result, error = _Result(), ct.create_string_buffer(2048)
        status = self._call(self._handle, pointers, sizes, ct.byref(config), ct.byref(callbacks),
            ct.byref(result), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        _status(status, error)
        if result.stop not in _STOPS:
            raise RuntimeError('native SIMPLE returned an invalid stop contract')
        momentum, mass = result.momentum, result.mass
        pressure = {name: getattr(result.pressure, name) for name, _ in _Pressure._fields_}
        pressure = {name: value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
                    for name, value in pressure.items()}
        self.last_result = dict(exit_reason=_STOPS[result.stop], converged=bool(result.converged),
            iterations=result.iterations, post_closure_measured=bool(result.post_closure_measured),
            post_closure_certified=bool(result.post_closure_certified), pressure_clip_hits=result.pressure_clip_hits,
            post_closure_rejections=result.post_closure_rejections, legacy_residual=result.legacy_residual,
            legacy_reference=result.legacy_reference,
            momentum=dict(maximum=momentum.maximum, numerator=tuple(momentum.numerator),
                denominator=tuple(momentum.denominator), component=tuple(momentum.component)),
            mass={name: getattr(mass, name) for name, _ in _Mass._fields_}, pressure=pressure,
            raw_mass_flux=raw_mass if result.mass_faces_available else None,
            effective_settings=dict(driver='cpp', abi=self.abi, bootstrap='caller_supplied_seed',
                ordering=ordering, momentum_threads=1, blas_threads='library_managed',
                second_order_upwind=bool(second_order_upwind)))
        if result.stop == 5:
            raise CancelledError('compute cancelled by user')
        return self.last_result
