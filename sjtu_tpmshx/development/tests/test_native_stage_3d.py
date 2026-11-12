"""Compare native 3D stage ownership, fields and evidence with public execution."""
import ctypes as ct
from contextlib import contextmanager
from dataclasses import replace
from copy import deepcopy
from itertools import product
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_3d as uniform
from sjtu_tpmshx.development.tests import test_native_preparation_flow_3d as flow
from sjtu_tpmshx.development.tests import test_native_preparation_continuous_3d as continuous
from sjtu_tpmshx.development.tests import test_native_preparation_spatial_3d as spatial
from sjtu_tpmshx.development.tests import test_native_stage_uniform as evaluation
from sjtu_tpmshx.development.tests.test_native_prepare_adapter import _same
from sjtu_tpmshx.development.tests.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared import _native_result_stage as query
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.models.fluid_props import WaterStateError
from sjtu_tpmshx.shared.io.case_io import save_case
from sjtu_tpmshx.shared.io.result_io import save_result
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.cpp import _full_3d_abi as abi
from sjtu_tpmshx.solvers.backends.cpp.enthalpy import _EnergyOptions
from sjtu_tpmshx.solvers.backends.cpp.model_h import _IterationOptions
from sjtu_tpmshx.solvers.backends.cpp.run_state import NativeRun, _Field, _Snapshot

