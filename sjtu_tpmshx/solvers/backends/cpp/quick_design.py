"""Thin prepared-case adapter for the independent Quick Design C ABI."""
import ctypes as ct
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.run_warnings import range_context
from sjtu_tpmshx.models.design_fluids import Props, record_native_design_ranges
from sjtu_tpmshx.models.fluid_props import WaterStateError, QuickDesignWaterFieldError
from sjtu_tpmshx.solvers.backends.quick_design import prepared_input, field_result
from sjtu_tpmshx.solvers.backends.cpp.temperature import _temperature_algorithm


class _Side(ct.Structure):
    _fields_ = [('fluid', ct.c_uint32), *[(name, ct.c_double) for name in
                ('inlet_temperature', 'inlet_pressure', 'mass_flow', 'inlet_pressure_fraction')]]


class _Config(ct.Structure):
    _fields_ = [*[(name, ct.c_uint32) for name in
                 ('topology', 'arrangement', 'property_mode', 'warm_start')],
                *[(name, ct.c_double) for name in
                  ('length', 'span', 'height', 'cell_length', 'area_density', 'hydraulic_diameter')],
                ('sides', _Side * 2), ('max_iterations', ct.c_size_t), ('chunk_iterations', ct.c_size_t),
                ('q_relative_tolerance', ct.c_double), ('alpha', ct.c_double)]


class _PassSide(ct.Structure):
    _fields_ = [(name, ct.c_double) for name in
                ('evaluation_temperature', 'rho', 'mu', 'k', 'cp', 'pr',
                 'reynolds', 'speed', 'hv', 'conductivity')]


class _Pass(ct.Structure):
    _fields_ = [('sides', _PassSide * 2), ('stop', ct.c_uint32), ('iterations', ct.c_size_t),
                ('residual', ct.c_double), ('q_b', ct.c_double)]


class _Pressure(ct.Structure):
    _fields_ = [('inlet', ct.c_double), ('outlet', ct.c_double), ('choked', ct.c_uint32)]


class _Result(ct.Structure):
    _fields_ = [('stop', ct.c_uint32), ('completed_passes', ct.c_size_t),
                ('passes', _Pass * 2), ('pressure', _Pressure * 2)]


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_uint)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('context', ct.c_void_p)]


