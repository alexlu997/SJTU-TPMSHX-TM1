"""A/B concurrency must not overlap Numba parallel sweep regions."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers import simple_solver_3d as simple
from sjtu_tpmshx.solvers.backends.python.three_d import runtime


@pytest.mark.parametrize('sizes', [(99, 99), (100, 99), (99, 100)])
def test_pair_uses_one_parallel_level(monkeypatch, sizes):
    monkeypatch.setattr(simple, '_PARALLEL_CELL_THRESHOLD', 100)
    parent = threading.current_thread()
    barrier = threading.Barrier(2)
    visits = []
    sequential = max(sizes) >= 100
    cancel = lambda: False

    def solve(side, **kwargs):
        visits.append((side, threading.current_thread()))
        assert kwargs == dict(max_iter=7, tol=0.02, verbose=False, cancel_check=cancel)
        if not sequential:
            barrier.wait(timeout=5)
        return True, side + 1

    sides = [SimpleNamespace(Nx=n, Ny=1, Nz=1,
                             solve=lambda side=i, **kw: solve(side, **kw))
             for i, n in enumerate(sizes)]
    assert runtime._run_two_simple(*sides, max_iter=7, tol=0.02,
                                   cancel_check=cancel) == [(True, 1), (True, 2)]
    if sequential:
        assert visits == [(0, parent), (1, parent)]
    else:
        assert all(thread is not parent and not thread.is_alive() for _, thread in visits)


@pytest.mark.parametrize('failure_side', [0, 1])
def test_sequential_pair_preserves_failure_over_cancellation(monkeypatch, failure_side):
    monkeypatch.setattr(simple, '_PARALLEL_CELL_THRESHOLD', 1)
    failure = ValueError('solver failed')
    visits = []

    def solve(side, **kwargs):
        visits.append(side)
        if side == failure_side:
            raise failure
        raise CancelledError('cancelled')

    sides = [SimpleNamespace(Nx=2, Ny=2, Nz=2,
                             solve=lambda side=i, **kw: solve(side, **kw)) for i in range(2)]
    with pytest.raises(ValueError) as caught:
        runtime._run_two_simple(*sides)
    assert caught.value is failure
    assert visits == [0, 1]


@pytest.mark.parametrize('threads', [1, 2])
def test_real_workqueue_sweeps_in_child_process(threads):
    # Force the actual large-grid dispatch on a small physical solver. A native
    # workqueue abort stays in the child and is a test failure on either OS.
    script = '''
import threading
import numba
import numpy as np
from sjtu_tpmshx.solvers import simple_solver_3d as simple
from sjtu_tpmshx.solvers.backends.python.three_d.runtime import _run_two_simple

assert numba.threading_layer() == 'workqueue'
assert simple._should_parallelize(8, 12, 4)
parent = threading.current_thread()
calls = []
original = simple._sweep_u_jit_df_3d_parallel
def sweep(*args):
    assert threading.current_thread() is parent
    calls.append(numba.get_num_threads())
    return original(*args)
simple._sweep_u_jit_df_3d_parallel = sweep

def make(water):
    return simple.SIMPLESolver3D(
        Lx=.02, Ly=.03, Lz=.01, Nx=8, Ny=12, Nz=4,
        rho=998. if water else 1.18, mu=.001 if water else 1.85e-5,
        T_in=300., v_inlet=.01 if water else 3., eps=.72,
        K_arr=np.full((12, 4), 3e-8), cF_arr=np.full((12, 4), 250.),
        fluid_type='incompressible' if water else 'ideal_gas')

sides = [make(False), make(True)]
paired = _run_two_simple(*sides, max_iter=3)
assert len(calls) >= 6
assert set(calls) == {numba.get_num_threads()}
for s, water, result in zip(sides, (False, True), paired):
    reference = make(water)
    assert reference.solve(max_iter=3, verbose=False) == result
    for name in ('u', 'v', 'w', 'P', 'rho_field'):
        np.testing.assert_allclose(getattr(s, name), getattr(reference, name),
                                   rtol=1e-12, atol=1e-12)
print('workqueue pair and direct sequential fields agree')
'''
    env = dict(os.environ, NUMBA_THREADING_LAYER='workqueue',
               NUMBA_NUM_THREADS=str(threads), TPMSHX_PARALLEL_THRESHOLD='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    completed = subprocess.run([sys.executable, '-c', script],
                               cwd=Path(__file__).resolve().parents[2], env=env,
                               capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert 'workqueue pair and direct sequential fields agree' in completed.stdout
