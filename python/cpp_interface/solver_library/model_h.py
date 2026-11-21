"""Thin binding to the complete fixed-flow 2D/3D model-h C driver.

Inputs are physical-axis signed mass faces and prepared coefficients. Numerical
iteration, Anderson trials and final energy certificates all remain native.
"""
import ctypes as ct
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.run_control.cancellation import CancelledError
from ._thermal_abi import _Callbacks, _Cancel as _Cancel, _Progress as _Progress, make_callbacks
from ._thermal_abi import (
    _IterationOptions as _IterationOptions,
    _IterationRecord as _IterationRecord,
    _IterationRecords as _IterationRecords,
    _Acceleration as _Acceleration,
    _iteration_options as _iteration_options,
    _ModelHResult as _Result,
)
from ._stage_capture_abi import (
    _copy_iteration_records as _copy_iteration_records,
    _plane_info,
    _volume_info,
    _model_h_algorithm,
)


class _Config(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in
                ('dimension', 'fluid_a', 'fluid_b', 'direction_a', 'direction_b',
                 'warm_start', 'accelerate', 'red_black')]
    _fields_ += [(n, ct.c_size_t) for n in ('max_iterations', 'chunk_iterations')]
    _fields_ += [(n, ct.c_double) for n in
                 ('inlet_a', 'inlet_b', 'q_relative_tolerance', 'alpha_a', 'alpha_solid', 'alpha_b')]