preparation_library = uniform.native
flow_library = flow.native
continuous_library = continuous.native
spatial_library = spatial.native
_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
record = evaluation.report.record
_Size, _Double = evaluation._Size, evaluation._Double
_Uint = record('UintOption3D', [('present', _U), ('value', _U)])
_Request = record('StageRequest3D', [('abi_version', _U), ('struct_size', _Z),
    *((name, _Size) for name in ('max_iter_simple', 'max_outer_ltne', 'thermal_iterations',
        'coarse_iterations', 'parallel_threshold')),
    *((name, _Double) for name in ('outer_tol_K', 'thermal_relaxation', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K', 'roughness_height_m')),
    *((name, _Uint) for name in ('pressure_shooting', 'variable_rho_cp', 'conservative',
        'strict_mass_balance', 'force_cell_centered', 'refined_port_energy', 'sco2_local_pressure_a',
        'coarse_bootstrap', 'adaptive_pressure_tolerance', 'track_momentum', 'roughness_mode', 'envelope_mode')),
    ('convergence_mode', ct.c_char_p), ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('energy_iterations', _Size), ('energy_sweeps', _Size),
    *((name, _Double) for name in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')),
    ('require_enthalpy_update_on_temperature', _U)])
_Control = record('StageControl3D', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _Z), ('callbacks', abi._Callbacks)])
_Saved = record('StageSaved3D', [('abi_version', _U), ('struct_size', _Z), ('input', ct.POINTER(abi._Input)),
    *((name, _D) for name in ('nominal_cell_length_mm', 'nominal_wall_thickness_mm', 'nominal_porosity')),
    ('wall_thickness_m', uniform.abi._Array), ('preparation', uniform.abi._Evidence),
    ('notices', ct.POINTER(uniform.abi._Text)), ('notice_count', _Z), ('inlet_recorded', _U),
    ('range_captured', ct.POINTER(_U))])
_Result = record('StageResult3D', [('abi_version', _U), ('struct_size', _Z), ('owner', ct.c_void_p),
    ('raw', abi._Result), ('evidence', evaluation.report.Evidence), ('resolved', abi._Control),
    ('evaluation', query.Input)])


def _evaluate(result):
    library = query.core._library().library
    function = library.tpmshx_result_stage_query_v2
    function.argtypes = [ct.POINTER(query.Input), _U, ct.POINTER(query.Spec), ct.POINTER(query.Metric), _Z,
        ct.POINTER(query.Output), ct.POINTER(query.core._Diagnostics), ct.POINTER(ct.c_uint64),
        ct.POINTER(ct.c_char), _Z]
    function.restype = ct.c_int
    output = query.Output(struct_size=ct.sizeof(query.Output))
    diagnostics, token, error = query.core._Diagnostics(), ct.c_uint64(), ct.create_string_buffer(4096)
    status = function(ct.byref(result.evaluation), 0, None, None, 0, ct.byref(output),
        ct.byref(diagnostics), ct.byref(token), error, len(error))
    assert status == 0, error.value.decode()
    try:
        return json.loads(output.json)
    finally:
        release = library.tpmshx_result_stage_release_v1
        release.argtypes, release.restype = [ct.POINTER(query.Output)], None
        release(ct.byref(output))


@pytest.fixture(scope='module')
def stage_library():
    library = ct.CDLL(str(library_path()))
    common = [ct.POINTER(uniform._Result), ct.POINTER(continuous._Result), ct.POINTER(spatial._Result),
        ct.POINTER(_Request), ct.POINTER(_Control)]
    saved = [ct.POINTER(_Saved), ct.POINTER(_Request), ct.POINTER(_Control)]
    tail = [ct.POINTER(ct.c_char), _Z]
    signatures = {
        'create': [*common, ct.POINTER(ct.c_void_p), *tail],
        'restore': [*common, ct.POINTER(_Field), _Z, ct.POINTER(ct.c_void_p), *tail],
        'create_saved': [*saved, ct.POINTER(ct.c_void_p), *tail],
        'restore_saved': [*saved, ct.POINTER(_Field), _Z, ct.POINTER(ct.c_void_p), *tail],
        'advance_step': [ct.c_void_p, ct.POINTER(_U), *tail],
        'phase': [ct.c_void_p, ct.POINTER(_U)],
        'snapshot': [ct.c_void_p, ct.POINTER(_Snapshot), *tail],
        'take_result': [ct.c_void_p, ct.POINTER(_Result), *tail],
        'release_run': [ct.POINTER(ct.c_void_p)],
        'release': [ct.POINTER(_Result)],
    }
    for name, arguments in signatures.items():
        function = getattr(library, 'tpmshx_stage_run_3d_' + name + '_v1')
        function.argtypes = arguments
        function.restype = None if name.startswith('release') else ct.c_int
    library.tpmshx_run_case_3d_v1.argtypes = [*common, ct.POINTER(_Result), *tail]
    library.tpmshx_run_case_3d_v1.restype = ct.c_int
    library.tpmshx_run_state_release_v1.argtypes = [ct.POINTER(_Snapshot)]
    library.tpmshx_run_state_release_v1.restype = None
    return library


def _arguments(prepared):
    return [ct.byref(prepared) if isinstance(prepared, kind) else None
            for kind in (uniform._Result, continuous._Result, spatial._Result)]


@contextmanager
def _prepared(libraries, config, layout):
    library = libraries[layout]
    if layout == 'uniform':
        status, value, _, error, _, source = uniform._call(library, config)
        release = library.tpmshx_preparation_case_3d_release_v1
    else:
        module = flow if layout == 'fixed' else continuous if layout in ('xy', 'xyz') else spatial
        status, value, _, error, _, source = module._call(library, 'prepare_flow_case', config)
        release = lambda pointer: module._release(library, pointer._obj)
    assert status == 0, error
    try:
        yield value.prepared if layout == 'fixed' else value
    finally:
        release(ct.byref(value))
        del source


@pytest.fixture(scope='module')
def preparation_libraries(preparation_library, flow_library, continuous_library, spatial_library):
    return dict(uniform=preparation_library, fixed=flow_library, xy=continuous_library,
        xyz=continuous_library, grid=spatial_library, asymmetric=spatial_library)


def _configuration(pair=('air', 'water'), layout='uniform'):
    if layout in ('xy', 'xyz'):
        config = continuous._configuration(pair=pair, nz=3 if layout == 'xyz' else None)
    elif layout in ('grid', 'asymmetric'):
        config = spatial._configuration(pair=pair, spatial=layout == 'grid', delta=.12 if layout == 'asymmetric' else 0.)
    else:
        config = uniform._configuration(pair=pair)
    if layout == 'fixed':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .02
    config.flags.port_wall_refine = False
    request = _Request(1, ct.sizeof(_Request))
    request.max_iter_simple, request.max_outer_ltne = _Size(1, 12), _Size(1, 2)
    config.solver.max_iter_simple, config.solver.max_outer_ltne = 12, 2
    if any(name in ('sco2', 'co2') for name in pair):
        request.energy_iterations = _Size(1, 9)
        config.solver.ltne_enthalpy_outer = 9
    else:
        request.model_h = _IterationOptions(9, .5, 1e-3)
        config.solver.model_h_max_iterations = 9
        config.solver.model_h_temperature_tol_K = .5
        config.solver.model_h_q_relative_tol = 1e-3
    return config, request


def _control(events, *, cancel=None, threads=2):
    callbacks = abi._Callbacks(abi._Cancel(lambda _: int(cancel())) if cancel else abi._Cancel(),
        abi._Progress(lambda _, value: events.append(('progress', int(value)))),
        abi._OuterProgress(lambda _, done, total: events.append(('outer', done, total))), None)
    table = os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY')
    value = _Control(b'native-3d-stage', None if table is None else table.encode(), threads, callbacks)
    value._callbacks = callbacks
    return value


def _reference(config, events):
    case = prepare_case(config, case_id='native-3d-reference')
    result = run_case(case, RunControl(cpu_threads=2, native_library=str(library_path()),
        native_table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY'),
        progress=lambda value: events.append(('progress', value)),
        outer_iteration=lambda done, total: events.append(('outer', done, total))))
    return case, result


def _fields(evidence):
    output = {}
    for row in evidence.fields[:evidence.field_count]:
        array = row.value
        assert array.rank == 3
        shape = tuple(array.shape[:array.rank])
        output[row.name.decode()] = np.ctypeslib.as_array(ct.cast(array.data, ct.POINTER(_D)),
            (int(np.prod(shape)),)).reshape(shape).copy()
    return output


def _compare(result, expected, tmp_path):
    fields = _fields(result.evidence)
    assert fields.keys() == expected.fields.keys()
    for name, value in fields.items():
        assert value.dtype == expected.fields[name].dtype
        np.testing.assert_array_equal(value.view(np.uint8), expected.fields[name].view(np.uint8), err_msg=name)
    actual = _evaluate(result)
    wanted = evaluation.report.python_report(expected)
    wanted['source_result_id'] = wanted['qualification']['source_result_id'] = actual['source_result_id']
    (tmp_path / 'native-report.json').write_text(json.dumps(actual, indent=2))
    (tmp_path / 'reference-report.json').write_text(json.dumps(wanted, indent=2))
    save_result(expected, tmp_path / 'reference.h5')
    np.savez(tmp_path / 'native-fields.npz', **fields)
    _same(actual, wanted, 'native report')
    assert result.evidence.thermal_mode.decode() == expected.metadata['thermal_mode']
    return fields


@pytest.mark.parametrize('layout,pair', [(layout, pair)
    for layout in ('uniform', 'fixed', 'xy', 'xyz', 'grid', 'asymmetric')
    for pair in product(('air', 'water', 'sco2', 'co2'), repeat=2)
    if layout not in ('grid', 'asymmetric') or all(name in ('air', 'water') for name in pair)])
def test_stage_complete_fields_and_report(preparation_libraries, stage_library, layout, pair, tmp_path):
    config, request = _configuration(pair, layout)
    events, expected_events = [], []
    control, result, error = _control(events), _Result(1, ct.sizeof(_Result)), ct.create_string_buffer(4096)
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    with _prepared(preparation_libraries, config, layout) as prepared:
        status = stage_library.tpmshx_run_case_3d_v1(*_arguments(prepared), ct.byref(request),
            ct.byref(control), ct.byref(result), error, len(error))
        if status:
            assert not result.owner and not result.evidence.abi_version
            with pytest.raises({1: ValueError, 2: WaterStateError, 3: FloatingPointError}.get(status, RuntimeError)) as caught:
                _reference(config, expected_events)
            assert str(caught.value) == error.value.decode()
            assert events == expected_events
            (tmp_path / 'verdict.json').write_text(json.dumps(dict(status=status, error=str(caught.value),
                error_exact=True, callback_order_exact=True, no_result=True)))
            return
    try:
        case, expected = _reference(config, expected_events)
        save_case(case, tmp_path / 'case.h5')
        fields = _compare(result, expected, tmp_path)
        assert events == expected_events
        (tmp_path / 'events.json').write_text(json.dumps(dict(actual=events, expected=expected_events)))
        (tmp_path / 'verdict.json').write_text(json.dumps(dict(fields_exact=len(fields), report_exact=True,
            callback_order_exact=True, released_preparation=True)))
    finally:
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))
        assert not result.owner


