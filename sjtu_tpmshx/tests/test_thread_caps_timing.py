"""Thread-cap helper behavior and a lightweight spawn entry point.

The cap module stays light and the synthetic spawn script applies its caps
before importing NumPy. A production entry point may import NumPy while the
spawned process loads its main module, before the initializer runs.
test_tool_handoffs checks the production executor's initializer and context.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_cap_module_is_light():
    """Importing _thread_caps must not drag in numpy (its entire purpose)."""
    r = subprocess.run(
        [sys.executable, '-c',
         "import sys; import sjtu_tpmshx.optimization._thread_caps; "
         "sys.exit(1 if 'numpy' in sys.modules else 0)"],
        capture_output=True, text=True, timeout=120, cwd=str(REPO))
    assert r.returncode == 0, (
        "_thread_caps import pulled numpy into the process:\n" + r.stderr[-400:])


def test_initializer_caps_before_numpy_in_real_spawn_pool(tmp_path):
    """The lightweight script defers NumPy until after its initializer.

    This checks the helper in a real child, not production-entry import order.
    """
    script = tmp_path / "spawn_probe.py"
    script.write_text(textwrap.dedent("""
        import os
        import sys
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing as mp

        from sjtu_tpmshx.optimization._thread_caps import set_worker_thread_caps

        def probe_initializer():
            # Runs in the child. numpy must NOT be loaded yet.
            os.environ['_PROBE_NUMPY_PRELOADED'] = (
                '1' if 'numpy' in sys.modules else '0')
            set_worker_thread_caps()

        def probe_task():
            import numpy  # noqa: F401  (the heavy import, AFTER the caps)
            return (os.environ.get('_PROBE_NUMPY_PRELOADED'),
                    os.environ.get('OPENBLAS_NUM_THREADS'),
                    os.environ.get('NUMBA_NUM_THREADS'))

        if __name__ == '__main__':
            ctx = mp.get_context('spawn')
            with ProcessPoolExecutor(max_workers=1, mp_context=ctx,
                                     initializer=probe_initializer) as ex:
                pre, blas, numba_n = ex.submit(probe_task).result(timeout=180)
            print(f"RESULT pre={pre} blas={blas} numba={numba_n}")
    """), encoding='utf-8')
    env = dict(os.environ)
    env.pop('OPENBLAS_NUM_THREADS', None)
    env.pop('NUMBA_NUM_THREADS', None)
    r = subprocess.run([sys.executable, str(script)], capture_output=True,
                       text=True, timeout=300, cwd=str(REPO), env=env)
    assert r.returncode == 0, r.stderr[-600:]
    line = [ln for ln in r.stdout.splitlines() if ln.startswith('RESULT')][-1]
    assert line == "RESULT pre=0 blas=1 numba=1", (
        f"timing contract broken: {line!r} (pre=1 means numpy beat the "
        "initializer into the child; blas/numba != 1 means caps not set)")


def test_caps_hard_set_and_escape_hatch(monkeypatch):
    from sjtu_tpmshx.optimization._thread_caps import set_worker_thread_caps
    # The worker initializer writes every cap directly; isolate those writes
    # from the already-initialized Numba pool in this pytest process.
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    monkeypatch.setenv('OMP_NUM_THREADS', '8')   # stray shell export
    monkeypatch.delenv('TPMSHX_WORKER_THREADS', raising=False)
    set_worker_thread_caps()
    assert os.environ['OMP_NUM_THREADS'] == '1', "guard must beat stray env"
    assert os.environ['NUMBA_NUM_THREADS'] == '1'
    monkeypatch.setenv('TPMSHX_WORKER_THREADS', '4')
    set_worker_thread_caps()
    assert os.environ['OMP_NUM_THREADS'] == '4', "explicit hatch must win"
    monkeypatch.setenv('TPMSHX_WORKER_THREADS', 'garbage')
    set_worker_thread_caps()
    assert os.environ['OMP_NUM_THREADS'] == '1', "garbage hatch falls back"
