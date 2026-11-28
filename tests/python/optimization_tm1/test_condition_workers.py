"""Spawned condition workers keep callbacks, archives and failures separate."""
from dataclasses import replace
from functools import partial
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from time import monotonic, sleep

import numpy as np
import pytest

from tm1.run_control.cancellation import CancelledError
from tm1.run_control.module_ports import RunControl
from tm1.file_io.result_io import load_result
from tm1.applications.optimization import multi_condition as batch
from tests.python.optimization_tm1.test_multi_condition_batch import _baseline, _conditions, _native


def _analytic_worker(index, case_file, directory, library, threads, checkpoint_file=None,
                     *, crash_delay_s=None):
    from tm1.applications.execution import recovery

    def solve(case, control, *, checkpoint, checkpoint_due, resume_state):
        label = case.case_id.rsplit(':', 1)[-1]
        step = 0 if resume_state is None else int(resume_state['step'][0])
        if checkpoint_due():
            checkpoint({'build': 'analytic-worker', 'state.phase': np.array([6], dtype=np.uint64),
                        'step': np.array([step+1], dtype=np.uint64)})
        started = Path(directory).parent / f'started-{index}'
        started.write_text(str(os.getpid()))
        first_condition = json.loads((started.parent / 'batch-input.json').read_text())[0]['condition_id']
        if index < 2 and resume_state is None:
            deadline = monotonic()+15.
            while len(list(started.parent.glob('started-*'))) < 2:
                control.check_cancelled()
                # The crash probe bounds both workers with one process-tree timeout.
                if crash_delay_s is None and monotonic() > deadline:
                    raise TimeoutError('The second test worker did not start.')
                sleep(.01)
            if label == 'crash':
                (started.parent / 'both-workers-ready').write_text(str(monotonic()))
        control.iteration(label)
        control.outer_iteration(1, 2)
        control.residual('A', 1, .01)
        control.report_progress(40)
        if label == 'bad':
            error = ValueError('injected worker solve failure')
            error.add_note('retained worker diagnostic detail')
            raise error
        if label == 'crash':
            sleep(crash_delay_s)
            # Manager-backed cancellation must not expose a cross-process semaphore lock.
            assert not hasattr(batch._batch_cancel, '_cond')
            (started.parent / 'before-os-exit').write_text(str(monotonic()))
            os._exit(17)
        if crash_delay_s is not None and index < 2:
            # Keep this slot occupied until the parent detects the broken pool.
            batch._batch_cancel.wait()
            control.check_cancelled()
        if first_condition == 'pause' and index < 2 and resume_state is None:
            deadline = monotonic()+10.
            while monotonic() < deadline:
                control.check_cancelled()
                if checkpoint_due():
                    checkpoint({'build': 'analytic-worker', 'state.phase': np.array([6], dtype=np.uint64),
                                'step': np.array([step+2], dtype=np.uint64)})
                sleep(.01)
            raise TimeoutError('The parent did not pause the test worker.')
        waits_for_cancel = label == 'stop' or (label == 'mid' and first_condition == 'stop')
        if waits_for_cancel and resume_state is None:
            # Keep a finite wait bound so an uncancelled peer exits instead of hanging.
            deadline = monotonic() + 25.
            while monotonic() < deadline:
                control.check_cancelled()
                sleep(.01)
            raise TimeoutError('The parent did not cancel the test worker.')
        if index == 0:
            sleep(.2)
        control.check_cancelled()
        control.report_progress(100)
        field = _native(case)
        return replace(field, metadata={**field.metadata,
            'test_worker_pid': os.getpid(), 'test_cpu_threads': control.cpu_threads,
            'test_resumed_step': step})

    recovery.run_case = solve
    return batch._run_native_condition(index, case_file, directory, library, threads, checkpoint_file)


def _control(tmp_path, **kwargs):
    library = tmp_path / 'analytic-library.dylib'
    library.write_bytes(b'non-executable test data')
    return RunControl(backend='cpp', native_library=str(library), cpu_threads=4, **kwargs)


