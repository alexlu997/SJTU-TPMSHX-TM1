"""Fixed-flow preparation and equal-weight multi-condition objectives."""
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, replace
import json
from math import fsum, isfinite
from pathlib import Path
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import full_metric_version
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.domain.performance_result import PerformanceResult
from sjtu_tpmshx.logutil import get_logger
from sjtu_tpmshx.preprocess.api import (
    prepare_fixed_mass_flow_case,
    resolve_fixed_mass_flow_config as resolve_fixed_mass_flow_config,
)
from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity


_log = get_logger(__name__)

ConditionResult = tuple[str, FieldResult, PerformanceResult]
ConditionInput = tuple[str, ComputeConfig, float, float]
_METRICS = ('Q_B', 'dP_A', 'dP_B')


def _full_result_metadata(field):
    metadata = field.metadata
    dimension = metadata.get('dimension')
    if (dimension not in (2, 3) or field.grid['dimension'] != dimension
            or metadata.get('quantity_basis') != {2: 'per_unit_depth', 3: 'total'}[dimension]
            or metadata.get('mode', 'full') != 'full'
            or metadata.get('thermal_mode') not in ('model_h', 'true_h', 'conservative_energy')):
        raise ValueError('batch comparison requires full 2D/3D enthalpy results with native units')
    parameters = metadata['parameters']
    df_mode = parameters['df_mode'] if dimension == 3 else parameters['run_settings']['df_mode']
    if metadata['df_metadata']['mode'] != df_mode:
        raise ValueError('result D-F mode disagrees with prepared parameters')
    return metadata


def _check_baseline_case(reference, case, flow_a, flow_b):
    """Pair like-for-like inputs, allowing candidate inlet speed to change."""
    metadata = _full_result_metadata(reference)
    if metadata['dimension'] != case.grid['dimension']:
        raise ValueError('baseline and candidate dimensions differ')
    if metadata['design_mode'] != 'uniform':
        raise ValueError('baseline must retain the original uniform design')
    parameters = metadata['parameters']
    if case.grid['dimension'] == 2:
        from sjtu_tpmshx.domain.portable_data import mutable_data
        previous, current = (mutable_data(values['run_settings'])
                             for values in (parameters, case.parameters))
        for settings in (previous, current):
            for side in ('A', 'B'):
                settings['fluid_' + side].pop('u_mps')
        if previous != current or parameters['_environment'] != case.parameters['_environment']:
            raise ValueError('baseline and candidate fixed 2D inputs differ')
        fixed_keys = ()
    else:
        fixed_keys = ('L', 'H', 'Lz', 'tpms_type', 'k_s', 'delta_levelset',
                'fluid_type_A', 'fluid_type_B', 'T_inA', 'T_inB', 'P_inA', 'P_inB',
                'fluid_A_cfg', 'fluid_B_cfg', 'df_mode', 'sco2_nu',
                'variable_rho_cp', 'envelope_mode', '_environment', 'roughness_resolved')
    for key in fixed_keys:
        if parameters[key] != case.parameters[key]:
            raise ValueError(f'baseline and candidate differ in fixed input {key}')
    for key in ('max_iter_simple', 'max_outer_ltne', 'outer_tol_K', 'convergence_mode',
                'mom_tol', 'mass_local_tol', 'mass_global_tol', 'T_s_init',
                'simple_velocity_relaxation', 'enthalpy_algorithm', 'enthalpy_temperature_tol_K',
                'model_h_max_iterations', 'model_h_temperature_tol_K', 'model_h_q_relative_tol',
                'ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega',
                'ltne_enthalpy_tol', 'ltne_enthalpy_coupled_energy_tol',
                'ltne_enthalpy_equation_energy_tol', 'require_enthalpy_update_on_temperature'):
        default = False if key == 'require_enthalpy_update_on_temperature' else None
        if parameters.get(key, default) != case.parameters.get(key, default):
            raise ValueError(f'baseline and candidate solver setting {key} differs')
    if reference.model_refs != case.model_refs:
        raise ValueError('baseline and candidate model resources differ')
    for axis in 'xyz'[:case.grid['dimension']]:
        if not np.array_equal(reference.grid['d' + axis], case.grid['d' + axis]):
            raise ValueError('baseline and candidate evaluation grids differ')
    for name, parameter in (('L_field_m', 'L_cell_m'), ('t_field_m', 't_wall_m')):
        if not np.all(metadata['design_fields'][name] == case.parameters[parameter]):
            raise ValueError(f'baseline {name} differs from original uniform geometry')
    for side, target in (('A', flow_a), ('B', flow_b)):
        prescribed = parameters['u_' + side] * total_inlet_mass_capacity(
            metadata['design_fields'], parameters, reference.grid, side)
        # This checks serialized input arithmetic, not measured flow accuracy.
        if not np.isclose(prescribed, target, rtol=1e-12, atol=0.):
            raise ValueError(f'baseline and candidate prescribed mass flow {side} differs')



