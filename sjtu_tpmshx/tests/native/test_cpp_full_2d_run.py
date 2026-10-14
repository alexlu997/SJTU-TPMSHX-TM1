"""Complete 2D results retain their state across native and process boundaries."""
from dataclasses import replace
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.module_ports import RunControl
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


@pytest.mark.parametrize('route', ['temperature', 'model_h', 'true_h', 'temperature_fou', 'temperature_sou'])
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
    prepared = case(route)
    if route == 'model_h':
        prepared = replace(prepared, parameters={**prepared.parameters,
            'model_h_max_iterations': 17, 'model_h_temperature_tol_K': 1e-5, 'model_h_q_relative_tol': 1e-8})
    case_path = save_case(prepared, tmp_path/'case.h5')
    saved_path, result_path = tmp_path/'checkpoint.h5', tmp_path/'result.h5'
    arguments = [str(case_path), str(saved_path), str(result_path), str(driver.path), driver.table_directory.decode()]
    stopped = subprocess.run([sys.executable, '-c', CHILD, 'interrupt', *arguments],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    assert not result_path.exists()
    saved = load_solver_checkpoint(saved_path)
    assert saved.native_state[COUNT][0] == 1
    finished = subprocess.run([sys.executable, '-c', CHILD, 'resume', *arguments],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert finished.returncode == 0, finished.stderr
    actual, expected = load_result(result_path), run_case(prepared, control(driver))
    compare_result(actual, expected)
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