@pytest.mark.parametrize('available_cpus', [2, 3, 8])
@pytest.mark.parametrize('failed_member', [False, True])
def test_process_batch_keeps_order_resources_and_parent_callbacks(
        tmp_path, monkeypatch, failed_member, available_cpus):
    monkeypatch.setattr(os, 'cpu_count', lambda: available_cpus)
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    if failed_member:
        conditions[1] = ('bad', *conditions[1][1:])
    baseline = _baseline(conditions)
    callbacks, progress = [], []
    def observe(*args):
        callbacks.append((os.getpid(), args))
    control = _control(tmp_path, progress=progress.append, iteration=observe,
                       outer_iteration=observe, residual=observe)
    root = tmp_path / 'parallel'
    result = batch.evaluate_condition_batch(conditions, output_dir=root,
        baseline=baseline, control=control, workers=2)
    assert result['status'] == ('failed' if failed_member else 'completed')
    budget = min(4, available_cpus)
    threads = budget // 2
    assert result['workers'] == 2 and result['native_cpu_budget'] == budget
    assert [row['condition_id'] for row in result['conditions']] == [row[0] for row in conditions]
    expected = ['low', 'high'] if failed_member else ['low', 'mid', 'high']
    assert [row[0] for row in result['results']] == expected
    assert progress == sorted(progress) and progress[-1] == 100
    assert callbacks and all(pid == os.getpid() for pid, _ in callbacks)
    assert len({row['worker_pid'] for row in result['conditions']}) == 2
    for row in result['conditions']:
        assert row['cpu_threads'] == threads and row['worker_pid'] != os.getpid()
        assert (root / row['checkpoint_file']).is_file()
        if row['status'] == 'completed':
            field = load_result(root / row['result_file'])
            assert field.metadata['test_worker_pid'] == row['worker_pid']
            assert field.metadata['test_cpu_threads'] == threads
    if failed_member:
        assert result['objectives'] is None
        assert 'injected worker solve failure' in result['conditions'][1]['reason']
        assert 'retained worker diagnostic detail' in result['conditions'][1]['reason']
    else:
        assert result['objectives'] == pytest.approx(dict(heat_gain_percent=0., pressure_ratio=1.))


def test_process_cancel_keeps_checkpoint_and_unrun_members(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('stop', *conditions[0][1:])
    cancelled = []
    def iteration(message):
        if message == 'stop':
            cancelled.append(True)
    root = tmp_path / 'cancelled'
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=root, workers=2,
            control=_control(tmp_path, iteration=iteration, cancel_check=lambda: bool(cancelled)))
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == 'cancelled' and record['objectives'] is None
    assert record['conditions'][0]['status'] == 'cancelled'
    assert (root / record['conditions'][0]['checkpoint_file']).is_file()
    assert record['conditions'][2]['status'] == 'not_run'
    assert all(row['status'] not in ('running', 'computed') for row in record['conditions'])


@pytest.mark.parametrize('cancel_after_pause', [False, True])
def test_process_pause_drains_workers_and_cancel_takes_precedence(tmp_path, monkeypatch, cancel_after_pause):
    from multiprocessing import active_children
    from tm1.run_control.paused_run import PausedRun
    previous_children = set(active_children())
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('pause', *conditions[0][1:])
    pause_requested, pause_seen = [], []
    def iteration(message):
        if message == 'pause':
            pause_requested.append(True)
    def pause_check():
        if pause_requested:
            pause_seen.append(True)
        return bool(pause_requested)
    root = tmp_path / 'paused'
    with pytest.raises(CancelledError if cancel_after_pause else PausedRun):
        batch.evaluate_compact_condition_batch(conditions, output_dir=root, workers=2,
            pause_check=pause_check, control=_control(tmp_path, iteration=iteration,
                cancel_check=lambda: cancel_after_pause and bool(pause_seen)))
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == ('cancelled' if cancel_after_pause else 'paused')
    assert record['conditions'][2]['status'] == 'not_run'
    assert all(row['status'] not in ('running', 'computed') for row in record['conditions'])
    assert (root / record['conditions'][0]['checkpoint_file']).is_file()
    assert set(active_children()) <= previous_children
    resumed = batch.resume_condition_batch(root / 'batch.json', output_dir=tmp_path / 'continued',
        workers=2, control=_control(tmp_path))
    assert resumed['status'] == 'completed' and len(resumed['results']) == 3
    assert resumed['results'][0][1].metadata['test_resumed_step'] >= 1