def _validate_condition_field(field, case, config):
    if field.case_id != case.case_id:
        raise ValueError('returned result does not belong to the prepared case')
    metadata = _full_result_metadata(field)
    dimension = case.grid['dimension']
    expected_thermal = ('true_h' if {'co2', 'sco2'}.intersection(
        (config.fluid_A.type, config.fluid_B.type)) else 'model_h')
    if expected_thermal == 'true_h' and config.solver.enthalpy_algorithm != 'legacy_h_fou':
        expected_thermal = 'conservative_energy'
    if metadata['thermal_mode'] != expected_thermal:
        raise ValueError('returned thermal mode disagrees with the configured fluids')
    result_mode = (metadata['parameters']['df_mode'] if dimension == 3
                   else metadata['parameters']['run_settings']['df_mode'])
    if (field.model_refs != case.model_refs or metadata['dimension'] != dimension
            or result_mode != config.df_mode
            or metadata['design_mode'] != case.metadata['design_mode']):
        raise ValueError('returned result changes prepared model or design mode')
    for name, values in case.design_fields.items():
        if not np.array_equal(metadata['design_fields'][name], values):
            raise ValueError(f'returned result changes prepared design field {name}')


def _condition_output_paths(directory):
    run = directory / 'run'
    paths = {}
    for key, name in (('run_file', 'run.json'), ('checkpoint_file', 'checkpoint.h5'),
                      ('result_file', 'failed-result.h5'), ('result_file', 'results.h5'),
                      ('metrics_file', 'metrics.json')):
        if (run / name).is_file():
            paths[key] = f'{directory.name}/run/{name}'
    return paths


def _solve_condition(case, config, directory, control, update, checkpoint_file=None, pause_check=None):
    from sjtu_tpmshx.postprocess.api import evaluate

    def evaluate_field(field):
        update(stage='validate_result')
        _validate_condition_field(field, case, config)
        control.check_cancelled()
        update(stage='postprocess')
        performance = evaluate(field)
        update(stage='save_result')
        return performance

    update(stage='solve')
    from sjtu_tpmshx.workflows.recovery import compute_prepared_run, resume_run
    primary_error = None
    try:
        if checkpoint_file is None:
            _, field, performance = compute_prepared_run(case, directory / 'run',
                checkpoint_interval_s=60., control=control, pause_check=pause_check, evaluate=evaluate_field)
        else:
            _, field, performance = resume_run(checkpoint_file, directory / 'run',
                checkpoint_interval_s=60., control=control, pause_check=pause_check, evaluate=evaluate_field)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            update(**_condition_output_paths(directory))
        except Exception as save_error:
            if primary_error is None:
                raise
            primary_error.add_note(f'Could not record native output paths: {save_error}')
            _log.exception('Could not record native condition outputs')
        # Drop the traceback cycle before the next batch member.
        primary_error = None
    return field, performance


_batch_cancel = None
_batch_events = None
_batch_pause = None


def _init_condition_worker(cancel, events, pause):
    global _batch_cancel, _batch_events, _batch_pause
    _batch_cancel, _batch_events, _batch_pause = cancel, events, pause
    # Final state returns through the future; queued progress must not delay exit.
    events.cancel_join_thread()


def _run_native_condition(index, case_file, directory, library, threads, checkpoint_file=None):
    import os
    from sjtu_tpmshx.io.case_io import load_case
    from sjtu_tpmshx.domain.portable_data import mutable_data

    directory = Path(directory)
    changes = dict(worker_pid=os.getpid(), cpu_threads=threads)
    def update(**values):
        changes.update(values)
        _batch_events.put((index, 'update', values))
    def callback(name):
        return lambda *args: _batch_events.put((index, name, args))
    tables = directory.parent / 'workers' / str(os.getpid()) / 'tables'
    tables.mkdir(parents=True, exist_ok=True)
    control = RunControl(backend='cpp', native_library=library,
        native_table_directory=str(tables), cpu_threads=threads,
        cancel_check=_batch_cancel.is_set, progress=callback('progress'),
        iteration=callback('iteration'), outer_iteration=callback('outer_iteration'),
        residual=callback('residual'))
    try:
        control.check_cancelled()
        case = load_case(case_file)
        config = ComputeConfig.from_dict(mutable_data(case.config_snapshot))
        _solve_condition(case, config, directory, control, update, checkpoint_file, _batch_pause.is_set)
        changes.update(status='computed', reason=None)
    except PausedRun as error:
        changes.update(status='paused', reason=str(error), pause_notes=getattr(error, '__notes__', []))
    except CancelledError as error:
        changes.update(status='cancelled', reason='\n'.join((str(error), *getattr(error, '__notes__', ()))))
    except Exception as error:
        changes.update(status='failed', reason='\n'.join((f'{type(error).__name__}: {error}',
                *getattr(error, '__notes__', ()))))
    return changes


