"""Thin prepared-case adapter for the independent Quick Design C ABI."""
import ctypes as ct
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.cpp_interface._native_result_stage import Evidence, closure_records
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.run_warnings import current_warnings, range_context, record_sample
from sjtu_tpmshx.physical_models.design_fluids import Props, record_native_design_ranges
from sjtu_tpmshx.physical_models.fluid_props import WaterStateError, QuickDesignWaterFieldError
from sjtu_tpmshx.cpp_interface._native_df import _Pressure as _PreparedPressure
from sjtu_tpmshx.solvers.backends.quick_design import field_result
from .solver_library._stage_capture_abi import RangeRecordView
from ._native_preparation_case import _Array
from ._native_preparation_case import _QuickInputV2 as _InputV2, _QuickPreparedV2 as _PreparedV2
from sjtu_tpmshx.cpp_interface.solver_library.temperature import _temperature_algorithm


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


class _Inlet(ct.Structure):
    _fields_ = [('fluid', ct.c_uint32), *[(name, ct.c_double) for name in
                ('temperature_K', 'pressure_Pa', 'mass_flow_kg_s')]]


class _Input(ct.Structure):
    _fields_ = [('abi_version', ct.c_uint32), ('struct_size', ct.c_size_t),
                *[(name, ct.c_uint32) for name in ('topology', 'arrangement', 'property_mode')],
                *[(name, ct.c_double) for name in
                  ('cell_length_mm', 'wall_thickness_mm', 'span_m', 'length_m')],
                ('sides', _Inlet * 2), *[(name, ct.c_uint32) for name in
                  ('have_height', 'have_solid_conductivity', 'have_tolerance')],
                *[(name, ct.c_double) for name in
                  ('height_m', 'solid_conductivity_W_mK', 'tolerance')],
                ('warm_start', ct.c_uint32), ('initial_shape', ct.c_size_t * 3), ('initial', _Array * 3)]


class _Prepared(ct.Structure):
    _fields_ = [('abi_version', ct.c_uint32), ('struct_size', ct.c_size_t), ('owner', ct.c_void_p),
                ('input', _Input), ('shape', ct.c_size_t * 3), ('widths', _Array * 3), ('edges', _Array * 3),
                *[(name, _Array) for name in ('epsilon', 'epsilon_a', 'solid_conductivity')],
                ('initial', _Array * 3), *[(name, ct.c_double) for name in
                  ('wall_thickness_m', 'solid_conductivity_W_mK', 'tolerance')],
                ('geometry_resolution', ct.c_size_t), ('resolved', _Config),
                ('inlet_pressure', _PreparedPressure * 2)]


class _StageControl(ct.Structure):
    _fields_ = [('result_id', ct.c_char_p), ('callbacks', _Callbacks)]


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', ct.c_uint32), ('struct_size', ct.c_size_t), ('owner', ct.c_void_p),
                ('raw', _Result), ('evidence', Evidence)]


class _Ranges(ct.Structure):
    _fields_ = [('data', ct.POINTER(RangeRecordView)), ('count', ct.c_size_t)]


def _record_pass(library, output, index, side, fluid):
    query = library.tpmshx_quick_run_ranges_v2
    query.argtypes = [ct.POINTER(_StageResult), ct.c_size_t, ct.c_size_t]
    query.restype = _Ranges
    view = query(ct.byref(output), index, side)
    if not view.count or not view.data:
        raise RuntimeError('native Quick Design returned no pass ranges')
    _, records = closure_records(view.data, view.count)
    for key, sample in records.items():
        if key[0] == 'nu' and fluid == 'sco2':
            from sjtu_tpmshx.physical_models.design_fluids import _warn_sco2_representative_pr
            _warn_sco2_representative_pr()
        record_sample(key, sample)


def _legacy_prepared(shape, p, op, views):
    seed, controls = p['initial_fields'], p['controls']
    plane = shape[2] == 1
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
    return _Prepared(abi_version=1, struct_size=ct.sizeof(_Prepared),
                         shape=(ct.c_size_t * 3)(*shape), widths=(_Array * 3)(*views[:3]),
                         epsilon=views[3], epsilon_a=views[4], solid_conductivity=views[5],
                         initial=(_Array * 3)(*views[6:]), resolved=config)