class _Run(NativeRun):
    def __init__(self, library, prepared, request, control, state=None):
        self.handle, self.library = ct.c_void_p(), library
        self.prepared, self.request, self.callbacks = prepared, request, control
        for name, entry in [('advance', 'advance_step'), ('phase', 'phase'), ('snapshot', 'snapshot'),
                            ('take_result', 'take_result'), ('release', 'release_run')]:
            setattr(self, '_' + name, getattr(library, 'tpmshx_stage_run_3d_' + entry + '_v1'))
        self._release_snapshot = library.tpmshx_run_state_release_v1
        saved = isinstance(prepared, _Saved)
        common = [ct.byref(prepared)] if saved else _arguments(prepared)
        common += [ct.byref(request), ct.byref(control)]
        suffix = '_saved' if saved else ''
        if state is None:
            self._call(getattr(library, 'tpmshx_stage_run_3d_create' + suffix + '_v1'),
                *common, ct.byref(self.handle))
        else:
            fields, keepalive = self._fields(state)
            self._call(getattr(library, 'tpmshx_stage_run_3d_restore' + suffix + '_v1'),
                *common, fields, len(fields), ct.byref(self.handle))
            del keepalive

    def take_result(self):
        value = _Result(1, ct.sizeof(_Result))
        self._call(self._take_result, self.handle, ct.byref(value))
        return value


def _state_equal(actual, expected):
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        if key.endswith(('.linear.build_seconds', '.linear.solve_seconds')):
            assert actual[key].dtype == value.dtype and actual[key].shape == value.shape
            assert np.all(actual[key] >= 0) and np.all(value >= 0)
        else:
            _same(actual[key], value, key)


def _old_states(config):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    cfg, prepared = build_execution_inputs(prepare_case(config, case_id='stage-native-reference'))
    snapshots = {}
    def checkpoint(value):
        snapshots.setdefault(int(value['state.phase'][0]), value)
    driver = NativeFull3DDriver(library_path(), table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY'))
    driver.run_prepared(cfg, prepared, RunControl(cpu_threads=2), checkpoint=checkpoint)
    return snapshots


@pytest.mark.parametrize('layout,pair', [('uniform', ('air', 'water')), ('xyz', ('water', 'air')),
    ('uniform', ('co2', 'air')), ('xy', ('water', 'sco2')), ('asymmetric', ('air', 'water'))])
def test_all_safe_snapshots_restore_exactly(preparation_libraries, stage_library, layout, pair, tmp_path):
    config, request = _configuration(pair, layout)
    events, expected_events, snapshots = [], [], {}
    control = _control(events)
    with _prepared(preparation_libraries, config, layout) as prepared:
        run = _Run(stage_library, prepared, request, control)
        try:
            with pytest.raises((ValueError, RuntimeError), match='phase|complete|result'):
                run.take_result()
            with pytest.raises((ValueError, RuntimeError), match='phase|boundary|snapshot'):
                run.snapshot()
            while run.phase not in (3, 4):
                phase = run.advance()
                assert phase != 4
                if phase in (1, 2, 6, 7, 8, 9, 10) and phase not in snapshots:
                    state = snapshots[phase] = run.snapshot()
                    np.savez(tmp_path / f'phase-{phase}.npz', **state)
                    run.close()
                    control.cpu_threads = 1 if control.cpu_threads == 2 else 2
                    run = _Run(stage_library, prepared, request, control, state)
                    _state_equal(run.snapshot(), state)
            result = run.take_result()
            with pytest.raises((ValueError, RuntimeError), match='transferred|taken|result'):
                run.take_result()
        finally:
            run.close()
            run.close()
    try:
        old = _old_states(config)
        assert set(snapshots) == set(old)
        assert {1, 2, 6, 7}.issubset(snapshots)
        for phase, state in snapshots.items():
            _state_equal(state, old[phase])
        _, expected = _reference(config, expected_events)
        _compare(result, expected, tmp_path)
        assert events == expected_events
        (tmp_path / 'verdict.json').write_text(json.dumps(dict(phases=sorted(snapshots),
            state_exact=True, result_exact=True, callbacks_exact=True, changed_cpu_limit=True)))
    finally:
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))