@pytest.mark.parametrize('whole_search', [False, True])
def test_cancel_after_final_paused_worker_is_published(tmp_path, monkeypatch, whole_search):
    from multiprocessing import active_children
    from tm1.applications.optimization import multi_condition_optimizer as search
    previous_children = set(active_children())
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('pause', *conditions[0][1:])
    pause, cancel = [], []
    def iteration(message):
        if message == 'pause':
            pause.append(True)
    def update(state):
        rows = state['conditions'] if whole_search else state
        if sum(row['status'] == 'paused' for row in rows) == 2:
            cancel.append(True)
    root = tmp_path / 'cancelled'
    options = dict(output_dir=root, workers=2, on_update=update,
        pause_check=lambda: bool(pause), control=_control(tmp_path, iteration=iteration,
            cancel_check=lambda: bool(cancel)))
    with pytest.raises(CancelledError):
        if whole_search:
            search.run_multi_condition_optimization(conditions, method='sobol',
                n_init=1, n_iter=0, **options)
        else:
            batch.evaluate_compact_condition_batch(conditions, **options)
    assert cancel
    batch_root = root / 'baseline' if whole_search else root
    assert json.loads((batch_root / 'batch.json').read_text())['status'] == 'cancelled'
    if whole_search:
        assert json.loads((root / 'optimization.json').read_text())['status'] == 'cancelled'
    assert set(active_children()) <= previous_children


@pytest.mark.parametrize('workers', [0, -1, True, 1.5])
def test_invalid_worker_count_creates_no_archive(tmp_path, workers):
    root = tmp_path / 'invalid'
    with pytest.raises(ValueError, match='workers'):
        batch.evaluate_condition_batch(_conditions(1), output_dir=root, workers=workers)
    assert not root.exists()





def test_batch_resume_reuses_complete_members_and_actual_saved_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions[0] = ('stop', *conditions[0][1:])
    cancelled = []
    def iteration(message):
        if message == 'stop':
            cancelled.append(True)
    original = tmp_path / 'source'
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=original, workers=2,
            control=_control(tmp_path, iteration=iteration, cancel_check=lambda: bool(cancelled)))
    moved = original.rename(tmp_path / 'moved')
    previous = json.loads((moved / 'batch.json').read_text())
    before = {p.relative_to(moved): p.read_bytes() for p in moved.rglob('*') if p.is_file()}
    target = tmp_path / 'resumed'
    result = batch.resume_condition_batch(moved / 'batch.json', output_dir=target, workers=2,
                                          control=_control(tmp_path))
    assert result['status'] == 'completed' and len(result['results']) == 3
    assert [item[0] for item in result['results']] == ['stop', 'mid', 'high']
    assert result['results'][0][1].metadata['test_resumed_step'] == 1
    for old, row, (_, field, _) in zip(previous['conditions'], result['conditions'], result['results']):
        assert row['case_id'] == old['case_id'] == field.case_id
        if old['status'] == 'completed':
            assert row['reused_from'] == str(moved / old['directory'])
            assert field.result_id == load_result(moved / old['result_file']).result_id
    assert {p.relative_to(moved): p.read_bytes() for p in moved.rglob('*') if p.is_file()} == before
    assert result['resumed_from'] == str(moved)


def test_completed_batch_replay_retains_objectives_without_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions(2)
    source = tmp_path / 'complete'
    original = batch.evaluate_condition_batch(conditions, output_dir=source, workers=2,
        baseline=_baseline(conditions), control=_control(tmp_path))
    monkeypatch.setattr(batch, '_run_native_condition', lambda *a: pytest.fail('completed member recomputed'))
    result = batch.resume_condition_batch(source / 'batch.json', output_dir=tmp_path/'copied', workers=2, control=_control(tmp_path))
    assert result['status'] == 'completed' and result['objectives'] == original['objectives']
    assert [item[1].result_id for item in result['results']] == [item[1].result_id for item in original['results']]


