"""Associate a native run with its input, checkpoints, runtime and results."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
from time import perf_counter
from uuid import uuid4

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.io.case_io import save_case
from sjtu_tpmshx.io.file_set import staged_files
from sjtu_tpmshx.io.metrics_io import save_metrics
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.solver_checkpoint_io import (
    load_checkpoint_case, load_solver_checkpoint, save_solver_checkpoint,
)
from sjtu_tpmshx.io.text_file import write_text
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from .compute import compute


# Reuse an identical retained library to keep native tables in one loaded image.
_runtime_files = {}


def read_run_checkpoint(path):
    """Read a project checkpoint and its local prepared input after relocation."""
    path = Path(path).resolve(strict=True)
    if path.name != 'checkpoint.h5':
        raise ValueError('select checkpoint.h5 from a saved run directory')
    record = json.loads((path.parent / 'run.json').read_text(encoding='utf-8'))
    if not isinstance(record, dict) or record.get('format') != 'native_run_v1':
        raise ValueError('unsupported saved run format')
    saved = load_solver_checkpoint(path)
    case = load_checkpoint_case(saved, case_file=path.parent / 'case.h5')
    if record.get('case_id') != case.case_id:
        raise ValueError('saved run and prepared-case identity differ')
    expected = f"full_{case.grid['dimension']}d_continuation_v1"
    if saved.state_format != expected:
        raise ValueError('saved run and checkpoint dimensions differ')
    return saved, case, record


def compute_run(config, directory, *, checkpoint_interval_s, case_id=None,
                control=RunControl(), progress_cb=None, pause_check=None, gui_provenance=None):
    """Start a native calculation in a new directory and save safe boundaries."""
    control.check_cancelled()
    return _execute(config, directory, checkpoint_interval_s=checkpoint_interval_s,
        case_id=case_id or str(uuid4()), control=control, progress_cb=progress_cb,
        pause_check=pause_check, gui_provenance=gui_provenance)


def compute_prepared_run(case, directory, *, checkpoint_interval_s,
                         control=RunControl(), progress_cb=None, pause_check=None, evaluate=None):
    """Save and solve the supplied prepared input without preparing it again."""
    control.check_cancelled()
    config = ComputeConfig.from_dict(mutable_data(case.config_snapshot))
    return _execute(config, directory, checkpoint_interval_s=checkpoint_interval_s,
        case_id=case.case_id, control=control, progress_cb=progress_cb,
        pause_check=pause_check, gui_provenance=None, saved_case=case, evaluate=evaluate)


def resume_run(checkpoint_file, directory, *, checkpoint_interval_s,
               control=RunControl(), progress_cb=None, pause_check=None, evaluate=None):
    """Continue the saved input in a new directory; retain the source run."""
    control.check_cancelled()
    saved, case, record = read_run_checkpoint(checkpoint_file)
    config = ComputeConfig.from_dict(mutable_data(case.config_snapshot))
    return _execute(config, directory, checkpoint_interval_s=checkpoint_interval_s,
        case_id=case.case_id, control=control, progress_cb=progress_cb,
        pause_check=pause_check, gui_provenance=record.get('gui_provenance'),
        saved_case=case, saved_state=saved.native_state,
        resumed_from=str(Path(checkpoint_file).resolve()), evaluate=evaluate)


def _execute(config, directory, *, checkpoint_interval_s, case_id, control, progress_cb,
             pause_check, gui_provenance, saved_case=None, saved_state=None, resumed_from=None, evaluate=None):
    if (isinstance(checkpoint_interval_s, bool) or not math.isfinite(checkpoint_interval_s)
            or checkpoint_interval_s <= 0.):
        raise ValueError('checkpoint interval must be finite and positive')
    from sjtu_tpmshx.domain.module_ports import resolve_control
    control = resolve_control(control)
    library = Path(control.native_library)
    if not library.is_absolute():
        raise ValueError('saved runs require an absolute native library path')
    library = library.resolve(strict=True)
    config.validate()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True)
    checkpoint_file = directory / 'checkpoint.h5'
    record = dict(format='native_run_v1', run_id=str(uuid4()), case_id=case_id,
        created_utc=datetime.now(timezone.utc).isoformat(), state='running',
        checkpoint_interval_s=checkpoint_interval_s, checkpoint_count=0,
        checkpoint_seconds=0., checkpoint_build=None, resumed_from=resumed_from,
        native_source=str(library), native_file='runtime/' + library.name,
        gui_provenance=gui_provenance, requested_cpu_threads=control.cpu_threads)

    def publish_status(state, **changes):
        record.update(state=state, updated_utc=datetime.now(timezone.utc).isoformat(), **changes)
        write_text(directory / 'run.json', json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + '\n')

    next_save = 0.
    completed_result = None

    def prepare(config, *, case_id):
        case = saved_case if saved_case is not None else prepare_case(config, case_id=case_id)
        if case.metadata.get('mode', 'full') != 'full':
            raise ValueError('saved runs require the full solver')
        save_case(case, directory / 'case.yaml')
        return case

    def due():
        return (pause_check is not None and pause_check()) or perf_counter() >= next_save

    def solve(case, solver_control):
        nonlocal completed_result
        def checkpoint(state):
            nonlocal next_save
            solver_control.check_cancelled()
            started = perf_counter()
            saved = SolverCheckpoint(str(directory / 'case.h5'), case.case_id, case.model_refs,
                state, f"full_{case.grid['dimension']}d_continuation_v1")
            save_solver_checkpoint(saved, checkpoint_file)
            record.update(checkpoint_count=record['checkpoint_count'] + 1,
                checkpoint_seconds=record['checkpoint_seconds'] + perf_counter() - started,
                checkpoint_build=state['build'], checkpoint_phase=int(state['state.phase'][0]))
            next_save = perf_counter() + checkpoint_interval_s
            publish_status('running')
            solver_control.check_cancelled()
            if pause_check is not None and pause_check():
                raise PausedRun(checkpoint_file)
        completed_result = run_case(case, solver_control, resume_state=saved_state,
                                    checkpoint=checkpoint, checkpoint_due=due)
        return completed_result

    try:
        publish_status('running')
        runtime = directory / 'runtime'
        runtime.mkdir()
        retained = runtime / library.name
        shutil.copy2(library, retained)
        retained_bytes = retained.read_bytes()
        if retained_bytes != library.read_bytes():
            raise OSError('native library changed while the run retained its runtime')
        runtime_file = _runtime_files.get(library)
        if (runtime_file is None or not runtime_file.is_file()
                or runtime_file.read_bytes() != retained_bytes):
            runtime_file = retained
            _runtime_files[library] = runtime_file
        del retained_bytes
        record['execution_library'] = str(runtime_file)
        runtime_control = replace(control, native_library=str(runtime_file))
        case, result, performance = compute(config, case_id=case_id, control=runtime_control,
            progress_cb=progress_cb, prepare=prepare, solve=solve, evaluate=evaluate)
        recovery = dict(directory=str(directory), checkpoint_file=str(checkpoint_file),
            native_library=str(retained), resumed_from=resumed_from,
            checkpoint_interval_s=checkpoint_interval_s,
            checkpoint_count=record['checkpoint_count'], checkpoint_seconds=record['checkpoint_seconds'])
        result = replace(result, metadata={**result.metadata, 'recovery': recovery})
        with staged_files([directory / 'results.h5', directory / 'metrics.json']) as stage:
            save_result(result, stage / 'results.h5')
            save_metrics(performance, stage / 'metrics.json')
        publish_status('completed', result_id=result.result_id,
                       converged=bool(result.run_status['converged']))
        return case, result, performance
    except BaseException as error:
        if completed_result is not None and not (directory / 'results.h5').exists():
            try:
                save_result(completed_result, directory / 'failed-result.h5')
                record['failed_result_file'] = 'failed-result.h5'
            except Exception as save_error:
                error.add_note(f'Could not save the completed solver fields: {save_error}')
        state = ('paused' if isinstance(error, PausedRun) else
                 'cancelled' if isinstance(error, CancelledError) else 'failed')
        try:
            publish_status(state, error=dict(type=type(error).__name__, message=str(error),
                                            notes=getattr(error, '__notes__', [])))
        except Exception as save_error:
            error.add_note(f'Could not record run status: {save_error}')
        raise