def _full_dto(config, request, prepared, stage_library, *, saved=False, change=None, cfg_updates=None,
              prepared_updates=None, evidence_change=None):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    case = prepare_case(config, case_id='stage-native-reference')
    if evidence_change:
        from sjtu_tpmshx.shared.domain.portable_data import mutable_data
        metadata = mutable_data(case.metadata)
        if evidence_change == 'missing':
            del metadata['applicability_inputs']
        elif evidence_change == 'empty':
            metadata['applicability_inputs'] = []
        elif evidence_change == 'uncaptured':
            metadata['applicability_inputs'][0]['captured'] = False
        else:
            row = metadata['applicability_inputs'][0]
            row.update(minimum=None, maximum=None, low=0, high=0, nonfinite=row['size'])
        case = replace(case, metadata=metadata)
    cfg, inputs = build_execution_inputs(case)
    inputs.update(prepared_updates or {})
    cfg['_emit_audit'] = True
    cfg.update(cfg_updates or {})
    if change == 'conductivity':
        inputs['design']['K_ss'] = np.array(inputs['design']['K_ss'], copy=True)
        inputs['design']['K_ss'][0, 0, 0] *= 1.2
    elif change == 'drag':
        inputs['design']['K_m2'] = np.array(inputs['design']['K_m2'], copy=True)
        inputs['design']['K_m2'][0, 0, 0] *= 1.1
    elif change == 'thermal':
        cfg['thermal_geometry'] = dict(cfg['thermal_geometry'])
        selected = 'fields' if cfg.get('continuous_field') or cfg.get('zone_grid_cells') else 'uniform'
        geometry = dict(cfg['thermal_geometry'][selected])
        cfg['thermal_geometry'][selected] = geometry
        geometry['A_0'] = np.asarray(geometry['A_0']) * 1.07
        geometry['D_h'] = np.asarray(geometry['D_h']) * .95
    expected_events, actual_events = [], []
    def control(events):
        return RunControl(cpu_threads=2, progress=lambda value: events.append(('progress', value)),
            outer_iteration=lambda done, total: events.append(('outer', done, total)))
    driver = NativeFull3DDriver(library_path(), table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY'))
    from sjtu_tpmshx.shared.domain.run_warnings import warning_scope
    with warning_scope({}) as expected_records:
        expected = driver.run_prepared(cfg, inputs, control(expected_events))
    result = _Result(1, ct.sizeof(_Result))
    captured_controls, captured_reports = [], []

    def execute(data, controls, energy, explicit_energy, model_h, threads, callbacks, output, error, capacity):
        host = _Control(b'complete-raw', driver.table_directory, threads,
            ct.cast(callbacks, ct.POINTER(abi._Callbacks)).contents)
        original_controls = ct.cast(controls, ct.POINTER(abi._Control)).contents
        if saved:
            raw_prepared = prepared if isinstance(prepared, uniform._Result) else prepared.prepared
            source = _Saved(1, ct.sizeof(_Saved), ct.cast(data, ct.POINTER(abi._Input)),
                config.geometry.L_cell_mm, config.geometry.t_wall_mm, raw_prepared.geometry.epsilon,
                raw_prepared.wall_thickness, raw_prepared.evidence, raw_prepared.notices,
                raw_prepared.notice_count, 1, None)
            if evidence_change in ('missing', 'empty'):
                source.preparation = uniform.abi._Evidence()
                source.inlet_recorded = int(evidence_change == 'empty')
            elif evidence_change == 'uncaptured':
                flags = (_U * source.preparation.range_count)(*([0] + [1] * (source.preparation.range_count - 1)))
                source.range_captured = flags
            elif evidence_change == 'no-finite':
                sample = source.preparation.ranges[0].sample
                sample.have_finite = sample.low = sample.high = 0
                sample.nonfinite = sample.size
            run, restored = _Run(stage_library, source, request, host), False
            try:
                while run.phase not in (3, 4):
                    phase = run.advance()
                    if phase == 7 and not restored:
                        state = run.snapshot()
                        run.close()
                        run = _Run(stage_library, source, request, host, state)
                        _state_equal(run.snapshot(), state)
                        restored = True
                assert restored
                owned = run.take_result()
            finally:
                run.close()
            ct.memmove(ct.byref(result), ct.byref(owned), ct.sizeof(result))
            code = 0
        else:
            code = stage_library.tpmshx_run_case_3d_v1(*_arguments(prepared), ct.byref(request),
                ct.byref(host), ct.byref(result), error, capacity)
        if code == 0:
            captured_reports.append(_evaluate(result))
            captured_controls.append((uniform.v1._struct_values(result.resolved),
                uniform.v1._struct_values(original_controls)))
            ct.memmove(output, ct.byref(result.raw), ct.sizeof(abi._Result))
        return code

    def release(raw):
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))
        ct.memset(raw, 0, ct.sizeof(abi._Result))

    driver.library.tpmshx_solve_full_3d_v5 = execute
    driver.release = release
    try:
        actual = driver.run_prepared(cfg, inputs, control(actual_events))
    finally:
        if result.owner:
            stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))
    assert captured_controls
    for actual_control, expected_control in captured_controls:
        _same(actual_control, expected_control, 'resolved controls')
    assert actual_events == expected_events
    for result in (actual, expected):
        for side in result['flow']:
            if side is not None:
                for name in ('build_seconds', 'solve_seconds'):
                    elapsed = side['last']['pressure'].pop(name)
                    assert type(elapsed) is float and np.isfinite(elapsed) and elapsed >= 0
    _same(actual, expected, 'complete detached native DTO')
    from sjtu_tpmshx.solvers.backends.cpp.full_3d_capture import capture_result
    from sjtu_tpmshx.solvers.applicability_evidence import capture_applicability
    from sjtu_tpmshx.solvers.execution_record import full_execution_record
    public = capture_result(case, cfg, inputs, expected, 1)
    public = replace(public, metadata=dict(public.metadata,
        execution_record=full_execution_record(case, public),
        applicability_evidence=capture_applicability(case, public, expected_records)))
    wanted = evaluation.report.python_report(public)
    wanted['source_result_id'] = wanted['qualification']['source_result_id'] = 'complete-raw'
    _same(captured_reports[0], wanted, 'complete DTO evaluation report')
    return actual


