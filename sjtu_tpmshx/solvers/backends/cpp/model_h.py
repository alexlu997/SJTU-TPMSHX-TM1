"""Thin binding to the complete fixed-flow 2D/3D model-h C driver.

Inputs are physical-axis signed mass faces and prepared coefficients. Numerical
iteration, Anderson trials and final energy certificates all remain native.
"""
import ctypes as ct
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError


class _Array(ct.Structure):
    _fields_ = [('data', ct.POINTER(ct.c_double)), ('size', ct.c_size_t)]


class _Config(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in
                ('dimension', 'fluid_a', 'fluid_b', 'direction_a', 'direction_b',
                 'warm_start', 'accelerate', 'red_black')]
    _fields_ += [(n, ct.c_size_t) for n in ('max_iterations', 'chunk_iterations')]
    _fields_ += [(n, ct.c_double) for n in
                 ('inlet_a', 'inlet_b', 'q_relative_tolerance', 'alpha_a', 'alpha_solid', 'alpha_b')]


class _Side2D(ct.Structure):
    _fields_ = [(n, ct.c_double) for n in
                ('q_advective', 'inlet_conduction', 'exchange', 'residual_sum', 'residual_max',
                 'linearized_sum', 'linearized_max', 'defect_sum', 'defect_max', 'mass_net',
                 'mass_local_max', 'mass_in', 'mass_out', 'normalization', 'cell_ratio')]
    _fields_ += [('unknown_inflow_faces', ct.c_size_t), ('cp_coefficients', ct.c_double * 5),
                 ('boundary_mass_out', _Array * 4), ('boundary_h_out', _Array * 4),
                 ('h_faces', _Array * 2), ('inlet_conduction_faces', _Array),
                 ('residual', _Array), ('linearization_defect', _Array)]


class _Audit2D(ct.Structure):
    _fields_ = [('sides', _Side2D * 2)]
    _fields_ += [(n, ct.c_double) for n in
                 ('solid_sum', 'solid_max', 'solid_cell_ratio', 'residual_sum', 'telescoping_error',
                  'net_boundary_in', 'denominator', 'energy_imbalance', 'solid_imbalance')]
    _fields_ += [(n, ct.c_uint32) for n in
                 ('boundary_complete', 'finite', 'energy_ok', 'solid_ok', 'equations_ok', 'passed')]
    _fields_ += [('solid_residual', _Array)]


class _Boundary3D(ct.Structure):
    _fields_ = [(n, ct.c_double) for n in
                ('mass_out', 'enthalpy_out', 'unknown_mass_in', 'inlet_reverse_mass_out')]
    _fields_ += [('unknown_inflow_count', ct.c_size_t), ('enthalpy_faces', _Array)]


class _Side3D(ct.Structure):
    _fields_ = [('boundaries', _Boundary3D * 6), ('cp_coefficients', ct.c_double * 5)]
    _fields_ += [(n, ct.c_double) for n in
                 ('temperature_min', 'temperature_max', 'mass_net', 'advective_in', 'diffusion_in',
                  'numerical_external_in', 'exchange', 'source', 'residual_sum', 'residual_max',
                  'normalization', 'global_ratio', 'cell_ratio')]
    _fields_ += [('boundary_complete', ct.c_uint32), ('residual', _Array), ('inlet_diffusion', _Array)]


class _Audit3D(ct.Structure):
    _fields_ = [('sides', _Side3D * 2)]
    _fields_ += [(n, ct.c_double) for n in
                 ('volume', 'numerical_external_in', 'explicit_source', 'solid_sum', 'solid_max',
                  'full_residual_sum', 'telescoping_error', 'ltne_source_ratio')]
    _fields_ += [('boundary_complete', ct.c_uint32), ('gates', ct.c_uint32 * 6),
                 ('passed', ct.c_uint32), ('solid_residual', _Array)]


class _Check(ct.Structure):
    _fields_ = [('iterations', ct.c_size_t), ('gates', ct.c_uint32 * 6)]


class _Result(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('dimension', 'stop', 'audit_available', 'has_sources')]
    _fields_ += [('iterations', ct.c_size_t), ('residual', ct.c_double), ('q_b', ct.c_double),
                 ('plane', _Audit2D), ('volume', _Audit3D), ('finishing_checks', ct.POINTER(_Check)),
                 ('finishing_count', ct.c_size_t), ('owner', ct.c_void_p)]


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_size_t)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('context', ct.c_void_p)]


def _copy(view, shape=None):
    result = np.ctypeslib.as_array(view.data, shape=(view.size,)).copy()
    return result if shape is None else result.reshape(shape)


