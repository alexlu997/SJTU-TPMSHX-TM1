"""Explicit prepared-field binding to the independent SIMPLE 2D C ABI.

The caller owns geometry/closure preparation, resolved numerical controls,
physical-axis mapping, thermal coupling and final physical acceptance.
Importing this module changes no production dispatch or fallback policy.
"""
import ctypes as ct
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from ._simple_abi import _Callbacks, _Cancel, _F2, _Mass, _Momentum, _Progress


class _Config(ct.Structure):
    _fields_ = [('max_iterations', ct.c_size_t), ('inner_sweeps', ct.c_size_t),
        *[(name, ct.c_double) for name in ('alpha_velocity', 'alpha_pressure', 'alpha_density',
            'pressure_reference_absolute', 'gas_constant', 'cf_anisotropy')],
        *[(name, ct.c_uint32) for name in ('ideal_gas', 'massflux_inlet', 'close_outlet_on_exit')],
        *[(name, ct.c_double) for name in ('reference_inlet_velocity', 'taper_flux_scale', 'inlet_density_reference')],
        ('have_inlet_density_reference', ct.c_uint32), ('f2', _F2)]


class _Result(ct.Structure):
    _fields_ = [*[(name, ct.c_uint32) for name in
        ('stop', 'converged', 'post_closure_measured', 'post_closure_certified')],
        ('iterations', ct.c_size_t), ('pressure_clip_hits', ct.c_size_t),
        ('legacy_residual', ct.c_double), ('momentum', _Momentum), ('mass', _Mass),
        ('have_massflux_target', ct.c_uint32), ('massflux_target', ct.c_double),
        ('pressure_success', ct.c_uint32), ('pressure_superlu_info', ct.c_int),
        ('pressure_relative_residual', ct.c_double), ('pressure_pin_maximum', ct.c_double),
        ('pressure_exit', ct.c_char*64), ('pressure_detail', ct.c_char*512)]


_FIELDS = ('epsilon', 'viscosity', 'effective_viscosity', 'permeability', 'forchheimer',
           'temperature', 'u', 'v', 'pressure', 'pressure_correction', 'd_u', 'd_v',
           'density', 'inlet_velocity', 'inlet_fraction', 'outlet_u_fraction')
_STOPS = ('ongoing', 'tol', 'stall', 'max_iter', 'nonfinite', 'cancelled', 'pressure_failure', 'post_closure')


def _integer(value, maximum):
    number = operator.index(value)
    if number < 0 or number > maximum:
        raise ValueError('native SIMPLE integer is outside its ABI range')
    return number


def _error(status, error):
    if status:
        exception = {1: ValueError, 2: FloatingPointError}.get(status, RuntimeError)
        raise exception(error.value.decode('utf-8', errors='replace'))


def _result_dict(native, abi):
    if native.stop >= len(_STOPS):
        raise RuntimeError('native SIMPLE returned an invalid stop contract')
    result = dict(exit_reason=_STOPS[native.stop], converged=bool(native.converged),
        iterations=native.iterations, post_closure_measured=bool(native.post_closure_measured),
        post_closure_certified=bool(native.post_closure_certified),
        pressure_clip_hits=native.pressure_clip_hits, legacy_residual=native.legacy_residual,
        massflux_target=native.massflux_target if native.have_massflux_target else None,
        momentum=dict(maximum=native.momentum.maximum, numerator=list(native.momentum.numerator),
            denominator=list(native.momentum.denominator), component=list(native.momentum.component)),
        mass={name: getattr(native.mass,name) for name, _ in _Mass._fields_},
        pressure=dict(success=bool(native.pressure_success), superlu_info=native.pressure_superlu_info,
            relative_residual=native.pressure_relative_residual, pin_maximum=native.pressure_pin_maximum,
            exit=native.pressure_exit.decode('utf-8', errors='replace'),
            detail=native.pressure_detail.decode('utf-8', errors='replace')),
        native_abi=abi)
    return result