def _condition_worker_count(workers, count, control):
    """Resolve one CPU allocation for batches and optimization."""
    budget = control.native_cpu_threads()
    if workers is None:
        workers = min(4, max(1, budget // 2))
    if type(workers) is not int or workers < 1:
        raise ValueError('workers must be a positive integer or None')
    return min(workers, count, budget)


def evaluate_condition_batch(
    conditions: Sequence[ConditionInput], *, output_dir: str | Path,
    baseline: Sequence[ConditionResult] | None = None,
    control: RunControl = RunControl(), workers: int | None = None,
) -> dict:
    """Run one design's fixed conditions and keep each member's evidence.

    Each input is ``(condition_id, config, mass_flow_A_kg_s, mass_flow_B_kg_s)``.
    Use the same design and fixed condition list for every comparison. The
    common result qualification includes the original model bounds. A
    ``completed`` batch does not establish experimental accuracy. Total input mass
    flows retain kg/s; 2D native metrics retain their per-unit-depth units.

    A new output directory is required. Every requested member appears in
    ``batch.json``, including failures and conditions not run after cancellation.
    Native results and metrics are saved before rejecting unconverged results.
    Ordinary condition failures do not discard later conditions; cancellation
    persists the current record and propagates ``CancelledError``. Only a fully
    completed batch with a supplied baseline can produce aggregate objectives.
    Native runs save checkpoints at safe boundaries with a 60-second interval.
    ``workers=None`` selects up to four native processes within the CPU limit.
    Automatic allocation keeps at least two CPU slots per worker when available.
    Set ``workers=1`` for serial execution.
    Callbacks run in the parent. The return value adds
    in-memory ``results`` to the JSON record in the requested order.
    """
    return _evaluate_condition_batch(conditions, output_dir=output_dir, baseline=baseline,
                                     control=control, collect_fields=True, workers=workers)


def _saved_condition_config(row):
    """Parse prescribed flow; preparation still validates the resolved speeds."""
    data = deepcopy(row['config'])
    for side in 'AB':
        data['fluid_'+side]['mass_flow_kg_s'] = row[f'mass_flow_{side}_kg_s']
    return ComputeConfig.from_dict(data)


def resume_condition_batch(batch_file, *, output_dir, control=RunControl(backend='cpp'), workers=None):
    """Keep completed members and continue saved native states in a new batch."""
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.io.metrics_io import load_metrics

    path = Path(batch_file).resolve(strict=True)
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('format') != 'condition_batch_v1' or record.get('backend') != 'cpp':
        raise ValueError('batch recovery requires a saved native condition batch')
    inputs = json.loads((path.parent / 'batch-input.json').read_text(encoding='utf-8'))
    conditions = [(row['condition_id'], _saved_condition_config(row),
                   row['mass_flow_A_kg_s'], row['mass_flow_B_kg_s']) for row in inputs]
    if [row[0] for row in conditions] != [row['condition_id'] for row in record['conditions']]:
        raise ValueError('saved batch input and condition membership differ')
    baseline = None
    if record.get('baseline_files') is not None:
        baseline = [(row['condition_id'], load_result(path.parent / row['result_file']),
                     load_metrics(path.parent / row['metrics_file'])) for row in record['baseline_files']]
    return _evaluate_condition_batch(conditions, output_dir=output_dir, baseline=baseline,
        control=control, collect_fields=True, workers=workers, resume_from=(path.parent, record))


def _check_saved_condition(case, config, flow_a, flow_b, case_id):
    from sjtu_tpmshx.domain.portable_data import mutable_data

    if case.case_id != case_id:
        raise ValueError('saved condition and prepared-case identity differ')
    resolved = mutable_data(case.config_snapshot)
    requested = config.to_dict()
    for side, target in (('A', flow_a), ('B', flow_b)):
        fluid = 'fluid_'+side
        requested[fluid]['u_mps'] = resolved[fluid]['u_mps']
        requested[fluid]['mass_flow_kg_s'] = None
        actual = case.parameters['u_'+side] * total_inlet_mass_capacity(
            case.design_fields, case.parameters, case.grid, side)
        if not np.isclose(actual, target, rtol=1e-12, atol=0.):
            raise ValueError(f'saved condition mass flow {side} differs')
    if requested != resolved:
        raise ValueError('saved condition configuration differs from its prepared input')


def _evaluate_condition_batch(conditions, *, output_dir, baseline=None,
                              control=RunControl(), collect_fields=False, workers=None, resume_from=None,
                              on_update=None, pause_check=None, keep_failed=False):
    """Share batch validation; optimizer summaries keep paths and scalar metrics."""
    from sjtu_tpmshx.io.case_io import load_case, save_case
    from sjtu_tpmshx.io.result_io import load_result, save_result
    from sjtu_tpmshx.io.metrics_io import load_metrics, save_metrics
    import shutil
    from sjtu_tpmshx.io.text_file import write_text

    from sjtu_tpmshx.domain.module_ports import resolve_control
    control = resolve_control(control)

    inputs = tuple(conditions)
    ids = tuple(row[0] for row in inputs)
    if (not ids or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('conditions require unique, nonempty condition IDs')
    worker_count = _condition_worker_count(workers, len(inputs), control)
    for condition_id, config, flow_a, flow_b in inputs:
        if not isinstance(config, ComputeConfig):
            raise TypeError(f'condition {condition_id}: config must be ComputeConfig')
        pair = (config.fluid_A.type, config.fluid_B.type)
        if pair != ('air', 'water') and not {'co2', 'sco2'}.intersection(pair):
            raise ValueError('condition batch requires air-A/water-B or a CO2/sCO2 side')
        if not all(isfinite(value) and value > 0 for value in (flow_a, flow_b)):
            raise ValueError(f'condition {condition_id}: mass flows must be finite and positive')
    frozen_keys = ('geometry', 'zones', 'bc_A', 'bc_B', 'flags', 'solver', 'df_mode',
                   'sco2_nu', 'envelope_mode', 'extrap')
    first = asdict(inputs[0][1])
    for condition_id, config, _, _ in inputs[1:]:
        current = asdict(config)
        if (any(current[key] != first[key] for key in frozen_keys)
                or any(current['fluid_' + s]['type'] != first['fluid_' + s]['type'] for s in 'AB')):
            raise ValueError(f'condition {condition_id}: design and evaluation settings must be fixed')
    reference = {}
    references = {}
    reference_metrics = {}
    if baseline is not None:
        if collect_fields:
            reference = _condition_metrics(baseline, ids, 'baseline', qualify=False)
            references = {name: field for name, field, _ in baseline}
            identities = {name: dict(case_id=field.case_id, result_id=field.result_id)
                          for name, field, _ in baseline}
        else:
            if set(baseline) != set(ids):
                raise ValueError('baseline: condition membership mismatch')
            reference = {name: row['performance'] for name, row in baseline.items()}
            identities = {name: dict(case_id=row['case_id'], result_id=row['result_id'])
                          for name, row in baseline.items()}
        reference_metrics = {name: dict(**identities[name], metrics_id=performance.result_id,
            metrics={key: asdict(performance.metrics[key]) for key in _METRICS})
            for name, performance in reference.items()}

    if resume_from is not None:
        source_root, source_record = resume_from
        source_root = Path(source_root).resolve()
        source_inputs = json.loads((source_root / 'batch-input.json').read_text(encoding='utf-8'))
        if (source_record.get('format') != 'condition_batch_v1' or source_record.get('backend') != 'cpp'
                or tuple(row['condition_id'] for row in source_record['conditions']) != ids
                or tuple(row['condition_id'] for row in source_inputs) != ids):
            raise ValueError('saved batch input and condition membership differ')
        for (_, config, a, b), saved in zip(inputs, source_inputs):
            requested, archived = config.to_dict(), _saved_condition_config(saved).to_dict()
            for settings in (requested, archived):
                for side in 'AB':
                    settings['fluid_'+side].update(u_mps=None, mass_flow_kg_s=None)
            if (requested != archived or a != saved['mass_flow_A_kg_s']
                    or b != saved['mass_flow_B_kg_s']):
                raise ValueError('saved batch inputs differ from the requested conditions')
        for row in source_record['conditions']:
            for key in ('directory', 'case_file', 'result_file', 'metrics_file', 'checkpoint_file'):
                if row.get(key) is not None:
                    (source_root / row[key]).resolve().relative_to(source_root)
    root = Path(output_dir).resolve()
    # Search recovery first copies the complete archive to a new task directory.
    retained = resume_from is not None and source_root == root
    root.mkdir(parents=True, exist_ok=retained)
    batch_id = str(uuid4())
    history = [dict(condition_id=condition_id, directory=f'condition_{index:03d}',
                    case_id=f'{batch_id}:{condition_id}', status='not_run', stage=None,
                    reason=None, case_file=None, result_file=None, metrics_file=None, qualification=None,
                    recovery_mode='new',
                    baseline=reference_metrics.get(condition_id),
                    mass_flow_A_kg_s=flow_a, mass_flow_B_kg_s=flow_b)
               for index, (condition_id, _, flow_a, flow_b) in enumerate(inputs, 1)]
    if resume_from is not None:
        for row, previous in zip(history, source_record['conditions']):
            if retained:
                row.update(previous)
            else:
                row['case_id'] = previous['case_id']
    worker_threads = max(1, control.native_cpu_threads() // worker_count)
    record = dict(format='condition_batch_v1', batch_id=batch_id, backend=control.backend, status='running', reason=None,
                  conditions=history, objectives=None, workers=worker_count,
                  native_cpu_budget=control.native_cpu_threads(),
                  resumed_from=str(resume_from[0]) if resume_from is not None else None)
    results = []
    summaries = {}
    design = {}

    def check_stop():
        control.check_cancelled()
        if pause_check is not None and pause_check():
            raise PausedRun(root / 'batch.json')

    def notify():
        if on_update is not None:
            on_update([{key: row[key] for key in ('condition_id', 'status', 'stage', 'reason')}
                       for row in history])

    def publish(primary_error=None):
        try:
            write_text(root / 'batch.json',
                       json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
        except Exception as save_error:
            if primary_error is None:
                raise
            primary_error.add_note(f'Could not save {root / "batch.json"}: {save_error!r}')
            _log.exception('Could not save condition batch checkpoint')
            raise primary_error
        try:
            notify()
        except Exception as callback_error:
            if primary_error is None:
                raise
            primary_error.add_note(f'Condition update failed: {callback_error}')
            raise primary_error

    def check_baseline(condition_id, case, flow_a, flow_b, row):
        if baseline is not None:
            row['stage'] = 'comparison'
            notify()
            if collect_fields:
                _condition_metrics([(condition_id, references[condition_id], reference[condition_id])],
                                   (condition_id,), 'baseline')
                _check_baseline_case(references[condition_id], case, flow_a, flow_b)
            else:
                baseline_field = load_result(baseline[condition_id]['result_file'])
                _condition_metrics([(condition_id, baseline_field, reference[condition_id])],
                                   (condition_id,), 'baseline')
                _check_baseline_case(baseline_field, case, flow_a, flow_b)
                del baseline_field

    def prepare_condition(condition, row, directory):
        condition_id, config, flow_a, flow_b = condition
        check_stop()
        if retained and directory.exists():
            suffix = 1
            while directory.with_name(f'{directory.name}_resume_{suffix:03d}').exists():
                suffix += 1
            directory = directory.with_name(f'{directory.name}_resume_{suffix:03d}')
            row['directory'] = directory.name
        directory.mkdir()
        write_text(directory / 'input.json', json.dumps(config.to_dict(),
            ensure_ascii=False, allow_nan=False, indent=2) + '\n')
        row['stage'] = 'prepare'
        notify()
        check_stop()
        case = None
        if resume_from is not None:
            previous = next(item for item in source_record['conditions'] if item['condition_id'] == condition_id)
            row.pop('resume_checkpoint', None)
            checkpoint = source_root / (previous.get('checkpoint_file')
                or f"{previous['directory']}/run/checkpoint.h5")
            if checkpoint.is_file():
                from sjtu_tpmshx.workflows.recovery import read_run_checkpoint
                _, case, _ = read_run_checkpoint(checkpoint)
                row['resume_checkpoint'] = str(checkpoint)
                row['recovery_mode'] = 'checkpoint'
            elif previous['case_file'] is not None:
                case = load_case(source_root / previous['case_file'])
                row['recovery_mode'] = 'prepared_restart'
            if case is not None:
                _check_saved_condition(case, config, flow_a, flow_b, row['case_id'])
        if case is None:
            case = prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=flow_a,
                mass_flow_B_kg_s=flow_b, case_id=row['case_id'])
        row['stage'] = 'save_case'
        notify()
        save_case(case, directory / 'case.yaml')
        row['case_file'] = f"{row['directory']}/case.yaml"
        publish()
        check_baseline(condition_id, case, flow_a, flow_b, row)
        check_stop()
        return case, directory

    def run_condition(index, condition, row, directory):
        condition_id, config, _, _ = condition
        case, directory = prepare_condition(condition, row, directory)
        check_stop()
        progress = (None if control.progress is None else
                    lambda percent, i=index: control.report_progress(
                        int(100 * (i + percent / 100) / len(inputs))))
        def update(**changes):
            row.update(changes)
            publish()
        field, performance = _solve_condition(case, config, directory,
            replace(control, progress=progress), update, row.get('resume_checkpoint'), pause_check)
        finish_condition(condition_id, case, row, field, performance)

    def finish_condition(condition_id, case, row, field, performance):
        result = (condition_id, field, performance)
        if collect_fields:
            results.append(result)
        row['stage'] = 'qualification'
        notify()
        from sjtu_tpmshx.domain.portable_data import mutable_data
        row['qualification'] = mutable_data(performance.qualification)
        design.update(_condition_metrics([result], (condition_id,), 'candidate'))
        if not collect_fields:
            summaries[condition_id] = dict(case_id=case.case_id, result_id=field.result_id,
                result_file=root / row['result_file'], performance=performance,
                config_snapshot=case.config_snapshot)
        row.update(status='completed', reason=None)

    def run_parallel():
        from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
        from concurrent.futures.process import BrokenProcessPool
        from multiprocessing import get_context
        from queue import Empty
        from sjtu_tpmshx.io.case_io import load_case
        from sjtu_tpmshx.io.metrics_io import load_metrics

        def finish_saved(index, row):
            case = load_case(root / row['case_file'])
            field = load_result(root / row['result_file'])
            performance = load_metrics(root / row['metrics_file'])
            finish_condition(inputs[index][0], case, row, field, performance)

        context = get_context('spawn')
        cancel, events, pause = context.Event(), context.Queue(), context.Event()
        pool = ProcessPoolExecutor(max_workers=worker_count, mp_context=context,
            initializer=_init_condition_worker, initargs=(cancel, events, pause))
        pending, next_index = {}, 0
        progress = [0] * len(inputs)
        error = None
        try:
            while pending or (next_index < len(inputs) and error is None):
                if error is None or isinstance(error, PausedRun):
                    try:
                        control.check_cancelled()
                        if error is None and pause_check is not None and pause_check():
                            error = PausedRun(root / 'batch.json')
                            pause.set()
                    except BaseException as caught:
                        error = caught
                        cancel.set()
                while error is None and len(pending) < worker_count and next_index < len(inputs):
                    index = next_index
                    next_index += 1
                    row = history[index]
                    if row['status'] in ('completed', 'failed'):
                        progress[index] = 100
                        continue
                    row.update(status='running', stage='input')
                    publish()
                    try:
                        case, _ = prepare_condition(inputs[index], row, root / row['directory'])
                        del case
                        check_stop()
                        future = pool.submit(_run_native_condition, index,
                            str(root / row['case_file']), str(root / row['directory']),
                            control.native_library, worker_threads, row.get('resume_checkpoint'))
                        pending[future] = index
                    except PausedRun as caught:
                        row.update(status='paused', reason=str(caught))
                        error = caught
                        pause.set()
                    except CancelledError as caught:
                        row.update(status='cancelled', reason=str(caught))
                        error = caught
                        cancel.set()
                    except Exception as caught:
                        row.update(status='failed', reason=f'{type(caught).__name__}: {caught}')
                        progress[index] = 100
                        if isinstance(caught, BrokenProcessPool):
                            error = caught
                            cancel.set()
                    publish()
                if not pending:
                    continue
                done, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                changed = False
                while True:
                    try:
                        index, name, values = events.get_nowait()
                    except Empty:
                        break
                    if name == 'update':
                        history[index].update(values)
                        changed = True
                    elif error is None:
                        try:
                            if name == 'progress':
                                progress[index] = max(progress[index], values[0])
                                control.report_progress(int(sum(progress) / len(inputs)))
                            else:
                                callback = getattr(control, name)
                                if callback is not None:
                                    callback(*values)
                        except BaseException as caught:
                            error = caught
                            cancel.set()
                if changed:
                    publish()
                for future in done:
                    index = pending.pop(future)
                    row = history[index]
                    try:
                        row.update(future.result())
                        if row['status'] == 'computed':
                            finish_saved(index, row)
                        elif row['status'] == 'paused':
                            if error is None:
                                error = PausedRun(root / 'batch.json')
                                pause.set()
                            for note in row['pause_notes']:
                                error.add_note(f'{row["condition_id"]}: {note}')
                        elif row['status'] == 'cancelled' and error is None:
                            error = CancelledError(row['reason'])
                            cancel.set()
                    except Exception as caught:
                        row.update(status='failed', reason=f'{type(caught).__name__}: {caught}',
                                   **_condition_output_paths(root / row['directory']))
                        if isinstance(caught, BrokenProcessPool):
                            error = caught if error is None else error
                            cancel.set()
                    progress[index] = 100
                    publish()
                if error is None:
                    try:
                        control.report_progress(int(sum(progress) / len(inputs)))
                    except BaseException as caught:
                        error = caught
                        cancel.set()
            if isinstance(error, PausedRun):
                try:
                    control.check_cancelled()
                except BaseException as caught:
                    for note in getattr(error, '__notes__', ()):
                        caught.add_note(note)
                    error = caught
            if error is not None:
                raise error
        finally:
            cancel.set()
            pool.shutdown(wait=True, cancel_futures=True)
            events.close()
            events.join_thread()

    publish()
    primary_error = None
    try:
        write_text(root / 'batch-input.json', json.dumps([dict(condition_id=name, config=config.to_dict(),
            mass_flow_A_kg_s=a, mass_flow_B_kg_s=b) for name, config, a, b in inputs],
            ensure_ascii=False, allow_nan=False, indent=2)+'\n')
        record['baseline_files'] = None
        if baseline is not None:
            record['baseline_files'] = []
            (root / 'references').mkdir(exist_ok=retained)
            for index, name in enumerate(ids):
                field = references[name] if collect_fields else load_result(baseline[name]['result_file'])
                files = dict(condition_id=name, result_file=f'references/{index:03d}.h5',
                             metrics_file=f'references/{index:03d}.json')
                save_result(field, root / files['result_file'])
                save_metrics(reference[name], root / files['metrics_file'])
                record['baseline_files'].append(files)
                del field
        check_stop()
        if control.native_library is None or not Path(control.native_library).is_absolute():
            raise ValueError('native batches require an absolute native library path')
        library = Path(control.native_library).resolve(strict=True)
        (root / 'runtime').mkdir(exist_ok=retained)
        runtime_file = root / 'runtime' / library.name
        shutil.copy2(library, runtime_file)
        if runtime_file.read_bytes() != library.read_bytes():
            raise OSError('native library changed while the batch retained its runtime')
        record['native_file'] = 'runtime/'+library.name
        publish()
        if resume_from is not None:
            for condition, row, previous in zip(inputs, history, source_record['conditions']):
                if keep_failed and previous['status'] == 'failed':
                    row.update(previous, recovery_mode='failed_copy')
                    source_directory = source_root / previous['directory']
                    if not retained and source_directory.is_dir():
                        shutil.copytree(source_directory, root / row['directory'])
                    publish()
                    continue
                if previous['status'] != 'completed':
                    continue
                name, config, a, b = condition
                row['stage'] = 'reuse'
                try:
                    case = load_case(source_root / previous['case_file'])
                    _check_saved_condition(case, config, a, b, row['case_id'])
                    field = load_result(source_root / previous['result_file'])
                    performance = load_metrics(source_root / previous['metrics_file'])
                    _validate_condition_field(field, case, config)
                    check_baseline(name, case, a, b, row)
                    _condition_metrics([(name, field, performance)], (name,), 'saved')
                    if not retained:
                        shutil.copytree(source_root / previous['directory'], root / row['directory'])
                    row.update({key: previous[key] for key in ('case_file', 'result_file', 'metrics_file')})
                    row.update(_condition_output_paths(root / row['directory']))
                    row['reused_from'] = str(source_root / previous['directory'])
                    row['recovery_mode'] = 'completed_copy'
                    finish_condition(name, case, row, field, performance)
                    del case, field, performance
                except Exception as error:
                    row.update(status='failed', reason=f'{type(error).__name__}: {error}')
                    raise
                publish()
        if worker_count > 1:
            run_parallel()
        else:
            for index, ((condition_id, config, flow_a, flow_b), row) in enumerate(zip(inputs, history)):
                check_stop()
                if row['status'] in ('completed', 'failed'):
                    continue
                directory = root / row['directory']
                row.update(status='running', stage='input')
                publish()
                condition_error = None
                try:
                    run_condition(index, (condition_id, config, flow_a, flow_b), row, directory)
                except PausedRun as exc:
                    condition_error = exc
                    row.update(status='paused', reason='\n'.join((str(exc), *getattr(exc, '__notes__', ()))))
                    raise
                except CancelledError as exc:
                    condition_error = exc
                    row.update(status='cancelled', reason='\n'.join((str(exc), *getattr(exc, '__notes__', ()))))
                    raise
                except Exception as exc:
                    condition_error = exc
                    row.update(status='failed', reason='\n'.join((f'{type(exc).__name__}: {exc}',
                        *getattr(exc, '__notes__', ()))))
                finally:
                    publish(condition_error)
                condition_error = None
                control.report_progress(int(100 * (index + 1) / len(inputs)))
        check_stop()
        if any(row['status'] != 'completed' for row in history):
            record.update(status='failed', reason='One or more conditions failed; no aggregate objectives')
        elif baseline is not None:
            try:
                record['objectives'] = _aggregate_metrics(ids, reference, design)
            except ValueError as exc:
                record.update(status='failed', reason=f'Aggregate rejected: {exc}')
            else:
                record['status'] = 'completed'
        else:
            record['status'] = 'completed'
    except (CancelledError, PausedRun) as exc:
        primary_error = exc
        record.update(status='paused' if isinstance(exc, PausedRun) else 'cancelled',
                      reason=str(exc), objectives=None)
        raise
    except Exception as exc:
        primary_error = exc
        record.update(status='failed', reason=f'{type(exc).__name__}: {exc}', objectives=None)
        for row in history:
            if row['status'] == 'running':
                row.update(status='failed', reason=record['reason'])
        raise
    finally:
        publish(primary_error)
    if collect_fields:
        order = {name: index for index, name in enumerate(ids)}
        results.sort(key=lambda item: order[item[0]])
    return {**record, **({'results': results} if collect_fields else {'summaries': summaries})}


def _condition_metrics(rows: Sequence[ConditionResult], condition_ids: tuple[str, ...],
                       label: str, *, qualify=True) -> dict[str, PerformanceResult]:
    results = {}
    for condition_id, field, performance in rows:
        prefix = f'{label} condition {condition_id}'
        if condition_id in results:
            raise ValueError(f'{prefix}: duplicate condition')
        if performance.source_result_id != field.result_id:
            raise ValueError(f'{prefix}: performance source does not match field result')
        if (field.run_status.get('execution') != 'completed'
                or field.run_status.get('converged') is not True):
            raise ValueError(f'{prefix}: run must be completed and converged')
        dimension = field.grid.get('dimension', field.metadata.get('dimension'))
        for name in _METRICS:
            metric = performance.metrics.get(name)
            if metric is None or metric.status != 'available':
                reason = 'missing metric' if metric is None else metric.reason
                raise ValueError(f'{prefix}: {name} unavailable: {reason}')
            if metric.value is None or not isfinite(metric.value):
                raise ValueError(f'{prefix}: {name} must be finite')
            if (name == 'Q_B' and dimension in (2, 3)
                    and metric.spec.unit != ('W/m' if dimension == 2 else 'W')):
                raise ValueError(f'{prefix}: Q_B unit disagrees with the result dimension')
        if qualify:
            from sjtu_tpmshx.postprocess.api import evaluate_qualification
            qualification = evaluate_qualification(field, performance.metrics)
            if qualification['optimization']['passed'] is not True:
                raise ValueError(f'{prefix}: optimization qualification failed: '
                                 + '; '.join(qualification['optimization']['reasons']))
        results[condition_id] = performance
    if set(results) != set(condition_ids):
        missing = sorted(set(condition_ids) - set(results))
        extra = sorted(set(results) - set(condition_ids))
        raise ValueError(f'{label}: condition membership mismatch; missing={missing}, extra={extra}')
    return results


def aggregate_multi_condition(
    condition_ids: Sequence[str],
    baseline: Sequence[ConditionResult],
    candidate: Sequence[ConditionResult],
) -> dict[str, float]:
    """Compare one design with the fixed uniform baseline at every condition.

    Each row pairs an explicit operating-condition ID with the native field
    result and its evaluated metrics. IDs are independent of design case IDs.
    All requested conditions must occur exactly once on each side. Invalid or
    unavailable runs raise ``ValueError`` instead of contributing a penalty or
    changing the averaging denominator. The common qualification owns result
    optimization permission. Model accuracy can remain unverified for sCO2.
    The caller owns the identity of the fixed baseline design.

    The fixed heat metric is ``-Q_B``: useful B-side heat uptake, preserving
    the Shanghai benchmark objective for CO2/sCO2. Native ``Q_B`` is signed heat loss, so it
    is negated, never made absolute; the generic A-side ``Q`` is not consumed.
    Heat gain is maximized; the independent pressure ratio is minimized. Metric
    definitions and units must match the baseline for each condition. No Pa
    floor, pressure cap, absolute gain, or objective scalarization is applied.
    """
    ids = tuple(condition_ids)
    if not ids or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError('condition_ids must contain nonempty string IDs')
    if len(set(ids)) != len(ids):
        raise ValueError('condition_ids must not contain duplicates')
    reference = _condition_metrics(baseline, ids, 'baseline')
    design = _condition_metrics(candidate, ids, 'candidate')
    return _aggregate_metrics(ids, reference, design)


def _aggregate_metrics(ids, reference, design):
    heat_gains, pressure_ratios = [], []
    for condition_id in ids:
        ratios = {}
        for name in _METRICS:
            base = reference[condition_id].metrics[name]
            current = design[condition_id].metrics[name]
            base_value = -base.value if name == 'Q_B' else base.value
            current_value = -current.value if name == 'Q_B' else current.value
            if base_value <= 0:
                denominator = '-Q_B' if name == 'Q_B' else name
                raise ValueError(f'baseline condition {condition_id}: {denominator} must be positive')
            if ((base.spec.unit, base.spec.definition_version)
                    != (current.spec.unit, current.spec.definition_version)):
                raise ValueError(f'condition {condition_id}: {name} metric definitions differ')
            if base.spec.definition_version != full_metric_version(name):
                raise ValueError(f'condition {condition_id}: re-evaluate native results '
                                 f'before comparing the current {name} definition')
            ratio = current_value / base_value
            if not isfinite(ratio):
                raise ValueError(f'condition {condition_id}: {name} ratio is not finite')
            ratios[name] = ratio
        heat_gains.append(ratios['Q_B'] - 1.0)
        pressure_ratios.append(0.5 * ratios['dP_A'] + 0.5 * ratios['dP_B'])
    scores = {
        'heat_gain_percent': 100.0 * fsum(value / len(ids) for value in heat_gains),
        'pressure_ratio': fsum(value / len(ids) for value in pressure_ratios),
    }
    if not all(isfinite(value) for value in scores.values()):
        raise ValueError('aggregate objectives must be finite')
    return scores