def _saved_case(case):
    from sjtu_tpmshx.data_types.persistence_validation import validate_grid
    from sjtu_tpmshx.model_configs.model_parameters import MODEL_VERSIONS

    shape = validate_grid(case.grid)
    if len(shape) != 3 or case.metadata['model'] != 'plug_ltne_analytic_dp_v1':
        raise ValueError('unsupported quick-design physical model')
    p = case.parameters
    op = SimpleNamespace(**p['operating_point'])
    fractions = p.get('inlet_pressure_fractions')
    if fractions is None or set(fractions) != {'A', 'B'} or any(not np.isscalar(v) for v in fractions.values()):
        raise ValueError('quick-design requires prepared nonnegative inlet pressure fractions')
    if len(case.model_refs) != 3 or case.model_refs[0].name != 'quick_design':
        raise ValueError('quick-design model resources are incomplete')
    if case.model_refs[0].parameters:
        raise ValueError('quick-design closure takes no fixed parameters')
    for ref, fluid in zip(case.model_refs[1:], (op.hot_fluid, op.cold_fluid)):
        if ref.name != 'fluid' or dict(ref.parameters) != {'fluid': fluid}:
            raise ValueError('quick-design fluid resource disagrees with operating point')
    for ref in case.model_refs:
        if ref.version != MODEL_VERSIONS[ref.name]:
            raise ValueError(f'unknown model resource: {ref.name}@{ref.version}')
    fixed = case.design_fields
    if set(fixed) != {'eps', 'eps_A', 'K_ss'}:
        raise ValueError('unsupported quick-design fields')
    for name, field in fixed.items():
        if np.shape(field) != shape:
            raise ValueError(f'quick-design requires a finite uniform {name} field on its prepared grid')
    widths = tuple(case.grid['d' + axis] for axis in 'xyz')
    return shape, p, op, widths, fixed


def _saved_v2(shape, p, op, widths, views, keepalive):
    from ._native_preparation_case import borrow_text

    raw = _InputV2(2, ct.sizeof(_InputV2))
    raw.have_height, raw.warm_start = 1, p['initial_fields'] is not None
    for name, text in [('topology', p['topology']), ('arrangement', p['arrangement']), ('property_mode', p['prop_model'])]:
        setattr(raw, name, borrow_text(text, keepalive))
    for index, text in enumerate((op.hot_fluid, op.cold_fluid)):
        raw.fluids[index] = borrow_text(text, keepalive)
    for i, value in enumerate((p['s'], p['Lx'], p['height'], 0., p['tol'], op.mdot_h, op.mdot_c,
                               op.T_in_h, op.T_in_c, op.P_in_h, op.P_in_c), 2):
        raw.values[i].value = value
    prepared = _PreparedV2(2, ct.sizeof(_PreparedV2))
    prepared.shape[:], prepared.widths[:] = shape, views[:3]
    if raw.warm_start:
        raw.initial_shape[:] = shape
        prepared.initial[:] = views[6:]
    prepared.width_precision[:] = [width.dtype.itemsize * 8 for width in widths]
    prepared.epsilon, prepared.epsilon_a, prepared.solid_conductivity = views[3:6]
    prepared.cell_length_m.value = p['L_cell_m']
    prepared.geometry.area_density_per_m, prepared.geometry.hydraulic_diameter_m = p['A_0'], p['D_h']
    for i, side in enumerate('AB'):
        prepared.fractions[i].value = p['inlet_pressure_fractions'][side]
    settings = p['controls']
    for value in (settings['maxit'], settings['chunk']):
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise ValueError('invalid quick-design numerical controls')
        if value is not None and value > ct.c_size_t(-1).value:
            raise ValueError('quick-design iteration budget exceeds native size_t')
    if settings['dirB'] not in (1, 2):
        raise ValueError('quick-design flow direction disagrees with arrangement')
    c = prepared.controls
    c.dir_b, c.max_iterations, c.alpha = settings['dirB'], settings['maxit'], settings['alpha']
    c.ny, c.nz = shape[1:]
    c.have_chunk_iterations, c.have_q_relative_tolerance = settings['chunk'] is not None, settings['qtol'] is not None
    c.chunk_iterations, c.q_relative_tolerance = settings['chunk'] or 0, settings['qtol'] or 0.
    return raw, prepared


