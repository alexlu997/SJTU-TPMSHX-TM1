"""Complete 2D results retain their state across native and process boundaries."""
from dataclasses import replace
import subprocess
import sys
import threading

import numpy as np
import pytest

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.io.case_io import save_case
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.solver_checkpoint_io import (
    save_solver_checkpoint, load_solver_checkpoint, load_checkpoint_case)
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import run_case
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
from sjtu_tpmshx.tests.native import test_cpp_full_2d as public
from sjtu_tpmshx.tests.native import test_cpp_full_3d as spatial
from sjtu_tpmshx.tests.native.test_cpp_full_3d import _exact_resume_values
from sjtu_tpmshx.tests.native.test_full_2d import configuration

driver = public.driver
native_path = spatial.native_path
ROOT = public.ROOT
COUNT = 'state.result.outer_history.size'
FORMAT = 'full_2d_continuation_v1'


class PauseCheckpoint(Exception):
    pass


def case(route):
    mode = 'true_h' if route.startswith('temperature_') else route
    config = configuration(mode=mode, outer=3, partial=not route.startswith('temperature_'))
    if route.startswith('temperature_'):
        config = replace(config, solver=replace(config.solver, enthalpy_algorithm=route))
    return prepare_case(config, case_id='full2d-checkpoint-'+route)


def control(driver):
    return RunControl(backend='cpp', native_library=str(driver.path),
                      native_table_directory=driver.table_directory.decode())


def compare_result(actual, expected):
    for key in ('grid', 'fields', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'field_metadata'):
        _exact_resume_values(getattr(actual, key), getattr(expected, key), key)
    _exact_resume_values({k: v for k, v in actual.metadata.items() if k != 'continuation'}, expected.metadata)


@pytest.mark.parametrize('route', ['temperature', 'model_h', 'true_h', 'temperature_sou'])
@pytest.mark.parametrize('cut', [0, 1, 'final'])
def test_full_2d_checkpoint_hdf5_round_trip(driver, tmp_path, route, cut):
    prepared = case(route)
    case_path = save_case(prepared, tmp_path/'case.h5')
    saved_path = tmp_path/'checkpoint.h5'
    expected = run_case(prepared, control(driver))
    def save_at_boundary(state):
        if (int(state['state.phase'][0]) == 2 if cut == 'final' else int(state[COUNT][0]) == cut):
            saved = SolverCheckpoint(str(case_path), prepared.case_id, prepared.model_refs, state, FORMAT)
            save_solver_checkpoint(saved, saved_path)
            state['state.result.thermal.temperature.0'][0] = -1.
            assert saved.native_state['state.result.thermal.temperature.0'][0] > 0.
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        run_case(prepared, control(driver), checkpoint=save_at_boundary)
    saved = load_solver_checkpoint(saved_path)
    actual = run_case(load_checkpoint_case(saved), control(driver), resume_state=saved.native_state)
    compare_result(actual, expected)
    assert actual.metadata['continuation']['completed_outer_steps'] == saved.native_state[COUNT][0]
    assert actual.metadata['continuation']['format'] == FORMAT


@pytest.mark.parametrize('damage', ['build', 'input', 'control', 'type', 'size', 'unknown', 'missing',
                                    'thermal', 'geometry', 'phase', 'nonfinite', 'premature_finish',
                                    'different_exit', 'thermal_mode', 'previous'])
def test_full_2d_checkpoint_rejects_damaged_fields(driver, damage):
    cfg, prepared = build_execution_inputs(case('model_h'))
    saved = {}
    def pause(state):
        if int(state[COUNT][0]) == (0 if damage == 'premature_finish' else 1):
            saved.update(state)
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        driver.run_prepared(cfg, prepared, checkpoint=pause)
    if damage == 'build':
        saved['build'] = 'another-build'
    elif damage == 'input':
        saved['input.sides.0.inlet_velocity'][0] *= 1.01
    elif damage == 'control':
        saved['control.outer_iterations'][0] += 1
    elif damage == 'type':
        saved['state.previous.0'] = saved['state.previous.0'].astype(np.float32)
    elif damage == 'size':
        saved['state.previous.0'] = saved['state.previous.0'][:-1].copy()
    elif damage == 'unknown':
        saved['unknown'] = np.zeros(1)
    elif damage == 'thermal':
        saved['state.result.thermal.temperature.0'] = np.empty(0)
    elif damage == 'geometry':
        saved['state.result.flow.0.epsilon'][0] *= .99
    elif damage == 'phase':
        saved['state.phase'][0] = 0
    elif damage == 'premature_finish':
        saved['state.phase'][0] = 2
        saved['state.result.outer_converged'][0] = 1
    elif damage == 'different_exit':
        saved['state.result.cancelled'][0] = 1
    elif damage == 'thermal_mode':
        saved['state.result.thermal.result.index'][0] = 2
    elif damage == 'nonfinite':
        saved['state.previous.0'][0] = np.nan
    elif damage == 'previous':
        saved['state.previous.0'][0] += .1
    else:
        del saved['state.previous.0']
    with pytest.raises((ValueError, TypeError), match='state|continuation'):
        driver.run_prepared(cfg, prepared, resume_state=saved)


