"""Isolated pressure candidate: fixed equations and original-residual gates.

The native executable owns no production solver binding. Direct LU compares
at rtol=1e-10/atol=1e-12 Pa, with original relative residual <=1e-10.
AMG ports locked PyAMG 5.3 modified classical interpolation, symmetric GS,
and pseudo-inverse, plus the SciPy 1.17.1 BiCGStab sequence. It retains 200
iterations per attempt, the original breakdown retry and rtol in [1e-7,1e-3].
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, bicgstab, spsolve


@pytest.fixture(scope='module')
def pressure_executable():
    root = Path(__file__).resolve().parents[3]
    platform = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    default = root / '.cache' / 'native-deps' / 'build' / ('pilot-' + platform) / (
        'pressure_smoke.exe' if os.name == 'nt' else 'pressure_smoke')
    executable = Path(os.environ.get('TPMSHX_NATIVE_PRESSURE_EXE', str(default)))
    if not executable.is_file():
        message = 'native pressure candidate executable is unavailable: ' + str(executable)
        if ('TPMSHX_NATIVE_PRESSURE_EXE' in os.environ
                or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1'):
            pytest.fail(message)
        pytest.skip(message)
    return executable


def request(matrix, rhs, pins, *, dimension=3, rtol=1e-7, rebuild=False, drift=.05):
    matrix = sparse.csr_matrix(matrix)
    return dict(dimension=dimension, n=matrix.shape[0], ptr=matrix.indptr.copy(),
                col=matrix.indices.copy(), val=matrix.data.copy(),
                rhs=np.asarray(rhs, dtype=float).copy(), pins=np.asarray(pins, dtype=int).copy(),
                rtol=rtol, rebuild=rebuild, drift=drift)


def encode(job):
    # 17 significant digits preserve the input doubles; no hidden rescaling.
    parts = ['TM1_PRESSURE_V1', str(job['dimension']), str(job['n']), str(len(job['val'])),
             format(job['rtol'], '.17g'), str(int(job['rebuild'])), format(job['drift'], '.17g')]
    for name in ('ptr', 'col', 'val', 'rhs', 'pins'):
        parts.extend(format(x, '.17g') for x in job[name])
    return ' '.join(parts) + '\n'


def run_requests(executable, jobs):
    completed = subprocess.run([str(executable), '--stream'], input=''.join(map(encode,jobs)),
                               text=True, capture_output=True, timeout=60)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    rows = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(rows) == len(jobs), completed.stdout
    return rows


def manufactured(n=2001):
    matrix = sparse.diags((-np.ones(n-1), np.full(n,4.), -np.ones(n-1)), (-1,0,1), format='lil')
    matrix[0,:] = 0.; matrix[0,0] = 1.
    matrix = matrix.tocsr()
    expected = (np.arange(n) % 17) * .125
    pins = np.zeros(n, dtype=int); pins[0] = 1
    return matrix, expected, pins


def verify(job, result, expected, *, direct=False, scale=1.):
    assert result['status'] == 'solved', result
    matrix = sparse.csr_matrix((job['val'],job['col'],job['ptr']), shape=(job['n'],job['n']))
    x = np.asarray(result['x'])
    # Independently evaluate the ORIGINAL CSR rows, including unmodified pins.
    residual = np.array([sum(job['val'][k] * x[job['col'][k]]
                            for k in range(job['ptr'][i],job['ptr'][i+1])) - job['rhs'][i]
                         for i in range(job['n'])])
    bnorm = np.linalg.norm(job['rhs'])
    relative = np.linalg.norm(residual) / bnorm if bnorm else np.linalg.norm(residual)
    assert relative <= (1e-10 if direct else job['rtol'])
    assert result['relative_residual'] == pytest.approx(relative, rel=1e-5, abs=1e-14)
    assert np.max(np.abs(x[job['pins'].astype(bool)])) <= 1e-10
    if direct:
        np.testing.assert_allclose(x, expected, rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(x, spsolve(matrix,job['rhs']), rtol=1e-10, atol=1e-12)
    else:
        assert np.max(np.abs(x/scale-expected)) <= 1e-7
        assert result['iterations'] <= 200


def test_standalone_known_equations_and_tiny_rhs(pressure_executable):
    completed = subprocess.run([str(pressure_executable)], text=True, capture_output=True, timeout=60)
    assert completed.returncode == 0, (completed.stdout,completed.stderr)
    assert json.loads(completed.stdout)['status'] == 'passed'


@pytest.mark.parametrize('dimension,n,method', [
    (2,2001,'superlu_colamd'), (3,2000,'superlu_colamd'), (3,2001,'pyamg_classical_bicgstab')])
def test_dimension_and_exact_2000_cell_switch(pressure_executable, dimension, n, method):
    matrix, expected, pins = manufactured(n)
    job = request(matrix,matrix @ expected,pins,dimension=dimension)
    result, = run_requests(pressure_executable,[job])
    assert result['method'] == method
    verify(job,result,expected,direct=method == 'superlu_colamd')


@pytest.mark.parametrize('rtol', [1e-3,1e-7])
def test_nonzero_small_rhs_and_zero_rhs_are_distinct(pressure_executable, rtol):
    matrix, expected, pins = manufactured()
    jobs = [request(matrix,scale*(matrix @ expected),pins,rtol=rtol) for scale in (1.,1e-30,0.)]
    # Both nonzero problems have the same normalized solve. At the loose
    # tolerance, compare those solutions rather than assert a tighter x gate.
    rows = run_requests(pressure_executable,jobs)
    for job,result in zip(jobs,rows):
        assert result['status'] == 'solved' and result['method'] == 'pyamg_classical_bicgstab'
        x = np.asarray(result['x'])
        residual = matrix @ x - job['rhs']
        scale = np.linalg.norm(job['rhs'])
        assert (np.linalg.norm(residual)/scale if scale else np.linalg.norm(residual)) <= rtol
        assert result['pin_max_abs'] <= 1e-10 and result['rebuild_count'] == 1
    assert rows[1]['rhs_scale'] > 0. and rows[1]['amg_exit'] == 'solved'
    np.testing.assert_allclose(np.asarray(rows[1]['x'])/1e-30, rows[0]['x'], rtol=1e-10, atol=1e-12)
    assert rows[2]['amg_exit'] == 'zero_rhs' and rows[2]['iterations'] == 0
    np.testing.assert_array_equal(rows[2]['x'],np.zeros(matrix.shape[0]))


def test_current_matrix_reuse_diagonal_drift_pattern_and_cadence(pressure_executable):
    matrix, expected, pins = manufactured()
    different = matrix.copy()
    # A changed off-diagonal must affect matvec even though diagonal drift=0.
    for row in range(1,matrix.shape[0]):
        start, end = different.indptr[row:row+2]
        for k in range(start,end):
            if different.indices[k] != row: different.data[k] *= .6
    drifted = different.copy()
    for row in range(1,matrix.shape[0]):
        start, end = drifted.indptr[row:row+2]
        drifted.data[start:end][drifted.indices[start:end] == row] *= 1.06
    pattern = drifted.copy().tolil()
    pattern[-1,1] = -.125
    pattern = pattern.tocsr(); pattern.sort_indices()
    jobs = [request(a,a @ expected,pins,rebuild=force)
            for a,force in ((matrix,False),(different,False),(drifted,False),(pattern,False),(pattern,True))]
    rows = run_requests(pressure_executable,jobs)
    assert [r['rebuild_reason'] for r in rows] == [
        'cold','','active_diagonal_drift','pattern_or_pins_changed','caller_cadence']
    assert [r['rebuild_count'] for r in rows] == [1,1,2,3,4]
    assert rows[1]['diagonal_drift'] == 0.
    assert rows[2]['diagonal_drift'] == pytest.approx(.06)
    for job,row in zip(jobs,rows):
        assert row['method'] == 'pyamg_classical_bicgstab'
        verify(job,row,expected)


@pytest.mark.parametrize('bad', ['ptr','column','duplicate','nan_matrix','nan_rhs','pin_row','pin_rhs','no_pin','rtol'])
def test_invalid_inputs_are_reported_before_c_solver(pressure_executable,bad):
    matrix, expected, pins = manufactured(4)
    job = request(matrix,matrix @ expected,pins,dimension=2)
    if bad == 'ptr': job['ptr'][-1] -= 1
    elif bad == 'column': job['col'][-1] = 9
    elif bad == 'duplicate': job['col'][2] = job['col'][1]
    elif bad == 'nan_matrix': job['val'][1] = np.nan
    elif bad == 'nan_rhs': job['rhs'][1] = np.nan
    elif bad == 'pin_row': job['val'][0] = 2.
    elif bad == 'pin_rhs': job['rhs'][0] = 1.
    elif bad == 'no_pin': job['pins'][:] = 0
    elif bad == 'rtol': job['rtol'] = 1e-8
    row, = run_requests(pressure_executable,[job])
    assert row['status'] == 'invalid_input' and row['detail']
    assert 'x' not in row


def test_singular_lu_is_a_failure_with_no_solution(pressure_executable):
    matrix = sparse.csr_matrix([[1.,0.,0.],[0.,1.,1.],[0.,1.,1.]])
    job = request(matrix,[0.,1.,2.],[1,0,0],dimension=2)
    row, = run_requests(pressure_executable,[job])
    assert row['status'] == 'linear_failure' and row['exit'] == 'singular'
    assert 0 < row['superlu_info'] <= 3 and row['x'] == []
    assert row['relative_residual'] is None


def test_original_breakdown_retry_uses_lu_and_audits_original_equations(pressure_executable):
    # A nonsingular indefinite tridiagonal, with a physical-format unit pin.
    # This is a manufactured failure-path case, not a production PPE sample.
    # No artificial iteration limit or injected backend failure is used.
    n = 2001
    matrix = sparse.diags((-np.ones(n-1),np.full(n,1.001),-np.ones(n-1)),
                          (-1,0,1),format='lil')
    matrix[0,:] = 0.; matrix[0,0] = 1.
    matrix = matrix.tocsr()
    expected = np.sin(np.arange(n)*.17); expected[0] = 0.
    pins = np.zeros(n,dtype=int); pins[0] = 1
    job = request(matrix,matrix @ expected,pins)
    import pyamg
    hierarchy = pyamg.ruge_stuben_solver(matrix, max_coarse=200)
    preconditioner = hierarchy.aspreconditioner(cycle='V')
    _, first_info = bicgstab(matrix, job['rhs'], M=preconditioner, rtol=job['rtol'], maxiter=200)
    _, retry_info = bicgstab(matrix, job['rhs']/np.linalg.norm(job['rhs']),
                            M=preconditioner, rtol=job['rtol'], maxiter=200)
    # The original locked algorithm breaks down on both real attempts here;
    # the retired AMGCL candidate instead exhausted 200 iterations.
    assert first_info == retry_info == -11
    result, = run_requests(pressure_executable,[job])
    assert result['method'] == 'superlu_after_amg'
    assert result['amg_exit'] == 'breakdown'
    assert result['rhs_scale'] == pytest.approx(np.linalg.norm(job['rhs']))
    assert result['detail'].endswith('info=-11')
    assert result['iterative_relative_residual'] > job['rtol']
    assert result['superlu_info'] == 0
    verify(job,result,expected,direct=True)


def test_failed_request_does_not_poison_existing_hierarchy(pressure_executable):
    matrix, expected, pins = manufactured()
    job = request(matrix,matrix @ expected,pins)
    invalid = deepcopy(job); invalid['val'][1] = np.nan
    first, bad, last = run_requests(pressure_executable,[job,invalid,job])
    assert bad['status'] == 'invalid_input'
    assert first['rebuild_count'] == last['rebuild_count'] == 1
    assert last['rebuild_reason'] == ''
    verify(job,last,expected)


@pytest.mark.parametrize('rtol', [1e-3, 1e-7])
def test_original_classical_algorithm_current_matrix_and_breakdown_retry(pressure_executable, rtol):
    import pyamg

    # A three-dimensional seven-point operator crosses the real AMG gate;
    # one full outlet plane uses the original unprojected unit-row pins.
    shape = (13, 14, 12)
    matrix = pyamg.gallery.poisson(shape, format='lil')
    pins = np.zeros(np.prod(shape), dtype=int)
    pins.reshape(shape)[:, -1, :] = 1
    for row in np.flatnonzero(pins):
        matrix.rows[row] = [int(row)]
        matrix.data[row] = [1.]
    matrix = matrix.tocsr()
    target = np.sin(np.arange(matrix.shape[0])*.013)
    target[pins.astype(bool)] = 0.
    changed = matrix.copy()
    for row in np.flatnonzero(~pins.astype(bool)):
        start, end = changed.indptr[row:row+2]
        changed.data[start:end][changed.indices[start:end] != row] *= .97
    jobs = [request(a, scale*(a @ target), pins, rtol=rtol)
            for a, scale in ((matrix, 1.), (changed, 1.), (changed, 1e-30))]
    rows = run_requests(pressure_executable, jobs)
    hierarchy = pyamg.ruge_stuben_solver(matrix, max_coarse=200)
    preconditioner = hierarchy.aspreconditioner(cycle='V')
    for job, actual in zip(jobs, rows):
        a = sparse.csr_matrix((job['val'], job['col'], job['ptr']), shape=matrix.shape)
        calls = 0

        def apply(x):
            nonlocal calls
            calls += 1
            return preconditioner @ x

        m = LinearOperator(a.shape, matvec=apply, dtype=np.float64)
        expected, info = bicgstab(a, job['rhs'], M=m, rtol=rtol, maxiter=200)
        first_calls = calls
        rescaled = info < 0
        if rescaled:
            calls = 0
            scale = np.linalg.norm(job['rhs'])
            expected, info = bicgstab(a, job['rhs']/scale, M=m, rtol=rtol, maxiter=200)
            expected *= scale
        assert info == 0
        assert actual['method'] == 'pyamg_classical_bicgstab' and actual['amg_exit'] == 'solved'
        assert actual['iterations'] == ((first_calls+1)//2 + (calls+1)//2 if rescaled else (calls+1)//2)
        assert actual['rebuild_count'] == 1
        assert actual['rhs_scale'] == pytest.approx(np.linalg.norm(job['rhs']) if rescaled else 1.)
        solution_scale = 1e-30 if rescaled else 1.
        np.testing.assert_allclose(np.asarray(actual['x'])/solution_scale, expected/solution_scale,
                                   rtol=2e-10, atol=2e-11)
        if sys.platform == 'darwin' and not rescaled:
            # These source-wheel kernels/BLAS operations feed a sensitive
            # nonlinear outer solve; the macOS path preserves their rounding.
            np.testing.assert_array_equal(actual['x'], expected)
        assert actual['relative_residual'] <= rtol
        np.testing.assert_array_equal(np.asarray(actual['x'])[pins.astype(bool)], 0.)