@pytest.mark.parametrize('layout,pair,saved,change', [
    ('uniform', ('air', 'water'), False, None), ('xyz', ('water', 'sco2'), False, None),
    ('grid', ('air', 'water'), False, None), ('asymmetric', ('water', 'air'), False, None),
    ('uniform', ('air', 'water'), True, 'conductivity'),
    ('xyz', ('air', 'water'), True, 'thermal'),
    ('uniform', ('co2', 'air'), True, 'drag')])
def test_complete_raw_dto_and_modified_saved_inputs(preparation_libraries, stage_library,
                                                    layout, pair, saved, change, tmp_path):
    config, request = _configuration(pair, layout)
    with _prepared(preparation_libraries, config, layout) as prepared:
        actual = _full_dto(config, request, prepared, stage_library, saved=saved, change=change)
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    (tmp_path / 'verdict.json').write_text(json.dumps(dict(full_raw_dto_exact=True,
        saved=saved, modification=change, thermal_mode=actual['mode'], outer_index=actual['outer_index'])))


@pytest.mark.parametrize('damage', ['occupied', 'error-input', 'output-input', 'result-version',
    'request-version', 'cpu-zero', 'boolean', 'convergence', 'model-energy', 'thermal-extent', 'topology'])
def test_stage_rejection_preserves_output(preparation_libraries, stage_library, damage):
    config, request = _configuration()
    control, result = _control([]), _Result(1, ct.sizeof(_Result))
    error = ct.create_string_buffer(b'unchanged', 4096)
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        if damage == 'occupied':
            result.owner = 1
        elif damage == 'result-version':
            result.abi_version = 9
        elif damage == 'request-version':
            request.abi_version = 9
        elif damage == 'cpu-zero':
            control.cpu_threads = 0
        elif damage == 'boolean':
            request.force_cell_centered = _Uint(1, 2)
        elif damage == 'convergence':
            request.convergence_mode = b'legacy'
        elif damage == 'model-energy':
            request.energy_iterations = _Size(1, 3)
        elif damage == 'thermal-extent':
            prepared.cell_length.size -= 1
        elif damage == 'topology':
            prepared.input.sco2_nu.mode = 1
            prepared.input.topology = 2
        output = ct.cast(ct.byref(prepared), ct.POINTER(_Result)) if damage == 'output-input' else ct.byref(result)
        error_pointer = ct.cast(ct.byref(prepared), ct.POINTER(ct.c_char)) if damage == 'error-input' else error
        before, original_prepared = bytes(result), bytes(prepared)
        status = stage_library.tpmshx_run_case_3d_v1(ct.byref(prepared), None, None, ct.byref(request),
            ct.byref(control), output, error_pointer, ct.sizeof(prepared) if damage == 'error-input' else len(error))
        assert status == 1
        assert bytes(result) == before and bytes(prepared) == original_prepared
        if damage in ('output-input', 'error-input'):
            assert error.value == b'unchanged'


@pytest.mark.parametrize('saved', [False, True])
@pytest.mark.parametrize('model_h', [False, True])
@pytest.mark.parametrize('tolerance', [0., -1., float('nan'), float('inf'), 1e-8])
def test_create_validates_energy_before_route_selection(
        preparation_libraries, stage_library, saved, model_h, tolerance, monkeypatch):
    from sjtu_tpmshx.shared.domain.compute_config import validate_enthalpy_algorithm
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs

    valid = np.isfinite(tolerance) and tolerance > 0.
    if valid:
        validate_enthalpy_algorithm('temperature_sou', tolerance)
    else:
        with pytest.raises(ValueError, match='finite and positive'):
            validate_enthalpy_algorithm('temperature_sou', tolerance)
    config, request = _configuration()
    if not model_h:
        request.model_h = _IterationOptions()
    recipe = _EnergyOptions(2, tolerance)
    request.energy = ct.pointer(recipe)
    cfg, inputs = build_execution_inputs(prepare_case(config, case_id='energy-validation'))
    driver = NativeFull3DDriver(library_path())
    events, cancellation_checks, calls = [], [], []
    host = _control(events, cancel=lambda: cancellation_checks.append(True) or False)

    class CreationChecked(Exception):
        pass

    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        def create_only(data, *unused):
            calls.append(True)
            source = _Saved(1, ct.sizeof(_Saved), ct.cast(data, ct.POINTER(abi._Input)),
                config.geometry.L_cell_mm, config.geometry.t_wall_mm, prepared.geometry.epsilon,
                prepared.wall_thickness, prepared.evidence, prepared.notices, prepared.notice_count, 1, None)
            arguments = [ct.byref(source)] if saved else _arguments(prepared)
            name = 'tpmshx_stage_run_3d_create' + ('_saved' if saved else '') + '_v1'
            handle, error = ct.c_void_p(), ct.create_string_buffer(4096)
            before = bytes(handle)
            try:
                status = getattr(stage_library, name)(*arguments, ct.byref(request), ct.byref(host),
                    ct.byref(handle), error, len(error))
                assert status == (0 if valid else 1), error.value.decode()
                if valid:
                    phase = _U(999)
                    assert stage_library.tpmshx_stage_run_3d_phase_v1(handle, ct.byref(phase)) == 0
                    assert phase.value == 0
                else:
                    assert bytes(handle) == before
                    assert error.value == b'invalid conservative energy options'
                assert events == [] and cancellation_checks == []
            finally:
                stage_library.tpmshx_stage_run_3d_release_run_v1(ct.byref(handle))
            raise CreationChecked

        monkeypatch.setattr(driver.library, 'tpmshx_solve_full_3d_v5', create_only)
        with pytest.raises(CreationChecked):
            driver.run_prepared(cfg, inputs, RunControl(cpu_threads=2))
    assert calls == [True]