def _delay_second_worker(patch, root):
    """Register the second worker while the pool manager watches only the first."""
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import connection
    from threading import Event

    spawn = ProcessPoolExecutor._spawn_process
    wait = connection.wait
    wake_sent, watching_first = Event(), Event()

    def observe_wait(handles, timeout=None):
        if timeout is None and len(handles) == 3:
            # Two pipes and the first worker's sentinel belong to this wait.
            wake_sent.wait()
            # On Windows this check can read the empty wake message.
            ready = wait(handles, 0)
            if ready:
                return ready
            watching_first.set()
        return wait(handles, timeout)

    def start_worker(pool):
        if pool._processes:
            # The first worker must own the peer condition before the second starts.
            while not (root / 'started-0').is_file():
                sleep(.01)
            with pytest.MonkeyPatch.context() as wait_patch:
                wait_patch.setattr(connection, 'wait', observe_wait)
                pool._executor_manager_thread_wakeup.wakeup()
                wake_sent.set()
                watching_first.wait()
        spawn(pool)

    patch.setattr(ProcessPoolExecutor, '_spawn_process', start_worker)


def _worker_exit_conditions(crash_index):
    conditions = _conditions()
    conditions[crash_index] = ('crash', *conditions[crash_index][1:])
    return conditions


def _run_worker_exit_probe(work_dir, crash_index, crash_delay_s):
    from concurrent.futures.process import BrokenProcessPool
    from multiprocessing import active_children

    work_path = Path(work_dir)
    previous_children = set(active_children())
    root = work_path / 'worker-exit'
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(batch, '_run_native_condition', partial(_analytic_worker, crash_delay_s=crash_delay_s))
        # In CPython 3.12.0 the manager takes the submit lock to clear a wake.
        if crash_index == 1 and sys.version_info >= (3, 12, 1):
            _delay_second_worker(patch, root)
        try:
            batch.evaluate_condition_batch(
                _worker_exit_conditions(crash_index), output_dir=root, workers=2, control=_control(work_path))
        except BrokenProcessPool:
            (root / 'after-broken-pool').write_text(str(monotonic()))
        else:
            raise AssertionError('Expected BrokenProcessPool when worker exits')
        remaining = set(active_children()) - previous_children
        if remaining:
            raise AssertionError(f'Child processes stayed active: {remaining!r}')


def _worker_exit_diagnostics(root, started):
    elapsed = {}
    for phase in ('both-workers-ready', 'before-os-exit', 'after-broken-pool'):
        try:
            elapsed[phase] = round(float((root / phase).read_text()) - started, 3)
        except (OSError, ValueError):
            elapsed[phase] = None
    try:
        status = json.loads((root / 'batch.json').read_text())['status']
    except (OSError, ValueError, KeyError, TypeError):
        status = None
    return f'phase_elapsed_s={elapsed}, saved_batch_status={status!r}'