class NativeSimple2D:
    """One prepared +y grid and port support; warm target/history persist.

    Use as a context manager or call close(). Mutable fields are updated in
    place; failures can leave partial state. Separate handles may run
    concurrently, but one handle cannot be called concurrently or reentrantly.
    """

    def __init__(self, library, *, dx, dy, outlet_open):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native SIMPLE library must be an absolute path')
        self.path = path.resolve(strict=True)
        self.library = ct.CDLL(str(self.path))
        self._handle = ct.c_void_p()
        self.last_result = None
        version = self.library.tpmshx_simple_2d_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 1:
            raise ValueError(f'unsupported SIMPLE 2D ABI: {self.abi}; expected 1')
        dp, sp, cp = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_char)
        self._create = self.library.tpmshx_simple_2d_create_v1
        self._create.argtypes = [ct.c_size_t, ct.c_size_t, dp, dp, ct.POINTER(ct.c_uint8),
                                ct.POINTER(ct.c_void_p), cp, ct.c_size_t]
        self._create.restype = ct.c_int
        self._destroy = self.library.tpmshx_simple_2d_destroy
        self._destroy.argtypes, self._destroy.restype = [ct.c_void_p], None
        self._solve = self.library.tpmshx_simple_2d_solve_v1
        self._solve.argtypes = [ct.c_void_p, ct.POINTER(dp), sp, ct.POINTER(_Config),
                               ct.POINTER(_Callbacks), ct.POINTER(_Result), cp, ct.c_size_t]
        self._solve.restype = ct.c_int
        self._history = self.library.tpmshx_simple_2d_history_v1
        self._history.argtypes = [ct.c_void_p, ct.c_uint32, dp, ct.c_size_t, sp, cp, ct.c_size_t]
        self._history.restype = ct.c_int
        dx, dy = (np.require(np.asarray(value, dtype=np.float64), requirements=['C', 'A'])
                  for value in (dx, dy))
        if dx.ndim != 1 or dy.ndim != 1 or not dx.size or not dy.size:
            raise ValueError('native SIMPLE widths must be nonempty one-dimensional arrays')
        self.shape = (dx.size, dy.size)
        outlet = np.asarray(outlet_open)
        if outlet.shape != (dx.size,) or not np.isin(outlet, (0, 1)).all():
            raise ValueError('native SIMPLE outlet support requires one 0/1 value per cross-stream cell')
        outlet = np.ascontiguousarray(outlet, dtype=np.uint8)
        error = ct.create_string_buffer(1024)
        _error(self._create(*self.shape, dx.ctypes.data_as(dp), dy.ctypes.data_as(dp),
            outlet.ctypes.data_as(ct.POINTER(ct.c_uint8)), ct.byref(self._handle), error, len(error)), error)

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._handle:
            self._destroy(self._handle)
            self._handle = ct.c_void_p()

    def _require_open(self):
        if not self._handle:
            raise ValueError('native SIMPLE handle is closed')

    def solve(self, *, fields, settings, cancel_check=None, progress_cb=None):
        """Run the C++ loop on prepared fields with explicit resolved settings.

        Field names follow simple_2d_c_api.h, with mu/mu_eff/K/cF spelled
        viscosity/effective_viscosity/permeability/forchheimer. Settings mirror
        tpmshx_simple_2d_config_v1; f2 is its nested mapping, and
        inlet_density_reference may be None. The eight mutable fields
        u..inlet_velocity require writable, aligned C-order float64.
        """
        self._require_open()
        self.last_result = None
        nx, ny = self.shape
        shapes = [(nx, ny)]*6 + [(nx+1, ny), (nx, ny+1), (nx, ny), (nx, ny),
                  (nx+1, ny), (nx, ny+1), (nx, ny), (nx,), (nx,), (nx+1,)]
        arrays = []
        for i, (name, shape) in enumerate(zip(_FIELDS, shapes)):
            value = fields[name]
            if 6 <= i <= 13:
                if (not isinstance(value, np.ndarray) or value.dtype != np.float64
                        or not value.flags.c_contiguous or not value.flags.aligned or not value.flags.writeable):
                    raise ValueError(f'native SIMPLE mutable field {name} requires writable aligned C-order float64')
            else:
                value = np.require(np.asarray(value, dtype=np.float64), requirements=['C', 'A'])
            if value.shape != shape:
                raise ValueError(f'native SIMPLE field {name} shape {value.shape} does not match {shape}')
            arrays.append(value)
        config = _Config()
        maximum = ct.c_size_t(-1).value
        for name, kind in _Config._fields_:
            if name in ('f2', 'inlet_density_reference', 'have_inlet_density_reference'):
                continue
            value = settings[name]
            if kind is ct.c_size_t:
                value = _integer(value, maximum)
            elif kind is ct.c_uint32:
                value = _integer(value, 1)
            setattr(config, name, value)
        reference = settings['inlet_density_reference']
        config.have_inlet_density_reference = reference is not None
        config.inlet_density_reference = 0. if reference is None else reference
        for name, kind in _F2._fields_:
            value = settings['f2'][name]
            setattr(config.f2, name, _integer(value, maximum) if kind is ct.c_size_t else value)
        callback_errors = []

        @_Cancel
        def cancelled(_):
            if callback_errors:
                return 1
            try:
                return int(bool(cancel_check())) if cancel_check is not None else 0
            except BaseException as error:
                callback_errors.append(error)
                return 1

        @_Progress
        def progressed(_, iteration, residual):
            if callback_errors:
                return
            try:
                progress_cb(iteration, residual)
            except BaseException as error:
                callback_errors.append(error)

        callbacks = _Callbacks(cancelled if cancel_check is not None or progress_cb is not None else _Cancel(),
                               progressed if progress_cb is not None else _Progress(), None)
        dp = ct.POINTER(ct.c_double)
        pointers = (dp*len(arrays))(*(value.ctypes.data_as(dp) for value in arrays))
        sizes = (ct.c_size_t*len(arrays))(*(value.size for value in arrays))
        native, error = _Result(), ct.create_string_buffer(2048)
        status = self._solve(self._handle,pointers,sizes,ct.byref(config),ct.byref(callbacks),
                             ct.byref(native),error,len(error))
        _error(status,error)
        result = _result_dict(native, self.abi)
        self.last_result = result
        if callback_errors:
            raise callback_errors[0]
        if native.stop == 5:
            raise CancelledError('compute cancelled by user')
        return result

    def history(self, kind):
        """Copy a recorded scalar history or rows of eight momentum values."""
        self._require_open()
        kind = _integer(kind, 3)
        needed, error = ct.c_size_t(), ct.create_string_buffer(1024)
        _error(self._history(self._handle,kind,None,0,ct.byref(needed),error,len(error)),error)
        values = np.empty(needed.value, dtype=np.float64)
        _error(self._history(self._handle,kind,values.ctypes.data_as(ct.POINTER(ct.c_double)),
            values.size,ct.byref(needed),error,len(error)),error)
        return values.reshape(-1, 8) if kind == 3 else values
