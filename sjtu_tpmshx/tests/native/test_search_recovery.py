"""A new process continues a moved search from its actual native checkpoint."""
from dataclasses import replace
import json
import shutil
import subprocess
import sys
from threading import Event

import pytest

from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.optimization.multi_condition_optimizer import (
    run_multi_condition_optimization, resume_multi_condition_optimization)
from sjtu_tpmshx.tests.native.test_backend_condition_consumers import _conditions, native_3d
from sjtu_tpmshx.tests.native.test_run_recovery import same_result

native_path = native_3d.native_path


def test_search_restarts_process_reuses_complete_design_and_matches_uninterrupted(native_path, tmp_path):
    # Windows can remove shared runtime files after their execution process exits.
    script = """
from pathlib import Path
import sys
from sjtu_tpmshx.tests.native.test_search_recovery import _exercise_search_recovery
_exercise_search_recovery(Path(sys.argv[1]), Path(sys.argv[2]))
"""
    process = subprocess.run([sys.executable, '-c', script, str(native_path), str(tmp_path)],
        capture_output=True, text=True, timeout=300)
    assert process.returncode == 0, process.stdout + process.stderr
    shutil.rmtree(tmp_path / 'moved')
    shutil.rmtree(tmp_path / 'second-move')
    destination = tmp_path / 'resumed'
    actual = json.loads((destination / 'optimization.json').read_text())
    for entry in (actual['baseline'], *actual['history']):
        directory = destination / entry['directory']
        restored = json.loads((directory / 'batch.json').read_text())
        for row in restored['conditions']:
            assert load_result(directory / row['result_file']).case_id == row['case_id']


def _exercise_search_recovery(native_path, tmp_path):
    conditions = _conditions(2)
    control = replace(native_3d.control(native_path), cpu_threads=2)
    settings = dict(method='sobol', n_init=2, n_iter=1, seed=7, workers=1,
                    field_spec={'L_bounds': [6.8, 7.2], 't_bounds': [.55, .6]})
    uninterrupted = tmp_path / 'uninterrupted'
    expected = run_multi_condition_optimization(conditions, output_dir=uninterrupted,
        control=control, **settings)
    assert expected['status'] == 'completed' and expected['n_usable'] == 3
    pause, active = Event(), []
    def update(state):
        active[:] = [row['index'] for row in state['report']['history'] if row['status'] == 'running']
    def iteration(_):
        if active == [1]:
            pause.set()
    original = tmp_path / 'original'
    with pytest.raises(PausedRun):
        run_multi_condition_optimization(conditions, output_dir=original,
            control=replace(control, iteration=iteration), pause_check=pause.is_set, on_update=update, **settings)
    moved = original.rename(tmp_path / 'moved')
    saved = json.loads((moved / 'optimization.json').read_text())
    assert saved['history'][0]['status'] == 'completed' and saved['history'][1]['status'] == 'paused'
    batch = json.loads((moved / 'design_0001/batch.json').read_text())
    assert batch['conditions'][0]['status'] == 'paused'
    assert (moved / 'design_0001' / batch['conditions'][0]['checkpoint_file']).is_file()
    before = {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()}
    prepared_pause = Event()
    def pause_during_preparation(state):
        if (any(row['index'] == 1 and row['status'] == 'running' for row in state['report']['history'])
                and any(row['stage'] == 'save_case' for row in state['conditions'])):
            prepared_pause.set()
    intermediate = tmp_path / 'intermediate'
    with pytest.raises(PausedRun):
        resume_multi_condition_optimization(moved / 'optimization.json', output_dir=intermediate,
            control=control, workers=1, pause_check=prepared_pause.is_set, on_update=pause_during_preparation)
    second_source = intermediate.rename(tmp_path / 'second-move')
    second_before = {path.relative_to(second_source): path.read_bytes()
                     for path in second_source.rglob('*') if path.is_file()}
    destination = tmp_path / 'resumed'
    script = """
import sys
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.optimization.multi_condition_optimizer import resume_multi_condition_optimization
result = resume_multi_condition_optimization(sys.argv[1], output_dir=sys.argv[2], workers=1,
    control=RunControl(native_library=sys.argv[3], native_table_directory=sys.argv[4], cpu_threads=2))
assert result['status'] == 'completed' and result['n_usable'] == 3, result
assert 'PySide6' not in sys.modules
"""
    process = subprocess.run([sys.executable, '-c', script, str(second_source / 'optimization.json'),
        str(destination), str(native_path), str(control.native_table_directory)],
        capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stdout + process.stderr
    actual = json.loads((destination / 'optimization.json').read_text())
    assert actual['initial_designs'] == expected['initial_designs']
    assert actual['ref_point'] == expected['ref_point']
    assert [row['model_y'] for row in actual['history']] == [row['model_y'] for row in expected['history']]
    for entry in (actual['baseline'], *actual['history']):
        directory = entry['directory']
        restored = json.loads((destination / directory / 'batch.json').read_text())
        prior = json.loads((uninterrupted / directory / 'batch.json').read_text())
        for row, old in zip(restored['conditions'], prior['conditions']):
            same_result(load_result(destination / directory / row['result_file']),
                load_result(uninterrupted / directory / old['result_file']),
                load_metrics(destination / directory / row['metrics_file']),
                load_metrics(uninterrupted / directory / old['metrics_file']))
        if directory in ('baseline', 'design_0000'):
            assert all(row['recovery_mode'] == 'completed_copy' for row in restored['conditions'])
            for row in restored['conditions']:
                relative = directory + '/' + row['result_file']
                assert (destination / relative).samefile(moved / relative)
            source = json.loads((moved / directory / 'batch.json').read_text())
            assert [load_result(destination / directory / row['result_file']).result_id for row in restored['conditions']] == [
                load_result(moved / directory / row['result_file']).result_id for row in source['conditions']]
        if directory == 'design_0001':
            assert restored['conditions'][0]['recovery_mode'] == 'checkpoint'
    assert {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()} == before
    assert {path.relative_to(second_source): path.read_bytes()
            for path in second_source.rglob('*') if path.is_file()} == second_before