@pytest.mark.parametrize('moment', ['entry', 'outer'])
def test_cancel_retains_only_raw_diagnostics(preparation_libraries, stage_library, moment):
    config, request = _configuration()
    events, checks = [], []
    def cancelled():
        checks.append(True)
        return moment == 'entry' or any(row[0] == 'outer' for row in events)
    control, result, error = _control(events, cancel=cancelled), _Result(1, ct.sizeof(_Result)), ct.create_string_buffer(4096)
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        status = stage_library.tpmshx_run_case_3d_v1(*_arguments(prepared), ct.byref(request),
            ct.byref(control), ct.byref(result), error, len(error))
        assert status == 0, error.value.decode()
    try:
        assert checks and result.raw.stop == 2 and bytes(result.evidence) == bytes(evaluation.report.Evidence())
        from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
        driver = NativeFull3DDriver(library_path())
        assert set(driver._bootstrap_traces(result.raw)) == {'A', 'B'}
    finally:
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))


def test_result_alias_headers_have_independent_lifetime(preparation_libraries, stage_library):
    config, request = _configuration(('co2', 'air'))
    control, result = _control([]), _Result(1, ct.sizeof(_Result))
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            while run.phase not in (3, 4):
                run.advance()
            result = run.take_result()
    try:
        fields = {row.name.decode(): row.value for row in result.evidence.fields[:result.evidence.field_count]}
        for name, alias in [('Ta', 'Ta_display'), ('Tb', 'Tb_display'), ('Ts', 'Ts_display'),
                            ('P_report_A', 'P_fA_display'), ('P_report_B', 'P_fB_display')]:
            assert fields[name].data == fields[alias].data
            assert ct.addressof(fields[name]) != ct.addressof(fields[alias])
            assert ct.addressof(fields[name].shape.contents) != ct.addressof(fields[alias].shape.contents)
        for side in range(2):
            thermal, true_h = result.evidence.thermal.mass[side], result.evidence.thermal.true_h.contents.mass[side]
            assert ct.addressof(thermal.contents) != ct.addressof(true_h.contents)
            for axis in range(3):
                assert thermal[axis].data == true_h[axis].data
                assert ct.addressof(thermal[axis].shape.contents) != ct.addressof(true_h[axis].shape.contents)
        assert _evaluate(result)['source_result_id'] == 'native-3d-stage'
    finally:
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))


