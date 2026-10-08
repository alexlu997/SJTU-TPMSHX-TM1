"""Explicit thin binding to complete native temperature drivers.

Callers prepare geometry, properties and physical-axis velocity fields. All
thermal iteration, conservative MAC and final equation evidence run in C++.
The same instance retains its last MAC grid hierarchy across outer calls.
"""
import ctypes as ct
import operator
from pathlib import Path
import weakref

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError


class _Config(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('scheme', 'direction_a', 'direction_b',
        'warm_start', 'second_order_b', 'conservative', 'red_black', 'accelerate')]
    _fields_ += [(n, ct.c_size_t) for n in ('max_iterations', 'chunk_iterations')]
    _fields_ += [(n, ct.c_double) for n in
        ('inlet_a', 'inlet_b', 'q_relative_tolerance', 'alpha_a', 'alpha_solid', 'alpha_b')]


class _Residual(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('cells', ct.POINTER(ct.c_double)), ('cell_count', ct.c_size_t)]
    _fields_ += [(n, ct.c_double) for n in ('sum', 'maximum', 'exchange', 'global_ratio', 'cell_ratio')]


class _Projection(ct.Structure):
    _fields_ = [('skipped', ct.c_uint32), ('used_bordered_lu', ct.c_uint32), ('cg_iterations', ct.c_size_t),
                ('rhs_mean', ct.c_double), ('residual_relative', ct.c_double)]


class _Result(ct.Structure):
    _fields_ = [('scheme', ct.c_uint32), ('stop', ct.c_uint32), ('iterations', ct.c_size_t),
                ('residual', ct.c_double), ('q_b', ct.c_double), ('fluid', _Residual*2),
                ('projection', _Projection*2), ('owner', ct.c_void_p)]


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_size_t)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('context', ct.c_void_p)]


def _temperature_algorithm(library, scheme):
    """Copy the recipe identity from the same native library used to solve."""
    try:
        query = library.tpmshx_temperature_algorithm_v1
    except AttributeError as error:
        raise ValueError('native library lacks tpmshx_temperature_algorithm_v1') from error
    query.argtypes, query.restype = [ct.c_uint32], ct.c_char_p
    identity = query(scheme)
    if not identity:
        raise ValueError(f'native library has no temperature algorithm for scheme {scheme}')
    return identity.decode('ascii')