def _stop_windows_probe_tree(probe_pid):
    """Bound the wait after taskkill receives a kill request."""
    try:
        helper = subprocess.Popen(['taskkill', '/F', '/T', '/PID', str(probe_pid)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        return f' Windows taskkill could not start ({error}).'
    try:
        helper.wait(timeout=5)
        return ''
    except subprocess.TimeoutExpired as error:
        note = f' Windows taskkill PID {helper.pid} timed out after {error.timeout} s.'
    except OSError as error:
        note = f' Windows taskkill PID {helper.pid} wait failed ({error}).'
    try:
        helper.kill()
    except OSError as error:
        note += f' Its kill request failed ({error}).'
    try:
        helper.wait(timeout=5)
    except subprocess.TimeoutExpired:
        note += f' Windows taskkill PID {helper.pid} did not exit after the kill request.'
    except OSError as error:
        note += f' Could not confirm its exit ({error}).'
    return note


def _fail_worker_exit_timeout(proc, root, probe_started, crash_delay_s, *, windows):
    returncode_before_kill = proc.poll()
    diagnostics = _worker_exit_diagnostics(root, probe_started)
    cleanup_note = ''
    pids = []
    if root.is_dir():
        for marker in sorted(root.glob('started-*')):
            try:
                pid = int(marker.read_text().strip())
            except (OSError, ValueError):
                continue
            pids.append((marker.name, pid))
    if windows:
        cleanup_note = _stop_windows_probe_tree(proc.pid)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    for _, pid in pids:
        try:
            os.kill(pid, signal.SIGKILL if hasattr(signal, 'SIGKILL') else signal.SIGTERM)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        # Windows reader threads close their streams when the last writer exits.
        if not windows:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cleanup_note += f' Probe PID {proc.pid} did not stop after the kill request.'
        stdout, stderr = '<pipe stayed open after process-tree kill>', ''
    pytest.fail(
        f'worker exit probe timed out after 45 s (crash_delay_s={crash_delay_s}, '
        f'probe_pid={proc.pid}, started_pids={pids}, returncode_before_kill={returncode_before_kill}, '
        f'{diagnostics}).{cleanup_note}\nstdout:\n{stdout}\nstderr:\n{stderr}')


def test_windows_probe_reports_timeout_while_pipe_writer_is_open(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import Mock

    read_fd, write_fd = os.pipe()
    pipe = os.fdopen(read_fd, 'rb')
    reading = Event()

    def read_to_eof():
        with pipe:
            reading.set()
            return pipe.read()

    probe_stdout = Mock(wraps=pipe)
    probe_stdout.close.side_effect = AssertionError('Cleanup tried to close the reader-owned pipe.')
    probe = Mock(pid=700, stdout=probe_stdout, stderr=None)
    probe.poll.return_value = 0
    probe.communicate.side_effect = subprocess.TimeoutExpired('probe', 5)
    monkeypatch.setattr(subprocess, 'Popen', Mock())
    # Release the writer before joining its reader, including when the check fails.
    with ThreadPoolExecutor(max_workers=1) as pool, os.fdopen(write_fd, 'wb'):
        reader = pool.submit(read_to_eof)
        reading.wait()
        with pytest.raises(pytest.fail.Exception, match='pipe stayed open') as caught:
            _fail_worker_exit_timeout(probe, tmp_path, monotonic(), 0., windows=True)
        assert 'returncode_before_kill=0' in str(caught.value)
        assert not reader.done() and not pipe.closed
    assert reader.result() == b'' and pipe.closed
    probe.wait.assert_called_once_with(timeout=5)


@pytest.mark.parametrize('start_fails', [False, True], ids=['helper-stays-alive', 'helper-start-fails'])
def test_windows_probe_cleanup_signals_each_pid_after_taskkill_failure(tmp_path, monkeypatch, start_fails):
    from unittest.mock import Mock, call

    for index, pid in enumerate((701, 702)):
        (tmp_path / f'started-{index}').write_text(str(pid))
    probe = Mock(pid=700)
    probe.poll.return_value = None
    probe.communicate.return_value = ('', '')
    helper = Mock(pid=703)
    helper.wait.side_effect = subprocess.TimeoutExpired('taskkill', 5)
    launch = Mock(side_effect=FileNotFoundError('taskkill') if start_fails else None, return_value=helper)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    signal_pid = Mock()
    monkeypatch.setattr(os, 'kill', signal_pid)

    with pytest.raises(pytest.fail.Exception) as caught:
        _fail_worker_exit_timeout(probe, tmp_path, monotonic(), 10.5, windows=True)
    message = str(caught.value)
    assert 'probe_pid=700' in message and "started_pids=[('started-0', 701), ('started-1', 702)]" in message
    launch.assert_called_once_with(['taskkill', '/F', '/T', '/PID', '700'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert [item.args[0] for item in signal_pid.call_args_list] == [701, 702]
    probe.kill.assert_called_once_with()
    if start_fails:
        assert 'could not start' in message
    else:
        assert 'taskkill PID 703' in message and 'did not exit' in message
        assert helper.wait.call_args_list == [call(timeout=5), call(timeout=5)]
        helper.kill.assert_called_once_with()


@pytest.mark.parametrize('crash_index,crash_delay_s', [(0, 0.), (1, 10.5)], ids=['0.0', '10.5'])
def test_worker_exit_keeps_last_complete_checkpoint(tmp_path, monkeypatch, crash_index, crash_delay_s):
    from tm1.applications.execution.recovery import read_run_checkpoint

    root = tmp_path / 'worker-exit'
    repo_root = Path(__file__).resolve().parents[3]
    # Run the crash pool in a child process so a timeout fails cleanly without killing an xdist worker.
    popen_kwargs = dict(
        cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if os.name != 'nt':
        popen_kwargs['start_new_session'] = True
    probe_started = monotonic()
    proc = subprocess.Popen(
        [sys.executable, '-c',
         'import sys; '
         'from tests.python.optimization_tm1.test_condition_workers import _run_worker_exit_probe; '
         '_run_worker_exit_probe(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]))',
         str(tmp_path), str(crash_index), str(crash_delay_s)],
        **popen_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        _fail_worker_exit_timeout(proc, root, probe_started, crash_delay_s, windows=os.name == 'nt')
    assert proc.returncode == 0, (
        f'probe exited with {proc.returncode}, {_worker_exit_diagnostics(root, probe_started)}'
        f'\nstdout:\n{stdout}\nstderr:\n{stderr}')
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == 'failed' and record['objectives'] is None
    statuses = [row['status'] for row in record['conditions']]
    assert statuses == ['failed', 'failed', 'not_run'], [row['reason'] for row in record['conditions']]
    checkpoint = root / record['conditions'][crash_index]['checkpoint_file']
    assert checkpoint.is_file()
    saved, _, _ = read_run_checkpoint(checkpoint)
    assert int(saved.native_state['step'][0]) == 1
    assert not (root / 'condition_003').exists()
    started = {path.name: path.read_text() for path in root.glob('started-*')}
    assert set(started) == {'started-0', 'started-1'}
    # The in-place continuation keeps both failed members and runs only the member that did not start.
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    result = batch.evaluate_compact_condition_batch(_worker_exit_conditions(crash_index),
        output_dir=root, workers=2, control=_control(tmp_path), resume_saved=True)
    rows = result['conditions']
    assert [row['status'] for row in rows] == ['failed', 'failed', 'completed']
    assert [row['recovery_mode'] for row in rows] == ['failed_copy', 'failed_copy', 'new']
    assert [row['reason'] for row in rows[:2]] == [row['reason'] for row in record['conditions'][:2]]
    assert {path.name: path.read_text() for path in root.glob('started-*') if path.name != 'started-2'} == started
    assert rows[2]['worker_pid'] == int((root / 'started-2').read_text())
    assert result['status'] == 'failed' and result['objectives'] is None
    assert list(result['summaries']) == ['high']


def test_parent_callback_error_is_retained_after_workers_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    error = ValueError('parent callback failed')
    def iteration(message):
        raise error
    root = tmp_path / 'callback-error'
    with pytest.raises(ValueError) as caught:
        batch.evaluate_condition_batch(_conditions(), output_dir=root, workers=2,
                                       control=_control(tmp_path, iteration=iteration))
    assert caught.value is error
    record = json.loads((root / 'batch.json').read_text())
    assert record['status'] == 'failed' and 'parent callback failed' in record['reason']
    assert record['conditions'][2]['status'] == 'not_run'
    assert all(row['status'] not in ('running', 'computed') for row in record['conditions'])


@pytest.mark.parametrize('damage,reason', [
    ('membership', 'membership differ'), ('case_id', 'identity differ'),
    ('flow', 'mass flow A differs'), ('config', 'configuration differs'),
    ('baseline', 'baseline must retain the original uniform design'),
])
def test_batch_resume_rejects_changed_saved_inputs(tmp_path, monkeypatch, damage, reason):
    from tm1.file_io.result_io import save_result
    from tm1.applications.execution import recovery

    monkeypatch.setattr(recovery, 'run_case', lambda case, control, **kw: _native(case))
    conditions = _conditions(1)
    source = tmp_path / 'complete'
    batch.evaluate_condition_batch(conditions, output_dir=source,
        baseline=_baseline(conditions), control=_control(tmp_path))
    record_path = source / 'batch.json'
    record = json.loads(record_path.read_text())
    input_path = source / 'batch-input.json'
    inputs = json.loads(input_path.read_text())
    if damage == 'membership':
        inputs[0]['condition_id'] = 'changed'
    elif damage == 'case_id':
        record['conditions'][0]['case_id'] = 'changed'
    elif damage == 'flow':
        inputs[0]['mass_flow_A_kg_s'] *= 1.1
    elif damage == 'config':
        inputs[0]['config']['fluid_A']['T_in_K'] += 1.
    else:
        file = source / record['baseline_files'][0]['result_file']
        field = load_result(file)
        save_result(replace(field, metadata={**field.metadata, 'design_mode': 'zones'}), file)
    record_path.write_text(json.dumps(record))
    input_path.write_text(json.dumps(inputs))
    monkeypatch.setattr(recovery, 'run_case', lambda *a, **kw: pytest.fail('invalid archive recomputed'))
    destination = tmp_path / 'rejected'
    with pytest.raises(ValueError, match=reason):
        batch.resume_condition_batch(record_path, output_dir=destination, control=_control(tmp_path))
    if (destination / 'batch.json').is_file():
        saved = json.loads((destination / 'batch.json').read_text())
        assert saved['status'] == 'failed' and saved['objectives'] is None


def test_process_batch_resolves_relative_output_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions(2)
    control = _control(tmp_path)
    monkeypatch.chdir(tmp_path)
    report = batch.evaluate_condition_batch(conditions, output_dir='relative-output',
                                           control=control, workers=2)
    assert report['status'] == 'completed'
    assert all((tmp_path / 'relative-output' / row['result_file']).is_file()
               for row in report['conditions'])



def test_pre_cancelled_batch_keeps_inputs_without_loading_missing_library(tmp_path, monkeypatch):
    from tm1.applications.execution import recovery

    conditions = _conditions(1)
    source = tmp_path / 'pre-cancelled'
    control = RunControl(backend='cpp', native_library=str(tmp_path / 'missing-library'), cancel_check=lambda: True)
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=source, baseline=_baseline(conditions), control=control)
    record = json.loads((source / 'batch.json').read_text())
    assert record['status'] == 'cancelled' and record['conditions'][0]['status'] == 'not_run'
    assert (source / 'batch-input.json').is_file()
    assert record['baseline_files'] and 'native_file' not in record
    monkeypatch.setattr(recovery, 'run_case', lambda case, control, **kw: _native(case))
    resumed = batch.resume_condition_batch(source / 'batch.json', output_dir=tmp_path / 'resumed', control=_control(tmp_path))
    assert resumed['status'] == 'completed'
    assert resumed['objectives'] == pytest.approx(dict(heat_gain_percent=0., pressure_ratio=1.))


@pytest.mark.parametrize('backend,available,limit,members,workers,expected', [
    ('cpp', 8, None, 5, None, 4),
    ('cpp', 8, 4, 5, None, 2),
    ('cpp', 3, None, 5, None, 1),
    ('cpp', 1, None, 5, None, 1),
    ('cpp', 8, None, 1, None, 1),
    ('cpp', 8, 4, 5, 4, 4),
    ('cpp', 8, 1, 5, 4, 1),
    ('cpp', 8, 8, 5, 1, 1),
])
def test_default_worker_count_is_saved_before_cancellation(
        tmp_path, monkeypatch, backend, available, limit, members, workers, expected):
    monkeypatch.setattr(os, 'cpu_count', lambda: available)
    template = _conditions(1)[0]
    conditions = [(f'condition-{index}', *template[1:]) for index in range(members)]
    control = RunControl(backend=backend, cpu_threads=limit, cancel_check=lambda: True)
    root = tmp_path / 'cancelled'
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=root, control=control, workers=workers)
    record = json.loads((root / 'batch.json').read_text())
    assert record['workers'] == expected
    assert record['native_cpu_budget'] == min(limit or 8, available)
    assert record['status'] == 'cancelled'
    assert len(record['conditions']) == members
    assert all(row['status'] == 'not_run' for row in record['conditions'])


def test_default_process_batch_and_recovery_keep_complete_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'cpu_count', lambda: 8)
    monkeypatch.setattr(batch, '_run_native_condition', _analytic_worker)
    conditions = _conditions()
    conditions.append(('extra', *conditions[-1][1:]))
    control = replace(_control(tmp_path), cpu_threads=8)
    source = tmp_path / 'automatic'
    report = batch.evaluate_condition_batch(conditions, output_dir=source,
        baseline=_baseline(conditions), control=control)
    assert report['status'] == 'completed' and report['workers'] == 4
    assert report['native_cpu_budget'] == 8
    assert [name for name, _, _ in report['results']] == [row[0] for row in conditions]
    for row, (_, field, _) in zip(report['conditions'], report['results']):
        assert row['worker_pid'] != os.getpid() and row['cpu_threads'] == 2
        assert field.metadata['test_cpu_threads'] == 2
        assert (source / row['result_file']).is_file()
        assert (source / row['checkpoint_file']).is_file()
    resumed = batch.resume_condition_batch(source / 'batch.json',
        output_dir=tmp_path / 'recovered', control=replace(control, cpu_threads=4))
    assert resumed['status'] == 'completed' and resumed['workers'] == 2
    assert resumed['objectives'] == report['objectives']
    assert all(row['recovery_mode'] == 'completed_copy' for row in resumed['conditions'])
