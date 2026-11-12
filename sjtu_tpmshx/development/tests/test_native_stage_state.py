"""Native stages retain full 2D continuation, controls and result evidence."""
import ctypes as ct
from contextlib import contextmanager
from copy import deepcopy
import json

import numpy as np
import pytest

from sjtu_tpmshx.compute import compute
from sjtu_tpmshx.development.tests import test_native_stage_continuous as continuous
from sjtu_tpmshx.development.tests import test_native_stage_uniform as uniform
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.io.result_io import save_result
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
from sjtu_tpmshx.solvers.backends.cpp.run_state import NativeRun, _Field, _Snapshot
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs

preparation_library = uniform.preparation_library
continuous_library = continuous.preparation_library
_Request = uniform.report.record('StateRequest', [('abi_version', ct.c_uint32), ('struct_size', ct.c_size_t),
    ('values', uniform._RequestV2), ('energy_iterations', uniform._Size), ('energy_sweeps', uniform._Size),
    *((name, uniform._Double) for name in ('energy_omega', 'energy_update_tolerance',
        'energy_coupled_tolerance', 'energy_equation_tolerance')),
    ('require_enthalpy_update_on_temperature', ct.c_uint32)])


@pytest.fixture(scope='module')
def stage_library():
    library = ct.CDLL(str(uniform.library_path()))
    common = [ct.POINTER(uniform.preparation._Result), ct.POINTER(continuous.preparation._Result),
        ct.POINTER(_Request), ct.POINTER(uniform._Control)]
    tail = [ct.POINTER(ct.c_char), ct.c_size_t]
    signatures = {
        'create': [*common, ct.POINTER(ct.c_void_p), *tail],
        'restore': [*common, ct.POINTER(_Field), ct.c_size_t, ct.POINTER(ct.c_void_p), *tail],
        'advance_step': [ct.c_void_p, ct.POINTER(ct.c_uint32), *tail],
        'phase': [ct.c_void_p, ct.POINTER(ct.c_uint32)],
        'snapshot': [ct.c_void_p, ct.POINTER(_Snapshot), *tail],
        'take_result': [ct.c_void_p, ct.POINTER(uniform._Result), *tail],
        'release_run': [ct.POINTER(ct.c_void_p)],
    }
    for name, arguments in signatures.items():
        function = getattr(library, 'tpmshx_stage_run_2d_' + name + '_v1')
        function.argtypes, function.restype = arguments, None if name == 'release_run' else ct.c_int
    library.tpmshx_run_state_release_v1.argtypes = [ct.POINTER(_Snapshot)]
    library.tpmshx_run_state_release_v1.restype = None
    library.tpmshx_stage_run_2d_release_v1.argtypes = [ct.POINTER(uniform._Result)]
    library.tpmshx_stage_run_2d_release_v1.restype = None
    return library


class _Run(NativeRun):
    def __init__(self, library, prepared, request, control, state=None):
        self.handle, self.library = ct.c_void_p(), library
        self.prepared, self.request, self.callbacks = prepared, request, control
        for name, entry in [('advance', 'advance_step'), ('phase', 'phase'), ('snapshot', 'snapshot'),
                            ('take_result', 'take_result'), ('release', 'release_run')]:
            setattr(self, '_' + name, getattr(library, 'tpmshx_stage_run_2d_' + entry + '_v1'))
        self._release_snapshot = library.tpmshx_run_state_release_v1
        spatial = isinstance(prepared, continuous.preparation._Result)
        common = [None if spatial else ct.byref(prepared), ct.byref(prepared) if spatial else None,
            ct.byref(request), ct.byref(control)]
        if state is None:
            self._call(library.tpmshx_stage_run_2d_create_v1, *common, ct.byref(self.handle))
        else:
            fields, keepalive = self._fields(state)
            self._call(library.tpmshx_stage_run_2d_restore_v1, *common, fields, len(fields), ct.byref(self.handle))
            del keepalive

    def take_result(self):
        value = uniform._Result(1, ct.sizeof(uniform._Result))
        self._call(self._take_result, self.handle, ct.byref(value))
        return value