def _plane_info(result, shape, widths, masses):
    audit = result.plane
    sides = {}
    for label, side, mass in zip(('A', 'B'), audit.sides, masses):
        sides[label] = dict(
            Q_advective_W_per_m=side.q_advective, inlet_conduction_W_per_m=side.inlet_conduction,
            exchange_W_per_m=side.exchange, source_W_per_m=0., residual_sum_W_per_m=side.residual_sum,
            residual_max_abs_W_per_m=side.residual_max,
            linearized_residual_sum_W_per_m=side.linearized_sum,
            linearized_residual_max_abs_W_per_m=side.linearized_max,
            linearization_defect_sum_W_per_m=side.defect_sum,
            linearization_defect_max_abs_W_per_m=side.defect_max,
            mass_net_out_kg_s_per_m=side.mass_net, mass_local_max_abs_kg_s_per_m=side.mass_local_max,
            mass_in_kg_s_per_m=side.mass_in, mass_out_kg_s_per_m=side.mass_out,
            boundary_mass_out_kg_s_per_m=[_copy(x).tolist() for x in side.boundary_mass_out],
            boundary_h_out_W_per_m=[_copy(x).tolist() for x in side.boundary_h_out],
            mass_faces_kg_s_per_m=[x.tolist() for x in mass],
            h_faces_W_per_m=[_copy(x, m.shape).tolist() for x, m in zip(side.h_faces, mass)],
            inlet_conduction_faces_W_per_m=_copy(side.inlet_conduction_faces).tolist(),
            cp_coefficients=list(side.cp_coefficients), unknown_inflow_faces=side.unknown_inflow_faces,
            physical_boundary_complete=side.unknown_inflow_faces == 0,
            strict_normalization_W_per_m=side.normalization, residual_cellmax_rel=side.cell_ratio)
    return dict(
        units='W/m; kg/(s m)', state='raw final thermal return', boundary_order=['-x', '+x', '-y', '+y'],
        **sides, sou_A=True, sou_B=True, cell_count=int(np.prod(shape)),
        dx_m=widths[0].tolist(), dy_m=widths[1].tolist(),
        area_m2=float(np.sum(widths[0][:, None] * widths[1][None, :])),
        solid_boundary_W_per_m=0., solid_source_W_per_m=0.,
        solid_residual_sum_W_per_m=audit.solid_sum, solid_residual_max_abs_W_per_m=audit.solid_max,
        solid_residual_cellmax_rel=audit.solid_cell_ratio, equation_tolerance=.01,
        residual_sum_W_per_m=audit.residual_sum, telescoping_error_W_per_m=audit.telescoping_error,
        net_boundary_in_W_per_m=audit.net_boundary_in, D2_W_per_m=audit.denominator,
        energy_imbalance_rel=audit.energy_imbalance, solid_imbalance_rel=audit.solid_imbalance,
        physical_boundary_complete=bool(audit.boundary_complete), finite=bool(audit.finite),
        energy_ok=bool(audit.energy_ok), solid_ok=bool(audit.solid_ok),
        equations_ok=bool(audit.equations_ok), passed=bool(audit.passed),
        thermal_converged=result.stop == 0, thermal_iterations=result.iterations,
        thermal_residual_K=result.residual)


def _volume_info(result, shape, *, include_faces=True):
    audit = result.volume
    sides, native_faces, strict = {}, {}, {}
    for label, side in zip(('A', 'B'), audit.sides):
        faces, owned_faces = {}, {}
        for index, (name, face) in enumerate(zip(('x-', 'x+', 'y-', 'y+', 'z-', 'z+'), side.boundaries)):
            faces[name] = dict(outward_mass_kg_s=face.mass_out, outward_model_h_W=face.enthalpy_out,
                non_inlet_inward_mass_kg_s=face.unknown_mass_in, unknown_inflow_count=face.unknown_inflow_count,
                inlet_reverse_outward_mass_kg_s=face.inlet_reverse_mass_out)
            face_shape = tuple(n for axis, n in enumerate(shape) if axis != index // 2)
            if include_faces:
                owned_faces[name] = _copy(face.enthalpy_faces, face_shape)
        native_faces[label] = owned_faces
        sides[label] = dict(faces=faces, physical_boundary_complete=bool(side.boundary_complete),
            model_cp_coefficients=list(side.cp_coefficients),
            temperature_range_K=[side.temperature_min, side.temperature_max], net_outward_mass_kg_s=side.mass_net,
            convective_inward_W=side.advective_in, inlet_diffusion_inward_W=side.diffusion_in,
            numerical_external_inward_W=side.numerical_external_in,
            physical_external_inward_W=side.numerical_external_in if side.boundary_complete else None,
            fluid_solid_exchange_to_fluid_W=side.exchange, explicit_source_W=side.source,
            residual_sum_W=side.residual_sum, residual_max_abs_W=side.residual_max,
            strict_normalization_W=side.normalization)
        strict.update({f'eps_{label}_strict': side.global_ratio, f'eps_{label}_strict_cellmax': side.cell_ratio,
                       f'Q_s{label}': side.exchange})
    balance = dict(reference_K=audit.sides[0].cp_coefficients[4], cell_count=int(np.prod(shape)),
        full_volume_m3=audit.volume, mass_source='completed SIMPLE raw faces before capacity balance/MAC',
        thermal_state='last returned temperatures; nonlinear model h and temperature SOU', sides=sides,
        physical_boundary_complete=bool(audit.boundary_complete), numerical_external_inward_W=audit.numerical_external_in,
        physical_external_inward_W=audit.numerical_external_in if audit.boundary_complete else None,
        explicit_source_W=audit.explicit_source, solid_external_diffusion_W=0.,
        solid_residual_sum_W=audit.solid_sum, solid_residual_max_abs_W=audit.solid_max,
        full_residual_sum_W=audit.full_residual_sum, telescoping_error_W=audit.telescoping_error,
        qualification='No physical acceptance inferred. Non-inlet inflow uses numerical self-extrapolation; its external h is unspecified.')
    return dict(model_h_balance=balance, _native_model_h=native_faces, **strict, delegated_to_2d=False)


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
            info = dict(converged=result.stop == 0, iterations=result.iterations, residual=result.residual)
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
