"""Bind the Quick Design solve operation and copy its output before release."""
import ctypes as ct
from pathlib import Path
from types import SimpleNamespace

from ._native_preparation_case import _QuickInputV2 as _InputV2, _QuickPreparedV2 as _PreparedV2
from ._native_result_stage import Evidence, _stage_array, closure_records
from ._native_values import borrow_array, borrow_text, real_scalar
from .solver_library._stage_capture_abi import RangeRecordView


_NAMES = ('l', 't', 's', 'Lx', 'height', 'k_s', 'tol', 'mdot_h', 'mdot_c', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c')


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


class _StageControl(ct.Structure):
    _fields_ = [('result_id', ct.c_char_p), ('callbacks', _Callbacks)]


class _StageResult(ct.Structure):
    _fields_ = [('abi_version', ct.c_uint32), ('struct_size', ct.c_size_t), ('owner', ct.c_void_p),
                ('raw', _Result), ('evidence', Evidence)]


class _Ranges(ct.Structure):
    _fields_ = [('data', ct.POINTER(RangeRecordView)), ('count', ct.c_size_t)]


def _copy_pass(row):
    sides = []
    for side in row.sides:
        values = {name: getattr(side, name) for name, _ in _PassSide._fields_}
        sides.append(SimpleNamespace(**values))
    return SimpleNamespace(stop=row.stop, iterations=row.iterations, residual=row.residual, sides=tuple(sides))


def _pass_records(library, output, index, side):
    query = library.tpmshx_quick_run_ranges_v2
    query.argtypes = [ct.POINTER(_StageResult), ct.c_size_t, ct.c_size_t]
    query.restype = _Ranges
    view = query(ct.byref(output), index, side)
    if not view.count or not view.data:
        raise RuntimeError('native Quick Design returned no pass ranges')
    _, records = closure_records(view.data, view.count)
    return records


def _check_iteration_size(value):
    if value > ct.c_size_t(-1).value:
        raise ValueError('quick-design iteration budget exceeds native size_t')


def _saved_v2(shape, p, op, views, keepalive, read_controls):
    raw = _InputV2(2, ct.sizeof(_InputV2))
    raw.have_height, raw.warm_start = 1, p['initial_fields'] is not None
    for name, text in [('topology', p['topology']), ('arrangement', p['arrangement']), ('property_mode', p['prop_model'])]:
        setattr(raw, name, borrow_text(text, keepalive))
    for index, text in enumerate((op.hot_fluid, op.cold_fluid)):
        raw.fluids[index] = borrow_text(text, keepalive)
    for i, value in enumerate((p['s'], p['Lx'], p['height'], 0., p['tol'], op.mdot_h, op.mdot_c,
                               op.T_in_h, op.T_in_c, op.P_in_h, op.P_in_c), 2):
        raw.values[i] = real_scalar(value, name=_NAMES[i])
    prepared = _PreparedV2(2, ct.sizeof(_PreparedV2))
    prepared.shape[:], prepared.widths[:] = shape, views[:3]
    if raw.warm_start:
        raw.initial_shape[:] = shape
        prepared.initial[:] = views[6:]
    prepared.epsilon, prepared.epsilon_a, prepared.solid_conductivity = views[3:6]
    prepared.cell_length_m = real_scalar(p['L_cell_m'], name='L_cell_m')
    prepared.geometry.area_density_per_m, prepared.geometry.hydraulic_diameter_m = p['A_0'], p['D_h']
    for i, side in enumerate('AB'):
        prepared.fractions[i] = real_scalar(p['inlet_pressure_fractions'][side], name='inlet_pressure_fractions')
    settings = read_controls(p, _check_iteration_size)
    c = prepared.controls
    c.dir_b, c.max_iterations, c.alpha = int(settings['dirB']), settings['maxit'], settings['alpha']
    c.ny, c.nz = shape[1:]
    c.have_chunk_iterations, c.have_q_relative_tolerance = settings['chunk'] is not None, settings['qtol'] is not None
    c.chunk_iterations, c.q_relative_tolerance = settings['chunk'] or 0, settings['qtol'] or 0.
    return raw, prepared


class QuickSolver:
    """Load the selected solver image before the host reads the saved case."""

    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute():
            raise ValueError('native_library must be an absolute path')
        path = path.resolve(strict=True)
        library = ct.CDLL(str(path))
        version = library.tpmshx_solver_abi_version
        version.argtypes, version.restype = [], ct.c_uint32
        abi = version()
        if abi != 1:
            raise ValueError(f'unsupported solver library ABI: {abi}; expected 1')
        try:
            call = library.tpmshx_run_quick_design_v2
            recipe = library.tpmshx_quick_run_temperature_algorithm_v1
        except AttributeError as error:
            raise ValueError('native solver library lacks the Quick Design v2 stage; rebuild the library') from error
        self._library = library
        self._call = call
        self._recipe = recipe
        self.abi = abi

    def run(self, shape, p, op, widths, fixed, state, *, read_controls, retained_fields, new_result_id, cancel,
            report_progress, error_types, expected_passes, range_output):
        """Return owned field data, declarations and pass evidence."""
        library, call, recipe = self._library, self._call, self._recipe
        recipe.argtypes, recipe.restype = [ct.POINTER(_StageResult)], ct.c_char_p
        release = library.tpmshx_quick_run_release_v1
        release.argtypes, release.restype = [ct.POINTER(_StageResult)], None
        keepalive = []
        views = [borrow_array(value, keepalive)
                 for value in (*widths, fixed['eps'], fixed['eps_A'], fixed['K_ss'], *state)]
        callback_errors = []

        @_Cancel
        def cancelled(_):
            if callback_errors:
                return 1
            try:
                return int(cancel is not None and cancel())
            except BaseException as error:
                callback_errors.append(error)
                return 1

        @_Progress
        def progress(_, percent):
            if not callback_errors:
                try:
                    report_progress(percent)
                except BaseException as error:
                    callback_errors.append(error)

        descriptors = _saved_v2(shape, p, op, views, keepalive, read_controls)
        call.argtypes = [*(ct.POINTER(type(item)) for item in descriptors), ct.POINTER(_StageControl),
                         ct.POINTER(_StageResult), ct.POINTER(ct.c_char), ct.c_size_t]
        call.restype = ct.c_int
        result_id = new_result_id()
        stage_control = _StageControl(result_id.encode(), _Callbacks(cancelled, progress, None))
        output = _StageResult(abi_version=1, struct_size=ct.sizeof(_StageResult))
        error = ct.create_string_buffer(1024)
        try:
            status = call(*(ct.byref(item) for item in descriptors), ct.byref(stage_control), ct.byref(output), error, len(error))
            if callback_errors:
                raise callback_errors[0]
            if status:
                raise error_types.get(status, RuntimeError)(error.value.decode('utf-8', errors='replace'))
            name = recipe(ct.byref(output))
            if not name:
                raise RuntimeError('native Quick Design returned no temperature algorithm')
            algorithm = name.decode('ascii')
            raw = output.raw
            pass_count = expected_passes()
            if raw.stop not in (0, 1) or raw.completed_passes != pass_count:
                raise RuntimeError('native Quick Design returned an invalid pass/status contract')
            passes = tuple(_copy_pass(row) for row in raw.passes[:raw.completed_passes])
            pressure = tuple((side.inlet, side.outlet, bool(side.choked)) for side in raw.pressure)
            ranges = range_output()
            if ranges is not None:
                for index in range(raw.completed_passes):
                    for side in range(2):
                        ranges.append(_pass_records(library, output, index, side))
            fields = {}
            for item in output.evidence.fields[:output.evidence.field_count]:
                key = item.name.decode()
                fields[key] = retained_fields[key] if key in retained_fields else _stage_array(item.value, shape)
            declarations = tuple((item.name.decode(), item.unit.decode(), item.state.decode())
                                 for item in output.evidence.field_metadata[:output.evidence.field_metadata_count])
            return SimpleNamespace(result_id=result_id, algorithm=algorithm, passes=passes,
                                   pressure=pressure, fields=fields, declarations=declarations)
        finally:
            release(ct.byref(output))