@pytest.mark.parametrize('selection', ['model-controls', 'explicit-defaults', 'eos-controls', 'bootstrap', 'temperature'])
def test_selected_run_controls_match_complete_dto(preparation_libraries, stage_library, selection, monkeypatch):
    pair = ('co2', 'air') if selection == 'eos-controls' else ('air', 'water')
    config, request = _configuration(pair)
    updates, prepared_updates = {}, {}
    if selection == 'model-controls':
        request.outer_tol_K, request.thermal_relaxation = _Double(1, .75), _Double(1, .65)
        request.simple_velocity_relaxation = _Double(1, .4)
        request.mom_tol, request.mass_local_tol, request.mass_global_tol = (_Double(1, x) for x in (2e-4, 3e-6, 4e-6))
        request.solid_seed_K, request.roughness_height_m = _Double(1, 335.), _Double(1, 80e-6)
        request.roughness_mode, request.envelope_mode = _Uint(1, 0), _Uint(1, 2)
        request.adaptive_pressure_tolerance, request.track_momentum = _Uint(1, 0), _Uint(1, 1)
        request.pressure_shooting, request.variable_rho_cp = _Uint(1, 0), _Uint(1, 1)
        request.parallel_threshold = _Size(1, 1)
        monkeypatch.setenv('TPMSHX_PARALLEL_THRESHOLD', '1')
        updates.update(outer_tol_K=.75, ltne_alpha_T=.65, simple_velocity_relaxation=.4,
            mom_tol=2e-4, mass_local_tol=3e-6, mass_global_tol=4e-6, T_s_init=335.,
            roughness_resolved=dict(mode='baseline', eps_m=80e-6), envelope_mode='off',
            use_adaptive_amg_tol=False, track_momentum_residual=True,
            _environment={'TPMSHX_P_IN_SHOOT': '0', 'TPMSHX_VAR_RHOCP': '1'})
    elif selection == 'explicit-defaults':
        for name in ('conservative', 'strict_mass_balance', 'force_cell_centered', 'refined_port_energy'):
            setattr(request, name, _Uint(1, 1))
        request.convergence_mode = b'f2'
        updates.update(conservative_ltne=True, strict_mass_balance=True, force_cc_ltne=True,
            port_wall_refine=True, convergence_mode='f2')
    elif selection == 'eos-controls':
        request.energy_sweeps, request.energy_omega = _Size(1, 2), _Double(1, .6)
        request.energy_update_tolerance = _Double(1, 2e-8)
        request.energy_coupled_tolerance, request.energy_equation_tolerance = _Double(1, 2e-3), _Double(1, 3e-3)
        request.require_enthalpy_update_on_temperature = 1
        request.sco2_local_pressure_a = _Uint(1, 1)
        updates.update(ltne_enthalpy_nsweep=2, ltne_enthalpy_omega=.6, ltne_enthalpy_tol=2e-8,
            ltne_enthalpy_coupled_energy_tol=2e-3, ltne_enthalpy_equation_energy_tol=3e-3,
            require_enthalpy_update_on_temperature=True, _environment={'TPMSHX_SCO2_COMPRESSIBLE': '1'})
    elif selection == 'temperature':
        request.model_h = _IterationOptions()
        request.variable_rho_cp, request.thermal_iterations = _Uint(1, 0), _Size(1, 9)
        updates.update(model_h_max_iterations=None, model_h_temperature_tol_K=None, model_h_q_relative_tol=None,
            variable_rho_cp=False, _environment={'TPMSHX_VAR_RHOCP': '0'})
        prepared_updates['ltne_max_iter'] = 9
    else:
        request.coarse_bootstrap, request.coarse_iterations = _Uint(1, 1), _Size(1, 3)
        updates.update(use_coarse_bootstrap=True, coarse_bootstrap_max_iter=3)
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        _full_dto(config, request, prepared, stage_library, cfg_updates=updates, prepared_updates=prepared_updates)


@pytest.mark.parametrize('kind', [np.float16, np.float32])
def test_narrow_geometry_and_reverse_ports_match_complete_dto(preparation_libraries, stage_library, kind):
    config, request = _configuration()
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = kind(7.), kind(.55)
    config.bc_A.dir, config.bc_B.dir = 1, 5
    config.bc_A.in_ctr = config.bc_A.out_ctr = .021
    config.bc_A.in_w, config.bc_A.out_w = .018, .024
    config.bc_B.in_z_ctr = config.bc_B.out_z_ctr = .021
    config.bc_B.in_z_w, config.bc_B.out_z_w = .022, .028
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        _full_dto(config, request, prepared, stage_library)


@pytest.mark.parametrize('evidence_change', ['missing', 'empty', 'uncaptured', 'no-finite'])
def test_saved_evidence_absence_is_not_promoted(preparation_libraries, stage_library, evidence_change):
    config, request = _configuration()
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        _full_dto(config, request, prepared, stage_library, saved=True, evidence_change=evidence_change)


@pytest.mark.parametrize('selection', ['Diamond', 'experimental-drag', 'experimental-nu', 'refined-ports'])
def test_additional_prepared_branches(preparation_libraries, stage_library, selection):
    pair = ('sco2', 'water') if selection == 'experimental-nu' else ('air', 'water')
    config, request = _configuration(pair)
    if selection == 'Diamond':
        config.geometry.tpms = selection
    elif selection == 'experimental-drag':
        config.df_mode = 'experimental'
    elif selection == 'experimental-nu':
        config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
            parameter_version='stage-comparison', source='existing experimental selection', applicability='uniform geometry')
    else:
        config.flags.port_wall_refine = True
        config.solver.Nx, config.solver.Ny, config.solver.Nz = 30, 30, 10
        config.bc_A.in_ctr = config.bc_A.out_ctr = .021
        config.bc_B.in_ctr = config.bc_B.out_ctr = .091
        config.bc_A.in_w = config.bc_A.out_w = .018
        config.bc_B.in_w = config.bc_B.out_w = .072
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        _full_dto(config, request, prepared, stage_library)


@pytest.mark.parametrize('damage', ['build', 'input', 'control', 'missing', 'unknown', 'type', 'size', 'phase'])
def test_invalid_snapshot_does_not_publish_handle(preparation_libraries, stage_library, damage):
    config, request = _configuration()
    control = _control([])
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            run.advance()
            state = deepcopy(run.snapshot())
        if damage == 'build':
            state['build'] = 'another-build'
        elif damage == 'input':
            state['input.a.inlet_velocity'][0] *= 1.01
        elif damage == 'control':
            state['control.max_outer'][0] += 1
        elif damage == 'missing':
            del state['state.phase']
        elif damage == 'unknown':
            state['unknown'] = np.zeros(1)
        elif damage == 'type':
            state['state.phase'] = state['state.phase'].astype(np.float64)
        elif damage == 'size':
            state['state.phase'] = np.repeat(state['state.phase'], 2)
        else:
            state['state.phase'][0] = 0
        fields, keepalive = NativeRun._fields(state)
        handle, error = ct.c_void_p(), ct.create_string_buffer(4096)
        status = stage_library.tpmshx_stage_run_3d_restore_v1(*_arguments(prepared), ct.byref(request),
            ct.byref(control), fields, len(fields), ct.byref(handle), error, len(error))
        assert status == 1 and not handle.value
        assert b'state' in error.value or b'continuation' in error.value
        del keepalive