class NativeTemperatureDriver:
    """Prepared 2D/3D temperature capability; never changes default dispatch.

    One instance is not concurrently callable. Use separate instances for
    independent jobs. ``close()`` releases the retained MAC cache; collection
    also releases it. Returned fields/evidence own their NumPy storage.
    """

    def __init__(self, library):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native temperature library must be an absolute path')
        self.path = path.resolve(strict=True)
        self.library = ct.CDLL(str(self.path))
        version = self.library.tpmshx_temperature_driver_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 1:
            raise ValueError(f'unsupported temperature driver ABI: {self.abi}; expected 1')
        self.algorithms = tuple(_temperature_algorithm(self.library, mode) for mode in range(3))
        double_p, size_p, char_p = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_char)
        self.call = self.library.tpmshx_solve_temperature_v1
        self.call.argtypes = [ct.c_void_p, size_p, ct.POINTER(double_p), size_p, ct.POINTER(_Config),
                             ct.POINTER(_Callbacks), ct.POINTER(_Result), char_p, ct.c_size_t]
        self.call.restype = ct.c_int
        self.release = self.library.tpmshx_temperature_release_v1
        self.release.argtypes, self.release.restype = [ct.POINTER(_Result)], None
        create = self.library.tpmshx_temperature_driver_create_v1
        create.argtypes, create.restype = [ct.POINTER(ct.c_void_p), char_p, ct.c_size_t], ct.c_int
        destroy = self.library.tpmshx_temperature_driver_destroy_v1
        destroy.argtypes, destroy.restype = [ct.c_void_p], None
        self.handle = ct.c_void_p()
        error = ct.create_string_buffer(2048)
        code = create(ct.byref(self.handle), error, len(error))
        if code:
            raise RuntimeError(error.value.decode('utf-8', errors='replace'))
        self._finalizer = weakref.finalize(self, destroy, self.handle)

    def close(self):
        self._finalizer()

    def __call__(self, *, scheme, widths, conductivity, exchange, epsilon, rho_cp,
                 velocity, directions, inlets, profiles=(None, None), openings=(None, None),
                 inlet_capacity=(None, None), initial=None, prescribed_b=None,
                 sources=(None, None, None), max_iterations=None, chunk_iterations=None,
                 q_relative_tolerance=None, tol=1e-6, alpha=None, second_order_b=None,
                 conservative=False, red_black=False, accelerate=False,
                 cancel_check=None, progress=None):
        if not self._finalizer.alive:
            raise RuntimeError('native temperature driver is closed')
        schemes = {'cell_centered_2d': 0, 'cell_centered_3d': 1, 'staggered_3d': 2}
        if scheme not in schemes:
            raise ValueError(f'unsupported native temperature scheme: {scheme}')
        mode = schemes[scheme]
        dimension = 2 if mode == 0 else 3
        if len(widths) != dimension:
            raise ValueError('temperature scheme and width dimension disagree')
        if accelerate:
            raise ValueError('non-model-h temperature does not support acceleration')
        if mode != 2 and conservative:
            raise ValueError('conservative projection requires staggered temperature')
        if mode == 1 and red_black:
            raise ValueError('CC3D temperature has no RB mode')
        if any(len(x) != 2 for x in (exchange, epsilon, rho_cp, velocity, directions, inlets,
                                     profiles, openings, inlet_capacity)) or len(conductivity) != 3 or len(sources) != 3:
            raise ValueError('temperature requires two fluid sides and one solid')
        widths = [np.require(np.asarray(x, dtype=np.float64), requirements=['C', 'A']) for x in widths]
        if any(x.ndim != 1 or x.size == 0 for x in widths):
            raise ValueError('temperature widths must be nonempty vectors')
        shape = tuple(x.size for x in widths)
        if mode != 0 and shape[2] <= 1:
            raise ValueError('3D temperature requires nz>1; delegate nz=1 explicitly to 2D')
        grid_shape = (*shape, 1) if dimension == 2 else shape
        directions = tuple(operator.index(x) for x in directions)
        if any(x < 0 or x >= 2*dimension for x in directions):
            raise ValueError('invalid temperature inlet direction')
        maximum = ct.c_size_t(-1).value
        budget = operator.index((50000 if dimension == 2 else 10000) if max_iterations is None else max_iterations)
        chunk = operator.index((500 if dimension == 2 else 250) if chunk_iterations is None else chunk_iterations)
        if budget < 0 or chunk <= 0 or max(budget, chunk) > maximum:
            raise ValueError('invalid temperature iteration/chunk budget')
        qtol = (min(float(tol)*2e-3, 1e-3) if dimension == 2 else max(float(tol)*10, 1e-4)) if q_relative_tolerance is None else float(q_relative_tolerance)
        alpha = (.7, 1., 1.) if alpha is None and dimension == 2 else ((.7, .7, .7) if alpha is None else tuple(alpha))
        if len(alpha) != 3:
            raise ValueError('temperature alpha requires A, solid, B')
        sou_b = dimension == 3 if second_order_b is None else bool(second_order_b)

        def array(value, expected, *, scalar=False, optional=False):
            if value is None and optional:
                return np.empty(0)
            result = np.asarray(value, dtype=np.float64)
            if scalar and result.ndim == 0:
                result = np.full(expected, float(result))
            if result.shape != expected:
                raise ValueError(f'temperature array shape {result.shape} does not match {expected}')
            return np.require(result, requirements=['C', 'A'])

        if initial is not None and len(initial) != 3:
            raise ValueError('warm temperature requires all three phase fields')
        state = [np.empty(shape) for _ in range(3)] if initial is None else [
            np.array(array(value, shape), order='C', copy=True) for value in initial]
        prescribed = array(prescribed_b, shape, optional=True)
        arrays = [*widths, *([np.ones(1)] if dimension == 2 else []),
                  array(conductivity[2], shape, scalar=True), array(sources[2], shape, optional=True), prescribed]
        for side in range(2):
            if len(velocity[side]) != dimension:
                raise ValueError('temperature velocity tuple dimension mismatch')
            expected_velocity = [tuple(n+(axis == ax) for ax, n in enumerate(shape)) for axis in range(3)] if mode == 2 else [shape]*dimension
            speeds = [array(value, expected) for value, expected in zip(velocity[side], expected_velocity)]
            if dimension == 2:
                speeds.append(np.empty(0))
            patch = tuple(n for axis, n in enumerate(shape) if axis != directions[side]//2)
            arrays += [array(conductivity[side], shape, scalar=True), array(exchange[side], shape, scalar=True),
                       array(epsilon[side], shape, scalar=True), array(rho_cp[side], shape, scalar=True), *speeds,
                       array(profiles[side], patch, optional=True), array(openings[side], patch, optional=True),
                       array(inlet_capacity[side], patch, optional=True), array(sources[side], shape, optional=True)]
        arrays += state
        config = _Config(mode, *directions, initial is not None, sou_b, bool(conservative), bool(red_black), 0,
                         budget, chunk, *inlets, qtol, *alpha)
        callback_errors = []

        @_Cancel
        def cancelled(_):
            if callback_errors:
                return 1
            try:
                return int(cancel_check()) if cancel_check is not None else 0
            except BaseException as error:
                callback_errors.append(error)
                return 1

        @_Progress
        def progressed(_, done, total):
            if callback_errors:
                return
            try:
                progress(done, total)
            except BaseException as error:
                callback_errors.append(error)

        callbacks = _Callbacks(cancelled, progressed if progress is not None else _Progress(), None)
        double_p = ct.POINTER(ct.c_double)
        pointers = (double_p*len(arrays))(*(x.ctypes.data_as(double_p) for x in arrays))
        sizes = (ct.c_size_t*len(arrays))(*(x.size for x in arrays))
        result, error = _Result(), ct.create_string_buffer(2048)
        try:
            code = self.call(self.handle, (ct.c_size_t*3)(*grid_shape), pointers, sizes, ct.byref(config),
                             ct.byref(callbacks), ct.byref(result), error, len(error))
            if callback_errors:
                raise callback_errors[0]
            if code:
                exception = {1: ValueError, 2: FloatingPointError}.get(code, RuntimeError)
                raise exception(error.value.decode('utf-8', errors='replace'))
            if result.stop == 2:
                raise CancelledError('compute cancelled by user')
            if result.scheme != mode or result.stop not in (0, 1):
                raise RuntimeError('native temperature returned an invalid result contract')
            info = dict(converged=result.stop == 0, iterations=result.iterations, residual=result.residual)
            if dimension == 3:
                info['delegated_to_2d'] = False
            evidence = dict(scheme=scheme, driver='cpp', driver_abi=self.abi,
                            algorithm=self.algorithms[mode], Q_B=result.q_b,
                            duty_units='W/m' if dimension == 2 else 'W', equations={}, projection={})
            if mode == 2 and conservative:
                for label, residual, projected in zip(('A', 'B'), result.fluid, result.projection):
                    info[f'eps_{label}_strict'] = residual.global_ratio if residual.available else None
                    info[f'eps_{label}_strict_cellmax'] = residual.cell_ratio if residual.available else None
                    if residual.available:
                        cells = np.ctypeslib.as_array(residual.cells, shape=(residual.cell_count,)).copy().reshape(shape)
                        evidence['equations'][label] = dict(residual_W=cells, sum_W=residual.sum,
                            max_abs_W=residual.maximum, exchange_W=residual.exchange)
                    evidence['projection'][label] = dict(skipped=bool(projected.skipped),
                        used_bordered_lu=bool(projected.used_bordered_lu), cg_iterations=projected.cg_iterations,
                        rhs_mean=projected.rhs_mean, residual_relative=projected.residual_relative)
            info['_native_temperature'] = evidence
            return *state, info
        finally:
            if result.owner:
                self.release(ct.byref(result))