def _request(config, *, bounded=True):
    request = _Request(3, ct.sizeof(_Request), uniform._request())
    if bounded:
        request.values.values.max_iter_simple = uniform._Size(1, 12)
        request.values.values.max_outer_ltne = uniform._Size(1, 2)
        config.solver.max_iter_simple, config.solver.max_outer_ltne = 12, 2
        if any(getattr(config, 'fluid_' + side).type in ('co2', 'sco2') for side in 'AB'):
            request.values.values.max_iter_simple = uniform._Size()
            config.solver.max_iter_simple = None
            request.energy_iterations = uniform._Size(1, 9)
            config.solver.ltne_enthalpy_outer = 9
        else:
            request.values.values.model_h = uniform._IterationOptions(9, .5, 1e-3)
            config.solver.model_h_max_iterations = 9
            config.solver.model_h_temperature_tol_K = .5
            config.solver.model_h_q_relative_tol = 1e-3
    return request


@contextmanager
def _prepared(preparation_library, continuous_library, config, spatial):
    if spatial:
        status, prepared, _, error, _, source = continuous.preparation._call(
            continuous_library, 'prepare_flow_case', config)
    else:
        status, prepared, _, error, _, source = uniform.preparation._call(preparation_library, config)
    assert status == 0, error
    try:
        yield prepared
    finally:
        if spatial:
            continuous.preparation._release(continuous_library, prepared)
        else:
            preparation_library.tpmshx_preparation_case_2d_release_v2(ct.byref(prepared))
        del source


def _state_equal(actual, expected):
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        if isinstance(value, str):
            assert actual[key] == value, key
        else:
            assert actual[key].dtype == value.dtype, key
            np.testing.assert_array_equal(actual[key].view(np.uint8), value.view(np.uint8), err_msg=key)