def test_capture_failure_keeps_result_empty(preparation_libraries, stage_library):
    config, request = _configuration()
    control = _control([])
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        row = next(row for row in prepared.evidence.ranges[:prepared.evidence.range_count] if row.rank)
        row.shape[0] = 0
        row.sample.have_finite = 1
        with _Run(stage_library, prepared, request, control) as run:
            while run.phase not in (3, 4):
                run.advance()
            output, error = _Result(1, ct.sizeof(_Result)), ct.create_string_buffer(4096)
            before = bytes(output)
            assert stage_library.tpmshx_stage_run_3d_take_result_v1(run.handle, ct.byref(output), error, len(error)) == 1
            assert b'captured range has an empty axis' in error.value and bytes(output) == before
            assert stage_library.tpmshx_stage_run_3d_take_result_v1(run.handle, ct.byref(output), error, len(error)) != 0
            assert bytes(output) == before
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(output))
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(output))


def test_snapshot_restores_in_fresh_process(preparation_libraries, stage_library, tmp_path):
    config, request = _configuration()
    events, expected_events = [], []
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        with _Run(stage_library, prepared, request, _control(events)) as run:
            while run.phase != 7:
                assert run.advance() not in (3, 4)
            np.savez(tmp_path / 'state.npz', **run.snapshot())
    script = r"""
import ctypes as ct
import json
from pathlib import Path
import sys
import numpy as np
from sjtu_tpmshx.development.tests import test_native_stage_3d as t
root=Path(sys.argv[1])
with np.load(root/'state.npz',allow_pickle=False) as archive:
    state={name: value.item() if value.ndim==0 and value.dtype.kind=='U' else value
        for name,value in archive.items()}
library=t.stage_library.__wrapped__()
config,request=t._configuration()
events=[]
with t._prepared({'uniform':t.uniform.native.__wrapped__()},config,'uniform') as prepared:
    with t._Run(library,prepared,request,t._control(events,threads=1),state) as run:
        while run.phase not in (3,4):run.advance()
        result=run.take_result()
try:
    np.savez(root/'fields.npz',**t._fields(result.evidence))
    (root/'report.json').write_text(json.dumps(t._evaluate(result)))
    (root/'events.json').write_text(json.dumps(events))
finally:
    library.tpmshx_stage_run_3d_release_v1(ct.byref(result))
"""
    process = subprocess.run([sys.executable, '-c', script, str(tmp_path)],
        capture_output=True, text=True, timeout=120, check=False)
    (tmp_path / 'process.log').write_text(process.stdout + process.stderr)
    assert process.returncode == 0, process.stdout + process.stderr
    _, expected = _reference(config, expected_events)
    with np.load(tmp_path / 'fields.npz', allow_pickle=False) as fields:
        assert set(fields.files) == set(expected.fields)
        for name, values in fields.items():
            np.testing.assert_array_equal(values.view(np.uint8), expected.fields[name].view(np.uint8), err_msg=name)
    wanted = evaluation.report.python_report(expected)
    wanted['source_result_id'] = wanted['qualification']['source_result_id'] = 'native-3d-stage'
    _same(json.loads((tmp_path / 'report.json').read_text()), wanted, 'fresh-process report')
    child_events = [tuple(row) for row in json.loads((tmp_path / 'events.json').read_text())]
    assert events + child_events == expected_events


@pytest.mark.parametrize('operation', ['take-result', 'snapshot', 'phase'])
def test_lifecycle_storage_cannot_overwrite_borrowed_preparation(preparation_libraries, stage_library, operation):
    config, request = _configuration()
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        with _Run(stage_library, prepared, request, _control([])) as run:
            before = bytes(prepared)
            error = ct.cast(ct.byref(prepared), ct.POINTER(ct.c_char))
            if operation == 'take-result':
                output = _Result(1, ct.sizeof(_Result))
                status = stage_library.tpmshx_stage_run_3d_take_result_v1(
                    run.handle, ct.byref(output), error, ct.sizeof(prepared))
                assert not output.owner
            elif operation == 'snapshot':
                output = _Snapshot()
                status = stage_library.tpmshx_stage_run_3d_snapshot_v1(
                    run.handle, ct.byref(output), error, ct.sizeof(prepared))
            else:
                status = stage_library.tpmshx_stage_run_3d_phase_v1(
                    run.handle, ct.cast(error, ct.POINTER(_U)))
            after = bytes(prepared)
            ct.memmove(ct.byref(prepared), before, len(before))
            assert status == 1 and after == before


@pytest.mark.parametrize('null_request', [False, True])
def test_absent_controls_keep_application_budgets(preparation_libraries, stage_library, null_request):
    config, _ = _configuration()
    request, control = _Request(1, ct.sizeof(_Request)), _control([], cancel=lambda: True)
    result, error = _Result(1, ct.sizeof(_Result)), ct.create_string_buffer(4096)
    with _prepared(preparation_libraries, config, 'uniform') as prepared:
        status = stage_library.tpmshx_run_case_3d_v1(*_arguments(prepared),
            None if null_request else ct.byref(request), ct.byref(control), ct.byref(result), error, len(error))
        assert status == 0, error.value.decode()
    try:
        assert result.raw.stop == 2 and not result.evaluation.abi_version
        selected = result.resolved
        assert (selected.initial_simple_iterations, selected.warm_simple_iterations, selected.max_outer,
            selected.thermal_iterations, selected.coarse_iterations) == (2000, 600, 12, 20000, 200)
        assert selected.roughness_height.hex() == (100. * 1e-6).hex()
    finally:
        stage_library.tpmshx_stage_run_3d_release_v1(ct.byref(result))
