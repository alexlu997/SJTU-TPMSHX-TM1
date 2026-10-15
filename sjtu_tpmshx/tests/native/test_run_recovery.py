"""Public saved runs retain native evidence through pause and process exit."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.solver_checkpoint_io import load_solver_checkpoint
from sjtu_tpmshx.tests.native import test_cpp_full_3d as spatial
from sjtu_tpmshx.tests.native.test_cpp_full_2d_run import inner_case
from sjtu_tpmshx.tests.native.test_cpp_full_3d import _exact_resume_values as exact
from sjtu_tpmshx.workflows.compute import compute
from sjtu_tpmshx.workflows.recovery import compute_run, resume_run

native_path = spatial.native_path


def configuration(route):
    case = inner_case(route[3:]) if route.startswith('2d-') else spatial.case(route[3:], cap=2)
    return ComputeConfig.from_dict(mutable_data(case.config_snapshot))


def same_result(actual, expected, actual_metrics, expected_metrics):
    for name in ('grid', 'fields', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'field_metadata'):
        exact(getattr(actual, name), getattr(expected, name), name)
    omitted = {'provenance', 'timings_s', 'recovery', 'continuation'}
    exact({k: v for k, v in actual.metadata.items() if k not in omitted},
          {k: v for k, v in expected.metadata.items() if k not in omitted}, 'metadata')
    exact({k: asdict(v) for k, v in actual_metrics.metrics.items()},
          {k: asdict(v) for k, v in expected_metrics.metrics.items()}, 'metrics')
    assert actual_metrics.qualification['source_result_id'] == actual.result_id
    exact({k: v for k, v in actual_metrics.qualification.items() if k != 'source_result_id'},
          {k: v for k, v in expected_metrics.qualification.items() if k != 'source_result_id'}, 'qualification')
    assert actual_metrics.source_result_id == actual.result_id


@pytest.mark.parametrize('route', ['2d-temperature', '2d-model_h', '2d-true_h',
    '2d-temperature_fou', '2d-temperature_sou', '3d-air-air', '3d-water-air', '3d-sco2-water'])
def test_native_saved_run_preserves_complete_public_evidence(native_path, tmp_path, route):
    config = configuration(route)
    control = spatial.control(native_path)
    case, expected, expected_metrics = compute(config, case_id=route, control=control)
    pause = threading.Event()
    paused = tmp_path / 'paused'
    with pytest.raises(PausedRun):
        compute_run(config, paused, checkpoint_interval_s=3600., case_id=case.case_id,
                    control=replace(control, iteration=lambda _: pause.set()), pause_check=pause.is_set)
    checkpoint = paused / 'checkpoint.h5'
    saved = load_solver_checkpoint(checkpoint)
    assert int(saved.native_state['state.phase'][0]) >= 6
    assert json.loads((paused / 'run.json').read_text())['state'] == 'paused'
    assert not (paused / 'results.h5').exists()
    previous = {name: (paused / name).read_bytes() for name in ('case.h5', 'checkpoint.h5', 'run.json')}
    resumed = tmp_path / 'resumed'
    _, actual, actual_metrics = resume_run(checkpoint, resumed, checkpoint_interval_s=3600., control=control)
    same_result(actual, expected, actual_metrics, expected_metrics)
    same_result(load_result(resumed / 'results.h5'), expected,
                load_metrics(resumed / 'metrics.json'), expected_metrics)
    assert {name: (paused / name).read_bytes() for name in previous} == previous
    assert json.loads((resumed / 'run.json').read_text())['state'] == 'completed'


@pytest.mark.parametrize('route', ['2d-model_h', '3d-air-air'])
@pytest.mark.parametrize('interrupt,exit_code', [('pause', 3), ('crash', 23)])
def test_cli_process_exit_and_relocated_resume_keep_public_result(
        native_path, tmp_path, route, interrupt, exit_code):
    config = configuration(route)
    control = spatial.control(native_path)
    _, expected, expected_metrics = compute(config, case_id=route, control=control)
    config_path, original = tmp_path / 'config.json', tmp_path / 'original'
    config.to_json(config_path)
    script = '''
import os, signal, sys
from sjtu_tpmshx import cli
from sjtu_tpmshx.workflows import recovery
save = recovery.save_solver_checkpoint
def interrupt_after_publication(*args):
    save(*args)
    print('checkpoint-ready', flush=True)
    command = sys.stdin.readline().strip()
    if command == 'crash':
        os._exit(23)
    signal.raise_signal(signal.SIGINT)
recovery.save_solver_checkpoint = interrupt_after_publication
status = cli.main(sys.argv[1:])
assert 'PySide6' not in sys.modules
raise SystemExit(status)
'''
    args = ['run', str(config_path), str(original), '--case-id', route, '--backend', 'cpp',
            '--native-library', str(native_path), '--native-table-directory', control.native_table_directory,
            '--checkpoint-interval', '3600']
    process = subprocess.run([sys.executable, '-c', script, *args], input=interrupt + '\n',
                             capture_output=True, text=True, timeout=120)
    assert process.returncode == exit_code, process.stdout + process.stderr
    assert 'checkpoint-ready' in process.stdout
    record = json.loads((original / 'run.json').read_text())
    assert record['state'] == ('paused' if interrupt == 'pause' else 'running')
    assert not (original / 'results.h5').exists()
    moved = original.rename(tmp_path / 'moved')
    before = {name: (moved / name).read_bytes() for name in ('checkpoint.h5', 'case.h5', 'run.json')}
    target = tmp_path / 'continued'
    args = ['resume', str(moved / 'checkpoint.h5'), str(target), '--checkpoint-interval', '3600',
            '--native-library', str(moved / record['native_file']),
            '--native-table-directory', control.native_table_directory]
    process = subprocess.run([sys.executable, '-m', 'sjtu_tpmshx.cli', *args],
                             capture_output=True, text=True, timeout=120)
    qualified = expected.run_status['converged'] and all(
        expected_metrics.metrics[name].status == 'available'
        for name in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B'))
    assert process.returncode == (0 if qualified else 2), process.stdout + process.stderr
    same_result(load_result(target / 'results.h5'), expected,
                load_metrics(target / 'metrics.json'), expected_metrics)
    assert {name: (moved / name).read_bytes() for name in before} == before
    retained = Path(json.loads((target / 'run.json').read_text())['native_source'])
    assert retained == moved / record['native_file']
