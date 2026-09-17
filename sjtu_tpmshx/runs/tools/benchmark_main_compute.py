"""Measure a frozen local manifest through prepare → solve → evaluate → display.

Each job has id, config (ComputeConfig data), and optional reference/depth_m.
No experiment data is bundled. Outputs are new per-run directories; native
Case/Result files retain settings, physical evidence and nonfinite diagnostics.
Run from the source root with the project's configured interpreter.
"""
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import asdict
import argparse
import functools
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
from time import perf_counter
import traceback
from unittest.mock import patch
from uuid import uuid4


def json_data(value):
    import numpy as np
    if isinstance(value, np.ndarray):
        return json_data(value.tolist())
    if isinstance(value, np.generic):
        return json_data(value.item())
    if isinstance(value, Mapping):
        return {key: json_data(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_data(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path, value):
    from sjtu_tpmshx.io.text_file import write_text
    write_text(path, json.dumps(json_data(value), ensure_ascii=False, allow_nan=False, indent=2) + '\n')


@contextmanager
def observe_solver(dimension, calls):
    """Boundary clocks only, not a statistical profiler or an alternate solve.

    Call spans are inclusive and may overlap. Never add SIMPLE A/B durations
    to obtain elapsed time. The unmodified solver remains the only executor.
    """
    sides = {}
    labels = threading.local()
    if dimension == 3:
        from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D as cls
        from sjtu_tpmshx.solvers.backends.python.three_d import result_capture as capture, runtime
    else:
        from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver as cls
        from sjtu_tpmshx.solvers.backends.python.two_d import result_capture as capture, execution

    def clocked(original, label, simple=False):
        @functools.wraps(original)
        def call(*args, **kwargs):
            start = perf_counter()
            record = dict(name=label, start_s=start, thread=threading.current_thread().name)
            record['controls'] = {key: kwargs[key] for key in
                                  ('max_iter', 'tol', 'tol_T', 'extra_tol', 'track', 'max_outer', 'max_inner')
                                  if key in kwargs}
            if label == 'outer_criterion':
                record['controls'].update(tol_T=args[0].tol_T, track=args[0].track)
            if simple:
                solver = args[0]
                record.update(side=sides.get(id(solver), getattr(labels, 'side', None)), max_iter=kwargs.get('max_iter'),
                              tol=kwargs.get('tol'), settings={key: getattr(solver, key, None)
                              for key in ('convergence_mode', 'mom_tol', 'mass_local_tol', 'mass_global_tol')})
            try:
                result = original(*args, **kwargs)
                if simple:
                    record['return'] = result
                return result
            finally:
                record['elapsed_s'] = perf_counter() - start
                calls.append(record)
        return call

    with ExitStack() as stack:
        from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence
        stack.enter_context(patch.object(OuterConvergence, 'check', clocked(OuterConvergence.check, 'outer_criterion')))
        stack.enter_context(patch.object(cls, 'solve', clocked(cls.solve, 'SIMPLE', True)))
        stack.enter_context(patch.object(capture, 'capture_result', clocked(capture.capture_result, 'native_capture')))
        if dimension == 3:
            from sjtu_tpmshx.solvers import ltne_enthalpy_3d as enthalpy
            stack.enter_context(patch.object(runtime, 'run_outer_coupling', clocked(runtime.run_outer_coupling, 'outer_loop')))
            stack.enter_context(patch.object(runtime, 'solve_full_domain_3d', clocked(runtime.solve_full_domain_3d, 'LTNE')))
            stack.enter_context(patch.object(enthalpy, 'solve_ltne_enthalpy_3d_pipeline', clocked(enthalpy.solve_ltne_enthalpy_3d_pipeline, 'enthalpy')))
            pair = runtime._run_two_simple
            def paired(a, b, **kwargs):
                sides.update({id(a): 'A', id(b): 'B'})
                return pair(a, b, **kwargs)
            stack.enter_context(patch.object(runtime, '_run_two_simple', paired))
        else:
            from sjtu_tpmshx.solvers.backends.python.two_d import coupling
            from sjtu_tpmshx.solvers import ltne_enthalpy_2d as enthalpy
            stack.enter_context(patch.object(coupling, 'run_outer_coupling', clocked(coupling.run_outer_coupling, 'outer_loop')))
            stack.enter_context(patch.object(coupling, 'solve_full_domain', clocked(coupling.solve_full_domain, 'LTNE')))
            stack.enter_context(patch.object(enthalpy, 'solve_enthalpy_2d', clocked(enthalpy.solve_enthalpy_2d, 'enthalpy')))
            build = execution.build_runtime
            def build_runtime(*args, **kwargs):
                fields = build(*args, **kwargs)
                original = fields['_run_simple']
                def solve_side(*args, **kwargs):
                    labels.side = str(args[5])
                    try:
                        return clocked(original, labels.side)(*args, **kwargs)
                    finally:
                        del labels.side
                fields['_run_simple'] = solve_side
                return fields
            stack.enter_context(patch.object(execution, 'build_runtime', build_runtime))
        yield


@contextmanager
def sample_rss(samples):
    """macOS/Linux RSS and native threads every 0.5 s; failures are explicit.

    Thread/process samples refer to this process. The solver creates threads,
    not worker processes; ps itself is an observer subprocess.
    """
    stop = threading.Event()
    def sample():
        while True:
            try:
                result = subprocess.run(['ps', '-o', 'rss=', '-p', str(os.getpid())],
                                        capture_output=True, text=True, check=True)
                threads = subprocess.run(['ps', '-M' if sys.platform == 'darwin' else '-L',
                                          '-p', str(os.getpid())],
                                         capture_output=True, text=True, check=True)
                samples.append(dict(time_s=perf_counter(), rss_bytes=int(result.stdout.strip()) * 1024,
                                    native_threads=len(threads.stdout.splitlines()) - 1))
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                samples.append(dict(time_s=perf_counter(), error=str(exc)))
                return
            if stop.wait(.5):
                return
    thread = threading.Thread(target=sample, name='RSS observer')
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def run_one(job, output, *, sample_kind):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate
    from sjtu_tpmshx.controllers.module_adapter import to_compute_result
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.io.result_io import save_result, load_result
    from sjtu_tpmshx.io.metrics_io import save_metrics, load_metrics
    from sjtu_tpmshx.domain.provenance import source_context
    from sjtu_tpmshx.validation.cases.validate_sco2_exp_q import FLOW_REL_TOL

    run_id = job['id'] + '-' + uuid4().hex
    target = output / run_id
    target.mkdir(parents=True, exist_ok=False)
    row = dict(run_id=run_id, job_id=job['id'], sample_kind=sample_kind,
               source=source_context(), interpreter=sys.executable, execution='started',
               environment={key: value for key, value in os.environ.items() if key.startswith(
                   ('TPMSHX_', 'SJTU_', 'NUMBA_', 'OMP_', 'OPENBLAS_', 'MKL_', 'VECLIB_', 'QT_', 'COOLPROP_'))},
               reference=job.get('reference', {}), timings_s={}, stage_spans=[], calls=[], rss_samples=[])
    write_json(target / 'attempt.json', row)

    def timed(name, fn, *args, **kwargs):
        start = perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            row['timings_s'][name] = perf_counter() - start
            row['stage_spans'].append(dict(name=name, start_s=start,
                                          elapsed_s=row['timings_s'][name]))

    start = perf_counter()
    try:
        with (target / 'solver.log').open('w') as log, redirect_stdout(log), redirect_stderr(log), sample_rss(row['rss_samples']):
            cfg = timed('config', ComputeConfig.from_dict, job['config'])
            case = timed('prepare', prepare_case, cfg, case_id=run_id)
            row.update(config=asdict(cfg), actual_grid=case.grid,
                       model_refs=[dict(name=ref.name, version=ref.version,
                                        parameters=ref.parameters, applicability=ref.applicability)
                                   for ref in case.model_refs])
            with observe_solver(case.grid['dimension'], row['calls']):
                native = timed('solve_inclusive', run_case, case)
            performance = timed('evaluate', evaluate, native)
            display = timed('application_map', to_compute_result, native, performance)
            row.update(execution=native.run_status['execution'], run_status=native.run_status,
                       result_id=native.result_id,
                       model_metadata=native.metadata.get('model_metadata', {}),
                       native_metrics={key: asdict(metric) for key, metric in performance.metrics.items()},
                       residuals=display.residuals, warnings=display.warnings,
                       envelope_valid=display.diagnostics.get('envelope_valid'),
                       convergence_detail=display.diagnostics.get('convergence_detail'),
                       display_metrics={key: getattr(display, key) for key in
                                        ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K')})
            q = performance.metrics['Q']
            depth = job.get('depth_m')
            total_q = q.value * depth if q.value is not None and q.spec.unit == 'W/m' and depth is not None else q.value
            row['experiment_comparison'] = dict(Q_W=total_q, depth_m=depth,
                definition='native Q multiplied by physical depth for 2D; native W for 3D',
                reference_Q_W=job.get('reference', {}).get('Q_W'))
            if job.get('family') == 'shanghai' and case.grid['dimension'] == 2:
                from sjtu_tpmshx.models.tpms_calc import air_cp
                row['legacy_comparison'] = dict(Q_W=job['reference']['mdot_A_kg_s'] *
                    float(air_cp(cfg.fluid_A.T_in_K)) * (cfg.fluid_A.T_in_K - display.T_out_A_K),
                    definition='measured air mass flow * cp(T_in) * predicted temperature drop')
            row['mass_flow_comparison'] = {}
            for side in ('A', 'B'):
                flow = performance.metrics['mass_flow_' + side]
                observed = flow.value
                if observed is not None and case.grid['dimension'] == 2:
                    observed = None if depth is None else observed * depth
                expected = job.get('reference', {}).get('mdot_' + side + '_kg_s')
                row['mass_flow_comparison'][side] = dict(actual_kg_s=observed, expected_kg_s=expected,
                    metric_status=flow.status, reason=flow.reason,
                    relative_error=None if observed is None or expected is None else observed / expected - 1)
            row['software_qualified'] = bool(native.run_status['converged']
                and display.diagnostics.get('envelope_valid', True)
                and (row['convergence_detail'] or {}).get('outer_converged', True) and all(
                performance.metrics[key].status == 'available' for key in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')))
            required_flows = [flow for flow in row['mass_flow_comparison'].values()
                              if flow['expected_kg_s'] is not None]
            row['input_flow_check'] = dict(relative_tolerance=FLOW_REL_TOL,
                status=('not_requested' if not required_flows else 'passed' if all(
                    flow['relative_error'] is not None and abs(flow['relative_error']) <= FLOW_REL_TOL
                    for flow in required_flows) else 'failed'))
            row['qualified_for_performance'] = row['software_qualified'] and row['input_flow_check']['status'] != 'failed'
            timed('write_case', save_case, case, target / 'case.h5')
            timed('write_result', save_result, native, target / 'result.h5')
            timed('write_metrics', save_metrics, performance, target / 'metrics.json')
            restored_case = timed('read_case', load_case, target / 'case.h5')
            restored_result = timed('read_result', load_result, target / 'result.h5')
            restored_metrics = timed('read_metrics', load_metrics, target / 'metrics.json')
            assert restored_case.case_id == restored_result.case_id == case.case_id
            assert restored_metrics.source_result_id == restored_result.result_id == native.result_id
    except Exception as exc:
        row.update(execution='failed', qualified_for_performance=False,
                   exception=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    row['timings_s']['total_inclusive'] = perf_counter() - start
    row['files_bytes'] = {p.name: p.stat().st_size for p in target.iterdir()}
    row['python_threads_after'] = threading.active_count()
    row['rss_sample_interval_s'] = .5
    values = [r['rss_bytes'] for r in row['rss_samples'] if 'rss_bytes' in r]
    row['sampled_peak_rss_bytes'] = max(values) if values else None
    write_json(target / 'measurement.json', row)
    print(run_id, row['execution'], 'qualified_for_performance=', row.get('qualified_for_performance'),
          row['timings_s'], flush=True)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--jobs', nargs='+', help='frozen job IDs; default all')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--warmup', action='store_true')
    args = parser.parse_args(argv)
    jobs = json.loads(args.manifest.read_text())['jobs']
    if args.jobs:
        by_id = {job['id']: job for job in jobs}
        jobs = [by_id[name] for name in args.jobs]
    if args.repeat < 1 or not jobs:
        parser.error('at least one job and one repetition are required')
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'selection.json', dict(manifest=str(args.manifest.resolve()),
               jobs=[j['id'] for j in jobs], repeat=args.repeat, warmup=args.warmup))
    outcomes = []
    for job in jobs:
        if args.warmup:
            row = run_one(job, args.output, sample_kind='warmup')
            outcomes.append((row['execution'], row.get('qualified_for_performance')))
            del row
        for index in range(args.repeat):
            row = run_one(job, args.output, sample_kind=f'measured-{index + 1}')
            outcomes.append((row['execution'], row.get('qualified_for_performance')))
            del row
    return 1 if any(state != 'completed' for state, _ in outcomes) else 2 if any(
        not qualified for _, qualified in outcomes) else 0


if __name__ == '__main__':
    raise SystemExit(main())
