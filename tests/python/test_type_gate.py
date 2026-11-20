"""Keep the selected public interfaces and data contracts type-checked.

The explicit file list and scoped function-body checks live in pyproject.toml.
This is not a strict whole-solver type gate.
Each process has a separate cache for concurrent tests.
"""
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def test_mypy_core_surface_clean(tmp_path):
    # Use the repository root to keep package names consistent.
    r = subprocess.run(
        [sys.executable, '-m', 'engineering.scripts.check_types',
         '--cache-dir', str(tmp_path / 'mypy')],
        capture_output=True, text=True, timeout=600, cwd=str(_REPO))
    assert r.returncode == 0, "mypy findings:\n" + r.stdout[-2000:] + r.stderr[-2000:]