def run_case(case, control):
    control.check_cancelled()
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
    current = getattr(library, 'tpmshx_run_quick_design_v2', None)
    if current is None:
        from sjtu_tpmshx.solvers.backends.quick_design import prepared_input
        shape, p, op, widths, fixed = prepared_input(case)
    else:
        shape, p, op, widths, fixed = _saved_case(case)
    plane = shape[2] == 1
    algorithm = _temperature_algorithm(library, 0 if plane else 1)
    double_p = ct.POINTER(ct.c_double)
    release = library.tpmshx_quick_run_release_v1
    release.argtypes, release.restype = [ct.POINTER(_StageResult)], None
    seed = p['initial_fields']
    if seed is not None and (len(seed) != 3 or any(np.shape(value) != shape for value in seed)):
        raise ValueError('quick-design warm start disagrees with prepared grid')
    state = ([] if seed is None
             else [np.array(value, dtype=np.float64, order='C', copy=True) for value in seed])
    arrays = [np.require(value, dtype=np.float64, requirements=['C', 'A'])
              for value in (*widths, fixed['eps'], fixed['eps_A'], fixed['K_ss'])] + state
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

    views = [_Array(array.ctypes.data_as(double_p), array.size) for array in arrays]
    if current is None:
        descriptors = (_legacy_prepared(shape, p, op, views),)
        call = library.tpmshx_run_quick_design_v1
    else:
        descriptors = _saved_v2(shape, p, op, widths, views, arrays)
        call = current
    call.argtypes = [*(ct.POINTER(type(item)) for item in descriptors), ct.POINTER(_StageControl),
                     ct.POINTER(_StageResult), ct.POINTER(ct.c_char), ct.c_size_t]
    call.restype = ct.c_int
    result_id = str(uuid4())
    stage_control = _StageControl(result_id.encode(), _Callbacks(cancelled, progress, None))
    output = _StageResult(abi_version=1, struct_size=ct.sizeof(_StageResult))
    error = ct.create_string_buffer(1024)
    try:
        status = call(*(ct.byref(item) for item in descriptors), ct.byref(stage_control), ct.byref(output), error, len(error))
        if callback_errors:
            raise callback_errors[0]
        if status:
            exception = {1: ValueError, 2: WaterStateError, 3: QuickDesignWaterFieldError,
                         4: FloatingPointError, 6: CancelledError}.get(status, RuntimeError)
            raise exception(error.value.decode('utf-8', errors='replace'))
        result = _Result.from_buffer_copy(output.raw)
        expected_passes = 2 if p['prop_model'] == 'mean' else 1
        if result.stop not in (0, 1) or result.completed_passes != expected_passes:
            raise RuntimeError('native Quick Design returned an invalid pass/status contract')
        use_records = current is not None and current_warnings() is not None
        if use_records:
            for index in range(result.completed_passes):
                for side, fluid in enumerate((op.hot_fluid, op.cold_fluid)):
                    _record_pass(library, output, index, side, fluid)
        fields = {}
        for item in output.evidence.fields[:output.evidence.field_count]:
            key = item.name.decode()
            if key in ('K_ss', 'eps'):
                fields[key] = fixed[key]
            else:
                fields[key] = np.ctypeslib.as_array(ct.cast(item.value.data, double_p),
                                                    shape=(int(np.prod(shape)),)).reshape(shape).copy()
        field_metadata = {item.name.decode(): dict(unit=item.unit.decode(), axes=('x', 'y', 'z'),
                          location='cell', state=item.state.decode()) for item in
                          output.evidence.field_metadata[:output.evidence.field_metadata_count]}
    finally:
        release(ct.byref(output))
    pass_info = []
    for index in range(result.completed_passes):
        native_pass = result.passes[index]
        pass_info.append(dict(converged=native_pass.stop == 0, iterations=native_pass.iterations,
                              residual=native_pass.residual, delegated_to_2d=plane))
        if not use_records:
            stage = 'design-inlet-pass' if index == 0 else 'design-mean-pass'
            for side, fluid, evidence in zip(('A', 'B'), (op.hot_fluid, op.cold_fluid), native_pass.sides):
                with range_context(side=side, stage=stage, layout='scalar'):
                    record_native_design_ranges(fluid, p['topology'], evidence.evaluation_temperature, evidence.reynolds)
    a, b = result.passes[result.completed_passes - 1].sides
    props_a, props_b = (Props(s.rho, s.mu, s.k, s.cp, s.pr) for s in (a, b))
    pressure = {side: dict(inlet_absolute_Pa=evidence.inlet, outlet_absolute_Pa=evidence.outlet,
                           model='inlet_state_analytic_df', choked=bool(evidence.choked))
                for side, evidence in zip(('A', 'B'), result.pressure)}
    return field_result(case, fields, props_a, props_b, a.speed, b.speed, pass_info,
                        field_metadata=field_metadata, result_id=result_id,
                        pressure=pressure, backend_id='cpp',
                        native_metadata=dict(solver_abi=abi, capability='quick_design_v1',
                                             temperature_algorithm=algorithm))