def _old_initial(config):
    class Paused(Exception):
        pass
    state = {}
    def checkpoint(value):
        state.update(value)
        raise Paused
    cfg, prepared = build_execution_inputs(prepare_case(config, case_id='stage-state-reference'))
    driver = NativeFull2DDriver(uniform.library_path())
    with pytest.raises(Paused):
        driver.run_prepared(cfg, prepared, RunControl(cpu_threads=2), checkpoint=checkpoint)
    return state


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('pair', [('air', 'water'), ('water', 'sco2'), ('co2', 'air')])
def test_stage_resume_at_each_boundary_is_exact(preparation_library, continuous_library, stage_library,
                                               spatial, pair, tmp_path):
    config = continuous._configuration(pair) if spatial else uniform._configuration(pair)
    request = _request(config)
    progress, residuals = [], []
    callback = uniform.abi._Progress(lambda _, current, total: progress.append((current, total)))
    residual = uniform.abi._Residual(lambda *values: residuals.append(values[1:]))
    control = uniform._Control(b'stage-state', None, 2,
        uniform.abi._Callbacks(uniform.abi._Cancel(), callback, residual, None))
    snapshots = {}
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    with _prepared(preparation_library, continuous_library, config, spatial) as prepared:
        run = _Run(stage_library, prepared, request, control)
        try:
            with pytest.raises(RuntimeError, match='result|phase|complete'):
                run.take_result()
            while run.phase != 3:
                phase = run.advance()
                assert phase != 4
                if phase in (1, 2, 6, 7, 8) and phase not in snapshots:
                    state = run.snapshot()
                    if phase == 1:
                        _state_equal(state, _old_initial(config))
                    snapshots[phase] = state
                    np.savez_compressed(tmp_path / f'state-{phase}.npz', **state)
                    run.close()
                    control.cpu_threads = 1 if control.cpu_threads == 2 else 2
                    run = _Run(stage_library, prepared, request, control, state)
                    _state_equal(run.snapshot(), state)
            output = uniform._Result(1, ct.sizeof(uniform._Result))
            before_prepared, before_output = bytes(prepared), bytes(output)
            assert stage_library.tpmshx_stage_run_2d_take_result_v1(run.handle, ct.byref(output),
                ct.cast(ct.byref(prepared), ct.POINTER(ct.c_char)), ct.sizeof(prepared)) == 1
            assert bytes(prepared) == before_prepared and bytes(output) == before_output
            result = run.take_result()
            with pytest.raises(RuntimeError, match='result|taken'):
                run.take_result()
        finally:
            run.close()
            run.close()
    try:
        expected_progress, expected_residuals = [], []
        _, expected, _ = compute(config, control=RunControl(cpu_threads=2,
            native_library=str(uniform.library_path()),
            outer_iteration=lambda *values: expected_progress.append(values),
            residual=lambda side, iteration, value: expected_residuals.append(('AB'.index(side), iteration, value))))
        actual = uniform._evaluate(result.evidence)
        wanted = uniform.report.python_report(expected)
        wanted['source_result_id'] = wanted['qualification']['source_result_id'] = 'stage-state'
        assert actual == wanted
        assert result.evidence.field_count == len(expected.fields)
        for index in range(result.evidence.field_count):
            field = result.evidence.fields[index]
            value = field.value
            array = np.ctypeslib.as_array(ct.cast(value.data, ct.POINTER(ct.c_double)),
                shape=(value.shape[0] * value.shape[1],)).reshape(value.shape[0], value.shape[1])
            np.testing.assert_array_equal(array.view(np.uint64), expected.fields[field.name.decode()].view(np.uint64))
        assert progress == expected_progress
        for side in (0, 1):
            assert [row for row in residuals if row[0] == side] == [row for row in expected_residuals if row[0] == side]
        assert {1, 2, 6, 7}.issubset(snapshots)
        if pair == ('air', 'water'):
            assert 8 in snapshots
        save_result(expected, tmp_path / 'reference.h5')
        (tmp_path / 'native-report.json').write_text(json.dumps(actual, indent=2))
        (tmp_path / 'reference-report.json').write_text(json.dumps(wanted, indent=2))
        (tmp_path / 'events.json').write_text(json.dumps({'native_progress': progress,
            'reference_progress': expected_progress, 'native_residuals': residuals,
            'reference_residuals': expected_residuals}))
        (tmp_path / 'verdict.json').write_text(json.dumps({'passed': True, 'phases': sorted(snapshots),
            'field_bits_exact': len(expected.fields), 'reports_exact': True, 'events_exact': True}))
    finally:
        stage_library.tpmshx_stage_run_2d_release_v1(ct.byref(result))


@pytest.mark.parametrize('pair', [('co2', 'air'), ('water', 'sco2')])
@pytest.mark.parametrize('field,host,value', [
    ('energy_iterations', 'ltne_enthalpy_outer', 11), ('energy_sweeps', 'ltne_enthalpy_nsweep', 4),
    ('energy_omega', 'ltne_enthalpy_omega', .65), ('energy_update_tolerance', 'ltne_enthalpy_tol', .03),
    ('energy_coupled_tolerance', 'ltne_enthalpy_coupled_energy_tol', 2e-4),
    ('energy_equation_tolerance', 'ltne_enthalpy_equation_energy_tol', 3e-4),
    ('require_enthalpy_update_on_temperature', 'require_enthalpy_update_on_temperature', 1)])
def test_stage_partial_energy_matches_selected_runtime(preparation_library, continuous_library, stage_library,
                                                       pair, field, host, value):
    config = uniform._configuration(pair)
    request = _request(config, bounded=False)
    setattr(config.solver, host, bool(value) if field.startswith('require_') else value)
    if field.startswith('require_'):
        setattr(request, field, value)
    else:
        option = uniform._Size if field in ('energy_iterations', 'energy_sweeps') else uniform._Double
        setattr(request, field, option(1, value))
    control = uniform._Control(b'partial', None, 2)
    with _prepared(preparation_library, continuous_library, config, False) as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            assert run.advance() == 1
            _state_equal(run.snapshot(), _old_initial(config))