def run_case(case, control):
    control.check_cancelled()
    shape, p, op, _, widths, fixed = prepared_input(case)
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    path = Path(control.native_library)
    if not path.is_absolute():
        raise ValueError('native_library must be an absolute path')
    path = path.resolve(strict=True)
    library = ct.CDLL(str(path))
    version = library.tpmshx_solver_abi_version
    version.argtypes, version.restype = [], ct.c_uint32
    abi = version()
    if abi != 1:
        raise ValueError(f'unsupported solver library ABI: {abi}; expected 1')
    plane = shape[2] == 1
    algorithm = _temperature_algorithm(library, 0 if plane else 1)
    call = library.tpmshx_solve_quick_design_v1
    double_p, size_p = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
    call.argtypes = [size_p, ct.POINTER(double_p), size_p, ct.POINTER(_Config),
                    ct.POINTER(_Callbacks), ct.POINTER(_Result), ct.POINTER(ct.c_char), ct.c_size_t]
    call.restype = ct.c_int
    seed, controls = p['initial_fields'], p['controls']
    if seed is not None and (len(seed) != 3 or any(np.shape(value) != shape for value in seed)):
        raise ValueError('quick-design warm start disagrees with prepared grid')
    state = ([np.zeros(shape) for _ in range(3)] if seed is None
             else [np.array(value, dtype=np.float64, order='C', copy=True) for value in seed])
    arrays = [np.require(value, dtype=np.float64, requirements=['C', 'A'])
              for value in (*widths, fixed['eps'], fixed['eps_A'], fixed['K_ss'])] + state
    fluid_codes = {'air': 0, 'water': 1, 'sco2': 2}
    sides = (_Side * 2)(*(_Side(fluid_codes[fluid], tin, pin, mass, p['inlet_pressure_fractions'][side])
        for fluid, tin, pin, mass, side in (
            (op.hot_fluid, op.T_in_h, op.P_in_h, op.mdot_h, 'A'),
            (op.cold_fluid, op.T_in_c, op.P_in_c, op.mdot_c, 'B'))))
    chunk = controls['chunk'] if controls['chunk'] is not None else (500 if plane else 250)
    qtol = controls['qtol']
    if qtol is None:
        qtol = min(p['tol'] * 2e-3, 1e-3) if plane else max(p['tol'] * 10, 1e-4)
    for value in (controls['maxit'], chunk):
        if value > ct.c_size_t(-1).value:
            raise ValueError('quick-design iteration budget exceeds native size_t')
    config = _Config({'Diamond': 0, 'Gyroid': 1}[p['topology']],
        {'cross': 0, 'counter': 1}[p['arrangement']], {'const': 0, 'mean': 1}[p['prop_model']],
        int(seed is not None), *(p[key] for key in ('Lx', 's', 'height', 'L_cell_m', 'A_0', 'D_h')),
        sides, controls['maxit'], chunk, qtol, controls['alpha'])
    callback_errors = []

    @_Cancel
    def cancelled(_):
        if callback_errors:
            return 1
        try:
            return int(control.cancel_check is not None and control.cancel_check())
        except BaseException as error:
            callback_errors.append(error)
            return 1

    @_Progress
    def progress(_, percent):
        if not callback_errors:
            try:
                control.report_progress(percent)
            except BaseException as error:
                callback_errors.append(error)

    callbacks = _Callbacks(cancelled, progress, None)
    pointers = (double_p * len(arrays))(*(array.ctypes.data_as(double_p) for array in arrays))
    sizes = (ct.c_size_t * len(arrays))(*(array.size for array in arrays))
    result, error = _Result(), ct.create_string_buffer(1024)
    status = call((ct.c_size_t * 3)(*shape), pointers, sizes, ct.byref(config), ct.byref(callbacks),
                  ct.byref(result), error, len(error))
    if callback_errors:
        raise callback_errors[0]
    if status:
        exception = {1: ValueError, 2: WaterStateError, 3: QuickDesignWaterFieldError,
                     4: FloatingPointError}.get(status, RuntimeError)
        raise exception(error.value.decode('utf-8', errors='replace'))
    if result.stop == 2:
        raise CancelledError('Solver cancelled by user')
    expected_passes = 2 if p['prop_model'] == 'mean' else 1
    if result.stop not in (0, 1) or result.completed_passes != expected_passes:
        raise RuntimeError('native Quick Design returned an invalid pass/status contract')
    pass_info = []
    for index in range(result.completed_passes):
        native_pass = result.passes[index]
        pass_info.append(dict(converged=native_pass.stop == 0, iterations=native_pass.iterations,
                              residual=native_pass.residual, delegated_to_2d=plane))
        stage = 'design-inlet-pass' if index == 0 else 'design-mean-pass'
        for side, fluid, evidence in zip(('A', 'B'), (op.hot_fluid, op.cold_fluid), native_pass.sides):
            with range_context(side=side, stage=stage, layout='scalar'):
                record_native_design_ranges(fluid, p['topology'], evidence.evaluation_temperature, evidence.reynolds)
    a, b = result.passes[result.completed_passes - 1].sides
    zero = np.zeros(shape)
    uc_b, vc_b = ((zero, np.full(shape, b.speed)) if p['arrangement'] == 'cross'
                  else (np.full(shape, -b.speed), zero))
    fields = dict(Ta=state[0], Tb=state[1], Ts=state[2], ucA=np.full(shape, a.speed), vcA=zero, wcA=zero,
                  ucB=uc_b, vcB=vc_b, wcB=zero, K_ffA=np.full(shape, a.conductivity),
                  K_ffB=np.full(shape, b.conductivity), K_ss=fixed['K_ss'],
                  h_vA=np.full(shape, a.hv), h_vB=np.full(shape, b.hv), eps=fixed['eps'])
    props_a, props_b = (Props(s.rho, s.mu, s.k, s.cp, s.pr) for s in (a, b))
    return field_result(case, fields, props_a, props_b, a.speed, b.speed, pass_info, backend_id='cpp',
                        native_metadata=dict(solver_abi=abi, capability='quick_design_v1',
                                             temperature_algorithm=algorithm))
