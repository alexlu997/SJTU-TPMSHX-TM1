"""Saved runs preserve inputs, completed outputs and original failures."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.solver_checkpoint_io import load_solver_checkpoint
from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case
from sjtu_tpmshx.workflows import recovery


@pytest.fixture
def stages(tmp_path, monkeypatch):
    config = ComputeConfig()
    case = replace(sample_case(), config_snapshot=config.to_dict())
    result = FieldResult('result', case.case_id, 'synthetic', grid=case.grid,
        fields={'Ta': np.full((2, 2), 300.)},
        field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw')},
        run_status={'execution': 'completed', 'converged': True}, metadata={'diagnostics': {}})
    metrics = PerformanceResult('metrics', result.result_id, {
        key: MetricValue(1., MetricSpec(kind, unit)) for key, kind, unit in
        (('Q', 'Q', 'W/m'), ('dP_A', 'dP', 'Pa'), ('dP_B', 'dP', 'Pa'),
         ('T_out_A', 'T_out', 'K'), ('T_out_B', 'T_out', 'K'))})
    library = tmp_path / 'library.dylib'
    library.write_bytes(b'non-executable test data')
    control = RunControl(backend='cpp', native_library=str(library))
    monkeypatch.setattr(recovery, 'prepare_case', lambda cfg, case_id: case)
    monkeypatch.setattr('sjtu_tpmshx.postprocess.api.evaluate', lambda field: metrics)
    state = {'build': 'test-build', 'state.phase': np.array([1], dtype=np.uint64),
             'position': np.array([1], dtype=np.uint64)}
    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        assert checkpoint_due()
        checkpoint(state)
        return result
    monkeypatch.setattr(recovery, 'run_case', solve)
    return config, case, result, metrics, control, state


def start(stages, directory, **kwargs):
    config, case, _, _, control, _ = stages
    return recovery.compute_run(config, directory, case_id=case.case_id, control=control,
                                checkpoint_interval_s=30., **kwargs)


def test_complete_run_keeps_input_runtime_and_metric_identity(tmp_path, stages):
    directory = tmp_path / 'run'
    case, result, metrics = start(stages, directory)
    record = json.loads((directory / 'run.json').read_text())
    assert record['state'] == 'completed'
    assert record['checkpoint_count'] == 1
    assert record['checkpoint_build'] == 'test-build'
    assert load_case(directory / 'case.yaml').case_id == case.case_id
    assert load_result(directory / 'results.h5').result_id == result.result_id
    assert load_metrics(directory / 'metrics.json').source_result_id == metrics.source_result_id == result.result_id
    assert (directory / record['native_file']).read_bytes() == Path(stages[4].native_library).read_bytes()
    saved, restored, _ = recovery.read_run_checkpoint(directory / 'checkpoint.h5')
    assert restored.case_id == saved.case_id == case.case_id
    assert result.metadata['recovery']['directory'] == str(directory)


def test_pause_stops_before_postprocessing_and_result_publication(tmp_path, stages, monkeypatch):
    monkeypatch.setattr('sjtu_tpmshx.postprocess.api.evaluate',
                        lambda result: pytest.fail('paused state reached postprocessing'))
    directory = tmp_path / 'paused'
    with pytest.raises(PausedRun) as error:
        start(stages, directory, pause_check=lambda: True)
    assert error.value.checkpoint_file == str(directory / 'checkpoint.h5')
    assert not (directory / 'results.h5').exists()
    assert not (directory / 'metrics.json').exists()
    assert json.loads((directory / 'run.json').read_text())['state'] == 'paused'
    assert load_solver_checkpoint(error.value.checkpoint_file).native_state['position'][0] == 1


def test_resume_uses_relocated_prepared_input_and_keeps_source(tmp_path, stages, monkeypatch):
    original = tmp_path / 'original'
    with pytest.raises(PausedRun):
        start(stages, original, pause_check=lambda: True, gui_provenance={'preset_source': 'saved'})
    moved = original.rename(tmp_path / 'moved')
    before = {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()}
    monkeypatch.setattr(recovery, 'prepare_case', lambda *a, **k: pytest.fail('resume repeated preparation'))
    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        assert case.case_id == stages[1].case_id
        assert resume_state['position'][0] == 1
        assert checkpoint_due()
        checkpoint({**stages[5], 'position': np.array([2], dtype=np.uint64)})
        return stages[2]
    monkeypatch.setattr(recovery, 'run_case', solve)
    target = tmp_path / 'resumed'
    _, result, _ = recovery.resume_run(moved / 'checkpoint.h5', target,
        control=stages[4], checkpoint_interval_s=30.)
    assert {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()} == before
    assert load_solver_checkpoint(target / 'checkpoint.h5').native_state['position'][0] == 2
    assert result.metadata['recovery']['resumed_from'] == str(moved / 'checkpoint.h5')
    assert json.loads((target / 'run.json').read_text())['gui_provenance'] == {'preset_source': 'saved'}


def test_time_gate_and_pause_request_do_not_export_unneeded_snapshots(tmp_path, stages, monkeypatch):
    clock, pause = [100.], [False]
    monkeypatch.setattr(recovery, 'perf_counter', lambda: clock[0])
    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        assert checkpoint_due()
        checkpoint(stages[5])
        clock[0] += 29.
        assert not checkpoint_due()
        clock[0] += 1.
        assert checkpoint_due()
        checkpoint(stages[5])
        assert not checkpoint_due()
        pause[0] = True
        assert checkpoint_due()
        checkpoint(stages[5])
        pytest.fail('pause did not stop the run')
    monkeypatch.setattr(recovery, 'run_case', solve)
    directory = tmp_path / 'timed'
    with pytest.raises(PausedRun):
        start(stages, directory, pause_check=lambda: pause[0])
    assert json.loads((directory / 'run.json').read_text())['checkpoint_count'] == 3


def test_checkpoint_write_failure_keeps_last_complete_file(tmp_path, stages, monkeypatch):
    original_writer = recovery.save_solver_checkpoint
    previous, count = [], [0]
    error = OSError('disk is full')
    def write(saved, path):
        count[0] += 1
        if count[0] == 2:
            raise error
        original_writer(saved, path)
        previous.append(path.read_bytes())
    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        checkpoint(stages[5])
        checkpoint({**stages[5], 'position': np.array([2], dtype=np.uint64)})
    monkeypatch.setattr(recovery, 'save_solver_checkpoint', write)
    monkeypatch.setattr(recovery, 'run_case', solve)
    directory = tmp_path / 'failed'
    with pytest.raises(OSError) as caught:
        start(stages, directory)
    assert caught.value is error
    assert (directory / 'checkpoint.h5').read_bytes() == previous[0]
    assert json.loads((directory / 'run.json').read_text())['state'] == 'failed'
    assert not (directory / 'results.h5').exists()


@pytest.mark.parametrize('cancelled', [True, False])
def test_original_execution_error_survives_status_write_failure(tmp_path, stages, monkeypatch, cancelled):
    error = CancelledError('stop requested') if cancelled else ValueError('bad numerical state')
    write = recovery.write_text
    def publish(path, text):
        if json.loads(text)['state'] in ('failed', 'cancelled'):
            raise OSError('status storage failed')
        return write(path, text)
    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        checkpoint(stages[5])
        raise error
    monkeypatch.setattr(recovery, 'write_text', publish)
    monkeypatch.setattr(recovery, 'run_case', solve)
    directory = tmp_path / 'run'
    with pytest.raises(type(error)) as caught:
        start(stages, directory)
    assert caught.value is error
    assert any('status storage failed' in note for note in error.__notes__)
    assert (directory / 'checkpoint.h5').is_file()
    assert not (directory / 'results.h5').exists()


def test_new_attempt_cannot_replace_existing_outputs(tmp_path, stages):
    directory = tmp_path / 'accepted'
    directory.mkdir()
    marker = directory / 'results.h5'
    marker.write_bytes(b'previous accepted result')
    with pytest.raises(FileExistsError):
        start(stages, directory)
    assert marker.read_bytes() == b'previous accepted result'
    assert not (directory / 'run.json').exists()


@pytest.mark.parametrize('interval', [True, 0., -1., float('nan'), float('inf')])
def test_invalid_interval_writes_no_run_directory(tmp_path, stages, interval):
    directory = tmp_path / 'invalid'
    with pytest.raises(ValueError, match='interval'):
        recovery.compute_run(stages[0], directory, control=stages[4], checkpoint_interval_s=interval)
    assert not directory.exists()


@pytest.mark.parametrize('damage', ['format', 'case_id', 'case_file'])
def test_bad_run_identity_cannot_start_a_new_attempt(tmp_path, stages, damage):
    directory = tmp_path / 'source'
    with pytest.raises(PausedRun):
        start(stages, directory, pause_check=lambda: True)
    path = directory / 'run.json'
    record = json.loads(path.read_text())
    if damage == 'case_file':
        (directory / 'case.h5').unlink()
    else:
        record[damage] = 'wrong'
        path.write_text(json.dumps(record))
    target = tmp_path / 'resumed'
    with pytest.raises((ValueError, OSError)):
        recovery.resume_run(directory / 'checkpoint.h5', target,
                            control=stages[4], checkpoint_interval_s=30.)
    assert not target.exists()


@pytest.mark.parametrize('resume', [False, True])
def test_pre_cancelled_run_does_not_read_inputs_or_create_outputs(tmp_path, resume):
    control = RunControl(backend='cpp', native_library=str(tmp_path / 'missing.dylib'),
                         cancel_check=lambda: True)
    target = tmp_path / 'cancelled'
    call = recovery.resume_run if resume else recovery.compute_run
    source = tmp_path / 'missing/checkpoint.h5' if resume else ComputeConfig()
    with pytest.raises(CancelledError):
        call(source, target, control=control, checkpoint_interval_s=30.)
    assert not target.exists()


@pytest.mark.parametrize('change', ['same', 'new_build', 'moved'])
def test_repeated_runs_reuse_only_the_matching_available_runtime(tmp_path, stages, monkeypatch, change):
    libraries = []
    solve = recovery.run_case
    def capture(case, control, **kwargs):
        libraries.append(Path(control.native_library))
        return solve(case, control, **kwargs)
    monkeypatch.setattr(recovery, 'run_case', capture)
    first = tmp_path / 'first'
    start(stages, first)
    first_runtime = first / 'runtime' / Path(stages[4].native_library).name
    if change == 'new_build':
        Path(stages[4].native_library).write_bytes(b'new non-executable test build')
    elif change == 'moved':
        first.rename(tmp_path / 'moved')
    second = tmp_path / 'second'
    start(stages, second)
    second_runtime = second / 'runtime' / first_runtime.name
    assert second_runtime.read_bytes() == Path(stages[4].native_library).read_bytes()
    assert libraries == [first_runtime, first_runtime if change == 'same' else second_runtime]
    record = json.loads((second / 'run.json').read_text())
    assert record['execution_library'] == str(libraries[-1])
    assert record['native_file'] == second_runtime.relative_to(second).as_posix()
