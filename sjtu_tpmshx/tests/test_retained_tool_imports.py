"""Retained validation and profiling entry points use the current package layout."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = sorted([
    ROOT / 'sjtu_tpmshx/validation/cases/validate_sco2_d76.py',
    *ROOT.glob('benchmarks/profiling/*.py'),
])


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.name)
def test_retained_entry_imports_from_repository_root(script):
    # Entry points run from the repository root, without a PYTHONPATH bootstrap.
    code = 'import runpy, sys; from pathlib import Path; p = Path(sys.argv[1]); '
    code += "runpy.run_path(str(p), run_name='__tm1_import_smoke__')"
    # Do not let conftest's child-process bootstrap hide a broken script entry.
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-c', code, str(script)], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