class NativeModelHDriver:
    """Explicit fixed-flow capability; construction never changes dispatch defaults."""

    def __init__(self, library):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError('native model-h library must be an absolute path')
        self.path = path.resolve(strict=True)
        self.library = ct.CDLL(str(self.path))
        version = self.library.tpmshx_model_h_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        self.abi = version()
        if self.abi != 1:
            raise ValueError(f'unsupported model-h ABI: {self.abi}; expected 1')
        self.call = self.library.tpmshx_solve_model_h_v1
        double_p, size_p = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
        self.call.argtypes = [size_p, ct.POINTER(double_p), size_p, ct.POINTER(_Config),
                             ct.POINTER(_Callbacks), ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
        self.call.restype = ct.c_int
        self.release = self.library.tpmshx_model_h_release_v1
        self.release.argtypes, self.release.restype = [ct.POINTER(_Result)], None

    def __call__(self, *, widths, conductivity, exchange, mass_faces, directions, inlets,
                 fluids, profiles=(None, None), openings=(None, None), initial=None,
                 sources=(None, None, None), max_iterations=3000, chunk_iterations=250,
                 q_relative_tolerance=1e-4, alpha=None, accelerate=False, red_black=False,
                 cancel_check=None, progress=None):
        dimension = len(widths)
        if dimension not in (2, 3):
            raise ValueError('native model-h requires two or three coordinate widths')
        algorithm = _model_h_algorithm(self.library, dimension)
        widths = [np.require(x, dtype=np.float64, requirements=['C', 'A']) for x in widths]
        if any(x.ndim != 1 or not x.size for x in widths):
            raise ValueError('native model-h widths must be nonempty vectors')
        shape = tuple(len(x) for x in widths)
        maximum = ct.c_size_t(-1).value
        budget, chunk = operator.index(max_iterations), operator.index(chunk_iterations)
        if not 0 <= budget <= maximum or not 0 < chunk <= maximum:
            raise ValueError('invalid native model-h iteration budget')
        if len(fluids) != 2 or any(f not in ('air', 'water') for f in fluids):
            raise ValueError('native model-h supports air/water fluids')
        directions = tuple(operator.index(x) for x in directions)
        if len(directions) != 2 or any(not 0 <= d < 2*dimension for d in directions):
            raise ValueError('invalid native model-h flow directions')
        if not (len(conductivity) == 3 and len(exchange) == len(mass_faces) == len(inlets)
                == len(profiles) == len(openings) == 2 and len(sources) == 3):
            raise ValueError('invalid native model-h side table')

        def array(value, expected, optional=False):
            if value is None and optional:
                return np.empty(0)
            value = np.asarray(value, dtype=np.float64)
            if value.shape != expected:
                raise ValueError(f'model-h array shape {value.shape} does not match {expected}')
            return np.require(value, requirements=['C', 'A'])

        if dimension == 2 and any(x is not None for x in sources):
            raise ValueError('2D model-h does not support explicit sources')
        masses, side_arrays = [], []
        for s in range(2):
            if len(mass_faces[s]) != dimension:
                raise ValueError('model-h requires a signed mass-face array for each axis')
            faces = tuple(array(x, tuple(n + int(axis == k) for k, n in enumerate(shape)))
                          for axis, x in enumerate(mass_faces[s]))
            masses.append(faces)
            boundary_shape = tuple(n for axis, n in enumerate(shape) if axis != directions[s] // 2)
            side_arrays.extend([array(conductivity[s], shape), array(exchange[s], shape), *faces,
                                *([np.empty(0)] if dimension == 2 else []),
                                array(profiles[s], boundary_shape, True), array(openings[s], boundary_shape, True),
                                array(sources[s], shape, True)])
        if initial is not None and len(initial) != 3:
            raise ValueError('model-h warm start requires A/B/solid temperatures')
        state = [np.empty(shape) for _ in range(3)] if initial is None else [
            np.array(array(x, shape), order='C', copy=True) for x in initial]
        arrays = [*widths, *([np.ones(1)] if dimension == 2 else []), array(conductivity[2], shape),
                  array(sources[2], shape, True), *side_arrays, *state]
        if alpha is None:
            alpha = (.2, 1., .2) if dimension == 2 else (.7, .7, .7)
        if len(alpha) != 3:
            raise ValueError('model-h relaxation requires A/solid/B values')
        config = _Config(dimension, *(int(f == 'water') for f in fluids), *directions,
                         initial is not None, bool(accelerate), bool(red_black), budget, chunk,
                         *inlets, q_relative_tolerance, *alpha)
        callbacks, callback_errors = make_callbacks(cancel_check, progress)
        double_p = ct.POINTER(ct.c_double)
        pointers = (double_p * len(arrays))(*(x.ctypes.data_as(double_p) for x in arrays))
        sizes = (ct.c_size_t * len(arrays))(*(x.size for x in arrays))
        result, error = _Result(), ct.create_string_buffer(2048)
        try:
            code = self.call((ct.c_size_t * 3)(*shape, *([1] if dimension == 2 else [])), pointers, sizes,
                             ct.byref(config), ct.byref(callbacks), ct.byref(result), error, len(error))
            if callback_errors:
                raise callback_errors[0]
            if code:
                exception = {1: ValueError, 2: FloatingPointError}.get(code, RuntimeError)
                raise exception(error.value.decode('utf-8', errors='replace'))
            if result.stop == 2:
                raise CancelledError('compute cancelled by user')
            if result.dimension != dimension or result.stop not in (0, 1) or not result.audit_available:
                raise RuntimeError('native model-h returned an invalid result contract')
            info = dict(converged=result.stop == 0, iterations=result.iterations, residual=result.residual,
                        native_metadata=dict(abi=self.abi, algorithm=algorithm, red_black=bool(config.red_black)))
            checks = [result.finishing_checks[i] for i in range(result.finishing_count)]
            if dimension == 2:
                info['model_h_balance'] = _plane_info(result, shape, widths, masses)
                info['energy_finishing_checks'] = [dict(iterations=c.iterations, passed=bool(c.gates[0]),
                                                       equations_ok=bool(c.gates[1])) for c in checks]
            else:
                info.update(_volume_info(result, shape))
                names = [f'{side} strict {metric} < 1 %' for side in ('A', 'B') for metric in ('global', 'cellmax')]
                names += ['full-volume LTNE source balance < 1 %', 'physical boundary data complete']
                info['energy_finishing_checks'] = [dict(iterations=c.iterations,
                    gates=[(name, bool(value)) for name, value in zip(names, c.gates)]) for c in checks]
            return *state, info
        finally:
            if result.owner:
                self.release(ct.byref(result))
