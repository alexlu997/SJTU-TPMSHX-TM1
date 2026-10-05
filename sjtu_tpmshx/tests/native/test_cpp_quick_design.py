"""Public native QD handoff, failure semantics and isolation with the qualified driver."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.case_io import save_case
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.models.fluid_props import WaterStateError, QuickDesignWaterFieldError
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.native import test_quick_design_driver as qd
from sjtu_tpmshx.tests.native.test_quick_design_driver import prepared, python_run

ROOT = Path(__file__).resolve().parents[3]
quick_design_native = qd.quick_design_native
same_qd_thermal = qd.same_qd_thermal


@pytest.fixture(scope='module')
def native_control():
    system = 'macos' if sys.platform == 'darwin' else ('windows' if os.name == 'nt' else 'linux')
    arch = platform.machine().lower()
    if arch in ('amd64', 'x86_64'):
        arch = 'x64' if os.name == 'nt' else 'x86_64'
    name = ('tpmshx_solver_shared.dll' if os.name == 'nt' else
            'libtpmshx_solver_shared.' + ('dylib' if sys.platform == 'darwin' else 'so'))
    path = Path(os.environ.get('TPMSHX_SOLVER_LIBRARY',
        str(ROOT / '.cache/native-deps/build' / f'pilot-{system}-{arch}' / name))).resolve()
    if not path.is_file():
        message = f'native solver qualification library is not built: {path}'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1' or 'TPMSHX_SOLVER_LIBRARY' in os.environ:
            pytest.fail(message)
        pytest.skip(message)
    return RunControl(backend='cpp', native_library=str(path))


def compare_results(actual, expected, plane):
    rtol, atol = (2e-12, 2e-10) if plane else (2e-11, 2e-9)
    assert actual.backend_id == 'cpp' and expected.backend_id == 'python'
    assert actual.fields.keys() == expected.fields.keys()
    for key in actual.fields:
        np.testing.assert_allclose(actual.fields[key], expected.fields[key], rtol=rtol, atol=atol)
    assert actual.field_metadata == expected.field_metadata
    assert actual.pressure_evidence == expected.pressure_evidence
    assert actual.run_status['converged'] == expected.run_status['converged']
    assert actual.run_status['physical_validation'] == 'not_established'
    assert len(actual.run_status['passes']) == len(expected.run_status['passes'])
    for a, b in zip(actual.run_status['passes'], expected.run_status['passes']):
        assert a.keys() == b.keys()
        assert a['iterations'] == b['iterations'] and a['converged'] == b['converged']
        assert a['delegated_to_2d'] == b['delegated_to_2d']
        assert a['residual'] == pytest.approx(b['residual'], rel=rtol, abs=atol)
    for side in ('A', 'B'):
        assert actual.boundary_fluxes[side].keys() == expected.boundary_fluxes[side].keys()
        for name, value in actual.boundary_fluxes[side].items():
            assert value == pytest.approx(expected.boundary_fluxes[side][name], rel=2e-10)
    for name, metric in evaluate(actual).metrics.items():
        target = evaluate(expected).metrics[name]
        assert metric.status == target.status and metric.spec == target.spec
        if metric.value is not None:
            assert metric.value == pytest.approx(target.value, rel=2e-10, abs=2e-8)


@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
@pytest.mark.parametrize('mode', ['const', 'mean'])
@pytest.mark.parametrize('pair,topology', [('air_water', 'Diamond'), ('water_air', 'Gyroid'),
                                         ('sco2_sco2', 'Diamond')])
def test_public_fields_metrics_and_pass_contract(native_control, same_qd_thermal, monkeypatch, arrangement, mode, pair, topology):
    case = prepared(arrangement, mode, pair, topology)
    expected = python_run(case, monkeypatch, thermal=same_qd_thermal, public=True)[0]
    actual = run_case(case, native_control)
    compare_results(actual, expected, arrangement == 'cross')


def test_warnings_use_native_pass_evidence_without_python_numerics(native_control, same_qd_thermal, monkeypatch):
    from sjtu_tpmshx.models import quick_design, design_fluids, fluid_props
    case = prepared('counter', 'mean', 'water_air')
    p = case.parameters
    # Prepared dP remains frozen; these changed states specifically exercise
    # existing property/Re warnings on both actual property passes.
    case = replace(case, parameters={**p, 'operating_point': {
        **p['operating_point'], 'T_in_h': 380., 'P_in_h': 3e6, 'mdot_c': .001}})
    expected = python_run(case, monkeypatch, thermal=same_qd_thermal, public=True)[0]

    def forbidden(*args, **kwargs):
        pytest.fail('native execution called a Python property or thermal implementation')

    monkeypatch.setattr(quick_design, '_hvol', forbidden)
    monkeypatch.setattr(design_fluids, 'fluid_props', forbidden)
    monkeypatch.setattr(fluid_props, 'check_water_state', forbidden)
    monkeypatch.setattr('sjtu_tpmshx.solvers.backends.python.quick_design.execution.solve_full_domain_3d', forbidden)
    actual = run_case(case, native_control)
    # Native roundoff can alter the printed last digit of extrema. Source,
    # side, stage, layout, label and original range must match exactly.
    signature = lambda result: [message.split('finite extrema')[0]
        for message in result.metadata['diagnostics']['warnings_list']]
    assert signature(actual) == signature(expected)
    assert any('water_cp' in message for message in signature(actual))
    compare_results(actual, expected, False)


@pytest.mark.parametrize('failure', ['cancel', 'callback_error', 'water_input', 'water_field'])
def test_failed_run_then_success_and_warm_input_preserved(native_control, failure):
    case = prepared('cross', 'mean')
    p = case.parameters
    shape = tuple(len(case.grid['d' + axis]) for axis in 'xyz')
    seed = tuple(np.full(shape, t) for t in (340., 330., 335.))
    bad = replace(case, parameters={**p, 'initial_fields': seed})
    control = native_control
    if failure == 'water_input':
        bad = replace(bad, parameters={**bad.parameters,
            'operating_point': {**p['operating_point'], 'T_in_c': 500.}})
        exception = WaterStateError
    elif failure == 'water_field':
        seed[1][0, 0, 0] = 500.
        bad = replace(bad, parameters={**p, 'initial_fields': seed})
        exception = QuickDesignWaterFieldError
    elif failure == 'cancel':
        progressed = []
        control = replace(control, progress=progressed.append, cancel_check=lambda: bool(progressed))
        exception = CancelledError
    else:
        def failing_callback(percent):
            raise LookupError('callback did not complete')
        control = replace(control, progress=failing_callback)
        exception = LookupError
    saved = [value.copy() for value in bad.parameters['initial_fields']]
    with pytest.raises(exception):
        run_case(bad, control)
    for actual, expected in zip(bad.parameters['initial_fields'], saved):
        np.testing.assert_array_equal(actual, expected)
    assert run_case(case, native_control).run_status['converged']


def test_budget_exhaustion_is_saved_as_unconverged(native_control, tmp_path):
    case = prepared('cross', 'mean')
    p = case.parameters
    case = replace(case, parameters={**p, 'controls': {**p['controls'], 'maxit': 7, 'chunk': 5}})
    result = run_case(case, native_control)
    assert not result.run_status['converged']
    assert [item['iterations'] for item in result.run_status['passes']] == [7, 7]
    save_result(result, tmp_path / 'unconverged.h5')
    restored = load_result(tmp_path / 'unconverged.h5')
    assert restored.run_status == result.run_status
    assert restored.metadata['native']['solver_abi'] == 1


def test_two_runs_cancel_only_one(native_control, same_qd_thermal, monkeypatch):
    first, second = prepared('cross', 'mean'), prepared('counter', 'mean', 'sco2_sco2')
    progressed = []
    cancelled_control = replace(native_control, progress=progressed.append,
                                cancel_check=lambda: bool(progressed))
    with ThreadPoolExecutor(max_workers=2) as workers:
        cancelled = workers.submit(run_case, first, cancelled_control)
        completed = workers.submit(run_case, second, native_control)
        with pytest.raises(CancelledError):
            cancelled.result()
        result = completed.result()
    compare_results(result, python_run(second, monkeypatch, thermal=same_qd_thermal, public=True)[0], False)


@pytest.mark.parametrize('invalid', ['missing', 'relative', 'wrong_abi', 'unknown_mode', 'unknown_3d_mode', 'dimension'])
def test_library_and_capability_errors_are_explicit(native_control, tmp_path, monkeypatch, invalid):
    from sjtu_tpmshx.solvers.backends.cpp import quick_design
    case = prepared()
    control = native_control
    if invalid == 'missing':
        control = replace(control, native_library=str(tmp_path / 'missing'))
        exception, match = FileNotFoundError, 'missing'
    elif invalid == 'relative':
        control = replace(control, native_library='relative.dll')
        exception, match = ValueError, 'absolute'
    elif invalid == 'wrong_abi':
        monkeypatch.setattr(quick_design.ct, 'CDLL', lambda path: SimpleNamespace(tpmshx_solver_abi_version=lambda: 99))
        exception, match = ValueError, 'ABI: 99'
    elif invalid in ('unknown_mode', 'unknown_3d_mode'):
        case = replace(case, metadata={**case.metadata, 'mode': 'unknown'})
        if invalid == 'unknown_3d_mode':
            case = replace(case, grid={**case.grid, 'dimension': 3})
        exception, match = ValueError, 'unsupported solver mode'
    else:
        case = replace(case, metadata={**case.metadata, 'mode': 'full'},
                       grid={**case.grid, 'dimension': 4})
        exception, match = ValueError, 'unsupported physical dimension'
    with pytest.raises(exception, match=match):
        run_case(case, control)


def test_fresh_process_replays_saved_case_without_python_kernels(native_control, tmp_path):
    case_path, result_path = tmp_path / 'case.h5', tmp_path / 'result.h5'
    save_case(prepared('counter', 'mean', 'sco2_sco2'), case_path)
    code = '''
import sys
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
result = run_case(load_case(sys.argv[1]), RunControl(backend='cpp', native_library=sys.argv[3]))
assert result.run_status['converged'] and evaluate(result).metrics['Q'].status == 'available'
save_result(result, sys.argv[2])
forbidden = ('numba', 'sjtu_tpmshx.solvers.ltne_', 'sjtu_tpmshx.solvers.simple_',
             'sjtu_tpmshx.solvers._kernels', 'sjtu_tpmshx.solvers.backends.python.quick_design')
assert not [name for name in sys.modules if name.startswith(forbidden)]
'''
    process = subprocess.run([sys.executable, '-c', code, str(case_path), str(result_path),
                              native_control.native_library], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    restored = load_result(result_path)
    assert restored.backend_id == 'cpp' and restored.run_status['converged']


def test_parallel_selection_keeps_native_backend_and_infeasible_candidates(
        native_control, monkeypatch, tmp_path):
    from threading import Lock
    from sjtu_tpmshx.design import select
    from sjtu_tpmshx.tests.design.test_select import _cases

    # The 4 mm cell exceeds this inlet-pressure limit even at the largest
    # build width; the 8 mm cell completes the real sizing search and solve.
    cases = [replace(_cases()[0], Q=30., dPlim_h=2e-5)]
    nodes = dict(topo=['Diamond'], l=[4., 8.], t=[.4])
    library = native_control.native_library
    table_directory = str(tmp_path / 'tables')
    Path(table_directory).mkdir()
    parent_pid = os.getpid()
    progress, lock = [], Lock()

    def report(percent):
        # A real host callback can own unpicklable state (for example Qt).
        with lock:
            progress.append(percent)

    control = replace(native_control, native_table_directory=table_directory,
                      progress=report)

    def traced_sizing(log_directory):
        def size(*args, **kwargs):
            from unittest.mock import patch
            from sjtu_tpmshx.design.sizing import size_fixed_cell
            from sjtu_tpmshx.solvers import api

            child = kwargs['control']
            assert child.backend == 'cpp'
            assert child.native_library == library
            assert child.native_table_directory == table_directory
            if os.getpid() != parent_pid:
                assert all(getattr(child, name) is None for name in (
                    'progress', 'cancel_check', 'iteration', 'outer_iteration', 'residual'))
            calls = []
            original = api.run_case

            def run(prepared_case, control):
                result = original(prepared_case, control)
                assert result.backend_id == 'cpp'
                calls.append(result.backend_id)
                return result

            with patch.object(api, 'run_case', run):
                design = size_fixed_cell(*args, **kwargs)
            (log_directory / f'{design.l}.json').write_text(json.dumps(dict(
                pid=os.getpid(), calls=calls, feasible=design.feasible)))
            return design
        return size

    results = []
    for n_jobs in (1, 2):
        log_directory = tmp_path / str(n_jobs)
        log_directory.mkdir()
        monkeypatch.setattr(select, 'size_fixed_cell', traced_sizing(log_directory))
        completed = []
        designs, best = select.enumerate_select(
            cases, nodes=nodes, n_jobs=n_jobs, control=control, completed=completed)
        assert designs is completed and len(designs) == 2
        assert [design.feasible for design in designs] == [False, True]
        assert designs[0].reason == 'dP>lim@s_max' and best is designs[1]
        traces = [json.loads((log_directory / f'{l}.json').read_text()) for l in nodes['l']]
        assert not traces[0]['calls'] and traces[1]['calls']
        if n_jobs == 1:
            assert all(trace['pid'] == parent_pid for trace in traces)
        else:
            assert all(trace['pid'] != parent_pid for trace in traces)
        results.append(designs)
        if n_jobs == 1:
            assert progress
            serial_progress_count = len(progress)
    assert len(progress) == serial_progress_count
    assert results[1] == results[0]


@pytest.mark.parametrize('exhausted', [False, True])
def test_saved_qd_cpp_cli_solve_postprocess_and_replay(native_control, tmp_path, exhausted):
    case = prepared('cross', 'mean')
    if exhausted:
        case = replace(case, parameters={**case.parameters, 'controls': {
            **case.parameters['controls'], 'maxit': 7, 'chunk': 5}})
    source, tables = tmp_path / 'case.h5', tmp_path / 'tables'
    save_case(case, source)
    original = source.read_bytes()
    expected = run_case(case, native_control)
    outputs = []
    for attempt in range(2):
        output = tmp_path / f'result-{attempt}.h5'
        command = [sys.executable, '-m', 'sjtu_tpmshx.workflows.cli', 'solve',
                   str(source), str(output), '--backend', 'cpp',
                   '--native-library', native_control.native_library,
                   '--native-table-directory', str(tables)]
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert process.returncode == (2 if exhausted else 0), process.stdout + process.stderr
        result = load_result(output)
        assert result.backend_id == 'cpp' and result.run_status == expected.run_status
        assert result.run_status['converged'] is (not exhausted)
        for name in expected.fields:
            np.testing.assert_array_equal(result.fields[name], expected.fields[name])
        assert result.pressure_evidence == expected.pressure_evidence
        assert native_control.native_library not in str(result.metadata)
        assert str(tables) not in str(result.metadata)
        outputs.append(output)
    assert source.read_bytes() == original
    metrics_path = tmp_path / 'metrics.json'
    process = subprocess.run([
        sys.executable, '-m', 'sjtu_tpmshx.workflows.cli', 'postprocess',
        str(outputs[1]), str(metrics_path)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    performance = load_metrics(metrics_path)
    assert performance.source_result_id == load_result(outputs[1]).result_id
    assert performance.metrics == evaluate(expected).metrics


def test_cpp_cli_missing_library_preserves_existing_result(native_control, tmp_path):
    source, output = tmp_path / 'case.h5', tmp_path / 'result.h5'
    save_case(prepared(), source)
    output.write_bytes(b'previous result')
    missing = tmp_path / 'missing-library'
    process = subprocess.run([
        sys.executable, '-m', 'sjtu_tpmshx.workflows.cli', 'solve', str(source), str(output),
        '--backend', 'cpp', '--native-library', str(missing)],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert process.returncode != 0 and 'missing-library' in process.stderr
    assert output.read_bytes() == b'previous result'


@pytest.mark.parametrize('mode', ['fixed', 'auto'])
def test_design_cli_performs_real_native_sizing(native_control, tmp_path, monkeypatch, mode):
    import openpyxl
    from sjtu_tpmshx.design import cli
    from sjtu_tpmshx.solvers import api

    source, output = tmp_path / 'spec.csv', tmp_path / 'design.xlsx'
    source.write_text(
        'case,hot_fluid,T_in_h_K,P_in_h_kPa,mdot_h,cold_fluid,T_in_c_K,P_in_c_kPa,'
        'mdot_c,Q_kW,dPlim_h,dPlim_c\n'
        '1,air,688.23,1088.7,0.2855,water,320,200,0.5,0.03,0.00002,0.05\n')
    before = source.read_bytes()
    observed = []
    original = api.run_case

    def run(prepared_case, control):
        result = original(prepared_case, control)
        assert result.backend_id == 'cpp'
        observed.append(result)
        return result

    monkeypatch.setattr(api, 'run_case', run)
    arguments = ['--xlsx', str(source), '--mode', mode, '--out', str(output),
                 '--jobs', '1', '--backend', 'cpp',
                 '--native-library', native_control.native_library]
    arguments += (['--cell', 'Diamond,8,0.4'] if mode == 'fixed' else
                  ['--nodes', 'Diamond:4,8:0.4'])
    assert cli.run(arguments) == 0 and observed
    assert observed[-1].run_status['converged']
    assert source.read_bytes() == before
    workbook = openpyxl.load_workbook(output, read_only=True, data_only=True)
    try:
        summary = list(workbook['构型汇总'].values)
        feasibility = summary[0].index('可行')
        assert [row[feasibility] for row in summary[1:]] == (
            ['是'] if mode == 'fixed' else ['否', '是'])
        detail = list(workbook['工况明细'].values)
        assert len(detail) == 2  # Only the completed feasible design has case evidence.
        assert native_control.native_library not in str(summary + detail)
    finally:
        workbook.close()


@pytest.mark.parametrize('termination', ['completed', 'host_cancel', 'qt_cancel', 'callback_error'])
def test_real_qt_worker_native_sizing_and_terminal_signals(native_control, tmp_path, termination):
    source = tmp_path / 'spec.csv'
    source.write_text(
        'case,hot_fluid,T_in_h_K,P_in_h_kPa,mdot_h,cold_fluid,T_in_c_K,P_in_c_kPa,'
        'mdot_c,Q_kW,dPlim_h,dPlim_c\n'
        '1,air,688.23,1088.7,0.2855,water,320,200,0.5,0.03,0.00002,0.05\n')
    # Keep a fresh import boundary: the numerical comparison tests above load
    # Python kernels, while the real Qt worker must not import those kernels.
    code = '''
import json
import math
import sys
from threading import Event, get_ident
import time
from unittest.mock import patch

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.solvers import api
from sjtu_tpmshx.ui.quick_design_panel import _make_worker_class

app = QApplication(['native-qd-worker', '-platform', 'offscreen'])
source, library, termination = sys.argv[1:]
main_thread = get_ident()
progress, callback_threads, calls, native_results = [], [], [], []
stop = Event()

class Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.results, self.errors, self.threads = [], [], []
        self.cancel_count, self.finished_count = 0, 0

    @Slot(object)
    def result(self, value):
        self.threads.append(get_ident())
        self.results.append(value)

    @Slot(str)
    def error(self, value):
        self.threads.append(get_ident())
        self.errors.append(value)

    @Slot()
    def cancelled(self):
        self.threads.append(get_ident())
        self.cancel_count += 1

    @Slot()
    def finished(self):
        self.threads.append(get_ident())
        self.finished_count += 1

def report(percent):
    progress.append(percent)
    callback_threads.append(get_ident())
    # Enter a real native numerical chunk before requesting either kind of
    # cancellation or raising through the ctypes callback error boundary.
    if percent > 0:
        if termination == 'host_cancel':
            stop.set()
        elif termination == 'qt_cancel':
            worker.requestInterruption()
        elif termination == 'callback_error':
            raise LookupError('native Qt progress failed')

control = RunControl(backend='cpp', native_library=library,
                     progress=report, cancel_check=stop.is_set)
params = dict(file=source, mode='fixed', cell=('Diamond', 8., .4),
              arrangement='cross', rho_s=7900., k_s=16., prop_model='const',
              height=None, refine=False)
worker = _make_worker_class()(params, control=control)
receiver = Receiver()
worker.finished_with_result.connect(receiver.result)
worker.error_signal.connect(receiver.error)
worker.cancelled.connect(receiver.cancelled)
worker.finished.connect(receiver.finished)
original_run = api.run_case

def traced_run(case, control):
    calls.append(dict(backend=control.backend, library=control.native_library,
                      thread=get_ident()))
    result = original_run(case, control)
    native_results.append(result)
    assert result.backend_id == 'cpp'
    return result

with patch.object(api, 'run_case', traced_run):
    worker.start()
    deadline = time.monotonic() + 50
    while not receiver.finished_count and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    worker.requestInterruption()
    assert worker.wait(5000), 'native Qt worker did not exit after interruption'
    app.processEvents()

assert receiver.finished_count == 1
assert calls and all(c['backend'] == 'cpp' and c['library'] == library for c in calls)
assert all(c['thread'] != main_thread for c in calls)
assert progress and max(progress) > 0
assert all(t != main_thread for t in callback_threads)
assert receiver.threads and all(t == main_thread for t in receiver.threads)
if termination == 'callback_error':
    assert receiver.errors == ['LookupError: native Qt progress failed'], receiver.errors
    assert not receiver.results and receiver.cancel_count == 0
elif termination in ('host_cancel', 'qt_cancel'):
    assert not receiver.errors and receiver.cancel_count == 1
    result, = receiver.results
    assert result['termination_reason'] == 'cancelled' and result['partial']
    assert result['all'] == [] and result['best'] is None
else:
    assert not receiver.errors and receiver.cancel_count == 0
    result, = receiver.results
    assert result['termination_reason'] == 'completed' and not result['partial']
    assert len(result['all']) == 1 and result['all'] == result['feasible']
    best = result['best']
    assert best is result['all'][0] and best.feasible
    assert native_results and native_results[-1].run_status['converged']
    assert native_results[-1].metadata['native']['capability'] == 'quick_design_v1'
    assert all(math.isfinite(row['Q_W']) and row['Q_W'] >= 30 for row in best.percase)

forbidden = ('numba', 'sjtu_tpmshx.solvers.ltne_', 'sjtu_tpmshx.solvers.simple_',
             'sjtu_tpmshx.solvers._kernels', 'sjtu_tpmshx.solvers.backends.python.quick_design')
assert not [name for name in sys.modules if name.startswith(forbidden)]
print('QD_QT_RESULT=' + json.dumps(dict(termination=termination, native_calls=len(calls),
    completed_native_calls=len(native_results), progress_count=len(progress),
    terminal_results=len(receiver.results), errors=receiver.errors,
    cancelled=receiver.cancel_count, finished=receiver.finished_count, no_numba=True,
    selected_Q_W=([float(row['Q_W']) for row in result['best'].percase]
                  if termination == 'completed' else []))))
'''
    process = subprocess.run([sys.executable, '-c', code, str(source),
                              native_control.native_library, termination],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    report = next(line.removeprefix('QD_QT_RESULT=') for line in process.stdout.splitlines()
                  if line.startswith('QD_QT_RESULT='))
    report = json.loads(report)
    assert report['termination'] == termination and report['no_numba']
    assert report['native_calls'] > 0 and report['finished'] == 1
    print('QD_QT_RESULT=' + json.dumps(report, sort_keys=True))