@pytest.mark.parametrize('damage', ['build', 'input', 'control', 'missing', 'unknown', 'type', 'size', 'phase'])
def test_stage_rejects_changed_continuation(preparation_library, continuous_library, stage_library, damage):
    config = uniform._configuration(('air', 'water'))
    request, control = _request(config), uniform._Control(b'damaged', None, 2)
    with _prepared(preparation_library, continuous_library, config, False) as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            run.advance()
            state = deepcopy(run.snapshot())
        if damage == 'build':
            state['build'] = 'another-build'
        elif damage == 'input':
            state['input.sides.0.inlet_velocity'][0] *= 1.01
        elif damage == 'control':
            state['control.outer_iterations'][0] += 1
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
        with pytest.raises(ValueError, match='state|continuation'):
            _Run(stage_library, prepared, request, control, state)


def test_stage_cancel_and_boundary_storage(preparation_library, continuous_library, stage_library):
    config = uniform._configuration(('air', 'water'))
    request = _request(config)
    cancel = uniform.abi._Cancel(lambda _: 1)
    control = uniform._Control(b'cancel', None, 2,
        uniform.abi._Callbacks(cancel, uniform.abi._Progress(), uniform.abi._Residual(), None))
    with _prepared(preparation_library, continuous_library, config, False) as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            while run.phase != 4:
                run.advance()
            with pytest.raises(RuntimeError, match='cancelled'):
                run.take_result()
            with pytest.raises(RuntimeError, match='snapshot|boundary'):
                run.snapshot()
        handle, error = ct.c_void_p(), ct.create_string_buffer(4096)
        arguments = [ct.byref(prepared), None, ct.byref(request), ct.byref(control)]
        create = stage_library.tpmshx_stage_run_2d_create_v1
        before = bytes(prepared)
        assert create(*arguments, ct.byref(handle), ct.cast(ct.byref(prepared), ct.POINTER(ct.c_char)),
                      ct.sizeof(prepared)) == 1
        assert bytes(prepared) == before and not handle.value
        request.energy_iterations = uniform._Size(2, 9)
        assert create(*arguments, ct.byref(handle), error, len(error)) == 1
        assert not handle.value
        request.energy_iterations = uniform._Size(1, 9)
        assert create(*arguments, ct.byref(handle), error, len(error)) == 1
        assert b'true-h' in error.value and not handle.value


def test_stage_failed_flow_preserves_original_error(preparation_library, continuous_library, stage_library, tmp_path):
    config = uniform._configuration(('co2', 'air'))
    request = _request(config)
    request.values.values.max_iter_simple = uniform._Size(1, 12)
    config.solver.max_iter_simple = 12
    control = uniform._Control(b'failed-flow', None, 2)
    with _prepared(preparation_library, continuous_library, config, False) as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            with pytest.raises(ValueError, match='exterior inflow') as actual:
                while run.phase != 3:
                    run.advance()
            assert run.phase == 5
            with pytest.raises(RuntimeError, match='snapshot|boundary'):
                run.snapshot()
            with pytest.raises(RuntimeError, match='result'):
                run.take_result()
    with pytest.raises(ValueError) as expected:
        compute(config, control=RunControl(cpu_threads=2, native_library=str(uniform.library_path())))
    assert str(actual.value) == str(expected.value)
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    (tmp_path / 'verdict.json').write_text(json.dumps({'passed': True, 'phase': 5,
        'error': str(actual.value), 'original_error_preserved': True, 'no_result_or_checkpoint': True}))


def test_stage_callback_failure_cancels_before_result(preparation_library, continuous_library, stage_library):
    config = uniform._configuration(('air', 'water'))
    request, errors = _request(config), []
    def progress(_context, _current, _total):
        try:
            raise LookupError('callback failed')
        except Exception as error:
            errors.append(error)
    callback = uniform.abi._Progress(progress)
    cancel = uniform.abi._Cancel(lambda _: bool(errors))
    control = uniform._Control(b'callback', None, 2,
        uniform.abi._Callbacks(cancel, callback, uniform.abi._Residual(), None))
    with _prepared(preparation_library, continuous_library, config, False) as prepared:
        with _Run(stage_library, prepared, request, control) as run:
            while run.phase != 4:
                run.advance()
            assert errors and isinstance(errors[0], LookupError)
            with pytest.raises(RuntimeError, match='cancelled'):
                run.take_result()