CHILD = r"""
import os
import sys
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.solver_checkpoint_io import (
    load_solver_checkpoint, save_solver_checkpoint, load_checkpoint_case)
from sjtu_tpmshx.solvers.backends.cpp.full_2d import run_case
mode, case_path, saved_path, result_path, library, tables = sys.argv[1:]
control = RunControl(backend='cpp', native_library=library, native_table_directory=tables)
if mode == 'interrupt':
    case = load_case(case_path)
    def stop(state):
        if int(state['state.result.outer_history.size'][0]) == 1:
            saved = SolverCheckpoint(case_path, case.case_id, case.model_refs, state, 'full_2d_continuation_v1')
            save_solver_checkpoint(saved, saved_path)
            os._exit(23)
    run_case(case, control, checkpoint=stop)
    raise RuntimeError('checkpoint boundary was not reached')
saved = load_solver_checkpoint(saved_path)
save_result(run_case(load_checkpoint_case(saved), control, resume_state=saved.native_state), result_path)
"""


@pytest.mark.parametrize('route', ['temperature', 'model_h', 'true_h', 'temperature_sou'])
def test_full_2d_checkpoint_continues_after_process_exit(driver, tmp_path, route):
    if route == 'model_h':
        config = configuration(mode='model_h', outer=3)
        config = replace(config, solver=replace(config.solver, model_h_max_iterations=17,
            model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8, simple_velocity_relaxation=.35))
        prepared = prepare_case(config, case_id='full2d-checkpoint-model_h-controls')
    else:
        prepared = case(route)
    case_path = save_case(prepared, tmp_path/'case.h5')
    saved_path, result_path = tmp_path/'checkpoint.h5', tmp_path/'result.h5'
    arguments = [str(case_path), str(saved_path), str(result_path), str(driver.path), driver.table_directory.decode()]
    stopped = subprocess.run([sys.executable, '-c', CHILD, 'interrupt', *arguments],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    assert not result_path.exists()
    saved = load_solver_checkpoint(saved_path)
    assert saved.native_state[COUNT][0] == 1
    if route == 'model_h':
        assert saved.native_state['control.model_h_iterations.max_iterations'][0] == 17
        assert saved.native_state['control.flow.alpha_velocity'][0] == .35
    finished = subprocess.run([sys.executable, '-c', CHILD, 'resume', *arguments],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert finished.returncode == 0, finished.stderr
    actual, expected = load_result(result_path), run_case(prepared, control(driver))
    compare_result(actual, expected)
    if route == 'model_h':
        assert actual.metadata['simple_velocity_relaxation'] == .35
        assert all(row['settings']['max_iterations'] == 17 for row in actual.metadata['model_h_iterations']['records'])
    actual_metrics, expected_metrics = evaluate(actual), evaluate(expected)
    for key, metric in expected_metrics.metrics.items():
        assert actual_metrics.metrics[key].status == metric.status
        _exact_resume_values(actual_metrics.metrics[key].value, metric.value, key)


def test_checkpoint_rejects_other_dimension_in_the_same_library(native_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case as run_spatial
    planar_driver = NativeFull2DDriver(native_path, table_directory=ROOT/'.cache/native-deps/tables')
    cfg, prepared = build_execution_inputs(case('model_h'))
    planar_state, spatial_state = {}, {}
    def pause_planar(state):
        planar_state.update(state)
        raise PauseCheckpoint
    def pause_spatial(state):
        spatial_state.update(state)
        raise PauseCheckpoint
    spatial_case = spatial.case(cap=3)
    with pytest.raises(PauseCheckpoint):
        planar_driver.run_prepared(cfg, prepared, checkpoint=pause_planar)
    with pytest.raises(PauseCheckpoint):
        run_spatial(spatial_case, spatial.control(native_path), checkpoint=pause_spatial)
    assert planar_state['build'] == spatial_state['build']
    with pytest.raises(ValueError, match='state|continuation'):
        planar_driver.run_prepared(cfg, prepared, resume_state=spatial_state)
    with pytest.raises(ValueError, match='state|continuation'):
        run_spatial(spatial_case, spatial.control(native_path), resume_state=planar_state)


def inner_case(route, *, simple=40):
    eos = route in ('true_h', 'temperature_sou')
    cfg = configuration(mode='true_h' if eos else route, outer=2, simple_max=simple, partial=not eos)
    settings = (dict(ltne_enthalpy_outer=12, ltne_enthalpy_nsweep=3,
                     enthalpy_algorithm=route if route.startswith('temperature_') else 'temperature_sou')
                if eos else dict(model_h_max_iterations=79))
    cfg = replace(cfg, solver=replace(cfg.solver, Nx=4, Ny=3 if eos else 6, **settings))
    return prepare_case(cfg, case_id='full2d-inner-'+route)


def inner_position(state):
    prefix = 'state.thermal.value.'
    owner = 'model_h' if state[prefix+'model_h.present'][0] else 'enthalpy'
    prefix += owner+'.value.'
    position = int(state[prefix+'result.iterations'][0])
    if owner == 'model_h' and state[prefix+'iteration.chunk.present'][0]:
        position += int(state[prefix+'iteration.chunk.value.completed'][0])
    return position


def compare_native(actual, expected):
    actual.pop('continuation')
    _exact_resume_values(actual, expected)


@pytest.mark.parametrize('route', ['temperature', 'model_h', 'true_h', 'temperature_sou'])
@pytest.mark.parametrize('after_update', [False, True])
def test_inner_thermal_checkpoint_keeps_complete_result(driver, route, after_update):
    cfg, prepared = build_execution_inputs(inner_case(route))
    expected = driver.run_prepared(cfg, prepared)
    saved = {}
    def pause(state):
        if state['state.phase'][0] == 7 and bool(inner_position(state)) == after_update:
            saved.update(state)
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        driver.run_prepared(cfg, prepared, checkpoint=pause)
    assert saved['format'][0] == 2
    compare_native(driver.run_prepared(cfg, prepared, resume_state=saved), expected)


@pytest.mark.parametrize('route', ['temperature', 'model_h'])
@pytest.mark.parametrize('position', [0, 25, 50])
def test_inner_refinement_checkpoint_keeps_complete_result(driver, route, position):
    cfg, prepared = build_execution_inputs(inner_case(route))
    expected = driver.run_prepared(cfg, prepared)
    saved = {}
    def pause(state):
        if state['state.phase'][0] == 8 and inner_position(state) >= position:
            saved.update(state)
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        driver.run_prepared(cfg, prepared, checkpoint=pause)
    fine = 'state.result.refined.value.'
    assert saved[fine+'thermal.mass_x.0'].size > saved['state.result.thermal.mass_x.0'].size
    assert saved[fine+'thermal.temperature.0'].size == 4*saved['state.result.thermal.temperature.0'].size
    compare_native(driver.run_prepared(cfg, prepared, resume_state=saved), expected)


@pytest.mark.parametrize('outer', [0, 1])
@pytest.mark.parametrize('iteration', [0, 1, 7])
def test_inner_flow_checkpoint_keeps_complete_result(driver, outer, iteration):
    cfg, prepared = build_execution_inputs(inner_case('model_h'))
    expected = driver.run_prepared(cfg, prepared)
    saved = {}
    def pause(state):
        if (state['state.phase'][0] == 6 and state[COUNT][0] == outer
                and state['state.flow.value.0.iteration.value.result.iterations'][0] == iteration):
            saved.update(state)
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        driver.run_prepared(cfg, prepared, checkpoint=pause)
    if outer:
        assert saved['state.flow.value.0.flow.pressure_iterations.size'][0] > 0
    compare_native(driver.run_prepared(cfg, prepared, resume_state=saved), expected)


def test_inner_flow_keeps_two_workers_and_original_callback_positions(driver):
    cfg, prepared = build_execution_inputs(inner_case('model_h'))
    barrier = threading.Barrier(2, timeout=5)
    identifiers = {(outer, side): set() for outer in range(2) for side in 'AB'}
    positions = {key: [] for key in identifiers}
    outer = 0
    def outer_iteration(index, total):
        nonlocal outer
        outer = index
    def residual(side, iteration, value):
        identifiers[outer, side].add(threading.get_ident())
        positions[outer, side].append(iteration)
        if iteration == 1:
            barrier.wait()
    actual = driver.run_prepared(cfg, prepared, replace(control(driver), residual=residual, outer_iteration=outer_iteration),
                                 checkpoint=lambda state: None)
    assert all(len(ids) == 1 for ids in identifiers.values())
    assert all(identifiers[i, 'A'].isdisjoint(identifiers[i, 'B']) for i in range(2))
    expected_positions = {key: [] for key in identifiers}
    def reference_residual(side, iteration, value):
        expected_positions[outer, side].append(iteration)
    expected = driver.run_prepared(cfg, prepared,
        replace(control(driver), residual=reference_residual, outer_iteration=outer_iteration))
    assert positions == expected_positions
    assert all(value[0] == 1 for value in positions.values())
    _exact_resume_values(actual, expected)


@pytest.mark.parametrize('damage', ['flow_budget', 'flow_monitor', 'flow_previous', 'flow_field',
    'flow_shared_field', 'flow_geometry', 'flow_owner', 'flow_acceleration',
    'flow_acceleration_extent', 'flow_acceleration_budget', 'thermal_owner', 'thermal_field',
    'thermal_shared_field', 'thermal_budget', 'thermal_settings', 'thermal_input', 'fine_grid', 'fine_port'])
def test_inner_checkpoint_rejects_damaged_iteration(driver, damage):
    cfg, prepared = build_execution_inputs(inner_case('model_h'))
    saved = {}
    def pause(state):
        phase = 6 if damage.startswith('flow') else 8 if damage.startswith('fine') else 7
        if state['state.phase'][0] != phase:
            return
        position = state['state.flow.value.0.iteration.value.result.iterations'][0] if phase == 6 else inner_position(state)
        if position > 0:
            saved.update(state)
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        driver.run_prepared(cfg, prepared, checkpoint=pause)
    flow = 'state.flow.value.0.'
    thermal = 'state.thermal.value.model_h.value.'
    if damage == 'flow_acceleration':
        saved['state.flow.value.1.iteration.value.pressure_scale'][0] = 0.
    elif damage == 'flow_acceleration_extent':
        saved['state.flow.value.1.iteration.value.acceleration.x.0'] = np.empty(0)
    elif damage == 'flow_acceleration_budget':
        saved['state.flow.value.1.iteration.value.result.acceleration_attempts'][0] = 100
    elif damage == 'flow_budget':
        saved[flow+'iteration.value.result.iterations'][0] = 40
    elif damage == 'flow_monitor':
        saved[flow+'iteration.value.convergence.streak'][0] = 100
    elif damage == 'flow_previous':
        saved[flow+'iteration.value.convergence.previous.0'] = np.empty(0)
    elif damage == 'flow_field':
        saved[flow+'flow.density'][0] = np.nan
    elif damage == 'flow_shared_field':
        saved[flow+'iteration.value.fields.0'] = saved[flow+'flow.u'].copy()
    elif damage == 'flow_geometry':
        saved[flow+'flow.epsilon'][0] *= .9
    elif damage == 'flow_owner':
        saved[flow+'iteration.present'][0] = 0
    elif damage == 'thermal_owner':
        saved['state.thermal.value.model_h.present'][0] = 0
    elif damage == 'thermal_field':
        saved['state.result.thermal.temperature.0'][0] = np.nan
    elif damage == 'thermal_shared_field':
        saved[thermal+'iteration.temperature.0'] = saved['state.result.thermal.temperature.0'].copy()
    elif damage == 'thermal_budget':
        saved[thermal+'iteration.chunk.value.completed'][0] = 99999
    elif damage == 'thermal_settings':
        saved['state.result.thermal.model_h_iterations.value.max_iterations'][0] += 1
    elif damage == 'thermal_input':
        saved['state.result.thermal.pressure.0'][0] += 1.
    elif damage == 'fine_grid':
        saved['state.result.refined.value.dx'][0] *= .99
    else:
        saved['state.result.refined.value.inlet_profile.0'][0] += .1
    with pytest.raises(ValueError, match='state|continuation|SIMPLE|model-h|chunk|monitor'):
        driver.run_prepared(cfg, prepared, resume_state=saved)


@pytest.mark.parametrize('phase', [6, 7, 8])
def test_inner_cancel_keeps_last_complete_boundary(driver, phase):
    cfg, prepared = build_execution_inputs(inner_case('model_h'))
    saved = {}
    cancel = False
    def checkpoint(state):
        nonlocal cancel
        assert not cancel
        saved.clear()
        saved.update(state)
        if state['state.phase'][0] == phase:
            position = state['state.flow.value.0.iteration.value.result.iterations'][0] if phase == 6 else inner_position(state)
            cancel = position > 0
    with pytest.raises(CancelledError):
        driver.run_prepared(cfg, prepared, replace(control(driver), cancel_check=lambda: cancel), checkpoint=checkpoint)
    assert saved['state.phase'][0] == phase
    compare_native(driver.run_prepared(cfg, prepared, resume_state=saved), driver.run_prepared(cfg, prepared))


INNER_CHILD = r"""
import os
import sys
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.solver_checkpoint_io import load_solver_checkpoint, save_solver_checkpoint, load_checkpoint_case
from sjtu_tpmshx.solvers.backends.cpp.full_2d import run_case
from sjtu_tpmshx.tests.native.test_cpp_full_2d_run import inner_position
mode, target, case_path, saved_path, result_path, library, tables = sys.argv[1:]
control = RunControl(backend='cpp', native_library=library, native_table_directory=tables)
if mode == 'interrupt':
    case = load_case(case_path)
    def stop(state):
        if state['state.phase'][0] != int(target):
            return
        position = state['state.flow.value.0.iteration.value.result.iterations'][0] if target == '6' else inner_position(state)
        if position >= (7 if target == '6' else 1):
            saved = SolverCheckpoint(case_path, case.case_id, case.model_refs, state, 'full_2d_continuation_v1')
            save_solver_checkpoint(saved, saved_path)
            os._exit(23)
    run_case(case, control, checkpoint=stop)
    raise RuntimeError('inner checkpoint boundary was not reached')
saved = load_solver_checkpoint(saved_path)
save_result(run_case(load_checkpoint_case(saved), control, resume_state=saved.native_state), result_path)
"""


@pytest.mark.parametrize('phase,route', [(6, 'model_h'), (6, 'true_h'), (7, 'temperature'), (7, 'model_h'),
    (7, 'true_h'), (7, 'temperature_sou'), (8, 'temperature'), (8, 'model_h')])
def test_inner_checkpoint_continues_after_process_exit(driver, tmp_path, phase, route):
    prepared = inner_case(route)
    case_path = save_case(prepared, tmp_path/'case.h5')
    saved_path, result_path = tmp_path/'checkpoint.h5', tmp_path/'result.h5'
    arguments = [str(phase), str(case_path), str(saved_path), str(result_path), str(driver.path), driver.table_directory.decode()]
    stopped = subprocess.run([sys.executable, '-c', INNER_CHILD, 'interrupt', *arguments],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    assert not result_path.exists()
    saved = load_solver_checkpoint(saved_path)
    assert saved.native_state['state.phase'][0] == phase
    assert saved.native_state['format'][0] == 2
    if phase == 6:
        prefix = 'state.flow.value.1.iteration.value.'
        assert saved.native_state[prefix+'acceleration.x.size'][0] >= 2
        assert saved.native_state[prefix+'result.acceleration_attempts'][0] > 0
    finished = subprocess.run([sys.executable, '-c', INNER_CHILD, 'resume', *arguments],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert finished.returncode == 0, finished.stderr
    actual, expected = load_result(result_path), run_case(prepared, control(driver))
    compare_result(actual, expected)
    actual_metrics, expected_metrics = evaluate(actual), evaluate(expected)
    for name, metric in expected_metrics.metrics.items():
        value = actual_metrics.metrics[name]
        assert value.status == metric.status
        _exact_resume_values(value.value, metric.value, name)


@pytest.mark.parametrize('cut', ['completed_side', 'confirmation'])
def test_inner_flow_keeps_each_side_position(driver, cut):
    cfg, prepared = build_execution_inputs(inner_case('model_h', simple=400))
    expected = driver.run_prepared(cfg, prepared)
    saved = {}
    def pause(state):
        if state['state.phase'][0] != 6:
            return
        active = [bool(state[f'state.flow.value.{side}.iteration.present'][0]) for side in (0, 1)]
        selected = (active[0] != active[1] if cut == 'completed_side' else any(
            active[side] and state[f'state.flow.value.{side}.iteration.value.convergence.streak'][0] > 0
            for side in (0, 1)))
        if selected:
            saved.update(state)
            raise PauseCheckpoint
    with pytest.raises(PauseCheckpoint):
        driver.run_prepared(cfg, prepared, checkpoint=pause)
    compare_native(driver.run_prepared(cfg, prepared, resume_state=saved), expected)
