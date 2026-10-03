"""Actual linked SuperLU allocation/ABORT cleanup and in-process recovery.

The executable fails each allocation ordinal observed during a real successful
factorization, then solves normally in the same process after every failure.
The failure ledger is C-thread-local; no Python callback or C++ object is inside
the C setjmp/longjmp region. ASan/UBSan qualification is a separate build lane.
"""
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope='module')
def superlu_error_executable():
    root = Path(__file__).resolve().parents[3]
    platform = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    default = root / '.cache' / 'native-deps' / 'build' / ('pilot-' + platform) / (
        'superlu_error_smoke.exe' if os.name == 'nt' else 'superlu_error_smoke')
    executable = Path(os.environ.get('TPMSHX_SUPERLU_ERROR_EXE', str(default)))
    if not executable.is_file():
        message = 'native SuperLU error-boundary executable is unavailable: ' + str(executable)
        if ('TPMSHX_SUPERLU_ERROR_EXE' in os.environ
                or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1'):
            pytest.fail(message)
        pytest.skip(message)
    return executable


def run_case(executable, name, storage):
    # The executable and libraries must work without a Python/venv search path.
    # Keep sanitizer settings when the caller selected an instrumented binary.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV', 'DYLD'))}
    if os.name != 'nt':
        environment['PATH'] = '/usr/bin:/bin'
    completed = subprocess.run([str(executable), '--case', name, '--format', storage], text=True,
                               capture_output=True, timeout=60, env=environment)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    row = json.loads(completed.stdout)
    assert row['status'] == 'passed' and row['case'] == name and row['format'] == storage
    assert row['outstanding_blocks'] == 0 and row['outstanding_bytes'] == 0
    return row


@pytest.mark.parametrize('storage', ['csc', 'csr'])
def test_every_observed_allocation_failure_cleans_and_recovers(superlu_error_executable, storage):
    row = run_case(superlu_error_executable, 'allocations', storage)
    assert row['failpoints'] > 0 and row['recovered'] == row['failpoints']
    assert row['peak_bytes'] > 0
    assert row['maximum_error'] <= 1e-12 and row['relative_residual'] <= 1e-12


@pytest.mark.parametrize('storage', ['csc', 'csr'])
def test_real_abort_macro_and_long_file_messages_are_bounded(superlu_error_executable, storage):
    row = run_case(superlu_error_executable, 'aborts', storage)
    assert row['aborts'] == row['recovered'] == 3
    assert row['truncated'] == 2


@pytest.mark.parametrize('storage', ['csc', 'csr'])
def test_singular_info_is_preserved_and_next_solve_recovers(superlu_error_executable, storage):
    row = run_case(superlu_error_executable, 'singular', storage)
    assert 0 < row['superlu_info'] <= 3 and row['recovered'] == 1


@pytest.mark.parametrize('storage', ['csc', 'csr'])
def test_two_native_threads_isolate_failure_state(superlu_error_executable, storage):
    row = run_case(superlu_error_executable, 'concurrent', storage)
    assert row['threads'] == 2 and row['rounds'] == 40
    assert row['successes'] == row['faults'] == row['rounds']
