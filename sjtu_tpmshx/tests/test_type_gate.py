"""Keep the selected public interfaces and data contracts type-checked.

The explicit scope lives in mypy-core-files.txt, with scoped function-body
checks in pyproject.toml. This is not a strict whole-solver type gate.
"""
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / 'sjtu_tpmshx'


def test_mypy_core_surface_clean():
    # P1.8b F2: repo-root basis — core files are package-style now, so
    # module names resolve as sjtu_tpmshx.* (explicit_package_bases + cwd).
    r = subprocess.run(
        [sys.executable, '-m', 'mypy', '@mypy-core-files.txt',
         '--config-file', 'pyproject.toml'],
        capture_output=True, text=True, timeout=600, cwd=str(_REPO))
    assert r.returncode == 0, "mypy findings:\n" + r.stdout[-2000:]


def test_public_module_inputs_reject_wrong_types():
    source = '''
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate

prepare_case("not a config", case_id="type-check")
run_case("not a prepared case")
evaluate("not a native result")
'''
    result = subprocess.run(
        [sys.executable, '-m', 'mypy', '-c', source,
         '--config-file', 'pyproject.toml'],
        capture_output=True, text=True, timeout=600, cwd=str(_REPO))
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count('[arg-type]') == 3, result.stdout
